"""Progress tracker and runtime echo suppression (T7.1, T7.3 — FR12, FR56, FR57).

Marks the talking points you have already covered, from **your own microphone only**.
Playing a tracked phrase through the interviewer's stream must never mark it (FR56) —
otherwise the interviewer describing the role would tick off points you never made.

**Echo suppression drops the mic copy, not the interviewer utterance** (design §5a).
When you are on speakers, the duplicated audio *is* the interviewer's real question
bleeding into your microphone. Suppressing the interviewer span would throw away the
genuine question while the echoed mic copy still marked a talking point you never said
— which is precisely the FR56 failure this exists to prevent, implemented backwards.
The mic copy is the artefact; it is the one to drop.

Suppression is text-domain rather than audio cross-correlation. The two streams are
consumed by independent STT backends with different internal buffering, so aligning
their PCM at runtime would mean retaining and time-warping both — expensive, and it
re-introduces exactly the retained-audio problem FR16 exists to avoid.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from interview_prep_recall.diagnostics.ring import DiagnosticRing
from interview_prep_recall.notes.index import Embedder, EmbeddingIndex
from interview_prep_recall.notes.model import NoteSet
from interview_prep_recall.stt.assembler import Utterance

TAU_TRACK = 0.60
"""Design §5. Deliberately stricter than τ_floor: a false "you covered that" is worse
than a missed tick, because the user acts on it by *not* saying something."""

TAU_ECHO_TEXT = 0.80
"""Jaccard overlap above which a mic span is judged to be an echo of the interviewer."""

ECHO_WINDOW_S = 1.5
"""How far apart two spans may sit and still be the same utterance."""

ECHO_HOLD_S = 0.3
"""How long a mic utterance waits for a matching interviewer utterance to appear.

The delay lands on the tracker, which is not latency-critical, rather than on matching,
which is. An interviewer utterance is never held.
"""

MAX_HELD = 32
"""Mic utterances awaiting release. Bounded, drop-oldest.

`submit_user` appends and only `tick`/`flush` drain, so a caller that never ticks would
grow this without limit — precisely what FR33 forbids. Dropping the oldest is safe here:
a mic span old enough to be evicted has long outlived its 300 ms hold window, and the
only cost of losing it is one unticked checklist item.
"""

INTERVIEWER_MEMORY = 8
"""Recent interviewer utterances kept for comparison. Bounded — nothing in the pipeline
may grow with session length (FR33)."""


def _tokens(text: str) -> set[str]:
    return {w for w in text.lower().split() if w}


def jaccard(a: str, b: str) -> float:
    """Normalised token overlap on lowercased word sets (design §5a)."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def spans_overlap(a: Utterance, b: Utterance, window: float = ECHO_WINDOW_S) -> bool:
    """True when two spans are close enough in time to be the same speech."""
    return a.t_start - window <= b.t_end and b.t_start - window <= a.t_end


@dataclass(frozen=True)
class TrackedPoint:
    note_id: str
    headline: str
    mentioned: bool = False


@dataclass
class _Held:
    utterance: Utterance
    released: bool = False


