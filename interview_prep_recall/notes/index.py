"""Embedding index and cache (T3.6, FR34).

The failure this module exists to prevent (BC-1) is silent: if the embedding model
changes and stale vectors are compared against fresh query vectors, nothing errors —
matching just quietly gets worse, which is nearly undetectable to the user and attacks
the product's core function. So the cache records what produced it and refuses to be
used with anything else.

Two invalidation levels:
  * `embed_model_id` / `embed_model_version` mismatch  → discard everything, re-embed
  * per-note `content_hash` mismatch                    → re-embed that note only

The embedder is a Protocol so unit tests run against a deterministic fake and CI needs
no torch. Real runs use `sentence-transformers` behind the same interface — which is
the same swappability argument FR17 makes for STT backends.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from interview_prep_recall.notes.model import ContextSet

INDEX_SCHEMA_VERSION = 1

DEFAULT_EMBED_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"


def model_slug(model_id: str) -> str:
    """Filename-safe form of a model id.

    Hugging Face ids contain `/`, which is illegal in a Windows filename — the path
    `index\\<uuid>.<model_id>.npz` would simply not construct. The unmodified id stays
    in the file's attributes, and that is what the FR34 mismatch check compares.
    """
    return re.sub(r"[^A-Za-z0-9_.-]", "_", model_id)


class Embedder(Protocol):
    model_id: str
    model_version: str

    def encode(self, texts: list[str]) -> np.ndarray:
        """Return an (n, d) float32 array. Normalisation is this module's job."""
        ...


def _l2_normalise(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    normalised: np.ndarray = (vectors / norms).astype(np.float32)
    return normalised


@dataclass
class IndexStats:
    total: int
    reembedded: int
    reused: int
    full_rebuild: bool


class EmbeddingIndex:
    """Vectors for one note set, cached on disk beside it."""

    def __init__(self, root: Path, embedder: Embedder) -> None:
        self.dir = Path(root) / "index"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder
        self._ids: list[str] = []
        self._hashes: list[str] = []
        self._vectors: np.ndarray = np.zeros((0, 0), dtype=np.float32)

    def path_for(self, noteset_id: str) -> Path:
        return self.dir / f"{noteset_id}.{model_slug(self.embedder.model_id)}.npz"

    @property
    def vectors(self) -> np.ndarray:
        return self._vectors

    @property
    def note_ids(self) -> list[str]:
        return list(self._ids)

    def vector_for(self, note_id: str) -> np.ndarray | None:
        if note_id not in self._ids:
            return None
        vector: np.ndarray = self._vectors[self._ids.index(note_id)]
        return vector

    # ---------- cache ----------

    def _load_cache(self, noteset_id: str) -> dict[str, tuple[str, np.ndarray]] | None:
        path = self.path_for(noteset_id)
        if not path.exists():
            return None
        try:
            with np.load(path, allow_pickle=False) as data:
                if int(data["schema_version"][0]) != INDEX_SCHEMA_VERSION:
                    return None
                if str(data["embed_model_id"][0]) != self.embedder.model_id:
                    return None
                if str(data["embed_model_version"][0]) != self.embedder.model_version:
                    return None
                ids = [str(x) for x in data["note_ids"]]
                hashes = [str(x) for x in data["content_hashes"]]
                vectors = np.asarray(data["vectors"], dtype=np.float32)
        except Exception:
            # Derived data: a corrupt cache is deleted and rebuilt, never recovered
            # (FR44). There is nothing in here the user cannot regenerate.
            path.unlink(missing_ok=True)
            return None
        if not (len(ids) == len(hashes) == vectors.shape[0]):
            path.unlink(missing_ok=True)
            return None
        return {nid: (h, vectors[i]) for i, (nid, h) in enumerate(zip(ids, hashes, strict=True))}

    def _save_cache(self, noteset_id: str) -> None:
        np.savez(
            self.path_for(noteset_id),
            schema_version=np.array([INDEX_SCHEMA_VERSION]),
            embed_model_id=np.array([self.embedder.model_id]),
            embed_model_version=np.array([self.embedder.model_version]),
            embedded_at=np.array([str(time.time())]),
            note_ids=np.array(self._ids, dtype=object).astype(str),
            content_hashes=np.array(self._hashes, dtype=object).astype(str),
            vectors=self._vectors,
        )

    # ---------- build ----------

    def build(self, note_set: ContextSet, *, persist: bool = True) -> IndexStats:
        cached = self._load_cache(note_set.id)
        full_rebuild = cached is None

        ids: list[str] = []
        hashes: list[str] = []
        rows: list[np.ndarray | None] = []
        to_embed: list[tuple[int, str]] = []

        for note in note_set.notes:
            digest = note.content_hash
            ids.append(note.id)
            hashes.append(digest)
            hit = cached.get(note.id) if cached else None
            if hit is not None and hit[0] == digest:
                rows.append(hit[1])
            else:
                rows.append(None)
                to_embed.append((len(rows) - 1, note.embed_text))

        if to_embed:
            fresh = _l2_normalise(self.embedder.encode([text for _, text in to_embed]))
            for slot, (row_index, _) in enumerate(to_embed):
                rows[row_index] = fresh[slot]

        dim = rows[0].shape[0] if rows and rows[0] is not None else 0
        self._ids = ids
        self._hashes = hashes
        self._vectors = (
            np.vstack([r for r in rows if r is not None]).astype(np.float32)
            if rows
            else np.zeros((0, dim), dtype=np.float32)
        )

        if persist:
            self._save_cache(note_set.id)

        return IndexStats(
            total=len(ids),
            reembedded=len(to_embed),
            reused=len(ids) - len(to_embed),
            full_rebuild=full_rebuild,
        )
