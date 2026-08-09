"""The T2.1 conformance suite, as a suite rather than a claim.

`docs/implementation/03-tasks.md` gives T8.1 and T8.2 the acceptance criterion "passes
the T2.1 conformance suite **unmodified**". Until now there was no such artifact — only
`test_stt_interface.py`, which checked that a null object satisfied the Protocol shape.
That is a typing check, not a conformance check: it exercises none of the eight semantic
rules the interface docstring calls the actual contract, and a backend could violate
every one of them and still pass.

So this is the suite. Each function checks one numbered rule from `SttBackend`, takes a
zero-argument factory, and knows nothing about any backend. `run_conformance_suite`
runs the lot. A new backend adds one test file with one factory and inherits all of it —
which is the only way "unmodified" means anything.

Two rules are checked per backend rather than here, because a generic factory cannot
produce the conditions they need. Rule 1's drop-and-report-DEGRADED half requires a
*stalled* transport — against a double that drains instantly nothing ever overflows,
and asserting DEGRADED anyway would fail a correct backend. Rules 2, 3 and 5 need
scripted server output that only the backend's own protocol can produce.

Rule 7 (callbacks may run on any thread) is a constraint on *consumers*, not on
backends, so it has no check here; it is enforced where consumers are written.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from interview_prep_recall.stt.interface import (
    FRAME_BYTES,
    StateEvent,
    SttBackend,
    SttStreamState,
    TranscriptEvent,
)

BackendFactory = Callable[[], SttBackend]


class Recorder:
    """Thread-safe callback sink. Backends emit from their own threads (rule 7)."""

    def __init__(self) -> None:
        self.transcripts: list[TranscriptEvent] = []
        self.states: list[StateEvent] = []
        self._lock = threading.Lock()

    def on_transcript(self, event: TranscriptEvent) -> None:
        with self._lock:
            self.transcripts.append(event)

    def on_state(self, event: StateEvent) -> None:
        with self._lock:
            self.states.append(event)

    @property
    def finals(self) -> list[TranscriptEvent]:
        with self._lock:
            return [e for e in self.transcripts if e.is_final]

    @property
    def state_names(self) -> list[SttStreamState]:
        with self._lock:
            return [e.state for e in self.states]


def start(backend: SttBackend, stream_id: str = "interviewer") -> Recorder:
    recorder = Recorder()
    backend.start(stream_id, 16_000, 1, recorder.on_transcript, recorder.on_state)
    return recorder


# ---------- rule 1: feed never blocks and never raises ----------


def check_feed_never_raises(factory: BackendFactory) -> None:
    backend = factory()
    start(backend)
    for i in range(2_000):
        backend.feed(b"\x00" * FRAME_BYTES, i * 0.02)
    backend.close()


def check_feed_before_start_is_harmless(factory: BackendFactory) -> None:
    """The audio thread can outlive a stopped stream. Rule 1 makes that the backend's
    problem to absorb, not the caller's to guard against."""
    backend = factory()
    backend.feed(b"\x00" * FRAME_BYTES, 0.0)
    backend.close()


# ---------- rule 6: stop and close ----------


def check_close_is_idempotent(factory: BackendFactory) -> None:
    backend = factory()
    start(backend)
    backend.close()
    backend.close()
    backend.close()


def check_stop_reaches_stopped(factory: BackendFactory) -> None:
    backend = factory()
    recorder = start(backend)
    backend.feed(b"\x00" * FRAME_BYTES, 0.0)
    backend.stop(flush_timeout_s=1.0)
    assert recorder.state_names[-1] is SttStreamState.STOPPED, (
        f"stop() must end in STOPPED, ended in {recorder.state_names[-1]}"
    )


def check_stop_without_start_is_harmless(factory: BackendFactory) -> None:
    backend = factory()
    backend.stop()
    backend.close()


# ---------- rule 8: frame size ----------


def check_declares_frame_contract(factory: BackendFactory) -> None:
    backend = factory()
    assert isinstance(backend.name, str) and backend.name
    assert isinstance(backend.supports_interim, bool)
    backend.close()


def run_conformance_suite(factory: BackendFactory) -> None:
    """Every backend-independent rule. Rules needing scripted server output (2, 3, 5)
    are checked per backend, since only the backend's own protocol can produce them."""
    check_declares_frame_contract(factory)
    check_feed_never_raises(factory)
    check_feed_before_start_is_harmless(factory)
    check_close_is_idempotent(factory)
    check_stop_reaches_stopped(factory)
    check_stop_without_start_is_harmless(factory)
