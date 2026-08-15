"""The application window (T9.6 — FR38, FR52, FR37).

**Not in design §1's module layout**, and that is a deliberate deviation rather than an
oversight. §1 lists `overlay.py`, `editor.py`, `settings.py` and `indicators.py` because
the product's session UI *is* the overlay — there was never meant to be a general window.
But the overlay is M5 and blocked on `SetWindowDisplayAffinity`, and meanwhile three
tasks (T9.1a, T9.2b, T9.4) are all blocked on there being *somewhere* for the app to open
its dialogs from. This is that somewhere. When M5 lands, the overlay becomes the session
surface and this stays what it is now: the readiness-and-settings shell around it.

**M5 landed, and this is now where the overlay's chrome controls live (T5.4).** FR55 asks
for a reset control "for recovery when persisted coordinates land off-screen", so the
control cannot live on the panel it is rescuing — a button on an invisible window is not
a recovery route. FR27's lock is here for the same reason: it is the pair to the reset,
and a user who has locked the panel somewhere unreachable needs both from one place they
can always get to. Found by review on PR #21, where both existed only as methods with no
production caller.

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
    QCheckBox,
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
from interview_prep_recall.ui.overlay import (
    OverlayGeometry,
    OverlayPanel,
    ScreenBounds,
    load_geometry,
    save_geometry,
)
from interview_prep_recall.ui.settings import SettingsDialog

WINDOW_TITLE = "Interview Prep Recall"

READY_TEXT = "Ready. Start your interview when you are."
BLOCKED_HEADING = "Not ready to start:"
RESTART_NOTICE = "Some changes take effect the next time you start the app:"

RESET_OVERLAY_TEXT = "Reset overlay position"
LOCK_OVERLAY_TEXT = "Lock overlay position"
PREVIEW_OVERLAY_TEXT = "Show overlay"

DialogFactory = Callable[[Application], SettingsDialog]
DiagnosticsFactory = Callable[[Application, QWidget], DiagnosticsView]
"""Takes the parent, because a modeless window this one opens must be owned by it."""


def _default_diagnostics(application: Application, parent: QWidget) -> DiagnosticsView:
    return DiagnosticsView(application.ring, parent=parent)


def _default_dialog(application: Application) -> SettingsDialog:
    return SettingsDialog(
        application.config,
        # `asdict`, not `vars`: it states that only dataclass *fields* are switches, and
        # will not silently start offering a non-field attribute added later.
        switches=asdict(application.session.switches),
        on_switch=application.session.set_switch,
    )


class MainWindow(QMainWindow):
    """Readiness status, the overlay's chrome controls, and a route into Settings.

    **`overlay_settings` is required and injected**, rather than defaulted to a
    `QSettings` built here. A widget constructor that mints its own registry handle
    reaches the user's real settings from every test that ever builds one — and the T0.4
    allowlist guard cannot see it, because `QSettings` writes through Qt's C++ layer and
    not through Python's `open`. Injection is also what every other collaborator in this
    codebase gets, for the reason `app.py` states: the defects live in the connections,
    and a dependency with a working default never has its connection tested.
    """

    def __init__(
        self,
        application: Application,
        report: PreflightReport | None = None,
        *,
        dialog_factory: DialogFactory = _default_dialog,
        diagnostics_factory: DiagnosticsFactory = _default_diagnostics,
        overlay_settings: object,
        refresh_preflight: Callable[[], PreflightReport] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(WINDOW_TITLE)
        self.application = application
        self._dialog_factory = dialog_factory
        self._diagnostics_factory = diagnostics_factory
        self._refresh_preflight = refresh_preflight
        self._overlay_settings = overlay_settings

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

        # The overlay is built here, from the persisted geometry, so FR26's stored layout
        # is what the chrome controls below actually operate on.
        #
        # **Parented to this window, and it still is its own top-level window.** The
        # `Qt.Tool` flag the panel sets keeps it floating and frameless rather than
        # embedding it here; the parent only decides who owns its lifetime. Without one
        # the panel's sole reference is this Python attribute, and a parentless top-level
        # widget torn down through that reference segfaults the interpreter — which is how
        # this was found, on the twenty-fourth window built in one process.
        # The callback closes over the **store**, not over `self`. A bound method here
        # makes a window→panel→method→window cycle, which only the cyclic collector can
        # break — and Qt objects freed on the GC's schedule are destroyed in an order
        # nobody chose. That segfaulted the interpreter once enough windows had been
        # built and collected; it is also simply more coupling than the panel needs,
        # since all it has to reach is the settings object.
        store = self._overlay_settings
        self.overlay = OverlayPanel(
            load_geometry(store, ScreenBounds.of(self)),
            on_geometry_changed=lambda geometry: save_geometry(store, geometry),
            parent=self,
        )

        self.preview_overlay_button = QPushButton(PREVIEW_OVERLAY_TEXT)
        self.preview_overlay_button.setCheckable(True)
        self.preview_overlay_button.toggled.connect(self.set_overlay_visible)
        layout.addWidget(self.preview_overlay_button)

        self.lock_overlay_box = QCheckBox(LOCK_OVERLAY_TEXT)
        self.lock_overlay_box.setChecked(self.overlay.locked)
        self.lock_overlay_box.toggled.connect(self.set_overlay_locked)
        layout.addWidget(self.lock_overlay_box)

        self.reset_overlay_button = QPushButton(RESET_OVERLAY_TEXT)
        self.reset_overlay_button.clicked.connect(self.reset_overlay)
        layout.addWidget(self.reset_overlay_button)

        self.setCentralWidget(central)

    # ---------- overlay chrome (T5.4 — FR26, FR27, FR55) ----------

    def set_overlay_visible(self, visible: bool) -> None:
        """Show or hide the panel so the chrome controls have something to act on.

        Not a session: nothing is captured, matched or rendered into it. It exists because
        FR22's drag, FR23's resize and FR55's reset are all things the user does *to a
        panel they can see*, and none of them needs an interview to be running.
        """
        self.overlay.setVisible(visible)

    def set_overlay_locked(self, locked: bool) -> None:
        """FR27's toggle, on a surface that stays reachable when the panel does not."""
        self.overlay.set_locked(locked)

    def reset_overlay(self) -> OverlayGeometry:
        """FR55. Returns the recovered geometry so a caller can see where it landed.

        The control lives here rather than on the panel because the case it exists for is
        a panel the user cannot reach. It also clears the lock, so the checkbox is brought
        back in step — leaving it ticked would show a lock the geometry no longer has.
        """
        recovered = self.overlay.reset_geometry()
        self.lock_overlay_box.setChecked(recovered.locked)
        return recovered

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

        Held on the instance *and* parented to this window. The Python reference keeps a
        modeless dialog from being collected the moment `open_diagnostics` returns — the
        same defect the overlay's transition animation had. The Qt parent decides who
        destroys it, and without one the dialog is a parentless top-level widget torn
        down through a Python refcount, which segfaults the interpreter once enough of
        them have come and gone. Found by review on PR #21, in the same pass that gave
        the overlay a parent for the same reason.

        Modeless rather than modal — the ring is worth watching *while* something is
        going wrong, and a modal dialog would block the window it is diagnosing.
        """
        view = self._diagnostics_factory(self.application, self)
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
