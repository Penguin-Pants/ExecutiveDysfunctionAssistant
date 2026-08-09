"""Note and NoteSet models (T3.1, FR41–FR43).

Identity rules (FR41): note IDs and note-set IDs are UUID4, assigned at creation,
stable across edits and reorders, never reused after deletion. The note-set ID is also
its filename and its embedding-cache key, which is why it needs the same guarantee the
note IDs get.

Embedding rule (design §4): only `headline` is embedded, and `content_hash` covers
exactly that text and nothing else. Matching is question-to-question — the headline is
the anticipated question, while `body` is the prepared answer. Hashing more than what
is embedded would re-embed on irrelevant edits; hashing less would miss real ones,
silently reintroducing the BC-1 stale-vector failure FR34 exists to prevent.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = 1


def new_id() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def content_hash(headline: str) -> str:
    """SHA-256 of exactly the embedded text (design §4)."""
    return hashlib.sha256(headline.encode("utf-8")).hexdigest()


@dataclass
class Note:
    headline: str
    body: str = ""
    bullets: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    track_progress: bool = False
    id: str = field(default_factory=new_id)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    @property
    def embed_text(self) -> str:
        return self.headline

    @property
    def content_hash(self) -> str:
        return content_hash(self.embed_text)

    @property
    def is_overlay_optimised(self) -> bool:
        """False triggers the D-6 truncation path and the editor's advisory flag."""
        return bool(self.bullets)

    def verify_bullets_verbatim(self) -> None:
        """FR42: every bullet must be a byte-exact substring of the note.

        Called on save. The overlay renders bullets directly, so a bullet that is not
        verbatim source text is generated content reaching the screen — the one thing
        the retrieval-only principle forbids.
        """
        haystack = f"{self.headline}\n{self.body}"
        for bullet in self.bullets:
            if bullet not in haystack:
                raise ValueError(
                    f"bullet {bullet[:40]!r} is not a verbatim substring of note {self.id}"
                )

    def touch(self) -> Note:
        return replace(self, updated_at=_now())

    def to_dict(self, order_index: int) -> dict[str, Any]:
        return {
            "id": self.id,
            "headline": self.headline,
            "bullets": list(self.bullets),
            "body": self.body,
            "tags": list(self.tags),
            "order_index": order_index,
            "track_progress": self.track_progress,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Note:
        return cls(
            id=data["id"],
            headline=data["headline"],
            body=data.get("body", ""),
            bullets=list(data.get("bullets", [])),
            tags=list(data.get("tags", [])),
            track_progress=bool(data.get("track_progress", False)),
            created_at=data.get("created_at", _now()),
            updated_at=data.get("updated_at", _now()),
        )


@dataclass
class NoteSet:
    name: str
    notes: list[Note] = field(default_factory=list)
    id: str = field(default_factory=new_id)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        self._assert_unique_ids()

    def _assert_unique_ids(self) -> None:
        seen: set[str] = set()
        for note in self.notes:
            if note.id in seen:
                raise ValueError(f"duplicate note id {note.id} in note set {self.id}")
            seen.add(note.id)

    def get(self, note_id: str) -> Note | None:
        return next((n for n in self.notes if n.id == note_id), None)

    def add(self, note: Note) -> None:
        if self.get(note.id) is not None:
            raise ValueError(f"note id {note.id} already present")
        self.notes.append(note)
        self.updated_at = _now()

    def delete(self, note_id: str) -> bool:
        before = len(self.notes)
        self.notes = [n for n in self.notes if n.id != note_id]
        changed = len(self.notes) != before
        if changed:
            self.updated_at = _now()
        return changed

    def reorder(self, ordered_ids: list[str]) -> None:
        """Reorder by ID. IDs are unaffected (FR3/FR41) — position is not identity."""
        if set(ordered_ids) != {n.id for n in self.notes}:
            raise ValueError("reorder must list exactly the current note ids")
        by_id = {n.id: n for n in self.notes}
        self.notes = [by_id[i] for i in ordered_ids]
        self.updated_at = _now()

    def tracked(self) -> list[Note]:
        """FR12 checklist membership."""
        return [n for n in self.notes if n.track_progress]

    def verify(self) -> None:
        self._assert_unique_ids()
        for note in self.notes:
            note.verify_bullets_verbatim()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "notes": [n.to_dict(i) for i, n in enumerate(self.notes)],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NoteSet:
        raw = data.get("notes", [])
        # order_index is authoritative on load; array order is a serialisation detail.
        ordered = sorted(raw, key=lambda d: d.get("order_index", 0))
        return cls(
            id=data["id"],
            name=data["name"],
            created_at=data.get("created_at", _now()),
            updated_at=data.get("updated_at", _now()),
            notes=[Note.from_dict(d) for d in ordered],
        )
