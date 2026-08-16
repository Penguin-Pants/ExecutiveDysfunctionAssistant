"""T3.7 / T3.8 — the notes editor and the note-set lifecycle (FR3, FR4, FR41, FR43, FR60).

Notes could be imported, matched, tracked, embedded and reported on, and could not be
*written*: the store, the model, the importer and the index all had tests, and the product
had no way to create a note. The tests here are about the two properties that make an
editor safe to type into — ids survive edits, and saving is not per keystroke — plus the
switch FR43 hangs on.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from helpers import ReversingCipher, ScriptedClient

pytest.importorskip("PySide6", reason="Qt UI tests require the [ui] extra")

from PySide6.QtWidgets import QApplication  # noqa: E402

from interview_prep_recall.app import ActiveSetLocked, Application  # noqa: E402
from interview_prep_recall.notes.model import ContextSet, Note, SourceKind  # noqa: E402
from interview_prep_recall.notes.store import NotesStore  # noqa: E402
from interview_prep_recall.ui.editor import (  # noqa: E402
    ACTIVE_SET_KEY,
    NOT_OPTIMISED_TEXT,
    SAVE_DEBOUNCE_MS,
    NotesEditor,
    load_active_set,
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


def _app(tmp: Path, context_set: ContextSet | None = None) -> Application:
    return Application(
        root=tmp,
        embedder=FlatEmbedder(),
        client=ScriptedClient(),
        cipher=ReversingCipher(),
        context_set=context_set
        or ContextSet(
            name="Acme",
            notes=[
                Note(headline="Tell me about a migration", body="Led it.", kind=SourceKind.PREP),
                Note(headline="Senior engineer wanted", kind=SourceKind.ROLE),
            ],
        ),
    )


def _editor(app: Application, **kwargs) -> NotesEditor:  # type: ignore[no-untyped-def]
    kwargs.setdefault("settings", FakeSettings())
    kwargs.setdefault("confirm", lambda _message: True)
    kwargs.setdefault("prompt", lambda _title, default: default)
    return NotesEditor(app, **kwargs)


# ---------- T3.7: editing (FR3, FR4, FR41) ----------


def test_editing_a_note_keeps_its_id(qapp: QApplication, tmp_path: Path) -> None:
    """FR41, and the reason it matters: the embedding cache is keyed on note id, so a new
    id on every edit silently invalidates every vector — BC-1's stale-vector failure,
    arriving through the editor instead of through the index."""
    app = _app(tmp_path)
    original = app.context_set.notes[0].id
    editor = _editor(app)
    editor.note_list.setCurrentRow(0)

    editor.headline_edit.setText("Tell me about a migration you led")
    editor.headline_edit.textEdited.emit(editor.headline_edit.text())
    editor.flush()

    assert app.context_set.notes[0].id == original
    reloaded = NotesStore(tmp_path).load(app.context_set.id)
    assert reloaded.notes[0].headline == "Tell me about a migration you led"
    assert reloaded.notes[0].id == original


def test_tags_round_trip(qapp: QApplication, tmp_path: Path) -> None:
    """FR4. Free-form, comma separated, and they reach the file."""
    app = _app(tmp_path)
    editor = _editor(app)
    editor.note_list.setCurrentRow(0)

    editor.tags_edit.setText("scaling, leadership")
    editor.tags_edit.textEdited.emit(editor.tags_edit.text())
    editor.flush()

    assert NotesStore(tmp_path).load(app.context_set.id).notes[0].tags == ["scaling", "leadership"]


def test_adding_a_note_takes_the_selected_kind(qapp: QApplication, tmp_path: Path) -> None:
    """FR67's one permitted moment: kind is chosen at creation."""
    app = _app(tmp_path)
    editor = _editor(app)
    editor.kind_box.setCurrentIndex(editor.kind_box.findData(SourceKind.RESUME))

    note = editor.add_note()

    assert note.kind is SourceKind.RESUME
    assert note in app.context_set.notes


def test_kind_is_not_editable_on_an_existing_note(qapp: QApplication, tmp_path: Path) -> None:
    """FR67. Disabled rather than raising — the requirement made visible instead of an
    error the user meets after typing."""
    app = _app(tmp_path)
    editor = _editor(app)

    editor.note_list.setCurrentRow(0)

    assert not editor.kind_box.isEnabled()


