"""T3.9 — backup restore (FR29, FR44).

FR29 keeps five generations and says they are **restorable from the UI**; FR44 says a
corrupt set *offers restore* rather than failing silently or starting empty. The rotation
and the fall-through were built in T3.2/T3.3 with passing tests, and nothing in the
product ever opened them — a backup that cannot be reached is a file, not a recovery.

The tests here are about the properties that make a restore safe to click: previewing
never writes, a corrupt generation is not the end of the list, and restoring the active
set re-points everything that reads it rather than only rewriting the file.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from helpers import ReversingCipher, ScriptedClient

pytest.importorskip("PySide6", reason="Qt UI tests require the [ui] extra")

from PySide6.QtWidgets import QApplication  # noqa: E402

from interview_prep_recall.app import Application  # noqa: E402
from interview_prep_recall.notes.model import ContextSet, Note, SourceKind  # noqa: E402
from interview_prep_recall.notes.store import (  # noqa: E402
    NotesStore,
    NotesStoreError,
    SchemaTooNewError,
)
from interview_prep_recall.ui.editor import (  # noqa: E402
    ACTIVE_SET_KEY,
    NotesEditor,
    load_active_set,
)
from interview_prep_recall.ui.restore import (  # noqa: E402
    NO_BACKUPS_TEXT,
    RestoreDialog,
    describe,
)


class FlatEmbedder:
    model_id = "flat/one"
    model_version = "1.0"

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.ones((len(texts), 2), dtype=np.float32)


class FakeSettings:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def setValue(self, key: str, value: object) -> None:  # noqa: N802 — Qt casing
        self.values[key] = str(value)

    def value(self, key: str, default: object = None) -> object:
        return self.values.get(key, default)


def _set(name: str, *headlines: str) -> ContextSet:
    return ContextSet(
        name=name,
        notes=[Note(headline=h, body="Body.", kind=SourceKind.PREP) for h in headlines],
    )


def _app(tmp: Path, context_set: ContextSet) -> Application:
    return Application(
        root=tmp,
        embedder=FlatEmbedder(),
        client=ScriptedClient(),
        cipher=ReversingCipher(),
        context_set=context_set,
    )


def _history(store: NotesStore, noteset_id: str, versions: list[ContextSet]) -> None:
    """Save each version in turn **under one id**, so they rotate into generations.

    The id has to be forced: rotation is per set, and versions with fresh ids are five
    different sets with no history between them. Generation 1 is the *previous* live
    file, so v1 then v2 then v3 leaves v3 live, v2 at generation 1 and v1 at generation 2.
    """
    for version in versions:
        version.id = noteset_id
        store.save(version)


def _corrupt(path: Path) -> None:
    path.write_text("{ this is not json", encoding="utf-8")


# ---------- the store: describing and reading generations ----------


def test_each_generation_is_described_well_enough_to_choose(tmp_path: Path) -> None:
    """Five rows named "backup 1" through "backup 5" is not a choice. The name and the
    note count come free from the parse `list_backups` was already doing."""
    store = NotesStore(tmp_path)
    original = _set("Acme", "One")
    _history(
        store,
        original.id,
        [original, _set("Acme", "One", "Two"), _set("Acme", "One", "Two", "Three")],
    )
    backups = store.list_backups(original.id)

    assert [b.generation for b in backups] == [1, 2]
    assert backups[0].note_count == 2  # the version just replaced
    assert backups[1].note_count == 1
    assert all(b.name == "Acme" for b in backups)
    assert all(b.saved_at > 0 for b in backups)
    assert all(b.error is None for b in backups)


def test_an_unreadable_generation_says_why(tmp_path: Path) -> None:
    """The reason is what tells the user whether the other four are worth trying."""
    store = NotesStore(tmp_path)
    note_set = _set("Acme", "One")
    _history(store, note_set.id, [note_set, _set("Acme", "One", "Two")])
    _corrupt(store.backup_path(note_set.id, 1))

    (info,) = store.list_backups(note_set.id)

    assert info.readable is False
    assert info.error
    assert info.note_count is None


def test_reading_a_backup_writes_nothing(tmp_path: Path) -> None:
    """Preview must not be able to cost the user their live file — and must not rotate
    the generations out from under the list they are reading."""
    store = NotesStore(tmp_path)
    note_set = _set("Acme", "One")
    _history(store, note_set.id, [note_set, _set("Acme", "One", "Two")])
    live_before = store.path_for(note_set.id).read_text(encoding="utf-8")
    stamps_before = [b.saved_at for b in store.list_backups(note_set.id)]

    previewed = store.read_backup(note_set.id, 1)

    assert [n.headline for n in previewed.notes] == ["One"]
    assert store.path_for(note_set.id).read_text(encoding="utf-8") == live_before
    assert [b.saved_at for b in store.list_backups(note_set.id)] == stamps_before


def test_restoring_keeps_the_version_it_replaced(tmp_path: Path) -> None:
    """The only reason a one-click restore of a file the user cannot fully read on screen
    is safe: the wrong choice is undoable."""
    store = NotesStore(tmp_path)
    note_set = _set("Acme", "One")
    _history(
        store,
        note_set.id,
        [note_set, _set("Acme", "One", "Two"), _set("Acme", "One", "Two", "Three")],
    )

    restored = store.restore_generation(note_set.id, 2)  # back to the one-note version

    assert [n.headline for n in restored.notes] == ["One"]
    assert [n.headline for n in store.load(note_set.id).notes] == ["One"]
    # The three-note version that was live is now the newest backup.
    assert store.read_backup(note_set.id, 1).notes[-1].headline == "Three"


def test_restoring_a_corrupt_generation_leaves_the_live_file_alone(tmp_path: Path) -> None:
    store = NotesStore(tmp_path)
    note_set = _set("Acme", "One")
    _history(store, note_set.id, [note_set, _set("Acme", "One", "Two")])
    _corrupt(store.backup_path(note_set.id, 1))
    live_before = store.path_for(note_set.id).read_text(encoding="utf-8")

    with pytest.raises(NotesStoreError):
        store.restore_generation(note_set.id, 1)

    assert store.path_for(note_set.id).read_text(encoding="utf-8") == live_before


# ---------- the dialog: browsing and previewing ----------


def _dialog(app: Application, noteset_id: str | None = None, **kwargs) -> RestoreDialog:  # type: ignore[no-untyped-def]
    kwargs.setdefault("confirm", lambda _message: True)
    return RestoreDialog(app, noteset_id or app.context_set.id, **kwargs)


def test_the_list_shows_every_generation(qapp: QApplication, tmp_path: Path) -> None:
    note_set = _set("Acme", "One")
    app = _app(tmp_path, note_set)
    store = NotesStore(tmp_path)
    _history(
        store,
        note_set.id,
        [note_set, _set("Acme", "One", "Two"), _set("Acme", "One", "Two", "Three")],
    )

    dialog = _dialog(app)

    assert dialog.generation_list.count() == 2
    assert "Acme" in dialog.generation_list.item(0).text()


def test_no_backups_says_so(qapp: QApplication, tmp_path: Path) -> None:
    """An empty list under a requirement that promises five generations otherwise reads
    as data loss."""
    note_set = _set("Acme", "One")
    app = _app(tmp_path, note_set)

    dialog = _dialog(app)

    assert dialog.generation_list.count() == 0
    assert dialog.status.text() == NO_BACKUPS_TEXT
    assert dialog.restore_button.isEnabled() is False
    assert dialog.latest_button.isEnabled() is False


def test_the_preview_shows_that_version_not_the_live_one(
    qapp: QApplication, tmp_path: Path
) -> None:
    """The question is "is this the version I want back", which only the backup's own
    contents answer."""
    note_set = _set("Acme", "One")
    app = _app(tmp_path, note_set)
    store = NotesStore(tmp_path)
    _history(store, note_set.id, [_set("Acme", "Old headline"), note_set])
    store.save(app.context_set)

    dialog = _dialog(app)
    dialog.generation_list.setCurrentRow(1)

    assert "Old headline" in dialog.preview.toPlainText()


def test_a_corrupt_generation_cannot_be_restored_and_explains_itself(
    qapp: QApplication, tmp_path: Path
) -> None:
    note_set = _set("Acme", "One")
    app = _app(tmp_path, note_set)
    store = NotesStore(tmp_path)
    _history(store, note_set.id, [note_set, _set("Acme", "One", "Two")])
    _corrupt(store.backup_path(note_set.id, 1))

    dialog = _dialog(app)

    assert dialog.restore_button.isEnabled() is False
    assert "cannot be read" in dialog.preview.toPlainText()
    assert "unreadable" in describe(dialog.backups[0])


# ---------- the dialog: restoring ----------


def test_restoring_re_points_everything_that_reads_the_set(
    qapp: QApplication, tmp_path: Path
) -> None:
    """D-61. Rewriting the file alone would leave matching drawing from the version the
    user just replaced — invisible, and indistinguishable from bad retrieval.

    Asserts the state of each holder, not that `activate_context_set` was called.
    """
    note_set = _set("Acme", "One")
    app = _app(tmp_path, note_set)
    store = NotesStore(tmp_path)
    _history(store, note_set.id, [_set("Acme", "Old headline"), note_set])
    store.save(app.context_set)
    dialog = _dialog(app)
    dialog.generation_list.setCurrentRow(1)  # the one-note "Old headline" version

    assert dialog.restore_selected() is True

    assert [n.headline for n in app.context_set.notes] == ["Old headline"]
    assert app.prefilter.note_set is app.context_set
    assert app.tracker.note_set is app.context_set
    assert app.index.note_ids == [n.id for n in app.context_set.notes]


def test_a_restore_is_confirmed_first(qapp: QApplication, tmp_path: Path) -> None:
    """FR60. Declining changes nothing on disk."""
    note_set = _set("Acme", "One")
    app = _app(tmp_path, note_set)
    store = NotesStore(tmp_path)
    _history(store, note_set.id, [_set("Acme", "Old"), note_set])
    live_before = store.path_for(note_set.id).read_text(encoding="utf-8")

    dialog = _dialog(app, confirm=lambda _message: False)

    assert dialog.restore_selected() is False
    assert store.path_for(note_set.id).read_text(encoding="utf-8") == live_before
    assert dialog.restored is None


def test_a_restore_is_refused_mid_session_before_it_writes(
    qapp: QApplication, tmp_path: Path
) -> None:
    """The check has to precede the write. Discovering the refusal afterwards would leave
    the file replaced and the application still matching the version just discarded."""
    note_set = _set("Acme", "One")
    app = _app(tmp_path, note_set)
    store = NotesStore(tmp_path)
    _history(store, note_set.id, [_set("Acme", "Old"), note_set])
    live_before = store.path_for(note_set.id).read_text(encoding="utf-8")
    dialog = _dialog(app)
    app.session.request_start()
    app.session.preflight_result(blocked=False)

    assert dialog.restore_selected() is False

    assert "session is running" in dialog.status.text().lower()
    assert store.path_for(note_set.id).read_text(encoding="utf-8") == live_before
    assert [n.headline for n in app.context_set.notes] == ["One"]


def test_restore_newest_readable_falls_through_and_names_what_it_skipped(
    qapp: QApplication, tmp_path: Path
) -> None:
    """T3.9's acceptance criterion. Landing quietly on version 3 leaves the user believing
    1 and 2 are still there to go back to."""
    note_set = _set("Acme", "Newest")
    app = _app(tmp_path, note_set)
    store = NotesStore(tmp_path)
    _history(store, note_set.id, [_set("Acme", "Oldest"), _set("Acme", "Middle"), note_set])
    store.save(app.context_set)
    _corrupt(store.backup_path(note_set.id, 1))

    dialog = _dialog(app)
    assert dialog.restore_latest_readable() is True

    assert [n.headline for n in app.context_set.notes] == ["Middle"]
    assert "1" in dialog.status.text()
    assert "skipped" in dialog.status.text()


def test_every_generation_corrupt_changes_nothing(qapp: QApplication, tmp_path: Path) -> None:
    note_set = _set("Acme", "One")
    app = _app(tmp_path, note_set)
    store = NotesStore(tmp_path)
    _history(store, note_set.id, [_set("Acme", "Old"), note_set])
    _corrupt(store.backup_path(note_set.id, 1))
    live_before = store.path_for(note_set.id).read_text(encoding="utf-8")

    dialog = _dialog(app)

    assert dialog.restore_latest_readable() is False
    assert dialog.latest_button.isEnabled() is False
    assert "Nothing has been changed" in dialog.status.text()
    assert store.path_for(note_set.id).read_text(encoding="utf-8") == live_before


def test_the_list_refreshes_after_a_restore(qapp: QApplication, tmp_path: Path) -> None:
    """Rotation moves every generation down one, so the list is stale the instant the
    restore returns — and the row the user is looking at would name a different version
    from the one it describes."""
    note_set = _set("Acme", "Newest")
    app = _app(tmp_path, note_set)
    store = NotesStore(tmp_path)
    _history(store, note_set.id, [_set("Acme", "Oldest"), _set("Acme", "Middle"), note_set])
    store.save(app.context_set)

    dialog = _dialog(app)
    assert [b.generation for b in dialog.backups] == [1, 2, 3]  # Newest, Middle, Oldest
    dialog.generation_list.setCurrentRow(1)  # "Middle"
    assert dialog.restore_selected() is True

    # Everything moved down one, and the list the user is looking at knows it.
    assert [b.generation for b in dialog.backups] == [1, 2, 3, 4]
    assert dialog.generation_list.count() == 4
    assert store.read_backup(note_set.id, 1).notes[0].headline == "Newest"
    assert store.read_backup(note_set.id, 2).notes[0].headline == "Newest"
    assert store.read_backup(note_set.id, 3).notes[0].headline == "Middle"


def test_a_restore_is_recorded(qapp: QApplication, tmp_path: Path) -> None:
    note_set = _set("Acme", "One")
    app = _app(tmp_path, note_set)
    store = NotesStore(tmp_path)
    _history(store, note_set.id, [_set("Acme", "Old"), note_set])

    assert _dialog(app).restore_selected() is True

    assert any(e.event == "noteset_restored" for e in app.ring.snapshot())


# ---------- the editor: where the offer appears (FR44) ----------


def _editor(app: Application, **kwargs) -> NotesEditor:  # type: ignore[no-untyped-def]
    kwargs.setdefault("settings", FakeSettings())
    kwargs.setdefault("confirm", lambda _message: True)
    kwargs.setdefault("prompt", lambda _title, default: default)
    return NotesEditor(app, **kwargs)


class SpyRestore:
    """Records the set a restore was offered for, without opening a window."""

    def __init__(self) -> None:
        self.opened: list[str] = []

    def __call__(self, application, noteset_id, store, parent):  # type: ignore[no-untyped-def]
        self.opened.append(noteset_id)
        return RestoreDialog(
            application, noteset_id, store=store, confirm=lambda _m: True, parent=parent
        )


def test_the_editor_offers_restore_for_the_active_set(qapp: QApplication, tmp_path: Path) -> None:
    """FR29's "from the UI". The button is the entire requirement."""
    note_set = _set("Acme", "One")
    app = _app(tmp_path, note_set)
    spy = SpyRestore()
    editor = _editor(app, restore_factory=spy)

    editor.open_restore()

    assert spy.opened == [note_set.id]