@dataclass
class ProgressTracker:
    """FR12 checklist state for one session.

    Marks are **sticky**: once covered, a point stays covered. Un-marking would make the
    checklist flicker while the user is mid-sentence, which is the opposite of what a
    glanceable list is for.
    """

    note_set: NoteSet
    index: EmbeddingIndex
    embedder: Embedder
    tau_track: float = TAU_TRACK
    ring: DiagnosticRing = field(default_factory=DiagnosticRing)

    _marked: set[str] = field(default_factory=set)
    _recent_interviewer: list[Utterance] = field(default_factory=list)
    _held: list[_Held] = field(default_factory=list)
    _suppressed: int = 0

    # ---------- checklist ----------

    def points(self) -> list[TrackedPoint]:
        return [
            TrackedPoint(n.id, n.headline, n.id in self._marked) for n in self.note_set.tracked()
        ]

    @property
    def marked_ids(self) -> set[str]:
        return set(self._marked)

    @property
    def suppressed_count(self) -> int:
        return self._suppressed

    def reset(self) -> None:
        """Session purge (FR15). Marks are session state, cleared with everything else."""
        self._marked.clear()
        self._recent_interviewer.clear()
        self._held.clear()
        self._suppressed = 0

    # ---------- input ----------

    def observe_interviewer(self, utterance: Utterance) -> None:
        """Record an interviewer utterance for echo comparison.

        Never suppresses, never marks, never delays. The interviewer stream proceeds to
        matching untouched — this is only a copy kept for comparison.
        """
        if utterance.stream_id != "interviewer":
            raise ValueError(f"expected an interviewer utterance, got {utterance.stream_id!r}")
        self._recent_interviewer.append(utterance)
        if len(self._recent_interviewer) > INTERVIEWER_MEMORY:
            self._recent_interviewer.pop(0)

        # A held mic span that this utterance explains can be dropped immediately
        # rather than waiting out its hold window.
        for held in self._held:
            if not held.released and self._is_echo(held.utterance, utterance):
                held.released = True
                self._suppressed += 1
                self.ring.record("echo_suppressed", stream="user")

    def submit_user(self, utterance: Utterance) -> list[str]:
        """Offer a mic utterance to the tracker. Returns note IDs newly marked.

        Held for `ECHO_HOLD_S` so a matching interviewer utterance has a chance to
        arrive; call `tick()` to release it. Returns nothing on this call by design.
        """
        if utterance.stream_id != "user":
            raise ValueError(
                f"the tracker consumes the mic stream only; got {utterance.stream_id!r} "
                "(FR56 — an interviewer phrase must never mark a talking point)"
            )
        # An interviewer utterance already seen can settle it without any wait.
        if any(self._is_echo(utterance, prior) for prior in self._recent_interviewer):
            self._suppressed += 1
            self.ring.record("echo_suppressed", stream="user")
            return []
        self._held.append(_Held(utterance))
        while len(self._held) > MAX_HELD:
            dropped = self._held.pop(0)
            if not dropped.released:
                self.ring.record("held_utterance_dropped", stream="user")
        return []

    def tick(self, now: float) -> list[str]:
        """Release held mic utterances whose hold window has elapsed.

        `now` is stream time, not wall clock, so tests are deterministic against
        utterance timestamps rather than `sleep()`.
        """
        newly: list[str] = []
        still: list[_Held] = []
        for held in self._held:
            if held.released:
                continue
            if now - held.utterance.t_end < ECHO_HOLD_S:
                still.append(held)
                continue
            newly.extend(self._mark(held.utterance))
        self._held = still
        return newly

    def flush(self) -> list[str]:
        """Release everything held, ignoring the hold window.

        Called at session stop by the session manager. **Not yet wired** — `app.py`
        (M9) owns that wiring, so this and `reset()` currently have no production
        caller. Recorded rather than left implicit, because an uncalled method that
        documents itself as called is this project's most repeated defect (D-20).
        """
        newly: list[str] = []
        for held in self._held:
            if not held.released:
                newly.extend(self._mark(held.utterance))
        self._held = []
        return newly

    # ---------- internals ----------

    def _is_echo(self, user: Utterance, interviewer: Utterance) -> bool:
        return (
            spans_overlap(user, interviewer)
            and jaccard(user.text, interviewer.text) >= TAU_ECHO_TEXT
        )

    def _mark(self, utterance: Utterance) -> list[str]:
        tracked = self.note_set.tracked()
        if not tracked or self.index.vectors.shape[0] == 0 or not utterance.text.strip():
            return []

        query = self.embedder.encode([utterance.text])
        norm = float(np.linalg.norm(query[0]))
        if norm == 0.0:
            return []
        unit = (query[0] / norm).astype(np.float32)
        similarities = self.index.vectors @ unit

        note_ids = self.index.note_ids
        trackable = {n.id for n in tracked}
        newly: list[str] = []
        for position, note_id in enumerate(note_ids):
            if note_id not in trackable or note_id in self._marked:
                continue
            if float(similarities[position]) >= self.tau_track:
                self._marked.add(note_id)
                newly.append(note_id)
                self.ring.record("point_marked", note_id=note_id)
        return newly
