"""Utterance assembly (T2.3, FR46 — design §3).

An *utterance* is a finalised transcript span, not an audio chunk. FR8's 2–4 s windows
and FR9's "each transcribed utterance" are different units, and matching per audio
chunk would fire mid-sentence and multiply stage-2 calls roughly threefold.

The assembler owns its accumulation state exclusively — exactly one thread per stream
touches it (design §2), so nothing here is locked.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from interview_prep_recall.stt.interface import TranscriptEvent

SILENCE_GAP_S = 0.700
"""Close an utterance after this much silence since the last final event."""

MAX_SPAN_S = 10.0
"""Force a close on a monologue that never pauses."""

MIN_WORDS = 3
MIN_CHARS = 12

MAX_FRAGMENT_HOLD_S = 30.0
"""An isolated "mm" is not worth carrying into an unrelated question."""

CONTEXT_WINDOW_S = 10.0
"""How much preceding finalised text rides along as stage-2 context."""

MAX_CONTEXT_CHARS = 600
"""Hard cap on the context string. Bounds stage-2 prompt size (NFR6)."""


@dataclass(frozen=True)
class Utterance:
    stream_id: str
    text: str
    t_start: float
    t_end: float
    context: str
    """Preceding finalised text on the same stream.

    Used **only** in the stage-2 prompt, never in the stage-1 embedding — including it
    blurs the query vector and costs prefilter precision (design §3).
    """

    @property
    def duration(self) -> float:
        return self.t_end - self.t_start


def _qualifies(text: str) -> bool:
    return len(text.split()) >= MIN_WORDS and len(text) >= MIN_CHARS


@dataclass
class _Open:
    text: str
    t_start: float
    t_end: float


class UtteranceAssembler:
    """Turns a stream of final `TranscriptEvent`s into `Utterance`s.

    Emission is pull-based: `feed()` and `tick()` return whatever closed as a result of
    that call. Nothing is emitted from a background timer, so tests are deterministic
    against a fake clock rather than `sleep()`.
    """

    def __init__(self, stream_id: str) -> None:
        self.stream_id = stream_id
        self._open: _Open | None = None
        self._fragment: _Open | None = None
        self._history: deque[tuple[float, str]] = deque()
        self._history_chars = 0

    # ---------- input ----------

    def feed(self, event: TranscriptEvent) -> list[Utterance]:
        """Consume one transcript event. Interim events are ignored (contract rule 3)."""
        if not event.is_final:
            return []
        if event.stream_id != self.stream_id:
            raise ValueError(
                f"assembler for {self.stream_id!r} received {event.stream_id!r}; "
                "streams must not be crossed"
            )

        emitted: list[Utterance] = []

        # A gap before this event closes whatever was open.
        if self._open is not None and event.t_start - self._open.t_end >= SILENCE_GAP_S:
            emitted.extend(self._close(self._open.t_end))

        if self._open is None:
            self._open = _Open(text=event.text.strip(), t_start=event.t_start, t_end=event.t_end)
        else:
            joined = f"{self._open.text} {event.text.strip()}".strip()
            self._open = _Open(text=joined, t_start=self._open.t_start, t_end=event.t_end)

        # A speaker who never pauses still gets cut, or the overlay waits forever.
        if self._open.t_end - self._open.t_start >= MAX_SPAN_S:
            emitted.extend(self._close(self._open.t_end))

        return emitted

    def tick(self, now: float) -> list[Utterance]:
        """Advance the clock. Closes an open span whose silence budget has elapsed.

        This is what the design means by the assembler waiting on its queue with a
        timeout: a trailing utterance must close even when no further events arrive.
        """
        emitted: list[Utterance] = []
        # Expire BEFORE closing. Closing merges any held fragment, so expiring afterwards
        # is too late — the stale fragment has already been consumed.
        self._expire_fragment(now)
        if self._open is not None and now - self._open.t_end >= SILENCE_GAP_S:
            emitted.extend(self._close(now))
        return emitted

    def stop(self) -> list[Utterance]:
        """Session stop. Closes an open span; a held fragment is dropped, not emitted."""
        emitted: list[Utterance] = []
        if self._open is not None:
            emitted.extend(self._close(self._open.t_end))
        # Firing a match on "why?" as the session ends serves nobody (design §3).
        self._fragment = None
        return emitted

    def reset(self) -> None:
        """Purge (FR15). Drops all accumulated transcript state."""
        self._open = None
        self._fragment = None
        self._history.clear()
        self._history_chars = 0

    # ---------- internals ----------

    def _close(self, at: float) -> list[Utterance]:
        span = self._open
        self._open = None
        if span is None:
            return []

        # Prepend any held fragment, then re-test against the minimum. The age check
        # lives here as well as in tick(): a close can be reached via feed() with no
        # intervening tick, and without it a 40-second-old "mm" would be glued to an
        # unrelated question and would drag the utterance's t_start back with it,
        # corrupting the context window anchor too.
        if self._fragment is not None and span.t_start - self._fragment.t_end >= (
            MAX_FRAGMENT_HOLD_S
        ):
            self._fragment = None
        if self._fragment is not None:
            span = _Open(
                text=f"{self._fragment.text} {span.text}".strip(),
                t_start=self._fragment.t_start,
                t_end=span.t_end,
            )
            self._fragment = None

        if not span.text:
            return []

        if not _qualifies(span.text):
            # Hold and merge forward. Short-but-meaningful questions ("Why?") do not
            # trigger matching alone — deliberate, they carry too little signal to place.
            self._fragment = span
            return []

        utterance = Utterance(
            stream_id=self.stream_id,
            text=span.text,
            t_start=span.t_start,
            t_end=span.t_end,
            context=self._context_for(span.t_start),
        )
        self._remember(span.t_end, span.text)
        return [utterance]

    def _expire_fragment(self, now: float) -> None:
        if self._fragment is not None and now - self._fragment.t_end >= MAX_FRAGMENT_HOLD_S:
            self._fragment = None

    def _context_for(self, t_start: float) -> str:
        cutoff = t_start - CONTEXT_WINDOW_S
        joined = " ".join(text for t_end, text in self._history if t_end >= cutoff)
        # Bounded independently of the history bound: context goes into every stage-2
        # prompt, so an unbounded string is a per-call token cost (NFR6). Trim from the
        # front — the most recent words are the ones that disambiguate the question.
        return joined[-MAX_CONTEXT_CHARS:] if len(joined) > MAX_CONTEXT_CHARS else joined

    def _remember(self, t_end: float, text: str) -> None:
        self._history.append((t_end, text))
        self._history_chars += len(text)
        # Bounded: transcript retention is a privacy cost, and FR33 forbids anything
        # that grows with session length.
        while len(self._history) > 16 or self._history_chars > 4000:
            _, dropped = self._history.popleft()
            self._history_chars -= len(dropped)

    @property
    def has_pending_fragment(self) -> bool:
        return self._fragment is not None


@dataclass
class StreamRouter:
    """Routes utterances to the right consumer (FR53, D-10).

    Matching consumes the interviewer stream only; the mic stream feeds the tracker.
    Enforced here rather than by convention at each call site, because "the mic must
    never reach matching" is a requirement with a test, not a coding style.
    """

    interviewer_stream: str = "interviewer"
    user_stream: str = "user"
    _matching: list[Utterance] = field(default_factory=list)
    _tracking: list[Utterance] = field(default_factory=list)

    def route(self, utterance: Utterance) -> None:
        if utterance.stream_id == self.interviewer_stream:
            self._matching.append(utterance)
        elif utterance.stream_id == self.user_stream:
            self._tracking.append(utterance)
        else:
            raise ValueError(f"unknown stream {utterance.stream_id!r}")

    def drain_matching(self) -> list[Utterance]:
        out, self._matching = self._matching, []
        return out

    def drain_tracking(self) -> list[Utterance]:
        out, self._tracking = self._tracking, []
        return out
