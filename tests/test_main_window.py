"""T9.6 — the window and the process entry point, under `QT_QPA_PLATFORM=offscreen`.

This is where T9.2b closes: something in production now constructs `SettingsDialog`,
feeds `on_switch` to `SessionManager.set_switch`, and passes the result to
`Application.apply_settings`. Until now those three pieces were each tested and none of
them was reachable.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from helpers import ReversingCipher, ScriptedClient

pytest.importorskip("PySide6", reason="Qt UI tests require the [ui] extra")

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from interview_prep_recall.app import Application  # noqa: E402
from interview_prep_recall.config import ConfigStore  # noqa: E402
from interview_prep_recall.first_run import CONSENT_FILENAME, FirstRunConsent  # noqa: E402
from interview_prep_recall.notes.model import ContextSet, Note, SourceKind  # noqa: E402
from interview_prep_recall.session.manager import PauseCause, SessionState  # noqa: E402
from interview_prep_recall.session.preflight import (  # noqa: E402
    CHECKS,
    Check,
    CheckClass,
    CheckResult,
    PreflightReport,
)
from interview_prep_recall.stt.assembler import Utterance  # noqa: E402
from interview_prep_recall.tracker.progress import TrackedPoint  # noqa: E402
from interview_prep_recall.ui.main_window import (
    BLOCKED_HEADING,
    PANIC_UNAVAILABLE,
    READY_TEXT,
    REPORTS_TEXT,  # noqa: E402
    MainWindow,
)
from interview_prep_recall.ui.overlay import (  # noqa: E402
    OverlayGeometry,
    load_geometry,
    save_geometry,
)
from interview_prep_recall.ui.report_view import DELETE_ALL_TEXT  # noqa: E402
from interview_prep_recall.ui.settings import SettingsDialog  # noqa: E402


class FlatEmbedder:
    model_id = "flat/one"
    model_version = "1.0"

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.ones((len(texts), 2), dtype=np.float32)


@pytest.fixture
def application(tmp_path: Path) -> Application:
    return Application(
        root=tmp_path,
        embedder=FlatEmbedder(),
        client=ScriptedClient(),
        cipher=ReversingCipher(),
        context_set=ContextSet(
            name="prep", notes=[Note(headline="Tell me about scaling", kind=SourceKind.PREP)]
        ),
    )


class FakeSettings:
    """Stands in for `QSettings`, round-tripping through strings as the real one does."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def setValue(self, key: str, value: object) -> None:  # noqa: N802 — Qt's name
        self.store[key] = str(value)

    def value(self, key: str, default: object = None) -> object:
        return self.store.get(key, default)


@pytest.fixture
def overlay_settings() -> FakeSettings:
    """Every window in these tests gets a settings double.

    `MainWindow` requires one rather than defaulting to `QSettings`, so a test cannot
    reach the real registry by forgetting — see the class docstring for why the T0.4
    guard cannot catch that on its own.
    """
    return FakeSettings()


def _report(*, blocked: bool) -> PreflightReport:
    check = Check("mic_device", "Microphone (you)", CheckClass.BLOCK)
    return PreflightReport((CheckResult(check, ok=not blocked, detail="no device"),))


# ---------- FR38 status ----------


