"""T3.7a — the import surface (FR1a, FR2, FR42, FR60, FR66, FR67).

T3.5 built the chunkers, the strategy detection and the verbatim bullet proposal; T10.3
built `add_source`. Both had passing tests and **neither had a caller**, so a `.md` of prep
notes could not be brought into the product at all.

The tests here are about the properties FR2 actually asks for — the strategy is named and
switchable, every chunk is presented and editable before the save, and the save is blocked
until there is something reviewed to save — plus the two that make the import safe to
press: it replaces one kind and only that kind, and it refuses a bullet that is not in its
own note before it removes anything.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from helpers import ReversingCipher, ScriptedClient

pytest.importorskip("PySide6", reason="Qt UI tests require the [ui] extra")

from PySide6.QtWidgets import QApplication  # noqa: E402

from interview_prep_recall.app import Application  # noqa: E402
from interview_prep_recall.notes.importer import ChunkStrategy  # noqa: E402
from interview_prep_recall.notes.model import ContextSet, Note, SourceKind  # noqa: E402
from interview_prep_recall.notes.store import NotesStore  # noqa: E402
from interview_prep_recall.ui.editor import NotesEditor  # noqa: E402
from interview_prep_recall.ui.import_notes import (  # noqa: E402
    NOTHING_TO_IMPORT_TEXT,
    STRATEGY_NAMES,
    ImportDialog,
    summarise,
)

MARKDOWN = """## What was your hardest migration?
Led a Postgres cutover for 40 services. It ran for six weeks with no downtime.

## Why are you leaving?
I want to work closer to the product. My current role is mostly maintenance.
"""

QA_TEXT = """Q: What was your hardest migration?
A: Led a Postgres cutover for 40 services.