def test_an_untrackable_kind_cannot_be_tracked(qapp: QApplication, tmp_path: Path) -> None:
    """FR70. The ROLE note's checkbox is off the table; the model would refuse anyway."""
    app = _app(tmp_path)
    editor = _editor(app)

    editor.note_list.setCurrentRow(1)  # the ROLE note

    assert not editor.track_box.isEnabled()
    assert "FR70" in editor.advisory.text()


def test_a_bulletless_note_is_flagged(qapp: QApplication, tmp_path: Path) -> None:
    """D-6's advisory. The note still saves — the requirement permits it and says the
    overlay degrades, so blocking would be stricter than the design."""
    app = _app(tmp_path)
    editor = _editor(app)

    editor.note_list.setCurrentRow(0)

    assert NOT_OPTIMISED_TEXT in editor.advisory.text()


def test_deleting_a_note_is_confirmed(qapp: QApplication, tmp_path: Path) -> None:
    """FR60."""
    app = _app(tmp_path)
    editor = _editor(app, confirm=lambda _message: False)
    editor.note_list.setCurrentRow(0)

    assert editor.delete_note() is False
    assert len(app.context_set.notes) == 2


def test_deleting_a_note_leaves_the_others_intact(qapp: QApplication, tmp_path: Path) -> None:
    app = _app(tmp_path)
    survivor = app.context_set.notes[1].id
    editor = _editor(app)
    editor.note_list.setCurrentRow(0)

    assert editor.delete_note() is True

    assert [n.id for n in app.context_set.notes] == [survivor]


def test_reordering_keeps_ids(qapp: QApplication, tmp_path: Path) -> None:
    """FR3 with FR41: position is not identity."""
    app = _app(tmp_path)
    before = [n.id for n in app.context_set.notes]
    editor = _editor(app)
    editor.note_list.setCurrentRow(0)

    assert editor.move_note(1) is True
    editor.flush()

    assert [n.id for n in app.context_set.notes] == list(reversed(before))
    assert [n.id for n in NotesStore(tmp_path).load(app.context_set.id).notes] == list(
        reversed(before)
    )


def test_moving_past_the_end_does_nothing(qapp: QApplication, tmp_path: Path) -> None:
    app = _app(tmp_path)
    editor = _editor(app)
    editor.note_list.setCurrentRow(0)

    assert editor.move_note(-1) is False


# ---------- T3.7: saving is not per keystroke ----------


def test_typing_does_not_write(qapp: QApplication, tmp_path: Path) -> None:
    """The acceptance criterion, and the reason for it: `NotesStore.save` rotates FR29's
    five backup generations on every write, so a save per keystroke would leave the user's
    recovery window covering the last twelve characters they typed."""
    app = _app(tmp_path)
    editor = _editor(app)
    NotesStore(tmp_path).save(app.context_set)  # a clean baseline on disk
    before = NotesStore(tmp_path).path_for(app.context_set.id).read_bytes()
    editor.note_list.setCurrentRow(0)

    for text in ("T", "Te", "Tes", "Test"):
        editor.headline_edit.setText(text)
        editor.headline_edit.textEdited.emit(text)

    assert NotesStore(tmp_path).path_for(app.context_set.id).read_bytes() == before
    assert editor.dirty


def test_the_debounce_is_five_seconds() -> None:
    """Stated as a constant so the timer and the acceptance criterion cannot drift."""
    assert SAVE_DEBOUNCE_MS == 5_000


def test_an_explicit_save_writes(qapp: QApplication, tmp_path: Path) -> None:
    app = _app(tmp_path)
    editor = _editor(app)
    editor.note_list.setCurrentRow(0)
    editor.headline_edit.setText("Edited")
    editor.headline_edit.textEdited.emit("Edited")

    assert editor.flush() is True
    assert editor.dirty is False


def test_flushing_a_clean_editor_writes_nothing(qapp: QApplication, tmp_path: Path) -> None:
    """Otherwise every open-and-close would burn a backup generation."""
    app = _app(tmp_path)
    editor = _editor(app)
    editor.flush()

    assert editor.flush() is False


