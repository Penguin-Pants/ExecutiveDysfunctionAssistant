"""The session transcript record (T11.1 — FR74, FR75, FR76).

**This is the only structure in the application permitted to grow with session length,
and it is capped.** FR33 forbids that everywhere else because an unbounded buffer in a
60-minute session is how this app dies mid-interview. A feature that genuinely needs an
accumulating structure has to say so loudly and bound it, or the next reviewer is right
to read it as a regression — which is what FR76 is for.

Finals only. `Utterance` is produced by the assembler from finalised transcript events,
so interim text cannot reach here by construction rather than by filtering (FR74).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from interview_prep_recall.diagnostics.ring import DiagnosticRing
from interview_prep_recall.stt.assembler import Utterance

MAX_UTTERANCES = 5_000
MAX_DURATION_S = 4 * 60 * 60
"""FR75. Whichever comes first. Both are far beyond any real interview — they exist to
bound a runaway session, not to trim a long one."""


@dataclass(frozen=True)
class RecordedUtterance:
    """One finalised span, with the index that presence evidence cites (FR78)."""

    index: int
    stream_id: str
    text: str
    t_start: float
    t_end: float

    @property
    def is_user(self) -> bool:
        return self.stream_id == "user"


@dataclass
class SessionRecord:
    """Ordered, bounded, finals-only.

    **Truncation stops recording rather than dropping the oldest.** Dropping oldest
    would silently lose the opening of the interview while the report claimed to cover
    the whole meeting; stopping loses the tail and says so. Neither is good, and the
    difference is that one of them is visible — FR75 requires the report to state it.
    """

    ring: DiagnosticRing = field(default_factory=DiagnosticRing)
    max_utterances: int = MAX_UTTERANCES
    max_duration_s: float = MAX_DURATION_S

    _utterances: list[RecordedUtterance] = field(default_factory=list)
    _truncated: bool = False
    _first_start: float | None = None

    def __len__(self) -> int:
        return len(self._utterances)

    @property
    def utterances(self) -> list[RecordedUtterance]:
        return list(self._utterances)

    @property
    def truncated(self) -> bool:
        """FR75. Read by the generator, which must state it in the report."""
        return self._truncated

    @property
    def duration_s(self) -> float:
        if not self._utterances:
            return 0.0
        return self._utterances[-1].t_end - self._utterances[0].t_start

    def add(self, utterance: Utterance) -> RecordedUtterance | None:
        """Append one finalised span. Returns None once a bound is reached."""
        if self._truncated:
            return None
        if len(self._utterances) >= self.max_utterances:
            self._truncate("utterance_cap")
            return None
        if self._first_start is None:
            self._first_start = utterance.t_start
        elif utterance.t_end - self._first_start > self.max_duration_s:
            self._truncate("duration_cap")
            return None

        recorded = RecordedUtterance(
            index=len(self._utterances),
            stream_id=utterance.stream_id,
            text=utterance.text,
            t_start=utterance.t_start,
            t_end=utterance.t_end,
        )
        self._utterances.append(recorded)
        return recorded

    def _truncate(self, reason: str) -> None:
        self._truncated = True
        self.ring.record("record_truncated", reason=reason[:64], count=len(self._utterances))

    def get(self, index: int) -> RecordedUtterance | None:
        """Resolve a presence citation (FR78). None means the citation is unresolvable,
        which is what makes an invented index detectable rather than merely wrong."""
        if 0 <= index < len(self._utterances):
            return self._utterances[index]
        return None

    def clear(self) -> None:
        """Session purge (FR15). The transcript is `str` and cannot be zeroed in Python;
        this drops every application reference, which is the honest limit FR15 states."""
        self._utterances.clear()
        self._truncated = False
        self._first_start = None

    @classmethod
    def rehydrate(cls, utterances: Sequence[RecordedUtterance]) -> SessionRecord:
        """Rebuild a record from stored spans, for regenerating an old report.

        Regeneration is the reason D-U8 traded away "nothing reaches the disk", so it has
        to work from the store rather than from live memory — the live record is purged
        at session end, and an interview reviewed a week later has no live anything.
        """
        record = cls()
        record._utterances = list(utterances)
        return record

    def transcript_lines(self) -> list[str]:
        """Numbered, speaker-labelled, for the generation prompt.

        The index is in the text because the model has to cite it back — presence
        evidence is an index into this record, and a model that never sees the indices
        cannot produce one that resolves.
        """
        return [
            f"[{u.index}] {'YOU' if u.is_user else 'INTERVIEWER'}: {u.text}"
            for u in self._utterances
        ]