Q: Why are you leaving?
A: I want to work closer to the product.
"""


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
        context_set=context_set or ContextSet(name="Acme"),
    )


def _dialog(app: Application, **kwargs) -> ImportDialog:  # type: ignore[no-untyped-def]
    kwargs.setdefault("confirm", lambda _message: True)
    return ImportDialog(app, **kwargs)


def _choose(dialog: ImportDialog, strategy: ChunkStrategy) -> None:
    """Pick a strategy the way a user does — which also marks it as *their* choice, so
    detection stops overriding it. Setting the combo alone is the programmatic path."""
    dialog._select_strategy(strategy)
    dialog._on_strategy_changed(0)


def _loaded(app: Application, text: str = MARKDOWN, **kwargs) -> ImportDialog:  # type: ignore[no-untyped-def]
    dialog = _dialog(app, **kwargs)
    dialog.source_edit.setPlainText(text)
    _choose(dialog, ChunkStrategy.MD_HEADER)
    return dialog


# ---------- FR1a: the three ways in ----------


def test_pasted_text_can_be_chunked(qapp: QApplication, tmp_path: Path) -> None:
    """The paste path. It needs no filename, which is why `detect_strategy` takes one
    optionally."""
    dialog = _loaded(_app(tmp_path))

    assert [p.headline for p in dialog.proposals] == [
        "What was your hardest migration?",
        "Why are you leaving?",
    ]


def test_a_markdown_file_is_read_and_its_strategy_detected(
    qapp: QApplication, tmp_path: Path
) -> None:
    """The `.md` path. The suffix is what picks the header strategy, so the box has to
    follow the file rather than stay on whatever the last source needed."""
    source = tmp_path / "prep.md"
    source.write_text(MARKDOWN, encoding="utf-8")
    dialog = _dialog(_app(tmp_path), choose_file=lambda: source)
    dialog._select_strategy(ChunkStrategy.BLANK_LINE)

    assert dialog.choose_file() is True

    assert dialog.strategy is ChunkStrategy.MD_HEADER
    assert dialog.source_edit.toPlainText() == MARKDOWN
    assert dialog.filename == "prep.md"


def test_a_txt_file_with_q_lines_detects_the_qa_convention(
    qapp: QApplication, tmp_path: Path
) -> None:
    source = tmp_path / "prep.txt"
    source.write_text(QA_TEXT, encoding="utf-8")
    dialog = _dialog(_app(tmp_path), choose_file=lambda: source)

    assert dialog.choose_file() is True

    assert dialog.strategy is ChunkStrategy.QA_CONVENTION


def test_an_unsupported_suffix_is_refused(qapp: QApplication, tmp_path: Path) -> None:
    """FR1a names `.txt` and `.md`. A `.docx` is FR1b, deferred under D-U1, and silently
    reading it as text would produce chunks of XML."""
    source = tmp_path / "prep.docx"
    source.write_text("not really a docx", encoding="utf-8")
    dialog = _dialog(_app(tmp_path), choose_file=lambda: source)

    assert dialog.choose_file() is False
    assert "not a .txt or .md" in dialog.status.text()
    assert dialog.source_edit.toPlainText() == ""


def test_an_unreadable_file_reports_rather_than_raises(qapp: QApplication, tmp_path: Path) -> None:
    missing = tmp_path / "gone.md"
    dialog = _dialog(_app(tmp_path), choose_file=lambda: missing)

    assert dialog.choose_file() is False
    assert "could not be read" in dialog.status.text()


# ---------- FR2: named strategy, switchable, every chunk reviewable ----------


def test_the_strategy_is_named_in_words(qapp: QApplication, tmp_path: Path) -> None:
    """FR2 says the chosen strategy is *named* in the review UI. `md_header` is an
    identifier, not a name."""
    dialog = _loaded(_app(tmp_path))

    assert STRATEGY_NAMES[ChunkStrategy.MD_HEADER] in dialog.status.text()
    assert dialog.strategy_box.currentText() == STRATEGY_NAMES[ChunkStrategy.MD_HEADER]


def test_switching_the_strategy_re_chunks(qapp: QApplication, tmp_path: Path) -> None:
    """FR2: "the user can switch it before saving". Switching that did not re-chunk would
    be a label, not a control."""
    dialog = _loaded(_app(tmp_path))
    assert len(dialog.proposals) == 2

    _choose(dialog, ChunkStrategy.BLANK_LINE)

    assert dialog.strategy is ChunkStrategy.BLANK_LINE
    assert [p.headline for p in dialog.proposals] != [
        "What was your hardest migration?",
        "Why are you leaving?",
    ]


def test_re_chunking_over_edits_is_confirmed(qapp: QApplication, tmp_path: Path) -> None:
    """Re-chunking discards what the user typed into the review pane. Correct, and not
    something to do silently."""
    refused: list[str] = []

    def confirm(message: str) -> bool:
        refused.append(message)
        return False

    dialog = _loaded(_app(tmp_path), confirm=confirm)
    dialog.headline_edit.setText("A headline I typed myself?")
    dialog._on_edited()

    _choose(dialog, ChunkStrategy.BLANK_LINE)

    assert refused  # asked
    assert dialog.proposals[0].headline == "A headline I typed myself?"  # and kept


def test_every_chunk_is_listed_and_editable(qapp: QApplication, tmp_path: Path) -> None:
    """FR2: presented for review *and editable* before save."""
    dialog = _loaded(_app(tmp_path))

    assert dialog.chunk_list.count() == len(dialog.proposals) == 2

    dialog.chunk_list.setCurrentRow(1)
    dialog.headline_edit.setText("Why do you want to leave?")
    dialog._on_edited()

    assert dialog.proposals[1].headline == "Why do you want to leave?"
    assert "Why do you want to leave?" in dialog.chunk_list.item(1).text()


def test_a_rewritten_headline_clears_its_own_warning(qapp: QApplication, tmp_path: Path) -> None:
    """The flag is the importer's opinion of the *original* text. Leaving it up after the
    user has rewritten the headline tells them to fix what they just fixed."""
    dialog = _loaded(_app(tmp_path), text="A statement, not a question\n\nBody here.")
    _choose(dialog, ChunkStrategy.BLANK_LINE)
    assert dialog.proposals[0].needs_headline_review is True

    dialog.chunk_list.setCurrentRow(0)
    dialog.headline_edit.setText("Is this a question?")
    dialog._on_edited()

    assert dialog.proposals[0].needs_headline_review is False
    assert dialog.advisory.text() == ""


def test_a_chunk_can_be_dropped_before_import(qapp: QApplication, tmp_path: Path) -> None:
    """The review step exists to keep bad chunks out, not to import them and delete them
    afterwards."""
    dialog = _loaded(_app(tmp_path))
    dialog.chunk_list.setCurrentRow(0)

    assert dialog.drop_selected() is True

    assert [p.headline for p in dialog.proposals] == ["Why are you leaving?"]
    assert dialog.chunk_list.count() == 1


def test_the_import_is_blocked_until_there_are_chunks(qapp: QApplication, tmp_path: Path) -> None:
    """FR2: save is blocked until the review has happened. With nothing chunked there is
    nothing reviewed."""
    dialog = _dialog(_app(tmp_path))

    assert dialog.import_button.isEnabled() is False
    assert dialog.import_now() is False
    assert dialog.status.text() == NOTHING_TO_IMPORT_TEXT


def test_chunking_empty_text_says_what_to_do(qapp: QApplication, tmp_path: Path) -> None:
    dialog = _dialog(_app(tmp_path))

    assert dialog.analyse() is False
    assert dialog.status.text() == NOTHING_TO_IMPORT_TEXT


def test_a_flagged_headline_is_visible_in_the_list(qapp: QApplication, tmp_path: Path) -> None:
    """A warning only in the detail pane is a warning the user has to go looking for."""
    dialog = _loaded(_app(tmp_path), text="A statement, not a question\n\nBody here.")
    _choose(dialog, ChunkStrategy.BLANK_LINE)

    assert "⚠" in summarise(dialog.proposals[0])
    assert "⚠" in dialog.chunk_list.item(0).text()


# ---------- FR66: replace one kind, leave the other four ----------


def test_importing_adds_the_notes_and_saves_them(qapp: QApplication, tmp_path: Path) -> None:
    app = _app(tmp_path)
    store = NotesStore(tmp_path)
    store.save(app.context_set)
    dialog = _loaded(app, store=store)

    assert dialog.import_now() is True

    assert [n.headline for n in app.context_set.notes] == [
        "What was your hardest migration?",
        "Why are you leaving?",
    ]
    assert [n.headline for n in store.load(app.context_set.id).notes] == [
        "What was your hardest migration?",
        "Why are you leaving?",
    ]


def test_importing_re_embeds(qapp: QApplication, tmp_path: Path) -> None:
    """JSON is not vectors. An imported note is matched on nothing at all until the index
    is rebuilt (FR34) — the same defect PR #27 found in the editor's save."""
    app = _app(tmp_path)
    store = NotesStore(tmp_path)
    store.save(app.context_set)
    dialog = _loaded(app, store=store)

    assert dialog.import_now() is True

    assert app.index.note_ids == [n.id for n in app.context_set.notes]