def test_closing_saves(qapp: QApplication, tmp_path: Path) -> None:
    """Closing is an explicit action. The alternative discards up to five seconds of
    typing because the user was quicker than the timer."""
    app = _app(tmp_path)
    editor = _editor(app)
    editor.note_list.setCurrentRow(0)
    editor.headline_edit.setText("Closed while dirty")
    editor.headline_edit.textEdited.emit("Closed while dirty")

    editor.close()

    assert editor.dirty is False
    assert NotesStore(tmp_path).load(app.context_set.id).notes[0].headline == "Closed while dirty"


def test_a_non_verbatim_bullet_is_refused_before_the_write(
    qapp: QApplication, tmp_path: Path
) -> None:
    """FR42, checked before the file rather than after. Saving text the render boundary
    would refuse leaves the user with notes that are stored and unusable."""
    app = _app(tmp_path)
    editor = _editor(app)
    editor.note_list.setCurrentRow(0)
    editor.bullets_edit.setPlainText("A bullet the note does not contain")

    assert editor.flush() is False
    assert editor.dirty, "still unsaved, so the user can fix it"
    assert "not saved" in editor.status.text().lower()

    # And the promise is kept: fixing the bullet saves. Asserted rather than left
    # implied, which also means this test does not hand the session a dirty editor —
    # CI on PR #27 crashed in teardown deleting a widget whose close was refused.
    editor.bullets_edit.setPlainText("Led it.")
    assert editor.flush() is True


# ---------- T3.8: the set lifecycle (FR43, FR60) ----------


def test_creating_a_set_activates_it(qapp: QApplication, tmp_path: Path) -> None:
    app = _app(tmp_path)
    editor = _editor(app, prompt=lambda _title, _default: "Second employer")

    created = editor.create_set()

    assert created is not None
    assert app.context_set.id == created.id
    assert app.context_set.name == "Second employer"


def test_the_active_set_is_persisted(qapp: QApplication, tmp_path: Path) -> None:
    """FR43 across restarts (T3.8)."""
    app = _app(tmp_path)
    settings = FakeSettings()
    editor = _editor(app, settings=settings, prompt=lambda _t, _d: "Second")

    created = editor.create_set()

    assert created is not None
    assert settings.values[ACTIVE_SET_KEY] == created.id


def test_switching_sets_rebuilds_what_matching_reads(qapp: QApplication, tmp_path: Path) -> None:
    """FR43's actual requirement — *matching draws only from the active set*. Assigning
    `application.context_set` alone would leave the index and the prefilter pointed at the
    previous corpus, which fails silently and looks like bad retrieval."""
    app = _app(tmp_path)
    first = app.context_set
    editor = _editor(app, prompt=lambda _t, _d: "Second")
    created = editor.create_set()
    assert created is not None

    assert app.prefilter.note_set is app.context_set
    assert app.context_set.id != first.id

    assert editor.activate(first.id) is True
    assert app.prefilter.note_set.id == first.id


def test_switching_sets_is_refused_mid_session(qapp: QApplication, tmp_path: Path) -> None:
    """Changing the corpus under a running interview would make the tracker's verdict and
    the report's snapshot describe two different sets — the disagreement D-58 exists to
    prevent, arriving from the other direction."""
    app = _app(tmp_path)
    editor = _editor(app, prompt=lambda _t, _d: "Second")
    created = editor.create_set()
    assert created is not None
    app.session.request_start()
    app.session.preflight_result(blocked=False)

    with pytest.raises(ActiveSetLocked):
        app.activate_context_set(ContextSet(name="Third"))

    assert editor.activate(created.id) is False
    assert "session is running" in editor.status.text().lower()


def test_renaming_keeps_the_set_id(qapp: QApplication, tmp_path: Path) -> None:
    """The id is the filename and the embedding-cache key, so renaming through a new id
    would orphan every vector."""
    app = _app(tmp_path)
    original = app.context_set.id
    editor = _editor(app, prompt=lambda _t, _d: "Renamed")

    assert editor.rename_set() is True

    assert app.context_set.id == original
    assert NotesStore(tmp_path).load(original).name == "Renamed"


def test_deleting_a_set_is_confirmed(qapp: QApplication, tmp_path: Path) -> None:
    """FR60."""
    app = _app(tmp_path)
    editor = _editor(app, prompt=lambda _t, _d: "Second", confirm=lambda _m: False)
    editor.create_set()

    assert editor.delete_set() is False


