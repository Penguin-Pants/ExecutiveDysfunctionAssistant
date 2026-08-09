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
from interview_prep_recall.notes.model import NoteSet

TAU_FLOOR_DEFAULT = 0.35
TAU_FLOOR_MIN = 0.20
TAU_FLOOR_MAX = 0.60
"""FR52 sensitivity control range (design §5)."""

TOP_K = 5
"""Bounds the FR48 enum regardless of corpus size."""


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


class Prefilter:
    def __init__(
        self,
        index: EmbeddingIndex,
        note_set: NoteSet,
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

        order = np.argsort(-similarities)[: self.top_k]
        note_ids = self.index.note_ids
        out: list[Candidate] = []
        for position in order:
            score = float(similarities[position])
            if score < self._tau_floor:
                break  # sorted descending, so nothing after this clears either
            note = self.note_set.get(note_ids[position])
            if note is None:
                continue  # index outlives a deletion until the next build
            out.append(
                Candidate(
                    note_id=note.id,
                    headline=note.headline,
                    tags=tuple(note.tags),
                    similarity=score,
                )
            )
        return out
