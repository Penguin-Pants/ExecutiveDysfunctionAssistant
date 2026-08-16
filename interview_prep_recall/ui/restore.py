"""Backup restore (T3.9 — FR29, FR44).

FR29 keeps five generations of every note set and says they are **restorable from the
UI**. The rotation, the atomic write and the fall-through were built in T3.2 and T3.3 and
had passing tests; nothing in the product ever opened them. A backup that cannot be
reached is a file, not a recovery — the same missing-join shape as T5.10's match feed and
T3.7's editor, in the one requirement whose entire purpose is the moment something has
already gone wrong.

**Three rules carry this surface.**

*Preview never writes.* Reading a generation goes through `NotesStore.read_backup`, which
parses and returns; the restore path is a separate call. Looking at a backup must not be
able to cost the user their live file, and a preview routed through restore would rotate
the generations out from under the list the user is reading.

*A corrupt generation is not the end of the list* (T3.9's acceptance criterion). Each row
says whether it can be read and why not, and "Restore newest readable" falls through the
unreadable ones and **names the ones it skipped**. Silence there would look identical to
having fewer backups than FR29 promises.

*Restoring the active set re-points everything that reads it.* The index, the prefilter
and the tracker each hold their own reference (D-61), so a restore that only rewrote the
file would leave matching drawing from the version the user just replaced — invisible,
and indistinguishable from bad retrieval. It goes through
`Application.activate_context_set`, and it asks `can_change_context_set` **before** the
write rather than discovering the refusal after it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from interview_prep_recall.notes.model import ContextSet
from interview_prep_recall.notes.store import BackupInfo, NotesStore, NotesStoreError

if TYPE_CHECKING:
    from interview_prep_recall.app import Application

TITLE = "Restore a previous version"

NO_BACKUPS_TEXT = (
    "No previous versions yet. A backup is kept each time this note set is saved, up to five."
)
"""A first-run set has never been rotated. Said plainly, because an empty list under a
requirement that promises five generations otherwise reads as data loss."""

SESSION_LOCKED_TEXT = (
    "A session is running. Stop it before restoring — matching, the tracker and the "
    "report all read the set that was active at the start."
)

UNSAVED_WARNING = "Your unsaved changes to this note set will be discarded. "
"""Restoring *is* discarding, and the confirmation says so. See `RestoreDialog.restore`
for why the alternative — flushing first — is worse."""

Confirmer = Callable[[str], bool]
"""FR60. Injected so the confirmation is testable without driving a modal."""


def describe(info: BackupInfo) -> str:
    """One row of the list. The generation orders them; the rest is what the user
    recognises — a set called "Backend interview" with 14 notes from this morning."""
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(info.saved_at))
    if not info.readable:
        return f"Version {info.generation} — {when} — unreadable ({info.error or 'unknown'})"
    notes = "1 note" if info.note_count == 1 else f"{info.note_count} notes"
    return f"Version {info.generation} — {when} — {info.name} — {notes}"


def preview_text(note_set: ContextSet) -> str:
    """What a generation contains, at the level a person can check in a few seconds.

    Headlines only. The body is where the length is, and the question being answered here
    is "is this the version I want back", which the list of questions answers and a wall
    of prose does not.
    """
    lines = [f"{note_set.name} — {len(note_set.notes)} note(s)", ""]
    lines += [f"• {note.headline or '(untitled)'}" for note in note_set.notes]
    if not note_set.notes:
        lines.append("(no notes in this version)")
    return "\n".join(lines)


class RestoreDialog(QDialog):
    """Browse, preview and restore the five generations of one note set (T3.9)."""

    restored_set = Signal(object)
    """Emitted with the `ContextSet` that was made live. The editor that opened this
    dialog is showing the version that was just replaced, and waiting for the window to
    close would leave it editing notes that are no longer on disk."""

    def __init__(
        self,
        application: Application,
        noteset_id: str,
        *,
        store: NotesStore | None = None,
        confirm: Confirmer | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        self.application = application
        self.noteset_id = noteset_id
        self.store = store if store is not None else NotesStore(application.root)
        self._confirm = confirm if confirm is not None else self._ask
        self.restored: ContextSet | None = None
        """The version that was made live, for a caller that needs to refresh itself.
        None until a restore succeeds."""
        self.backups: list[BackupInfo] = []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Each save keeps a copy. Pick the version you want back:", self))

        body = QHBoxLayout()
        self.generation_list = QListWidget(self)
        self.generation_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.generation_list.currentRowChanged.connect(self._on_selected)
        body.addWidget(self.generation_list, 1)

        self.preview = QPlainTextEdit(self)
        self.preview.setReadOnly(True)
        body.addWidget(self.preview, 1)
        layout.addLayout(body)

        self.status = QLabel("", self)
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        self.restore_button = QPushButton("Restore this version…", self)
        self.restore_button.clicked.connect(self.restore_selected)
        self.latest_button = QPushButton("Restore newest readable…", self)
        self.latest_button.clicked.connect(self.restore_latest_readable)
        self.close_button = QPushButton("Close", self)
        self.close_button.clicked.connect(self.reject)
        for button in (self.restore_button, self.latest_button, self.close_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        self.refresh()

    # ---------- browsing ----------

    def refresh(self) -> None:
        """Re-read what is on disk. Called after a restore because rotation moves every
        generation down one — the list is stale the instant the restore returns."""
        self.backups = self.store.list_backups(self.noteset_id)
        self.generation_list.clear()
        for info in self.backups:
            item = QListWidgetItem(describe(info))
            item.setData(Qt.ItemDataRole.UserRole, info.generation)
            self.generation_list.addItem(item)
        if self.backups:
            self.generation_list.setCurrentRow(0)
        else:
            self.status.setText(NO_BACKUPS_TEXT)
        self._refresh_buttons()
        self._on_selected(self.generation_list.currentRow())

    @property
    def selected(self) -> BackupInfo | None:
        row = self.generation_list.currentRow()
        if not 0 <= row < len(self.backups):
            return None
        return self.backups[row]

    def _on_selected(self, _row: int) -> None:
        info = self.selected
        if info is None:
            self.preview.setPlainText("")
            self._refresh_buttons()
            return
        if not info.readable:
            # The row already says it is unreadable; the pane says what that means for
            # the user rather than leaving a blank box that reads like an empty backup.
            self.preview.setPlainText(
                f"This version cannot be read:\n\n{info.error}\n\n"
                "The other versions are unaffected — try an older one, or use "
                "“Restore newest readable”."
            )
            self._refresh_buttons()
            return
        try:
            note_set = self.store.read_backup(self.noteset_id, info.generation)
        except NotesStoreError as error:  # pragma: no cover — list_backups just parsed it
            # Only reachable if the file changed between the listing and this read.
            self.preview.setPlainText(f"This version cannot be read: {error}")
        else:
            self.preview.setPlainText(preview_text(note_set))
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        info = self.selected
        self.restore_button.setEnabled(info is not None and info.readable)
        self.latest_button.setEnabled(any(b.readable for b in self.backups))

    # ---------- restoring ----------

    def restore_selected(self) -> bool:
        info = self.selected
        if info is None or not info.readable:
            return False
        return self.restore(info.generation)

    def restore_latest_readable(self) -> bool:
        """T3.9's fall-through, and it **says which ones it skipped**.

        A corrupt backup is not a dead end — keeping five is the whole point — but a
        recovery that quietly lands on version 3 leaves the user believing versions 1 and
        2 are still there to go back to.
        """
        skipped = [info.generation for info in self.backups if not info.readable]
        target = next((info for info in self.backups if info.readable), None)
        if target is None:
            self.status.setText("None of the saved versions can be read. Nothing has been changed.")
            return False
        if not self.restore(target.generation, skipped=skipped):
            return False
        if skipped:
            listed = ", ".join(str(generation) for generation in skipped)
            self.status.setText(
                f"{self.status.text()} Version(s) {listed} could not be read and were skipped."
            )
        return True

    def restore(self, generation: int, *, skipped: list[int] | None = None) -> bool:
        """Make one generation live (FR29), confirmed (FR60).

        **The session check happens before the write.** Restoring the active set has to
        re-point the index, the prefilter and the tracker, and `activate_context_set`
        refuses mid-session — asking afterwards would leave the file replaced and the
        application still matching against the version the user had just discarded.

        **Unsaved edits are discarded, not flushed.** Flushing first would rotate the
        generations, so the version the user selected would not be the version they get.
        The confirmation says the edits will be lost; the editor clears its dirty flag so
        closing cannot write the pre-restore set back over the restored one.
        """
        is_active = self.noteset_id == self.application.context_set.id
        if is_active and not self.application.can_change_context_set:
            self.status.setText(SESSION_LOCKED_TEXT)
            return False
        skipped = skipped or []
        preamble = UNSAVED_WARNING if is_active and self._caller_has_unsaved_edits() else ""
        if not self._confirm(
            f"{preamble}Replace the current notes with version {generation}? "
            "The current version is kept as a backup, so this can be undone."
        ):
            return False
        try:
            restored = self.store.restore_generation(self.noteset_id, generation)
        except NotesStoreError as error:  # a UI boundary
            self.status.setText(f"That version could not be restored: {error}")
            self.refresh()
            return False
        if is_active:
            self.application.activate_context_set(restored)
        self.application.ring.record(
            "noteset_restored",
            noteset_id=self.noteset_id,
            generation=generation,
            count=len(restored.notes),
            recovered=bool(skipped),
        )
        self.restored = restored
        self.restored_set.emit(restored)
        self.status.setText(
            f"Restored version {generation} — {len(restored.notes)} note(s). "
            "The version it replaced is now the newest backup."
        )
        self.refresh()
        return True

    def _caller_has_unsaved_edits(self) -> bool:
        """The editor that opened this dialog, if it is the parent and it is dirty.

        Deliberately a question about the parent rather than a constructor argument: the
        dialog is usable on its own, and a `dirty` flag it was handed could be stale by
        the time the user clicks restore.
        """
        parent = self.parent()
        return bool(getattr(parent, "dirty", False))

    # ---------- default Qt prompt ----------

    def _ask(self, message: str) -> bool:
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self,
            "Restore?",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes
