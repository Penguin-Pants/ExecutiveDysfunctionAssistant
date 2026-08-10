"""Stage-1 local embedding prefilter (T4.1, FR9, FR50).

Always on, no network call. Embeds the utterance, compares against the active note
set's cached vectors, and returns the top-K candidates above τ_floor. If nothing
clears the floor the overlay shows nothing (FR50) — the system never surfaces a note
it did not select.

Only `headline` is embedded on both sides (design §4): matching is question-to-question,
and the utterance is a question.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from interview_prep_recall.notes.index import Embedder, EmbeddingIndex
from interview_prep_recall.notes.model import ContextSet, SourceKind

TAU_FLOOR_DEFAULT = 0.35
TAU_FLOOR_MIN = 0.20
TAU_FLOOR_MAX = 0.60
"""FR52 sensitivity control range (design §5)."""

TOP_K = 5
"""Bounds the FR48 enum regardless of corpus size."""

PER_KIND_CAP = 2
"""FR68. At most this many candidates from any one kind, before the TOP_K truncation.

Without it a long job description wins on chunk count alone: it is the biggest document
most users will import, so an unweighted top-5 fills with role requirements and crowds
out the prep notes the product exists to surface. The cap is on *supply*, not on rank —
the best two of a kind still compete on score with everything else.
"""

KIND_TAU_OFFSET: dict[SourceKind, float] = {
    SourceKind.PREP: 0.0,
    SourceKind.RESUME: 0.0,
    SourceKind.ROLE: -0.05,
    SourceKind.COMPANY: -0.05,
    SourceKind.INTERVIEWER: -0.05,
}
"""FR69. Per-kind offsets from the single user-facing control (FR52).

Prep and resume sit at the control exactly: those are the user's own words, and the bar
they set is the bar they meant. The three reference kinds sit slightly lower, because a
job description phrased in HR language will not match a spoken question as tightly as a
note the user wrote in their own voice — holding them to the same threshold would mean
they effectively never surface.

Offsets, never absolutes. A fixed threshold per kind would stop tracking the control and
silently ignore the user turning sensitivity up or down, which is the mistake design §5
already had to correct once for tau_degraded.
"""


def tau_degraded_for(tau_floor: float) -> float:
    """Derived, never independent (design §5).

    A fixed 0.55 falls below τ_floor once the user raises sensitivity past it, which
    makes the FR49 degraded gate unconditional and silently restores the very PRD
    behaviour D-U3 exists to overturn.
    """
    return max(0.55, tau_floor + 0.10)


@dataclass(frozen=True)
class Candidate:
    note_id: str
    headline: str
    tags: tuple[str, ...]
    similarity: float
    kind: SourceKind = SourceKind.PREP
    """Carried to the stage-2 prompt (FR71) so the selector can tell "a thing I planned
    to say" from "a fact about the company"."""


class Prefilter:
    def __init__(
        self,
        index: EmbeddingIndex,
        note_set: ContextSet,
        embedder: Embedder,
        tau_floor: float = TAU_FLOOR_DEFAULT,
        top_k: int = TOP_K,
    ) -> None:
        self.index = index
        self.note_set = note_set
        self.embedder = embedder
        self.top_k = top_k
        self._tau_floor = TAU_FLOOR_DEFAULT
        self.tau_floor = tau_floor

    @property
    def tau_floor(self) -> float:
        return self._tau_floor

    @tau_floor.setter
    def tau_floor(self, value: float) -> None:
        if not TAU_FLOOR_MIN <= value <= TAU_FLOOR_MAX:
            raise ValueError(
                f"tau_floor {value} outside the FR52 control range "
                f"[{TAU_FLOOR_MIN}, {TAU_FLOOR_MAX}]"
            )
        self._tau_floor = value

    @property
    def tau_degraded(self) -> float:
        return tau_degraded_for(self._tau_floor)

    def tau_for(self, kind: SourceKind) -> float:
        """Effective floor for one kind. Clamped to the control range, so an offset can
        never push a kind outside the bounds FR52 defines."""
        raw = self._tau_floor + KIND_TAU_OFFSET.get(kind, 0.0)
        return min(TAU_FLOOR_MAX, max(TAU_FLOOR_MIN, raw))

    def candidates(self, text: str) -> list[Candidate]:
        """Top-K notes above τ_floor, best first. Empty means "show nothing" (FR50)."""
        vectors = self.index.vectors
        if vectors.shape[0] == 0 or not text.strip():
            return []

        query = self.embedder.encode([text])
        norm = float(np.linalg.norm(query[0]))
        if norm == 0.0:
            return []
        unit = (query[0] / norm).astype(np.float32)

        # Index vectors are L2-normalised, so a dot product is the cosine.
        similarities = vectors @ unit

        # Full descending order rather than a top-K slice: the per-kind cap means one
        # kind's second-best chunk can make the final list while another kind's
        # third-best cannot, so truncating before the cap is applied would drop
        # candidates that belong in the enum.
        order = np.argsort(-similarities)
        note_ids = self.index.note_ids
        # By id, not `note_set.get`, which is a linear scan: the loop can now walk the
        # whole corpus rather than a top-K slice, and a scan inside it makes the
        # prefilter O(n^2) in note count against NFR's 50 ms budget for 200 notes.
        by_id = {n.id: n for n in self.note_set.notes}
        # Below this, no kind's floor can be cleared, so the descending order lets us
        # stop. Recovers the early exit the single-threshold version had, without
        # assuming every kind shares one floor.
        lowest_floor = min(self.tau_for(k) for k in SourceKind)
        taken: dict[SourceKind, int] = {}
        out: list[Candidate] = []
        for position in order:
            score = float(similarities[position])
            if score < lowest_floor:
                break
            note = by_id.get(note_ids[position])
            if note is None:
                continue  # index outlives a deletion until the next build
            if score < self.tau_for(note.kind):
                continue  # FR69 — this kind's floor is higher than the global minimum
            if taken.get(note.kind, 0) >= PER_KIND_CAP:
                continue  # FR68
            taken[note.kind] = taken.get(note.kind, 0) + 1
            out.append(
                Candidate(
                    note_id=note.id,
                    headline=note.headline,
                    tags=tuple(note.tags),
                    similarity=score,
                    kind=note.kind,
                )
            )
            if len(out) == self.top_k:
                break
        return out
