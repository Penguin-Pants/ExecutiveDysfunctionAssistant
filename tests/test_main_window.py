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

from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from interview_prep_recall.app import Application  # noqa: E402
from interview_prep_recall.config import ConfigStore  # noqa: E402
from interview_prep_recall.first_run import CONSENT_FILENAME, FirstRunConsent  # noqa: E402
from interview_prep_recall.notes.model import ContextSet, Note, SourceKind  # noqa: E402
from interview_prep_recall.session.preflight import (  # noqa: E402
    CHECKS,
    Check,
    CheckClass,
    CheckResult,
    PreflightReport,
)
from interview_prep_recall.ui.main_window import (  # noqa: E402
    BLOCKED_HEADING,
    READY_TEXT,
    MainWindow,
)
from interview_prep_recall.ui.settings import SettingsDialog  # noqa: E402


class FlatEmbedder:
    model_id = "flat/one"
    model_version = "1.0"

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.ones((len(texts), 2), dtype=np.float32)


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


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


def _report(*, blocked: bool) -> PreflightReport:
    check = Check("mic_device", "Microphone (you)", CheckClass.BLOCK)
    return PreflightReport((CheckResult(check, ok=not blocked, detail="no device"),))


# ---------- FR38 status ----------


def test_blockers_are_listed_with_reasons(qapp: QApplication, application: Application) -> None:
    """A count tells the user nothing about which thing to fix."""
    window = MainWindow(application, _report(blocked=True))

    text = window.status.text()
    assert BLOCKED_HEADING in text
    assert "Microphone (you)" in text
    assert "no device" in text


def test_a_clear_preflight_reads_as_ready(qapp: QApplication, application: Application) -> None:
    window = MainWindow(application, _report(blocked=False))
    assert READY_TEXT in window.status.text()


def test_warnings_are_shown_without_blocking(qapp: QApplication, application: Application) -> None:
    check = Check("echo_clear", "Headphones detected", CheckClass.WARN)
    report = PreflightReport((CheckResult(check, ok=False, detail="echo suspected"),))

    window = MainWindow(application, report)

    assert READY_TEXT in window.status.text()
    assert "Headphones detected" in window.status.text()


def test_every_preflight_check_can_be_rendered(
    qapp: QApplication, application: Application
) -> None:
    """A check added to `CHECKS` must not produce a window that crashes on display."""
    report = PreflightReport(tuple(CheckResult(c, ok=False, detail=c.key) for c in CHECKS))
    window = MainWindow(application, report)
    assert window.status.text()


# ---------- T9.2b: the settings route ----------


def test_accepting_settings_applies_and_persists(
    qapp: QApplication, application: Application, tmp_path: Path
) -> None:
    """The whole T9.2b path: dialog → `apply_settings` → disk."""

    def factory(app: Application) -> SettingsDialog:
        dialog = SettingsDialog(app.config)
        dialog.sensitivity.setValue(50)
        # Answer `exec()` without an event loop; the dialog's own behaviour is covered
        # in `test_settings.py`, and what this test is about is the wiring around it.
        dialog.exec = lambda: QDialog.DialogCode.Accepted  # type: ignore[method-assign]
        return dialog

    window = MainWindow(application, dialog_factory=factory)
    result = window.open_settings()

    assert result is not None
    assert "tau_floor" in result.applied
    assert application.prefilter.tau_floor == pytest.approx(0.50)
    reloaded, _status = ConfigStore(tmp_path).load()
    assert reloaded.tau_floor == pytest.approx(0.50)


def test_cancelling_settings_changes_nothing(
    qapp: QApplication, application: Application, tmp_path: Path
) -> None:
    """Cancel must be a genuine no-op — nothing applied, nothing written."""
    before = application.prefilter.tau_floor

    def factory(app: Application) -> SettingsDialog:
        dialog = SettingsDialog(app.config)
        dialog.sensitivity.setValue(60)
        dialog.exec = lambda: QDialog.DialogCode.Rejected  # type: ignore[method-assign]
        return dialog

    window = MainWindow(application, dialog_factory=factory)

    assert window.open_settings() is None
    assert application.prefilter.tau_floor == pytest.approx(before)
    assert not (tmp_path / "config.json").exists()


def test_the_default_dialog_wires_the_fr37_switches(
    qapp: QApplication, application: Application
) -> None:
    """FR37's switches must reach `SessionManager.set_switch`, which is the only writer.

    Built through the *default* factory, because the production wiring is the thing under
    test — a test supplying its own factory would prove nothing about what ships.
    """
    window = MainWindow(application)
    dialog = window._dialog_factory(application)  # noqa: SLF001

    assert application.session.switches.progress_tracker is True
    dialog.switches["progress_tracker"].setChecked(False)
    assert application.session.switches.progress_tracker is False


def test_every_switch_reaches_the_session_manager(
    qapp: QApplication, application: Application
) -> None:
    """Each FR37 switch must actually flip the manager's state.

    Found in local review: this previously toggled each checkbox and then asserted
    `hasattr(switches, name)` — trivially true, unrelated to whether the toggle landed,
    and named for a guarantee it did not check. The same defect this project keeps
    finding, in a test written minutes earlier.
    """
    window = MainWindow(application)
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
