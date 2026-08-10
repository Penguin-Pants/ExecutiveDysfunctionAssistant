"""T3.1–T3.4 — model, atomic write, rotation, schema guard, recovery, export."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from interview_prep_recall.notes.model import SCHEMA_VERSION, ContextSet, Note
from interview_prep_recall.notes.store import (
    BACKUP_DEPTH,
    NoteSetCorruptError,
    NotesStore,
    SchemaTooNewError,
)


def make_set(name: str = "Acme — Senior PM", n: int = 3) -> ContextSet:
    return ContextSet(
        name=name,
        notes=[
            Note(
                headline=f"Tell me about situation {i}?",
                body=f"Body number {i}. It has two sentences here.",
                bullets=[f"Body number {i}."],
                tags=["conflict"],
                track_progress=(i == 0),
            )
            for i in range(n)
        ],
    )


# ---------- T3.1 model / identity ----------


def test_ids_are_uuid4_and_distinct() -> None:
    ns = make_set()
    assert len({n.id for n in ns.notes}) == len(ns.notes)
    assert len(ns.id) == 36


def test_ids_stable_across_edit_and_reorder(app_data: Path) -> None:
    """FR3/FR41: position is not identity."""
    store = NotesStore(app_data)
    ns = make_set()
    before = [n.id for n in ns.notes]
    store.save(ns)

    ns.notes[0].headline = "Rewritten headline?"
    ns.reorder(list(reversed(before)))
    store.save(ns)

    reloaded = store.load(ns.id)
    assert [n.id for n in reloaded.notes] == list(reversed(before))
    assert reloaded.notes[-1].headline == "Rewritten headline?"


def test_deleted_ids_are_never_reused() -> None:
    ns = make_set(n=1)
    dead = ns.notes[0].id
    ns.delete(dead)
    for _ in range(100):
        ns.add(Note(headline="q?"))
    assert dead not in {n.id for n in ns.notes}


def test_order_index_is_authoritative_on_load(app_data: Path) -> None:
    store = NotesStore(app_data)
    ns = make_set()
    store.save(ns)
    raw = json.loads(store.path_for(ns.id).read_text())
    raw["notes"].reverse()  # array order now disagrees with order_index
    store.path_for(ns.id).write_text(json.dumps(raw))
    assert [n.id for n in store.load(ns.id).notes] == [n.id for n in ns.notes]


def test_non_verbatim_bullet_is_refused(app_data: Path) -> None:
    """FR42: generated text must never reach disk, let alone the overlay."""
    ns = make_set(n=1)
    ns.notes[0].bullets = ["A summary the user never wrote"]
    with pytest.raises(ValueError, match="verbatim"):
        NotesStore(app_data).save(ns)


# ---------- T3.2 atomic write + rotation ----------


def test_save_and_load_round_trip(app_data: Path) -> None:
    store = NotesStore(app_data)
    ns = make_set()
    store.save(ns)
    assert store.load(ns.id).to_dict() == ns.to_dict()


def test_rotation_keeps_five_generations(app_data: Path) -> None:
    store = NotesStore(app_data)
    ns = make_set(n=1)
    for i in range(8):
        ns.notes[0].headline = f"version {i}?"
        ns.notes[0].bullets = []
        store.save(ns)
    gens = [b.generation for b in store.list_backups(ns.id)]
    assert gens == list(range(1, BACKUP_DEPTH + 1))
    assert store.load(ns.id).notes[0].headline == "version 7?"
    # .bak.1 is the immediately previous version.
    assert store._load_path(store.backup_path(ns.id, 1)).notes[0].headline == "version 6?"


def test_live_file_exists_at_every_point_of_rotation(app_data: Path) -> None:
    """FR28: rotation copies rather than renames, so there is no gap with no live file."""
    store = NotesStore(app_data)
    ns = make_set(n=1)
    store.save(ns)
    target = store.path_for(ns.id)

    real_copy = __import__("shutil").copy2
    seen: list[bool] = []

    def spy(src, dst, *a, **k):  # type: ignore[no-untyped-def]
        seen.append(target.exists())
        return real_copy(src, dst, *a, **k)

    import shutil

    original = shutil.copy2
    shutil.copy2 = spy  # type: ignore[assignment]
    try:
        ns.notes[0].headline = "second?"
        store.save(ns)
    finally:
        shutil.copy2 = original  # type: ignore[assignment]

    assert seen and all(seen), "live file vanished during rotation"


def test_survives_hard_kill_during_save(tmp_path: Path) -> None:
    """The review's highest-severity criterion, in its automatable form.

    A real `taskkill /F` run belongs on the Windows machine (T3.2). Here we kill the
    interpreter with SIGKILL mid-save, ten consecutive times, and require the notes to
    load intact every single time.
    """
    root = tmp_path / "app"
    script = textwrap.dedent(f"""
        import os, sys, time, threading
        sys.path.insert(0, {str(Path.cwd())!r})
        from pathlib import Path
        from interview_prep_recall.notes.store import NotesStore
        from interview_prep_recall.notes.model import Note, ContextSet

        store = NotesStore(Path({str(root)!r}))
        ns = ContextSet(name="kill-test", id="11111111-2222-3333-4444-555555555555",
                     notes=[Note(headline="q %d?" % i, body="b") for i in range(50)])
        store.save(ns)
        threading.Timer(0.02, lambda: os.kill(os.getpid(), 9)).start()
        for i in range(4000):
            ns.notes[0].headline = "iteration %d?" % i
            store.save(ns)
    """)
    script_path = tmp_path / "killer.py"
    script_path.write_text(script)

    for attempt in range(10):
        subprocess.run([sys.executable, str(script_path)], capture_output=True, timeout=60)
        store = NotesStore(root)
        loaded = store.load("11111111-2222-3333-4444-555555555555")
        assert len(loaded.notes) == 50, f"notes damaged on attempt {attempt}"
        # No temp file should be mistaken for the real thing.
        assert not list((root / "notesets").glob("*.tmp"))


# ---------- T3.3 schema guard + corruption ----------


def test_newer_schema_is_refused_and_file_untouched(app_data: Path) -> None:
    store = NotesStore(app_data)
    ns = make_set()
    path = store.save(ns)
    raw = json.loads(path.read_text())
    raw["schema_version"] = SCHEMA_VERSION + 1
    path.write_text(json.dumps(raw))
    before = path.read_bytes()

    with pytest.raises(SchemaTooNewError, match="Refusing to parse"):
        store.load(ns.id)
    assert path.read_bytes() == before


def test_newer_schema_never_triggers_auto_recovery(app_data: Path) -> None:
    """Silently restoring an old backup over a newer file would destroy real data."""
    store = NotesStore(app_data)
    ns = make_set()
    store.save(ns)
    store.save(ns)  # create a backup generation
    path = store.path_for(ns.id)
    raw = json.loads(path.read_text())
    raw["schema_version"] = SCHEMA_VERSION + 1
    path.write_text(json.dumps(raw))

    with pytest.raises(SchemaTooNewError):
        store.load_or_recover(ns.id)


@pytest.mark.parametrize("corruption", ["truncate", "not-json", "no-version", "not-object"])
def test_corrupt_file_recovers_from_backup(app_data: Path, corruption: str) -> None:
    store = NotesStore(app_data)
    ns = make_set()
    store.save(ns)
    ns.notes[0].headline = "second version?"
    ns.notes[0].bullets = []
    store.save(ns)

    path = store.path_for(ns.id)
    text = path.read_text()
    payload = {
        "truncate": text[: len(text) // 2],
        "not-json": "{{{ not json",
        "no-version": json.dumps({"id": ns.id, "name": "x", "notes": []}),
        "not-object": json.dumps([1, 2, 3]),
    }[corruption]
    path.write_text(payload)

    recovered, was_recovered = store.load_or_recover(ns.id)
    assert was_recovered
    assert len(recovered.notes) == 3


def test_missing_file_is_treated_as_recoverable(app_data: Path) -> None:
    store = NotesStore(app_data)
    ns = make_set()
    store.save(ns)
    store.save(ns)
    store.path_for(ns.id).unlink()
    recovered, was_recovered = store.load_or_recover(ns.id)
    assert was_recovered and len(recovered.notes) == 3


def test_falls_through_to_the_next_readable_backup(app_data: Path) -> None:
    """A corrupt backup is not a dead end — that is why five are kept."""
    store = NotesStore(app_data)
    ns = make_set()
    store.save(ns)
    store.save(ns)
    store.save(ns)

    store.backup_path(ns.id, 1).write_text("{{ corrupt")
    store.path_for(ns.id).write_text("{{ also corrupt")

    recovered, _ = store.load_or_recover(ns.id)
    assert len(recovered.notes) == 3


def test_no_readable_backup_raises_rather_than_starting_empty(app_data: Path) -> None:
    store = NotesStore(app_data)
    ns = make_set()
    store.save(ns)
    store.path_for(ns.id).write_text("{{ corrupt")
    with pytest.raises(NoteSetCorruptError):
        store.load_or_recover(ns.id)


# ---------- T3.4 export / import ----------


def test_export_import_round_trip_is_lossless(app_data: Path, tmp_path: Path) -> None:
    store = NotesStore(app_data)
    ns = make_set()
    store.save(ns)

    dest = tmp_path / "export"
    json_path, md_path = store.export_bundle(ns, dest)

    for path in store.notesets_dir.glob("*"):
        path.unlink()

    reimported = store.import_bundle(json_path)
    assert reimported.to_dict() == ns.to_dict()
    assert md_path.read_text().startswith("# Acme")


def test_export_preserves_tags_bullets_and_order(app_data: Path, tmp_path: Path) -> None:
    store = NotesStore(app_data)
    ns = make_set()
    out, _ = store.export_bundle(ns, tmp_path / "e")
    back = store.import_bundle(out)
    assert [n.tags for n in back.notes] == [n.tags for n in ns.notes]
    assert [n.bullets for n in back.notes] == [n.bullets for n in ns.notes]
    assert [n.id for n in back.notes] == [n.id for n in ns.notes]
    assert [n.track_progress for n in back.notes] == [n.track_progress for n in ns.notes]


def test_store_writes_only_under_its_root(app_data: Path) -> None:
    """The autouse allowlist already enforces this; asserted explicitly for FR16."""
    store = NotesStore(app_data)
    ns = make_set()
    store.save(ns)
    written = {p.resolve() for p in app_data.rglob("*") if p.is_file()}
    assert written
    assert all(str(p).startswith(str(app_data.resolve()) + os.sep) for p in written)


# ---- path-safety and corruption boundaries (from PR review) ----


def test_non_uuid_noteset_id_is_rejected() -> None:
    """A JSON-controlled id reaches `path_for`, so it must be validated first."""
    from interview_prep_recall.notes.model import InvalidIdError

    with pytest.raises(InvalidIdError):
        ContextSet(name="evil", id="../../escaped")


def test_traversal_id_in_an_imported_bundle_cannot_escape(app_data: Path, tmp_path: Path) -> None:
    """The concrete attack: import a crafted bundle, then save writes outside the root."""
    from interview_prep_recall.notes.store import NoteSetCorruptError

    crafted = tmp_path / "crafted.json"
    crafted.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "id": "../../escaped",
                "name": "evil",
                "notes": [],
            }
        )
    )
    store = NotesStore(app_data)
    with pytest.raises(NoteSetCorruptError):
        store.import_bundle(crafted)


def test_non_uuid_note_id_is_rejected() -> None:
    from interview_prep_recall.notes.model import InvalidIdError

    with pytest.raises(InvalidIdError):
        Note(headline="q?", id="not-a-uuid")


def test_missing_notes_key_is_corruption_not_an_empty_set(app_data: Path) -> None:
    """Otherwise the UI shows every note deleted and recovery is never offered."""
    store = NotesStore(app_data)
    ns = make_set()
    store.save(ns)
    store.save(ns)

    path = store.path_for(ns.id)
    raw = json.loads(path.read_text())
    del raw["notes"]
    path.write_text(json.dumps(raw))

    with pytest.raises(NoteSetCorruptError):
        store.load(ns.id)

    recovered, was_recovered = store.load_or_recover(ns.id)
    assert was_recovered and len(recovered.notes) == 3


def test_malformed_notes_value_is_corruption(app_data: Path) -> None:
    store = NotesStore(app_data)
    ns = make_set()
    store.save(ns)
    path = store.path_for(ns.id)
    raw = json.loads(path.read_text())
    raw["notes"] = {"not": "a list"}
    path.write_text(json.dumps(raw))
    with pytest.raises(NoteSetCorruptError):
        store.load(ns.id)


@pytest.mark.parametrize(
    "name", ["Product / Program Manager", "../escape", "Acme: Senior PM", "  ..  "]
)
def test_export_filenames_are_sanitised(app_data: Path, tmp_path: Path, name: str) -> None:
    """Names are free text; a role title with a slash is ordinary, not an attack."""
    store = NotesStore(app_data)
    ns = make_set(name=name)
    dest = tmp_path / "export"
    json_path, md_path = store.export_bundle(ns, dest)

    for path in (json_path, md_path):
        assert path.parent.resolve() == dest.resolve()
        assert path.exists()
    # The original name survives inside the content, only the filename is normalised.
    assert store.import_bundle(json_path).name == name
