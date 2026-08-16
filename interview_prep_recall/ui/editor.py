"""The notes editor and note-set lifecycle (T3.7, T3.8 — FR3, FR4, FR41, FR43, FR60, D-6).

**The last surface with no way in.** Notes could be imported, matched, tracked, embedded
and reported on; they could not be *written*. The store, the model, the importer and the
index all had tests, and the product had no way to create a note — the same missing-join
shape as the match feed (T5.10), one layer further out.

**Saving is debounced, never per keystroke** (T3.7). FR29 keeps five backup generations
and `NotesStore.save` rotates on every write, so a save per keystroke would consume all
five within one sentence and leave the user's recovery window covering the last twelve
characters they typed. Edits mark the set dirty; `flush()` writes. The timer is a
convenience over `flush`, so the behaviour under test is the behaviour that ships.

**Ids never change** (FR41). Editing mutates the note the set already holds rather than
replacing it: the embedding cache is keyed on note id, and a new id on every edit would
silently invalidate every vector — the BC-1 stale-vector failure, arriving through the
editor instead of through the index.

**Kind is not editable** (FR67). It is chosen once, at creation, and re-classifying means
delete and re-import. The control is offered for a new note and disabled for an existing
one, which is the requirement made visible rather than an error the user meets after
typing.

**Switching sets goes through `Application.activate_context_set`** (FR43), never by
assigning the attribute: the index and the prefilter hold their own references, and a set
swapped in behind them leaves matching drawing from the previous corpus.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
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

from interview_prep_recall.diagnostics.ring import DiagnosticRing
from interview_prep_recall.notes.model import TRACKABLE_KINDS, ContextSet, Note, SourceKind
from interview_prep_recall.notes.store import NotesStore, NotesStoreError, SchemaTooNewError
from interview_prep_recall.ui.import_notes import ImportDialog
from interview_prep_recall.ui.restore import RestoreDialog

if TYPE_CHECKING:
    from interview_prep_recall.app import Application

TITLE = "Notes"

SAVE_DEBOUNCE_MS = 5_000
"""T3.7: five seconds idle, or an explicit action. Never per keystroke — see the module
note on what that would do to FR29's five backup generations."""

ACTIVE_SET_KEY = "notes/active_set_id"
"""FR43's "exactly one active per session", persisted across restarts (T3.8)."""

NOT_OPTIMISED_TEXT = "No bullets — the overlay will show the start of the body (D-6)."
"""D-6's advisory. The note still works; it renders less well, and the editor says so
rather than blocking a save the requirement permits."""

TRACK_DISABLED_TEXT = "Only prep notes and resume entries can be tracked (FR70)."

UNREADABLE_LABEL = "⚠ Unreadable set {short}… — select to restore"
"""How a corrupt set appears in the selector (T3.9). It is listed rather than hidden
because selecting it is the only route to its backups — see `refresh_sets`."""

Confirmer = Callable[[str], bool]
"""FR60's confirmation for destructive actions. Injected so the requirement is testable
without driving a modal."""

Prompter = Callable[[str, str], str | None]
"""Asks for a name, given a title and a default. None if the user cancelled."""

RestoreFactory = Callable[["Application", str, NotesStore, QWidget], RestoreDialog]
"""How T3.9's dialog gets built. Injected for the same reason the confirmer is: a test
about *when* the offer appears should not have to drive the window that appears."""

ImportFactory = Callable[["Application", NotesStore, QWidget], ImportDialog]
"""The same, for T3.7a's import surface."""


def _open_restore(
    application: Application, noteset_id: str, store: NotesStore, parent: QWidget
) -> RestoreDialog:
    return RestoreDialog(application, noteset_id, store=store, parent=parent)


def _open_import(application: Application, store: NotesStore, parent: QWidget) -> ImportDialog:
    return ImportDialog(application, store=store, parent=parent)


def active_set_id(settings: object) -> str | None:
    """The set FR43 says is active, as persisted by this editor (T3.8).

    Exists so the composition root has something to *read* — the id was being written
    with no reader anywhere, which is D-20's shape and was found by review on PR #27.
    `__main__._build_application` (T9.6a) names FR43's selection as one of its blockers;
    this is that blocker's answer, and `load_active_set` below is the whole of it.
    """
    value = settings.value(ACTIVE_SET_KEY, None)  # type: ignore[attr-defined]
    return str(value) if value else None


