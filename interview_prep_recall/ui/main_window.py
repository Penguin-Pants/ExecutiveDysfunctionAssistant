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

from PySide6.QtCore import Qt, Signal
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
from interview_prep_recall.matching.pipeline import MatchResult
from interview_prep_recall.session.manager import SessionState
from interview_prep_recall.session.preflight import PreflightReport
from interview_prep_recall.settings import AppliedSettings
from interview_prep_recall.ui.diagnostics_view import DiagnosticsView
from interview_prep_recall.ui.editor import NotesEditor
from interview_prep_recall.ui.overlay import (
    OverlayGeometry,
    OverlayPanel,
    ScreenBounds,
    load_geometry,
    save_geometry,
)
from interview_prep_recall.ui.report_view import ReportView
from interview_prep_recall.ui.settings import SettingsDialog

WINDOW_TITLE = "Interview Prep Recall"

READY_TEXT = "Ready. Start your interview when you are."
BLOCKED_HEADING = "Not ready to start:"
RESTART_NOTICE = "Some changes take effect the next time you start the app:"

RESET_OVERLAY_TEXT = "Reset overlay position"
LOCK_OVERLAY_TEXT = "Lock overlay position"
PREVIEW_OVERLAY_TEXT = "Show overlay"
REPORTS_TEXT = "Interview reports…"
NOTES_TEXT = "Notes…"

PANIC_TEXT = "Panic — stop listening"
"""FR60: **single action, no confirmation.** The control is no longer destructive
(FR64a/D-U11), so there is nothing to confirm — and a confirmation on the control a user
reaches for when someone walks into the room is a control that does not work."""

RESUME_TEXT = "Resume listening"

PANIC_SIGNPOST = (
    "Panic pauses capture and nothing else — your transcript, notes and this session all "
    "survive, and Resume continues where you left off. Nothing here deletes anything. "
    "To delete stored interviews, use “Delete all sessions” in Interview reports."
)
"""FR87, at the surface it names.

The requirement exists because panic used to destroy things and no longer does (D-U11),
which leaves a user who presses it for privacy reasons with a false impression unless the
surface says otherwise — and then leaves them with no route to the thing they actually
wanted. Both halves are here: what panic does not do, and where the deliberate route is.
"""

PANIC_UNAVAILABLE = "Nothing is being captured right now."

DialogFactory = Callable[[Application], SettingsDialog]
DiagnosticsFactory = Callable[[Application, QWidget], DiagnosticsView]
"""Takes the parent, because a modeless window this one opens must be owned by it."""

ReportsFactory = Callable[[Application, QWidget], ReportView]
NotesFactory = Callable[[Application, object, QWidget], NotesEditor]


def _no_context_set_change(_context_set: object) -> None:
    """What `on_context_set_change` reverts to when the window goes."""


def _no_result(_result: MatchResult) -> None:
    """What `on_result` reverts to when the window goes. Not a silent default anywhere
    else: `Application`'s own is the one that hid T5.10 for six milestones."""


def _default_diagnostics(application: Application, parent: QWidget) -> DiagnosticsView:
    return DiagnosticsView(application.ring, parent=parent)


def _default_reports(application: Application, parent: QWidget) -> ReportView:
    return ReportView(application, parent=parent)