def test_opening_a_corrupt_set_offers_restore(qapp: QApplication, tmp_path: Path) -> None:
    """FR44, at the one place in the product that meets a corrupt set. Reporting and
    stopping is what "failing silently" looks like from the user's side: five readable
    copies on disk and nothing connecting them."""
    app = _app(tmp_path, _set("Acme", "One"))
    store = NotesStore(tmp_path)
    other = _set("Other", "Theirs")
    _history(store, other.id, [other, other])
    _corrupt(store.path_for(other.id))
    spy = SpyRestore()
    editor = _editor(app, restore_factory=spy)

    assert editor.activate(other.id) is False

    assert spy.opened == [other.id]


def test_a_newer_schema_is_never_offered_a_restore(qapp: QApplication, tmp_path: Path) -> None:
    """The backups are that format too, so rolling one in would be this build overwriting
    data it cannot read."""
    app = _app(tmp_path, _set("Acme", "One"))
    store = NotesStore(tmp_path)
    other = _set("Other", "Theirs")
    store.save(other)
    payload = json.loads(store.path_for(other.id).read_text(encoding="utf-8"))
    payload["schema_version"] = 99
    store.path_for(other.id).write_text(json.dumps(payload), encoding="utf-8")
    spy = SpyRestore()
    editor = _editor(app, restore_factory=spy)

    assert editor.activate(other.id) is False

    assert spy.opened == []
    assert "99" in editor.status.text()