def test_the_last_set_cannot_be_deleted(qapp: QApplication, tmp_path: Path) -> None:
    """Deleting the only set leaves the app with no active set and no surface able to make
    one — an empty state this dialog cannot recover from."""
    app = _app(tmp_path)
    editor = _editor(app)

    assert editor.delete_set() is False
    assert "only note set" in editor.status.text().lower()


def test_deleting_a_set_switches_to_another_first(qapp: QApplication, tmp_path: Path) -> None:
    """Switch first, delete second: activation can refuse, and a deleted file with the app
    still pointing at it is unrecoverable."""
    app = _app(tmp_path)
    first = app.context_set.id
    editor = _editor(app, prompt=lambda _t, _d: "Second")
    created = editor.create_set()
    assert created is not None

    assert editor.delete_set() is True

    assert app.context_set.id == first
    assert not NotesStore(tmp_path).path_for(created.id).exists()


# ---------- the wire (T5.10a) ----------


def test_switching_sets_re_hands_the_overlay_its_notes(qapp: QApplication, tmp_path: Path) -> None:
    """T5.10a, closed. The panel resolves match results against a set it was handed once,
    so a switch nothing tells it about renders the previous corpus's notes."""
    from interview_prep_recall.ui.main_window import MainWindow

    app = _app(tmp_path)
    window = MainWindow(app, overlay_settings=FakeSettings())
    editor = _editor(app, prompt=lambda _t, _d: "Second")

    created = editor.create_set()

    assert created is not None
    assert window.overlay.context_set is app.context_set
    assert window.overlay.context_set.id == created.id


def test_an_unwired_switch_is_recorded(qapp: QApplication, tmp_path: Path) -> None:
    """D-60 again: with no surface attached the switch is still visible in diagnostics
    rather than silently rendering the old corpus."""
    app = _app(tmp_path)

    app.activate_context_set(ContextSet(name="Nobody is listening"))

    assert any(e.event == "context_set_change_unrendered" for e in app.ring.snapshot())


def test_an_unsaved_active_set_is_persisted_on_open(qapp: QApplication, tmp_path: Path) -> None:
    """The application can be constructed with a set that has never been written — the
    composition root does exactly that on a first run. Until it exists on disk it cannot
    be listed, cannot be switched back to, and vanishes the moment a second set is
    created. Opening the editor is where that gets fixed."""
    app = _app(tmp_path)
    assert not NotesStore(tmp_path).path_for(app.context_set.id).exists()

    _editor(app)

    assert NotesStore(tmp_path).path_for(app.context_set.id).exists()


def test_both_sets_are_listed_after_creating_one(qapp: QApplication, tmp_path: Path) -> None:
    """FR43's selector shows what the user can switch between, which is the whole point of
    naming sets."""
    app = _app(tmp_path)
    editor = _editor(app, prompt=lambda _t, _d: "Second")

    editor.create_set()

    listed = {editor.set_box.itemText(row) for row in range(editor.set_box.count())}
    assert listed == {"Acme", "Second"}


# ---------- PR #27 review findings ----------


def test_activating_a_set_repoints_the_tracker(qapp: QApplication, tmp_path: Path) -> None:
    """The tracker holds its own reference and `reset()` only clears session state. Left
    pointed at the previous set it renders the old checklist and intersects the old
    tracked ids with the new index, so nothing in the new set can ever be marked."""
    app = _app(tmp_path)
    editor = _editor(app, prompt=lambda _t, _d: "Second")

    created = editor.create_set()

    assert created is not None
    assert app.tracker.note_set is app.context_set
    assert app.tracker.note_set.id == created.id


def test_saving_re_embeds(qapp: QApplication, tmp_path: Path) -> None:
    """Saving writes JSON and not vectors. Without a rebuild, a note added here is absent
    from matching until the user switches sets or restarts (FR34)."""
    app = _app(tmp_path)
    editor = _editor(app)
    before = len(app.index.note_ids)

    editor.add_note()
    editor.flush()

    assert len(app.index.note_ids) == before + 1
    assert any(e.event == "notes_reindexed" for e in app.ring.snapshot())


