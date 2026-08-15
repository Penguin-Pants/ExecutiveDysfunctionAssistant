"""The application window (T9.6 — FR38, FR52, FR37).

**Not in design §1's module layout**, and that is a deliberate deviation rather than an
oversight. §1 lists `overlay.py`, `editor.py`, `settings.py` and `indicators.py` because
the product's session UI *is* the overlay — there was never meant to be a general window.
But the overlay is M5 and blocked on `SetWindowDisplayAffinity`, and meanwhile three
tasks (T9.1a, T9.2b, T9.4) are all blocked on there being *somewhere* for the app to open
its dialogs from. This is that somewhere. When M5 lands, the overlay becomes the session
surface and this stays what it is now: the readiness-and-settings shell around it.

**What it deliberately does not do.** It cannot start a session, because capture is M1
and the overlay is M5. Rather than fake a Start button that fails, it shows FR38's
preflight result — which on a machine without audio devices correctly reports blocking
failures, because `Preflight` treats a check with no probe as unsatisfied rather than
passed. The honest screen for "you cannot start yet" is the list of reasons.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from interview_prep_recall.app import Application
from interview_prep_recall.session.preflight import PreflightReport
from interview_prep_recall.settings import AppliedSettings
from interview_prep_recall.ui.diagnostics_view import DiagnosticsView
from interview_prep_recall.ui.settings import SettingsDialog

WINDOW_TITLE = "Interview Prep Recall"

READY_TEXT = "Ready. Start your interview when you are."
BLOCKED_HEADING = "Not ready to start:"
RESTART_NOTICE = "Some changes take effect the next time you start the app:"

DialogFactory = Callable[[Application], SettingsDialog]
DiagnosticsFactory = Callable[[Application], DiagnosticsView]


def _default_diagnostics(application: Application) -> DiagnosticsView:
    return DiagnosticsView(application.ring)


def _default_dialog(application: Application) -> SettingsDialog:
    return SettingsDialog(
        application.config,
        # `asdict`, not `vars`: it states that only dataclass *fields* are switches, and
        # will not silently start offering a non-field attribute added later.
        switches=asdict(application.session.switches),
        on_switch=application.session.set_switch,
    )


class MainWindow(QMainWindow):
    """Readiness status plus a route into Settings."""

    def __init__(
        self,
        application: Application,
        report: PreflightReport | None = None,
        *,
        dialog_factory: DialogFactory = _default_dialog,
        diagnostics_factory: DiagnosticsFactory = _default_diagnostics,
        refresh_preflight: Callable[[], PreflightReport] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(WINDOW_TITLE)
        self.application = application
        self._dialog_factory = dialog_factory
        self._diagnostics_factory = diagnostics_factory
        self._refresh_preflight = refresh_preflight

        central = QWidget()
        layout = QVBoxLayout(central)

        self.status = QLabel(_status_text(report))
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)

        self.settings_button = QPushButton("Settings…")
        self.settings_button.clicked.connect(self.open_settings)
        layout.addWidget(self.settings_button)

        self.diagnostics_button = QPushButton("Diagnostics…")
        self.diagnostics_button.clicked.connect(self.open_diagnostics)
        layout.addWidget(self.diagnostics_button)

        self.setCentralWidget(central)

    def open_settings(self) -> AppliedSettings | None:
        """Show the settings dialog and apply the result (T9.2b).

        Returns what happened so a caller — and a test — can see it. `None` means the
        user cancelled, which must apply and persist nothing: the dialog edits a copy,
        so cancelling is genuinely a no-op rather than something to undo.
        """
        dialog = self._dialog_factory(self.application)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        result = self.application.apply_settings(dialog.config())
        # Re-run FR38's checks: which ones apply depends on the configured backend, so a
        # report taken at process start goes stale the moment the user switches to a
        # cloud backend. Leaving it would show "ready" without the API key or the service
        # having ever been validated.
        self.refresh_status()
        if result.needs_restart:
            self.notify_restart(result)
        return result

    def open_diagnostics(self) -> DiagnosticsView:
        """FR36's "viewable in-app". Returns the view so a caller can drive it.

        Held on the instance: a `QDialog` that goes out of scope is collected and the
        window vanishes, which is the same defect the overlay's transition animation had.
        Modeless rather than modal — the ring is worth watching *while* something is
        going wrong, and a modal dialog would block the window it is diagnosing.
        """
        view = self._diagnostics_factory(self.application)
        self._diagnostics = view
        view.show()
        return view

    def refresh_status(self) -> None:
        if self._refresh_preflight is not None:
            self.status.setText(_status_text(self._refresh_preflight()))

    def notify_restart(self, result: AppliedSettings) -> None:
        """Tell the user which settings are waiting on a restart.

        Separated so `open_settings` is testable without a modal message box, and because
        FR52's promise is that a change *takes effect* — a setting silently waiting for a
        restart is the difference between the app being wrong and the user being informed.
        """
        QMessageBox.information(
            self,
            WINDOW_TITLE,
            RESTART_NOTICE + "\n\n" + "\n".join(sorted(result.needs_restart)),
        )


def _status_text(report: PreflightReport | None) -> str:
    """FR38's classification, rendered.

    Blockers are listed with their reasons rather than summarised as "not ready", because
    the user's next action is to fix one of them and a count tells them nothing about
    which.
    """
    if report is None:
        return READY_TEXT
    if not report.blocked:
        warnings = report.warnings
        if not warnings:
            return READY_TEXT
        return (
            READY_TEXT
            + "\n\nWarnings:\n"
            + "\n".join(
                f"• {r.check.label}" + (f" — {r.detail}" if r.detail else "") for r in warnings
            )
        )
    return (
        BLOCKED_HEADING
        + "\n"
        + "\n".join(
            f"• {r.check.label}" + (f" — {r.detail}" if r.detail else "") for r in report.blockers
        )
    )
