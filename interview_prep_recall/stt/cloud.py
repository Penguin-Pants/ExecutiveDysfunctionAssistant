"""Shared machinery for streaming cloud STT backends (T8.1/T8.2 — FR17, FR18, FR20).

Deepgram and ElevenLabs speak different protocols but need identical plumbing: an
asyncio loop that must not escape the module (D-1), a bounded send queue that keeps
`feed()` non-blocking (contract rule 1), a finalisation guarantee the wire protocol
does not provide on its own (rule 2), and — the one that is easy to get wrong —
timestamps on the *capture* clock rather than the server's (rule 5).

**Asyncio is confined here.** The rest of the application is threads and queues. Each
backend owns one event loop on one daemon thread; nothing outside this module awaits
anything. `feed()` is called from the audio callback and only ever appends to a deque.

**Why raw `websockets` and not the vendor SDKs** (design §10): both SDKs want to own
the event loop and deliver their own event objects, which would put vendor types on
the conformance-suite boundary and defeat the point of D-2's interface. The trade is
recorded as medium risk — hand-rolling two proprietary protocols is not free — and the
mitigation is that neither backend is on the default path (FR18).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from interview_prep_recall.diagnostics.ring import DiagnosticRing
from interview_prep_recall.stt.interface import (
    FRAME_BYTES,
    OnState,
    OnTranscript,
    StateEvent,
    SttStreamState,
    TranscriptEvent,
)

FRAME_S = FRAME_BYTES / (16_000 * 2)
"""Seconds of audio in one frame: 0.02."""

MAX_QUEUED_FRAMES = 250
"""5 seconds of audio. Bounded because `feed()` may never block (rule 1) and because
nothing in this pipeline may grow with session length (FR33).

Drop-oldest rather than drop-newest: when the socket stalls, the useful audio is the
most recent speech, not the backlog. A drop is reported as DEGRADED — silently
transcribing a gap would violate rule 2's "no span is silently dropped".
"""

DROP_REPORT_EVERY = 50
"""One DEGRADED report per second of dropped audio, after the first.

A stalled socket drops every frame that arrives. Reporting each one would evict the
bounded ring's real diagnostics with repetitions of a fact already recorded.
"""

FINAL_FLUSH_TAIL_S = 1.5
"""Longest quiet wait for the server's finals after the flush request.