def load_active_set(
    root: Path,
    settings: object,
    store: NotesStore | None = None,
    ring: DiagnosticRing | None = None,
) -> ContextSet:
    """The set to start with: the persisted one, else the only one, else a new one.

    **Never raises for an ordinary state.** A first run has no sets, and a persisted id
    can name a set the user deleted from another machine's synced folder — both are
    situations the entry point has to survive, so they fall through to the next answer
    rather than up the stack.

    **A corrupt set is recovered, not skipped** (FR44, T3.9). Falling through to the next
    candidate is how the user's notes turn into an empty editor: their set is on disk with
    five readable backups beside it, and the app opens showing nothing — the exact
    "starting empty" the requirement names, and the failure mode most likely to be read as
    "the app lost my notes". Recovery is recorded when a ring is supplied, because a
    restore that happens before any window exists is otherwise invisible.

    A `SchemaTooNewError` is deliberately *not* recovered: the backups are the newer
    format too, so restoring one would be this build overwriting data it cannot read.
    """
    store = store if store is not None else NotesStore(root)
    remembered = active_set_id(settings)
    candidates = [remembered] if remembered else []
    candidates += [set_id for set_id in store.list_ids() if set_id != remembered]
    for set_id in candidates:
        try:
            return store.load(set_id)
        except SchemaTooNewError:
            continue
        except NotesStoreError:
            try:
                recovered = store.restore_latest_readable(set_id)
            except NotesStoreError:
                continue
            if ring is not None:
                ring.record(
                    "noteset_recovered_on_start",
                    noteset_id=set_id,
                    count=len(recovered.notes),
                    recovered=True,
                )
            return recovered
    return ContextSet(name="My notes")


