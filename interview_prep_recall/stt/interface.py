"""The streaming STT contract (T2.1, FR17, FR47 — design §2).

Written before any backend, deliberately (D-2). The PRD's build order put a cloud
backend first, which would have shaped this interface around WebSocket conveniences —
native interim results, server-side finalisation — that local Whisper cannot provide.
So it is specified against the *local* backend's constraints and the cloud backends
adapt to it, not the other way round.

The semantic rules below are the contract. They are not documentation of what the
current implementations happen to do; a backend that violates any of them is broken
even if its tests pass, and the conformance suite exists to check exactly these.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from typing import Protocol

SAMPLE_RATE = 16_000
"""Design §1a. Every backend receives exactly this."""

CHANNELS = 1
FRAME_MS = 20
FRAME_BYTES = SAMPLE_RATE * CHANNELS * 2 * FRAME_MS // 1000
"""640 bytes: 20 ms of 16 kHz mono int16."""


class SttStreamState(Enum):
    STARTING = auto()
    READY = auto()
    DEGRADED = auto()
    RECONNECTING = auto()
    FAILED = auto()
    STOPPED = auto()


@dataclass(frozen=True)
class TranscriptEvent:
    stream_id: str
    """"interviewer" (loopback) or "user" (mic)."""

    text: str
    is_final: bool
    t_start: float
    """Seconds on the capture-side monotonic clock, not the backend's arrival time."""

    t_end: float
    confidence: float | None
    backend: str


@dataclass(frozen=True)
class StateEvent:
    stream_id: str
    state: SttStreamState
    detail: str | None


OnTranscript = Callable[[TranscriptEvent], None]
OnState = Callable[[StateEvent], None]


class SttBackend(Protocol):
    """A streaming speech-to-text backend.

    Binding rules, all of which the conformance suite checks:

    1. **`feed()` never blocks and never raises on transient errors.** It enqueues and
       returns. A backend that cannot keep up drops internally and reports `DEGRADED`.
       Blocking here stalls the audio callback and breaks FR45's 2 ms budget.
    2. **Finalisation is guaranteed.** Every span of audio the backend acknowledged
       produces exactly one `is_final=True` event, or the stream transitions to
       `FAILED`. No span is silently dropped (FR47). Local Whisper has no native final
       marker, which is why this is the backend's responsibility rather than something
       the interface assumes the wire protocol supplies.
    3. **Interim events are advisory.** Backends may emit `is_final=False`; consumers
       must never trigger matching on them. `supports_interim = False` is legal.
    4. **Ordering.** For a given `stream_id`, events are emitted in non-decreasing
       `t_start`.
    5. **Clock.** Timestamps derive from the capture-time monotonic value passed to
       `feed()`. Backends must not substitute wall-clock or their own arrival time —
       cloud latency would otherwise corrupt utterance boundaries.
    6. **`stop()`** flushes pending finals within `flush_timeout_s`, then transitions
       to `STOPPED`. **`close()`** releases resources and is idempotent.
    7. **Callbacks run on whichever thread the backend chooses**, not necessarily the
       caller of `feed()`. Consumers must enqueue and return.
    8. **`feed()` receives exactly one `FRAME_BYTES` frame.** Chunking into inference
       windows happens inside the backend (design §1a).
    """

    name: str
    supports_interim: bool

    def start(
        self,
        stream_id: str,
        sample_rate: int,
        channels: int,
        on_transcript: OnTranscript,
        on_state: OnState,
    ) -> None: ...

    def feed(self, pcm: bytes, t_capture: float) -> None: ...

    def stop(self, flush_timeout_s: float = 2.0) -> None: ...

    def close(self) -> None: ...
