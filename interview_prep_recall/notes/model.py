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
from enum import Enum
from typing import Any

SCHEMA_VERSION = 2
"""v2 adds `SourceKind`. The v1 -> v2 migration lives in `store.py`'s MIGRATIONS."""


class SourceKind(Enum):
    """The five context categories (FR66).

    One shared chunk type carrying a kind, rather than five parallel models: the
    embedding index, prefilter and stage-2 selector then need a category dimension and
    nothing else. Five models would mean five of everything downstream.
    """

    COMPANY = "company"
    ROLE = "role"
    """The job description."""

    INTERVIEWER = "interviewer"
    PREP = "prep"
    RESUME = "resume"


TRACKABLE_KINDS = frozenset({SourceKind.PREP, SourceKind.RESUME})
"""FR70. A job-description requirement is not something you "cover" by speaking, so
letting it onto the checklist would tick off points the user never made — the FR56
failure, arriving through the data model instead of through the mic."""


def new_id() -> str:
    return str(uuid.uuid4())


class InvalidIdError(ValueError):
    """An id that is not a UUID reached a boundary that builds a filesystem path.

    Note-set ids are interpolated into filenames by both the store and the embedding
    index, so an id like `../../escaped` from an imported bundle would place a later
    save outside the application root. Ids arrive from JSON that the user may have
    edited or received from someone else, so "we always generate them" is not a
    guarantee — it is an assumption about a file we do not control.
    """


def validate_id(value: str, *, label: str = "id") -> str:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise InvalidIdError(f"{label} {value!r} is not a valid UUID") from exc
    if str(parsed) != value:
        raise InvalidIdError(f"{label} {value!r} is not in canonical UUID form")
    return value


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _trackable_on_load(track_progress: bool, kind: SourceKind) -> bool:
    """FR70 on the load path: **coerce, do not reject.**

    Constructing a `Note` with `track_progress` on an untrackable kind raises, and that
    is right for code — it is a bug at the call site. On load it would be a disaster:
    `ContextSet.from_dict` turns the ValueError into `NoteSetCorruptError`, so one
    stray flag on one chunk would make the user's entire note set unloadable and send
    them to backup recovery.

    FR70's purpose is that an untrackable kind never reaches the checklist. Dropping the
    flag achieves exactly that; refusing the file achieves it at the cost of everything
    else in the file. Coercion is silent-fixing, which this codebase usually distrusts —
    the difference is that the safe interpretation here is unambiguous and the
    alternative destroys access to data.
    """
    return track_progress and kind in TRACKABLE_KINDS


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
    kind: SourceKind = SourceKind.PREP
    """FR67, immutable after creation. Defaults to PREP so v1 notes and any code that
    predates kinds keep their existing behaviour rather than silently changing category."""

    id: str = field(default_factory=new_id)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        # Validated at construction, not only on load: FR41 makes UUID4 a property of
        # every note id, and a note built in code can reach a ContextSet, an index key,
        # or a stage-2 enum just as easily as one parsed from a file.
        validate_id(self.id, label="note id")
        self._assert_trackable()
        object.__setattr__(self, "_kind_locked", True)

    def _assert_trackable(self) -> None:
        if self.track_progress and self.kind not in TRACKABLE_KINDS:
            raise ValueError(
                f"track_progress is not permitted on a {self.kind.value} chunk (FR70) — "
                "only prep notes and resume entries are talking points you cover by speaking"
            )

    def __setattr__(self, name: str, value: Any) -> None:
        """Enforces FR67 (kind is immutable) and FR70 (what may be tracked).

        On the setter rather than only at construction, because a chunk's kind drives
        its threshold, its enum quota and its tracker eligibility. Mutating it in place
        would move the chunk between all three regimes while its embedding — keyed on
        the note id — stayed exactly where it was.
        """
        locked = getattr(self, "_kind_locked", False)
        if name == "kind" and locked:
            raise ValueError(
                f"kind is immutable (FR67); reclassifying note {self.id} means deleting "
                "and re-importing it, so the index is rebuilt with it"
            )
        # Validated **before** the assignment commits. Assigning first and checking
        # after leaves the rejected value in place for any caller that catches the
        # error: the note stays tracked, `tracked()` returns it, and the checklist ticks
        # off a job-description requirement the user never spoke — FR70 violated by the
        # code written to enforce it.
        if name == "track_progress" and locked and value and self.kind not in TRACKABLE_KINDS:
            raise ValueError(
                f"track_progress is not permitted on a {self.kind.value} chunk (FR70) — "
                "only prep notes and resume entries are talking points you cover by speaking"
            )
        object.__setattr__(self, name, value)

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
            "kind": self.kind.value,
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
            id=validate_id(data["id"], label="note id"),
            headline=data["headline"],
            body=data.get("body", ""),
            bullets=list(data.get("bullets", [])),
            tags=list(data.get("tags", [])),
            track_progress=_trackable_on_load(
                bool(data.get("track_progress", False)),
                SourceKind(data.get("kind", SourceKind.PREP.value)),
            ),
            kind=SourceKind(data.get("kind", SourceKind.PREP.value)),
            created_at=data.get("created_at", _now()),
            updated_at=data.get("updated_at", _now()),
        )