def test_importing_one_kind_leaves_the_others_alone(qapp: QApplication, tmp_path: Path) -> None:
    """FR66. Re-importing a job description means *this* is the job description now; it
    does not mean the resume changes."""
    resume = Note(headline="Senior engineer, Acme?", body="Five years.", kind=SourceKind.RESUME)
    old_role = Note(headline="Old posting?", body="Superseded.", kind=SourceKind.ROLE)
    app = _app(tmp_path, ContextSet(name="Acme", notes=[resume, old_role]))
    store = NotesStore(tmp_path)
    store.save(app.context_set)
    dialog = _loaded(app, store=store)
    dialog.kind_box.setCurrentIndex(dialog.kind_box.findData(SourceKind.ROLE))

    assert dialog.import_now() is True

    kinds = [n.kind for n in app.context_set.notes]
    assert old_role.id not in [n.id for n in app.context_set.notes]  # replaced
    assert resume.id in [n.id for n in app.context_set.notes]  # untouched, same id
    assert kinds.count(SourceKind.ROLE) == 2


def test_replacing_an_existing_kind_is_confirmed_with_the_count(
    qapp: QApplication, tmp_path: Path
) -> None:
    """FR60. "This cannot be undone" is only fair if it says how much."""
    seen: list[str] = []
    old = Note(headline="Old posting?", body="Superseded.", kind=SourceKind.ROLE)
    app = _app(tmp_path, ContextSet(name="Acme", notes=[old]))
    NotesStore(tmp_path).save(app.context_set)
    dialog = _loaded(app, confirm=lambda message: bool(seen.append(message)) or False)
    dialog.kind_box.setCurrentIndex(dialog.kind_box.findData(SourceKind.ROLE))

    assert dialog.import_now() is False  # declined

    assert "replaces the 1 role note(s)" in seen[0]
    assert [n.id for n in app.context_set.notes] == [old.id]  # nothing happened


def test_importing_into_an_empty_kind_does_not_claim_to_replace_anything(
    qapp: QApplication, tmp_path: Path
) -> None:
    seen: list[str] = []
    app = _app(tmp_path)
    NotesStore(tmp_path).save(app.context_set)
    dialog = _loaded(app, confirm=lambda message: bool(seen.append(message)) or True)

    assert dialog.import_now() is True
    assert "replaces" not in seen[0]