def test_a_failed_save_blocks_the_switch(qapp: QApplication, tmp_path: Path) -> None:
    """`flush` leaves a non-verbatim set dirty on purpose. Switching anyway would replace
    `application.context_set` and put those edits where the user cannot reach them."""
    app = _app(tmp_path)
    editor = _editor(app, prompt=lambda _t, _d: "Second")
    created = editor.create_set()
    assert created is not None
    first = app.context_set.id
    editor.note_list.setCurrentRow(0) if editor.note_list.count() else editor.add_note()
    editor.bullets_edit.setPlainText("Not a substring of anything")

    assert editor.activate(first) is False
    assert app.context_set.id == created.id, "still on the set with the unsaved edit"

    # Fix it, and the switch that was refused now works.
    editor.bullets_edit.setPlainText("")
    assert editor.flush() is True
    assert editor.activate(first) is True


def test_a_failed_save_keeps_the_window_open(qapp: QApplication, tmp_path: Path) -> None:
    """The refusal tells the user they can fix it. Closing anyway makes that false: the
    next editor opens clean against the mutated object and quitting loses the edits."""
    from PySide6.QtGui import QCloseEvent

    app = _app(tmp_path)
    editor = _editor(app)
    editor.note_list.setCurrentRow(0)
    editor.bullets_edit.setPlainText("Not a substring of anything")

    event = QCloseEvent()
    editor.closeEvent(event)

    assert not event.isAccepted()
    assert editor.dirty

    # Then fix it and confirm the window will close — the refusal is a hold, not a trap,
    # and leaving a dirty editor behind is what crashed CI's teardown on PR #27.
    editor.bullets_edit.setPlainText("Led it.")
    reopened = QCloseEvent()
    editor.closeEvent(reopened)
    assert reopened.isAccepted()
    assert not editor.dirty


def test_deleting_a_set_removes_its_backups(qapp: QApplication, tmp_path: Path) -> None:
    """FR29 keeps five generations, so deleting only the live file leaves up to five
    copies of the complete notes on disk under a control whose confirmation says "cannot
    be undone" — true of the user's access, false of the data."""
    app = _app(tmp_path)
    store = NotesStore(tmp_path)
    doomed = app.context_set.id
    store.save(app.context_set)
    store.save(app.context_set)  # rotates a backup generation into existence
    assert store.list_backups(doomed)

    editor = _editor(app, prompt=lambda _t, _d: "Second")
    editor.create_set()
    # Back to the set we intend to delete, then delete it.
    assert editor.activate(doomed) is True
    assert editor.delete_set() is True

    assert store.list_backups(doomed) == []
    assert not store.path_for(doomed).exists()


# ---------- T3.8: the persisted id has a reader ----------


def test_the_persisted_set_is_what_loads(qapp: QApplication, tmp_path: Path) -> None:
    """The id was written with no reader anywhere — D-20's shape, in the requirement this
    task exists for. `load_active_set` is what the composition root calls."""
    settings = FakeSettings()
    store = NotesStore(tmp_path)
    first = ContextSet(name="First")
    second = ContextSet(name="Second")
    store.save(first)
    store.save(second)
    settings.setValue(ACTIVE_SET_KEY, second.id)

    assert load_active_set(tmp_path, settings).id == second.id


def test_a_first_run_gets_a_new_set(qapp: QApplication, tmp_path: Path) -> None:
    """No sets on disk and nothing persisted. Raising here would make the entry point
    fail on the one run where nothing is wrong."""
    loaded = load_active_set(tmp_path, FakeSettings())

    assert loaded.notes == []
    assert loaded.name


def test_a_persisted_id_that_no_longer_exists_falls_through(
    qapp: QApplication, tmp_path: Path
) -> None:
    """A synced folder can lose a set another machine deleted."""
    settings = FakeSettings()
    store = NotesStore(tmp_path)
    survivor = ContextSet(name="Survivor")
    store.save(survivor)
    settings.setValue(ACTIVE_SET_KEY, "00000000-0000-4000-8000-000000000000")

    assert load_active_set(tmp_path, settings).id == survivor.id


# ---------- T10.7a: the kind legend (FR72) ----------


