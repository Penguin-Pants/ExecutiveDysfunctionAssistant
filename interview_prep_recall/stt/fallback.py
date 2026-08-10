"""Automatic cloud→local fallback and the egress indicator (T8.4/T8.5 — FR20, FR21).

Two responsibilities that look separable and are not. The moment the active backend
stops being the cloud one is exactly the moment the "audio is leaving this device"
indicator must go out, and a design that updates them from two places will eventually
show the indicator lit while everything runs locally — or, far worse, dark while audio
still streams to a vendor. Ownership is therefore single: whoever switches the backend
also sets the flag, in that order, in one method.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from interview_prep_recall.diagnostics.ring import DiagnosticRing
from interview_prep_recall.session.health import Egress, HealthMonitor
from interview_prep_recall.stt.interface import (
    OnState,
    OnTranscript,
    StateEvent,
    SttBackend,
    SttStreamState,
)

FALLBACK_NOTICE = "Cloud transcription dropped — switched to local"
"""FR21's "brief notice". Surfaced through a state event so it reaches the same
indicator path as every other stream state rather than needing its own channel."""


class EgressMonitor:
    """The single owner of FR20's indicator.

    `Egress.of` already distinguishes the two paths; this holds the two booleans that
    feed it so no caller has to reconstruct the combined value. Independently settable
    and independently reported, because FR20 requires the cloud-STT path and the LLM
    path to be distinguishable — "something is leaving" is not the requirement.
    """

    def __init__(self, monitor: HealthMonitor | None = None) -> None:
        self.monitor = HealthMonitor() if monitor is None else monitor
        self._cloud_stt = False
        self._llm = False
        self._lock = threading.Lock()

    @property
    def egress(self) -> Egress:
        return Egress.of(cloud_stt=self._cloud_stt, llm=self._llm)

    def set_cloud_stt(self, active: bool) -> Egress:
        with self._lock:
            self._cloud_stt = active
            return self._publish()

    def set_llm(self, active: bool) -> Egress:
        with self._lock:
            self._llm = active
            return self._publish()

    def _publish(self) -> Egress:
        egress = self.egress
        self.monitor.update(egress=egress)
        return egress


class FallbackSttBackend:
    """Runs a primary backend, switching to a local one when it fails (FR21).

    Satisfies `SttBackend` itself, so the session wires one object and never learns
    which backend is live. That indirection is what lets FR18's "cloud is opt-in"
    and FR21's "fall back automatically" coexist without the caller branching.

    **Frames in flight during the switch are lost, and this is deliberate.** Replaying
    the buffered tail into the local backend would double-transcribe the overlap, and a
    duplicated question is worse than a missing half-second: the assembler would build
    two utterances from one span and matching would fire twice on the same question.
    The gap is reported as DEGRADED rather than hidden.
    """

    def __init__(
        self,
        primary: SttBackend,
        local_factory: Callable[[], SttBackend],
        *,
        egress: EgressMonitor | None = None,
        ring: DiagnosticRing | None = None,
    ) -> None:
        self._primary = primary
        self._local_factory = local_factory
        self._active: SttBackend = primary
        self._local: SttBackend | None = None
        self.egress = EgressMonitor() if egress is None else egress
        self.ring = DiagnosticRing() if ring is None else ring

        self._stream_id = ""
        self._sample_rate = 0
        self._channels = 0
        self._on_transcript: OnTranscript | None = None
        self._on_state: OnState | None = None
        self._switching = False
        self._switch_complete = threading.Event()
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return self._active.name

    @property
    def supports_interim(self) -> bool:
        """Follows the active backend, rather than being fixed at construction.

        A hardcoded value would be a lie for half the session's duration: the cloud
        primary emits interims and the local fallback does not. Consumers must ignore
        interims either way (rule 3), so nothing breaks today — but a flag that reports
        the wrong backend's capability is the kind of detail a later feature builds on.
        """
        return self._active.supports_interim

    @property
    def active_backend(self) -> SttBackend:
        return self._active

    @property
    def switched(self) -> bool:
        """True only once the switch has **finished**.

        Deliberately not the re-entry guard. That flag is set at the top of `_switch()`
        so a second FAILED event cannot start a second switch, and reporting it as
        "switched" would tell callers the local backend was live and the egress
        indicator settled while both were still mid-flight.
        """
        return self._switch_complete.is_set()

    def wait_for_switch(self, timeout: float = 5.0) -> bool:
        """Blocks until fallback completes. For callers verifying FR21's 5 s bound."""
        return self._switch_complete.wait(timeout)

    # ---------- SttBackend ----------

    def start(
        self,
        stream_id: str,
        sample_rate: int,
        channels: int,
        on_transcript: OnTranscript,
        on_state: OnState,
    ) -> None:
        self._stream_id = stream_id
        self._sample_rate = sample_rate
        self._channels = channels
        self._on_transcript = on_transcript
        self._on_state = on_state
        # Lit **before** the primary starts, for two reasons.
        #
        # Ordering: the primary can fail inside `start()` — a connector that raises
        # immediately does — and the fallback then runs on the backend thread and puts
        # the indicator out. Lighting it afterwards would overwrite that, leaving it
        # claiming cloud egress for the rest of a session running entirely locally.
        #
        # Direction: this over-claims by the width of the connection handshake. That is
        # the safe error. An indicator that says "leaving the device" a moment early is
        # a cosmetic flaw; one that says "not leaving" while the socket is open is a
        # false privacy statement, which is the failure FR20 exists to prevent.
        self.egress.set_cloud_stt(True)
        self._primary.start(stream_id, sample_rate, channels, on_transcript, self._watch_state)

    def feed(self, pcm: bytes, t_capture: float) -> None:
        self._active.feed(pcm, t_capture)

    def stop(self, flush_timeout_s: float = 2.0) -> None:
        self._active.stop(flush_timeout_s)
        self.egress.set_cloud_stt(False)

    def close(self) -> None:
        # Both are closed, not just the active one: after a switch the primary's socket
        # and thread are still live, and closing only the active backend would leave a
        # cloud connection open for the rest of the process — egress the indicator has
        # already reported as finished.
        self._primary.close()
        if self._local is not None:
            self._local.close()
        self.egress.set_cloud_stt(False)

    # ---------- fallback ----------

    def _watch_state(self, event: StateEvent) -> None:
        if event.state is SttStreamState.FAILED and not self._switching:
            self._switch()
            return
        if self._on_state is not None:
            self._on_state(event)

    def _switch(self) -> None:
        with self._lock:
            if self._switching:
                return
            self._switching = True

        self.ring.record("stt_fallback", stream=self._stream_id[:64])
        try:
            self._primary.close()
        except Exception as exc:  # noqa: BLE001 — a dead primary must not block recovery
            self.ring.record("stt_fallback_close_failed", cause=type(exc).__name__)

        # Order matters: the indicator goes dark only after the cloud backend is
        # actually closed, never on the intention to close it.
        self.egress.set_cloud_stt(False)

        local = self._local_factory()
        self._local = local
        self._active = local
        assert self._on_transcript is not None
        local.start(
            self._stream_id,
            self._sample_rate,
            self._channels,
            self._on_transcript,
            self._forward_state,
        )
        self._switch_complete.set()
        if self._on_state is not None:
            self._on_state(
                StateEvent(
                    stream_id=self._stream_id,
                    state=SttStreamState.DEGRADED,
                    detail=FALLBACK_NOTICE,
                )
            )

    def _forward_state(self, event: StateEvent) -> None:
        if self._on_state is not None:
            self._on_state(event)
