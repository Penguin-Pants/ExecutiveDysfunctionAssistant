"""In-app diagnostics viewer with export (T5.8 — FR36).

**Not in design §1's module layout**, for the same reason `main_window.py` is not: §1
lists `indicators.py` for the always-visible signals and `ring.py` for the buffer, and
FR36's "viewable in-app" needs a third thing that is neither. Recorded as a deviation
rather than squeezed into `indicators.py`, which is the overlay's persistent strip and
must stay glanceable — a scrolling event table on the panel the user reads mid-sentence
would defeat the one requirement the overlay has.

**The ring is read, never written to disk by this view.** FR36 is explicit that the buffer
is never auto-written; `export()` runs only from the user's button, to a path the user
chose. `DiagnosticRing.export()` already returns a structure rather than writing one, and
that split is kept here: this module is the only place in the product that turns
diagnostics into a file, and it does so under a click.

**Nothing here re-validates the content.** The no-content guarantee is the ring's
allowlist, enforced at `record()` — at the call site, where a leak is a bug someone can
fix. A second filter at the viewer would let unsafe events into the buffer and hide them
only from this one reader, which is worse than not having it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from interview_prep_recall.diagnostics.ring import DiagnosticEvent, DiagnosticRing

TITLE = "Diagnostics"
COLUMNS = ("time (s)", "event", "fields")
EXPORT_FILENAME = "diagnostics.json"
EMPTY_TEXT = "No diagnostic events recorded yet."

PathChooser = Callable[[], Path | None]
"""Returns where the user wants the export written, or None if they cancelled."""


def format_fields(event: DiagnosticEvent) -> str:
    """`k=v` pairs, sorted.

    Sorted rather than insertion-ordered: the reader is scanning a column for one field
    across many rows, and a stable position is worth more than the order the call site
    happened to pass them in.
    """
    return " ".join(f"{key}={value}" for key, value in sorted(event.fields.items()))


class DiagnosticsView(QDialog):
    """FR36's in-app view of the ring buffer, with a user-initiated export.

    `refresh()` is explicit rather than timed. The ring is written from every thread in
    design §8, and a viewer polling it during a session would add contention to the
    audio and matching paths for a window nobody is looking at — the user opens this
    *because* something went wrong, and pressing Refresh is a truthful gesture in a way a
    silently-updating table is not.
    """

    def __init__(
        self,
        ring: DiagnosticRing,
        *,
        choose_path: PathChooser | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        self.ring = ring
        self._choose_path = choose_path if choose_path is not None else self._ask_for_path

        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, len(COLUMNS), self)
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(
            len(COLUMNS) - 1, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.table)

        self.status = QLabel("", self)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh", self)
        self.refresh_button.clicked.connect(self.refresh)
        self.export_button = QPushButton("Export…", self)
        self.export_button.clicked.connect(self.export)
        buttons.addStretch(1)
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.export_button)
        layout.addLayout(buttons)

        self.refresh()

    # ---------- viewing ----------

    def refresh(self) -> None:
        """Re-read the ring. Oldest first, which is the order the events happened in."""
        events = self.ring.snapshot()
        self.table.setRowCount(len(events))
        for row, event in enumerate(events):
            self._set_row(row, event)
        self.status.setText(EMPTY_TEXT if not events else self._summary(len(events)))

    def _set_row(self, row: int, event: DiagnosticEvent) -> None:
        for column, text in enumerate(
            (f"{event.t_monotonic:.3f}", event.event, format_fields(event))
        ):
            self.table.setItem(row, column, QTableWidgetItem(text))

    def _summary(self, shown: int) -> str:
        return (
            f"{shown} of {self.ring.capacity} events. Structural events only — no transcript text."
        )

    @property
    def rows(self) -> tuple[tuple[str, ...], ...]:
        """What the table is showing, for tests and for the FR36 content-leak check."""
        return tuple(
            tuple(self._cell(row, column) for column in range(self.table.columnCount()))
            for row in range(self.table.rowCount())
        )

    def _cell(self, row: int, column: int) -> str:
        item = self.table.item(row, column)
        return item.text() if item is not None else ""

    # ---------- export ----------

    def export(self) -> Path | None:
        """FR36's explicit export. Returns where it went, or None if nothing was written.

        A failed write is reported in the status line **and** recorded structurally. A
        silent failure here is the worst kind: the user is exporting precisely because
        they are about to send this to someone, and a file that was never written looks
        exactly like one that was until they go looking for it.
        """
        destination = self._choose_path()
        if destination is None:
            return None
        payload = self.ring.export()
        try:
            destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError as error:
            self.ring.record("diagnostics_export", ok=False, code=type(error).__name__)
            self.status.setText(f"Could not write the export: {error}")
            return None
        self.ring.record("diagnostics_export", ok=True, count=len(payload["events"]))
        self.status.setText(f"Exported {len(payload['events'])} events to {destination}")
        return destination

    def _ask_for_path(self) -> Path | None:
        from PySide6.QtWidgets import QFileDialog

        chosen, _filter = QFileDialog.getSaveFileName(
            self, "Export diagnostics", EXPORT_FILENAME, "JSON (*.json)"
        )
        return Path(chosen) if chosen else None
