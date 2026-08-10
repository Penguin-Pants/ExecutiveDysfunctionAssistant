"""Note set persistence (T3.2–T3.4).

The safety review's highest-severity finding: prep notes are the only irreplaceable
asset in the system, and losing them the night before an interview destroys the entire
value of the product at the moment it is needed. Everything here exists for that.

Write sequence (FR28), and the order matters:

    write tmp → flush → fsync → rotate backups by COPY → os.replace(tmp, target)

Rotation **copies** rather than renames. An earlier draft of the spec renamed
`target → .bak.1`, which leaves a window where no live file exists at all — directly
contradicting the rationale it was written to support. The extra copy costs a few
milliseconds on a file of a few thousand words and buys the property that a crash at
any instant leaves either the old file or the new one intact, never neither.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from interview_prep_recall.notes.model import SCHEMA_VERSION, ContextSet

BACKUP_DEPTH = 5
"""FR29."""

_UNSAFE_STEM = re.compile(r"[^A-Za-z0-9 ._-]")


def safe_stem(name: str, fallback: str) -> str:
    """Filename stem from a user-chosen note-set name.

    Names are free text and routinely contain path characters — "Product / Program
    Manager" is an ordinary role title, not an attack. Unsanitised it becomes a
    subdirectory that does not exist, and an imported name containing `../` escapes
    the destination the user picked. The original name is preserved inside the
    exported content; only the filename is normalised.
    """
    cleaned = _UNSAFE_STEM.sub("_", name).strip(" .")
    return cleaned or fallback


class NotesStoreError(Exception):
    pass


class SchemaTooNewError(NotesStoreError):
    """FR31: refuse cleanly rather than best-effort parsing a future format."""


class NoteSetCorruptError(NotesStoreError):
    """FR44: corrupt, unparseable, or missing. Callers offer restore-from-backup."""


Migration = Callable[[dict[str, Any]], dict[str, Any]]


def _migrate_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """v1 had no `SourceKind`. Every v1 note becomes `PREP` (FR73a, D-33).

    `PREP` is the only mapping that preserves behaviour: v1 notes were trackable talking
    points, and prep is one of the two kinds FR70 still permits tracking on. Any other
    target would silently switch off the progress tracker for every existing user.

    **IDs are carried through untouched**, which is the load-bearing part. The embedding
    cache is keyed on note id (FR34), so minting new ones here would silently invalidate
    every stored vector and force a full re-embed that looks like a performance bug
    rather than a migration.

    Notes that already carry a `kind` are left alone rather than overwritten — a v1 file
    should not have one, but a hand-edited or partially-migrated file might, and
    clobbering it would be a lossy read of exactly the sort `SchemaTooNewError` exists
    to refuse.
    """
    notes = data.get("notes")
    if not isinstance(notes, list):
        # Not this function's job to diagnose. Leave it for `ContextSet.from_dict`,
        # which raises the corruption that routes to backup recovery (FR44). Silently
        # substituting [] here would make a damaged file migrate "successfully" into an
        # empty note set — the failure FR44 exists to prevent, one layer earlier.
        return data
    migrated = dict(data)
    migrated["notes"] = [
        note if not isinstance(note, dict) or "kind" in note else {**note, "kind": "prep"}
        for note in notes
    ]
    migrated["schema_version"] = 2
    return migrated


MIGRATIONS: dict[int, Migration] = {1: _migrate_v1_to_v2}
"""Forward-only `v{n} -> v{n+1}`, applied in sequence on load (design §4).

