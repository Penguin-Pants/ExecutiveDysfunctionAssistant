"""The import surface (T3.7a — FR1a, FR2, FR42, FR66, FR67).

T3.5 built the chunkers, the strategy detection and the verbatim bullet proposal; T10.3
built `add_source`, the per-kind replacement. Both had passing tests and **neither had a
caller** — so a `.md` of prep notes could not be brought into the product at all, and the
five kinds FR66 describes could only be created by hand, one note at a time, in the
editor. The fifth instance of this project's characteristic missing join, in the feature
that is the user's first contact with the app.

**FR2 is the shape of this dialog, not a step inside it.** The requirement is that every
auto-split chunk is *presented for review and editable before save*, that the chosen
strategy is *named*, and that the user can *switch it* before saving. So the review list
is the dialog's main body rather than a confirmation at the end, the strategy is a control
rather than a label, and the Import button is the confirmation FR2 blocks the save on —
it does nothing until there are proposals on screen.

**Re-chunking is destructive to edits, and says so.** Switching strategy re-runs the
chunker over the source, which discards anything typed into the review pane. That is the
correct behaviour — a different strategy means different chunks — but it is not something
to do silently, so it is confirmed once edits exist.

**Importing replaces one kind and leaves the other four alone** (FR66, via `add_source`).
Replacement is what re-importing a job description means, and it is destructive: the notes
of that kind are removed. It takes FR60's confirmation, with the count in it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from interview_prep_recall.notes.importer import (
    ChunkStrategy,
    ProposedNote,
    add_source,
    detect_strategy,
    headline_needs_review,
    import_text,
)
from interview_prep_recall.notes.model import SourceKind
from interview_prep_recall.notes.store import NotesStore

if TYPE_CHECKING:
    from interview_prep_recall.app import Application

TITLE = "Import notes"

STRATEGY_NAMES = {
    ChunkStrategy.MD_HEADER: "Markdown headings (## and ###)",
    ChunkStrategy.QA_CONVENTION: "Q: / A: pairs",
    ChunkStrategy.BLANK_LINE: "Blank lines",
}
"""FR2: "the chosen strategy is named in the review UI". The enum values are identifiers;
these are the names a person reads."""

HEADLINE_REVIEW_TEXT = (
    "This headline is long or is not a question. Only the headline is matched against "
    "what the interviewer says, so it is worth rewriting as the question it answers."
)
"""The importer's `needs_headline_review` flag, said in terms of what it costs. Design §5a
is the reason it matters: `headline` is the only embedded field."""

NOTHING_TO_IMPORT_TEXT = "Paste your notes or choose a file, then press “Chunk it”."

RECHUNK_WARNING = (
    "Re-chunking with a different strategy will discard the edits you have made to the "
    "chunks below. Continue?"
)

SESSION_LOCKED_TEXT = (
    "A session is running. Stop it before importing — importing replaces every note of "
    "the chosen kind, and the tracker and the report read the set the session started "
    "with."
)

READABLE_SUFFIXES = (".txt", ".md")
"""FR1a's two file paths. Paste is the third and needs no suffix."""

Confirmer = Callable[[str], bool]
FileChooser = Callable[[], Path | None]
"""Injected so the two destructive-or-modal steps are testable without driving a dialog."""


def summarise(proposal: ProposedNote) -> str:
    """One row of the review list: what will become a note, and whether it needs a look."""
    flag = "⚠ " if proposal.needs_headline_review else ""
    headline = proposal.headline or "(no headline)"
    bullets = len(proposal.bullets)
    return f"{flag}line {proposal.source_line}: {headline}  ({bullets} bullet(s))"