@dataclass
class ContextSet:
    """One interview's context, across all five kinds (FR66).

    A flat chunk list rather than five nested documents: "the job description" is
    exactly "every chunk of kind ROLE", so a separate container would be a second
    source of truth about membership, and the two would eventually disagree. Per-kind
    import, edit and removal are `by_kind` and `remove_kind` over the one list.
    """

    name: str
    notes: list[Note] = field(default_factory=list)
    id: str = field(default_factory=new_id)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    migrated_from: int | None = field(default=None, compare=False)
    """Schema version this set was upgraded from on load, or None (FR73c).

    Provenance of *this load*, not of the set, so it is deliberately excluded from
    `to_dict` and from equality — saving it back would make it look like a property of
    the data. It rides on the object rather than being returned alongside it because a
    caller that ignores an extra return value silently loses the notice, and FR73c's
    requirement is precisely that the migration is not silent.
    """

    def __post_init__(self) -> None:
        validate_id(self.id, label="note set id")
        for note in self.notes:
            validate_id(note.id, label="note id")
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
        """FR12 checklist membership. FR70 is enforced at the `Note` boundary, so
        anything with `track_progress` set is already a permitted kind."""
        return [n for n in self.notes if n.track_progress]

    def by_kind(self, kind: SourceKind) -> list[Note]:
        return [n for n in self.notes if n.kind is kind]

    def kinds_present(self) -> set[SourceKind]:
        """FR73: any subset is a complete set. Absent kinds degrade matching, never
        block a session."""
        return {n.kind for n in self.notes}

    def remove_kind(self, kind: SourceKind) -> int:
        """Remove one whole source. Returns how many chunks went.

        FR66's "without touching the others" is the point: this filters rather than
        rebuilding, so every surviving note keeps its identity and its cached vector.
        """
        before = len(self.notes)
        self.notes = [n for n in self.notes if n.kind is not kind]
        removed = before - len(self.notes)
        if removed:
            self.updated_at = _now()
        return removed

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
    def from_dict(cls, data: dict[str, Any]) -> ContextSet:
        # A missing or mistyped `notes` key is corruption, not an empty note set.
        # Defaulting to [] would make load_or_recover report success, skip the
        # backups entirely, and show the user every note deleted — the precise
        # opposite of FR44's never-start-empty guarantee.
        if "notes" not in data:
            raise ValueError("note set has no 'notes' key")
        raw = data["notes"]
        if not isinstance(raw, list):
            raise ValueError(f"'notes' must be a list, got {type(raw).__name__}")
        # order_index is authoritative on load; array order is a serialisation detail.
        ordered = sorted(raw, key=lambda d: d.get("order_index", 0))
        return cls(
            id=validate_id(data["id"], label="note set id"),
            name=data["name"],
            created_at=data.get("created_at", _now()),
            updated_at=data.get("updated_at", _now()),
            notes=[Note.from_dict(d) for d in ordered],
        )