# ---------- FR42, and the session rule ----------


def test_a_non_verbatim_bullet_is_refused_before_anything_is_removed(
    qapp: QApplication, tmp_path: Path
) -> None:
    """FR42 at the boundary that matters: `add_source` verifies before it removes, so a
    bad bullet leaves the existing source intact and the user in a fixable state."""
    old = Note(headline="Old posting?", body="Superseded.", kind=SourceKind.ROLE)
    app = _app(tmp_path, ContextSet(name="Acme", notes=[old]))
    NotesStore(tmp_path).save(app.context_set)
    dialog = _loaded(app)
    dialog.kind_box.setCurrentIndex(dialog.kind_box.findData(SourceKind.ROLE))
    dialog.chunk_list.setCurrentRow(0)
    dialog.bullets_edit.setPlainText("A bullet that appears nowhere in the note")
    dialog._on_edited()

    assert dialog.import_now() is False

    assert "Not imported" in dialog.status.text()
    assert [n.id for n in app.context_set.notes] == [old.id]
    assert dialog.proposals  # still on screen to fix


def test_importing_is_refused_mid_session(qapp: QApplication, tmp_path: Path) -> None:
    """D-61's reason by a different route: this removes every note of the chosen kind, and
    the tracker's verdict and the report's D-58 snapshot describe the set the session
    started with."""
    app = _app(tmp_path)
    NotesStore(tmp_path).save(app.context_set)
    dialog = _loaded(app)
    app.session.request_start()
    app.session.preflight_result(blocked=False)

    assert dialog.import_now() is False

    assert "session is running" in dialog.status.text().lower()
    assert app.context_set.notes == []


def test_an_import_is_recorded(qapp: QApplication, tmp_path: Path) -> None:
    app = _app(tmp_path)
    NotesStore(tmp_path).save(app.context_set)

    assert _loaded(app).import_now() is True

    assert any(e.event == "notes_imported" for e in app.ring.snapshot())


# ---------- the editor's way in ----------


class SpyImport:
    def __init__(self) -> None:
        self.opened = 0

    def __call__(self, application, store, parent):  # type: ignore[no-untyped-def]
        self.opened += 1
        return ImportDialog(application, store=store, confirm=lambda _m: True, parent=parent)


def _editor(app: Application, **kwargs) -> NotesEditor:  # type: ignore[no-untyped-def]
    kwargs.setdefault("settings", FakeSettings())
    kwargs.setdefault("confirm", lambda _message: True)
    kwargs.setdefault("prompt", lambda _title, default: default)
    return NotesEditor(app, **kwargs)


def test_the_editor_opens_the_import_surface(qapp: QApplication, tmp_path: Path) -> None:
    """T3.7a's whole point. The importer had no caller anywhere."""
    spy = SpyImport()
    editor = _editor(_app(tmp_path), import_factory=spy)

    assert editor.open_import() is not None
    assert spy.opened == 1


def test_a_refused_save_blocks_opening_the_import(qapp: QApplication, tmp_path: Path) -> None:
    """The import writes this set too, so an unsaved non-verbatim bullet would be carried
    into that write — past the check that refused it in the editor."""
    note = Note(headline="A question?", body="A body.", kind=SourceKind.PREP)
    app = _app(tmp_path, ContextSet(name="Acme", notes=[note]))
    spy = SpyImport()
    editor = _editor(app, import_factory=spy)
    editor.note_list.setCurrentRow(0)
    editor.bullets_edit.setPlainText("Not in the note at all")
    editor._on_edited()

    assert editor.open_import() is None

    assert spy.opened == 0
    assert editor.dirty is True


def test_the_editor_shows_what_was_imported(qapp: QApplication, tmp_path: Path) -> None:
    """The set this window is showing gained notes underneath it."""
    app = _app(tmp_path)
    NotesStore(tmp_path).save(app.context_set)
    editor = _editor(app, import_factory=SpyImport())
    dialog = editor.open_import()
    assert dialog is not None
    dialog.source_edit.setPlainText(MARKDOWN)
    _choose(dialog, ChunkStrategy.MD_HEADER)

    assert dialog.import_now() is True

    assert editor.note_list.count() == 2
    assert "Imported 2 note(s)" in editor.status.text()


