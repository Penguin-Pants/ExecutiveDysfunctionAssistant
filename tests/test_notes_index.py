"""T3.6 — embedding index, cache keying, and the FR34 invalidation rules."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from interview_prep_recall.notes.index import (
    DEFAULT_EMBED_MODEL_ID,
    EmbeddingIndex,
    model_slug,
)
from interview_prep_recall.notes.model import ContextSet, Note


class FakeEmbedder:
    """Deterministic, dependency-free, and counts calls.

    Unit tests must not need torch (design §10). Because this satisfies the same
    Protocol as the real embedder, the swap itself is what is under test.
    """

    def __init__(self, model_id: str = DEFAULT_EMBED_MODEL_ID, model_version: str = "1.0") -> None:
        self.model_id = model_id
        self.model_version = model_version
        self.calls: list[list[str]] = []

    def encode(self, texts: list[str]) -> np.ndarray:
        self.calls.append(list(texts))
        out = np.zeros((len(texts), 8), dtype=np.float32)
        for i, text in enumerate(texts):
            digest = hashlib.sha256(text.encode()).digest()
            out[i] = np.frombuffer(digest[:32], dtype=np.uint8)[:8].astype(np.float32)
        return out

    @property
    def embedded_count(self) -> int:
        return sum(len(c) for c in self.calls)


def make_set(n: int = 3) -> ContextSet:
    return ContextSet(
        name="s", notes=[Note(headline=f"Question {i}?", body=f"Body {i}") for i in range(n)]
    )


def test_vectors_are_l2_normalised(app_data: Path) -> None:
    index = EmbeddingIndex(app_data, FakeEmbedder())
    index.build(make_set())
    norms = np.linalg.norm(index.vectors, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)


def test_only_headline_is_embedded(app_data: Path) -> None:
    """Design §4: matching is question-to-question; the body is the answer."""
    embedder = FakeEmbedder()
    ns = make_set(n=1)
    EmbeddingIndex(app_data, embedder).build(ns)
    assert embedder.calls == [["Question 0?"]]


def test_second_build_reuses_the_cache(app_data: Path) -> None:
    embedder = FakeEmbedder()
    ns = make_set()
    EmbeddingIndex(app_data, embedder).build(ns)
    assert embedder.embedded_count == 3

    fresh = EmbeddingIndex(app_data, embedder)
    stats = fresh.build(ns)
    assert stats.reembedded == 0
    assert stats.reused == 3
    assert embedder.embedded_count == 3


def test_editing_one_headline_reembeds_only_that_note(app_data: Path) -> None:
    embedder = FakeEmbedder()
    ns = make_set()
    EmbeddingIndex(app_data, embedder).build(ns)

    ns.notes[1].headline = "Completely different question?"
    stats = EmbeddingIndex(app_data, embedder).build(ns)
    assert stats.reembedded == 1
    assert stats.reused == 2


def test_editing_only_the_body_does_not_reembed(app_data: Path) -> None:
    """content_hash covers exactly the embedded text and nothing else."""
    embedder = FakeEmbedder()
    ns = make_set()
    EmbeddingIndex(app_data, embedder).build(ns)

    ns.notes[0].body = "An entirely rewritten answer."
    stats = EmbeddingIndex(app_data, embedder).build(ns)
    assert stats.reembedded == 0


def test_model_version_change_forces_full_reembed(app_data: Path) -> None:
    """FR34/BC-1: the silent-degradation path this whole module exists to close."""
    ns = make_set()
    EmbeddingIndex(app_data, FakeEmbedder(model_version="1.0")).build(ns)

    upgraded = FakeEmbedder(model_version="2.0")
    stats = EmbeddingIndex(app_data, upgraded).build(ns)
    assert stats.full_rebuild
    assert stats.reembedded == 3


def test_model_id_change_uses_a_different_cache_file(app_data: Path) -> None:
    ns = make_set()
    a = EmbeddingIndex(app_data, FakeEmbedder(model_id="model/a"))
    b = EmbeddingIndex(app_data, FakeEmbedder(model_id="model/b"))
    a.build(ns)
    b.build(ns)
    assert a.path_for(ns.id) != b.path_for(ns.id)
    assert a.path_for(ns.id).exists() and b.path_for(ns.id).exists()


def test_model_slug_is_a_legal_windows_filename() -> None:
    """Hugging Face ids contain '/', which cannot appear in a Windows filename."""
    slug = model_slug("sentence-transformers/all-MiniLM-L6-v2")
    assert "/" not in slug and "\\" not in slug and ":" not in slug
    assert slug == "sentence-transformers_all-MiniLM-L6-v2"


def test_corrupt_cache_is_deleted_and_rebuilt(app_data: Path) -> None:
    """Derived data: FR44 says rebuild, not recover."""
    embedder = FakeEmbedder()
    ns = make_set()
    index = EmbeddingIndex(app_data, embedder)
    index.build(ns)
    path = index.path_for(ns.id)
    path.write_bytes(b"not an npz at all")

    stats = EmbeddingIndex(app_data, embedder).build(ns)
    assert stats.full_rebuild
    assert stats.reembedded == 3
    assert path.exists()


def test_deleted_note_leaves_the_index(app_data: Path) -> None:
    embedder = FakeEmbedder()
    ns = make_set()
    index = EmbeddingIndex(app_data, embedder)
    index.build(ns)

    dead = ns.notes[0].id
    ns.delete(dead)
    index.build(ns)
    assert dead not in index.note_ids
    assert index.vectors.shape[0] == 2


def test_vector_lookup_by_note_id(app_data: Path) -> None:
    index = EmbeddingIndex(app_data, FakeEmbedder())
    ns = make_set()
    index.build(ns)
    vec = index.vector_for(ns.notes[1].id)
    assert vec is not None and vec.shape == (8,)
    assert index.vector_for("no-such-id") is None


def test_empty_note_set_builds_without_error(app_data: Path) -> None:
    index = EmbeddingIndex(app_data, FakeEmbedder())
    stats = index.build(ContextSet(name="empty"))
    assert stats.total == 0
    assert index.vectors.shape[0] == 0