Also capped by the caller's `flush_timeout_s`: `close()` allows 0.5 s, and an internal
wait longer than the caller's timeout meant the join returned with the worker and socket
still live while `stop()` reported STOPPED.
"""

JOIN_GRACE_S = 0.5
"""Slack beyond the flush tail for the loop to unwind and close the socket."""

RECONNECT_ATTEMPTS = 2
RECONNECT_BACKOFF_S = 0.5


class CloudConnection(Protocol):
    """The slice of a WebSocket this module uses.

    A Protocol so the conformance suite runs against a scripted double with no socket,
    no network and no vendor account. Every rule in `SttBackend` is checkable that way;
    none of them is about the wire.
    """

    async def send(self, data: bytes | str) -> None: ...
    async def recv(self) -> bytes | str: ...
    async def close(self) -> None: ...


Connector = Callable[[], Awaitable[CloudConnection]]


class CaptureClock:
    """Maps a server-relative timestamp back onto the capture-side monotonic clock.

    Cloud backends report timestamps relative to the start of the audio *they received*.
    Contract rule 5 forbids passing those through: the consumer's utterance boundaries
    are in capture time, and cloud latency would shift every span.

    The naive fix — anchor on the first frame and add the server offset — is wrong the
    moment a frame is dropped under backpressure, because the server's stream is then
    shorter than the elapsed capture time and every subsequent timestamp drifts earlier
    by the size of the gap. So anchors record (audio actually sent, capture time) pairs
    and lookup interpolates within that, which stays correct across drops.
    """

    def __init__(self, max_anchors: int = 256) -> None:
        self._anchors: deque[tuple[float, float]] = deque(maxlen=max_anchors)
        self._sent_s = 0.0

    @property
    def sent_s(self) -> float:
        return self._sent_s

    def note_sent(self, t_capture: float, duration_s: float = FRAME_S) -> None:
        self._anchors.append((self._sent_s, t_capture))
        self._sent_s += duration_s

    def reset(self) -> None:
        """Start a new epoch. Called on every (re)connect.

        A reconnect gives the vendor a **new** stream, whose offsets restart at zero
        while `sent_s` has kept accumulating. Without this the first post-reconnect
        event maps back to the very first anchor — tens of seconds earlier — and the
        ordering guard, doing its job, then discards it and every event after it. The
        stream would go permanently silent while reporting READY, with a full test
        suite passing: this project's defect class, reached through the recovery path
        that exists to prevent an outage.
        """
        self._anchors.clear()
        self._sent_s = 0.0

    def to_capture(self, server_s: float) -> float:
        """Convert a server stream offset into capture-clock seconds."""
        if not self._anchors:
            return server_s
        best_sent, best_capture = self._anchors[0]
        for sent, capture in self._anchors:
            if sent > server_s:
                break
            best_sent, best_capture = sent, capture
        return best_capture + (server_s - best_sent)


class CloudSttBackend:
    """Base for streaming cloud backends. Subclasses supply protocol specifics only.

    Satisfies `SttBackend` structurally; the conformance suite is what proves it.
    """

    name = "cloud"
    supports_interim = True

    def __init__(
        self,
        connector: Connector,
        *,
        ring: DiagnosticRing | None = None,
        max_queued_frames: int = MAX_QUEUED_FRAMES,
        reconnect_attempts: int = RECONNECT_ATTEMPTS,
        backoff_s: float = RECONNECT_BACKOFF_S,
    ) -> None:
        self._connector = connector
        self.ring = DiagnosticRing() if ring is None else ring
        self._reconnect_attempts = reconnect_attempts
        self._backoff_s = backoff_s

        self._pending: deque[tuple[bytes, float]] = deque(maxlen=max_queued_frames)
        self._clock = CaptureClock()
        self._lock = threading.Lock()

        self._stream_id = ""
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._stopping = threading.Event()
        self._ready = threading.Event()

        self._on_transcript: OnTranscript | None = None
        self._on_state: OnState | None = None
        self._state = SttStreamState.STOPPED
        self._closed = False

        self._dropped = 0
        self._flush_timeout_s = FINAL_FLUSH_TAIL_S
        self._unfinalised = False
        self._final_seen = threading.Event()
        self._last_emitted_start = float("-inf")

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
        self._on_transcript = on_transcript
        self._on_state = on_state
        self._closed = False
        self._stopping.clear()
        self._final_seen.clear()
        self._unfinalised = False
        self._flush_timeout_s = FINAL_FLUSH_TAIL_S
        self._emit_state(SttStreamState.STARTING)

        self._thread = threading.Thread(
            target=self._thread_main, name=f"cloud-stt-{stream_id}", daemon=True
        )
        self._thread.start()
        # Wait for the loop to exist so `feed()` has something to wake. Bounded: a
        # backend that cannot even create a loop must not hang the caller forever.
        self._ready.wait(timeout=5.0)

    def feed(self, pcm: bytes, t_capture: float) -> None:
        """Enqueue one frame. Never blocks, never raises (contract rule 1).

        Called from the audio callback, which has a 2 ms budget (FR45). Everything
        expensive — the socket, the protocol, the retry — happens on the backend thread.
        """
        if self._closed or self._stopping.is_set():
            return
        if len(self._pending) == self._pending.maxlen:
            self._dropped += 1
            # Reported, not swallowed: a dropped frame is audio the user spoke that no
            # transcript will ever contain.
            #
            # Throttled, because a stalled socket drops every frame — 50 a second, each
            # one a state callback and a ring record. That evicts the bounded ring's
            # real diagnostics with repetitions of a fact already recorded, and floods
            # the UI. The first drop is the news; the rest are the same news.
            if self._dropped == 1 or self._dropped % DROP_REPORT_EVERY == 0:
                self._emit_state(SttStreamState.DEGRADED, f"dropped {self._dropped} frames")
        self._pending.append((pcm, t_capture))
        self._unfinalised = True
        # Newly accepted audio invalidates the previous final. Without this, `_final_seen`
        # latches on the *first* final of the session and never clears, so a later
        # utterance that the server never finalises reports STOPPED instead of FAILED —
        # the end of the interview dropped silently, by the very mechanism written to
        # make that impossible. Rule 2 is a per-span guarantee, not a per-session one.
        self._final_seen.clear()
        loop, wake = self._loop, self._wake
        if loop is None or wake is None:
            return
        try:
            loop.call_soon_threadsafe(wake.set)
        except RuntimeError:
            # The loop closed between the check and the call. Nothing to wake; the
            # frame stays queued and `stop()` will report any unfinalised audio.
            return

    def stop(self, flush_timeout_s: float = 2.0) -> None:
        """Flush pending finals, then STOPPED (contract rule 6).

        Three things have to hold when this returns, and each was wrong at some point:

        * **Audio accounted for.** If audio the backend accepted produced no final, the
          stream goes FAILED first. Rule 2 permits a final or FAILED, and reporting
          STOPPED with a span unaccounted for is neither.
        * **The worker is actually stopped.** The flush tail inside `_session` is bounded
          by the *caller's* timeout, so the join is not racing a longer internal wait.
        * **No callbacks after this returns.** They are detached unconditionally at the
          end. A worker that outlives its timeout would otherwise emit into a consumer
          that believes the stream is over — and `FallbackSttBackend` would clear the
          egress indicator while the socket was still open, which is FR20's false
          privacy statement in its worst direction.
        """
        if self._thread is None:
            self._emit_state(SttStreamState.STOPPED)
            return
        self._flush_timeout_s = flush_timeout_s
        self._stopping.set()
        loop, wake = self._loop, self._wake
        if loop is not None and wake is not None:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(wake.set)

        # Grace beyond the flush tail: the worker needs to unwind the loop and close the
        # socket after its last await returns, and joining for exactly the tail would
        # time out on a worker that is behaving correctly.
        self._thread.join(timeout=flush_timeout_s + JOIN_GRACE_S)
        alive = self._thread.is_alive()

        if self._unfinalised and not self._final_seen.is_set():
            self._emit_state(SttStreamState.FAILED, "audio was accepted but never finalised")
        if alive:
            self._emit_state(
                SttStreamState.FAILED,
                "worker did not stop within the timeout; callbacks detached",
            )
        self._emit_state(SttStreamState.STOPPED)

        # Detached last, after every state above has been delivered. The thread is a
        # daemon and will not outlive the process; what matters is that it can no longer
        # reach a consumer that has been told the stream is over.
        self._on_transcript = None
        self._on_state = None
        self._thread = None

    def close(self) -> None:
        """Idempotent (contract rule 6)."""
        if self._closed:
            return
        self._closed = True
        if self._thread is not None:
            self.stop(flush_timeout_s=0.5)
        self._pending.clear()

    # ---------- protocol hooks for subclasses ----------

    def build_start_message(self) -> str | None:
        """Sent once on connect, if the protocol needs a configuration frame."""
        return None

    def build_finalise_message(self) -> str | None:
        """Sent on stop to ask the server to flush its final results."""
        return None

    def encode_frame(self, pcm: bytes) -> bytes | str:
        """Wrap one frame for the wire. Raw binary by default.

        A hook rather than a branch in `_send_loop`: vendors disagree here (Deepgram
        takes binary frames, ElevenLabs takes base64 in a JSON envelope), and putting
        that difference in shared plumbing is what would make "both pass the same
        suite unmodified" a hollow claim.
        """
        return pcm

    def parse(self, message: bytes | str) -> list[TranscriptEvent]:
        """Turn one server message into zero or more events.

        Server-relative timestamps must be converted with `self.clock.to_capture`.
        Subclasses call `self.make_event(...)`, which does it for them.
        """
        raise NotImplementedError

    # ---------- helpers for subclasses ----------

    @property
    def clock(self) -> CaptureClock:
        return self._clock

    def make_event(
        self,
        text: str,
        *,
        is_final: bool,
        server_start: float,
        server_end: float,
        confidence: float | None = None,
    ) -> TranscriptEvent:
        return TranscriptEvent(
            stream_id=self._stream_id,
            text=text,
            is_final=is_final,
            t_start=self._clock.to_capture(server_start),
            t_end=self._clock.to_capture(server_end),
            confidence=confidence,
            backend=self.name,
        )

    @staticmethod
    def loads(message: bytes | str) -> dict[str, Any]:
        if isinstance(message, bytes):
            message = message.decode("utf-8", errors="replace")
        parsed = json.loads(message)
        if not isinstance(parsed, dict):
            raise ValueError("expected a JSON object")
        return parsed

    # ---------- internals ----------

    @property
    def _label(self) -> str:
        """Stream id for diagnostics. Never empty: the ring rejects empty strings, and
        `stop()` on a never-started backend is legal (contract rule 6) — so the guard
        would turn a legal call into a crash."""
        return self._stream_id[:64] or "unstarted"

    def _emit_state(self, state: SttStreamState, detail: str | None = None) -> None:
        self._state = state
        self.ring.record("stt_state", state=state.name, stream=self._label)
        if self._on_state is not None:
            self._on_state(StateEvent(stream_id=self._stream_id, state=state, detail=detail))

    def _emit_transcript(self, event: TranscriptEvent) -> None:
        # No audio sent yet means there is no anchor, so the event cannot be placed on
        # the capture clock — and it cannot describe audio of ours either. Emitting it
        # would put raw server time on a capture-clock field, which the assembler has
        # no way to detect: this project's recurring defect, in timestamp form.
        if self._clock.sent_s == 0.0:
            self.ring.record("stt_event_before_audio", stream=self._label)
            return
        # Rule 4: non-decreasing `t_start` per stream. A server that reorders — or a
        # reconnect that replays — would otherwise push a span backwards past one the
        # assembler has already closed, silently corrupting utterance boundaries.
        if event.t_start < self._last_emitted_start:
            self.ring.record("stt_out_of_order", stream=self._label)
            return
        self._last_emitted_start = event.t_start
        if event.is_final:
            self._unfinalised = False
            self._final_seen.set()
        if self._on_transcript is not None:
            self._on_transcript(event)

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as exc:  # noqa: BLE001 — the thread must not die silently
            self._emit_state(SttStreamState.FAILED, type(exc).__name__)

    async def _run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        self._ready.set()

        attempt = 0
        while not self._stopping.is_set():
            try:
                await self._session()
                return
            except Exception as exc:  # noqa: BLE001 — every failure is a reconnect decision
                if self._stopping.is_set():
                    return
                attempt += 1
                if attempt > self._reconnect_attempts:
                    self._emit_state(SttStreamState.FAILED, type(exc).__name__)
                    return
                self._emit_state(
                    SttStreamState.RECONNECTING, f"attempt {attempt}: {type(exc).__name__}"
                )
                await asyncio.sleep(self._backoff_s * attempt)

    async def _session(self) -> None:
        connection = await self._connector()
        # New socket, new server-side stream, new epoch — see `CaptureClock.reset`.
        self._clock.reset()
        self._emit_state(SttStreamState.READY)
        start_message = self.build_start_message()
        if start_message is not None:
            await connection.send(start_message)

        receiver = asyncio.create_task(self._receive(connection))
        try:
            await self._send_loop(connection)
            finalise = self.build_finalise_message()
            if finalise is not None:
                await connection.send(finalise)
            # Give the server its chance to flush finals before the socket goes.
            # `stop()` bounds the total wait; this only bounds the quiet tail.
            # Bounded by the caller's timeout, not by a fixed constant: `close()` gives
            # 0.5 s, and waiting 1.5 s here left `stop()` joining a worker that was
            # still inside this await.
            tail = min(FINAL_FLUSH_TAIL_S, self._flush_timeout_s)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(receiver, timeout=tail)
        finally:
            receiver.cancel()
            await connection.close()

    async def _send_loop(self, connection: CloudConnection) -> None:
        while True:
            while self._pending:
                pcm, t_capture = self._pending.popleft()
                self._clock.note_sent(t_capture)
                await connection.send(self.encode_frame(pcm))
            if self._stopping.is_set():
                return
            assert self._wake is not None
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=0.1)
            except TimeoutError:
                continue

    async def _receive(self, connection: CloudConnection) -> None:
        while True:
            message = await connection.recv()
            try:
                events = self.parse(message)
            except Exception:  # noqa: BLE001 — one bad frame must not kill the stream
                self.ring.record("stt_parse_failed", stream=self._label)
                continue
            for event in events:
                self._emit_transcript(event)