# ---------- found while reviewing this branch ----------


def test_pasted_qa_notes_are_auto_detected(qapp: QApplication, tmp_path: Path) -> None:
    """FR2 makes `.txt` auto-detected. On the paste path there is no filename and the
    strategy box is simply sitting on whichever member is listed first, so passing its
    value unconditionally chunked pasted Q/A notes as Markdown headings — which produces
    nothing at all."""
    dialog = _dialog(_app(tmp_path))
    dialog.source_edit.setPlainText(QA_TEXT)

    assert dialog.analyse() is True

    assert dialog.strategy is ChunkStrategy.QA_CONVENTION
    assert [p.headline for p in dialog.proposals] == [
        "What was your hardest migration?",
        "Why are you leaving?",
    ]


def test_an_explicit_strategy_is_not_second_guessed(qapp: QApplication, tmp_path: Path) -> None:
    """Detection stops once the user has chosen. Otherwise the control FR2 requires would
    be overridden the moment it was used."""
    dialog = _dialog(_app(tmp_path))
    dialog.source_edit.setPlainText(QA_TEXT)
    _choose(dialog, ChunkStrategy.BLANK_LINE)

    assert dialog.strategy is ChunkStrategy.BLANK_LINE
    assert len(dialog.proposals) == 2  # blank-line split, not the Q/A split


def test_a_bad_bullet_elsewhere_in_the_set_stops_the_import(
    qapp: QApplication, tmp_path: Path
) -> None:
    """This dialog is modeless, so the editor can make the *rest* of the set unsavable
    while it is open. `add_source` verifies only what is coming in and `save` verifies
    everything, so the write would have raised out of a Qt slot with the set already
    replaced in memory and untouched on disk."""
    resume = Note(headline="Senior engineer?", body="Five years.", kind=SourceKind.RESUME)
    app = _app(tmp_path, ContextSet(name="Acme", notes=[resume]))
    NotesStore(tmp_path).save(app.context_set)
    dialog = _loaded(app)
    resume.bullets = ["A bullet that is nowhere in the resume"]

    assert dialog.import_now() is False

    assert "Not imported" in dialog.status.text()
    assert [n.id for n in app.context_set.notes] == [resume.id]  # nothing replaced


def test_changing_the_source_blocks_the_import(qapp: QApplication, tmp_path: Path) -> None:
    """**The review list must describe what the user is looking at.**

    Pasting a second source left the previous source's chunks on screen with Import still
    live — and because the import replaces every note of the chosen kind, pressing it
    would have destroyed the user's notes in favour of a file they were not looking at.
    Found by review on PR #30.
    """
    app = _app(tmp_path)
    NotesStore(tmp_path).save(app.context_set)
    dialog = _loaded(app)
    assert dialog.import_button.isEnabled() is True

    dialog.source_edit.setPlainText("## A completely different source\nWith other notes.")

    assert dialog.stale is True
    assert dialog.import_button.isEnabled() is False
    assert dialog.import_now() is False
    assert app.context_set.notes == []


def test_edits_survive_a_source_change(qapp: QApplication, tmp_path: Path) -> None:
    """Disabling, not discarding: clearing the list would throw away review edits every
    time the user touched the source box. Undoing the change re-enables the import,
    because staleness is a comparison rather than a flag."""
    dialog = _loaded(_app(tmp_path))
    dialog.headline_edit.setText("An edit worth keeping?")
    dialog._on_edited()

    dialog.source_edit.setPlainText("something else")
    assert dialog.proposals[0].headline == "An edit worth keeping?"

    dialog.source_edit.setPlainText(MARKDOWN)
    assert dialog.stale is False
    assert dialog.import_button.isEnabled() is True


def test_declining_a_re_chunk_puts_the_selector_back(qapp: QApplication, tmp_path: Path) -> None:
    """FR2 requires the review UI to *name* the strategy the chunks were made with.
    Leaving the box on the declined choice names one that was never applied, and the user
    can import that misreading. Found by review on PR #30."""
    dialog = _loaded(_app(tmp_path), confirm=lambda _message: False)
    dialog.headline_edit.setText("An edit?")
    dialog._on_edited()

    _choose(dialog, ChunkStrategy.BLANK_LINE)

    assert dialog.strategy is ChunkStrategy.MD_HEADER
    assert dialog.strategy_box.currentText() == STRATEGY_NAMES[ChunkStrategy.MD_HEADER]
