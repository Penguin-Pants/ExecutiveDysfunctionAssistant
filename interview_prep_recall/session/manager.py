"""Session state machine, purge, and panic clear (design §6, T6.1–T6.3, T6.6–T6.7).

Seven states, an explicit transition table, and illegal transitions that raise rather
than being quietly ignored. Health is orthogonal (`health.py`) — it is a record the
session carries, never a state the session is in.

Two things here are load-bearing and easy to get subtly wrong:

* **Purge ordering.** In-flight network work is neutralised *before* local state is
  cleared, so nothing in transit outlives the purge (FR59). Notes, embedding caches,
  settings and consent are never touched (FR58) — a panic clear that destroyed the
  user's prep would be the worst outcome this codebase can produce.
* **`PAUSED` records why it paused.** Resume policy differs by cause: a deliberate user
  pause must not self-cancel, while a machine lock must resume on its own. One shared
  edge would force one policy onto all three causes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from typing import Protocol

from interview_prep_recall.diagnostics.ring import DiagnosticRing
from interview_prep_recall.session.health import HealthMonitor, MatchingStatus, Status


class SessionState(Enum):
    IDLE = auto()
    PREFLIGHT = auto()
    RUNNING = auto()
    PAUSED = auto()
    STOPPING = auto()
    PURGING = auto()
    WIPED = auto()
    """Panic-clear resting state (D-U5): capture stopped, buffers gone, devices held."""


class PauseCause(Enum):
    USER = auto()
    """FR13. Manual resume only — the user meant it."""

    LOCK = auto()
    """FR62. Auto-resumes on unlock."""

    DEVICE_LOST = auto()
    """FR39b. Auto-resumes when a device returns."""


AUTO_RESUME_CAUSES = frozenset({PauseCause.LOCK, PauseCause.DEVICE_LOST})

_ALLOWED: dict[SessionState, frozenset[SessionState]] = {
    SessionState.IDLE: frozenset({SessionState.PREFLIGHT}),
    SessionState.PREFLIGHT: frozenset({SessionState.IDLE, SessionState.RUNNING}),
    SessionState.RUNNING: frozenset(
        {SessionState.PAUSED, SessionState.STOPPING, SessionState.PURGING}
    ),
    SessionState.PAUSED: frozenset(
        {SessionState.RUNNING, SessionState.STOPPING, SessionState.PURGING}
    ),
    SessionState.STOPPING: frozenset({SessionState.PURGING}),
    SessionState.PURGING: frozenset({SessionState.IDLE, SessionState.WIPED}),
    SessionState.WIPED: frozenset({SessionState.RUNNING, SessionState.IDLE}),
}


class IllegalTransition(RuntimeError):
    """A transition design §6 does not permit. Raised, never silently absorbed."""


class MatchingTarget(Protocol):
    """The slice of `MatchingPipeline` the LLM switch drives.

    A Protocol rather than a direct import: the session owns lifecycle, not matching,
    and a hard dependency between them would make either untestable without the other.
    """

    def set_local_only(self, value: bool) -> None: ...


@dataclass
class PurgeHooks:
    """Injected so ordering is testable without real sockets, threads or Qt.

    Every hook defaults to a no-op: a partially wired session must still purge
    correctly, because the moment purge matters least is never the moment it runs.
    """

    cancel_network: Callable[[], None] = lambda: None
    """Step 1. Close the cloud STT socket; neutralise the in-flight LLM response."""

    stop_capture: Callable[[], None] = lambda: None
    zero_audio: Callable[[], None] = lambda: None
    drop_transcript: Callable[[], None] = lambda: None
    clear_overlay: Callable[[], None] = lambda: None


@dataclass
class DegradationSwitches:
    """FR37. Each toggles mid-session without a restart."""

    llm_matching: bool = True
    cloud_stt: bool = False
    progress_tracker: bool = True


class SessionManager:
    def __init__(
        self,
        hooks: PurgeHooks | None = None,
        ring: DiagnosticRing | None = None,
        monitor: HealthMonitor | None = None,
        on_state_change: Callable[[SessionState, SessionState], None] | None = None,
    ) -> None:
        self.hooks = hooks or PurgeHooks()
        self.ring = ring or DiagnosticRing()
        self.monitor = monitor or HealthMonitor()
        self.on_state_change = on_state_change
        self.switches = DegradationSwitches()

        self._state = SessionState.IDLE
        self._pause_cause: PauseCause | None = None
        self._purge_order: list[str] = []
        self._worker_restarts: dict[str, int] = {}
        self._preflight_passed = False
        self._matching: MatchingTarget | None = None
        self._purge_failures: list[tuple[str, str]] = []

    def attach_matching(self, target: MatchingTarget) -> None:
        """Wire the LLM switch to the live pipeline.

        Without this, `set_switch("llm_matching", False)` would flip a detached config
        object and light the local-only indicator while the pipeline kept calling the
        API — the UI claiming nothing leaves the device while text still does. That is
        why toggling the switch unattached raises rather than degrading quietly.
        """
        self._matching = target

    # ---------- state ----------

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def pause_cause(self) -> PauseCause | None:
        return self._pause_cause

    @property
    def purge_failures(self) -> list[tuple[str, str]]:
        """`(hook, exception)` pairs from the last purge. Empty means every step ran."""
        return list(self._purge_failures)

    @property
    def purge_order(self) -> list[str]:
        """Hook names in the order the last purge ran them. Ordering is a requirement."""
        return list(self._purge_order)

    def _to(self, target: SessionState) -> None:
        if target not in _ALLOWED[self._state]:
            raise IllegalTransition(f"{self._state.name} -> {target.name} is not permitted")
        previous, self._state = self._state, target
        self.ring.record("session_state", state=target.name)
        if self.on_state_change is not None:
            self.on_state_change(previous, target)

    # ---------- lifecycle ----------

    def request_start(self) -> None:
        self._to(SessionState.PREFLIGHT)

    def preflight_result(self, *, blocked: bool) -> SessionState:
        """FR38. A hard failure returns to IDLE; anything else proceeds."""
        self._preflight_passed = not blocked
        if not blocked:
            # One restart per stream **per session** (FR61). Without this the counter
            # persists for the process lifetime, so a stream that crashed in an earlier
            # session is held from its very first crash in this one.
            self.reset_supervision()
        self._to(SessionState.IDLE if blocked else SessionState.RUNNING)
        return self._state

    def pause(self, cause: PauseCause) -> None:
        """Validates *before* recording the cause.

        Order matters: if the user has already paused deliberately and a lock or
        device-loss callback fires, the transition is illegal — but writing the cause
        first would leave an auto-resumable cause behind, and the next unlock would
        restart capture the user had chosen to stop. Same failure D-22 closed on the
        panic-clear path, reachable through a second pause event.
        """
        if SessionState.PAUSED not in _ALLOWED[self._state]:
            raise IllegalTransition(
                f"{self._state.name} -> PAUSED is not permitted; "
                f"existing pause cause {self._pause_cause} is preserved"
            )
        self._pause_cause = cause
        self.ring.record("session_paused", cause=cause.name)
        self._to(SessionState.PAUSED)

    def resume(self, *, automatic: bool = False) -> None:
        """`automatic=True` is the machine acting (unlock, device return).

        A deliberate user pause never auto-resumes — otherwise pausing to think would
        silently undo itself.
        """
        if self._state is SessionState.WIPED:
            # A panic clear is a deliberate stop. Letting a machine event undo it —
            # a device-return callback firing after the user hit the button — would
            # silently restart capture they just chose to stop.
            if automatic:
                raise IllegalTransition(
                    "automatic resume refused from WIPED: a panic clear is undone only by the user"
                )
            if not self._preflight_passed:
                raise IllegalTransition("cannot resume from WIPED without a passed preflight")
            self._to(SessionState.RUNNING)
            return
        if automatic and self._pause_cause not in AUTO_RESUME_CAUSES:
            raise IllegalTransition(
                f"automatic resume refused: paused by {self._pause_cause} — "
                "a user pause resumes only on user action"
            )
        self._pause_cause = None
        self._to(SessionState.RUNNING)

    def end_session(self) -> None:
        if self._state is SessionState.WIPED:
            self._to(SessionState.IDLE)
            return
        self._to(SessionState.STOPPING)
        self._purge()
        self._to(SessionState.IDLE)

    def panic_clear(self) -> None:
        """US-F3 / D-U5. Wipes, stops capture, and stays resumable."""
        self._to(SessionState.PURGING)
        self._purge()
        self._to(SessionState.WIPED)

    # ---------- purge ----------

    def _purge(self) -> None:
        if self._state is not SessionState.PURGING:
            self._to(SessionState.PURGING)
        self._purge_order = []
        self._purge_failures = []
        # Order is the requirement (FR59) — and so is completeness. Every step runs even
        # if an earlier one throws: `cancel_network` closing a already-broken socket is
        # exactly the plausible failure, and letting it abort the loop would leave
        # capture running and audio, transcript and overlay uncleared. Panic clear would
        # fail precisely on the degraded session that most needs it.
        for name, hook in (
            ("cancel_network", self.hooks.cancel_network),
            ("stop_capture", self.hooks.stop_capture),
            ("zero_audio", self.hooks.zero_audio),
            ("drop_transcript", self.hooks.drop_transcript),
            ("clear_overlay", self.hooks.clear_overlay),
        ):
            try:
                hook()
            except Exception as exc:  # noqa: BLE001 — no hook may block the rest
                self._purge_failures.append((name, type(exc).__name__))
            self._purge_order.append(name)

        self.monitor.reset()
        # Diagnostics are session-scoped (FR36). Cleared here, before the new records
        # below, so the purge outcome survives into the next session while the ended
        # session's events do not leak into it or crowd the bounded ring.
        self.ring.clear()
        self.ring.record("session_purged", count=len(self._purge_order))
        for name, exc_name in self._purge_failures:
            self.ring.record("purge_hook_failed", reason=name, cause=exc_name[:64])

    # ---------- supervision (T6.6, design §9) ----------

    def note_worker_failure(self, stream: str) -> bool:
        """Returns True if the worker should be restarted, False if STT holds.

        One restart per stream per session, and **per stream** — a dead mic worker must
        never stop interviewer matching (FR61).
        """
        count = self._worker_restarts.get(stream, 0)
        self._worker_restarts[stream] = count + 1
        restart = count == 0
        self.ring.record("stt_worker_failure", stream=stream[:64], retry=count + 1)
        field = "stt_user" if stream == "user" else "stt_interviewer"
        self.monitor.update(**{field: Status.DEGRADED if restart else Status.FAILED})
        return restart

    def reset_supervision(self) -> None:
        self._worker_restarts.clear()

    # ---------- degradation switches (T6.7) ----------

    def set_switch(self, name: str, value: bool) -> None:
        if not hasattr(self.switches, name):
            raise ValueError(f"unknown degradation switch {name!r}")

        if name == "llm_matching":
            if self._matching is None:
                raise RuntimeError(
                    "llm_matching toggled with no pipeline attached — call "
                    "attach_matching() first. Reporting local-only while the pipeline "
                    "still calls the API would tell the user their question text stays "
                    "on the device when it does not."
                )
            # Apply to the pipeline first: if this raises, neither the switch nor the
            # indicator may claim a state the pipeline is not actually in.
            self._matching.set_local_only(not value)

        setattr(self.switches, name, value)
        self.ring.record("switch", reason=name[:64], ok=value)
        if name == "llm_matching":
            self.monitor.update(matching=MatchingStatus.OK if value else MatchingStatus.LOCAL_ONLY)