def test_restoring_drops_the_pending_write(qapp: QApplication, tmp_path: Path) -> None:
    """**The trap.** Unsaved edits belong to the version the user just replaced, and
    `flush` on close would put them straight back over the restored file — the restore
    undone by the window that offered it."""
    note_set = _set("Acme", "One")
    app = _app(tmp_path, note_set)
    store = NotesStore(tmp_path)
    _history(store, note_set.id, [_set("Acme", "Old"), note_set])
    editor = _editor(app, restore_factory=SpyRestore())
    editor.headline_edit.setText("Edited but never saved")
    editor._on_edited()
    assert editor.dirty is True

    dialog = editor.open_restore()
    assert dialog.restore_selected() is True

    assert editor.dirty is False
    editor.flush()
    assert [n.headline for n in store.load(note_set.id).notes] == ["Old"]


def test_restoring_a_corrupt_set_then_activates_it(qapp: QApplication, tmp_path: Path) -> None:
    """The user asked to open that set. Repairing it and leaving them on the old one is
    half the job."""
    app = _app(tmp_path, _set("Acme", "One"))
    store = NotesStore(tmp_path)
    other = _set("Other", "Theirs")
    _history(store, other.id, [other, other])
    _corrupt(store.path_for(other.id))
    editor = _editor(app, restore_factory=SpyRestore())

    assert editor.activate(other.id) is False
    assert editor._restore is not None
    assert editor._restore.restore_selected() is True

    assert app.context_set.id == other.id
    assert app.prefilter.note_set is app.context_set
    assert editor.settings.values[ACTIVE_SET_KEY] == other.id  # type: ignore[attr-defined]