class ImportDialog(QDialog):
    """Paste or open a file, review the chunks, import them into one kind (T3.7a)."""

    imported = Signal(int)
    """Emitted with the number of notes imported. The editor that opened this dialog is
    showing the set that just changed underneath it."""

    def __init__(
        self,
        application: Application,
        *,
        store: NotesStore | None = None,
        confirm: Confirmer | None = None,
        choose_file: FileChooser | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        self.application = application
        self.store = store if store is not None else NotesStore(application.root)
        self._confirm = confirm if confirm is not None else self._ask
        self._choose_file = choose_file if choose_file is not None else self._ask_for_file
        self.proposals: list[ProposedNote] = []
        self.filename: str | None = None
        self._edited = False
        self._strategy_chosen = False
        """Whether the user has picked a strategy themselves. Until they do, FR2's
        detection runs on every chunk — see `analyse`."""
        self._loading = False

        layout = QVBoxLayout(self)

        # ---- the source (FR1a: paste, .txt, .md) ----
        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Paste your notes, or:", self))
        self.choose_button = QPushButton("Choose a .txt or .md file…", self)
        self.choose_button.clicked.connect(self.choose_file)
        source_row.addWidget(self.choose_button)
        layout.addLayout(source_row)

        self.source_edit = QPlainTextEdit(self)
        layout.addWidget(self.source_edit)

        # ---- the strategy (FR2: named, and switchable before saving) ----
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Split on:", self))
        self.strategy_box = QComboBox(self)
        for strategy in ChunkStrategy:
            self.strategy_box.addItem(STRATEGY_NAMES[strategy], strategy)
        self.strategy_box.currentIndexChanged.connect(self._on_strategy_changed)
        controls.addWidget(self.strategy_box, 1)
        controls.addWidget(QLabel("Import as:", self))
        self.kind_box = QComboBox(self)
        for kind in SourceKind:
            self.kind_box.addItem(kind.value, kind)
        controls.addWidget(self.kind_box)
        self.chunk_button = QPushButton("Chunk it", self)
        self.chunk_button.clicked.connect(self.analyse)
        controls.addWidget(self.chunk_button)
        layout.addLayout(controls)

        # ---- the review (FR2: every chunk presented and editable before save) ----
        review = QHBoxLayout()
        self.chunk_list = QListWidget(self)
        self.chunk_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.chunk_list.currentRowChanged.connect(self._on_chunk_selected)
        review.addWidget(self.chunk_list, 1)

        form = QVBoxLayout()
        self.headline_edit = QLineEdit(self)
        self.headline_edit.textEdited.connect(self._on_edited)
        form.addWidget(QLabel("Headline (the question this answers):", self))
        form.addWidget(self.headline_edit)
        self.body_edit = QPlainTextEdit(self)
        self.body_edit.textChanged.connect(self._on_edited)
        form.addWidget(QLabel("Body:", self))
        form.addWidget(self.body_edit)
        self.bullets_edit = QPlainTextEdit(self)
        self.bullets_edit.textChanged.connect(self._on_edited)
        form.addWidget(QLabel("Bullets — verbatim from the text above (FR42):", self))
        form.addWidget(self.bullets_edit)
        self.advisory = QLabel("", self)
        self.advisory.setWordWrap(True)
        self.advisory.setTextFormat(Qt.TextFormat.PlainText)
        form.addWidget(self.advisory)
        review.addLayout(form, 2)
        layout.addLayout(review)

        self.status = QLabel(NOTHING_TO_IMPORT_TEXT, self)
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        self.drop_button = QPushButton("Drop this chunk", self)
        self.drop_button.clicked.connect(self.drop_selected)
        self.import_button = QPushButton("Import…", self)
        self.import_button.clicked.connect(self.import_now)
        self.close_button = QPushButton("Close", self)
        self.close_button.clicked.connect(self.reject)
        for button in (self.drop_button, self.import_button, self.close_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        self._refresh_buttons()

    # ---------- the source ----------

    def choose_file(self) -> bool:
        """FR1a's file paths. **Reading is not writing** — this is the user opening their
        own file, and the FR16 allowlist governs where the app *writes*."""
        path = self._choose_file()
        if path is None:
            return False
        if path.suffix.lower() not in READABLE_SUFFIXES:
            self.status.setText(f"{path.name} is not a .txt or .md file.")
            return False
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:  # a UI boundary
            self.status.setText(f"{path.name} could not be read: {error}")
            return False
        self.filename = path.name
        self.source_edit.setPlainText(text)
        # A new source gets a fresh reading: the previous file's override should not
        # decide how this one is split.
        self._strategy_chosen = False
        # The suffix decides the strategy for `.md`, so re-detect rather than leaving the
        # box on whatever the previous source needed.
        self._select_strategy(detect_strategy(text, path.name))
        self.status.setText(f"Loaded {path.name}. Press “Chunk it” to review the chunks.")
        return True

    def _select_strategy(self, strategy: ChunkStrategy) -> None:
        self._loading = True
        try:
            index = self.strategy_box.findData(strategy)
            if index >= 0:
                self.strategy_box.setCurrentIndex(index)
        finally:
            self._loading = False

    @property
    def strategy(self) -> ChunkStrategy:
        """**Coerced back to the enum on the way out.**

        `ChunkStrategy` is a `StrEnum`, and Qt stores a `str` subclass as a plain `str` —
        so `currentData()` returns `"md_header"`, not the member. Everything downstream
        happens to work, because a `StrEnum` hashes and compares as its value, which is
        exactly why this is worth fixing rather than living with: the property is annotated
        `ChunkStrategy`, mypy cannot see through Qt's `Any`, and the first caller to write
        `is ChunkStrategy.MD_HEADER` would be quietly wrong. (`SourceKind` is a plain
        `Enum` and round-trips as the object, which is why `kind` needs none of this.)
        """
        chosen = self.strategy_box.currentData()
        return ChunkStrategy(chosen) if chosen is not None else ChunkStrategy.BLANK_LINE

    @property
    def kind(self) -> SourceKind:
        chosen = self.kind_box.currentData()
        return chosen if chosen is not None else SourceKind.PREP

    # ---------- chunking (FR2) ----------

    def analyse(self) -> bool:
        """Run the chunker and put every chunk on screen for review.

        **Detection runs until the user overrides it.** FR2 makes `.txt` auto-detected —
        two or more `Q:` lines pick the Q/A convention — and passing the combo box's value
        unconditionally would defeat that on the paste path, where there is no filename
        and the box is simply sitting on whichever strategy is listed first. Pasted Q/A
        notes would then be chunked as Markdown headings and produce nothing. Once the
        user has picked a strategy themselves, their choice wins and detection stops
        second-guessing it.
        """
        text = self.source_edit.toPlainText()
        if not text.strip():
            self.status.setText(NOTHING_TO_IMPORT_TEXT)
            return False
        result = import_text(text, self.filename, self.strategy if self._strategy_chosen else None)
        self.proposals = result.proposals
        self._edited = False
        self._select_strategy(result.strategy)
        self._refresh_chunks()
        if not self.proposals:
            self.status.setText(
                "That split produced no chunks. Try a different strategy, or check the "
                "text has the structure you expect."
            )
        else:
            self.status.setText(
                f"{len(self.proposals)} chunk(s), split on "
                f"{STRATEGY_NAMES[result.strategy]}. Review and edit them, then import."
            )
        return True

    def _on_strategy_changed(self, _index: int) -> None:
        if self._loading:
            return
        if not self.source_edit.toPlainText().strip():
            return
        if self._edited and not self._confirm(RECHUNK_WARNING):
            return
        self._strategy_chosen = True
        self.analyse()

    def _refresh_chunks(self) -> None:
        self._loading = True
        try:
            row = self.chunk_list.currentRow()
            self.chunk_list.clear()
            for proposal in self.proposals:
                self.chunk_list.addItem(QListWidgetItem(summarise(proposal)))
            if self.chunk_list.count():
                self.chunk_list.setCurrentRow(min(max(row, 0), self.chunk_list.count() - 1))
        finally:
            self._loading = False
        self._load_selected()
        self._refresh_buttons()

    @property
    def selected(self) -> ProposedNote | None:
        row = self.chunk_list.currentRow()
        if not 0 <= row < len(self.proposals):
            return None
        return self.proposals[row]

    def _on_chunk_selected(self, _row: int) -> None:
        if self._loading:
            return
        self._load_selected()

    def _load_selected(self) -> None:
        proposal = self.selected
        self._loading = True
        try:
            self.headline_edit.setText("" if proposal is None else proposal.headline)
            self.body_edit.setPlainText("" if proposal is None else proposal.body)
            self.bullets_edit.setPlainText("" if proposal is None else "\n".join(proposal.bullets))
        finally:
            self._loading = False
        self._refresh_advisory()

    def _refresh_advisory(self) -> None:
        proposal = self.selected
        if proposal is not None and proposal.needs_headline_review:
            self.advisory.setText(HEADLINE_REVIEW_TEXT)
        else:
            self.advisory.setText("")

    def _on_edited(self) -> None:
        """FR2's "editable before save", applied to the proposal in memory."""
        if self._loading:
            return
        proposal = self.selected
        if proposal is None:
            return
        proposal.headline = self.headline_edit.text()
        proposal.body = self.body_edit.toPlainText()
        proposal.bullets = [line for line in self.bullets_edit.toPlainText().splitlines() if line]
        # The flag is the importer's opinion of the *original* headline. Once the user has
        # rewritten it, keeping the warning up would be telling them to fix what they just
        # fixed — so it is recomputed against what is now there.
        proposal.needs_headline_review = headline_needs_review(proposal.headline)
        self._edited = True
        item = self.chunk_list.currentItem()
        if item is not None:
            item.setText(summarise(proposal))
        self._refresh_advisory()

    def drop_selected(self) -> bool:
        """A chunk the user does not want is dropped here rather than imported and then
        deleted in the editor — the review step exists to keep bad chunks out."""
        proposal = self.selected
        if proposal is None:
            return False
        self.proposals.remove(proposal)
        self._edited = True
        self._refresh_chunks()
        self.status.setText(f"{len(self.proposals)} chunk(s) left to import.")
        return True

    def _refresh_buttons(self) -> None:
        # FR2: the save is blocked until there is something reviewed to save.
        self.import_button.setEnabled(bool(self.proposals))
        self.drop_button.setEnabled(self.selected is not None)

    # ---------- importing (FR66, FR60, FR42) ----------

    def import_now(self) -> bool:
        """Replace this kind with the reviewed chunks, then persist and re-embed.

        **Refused mid-session**, for D-61's reason arriving by a different route: this
        removes every note of the chosen kind, and the tracker's coverage verdict and the
        report's D-58 snapshot both describe the set the session started with.
        """
        if not self.proposals:
            self.status.setText(NOTHING_TO_IMPORT_TEXT)
            return False
        if not self.application.can_change_context_set:
            self.status.setText(SESSION_LOCKED_TEXT)
            return False
        context_set = self.application.context_set
        kind = self.kind
        replacing = sum(1 for note in context_set.notes if note.kind == kind)
        message = f"Import {len(self.proposals)} note(s) as {kind.value}?"
        if replacing:
            # FR66's replacement is destructive, so FR60's confirmation carries the count
            # rather than the word "some".
            message += (
                f" This replaces the {replacing} {kind.value} note(s) already in "
                f"“{context_set.name}”. The other kinds are untouched."
            )
        if not self._confirm(message):
            return False
        try:
            # **The survivors are checked too, before anything is removed.** `add_source`
            # verifies the incoming notes, and `NotesStore.save` verifies the whole set —
            # so a non-verbatim bullet typed into the *editor* while this modeless dialog
            # was open would pass the first check, get past the replacement, and then
            # raise out of `save`, inside a Qt slot, with the set already mutated in
            # memory and unchanged on disk. Checking here keeps the property `add_source`
            # was built around: nothing is destroyed until everything validates.
            for note in context_set.notes:
                if note.kind is not kind:
                    note.verify_bullets_verbatim()
            count = add_source(context_set, self.proposals, kind)
        except ValueError as error:
            # FR42, checked by `add_source` **before** it removes anything — so a bullet
            # that is not in its own note leaves the existing source intact and the user
            # in a state they can fix.
            self.status.setText(f"Not imported — {error}")
            return False
        self.store.save(context_set)
        # Vectors, not just JSON: an imported note is matched on nothing at all until
        # this runs (FR34).
        self.application.notes_changed()
        self.application.ring.record(
            "notes_imported",
            noteset_id=context_set.id,
            count=count,
            code=str(kind.value),
        )
        self.proposals = []
        self._refresh_chunks()
        self.status.setText(f"Imported {count} note(s) as {kind.value}.")
        self.imported.emit(count)
        return True

    # ---------- default Qt prompts ----------

    def _ask(self, message: str) -> bool:
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self,
            "Import?",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _ask_for_file(self) -> Path | None:
        from PySide6.QtWidgets import QFileDialog

        name, _filter = QFileDialog.getOpenFileName(
            self, "Choose notes to import", "", "Notes (*.txt *.md)"
        )
        return Path(name) if name else None