The hook existed from the first release because retrofitting a migration path onto a
format already in users' hands is how data gets lost. v1 -> v2 is the first user of it.
"""


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    generation: int
    readable: bool


class NotesStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.notesets_dir = self.root / "notesets"
        self.notesets_dir.mkdir(parents=True, exist_ok=True)
        self._sweep_stale_temp_files()

    def _sweep_stale_temp_files(self) -> int:
        """Remove `.tmp` files orphaned by a crash mid-write.

        `os.replace` is atomic, so a temp file surviving means the process died before
        the swap — the live file is intact and the temp holds a partial write with no
        value. Without this sweep they accumulate silently, one per crash, forever.
        Found by the SIGKILL test: the durability guarantee held, the housekeeping did
        not.
        """
        removed = 0
        for stale in self.notesets_dir.glob("*.tmp"):
            try:
                stale.unlink()
                removed += 1
            except OSError:
                pass
        return removed

    # ---------- paths ----------

    def path_for(self, noteset_id: str) -> Path:
        return self.notesets_dir / f"{noteset_id}.json"

    def backup_path(self, noteset_id: str, generation: int) -> Path:
        return self.notesets_dir / f"{noteset_id}.json.bak.{generation}"

    def list_ids(self) -> list[str]:
        return sorted(p.stem for p in self.notesets_dir.glob("*.json"))

    # ---------- write ----------

    def save(self, note_set: ContextSet) -> Path:
        note_set.verify()  # FR42: no non-verbatim bullet ever reaches disk
        target = self.path_for(note_set.id)
        payload = json.dumps(note_set.to_dict(), indent=2, ensure_ascii=False)

        tmp = target.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())

        self._rotate_backups(note_set.id)
        os.replace(tmp, target)  # atomic on NTFS and POSIX
        return target

    def _rotate_backups(self, noteset_id: str) -> None:
        target = self.path_for(noteset_id)
        for generation in range(BACKUP_DEPTH - 1, 0, -1):
            src = self.backup_path(noteset_id, generation)
            if src.exists():
                shutil.copy2(src, self.backup_path(noteset_id, generation + 1))
        if target.exists():
            # COPY, never rename: the live file must exist at every instant.
            shutil.copy2(target, self.backup_path(noteset_id, 1))

    # ---------- read ----------

    def load(self, noteset_id: str) -> ContextSet:
        return self._load_path(self.path_for(noteset_id))

    def _load_path(self, path: Path) -> ContextSet:
        if not path.exists():
            raise NoteSetCorruptError(f"{path.name} is missing")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise NoteSetCorruptError(f"{path.name} is unparseable: {exc}") from exc
        if not isinstance(data, dict):
            raise NoteSetCorruptError(f"{path.name} is not an object")
        return self._from_versioned(data, path.name)

    @staticmethod
    def _from_versioned(data: dict[str, Any], label: str) -> ContextSet:
        version = data.get("schema_version")
        if not isinstance(version, int):
            raise NoteSetCorruptError(f"{label} has no usable schema_version")
        if version > SCHEMA_VERSION:
            raise SchemaTooNewError(
                f"{label} is schema_version {version}; this build understands "
                f"{SCHEMA_VERSION}. Refusing to parse — upgrade the app rather than "
                "risk a lossy read. The file has not been modified."
            )
        loaded_as = version
        while version < SCHEMA_VERSION:
            migrate = MIGRATIONS.get(version)
            if migrate is None:
                raise NoteSetCorruptError(f"{label}: no migration from schema_version {version}")
            data = migrate(data)
            version += 1
        try:
            context_set = ContextSet.from_dict(data)
        except (KeyError, TypeError, ValueError) as exc:
            raise NoteSetCorruptError(f"{label} is structurally invalid: {exc}") from exc
        # FR73c: the migration is stated to the user, not silent. Without this the load
        # returns a plain ContextSet and no caller can tell an upgraded file from an
        # ordinary one, which makes the notice unimplementable rather than merely unbuilt.
        if loaded_as < SCHEMA_VERSION:
            context_set.migrated_from = loaded_as
        return context_set

    # ---------- recovery (FR29, FR44) ----------

    def list_backups(self, noteset_id: str) -> list[BackupInfo]:
        infos: list[BackupInfo] = []
        for generation in range(1, BACKUP_DEPTH + 1):
            path = self.backup_path(noteset_id, generation)
            if not path.exists():
                continue
            try:
                self._load_path(path)
                readable = True
            except NotesStoreError:
                readable = False
            infos.append(BackupInfo(path=path, generation=generation, readable=readable))
        return infos

    def restore_latest_readable(self, noteset_id: str) -> ContextSet:
        """Fall through generations until one parses (T3.9).

        A corrupt backup is not a dead end — that is the whole point of keeping five.
        """
        errors: list[str] = []
        for info in self.list_backups(noteset_id):
            if not info.readable:
                errors.append(f"gen {info.generation}: unreadable")
                continue
            note_set = self._load_path(info.path)
            self.save(note_set)
            return note_set
        raise NoteSetCorruptError(
            f"no readable backup for {noteset_id} ({'; '.join(errors) or 'none exist'})"
        )

    def load_or_recover(self, noteset_id: str) -> tuple[ContextSet, bool]:
        """Returns (note_set, recovered). Never silently starts empty (FR44)."""
        try:
            return self.load(noteset_id), False
        except SchemaTooNewError:
            raise  # never auto-recover past a newer format; that would lose the user's data
        except NoteSetCorruptError:
            return self.restore_latest_readable(noteset_id), True

    # ---------- export / import (FR30) ----------

    def export_bundle(self, note_set: ContextSet, dest_dir: Path) -> tuple[Path, Path]:
        """Write a `.json` + human-readable `.md` pair to a user-chosen directory.

        Deliberately outside the FR16 allowlist: this is the user exercising FR30, not
        the app writing on its own. The privacy gate runs without invoking it.
        """
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        stem = safe_stem(note_set.name, fallback=note_set.id)
        json_path = dest_dir / f"{stem}.json"
        md_path = dest_dir / f"{stem}.md"

        json_path.write_text(
            json.dumps(note_set.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )

        lines = [f"# {note_set.name}", ""]
        for note in note_set.notes:
            lines.append(f"## {note.headline}")
            if note.tags:
                lines.append(f"_tags: {', '.join(note.tags)}_")
            lines.append("")
            for bullet in note.bullets:
                lines.append(f"- {bullet}")
            if note.bullets:
                lines.append("")
            if note.body:
                lines.extend([note.body, ""])
        md_path.write_text("\n".join(lines), encoding="utf-8")
        return json_path, md_path

    def import_bundle(self, json_path: Path) -> ContextSet:
        """Lossless inverse of `export_bundle`'s JSON half (FR30)."""
        return self._load_path(Path(json_path))