# ---------- startup: FR44's "or starting empty" ----------


def test_a_corrupt_active_set_is_recovered_not_replaced(qapp: QApplication, tmp_path: Path) -> None:
    """Falling through to a fresh set is how the user's notes turn into an empty editor:
    their set is on disk with readable backups beside it, and the app opens showing
    nothing. That is the failure most likely to be read as "the app lost my notes"."""
    settings = FakeSettings()
    store = NotesStore(tmp_path)
    note_set = _set("Acme", "One")
    _history(store, note_set.id, [note_set, note_set])
    settings.setValue(ACTIVE_SET_KEY, note_set.id)
    _corrupt(store.path_for(note_set.id))

    loaded = load_active_set(tmp_path, settings)

    assert loaded.id == note_set.id
    assert [n.headline for n in loaded.notes] == ["One"]


def test_the_startup_recovery_is_recorded(qapp: QApplication, tmp_path: Path) -> None:
    """It happens before any window exists, so the ring is the only place it can be seen."""
    from interview_prep_recall.diagnostics.ring import DiagnosticRing

    settings = FakeSettings()
    store = NotesStore(tmp_path)
    note_set = _set("Acme", "One")
    _history(store, note_set.id, [note_set, note_set])
    settings.setValue(ACTIVE_SET_KEY, note_set.id)
    _corrupt(store.path_for(note_set.id))
    ring = DiagnosticRing()

    load_active_set(tmp_path, settings, ring=ring)

    assert any(e.event == "noteset_recovered_on_start" for e in ring.snapshot())