def test_the_legend_names_every_kind(qapp: QApplication, tmp_path: Path) -> None:
    """FR72's shapes were learnable only by hovering the overlay — during an interview,
    the one moment the user has no attention to spare for learning a code.

    Every kind, because a legend that covers four of five is worse than none: the missing
    glyph looks like a mark with no meaning rather than a gap in the legend.
    """
    from interview_prep_recall.notes.model import SourceKind as Kind
    from interview_prep_recall.ui.overlay import mark_for

    editor = _editor(_app(tmp_path))
    text = editor.legend.text()

    for kind in Kind:
        mark = mark_for(kind)
        assert mark.glyph in text, kind
        assert mark.label in text, kind


def test_the_legend_is_built_from_the_marks_it_explains(qapp: QApplication, tmp_path: Path) -> None:
    """Not restated. A legend that drifts from the marks is worse than no legend, because
    the reader cannot tell which of the two is lying."""
    from interview_prep_recall.ui import overlay
    from interview_prep_recall.ui.editor import legend_text
    from interview_prep_recall.ui.overlay import KindMark

    original = dict(overlay.KIND_MARKS)
    try:
        overlay.KIND_MARKS[SourceKind.PREP] = KindMark("☂", "Umbrella notes")
        assert "☂ Umbrella notes" in legend_text()
    finally:
        overlay.KIND_MARKS.clear()
        overlay.KIND_MARKS.update(original)


def test_the_legend_reads_in_the_same_order_as_the_kind_selector(
    qapp: QApplication, tmp_path: Path
) -> None:
    """A legend whose order drifts from the control beside it is one more thing for the
    reader to reconcile."""
    from interview_prep_recall.ui.overlay import legend_entries

    editor = _editor(_app(tmp_path))
    in_box = [editor.kind_box.itemData(row) for row in range(editor.kind_box.count())]

    assert in_box == [kind for kind, _mark in legend_entries()]


def test_each_note_carries_its_overlay_mark_in_the_list(qapp: QApplication, tmp_path: Path) -> None:
    """The half that makes the legend *teach*: the user sees the glyph beside their own
    notes every time they edit, so it is already familiar the first time one appears on
    the overlay mid-interview."""
    from interview_prep_recall.ui.overlay import mark_for

    app = _app(
        tmp_path,
        ContextSet(
            name="Acme",
            notes=[
                Note(headline="A prep note", kind=SourceKind.PREP),
                Note(headline="The posting", kind=SourceKind.ROLE),
            ],
        ),
    )
    editor = _editor(app)

    assert editor.note_list.item(0).text().endswith(mark_for(SourceKind.PREP).glyph)
    assert editor.note_list.item(1).text().endswith(mark_for(SourceKind.ROLE).glyph)
    # The headline still leads, so Qt's type-to-select still finds it (D-67).
    assert editor.note_list.item(0).text().startswith("A prep note")


def test_the_mark_survives_an_edit_to_the_headline(qapp: QApplication, tmp_path: Path) -> None:
    """`_on_edited` rewrites the row as the user types. Rebuilding it without the mark
    would make the glyph disappear from exactly the note being worked on."""
    from interview_prep_recall.ui.overlay import mark_for

    app = _app(
        tmp_path,
        ContextSet(name="Acme", notes=[Note(headline="Before", kind=SourceKind.RESUME)]),
    )
    editor = _editor(app)
    editor.note_list.setCurrentRow(0)
    editor.headline_edit.setText("After")
    editor._on_edited()

    row = editor.note_list.item(0).text()
    assert row.endswith(mark_for(SourceKind.RESUME).glyph)
    assert row.startswith("After")


def test_typing_a_headline_still_selects_it(qapp: QApplication, tmp_path: Path) -> None:
    """**A keyboard user must not lose navigation to a decoration.**

    Qt's incremental search matches `Qt.DisplayRole` from the start of the string, so a
    row prefixed with the FR72 glyph cannot be reached by typing the headline. The mark
    trails instead (D-67). Found by review on PR #31.
    """
    app = _app(
        tmp_path,
        ContextSet(
            name="Acme",
            notes=[
                Note(headline="Alpha migration", kind=SourceKind.PREP),
                Note(headline="Zebra posting", kind=SourceKind.ROLE),
            ],
        ),
    )
    editor = _editor(app)
    editor.note_list.setCurrentRow(0)

    editor.note_list.keyboardSearch("Zebra")

    assert editor.note_list.currentRow() == 1