class NotesEditor(QDialog):
    """Note CRUD (T3.7) and the note-set lifecycle (T3.8), in one surface.

    One dialog rather than two because the set selector *is* the editor's context: a user
    renaming a set is looking at its notes, and a separate window would mean two places
    that both believe they know which set is active.
    """

    def __init__(
        self,
        application: Application,
        *,
        settings: object,
        confirm: Confirmer | None = None,
        prompt: Prompter | None = None,
        restore_factory: RestoreFactory | None = None,
        import_factory: ImportFactory | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        self.application = application
        self.settings = settings
        self._confirm = confirm if confirm is not None else self._ask_to_delete
        self._prompt = prompt if prompt is not None else self._ask_for_name
        self._restore_factory = restore_factory if restore_factory is not None else _open_restore
        self._restore: RestoreDialog | None = None
        self._import_factory = import_factory if import_factory is not None else _open_import
        self._import: ImportDialog | None = None
        self.store = NotesStore(application.root)
        self._dirty = False
        self._loading = False
        self._timer: object | None = None

        layout = QVBoxLayout(self)

        # ---- T3.8: the set lifecycle ----
        sets = QHBoxLayout()
        self.set_box = QComboBox(self)
        self.set_box.currentIndexChanged.connect(self._on_set_selected)
        sets.addWidget(QLabel("Note set:", self))
        sets.addWidget(self.set_box, 1)
        self.new_set_button = QPushButton("New…", self)
        self.new_set_button.clicked.connect(self.create_set)
        self.rename_set_button = QPushButton("Rename…", self)
        self.rename_set_button.clicked.connect(self.rename_set)
        self.delete_set_button = QPushButton("Delete set…", self)
        self.delete_set_button.clicked.connect(self.delete_set)
        # T3.9. On the set row rather than the note row because a restore replaces the
        # whole set — FR29 rotates note *sets*, and a control sitting among the per-note
        # buttons would read as restoring the selected note.
        self.restore_button = QPushButton("Restore…", self)
        self.restore_button.clicked.connect(self.open_restore)
        # T3.7a. Next to the set controls because an import lands *in* a set and replaces
        # a whole kind within it — it is a set-level action, not a per-note one.
        self.import_button = QPushButton("Import…", self)
        self.import_button.clicked.connect(self.open_import)
        for button in (
            self.new_set_button,
            self.rename_set_button,
            self.delete_set_button,
            self.restore_button,
            self.import_button,
        ):
            sets.addWidget(button)
        layout.addLayout(sets)

        # ---- T3.7: the notes ----
        body = QHBoxLayout()
        self.note_list = QListWidget(self)
        self.note_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.note_list.currentRowChanged.connect(self._on_note_selected)
        body.addWidget(self.note_list, 1)

        form = QVBoxLayout()
        self.kind_box = QComboBox(self)
        for kind in SourceKind:
            self.kind_box.addItem(kind.value, kind)
        form.addWidget(QLabel("Kind (fixed after creation — FR67):", self))
        form.addWidget(self.kind_box)

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
        form.addWidget(QLabel("Bullets, one per line — verbatim from the note (FR42):", self))
        form.addWidget(self.bullets_edit)

        self.tags_edit = QLineEdit(self)
        self.tags_edit.textEdited.connect(self._on_edited)
        form.addWidget(QLabel("Tags, comma separated (FR4):", self))
        form.addWidget(self.tags_edit)

        self.track_box = QCheckBox("Track this as a talking point (FR12)", self)
        self.track_box.toggled.connect(self._on_edited)
        form.addWidget(self.track_box)

        self.advisory = QLabel("", self)
        self.advisory.setWordWrap(True)
        self.advisory.setTextFormat(Qt.TextFormat.PlainText)
        form.addWidget(self.advisory)
        body.addLayout(form, 2)
        layout.addLayout(body)

        self.status = QLabel("", self)
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        self.add_button = QPushButton("Add note", self)
        self.add_button.clicked.connect(self.add_note)
        self.delete_button = QPushButton("Delete note…", self)
        self.delete_button.clicked.connect(self.delete_note)
        self.up_button = QPushButton("Move up", self)
        self.up_button.clicked.connect(lambda: self.move_note(-1))
        self.down_button = QPushButton("Move down", self)
        self.down_button.clicked.connect(lambda: self.move_note(1))
        self.save_button = QPushButton("Save now", self)
        self.save_button.clicked.connect(self.flush)
        for button in (
            self.add_button,
            self.delete_button,
            self.up_button,
            self.down_button,
            self.save_button,
        ):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        # **The active set is persisted on open if it has no file yet.** The application
        # can be constructed with a set that has never been saved — the composition root
        # does exactly that on a first run — and until it exists on disk it cannot appear
        # in the selector, cannot be switched back to, and vanishes the moment the user
        # creates a second one. A write on open is a side effect worth having: the
        # alternative is an editor that quietly loses the set it is editing.
        if not self.store.path_for(self.context_set.id).exists():
            self.store.save(self.context_set)
        self.refresh_sets()

    # ---------- the active set (T3.8 — FR43) ----------

    @property
    def context_set(self) -> ContextSet:
        return self.application.context_set

    def refresh_sets(self) -> None:
        """Re-read what is on disk, keeping the active set selected.

        **An unreadable set is still listed** (T3.9). Omitting it hid the only route to
        its backups: selecting a set is what runs `activate`, and `activate` is what
        offers the restore — so a set that was already corrupt when this window opened had
        five recoverable generations on disk and no control anywhere that could reach
        them. Found by review on PR #28.
        """
        self._loading = True
        try:
            ids = self.store.list_ids()
            known = {self.context_set.id: self.context_set.name}
            for set_id in ids:
                if set_id not in known:
                    try:
                        known[set_id] = self.store.load(set_id).name
                    except Exception:  # noqa: BLE001 — one bad file must not hide the rest
                        self.application.ring.record("note_set_unreadable", noteset_id=set_id)
                        known[set_id] = UNREADABLE_LABEL.format(short=set_id[:8])
            self.set_box.clear()
            for set_id, name in known.items():
                self.set_box.addItem(name, set_id)
            index = self.set_box.findData(self.context_set.id)
            if index >= 0:
                self.set_box.setCurrentIndex(index)
        finally:
            self._loading = False
        self.refresh_notes()

    def _on_set_selected(self, _index: int) -> None:
        if self._loading:
            return
        set_id = self.set_box.currentData()
        if set_id is None or set_id == self.context_set.id:
            return
        self.activate(set_id)

    def activate(self, set_id: str) -> bool:
        """FR43. Flushes first — an unsaved edit belongs to the set being left.

        **A failed flush aborts the switch.** `flush` refuses a set whose bullets are not
        verbatim and leaves it dirty on purpose, so switching anyway would replace
        `application.context_set` and put those edits somewhere the user cannot reach —
        they would come back to the older version on disk with no sign of what happened.
        Found by review on PR #27.
        """
        self.flush()
        if self._dirty:
            self.refresh_sets()
            return False
        try:
            loaded = self.store.load(set_id)
        except SchemaTooNewError as error:
            # Never offer a restore past a newer format: the backups are that format too,
            # and rolling one in would be this build overwriting data it cannot read.
            self.status.setText(str(error))
            self.refresh_sets()
            return False
        except Exception as error:  # noqa: BLE001 — a UI boundary
            # **FR44's offer, at the one place in the product that meets a corrupt set.**
            # Reporting and stopping here is what "failing silently" looks like from the
            # user's side: the file is unreadable, five readable copies are on disk, and
            # nothing in the app connected the two.
            self.status.setText(f"That note set could not be opened: {error}")
            self.refresh_sets()
            self.open_restore(set_id)
            return False
        try:
            self.application.activate_context_set(loaded)
        except RuntimeError as error:
            # A session is running. Said plainly, and the selector goes back to the set
            # that is actually active rather than showing one the app is not using.
            self.status.setText(str(error))
            self.refresh_sets()
            return False
        self._remember_active(set_id)
        self.refresh_sets()
        self.status.setText(f"Active note set: {loaded.name}")
        return True

    def _remember_active(self, set_id: str) -> None:
        self.settings.setValue(ACTIVE_SET_KEY, set_id)  # type: ignore[attr-defined]

    # ---------- restore (T3.9 — FR29, FR44) ----------

    def open_restore(self, set_id: str | None = None) -> RestoreDialog:
        """FR29's "restorable from the UI". Modeless, and held on the instance.

        Held because a modeless dialog dropped on return is collected while it is on
        screen; modeless because the user comparing a backup against what they have now
        is the whole point, and a modal window hides the notes they are comparing it to.
        """
        target = set_id or self.context_set.id
        # One at a time. Replacing the attribute alone would leave the previous dialog on
        # screen with nothing holding it, listing generations that have since rotated —
        # and a stray window outliving the reference to it is how the overlay's timer
        # became a teardown crash.
        if self._restore is not None:
            self._restore.close()
        dialog = self._restore_factory(self.application, target, self.store, self)
        self._restore = dialog
        dialog.restored_set.connect(self._on_restored)
        dialog.show()
        return dialog

    # ---------- import (T3.7a — FR1a, FR2, FR66) ----------

    def open_import(self) -> ImportDialog | None:
        """T3.5's importer, given a way in at last.

        **Flushes first, and does not open if the flush refuses.** The import mutates the
        very `ContextSet` this editor is holding and then writes it, so an unsaved
        non-verbatim bullet would be carried into that write — past the check that refused
        it here. Same rule as `activate` and `_on_restored`: the refusal has to mean the
        same thing at every exit.
        """
        self.flush()
        if self._dirty:
            self.status.setText(
                f"{self.status.text()} Fix that before importing — the import writes this set too."
            )
            return None
        if self._import is not None:
            self._import.close()
        dialog = self._import_factory(self.application, self.store, self)
        self._import = dialog
        dialog.imported.connect(self._on_imported)
        dialog.show()
        return dialog

    def _on_imported(self, count: int) -> None:
        """The set this window is showing gained notes. The dialog has already saved and
        re-embedded, so this only has to catch the widgets up."""
        self.refresh_notes()
        self.status.setText(f"Imported {count} note(s).")

    def _on_restored(self, restored: ContextSet) -> None:
        """The disk changed under this window. Catch up — and **who owns the pending
        write decides what happens to it**.

        *The restored set is the one being edited:* the edits belong to the version the
        user just chose to replace, so they are dropped. `flush` on close would otherwise
        put them straight back over the restored file — the restore undone by the window
        that offered it.

        *The restored set is a different one:* the edits belong to the set being **left**,
        and this dialog is modeless, so they can have been typed while it was open. Same
        rule as `activate` — flush first, and if the flush refuses, do not switch. Clearing
        the flag here was the version of this that silently discarded them, with no
        warning either, because the dialog's unsaved-changes notice only covers the active
        set. Found by review on PR #28.
        """
        if restored.id == self.context_set.id:
            self._dirty = False
        else:
            self.flush()
            if self._dirty:
                self.status.setText(
                    f"{self.status.text()} The restored set was not opened, so your "
                    "unsaved changes are still here to fix."
                )
                self.refresh_sets()
                return
            # The set the user was trying to open was unreadable and has been repaired;
            # finish the switch they asked for. `activate_context_set` rather than
            # `activate`, because the set is already in hand and re-reading it from disk
            # would re-enter the failure path that opened this dialog.
            try:
                self.application.activate_context_set(restored)
            except RuntimeError as error:
                self.status.setText(str(error))
                self.refresh_sets()
                return
        self._remember_active(restored.id)
        self.refresh_sets()
        self.status.setText(f"Restored — {len(restored.notes)} note(s) in {restored.name}.")

    def create_set(self) -> ContextSet | None:
        """T3.8. A new set is saved immediately: an unsaved empty set is indistinguishable
        from one the user abandoned, and the selector would list something with no file."""
        name = self._prompt("New note set", "Untitled set")
        if not name:
            return None
        created = ContextSet(name=name)
        self.store.save(created)
        self.activate(created.id)
        return created

    def rename_set(self) -> bool:
        """Renames the set, **not** its id (FR41): the id is the filename and the
        embedding-cache key, so renaming through a new id would orphan every vector."""
        name = self._prompt("Rename note set", self.context_set.name)
        if not name:
            return False
        self.context_set.name = name
        self.mark_dirty()
        self.flush()
        self.refresh_sets()
        return True

    def delete_set(self) -> bool:
        """FR60's confirmation, and **never the last one**.

        Deleting the only set would leave the application with no active set and no way
        to make one from a surface that lists sets — the empty state this dialog cannot
        recover from. Refused with a reason rather than defended against later.
        """
        if self.set_box.count() <= 1:
            self.status.setText("This is your only note set. Create another before deleting it.")
            return False
        target = self.context_set
        if not self._confirm(
            f"Delete the note set “{target.name}” and its {len(target.notes)} note(s)? "
            "This cannot be undone."
        ):
            return False
        remaining = [
            self.set_box.itemData(row)
            for row in range(self.set_box.count())
            if self.set_box.itemData(row) != target.id
        ]
        # Switch first, delete second: activation can refuse (a running session), and a
        # deleted file with the app still pointing at it is unrecoverable.
        if not self.activate(remaining[0]):
            return False
        # **Backups go with it.** FR29 keeps five generations, so deleting only the live
        # file leaves up to five copies of the complete notes on disk under a control
        # whose confirmation says "cannot be undone" — true of the user's access, false
        # of the data. Found by review on PR #27.
        self.store.path_for(target.id).unlink(missing_ok=True)
        for backup in self.store.list_backups(target.id):
            backup.path.unlink(missing_ok=True)
        self.application.ring.record("note_set_deleted", noteset_id=target.id)
        self.refresh_sets()
        return True

    # ---------- notes (T3.7 — FR3, FR4) ----------

    def refresh_notes(self) -> None:
        self._loading = True
        try:
            row = self.note_list.currentRow()
            self.note_list.clear()
            for note in self.context_set.notes:
                item = QListWidgetItem(note.headline or "(untitled)")
                item.setData(Qt.ItemDataRole.UserRole, note.id)
                self.note_list.addItem(item)
            if self.note_list.count():
                self.note_list.setCurrentRow(min(max(row, 0), self.note_list.count() - 1))
        finally:
            self._loading = False
        self._load_selected()

    @property
    def selected_note(self) -> Note | None:
        item = self.note_list.currentItem()
        if item is None:
            return None
        return self.context_set.get(item.data(Qt.ItemDataRole.UserRole))

    def _on_note_selected(self, _row: int) -> None:
        if self._loading:
            return
        # The previous note's edits are already applied on every keystroke, so selecting
        # another one loses nothing — but the *file* is only written on flush.
        self._load_selected()

    def _load_selected(self) -> None:
        note = self.selected_note
        self._loading = True
        try:
            self.headline_edit.setText("" if note is None else note.headline)
            self.body_edit.setPlainText("" if note is None else note.body)
            self.bullets_edit.setPlainText("" if note is None else "\n".join(note.bullets))
            self.tags_edit.setText("" if note is None else ", ".join(note.tags))
            self.track_box.setChecked(False if note is None else note.track_progress)
            if note is not None:
                self.kind_box.setCurrentIndex(self.kind_box.findData(note.kind))
            # FR67: kind is immutable once the note exists.
            self.kind_box.setEnabled(note is None)
            trackable = note is not None and note.kind in TRACKABLE_KINDS
            self.track_box.setEnabled(trackable)
        finally:
            self._loading = False
        self._refresh_advisory()

    def _refresh_advisory(self) -> None:
        note = self.selected_note
        messages = []
        if note is not None and not note.is_overlay_optimised:
            messages.append(NOT_OPTIMISED_TEXT)
        if note is not None and note.kind not in TRACKABLE_KINDS:
            messages.append(TRACK_DISABLED_TEXT)
        self.advisory.setText(" ".join(messages))

    def _on_edited(self) -> None:
        """Apply the form to the note in memory and start the clock. **Never saves.**"""
        if self._loading:
            return
        note = self.selected_note
        if note is None:
            return
        note.headline = self.headline_edit.text()
        note.body = self.body_edit.toPlainText()
        note.bullets = [line for line in self.bullets_edit.toPlainText().splitlines() if line]
        note.tags = [tag.strip() for tag in self.tags_edit.text().split(",") if tag.strip()]
        if self.track_box.isEnabled():
            try:
                note.track_progress = self.track_box.isChecked()
            except ValueError as error:
                # FR70, enforced at the model. The checkbox is disabled for untrackable
                # kinds, so this is the belt to that braces — and it says why rather than
                # letting the exception cross the event loop.
                self.status.setText(str(error))
                self.track_box.setChecked(False)
        item = self.note_list.currentItem()
        if item is not None:
            item.setText(note.headline or "(untitled)")
        self._refresh_advisory()
        self.mark_dirty()

    def add_note(self) -> Note:
        """A new note takes the kind the box is showing — the one moment FR67 allows."""
        self.flush()
        kind = self.kind_box.currentData() or SourceKind.PREP
        note = Note(headline="New note", kind=kind)
        self.context_set.add(note)
        self.mark_dirty()
        self.refresh_notes()
        self.note_list.setCurrentRow(len(self.context_set.notes) - 1)
        return note

    def delete_note(self) -> bool:
        """FR60: confirmed. FR3: the rest keep their ids and their order."""
        note = self.selected_note
        if note is None:
            return False
        if not self._confirm(f"Delete the note “{note.headline}”? This cannot be undone."):
            return False
        self.context_set.delete(note.id)
        self.mark_dirty()
        self.refresh_notes()
        return True

    def move_note(self, offset: int) -> bool:
        """FR3's reorder. Ids are untouched — position is not identity (FR41)."""
        note = self.selected_note
        if note is None:
            return False
        ids = [n.id for n in self.context_set.notes]
        index = ids.index(note.id)
        target = index + offset
        if not 0 <= target < len(ids):
            return False
        ids[index], ids[target] = ids[target], ids[index]
        self.context_set.reorder(ids)
        self.mark_dirty()
        self.refresh_notes()
        self.note_list.setCurrentRow(target)
        return True

    # ---------- saving (T3.7) ----------

    @property
    def dirty(self) -> bool:
        return self._dirty

    def mark_dirty(self) -> None:
        """Start the debounce. **The only path to a write is `flush`.**"""
        self._dirty = True
        self.status.setText("Unsaved changes…")
        self._restart_timer()

    def _restart_timer(self) -> None:
        from PySide6.QtCore import QTimer

        timer = self._timer
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self.flush)
            self._timer = timer
        timer.setInterval(SAVE_DEBOUNCE_MS)  # type: ignore[attr-defined]
        timer.start()  # type: ignore[attr-defined]

    def flush(self) -> bool:
        """Write the set if anything changed. Returns whether a write happened.

        **Bullets are verified before the write, not after** (FR42). A bullet that is not
        a substring of its note is generated content one match away from the overlay, and
        `NotesStore.save` is the last place before it is durable. The editor reports it
        and keeps the set dirty rather than saving text the render boundary would then
        refuse — which would put the user in a state where their notes are stored and
        unusable.
        """
        if not self._dirty:
            return False
        try:
            for note in self.context_set.notes:
                note.verify_bullets_verbatim()
        except ValueError as error:
            self.status.setText(f"Not saved — {error}")
            return False
        self.store.save(self.context_set)
        self._dirty = False
        # Vectors, not just JSON: a note added or re-headlined here is matched on its
        # previous text until this runs (FR34).
        self.application.notes_changed()
        self.status.setText(f"Saved {len(self.context_set.notes)} note(s).")
        return True

    def closeEvent(self, event: Any) -> None:  # noqa: N802 — Qt override
        """Closing is an explicit action, so it saves (T3.7).

        The alternative is a dialog that silently discards up to five seconds of typing
        because the user was quicker than the timer.

        **A refused save keeps the window open.** `flush` tells the user they can fix a
        non-verbatim bullet, and closing anyway would make that false: the next editor
        opens clean against the mutated object, no timer is pending, and quitting loses
        the edits. Found by review on PR #27.
        """
        self.flush()
        if self._dirty:
            event.ignore()
            return
        super().closeEvent(event)

    # ---------- default Qt prompts ----------

    def _ask_to_delete(self, message: str) -> bool:
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self,
            "Delete?",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _ask_for_name(self, title: str, default: str) -> str | None:
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, title, "Name:", text=default)
        return name.strip() if ok and name.strip() else None