def test_a_corrupt_set_with_no_readable_backup_still_falls_through(
    qapp: QApplication, tmp_path: Path
) -> None:
    """Recovery that cannot succeed must not become a crash on startup."""
    settings = FakeSettings()
    store = NotesStore(tmp_path)
    broken = _set("Broken", "One")
    survivor = _set("Survivor", "Two")
    store.save(broken)
    store.save(survivor)
    settings.setValue(ACTIVE_SET_KEY, broken.id)
    _corrupt(store.path_for(broken.id))

    assert load_active_set(tmp_path, settings).id == survivor.id


def test_a_newer_schema_is_not_recovered_on_start(qapp: QApplication, tmp_path: Path) -> None:
    settings = FakeSettings()
    store = NotesStore(tmp_path)
    newer = _set("Newer", "One")
    survivor = _set("Survivor", "Two")
    _history(store, newer.id, [newer, newer])
    store.save(survivor)
    payload = json.loads(store.path_for(newer.id).read_text(encoding="utf-8"))
    payload["schema_version"] = 99
    store.path_for(newer.id).write_text(json.dumps(payload), encoding="utf-8")
    settings.setValue(ACTIVE_SET_KEY, newer.id)

    loaded = load_active_set(tmp_path, settings)

    assert loaded.id == survivor.id
    # The newer file is untouched — no backup was rolled over it.
    assert json.loads(store.path_for(newer.id).read_text(encoding="utf-8"))["schema_version"] == 99


def test_schema_too_new_is_still_raised_by_a_direct_load(tmp_path: Path) -> None:
    """`load_active_set` swallows it deliberately; the store must not."""
    store = NotesStore(tmp_path)
    note_set = _set("Newer", "One")
    store.save(note_set)
    payload = json.loads(store.path_for(note_set.id).read_text(encoding="utf-8"))
    payload["schema_version"] = 99
    store.path_for(note_set.id).write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SchemaTooNewError):
        store.load(note_set.id)
