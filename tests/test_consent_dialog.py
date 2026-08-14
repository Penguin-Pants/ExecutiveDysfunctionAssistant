"""T9.1 — the disclosure dialog itself, under `QT_QPA_PLATFORM=offscreen`.

These run headless, on Linux and on CI's Windows runner alike. The claim that PySide6
"cannot be exercised on the Linux dev box" was false; the only genuinely Windows-bound
piece of UI in this project is `SetWindowDisplayAffinity` (T5.2), which is an API call
rather than a toolkit.

Every test here is about **one** property: nothing except ticking the box and pressing
Continue produces an acknowledgement. FR63's "unavoidable" is exactly that property, and
it is not visible from the policy layer — `require_consent` cannot tell a presenter that
returns True honestly from one that returns True because Esc set an accepted flag.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="Qt UI tests require the [ui] extra")

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtGui import QCloseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from interview_prep_recall.first_run import (  # noqa: E402
    DISCLOSURE_TEXT,
    ConsentOutcome,
    FirstRunConsent,
    require_consent,
)
from interview_prep_recall.ui.consent_dialog import (  # noqa: E402
    FirstRunConsentDialog,
    present_disclosure,
)


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """One `QApplication` per session — Qt permits no more, and a per-test one would
    abort the run rather than fail a test."""
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(qapp: QApplication) -> FirstRunConsentDialog:
    return FirstRunConsentDialog(DISCLOSURE_TEXT)


# ---------- blocks until acknowledged ----------


def test_continue_is_disabled_until_the_box_is_ticked(dialog: FirstRunConsentDialog) -> None:
    assert dialog.continue_button.isEnabled() is False
    dialog.checkbox.setChecked(True)
    assert dialog.continue_button.isEnabled() is True
    dialog.checkbox.setChecked(False)
    assert dialog.continue_button.isEnabled() is False


def test_acknowledging_requires_both_steps(dialog: FirstRunConsentDialog) -> None:
    dialog.checkbox.setChecked(True)
    dialog.continue_button.click()
    assert dialog.acknowledged is True


def test_clicking_continue_without_ticking_does_not_acknowledge(
    dialog: FirstRunConsentDialog,
) -> None:
    """The button is disabled, so this is defence in depth — but `click()` bypasses the
    disabled state in some Qt paths, and a future refactor connecting a shortcut or a
    default-button Enter must not be able to manufacture consent."""
    dialog.continue_button.click()
    assert dialog.acknowledged is False


# ---------- unavoidable ----------


def test_escape_does_not_dismiss_the_dialog(dialog: FirstRunConsentDialog) -> None:
    """`QDialog` binds Esc to `reject()` by default. A legal notice that vanishes on a
    reflexive keypress is not unavoidable."""
    dialog.show()
    dialog.reject()  # what the Esc key binding calls
    assert dialog.acknowledged is False
    assert dialog.isVisible() is True, "Esc must not close the disclosure"


def test_window_close_is_refused(dialog: FirstRunConsentDialog) -> None:
    dialog.show()
    event = QCloseEvent()
    dialog.closeEvent(event)
    assert event.isAccepted() is False
    assert dialog.isVisible() is True


def test_close_call_does_not_acknowledge(dialog: FirstRunConsentDialog) -> None:
    dialog.show()
    dialog.close()
    assert dialog.acknowledged is False


def test_programmatic_accept_without_acknowledgement_is_refused(
    dialog: FirstRunConsentDialog,
) -> None:
    """`accept()` is public on `QDialog` and reachable from any future signal wiring."""
    dialog.show()
    dialog.accept()
    assert dialog.acknowledged is False
    assert dialog.isVisible() is True


def test_decline_is_the_one_way_out_without_acknowledging(
    dialog: FirstRunConsentDialog,
) -> None:
    dialog.show()
    dialog.decline_button.click()
    assert dialog.acknowledged is False
    assert dialog.isVisible() is False


def test_decline_can_be_called_programmatically(dialog: FirstRunConsentDialog) -> None:
    dialog.show()
    dialog.decline()
    assert dialog.acknowledged is False
    assert dialog.isVisible() is False


def test_the_close_gate_does_not_stay_open(dialog: FirstRunConsentDialog) -> None:
    """`decline()` opens the gate and must close it again.

    A flag left set would make every subsequent Esc dismiss the dialog — the guarantee
    working exactly once, which is this project's recurring defect shape.
    """
    dialog.decline()
    second = FirstRunConsentDialog(DISCLOSURE_TEXT)
    second.show()
    second.reject()
    assert second.isVisible() is True


# ---------- presentation ----------


def test_dialog_is_modal_and_shows_the_text(dialog: FirstRunConsentDialog) -> None:
    assert dialog.isModal() is True
    assert DISCLOSURE_TEXT in _label_text(dialog)


def test_disclosure_is_rendered_as_plain_text(dialog: FirstRunConsentDialog) -> None:
    """A `QLabel` defaulting to rich text would interpret markup the moment this string
    became translatable or user-influenced."""
    from PySide6.QtWidgets import QLabel

    label = next(w for w in dialog.findChildren(QLabel) if DISCLOSURE_TEXT in w.text())
    assert label.textFormat() is Qt.TextFormat.PlainText


def _label_text(dialog: FirstRunConsentDialog) -> str:
    from PySide6.QtWidgets import QLabel

    return "\n".join(w.text() for w in dialog.findChildren(QLabel))


# ---------- the presenter contract, end to end ----------
#
# These call `present_disclosure` itself rather than a hand-rolled stand-in. An earlier
# version of this file built its own presenters and only *imported* the real one — so
# two tests named `test_present_disclosure_*` passed without the function under test
# ever running, while an `__all__` line kept the unused import from being flagged. The
# production seam is the one thing here that must not be simulated.


def _interact_with_modal(
    qapp: QApplication, action: Callable[[FirstRunConsentDialog], None]
) -> None:
    """Run `action` against the modal dialog once `exec()` has entered its event loop.

    `present_disclosure` blocks in `exec()`, so the only way to drive it is from inside
    that loop. `singleShot(0)` fires on the first pass through it.
    """

    def run() -> None:
        dialog = qapp.activeModalWidget()
        assert isinstance(dialog, FirstRunConsentDialog), f"no modal dialog; got {dialog!r}"
        action(dialog)

    QTimer.singleShot(0, run)


def test_present_disclosure_returns_true_on_acknowledgement(qapp: QApplication) -> None:
    def acknowledge(dialog: FirstRunConsentDialog) -> None:
        dialog.checkbox.setChecked(True)
        dialog.continue_button.click()

    _interact_with_modal(qapp, acknowledge)
    assert present_disclosure(DISCLOSURE_TEXT) is True


def test_present_disclosure_returns_false_on_decline(qapp: QApplication) -> None:
    _interact_with_modal(qapp, lambda dialog: dialog.decline_button.click())
    assert present_disclosure(DISCLOSURE_TEXT) is False


def test_present_disclosure_is_a_valid_disclosure_presenter(
    qapp: QApplication, app_data: Path
) -> None:
    """The whole FR63 path: real dialog, real gate, real record on disk."""
    consent = FirstRunConsent(app_data / "consent.json")

    def acknowledge(dialog: FirstRunConsentDialog) -> None:
        dialog.checkbox.setChecked(True)
        dialog.continue_button.click()

    _interact_with_modal(qapp, acknowledge)
    outcome = require_consent(consent, present_disclosure)

    assert outcome is ConsentOutcome.ACKNOWLEDGED
    assert consent.required is False


def test_declining_through_the_real_dialog_writes_nothing(
    qapp: QApplication, app_data: Path
) -> None:
    consent = FirstRunConsent(app_data / "consent.json")

    _interact_with_modal(qapp, lambda dialog: dialog.decline_button.click())
    outcome = require_consent(consent, present_disclosure)

    assert outcome is ConsentOutcome.DECLINED
    assert not consent.path.exists()