def _default_notes(application: Application, settings: object, parent: QWidget) -> NotesEditor:
    return NotesEditor(application, settings=settings, parent=parent)


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

    session_state_changed = Signal()
    """A session transition reached the window. Emitted, never called directly: `_to`
    runs on whichever thread drove the transition, and this slot touches widgets."""

    def __init__(
        self,
        application: Application,
        report: PreflightReport | None = None,
        *,
        dialog_factory: DialogFactory = _default_dialog,
        diagnostics_factory: DiagnosticsFactory = _default_diagnostics,
        reports_factory: ReportsFactory = _default_reports,
        notes_factory: NotesFactory = _default_notes,
        overlay_settings: object,
        refresh_preflight: Callable[[], PreflightReport] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(WINDOW_TITLE)
        self.application = application
        self._dialog_factory = dialog_factory
        self._diagnostics_factory = diagnostics_factory
        self._reports_factory = reports_factory
        self._notes_factory = notes_factory
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

        self.notes_button = QPushButton(NOTES_TEXT)
        self.notes_button.clicked.connect(self.open_notes)
        layout.addWidget(self.notes_button)

        self.reports_button = QPushButton(REPORTS_TEXT)
        self.reports_button.clicked.connect(self.open_reports)
        layout.addWidget(self.reports_button)

        # ---- the panic surface (T6.3b — FR60, FR64a, FR87) ----
        self.panic_button = QPushButton(PANIC_TEXT)
        self.panic_button.clicked.connect(self.panic)
        layout.addWidget(self.panic_button)

        self.resume_button = QPushButton(RESUME_TEXT)
        self.resume_button.clicked.connect(self.resume)
        layout.addWidget(self.resume_button)

        self.panic_signpost = QLabel(PANIC_SIGNPOST)
        self.panic_signpost.setWordWrap(True)
        self.panic_signpost.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.panic_signpost)

        self.panic_status = QLabel("")
        self.panic_status.setWordWrap(True)
        self.panic_status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.panic_status)

        # FR60's control has to be live *while a session runs*, and a session starts
        # long after this window is built. Without this subscription the initial IDLE
        # refresh disabled the panic button for the rest of the process — the emergency
        # control dead in exactly the case it exists for. The tests missed it by starting
        # the session first. Found by review on PR #25.
        #
        # Through a signal: `_to` runs on whichever thread drove the transition.
        emit_state_change = self.session_state_changed.emit
        application.session.on_state_change = lambda _old, _new: emit_state_change()
        self.destroyed.connect(lambda: setattr(application.session, "on_state_change", None))
        self.refresh_panic()

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

        # FR12's checklist gets its production feed here (T7.4). **The signal's `emit`,
        # not the setter**: `Application.consume` runs on whichever thread the STT backend
        # chose, and a bound widget method stored here would mutate `QWidget` state from
        # that thread. `OverlayPanel.tracker_updated` is the hop. Found by review on
        # PR #22.
        #
        # It is the *panel's* bound emit, not this window's, so the callback the
        # application holds reaches the widget without a window→application→window cycle
        # for the collector to decide the teardown order of — the hazard the comment above
        # records.
        application.on_tracker_update = self.overlay.tracker_updated.emit
        # FR20/FR35, and the wire that did not exist: the monitor recorded every state
        # the indicators were built to render and nothing carried one to the other, so
        # the egress lamp was correct in memory and dark on screen. The panel's own
        # `emit`, for the reason the line above uses one — a bound widget method here
        # would be called from the watchdog and report threads. Found by review on PR #25.
        # T5.10, the wire the product exists for: a match reaches the panel. The
        # pipeline's worker thread calls this, so it is the panel's `emit` — the
        # `tracker_updated` contract, for the third collaborator in a row.
        self.overlay.context_set = application.context_set
        # T5.10a, closed: the panel resolves matches against a set it was handed once, so
        # switching sets (T3.8) has to re-hand it. Assigning the attribute rather than
        # emitting because `activate_context_set` refuses while a session runs, which
        # means this only ever fires on the GUI thread.
        application.on_context_set_change = self._on_context_set_change
        self.destroyed.connect(
            lambda: setattr(application, "on_context_set_change", _no_context_set_change)
        )
        application.on_result = self.overlay.match_received.emit
        self.destroyed.connect(lambda: setattr(application, "on_result", _no_result))
        # FR54's auto-clear had the same problem one layer down: `tick` was pull-based
        # and `start_clock` had no production caller either, so an unpinned snippet
        # would have stayed on screen for the whole interview once one finally arrived.
        #
        # **The panel starts its own clock when it becomes visible**, rather than being
        # started here at construction. A clock on a hidden panel is work nobody sees and
        # a timer that can tick into a teardown; see `OverlayPanel.showEvent`.

        application.monitor.on_change = self.overlay.health_updated.emit
        # **Cleared when this window is destroyed.** The application outlives the window,
        # so a hook holding a bound `emit` of a deleted widget is a dangling C++ pointer
        # the next health update walks into — an interpreter segfault, and the third time
        # this project has hit that shape (D-53, D-54). The lambda closes over
        # `application` and never over `self`, so it is not a cycle either.
        self.destroyed.connect(lambda: setattr(application.monitor, "on_change", None))
        # Pushed once so the strip shows the current state rather than a default nobody
        # chose, on a window that may be built mid-session.
        self.overlay.update_health(application.monitor.health)
        # Pushed once now so the panel is not blank until the first utterance: the
        # checklist is what the user reads before they have said anything.
        self.refresh_checklist()

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

        self.session_state_changed.connect(self.refresh_panic)
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
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        # Whether or not the dialog was accepted: FR37's switches apply the moment they
        # are toggled, so cancelling still leaves tracking off. Without this the
        # checklist keeps the rows it had until the next utterance arrives — and between
        # sessions there is no next utterance, so it would keep them indefinitely.
        self.refresh_checklist()
        if not accepted:
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

    # ---------- the panic surface (T6.3b — FR60, FR64a, FR87) ----------

    def panic(self) -> bool:
        """FR60's single action. One press, no confirmation, no second thought.

        **Guarded by state rather than by a dialog.** `panic_clear` raises from IDLE, and
        an exception escaping the one control a user presses under pressure is the worst
        possible response to a press that was merely early. Returns whether anything was
        stopped.
        """
        session = self.application.session
        if session.state not in (SessionState.RUNNING, SessionState.PAUSED):
            self.panic_status.setText(PANIC_UNAVAILABLE)
            self.refresh_panic()
            return False
        session.panic_clear()
        self.refresh_panic()
        return True

    def resume(self) -> bool:
        """FR64a's other half. A pause the user can undo is only a pause if they can."""
        session = self.application.session
        if session.state is not SessionState.PAUSED:
            self.refresh_panic()
            return False
        session.resume()
        self.refresh_panic()
        return True

    def refresh_panic(self) -> None:
        """State, in words, next to the control that changed it.

        The paused state has to be *visible*: a user who pressed panic and sees nothing
        change has no way to tell the press registered, and the failure mode is pressing
        it again — or worse, assuming it worked when it did not.
        """
        session = self.application.session
        paused = session.state is SessionState.PAUSED
        self.panic_button.setEnabled(session.state is SessionState.RUNNING or paused)
        self.resume_button.setEnabled(paused)
        if paused:
            cause = session.pause_cause
            self.panic_status.setText(
                f"Paused ({cause.name.lower() if cause else 'unknown'}). "
                "Nothing is being captured. Everything from this session is still here."
            )
        elif session.state is SessionState.RUNNING:
            self.panic_status.setText("Listening.")
        else:
            self.panic_status.setText(PANIC_UNAVAILABLE)

    def _on_context_set_change(self, context_set: object) -> None:
        """FR43. The panel renders against the newly active set from the next match on."""
        self.overlay.context_set = context_set  # type: ignore[assignment]
        self.refresh_checklist()

    def open_notes(self) -> NotesEditor:
        """T3.7/T3.8's surface. Same ownership rules as the other two dialogs.

        The overlay's geometry store is handed over as the settings object: FR43's active
        set persists beside the overlay's layout because both are per-user UI state, and
        because a widget minting its own `QSettings` is what D-52 forbids.
        """
        view = self._notes_factory(self.application, self._overlay_settings, self)
        self._notes = view
        view.show()
        return view

    def open_reports(self) -> ReportView:
        """M11's surface, reached from here (T11.10).

        Same ownership rules as the diagnostics view: held on the instance so a modeless
        dialog is not collected on return, and parented so Qt decides the teardown order.

        Modeless, because the session list is somewhere the user browses — and because
        the retention default means a session they are looking at can be one launch away
        from deletion, which is a thing to read next to the rest of the app rather than
        in a window that blocks it.
        """
        view = self._reports_factory(self.application, self)
        self._reports = view
        view.show()
        return view

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

    def refresh_checklist(self) -> None:
        """Push the tracker's current state at the overlay (T7.4 — FR12, FR37).

        The marks come from the tracker rather than being remembered here, so this is a
        redraw of what is already true and never a second opinion about coverage.
        """
        self.overlay.set_tracked_points(
            self.application.tracker.points(),
            self.application.session.switches.progress_tracker,
        )

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