def test_blockers_are_listed_with_reasons(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """A count tells the user nothing about which thing to fix."""
    window = MainWindow(application, _report(blocked=True), overlay_settings=overlay_settings)

    text = window.status.text()
    assert BLOCKED_HEADING in text
    assert "Microphone (you)" in text
    assert "no device" in text


def test_a_clear_preflight_reads_as_ready(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    window = MainWindow(application, _report(blocked=False), overlay_settings=overlay_settings)
    assert READY_TEXT in window.status.text()


def test_warnings_are_shown_without_blocking(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    check = Check("echo_clear", "Headphones detected", CheckClass.WARN)
    report = PreflightReport((CheckResult(check, ok=False, detail="echo suspected"),))

    window = MainWindow(application, report, overlay_settings=overlay_settings)

    assert READY_TEXT in window.status.text()
    assert "Headphones detected" in window.status.text()


def test_every_preflight_check_can_be_rendered(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """A check added to `CHECKS` must not produce a window that crashes on display."""
    report = PreflightReport(tuple(CheckResult(c, ok=False, detail=c.key) for c in CHECKS))
    window = MainWindow(application, report, overlay_settings=overlay_settings)
    assert window.status.text()


# ---------- T9.2b: the settings route ----------


def test_accepting_settings_applies_and_persists(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings, tmp_path: Path
) -> None:
    """The whole T9.2b path: dialog → `apply_settings` → disk."""

    def factory(app: Application) -> SettingsDialog:
        dialog = SettingsDialog(app.config)
        dialog.sensitivity.setValue(50)
        # Answer `exec()` without an event loop; the dialog's own behaviour is covered
        # in `test_settings.py`, and what this test is about is the wiring around it.
        dialog.exec = lambda: QDialog.DialogCode.Accepted  # type: ignore[method-assign]
        return dialog

    window = MainWindow(application, dialog_factory=factory, overlay_settings=overlay_settings)
    result = window.open_settings()

    assert result is not None
    assert "tau_floor" in result.applied
    assert application.prefilter.tau_floor == pytest.approx(0.50)
    reloaded, _status = ConfigStore(tmp_path).load()
    assert reloaded.tau_floor == pytest.approx(0.50)


def test_cancelling_settings_changes_nothing(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings, tmp_path: Path
) -> None:
    """Cancel must be a genuine no-op — nothing applied, nothing written."""
    before = application.prefilter.tau_floor

    def factory(app: Application) -> SettingsDialog:
        dialog = SettingsDialog(app.config)
        dialog.sensitivity.setValue(60)
        dialog.exec = lambda: QDialog.DialogCode.Rejected  # type: ignore[method-assign]
        return dialog

    window = MainWindow(application, dialog_factory=factory, overlay_settings=overlay_settings)

    assert window.open_settings() is None
    assert application.prefilter.tau_floor == pytest.approx(before)
    assert not (tmp_path / "config.json").exists()


def test_the_default_dialog_wires_the_fr37_switches(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """FR37's switches must reach `SessionManager.set_switch`, which is the only writer.

    Built through the *default* factory, because the production wiring is the thing under
    test — a test supplying its own factory would prove nothing about what ships.
    """
    window = MainWindow(application, overlay_settings=overlay_settings)
    dialog = window._dialog_factory(application)  # noqa: SLF001

    assert application.session.switches.progress_tracker is True
    dialog.switches["progress_tracker"].setChecked(False)
    assert application.session.switches.progress_tracker is False


def test_every_switch_reaches_the_session_manager(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """Each FR37 switch must actually flip the manager's state.

    Found in local review: this previously toggled each checkbox and then asserted
    `hasattr(switches, name)` — trivially true, unrelated to whether the toggle landed,
    and named for a guarantee it did not check. The same defect this project keeps
    finding, in a test written minutes earlier.
    """
    window = MainWindow(application, overlay_settings=overlay_settings)
    dialog = window._dialog_factory(application)  # noqa: SLF001

    for name, checkbox in dialog.switches.items():
        target = not getattr(application.session.switches, name)
        checkbox.setChecked(target)
        assert getattr(application.session.switches, name) is target, name


# ---------- the entry point ----------


def test_declined_consent_exits_without_building(tmp_path: Path, qapp: QApplication) -> None:
    """`main` returns a non-zero code and the factory is never called."""
    from interview_prep_recall.__main__ import EXIT_CONSENT_DECLINED, main

    calls: list[Path] = []

    def never(root: Path) -> Application:
        calls.append(root)
        raise AssertionError("must not be called")

    import interview_prep_recall.ui.consent_dialog as consent_dialog

    original = consent_dialog.present_disclosure
    consent_dialog.present_disclosure = lambda _text, parent=None: False  # type: ignore[assignment]
    try:
        code = main([str(tmp_path)], build_application=never)
    finally:
        consent_dialog.present_disclosure = original  # type: ignore[assignment]

    assert code == EXIT_CONSENT_DECLINED
    assert calls == []


def test_app_data_root_prefers_appdata(monkeypatch: pytest.MonkeyPatch) -> None:
    from interview_prep_recall.__main__ import APP_DIR_NAME, app_data_root

    monkeypatch.setenv("APPDATA", "/somewhere/roaming")
    assert app_data_root() == Path("/somewhere/roaming") / APP_DIR_NAME


def test_app_data_root_falls_back_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Not aspirational cross-platform support — it is what lets the entry point be run
    at all in the Linux dev container."""
    from interview_prep_recall.__main__ import APP_DIR_NAME, app_data_root

    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", "/home/someone/.config")
    assert app_data_root() == Path("/home/someone/.config") / APP_DIR_NAME


def test_real_dependency_construction_is_recorded_as_unfinished(tmp_path: Path) -> None:
    """T9.6a. It raises rather than guessing at FR43's active-note-set selection and the
    no-API-key policy — inventing those here would ship them as decisions nobody made."""
    from interview_prep_recall.__main__ import _build_application

    with pytest.raises(NotImplementedError, match="T9.6a"):
        _build_application(tmp_path)


def test_a_failed_startup_exits_cleanly_instead_of_crashing(
    tmp_path: Path, qapp: QApplication
) -> None:
    """Found in local review by running `python -m interview_prep_recall`, which printed
    a `NotImplementedError` traceback.

    An entry point's job is to start or to say why it cannot. A stack trace is neither —
    it is what a user sees when nobody decided what they should see.
    """
    from interview_prep_recall.__main__ import EXIT_STARTUP_FAILED, main

    FirstRunConsent(tmp_path / CONSENT_FILENAME).acknowledge()

    def explode(root: Path) -> Application:
        raise RuntimeError("dependency graph is incomplete")

    import interview_prep_recall.ui.main_window as main_window

    shown: list[str] = []
    original = main_window.QMessageBox.critical
    main_window.QMessageBox.critical = staticmethod(  # type: ignore[assignment]
        lambda _parent, _title, text: shown.append(text)
    )
    try:
        code = main([str(tmp_path)], build_application=explode)
    finally:
        main_window.QMessageBox.critical = original  # type: ignore[assignment]

    assert code == EXIT_STARTUP_FAILED
    assert shown, "the user was given no explanation"
    assert "dependency graph is incomplete" in shown[0]


def test_settings_change_refreshes_the_readiness_report(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """Found by review on PR #18.

    Which FR38 checks apply depends on the configured backend, so a report taken at
    process start goes stale the moment the user switches to a cloud backend — they would
    see the original "ready" without the API key or service ever being validated.
    """

    # The device disappeared (or the backend changed) since the window opened.
    def refresh() -> PreflightReport:
        return _report(blocked=True)

    def factory(app: Application) -> SettingsDialog:
        dialog = SettingsDialog(app.config)
        dialog.sensitivity.setValue(50)
        dialog.exec = lambda: QDialog.DialogCode.Accepted  # type: ignore[method-assign]
        return dialog

    window = MainWindow(
        application,
        _report(blocked=False),
        dialog_factory=factory,
        overlay_settings=overlay_settings,
        refresh_preflight=refresh,
    )
    assert READY_TEXT in window.status.text()

    window.open_settings()

    assert BLOCKED_HEADING in window.status.text(), "the readiness report went stale"


def test_a_window_without_a_refresh_hook_still_works(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """The hook is optional, and its absence must not break the settings route."""

    def factory(app: Application) -> SettingsDialog:
        dialog = SettingsDialog(app.config)
        dialog.exec = lambda: QDialog.DialogCode.Accepted  # type: ignore[method-assign]
        return dialog

    window = MainWindow(
        application,
        _report(blocked=False),
        dialog_factory=factory,
        overlay_settings=overlay_settings,
    )
    assert window.open_settings() is not None


# ---------- T5.8: the route into the diagnostics viewer ----------


def test_the_window_opens_the_diagnostics_viewer(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """FR36's "viewable in-app" needs somewhere to be viewed *from*. The buffer and the
    view both existed and nothing reached either — the same gap T9.2b closed for settings.
    """
    application.ring.record("stt_connected", backend="local")
    # The window is held: the viewer is parented to it, so a discarded window takes the
    # dialog with it. That is the ownership the parent is there to provide.
    window = window_with(application, overlay_settings)

    view = window.open_diagnostics()

    assert [row[1] for row in view.rows] == ["stt_connected"]


def test_the_viewer_is_held_so_it_does_not_vanish(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """A modeless `QDialog` that goes out of scope is collected and the window disappears
    — the defect the overlay's transition animation already had."""
    window = window_with(application, overlay_settings)

    view = window.open_diagnostics()

    assert window._diagnostics is view  # noqa: SLF001


def test_the_viewer_reads_the_applications_ring(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """Not a fresh buffer: a viewer wired to its own ring would show an empty table for
    every session and look like a working feature."""
    window = window_with(application, overlay_settings)

    assert window.open_diagnostics().ring is application.ring


# ---------- T11.10: the route into the report surface ----------


def test_the_window_opens_the_report_view(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """M11 stored, generated and verified reports for a whole milestone with nothing
    that could open one. Same gap T5.8 closed for the diagnostics ring."""
    window = window_with(application, overlay_settings)

    view = window.open_reports()

    assert view.isVisible()
    assert view.rows == (), "no sessions stored in this fixture"


def test_the_report_view_is_held_and_parented(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """The ownership rule this window already follows twice: held so a modeless dialog is
    not collected on return, parented so Qt decides the teardown order."""
    window = window_with(application, overlay_settings)

    view = window.open_reports()

    assert window._reports is view  # noqa: SLF001
    assert view.parent() is window


def test_the_report_view_reads_the_applications_store(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """Not a fresh store: a view wired to its own would show an empty list forever and
    look like a working feature."""
    window = window_with(application, overlay_settings)

    assert window.open_reports().sessions is application.sessions


def window_with(application: Application, settings: FakeSettings) -> MainWindow:
    return MainWindow(application, _report(blocked=False), overlay_settings=settings)


# ---------- PR #21 review: FR27 and FR55 need reachable controls ----------


def test_the_reset_control_is_on_the_window_not_the_panel(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """FR55 exists for a panel the user cannot reach, so a button on that panel is not a
    recovery route. Found by review on PR #21, where `reset_geometry` had no caller."""
    settings = FakeSettings()
    save_geometry(settings, OverlayGeometry(x=-9000, y=-9000, locked=True))
    window = MainWindow(application, _report(blocked=False), overlay_settings=settings)
    assert window.overlay.geometry_settings.x == -9000

    recovered = window.reset_overlay()

    assert recovered.x > -9000
    assert recovered.locked is False


def test_the_recovered_position_is_persisted(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """A reset that lasts until restart would put the user back on the coordinates it
    just rescued them from."""
    settings = FakeSettings()
    save_geometry(settings, OverlayGeometry(x=-9000, y=-9000))
    window = MainWindow(application, _report(blocked=False), overlay_settings=settings)

    recovered = window.reset_overlay()

    assert load_geometry(settings).x == recovered.x


def test_reset_brings_the_lock_checkbox_back_in_step(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """Reset clears the lock, so a checkbox left ticked would show a lock the geometry no
    longer has."""
    settings = FakeSettings()
    save_geometry(settings, OverlayGeometry(locked=True))
    window = MainWindow(application, _report(blocked=False), overlay_settings=settings)
    assert window.lock_overlay_box.isChecked() is True

    window.reset_overlay()

    assert window.lock_overlay_box.isChecked() is False


def test_the_lock_toggle_reaches_the_panel_and_the_store(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """FR27, from a surface that stays reachable when the panel does not."""
    settings = FakeSettings()
    window = MainWindow(application, _report(blocked=False), overlay_settings=settings)

    window.lock_overlay_box.setChecked(True)

    assert window.overlay.locked is True
    assert load_geometry(settings).locked is True


def test_the_lock_checkbox_starts_from_the_persisted_state(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    settings = FakeSettings()
    save_geometry(settings, OverlayGeometry(locked=True))

    window = MainWindow(application, _report(blocked=False), overlay_settings=settings)

    assert window.lock_overlay_box.isChecked() is True


def test_a_drag_on_the_panel_persists_through_the_window(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """The wiring the panel could not do for itself: `on_geometry_changed` now has a
    production subscriber, so FR26 holds outside the tests that fake one."""
    settings = FakeSettings()
    window = MainWindow(application, _report(blocked=False), overlay_settings=settings)
    start = window.overlay.geometry_settings

    window.overlay.begin_manipulation(QPoint(200, 60), QPoint(0, 0))
    window.overlay.update_manipulation(QPoint(35, 0))
    window.overlay.end_manipulation()

    assert load_geometry(settings).x == start.x + 35


def test_the_preview_toggle_shows_and_hides_the_panel(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """Drag, resize and reset are things the user does to a panel they can see, and none
    of them needs an interview to be running."""
    window = MainWindow(application, _report(blocked=False), overlay_settings=overlay_settings)

    window.preview_overlay_button.setChecked(True)
    assert window.overlay.isVisible() is True

    window.preview_overlay_button.setChecked(False)
    assert window.overlay.isVisible() is False


def test_the_overlay_starts_hidden(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """There is no session, so an always-on-top panel appearing at launch would be a
    claim that something is running."""
    window = MainWindow(application, _report(blocked=False), overlay_settings=overlay_settings)

    assert window.overlay.isVisible() is False


# ---------- T7.4: the checklist's production feed ----------


@pytest.fixture
def tracking_application(tmp_path: Path) -> Application:
    """An application whose note set actually has tracked points.

    The default fixture's note is untracked, so a checklist test against it would pass
    with the wiring removed — the widget would be empty either way.
    """
    return Application(
        root=tmp_path,
        embedder=FlatEmbedder(),
        client=ScriptedClient(),
        cipher=ReversingCipher(),
        context_set=ContextSet(
            name="prep",
            notes=[
                Note(headline="Tell me about scaling", kind=SourceKind.PREP, track_progress=True),
                Note(headline="Tell me about conflict", kind=SourceKind.PREP, track_progress=True),
            ],
        ),
    )


def test_the_checklist_is_populated_at_construction(
    qapp: QApplication, tracking_application: Application, overlay_settings: FakeSettings
) -> None:
    """The checklist is what the user reads *before* they have said anything, so waiting
    for the first utterance would leave it blank for the part that matters most."""
    window = MainWindow(tracking_application, overlay_settings=overlay_settings)

    assert len(window.overlay.checklist.rows) == 2


def test_the_application_pushes_the_checklist_at_the_panel(
    qapp: QApplication, tracking_application: Application, overlay_settings: FakeSettings
) -> None:
    """The connection, not the pieces: both ends were already tested and neither was
    reachable from the other."""
    window = MainWindow(tracking_application, overlay_settings=overlay_settings)
    tracked = tracking_application.context_set.tracked()

    tracking_application.on_tracker_update(
        [TrackedPoint(tracked[0].id, tracked[0].headline, True)], True
    )

    assert window.overlay.checklist.marked_count == 1


def test_turning_the_tracker_off_in_settings_clears_the_checklist(
    qapp: QApplication, tracking_application: Application, overlay_settings: FakeSettings
) -> None:
    """FR37 applies the moment the switch is toggled. Between sessions there is no next
    utterance to redraw on, so the rows would otherwise stay up indefinitely."""
    window = MainWindow(tracking_application, overlay_settings=overlay_settings)
    assert window.overlay.checklist.showing is True

    tracking_application.session.set_switch("progress_tracker", False)
    window.refresh_checklist()

    assert window.overlay.checklist.showing is False


def test_a_cancelled_settings_dialog_still_redraws_the_checklist(
    qapp: QApplication, tracking_application: Application, overlay_settings: FakeSettings
) -> None:
    """Cancelling does not undo an FR37 switch — it applies on toggle — so the redraw
    cannot hang off the accepted path."""

    def factory(app: Application) -> SettingsDialog:
        # The switch applies on toggle, which is what the real dialog does through its
        # `on_switch` callback — see `_default_dialog`.
        app.session.set_switch("progress_tracker", False)
        dialog = SettingsDialog(app.config)
        dialog.exec = lambda: QDialog.DialogCode.Rejected  # type: ignore[method-assign]
        return dialog

    window = MainWindow(
        tracking_application, dialog_factory=factory, overlay_settings=overlay_settings
    )

    assert window.open_settings() is None
    assert window.overlay.checklist.showing is False


# ---------- T6.3b / T11.10a: the panic surface and FR87's signpost ----------


def test_panic_is_a_single_action_that_pauses(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """FR60 keeps panic single-action, and FR64a makes it a pause. One press, no
    confirmation — a dialog on the control someone reaches for when a person walks into
    the room is a control that does not work."""
    application.session.request_start()
    application.session.preflight_result(blocked=False)
    window = window_with(application, overlay_settings)

    assert window.panic() is True

    assert application.session.state is SessionState.PAUSED
    assert application.session.pause_cause is PauseCause.PANIC


def test_panic_destroys_nothing(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """FR58/FR64a. The signpost claims the transcript survives; this is the claim."""
    application.session.request_start()
    application.session.preflight_result(blocked=False)
    application.consume(
        Utterance(stream_id="interviewer", text="a question", t_start=0.0, t_end=1.0, context=""),
        now=1.0,
    )
    window = window_with(application, overlay_settings)

    window.panic()

    assert len(application.record) == 1, "the transcript survives a panic (D-U11)"


def test_panic_before_a_session_says_so_rather_than_raising(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """`panic_clear` raises from IDLE, and an exception escaping the one control a user
    presses under pressure is the worst answer to a press that was merely early."""
    window = window_with(application, overlay_settings)

    assert window.panic() is False
    assert window.panic_status.text() == PANIC_UNAVAILABLE


def test_a_paused_session_can_be_resumed_from_the_same_surface(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """A pause the user can undo is only a pause if they can."""
    application.session.request_start()
    application.session.preflight_result(blocked=False)
    window = window_with(application, overlay_settings)
    window.panic()

    assert window.resume() is True
    assert application.session.state is SessionState.RUNNING


def test_the_paused_state_is_visible_not_inferred(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """A user who pressed panic and sees nothing change cannot tell it registered, and
    the failure mode is pressing it again — or assuming it worked when it did not."""
    application.session.request_start()
    application.session.preflight_result(blocked=False)
    window = window_with(application, overlay_settings)

    window.panic()

    assert "paused" in window.panic_status.text().lower()
    assert "panic" in window.panic_status.text().lower()
    assert window.resume_button.isEnabled(), "and the way out is offered with it"


def test_the_panic_surface_signposts_delete_all(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """FR87, which is the whole of T11.10a: panic no longer destroys anything, so the
    surface has to say so *and* point at the deliberate route — otherwise a user reaching
    for panic for privacy reasons leaves with a false impression and no way to act on it.
    """
    window = window_with(application, overlay_settings)

    signpost = window.panic_signpost.text()
    assert DELETE_ALL_TEXT.rstrip("…") in signpost
    assert REPORTS_TEXT.rstrip("…") in signpost
    assert "deletes anything" in signpost


def test_the_route_the_signpost_names_actually_exists(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """A signpost pointing at a control that is not there would satisfy FR87's wording
    and fail the person reading it."""
    window = window_with(application, overlay_settings)

    view = window.open_reports()

    assert view.delete_all_button.text() == DELETE_ALL_TEXT


# ---------- PR #25 review: the wires that did not exist ----------


def test_health_changes_reach_the_overlay(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """FR20/FR35. The monitor recorded every state the indicators were built to render
    and **nothing connected them** — correct in memory, never drawn. Both halves had
    passing tests; the wire between them was the part nobody owned (D-20).
    """
    window = window_with(application, overlay_settings)
    before = window.overlay.indicators.visual_state()

    application.egress.set_llm(True)

    assert window.overlay.indicators.visual_state() != before, "the egress lamp moved"


def test_the_indicator_shows_the_current_state_when_the_window_opens(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """A window built mid-session must not start from a default nobody chose."""
    application.egress.set_llm(True)

    window = window_with(application, overlay_settings)

    assert window.overlay.indicators.visual_state() == _egress_state(application)


def _egress_state(application: Application) -> tuple[str, ...]:
    from interview_prep_recall.ui.indicators import IndicatorBar

    bar = IndicatorBar()
    bar.update_health(application.monitor.health)
    return bar.visual_state()


def test_the_panic_control_comes_alive_when_a_session_starts(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """The window is built at IDLE and the session starts later, so a one-shot refresh
    at construction left the emergency control disabled for the whole session — dead in
    exactly the case it exists for. The first tests missed it by starting the session
    before building the window. Found by review on PR #25.
    """
    window = window_with(application, overlay_settings)
    assert not window.panic_button.isEnabled()

    application.session.request_start()
    application.session.preflight_result(blocked=False)

    assert window.panic_button.isEnabled()
    assert window.panic_status.text() == "Listening."


def test_the_state_subscription_does_not_outlive_the_window(
    qapp: QApplication, application: Application, overlay_settings: FakeSettings
) -> None:
    """The application outlives the window, so a hook holding a bound `emit` of a deleted
    widget is a dangling pointer the next transition walks into — the segfault shape this
    codebase has now hit three times (D-53, D-54)."""
    from PySide6.QtCore import QCoreApplication, QEvent

    window = window_with(application, overlay_settings)
    window.close()
    window.deleteLater()
    # `processEvents` alone does not run deferred deletions; this is the documented way
    # to force them, and forcing them is the point — the hazard is what happens *after*
    # the C++ object is gone.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    assert application.session.on_state_change is None
    assert application.monitor.on_change is None
