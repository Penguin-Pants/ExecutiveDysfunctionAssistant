"""The first-run disclosure dialog (T9.1 — FR63).

The **first Qt in this codebase.** `pyproject.toml` claimed PySide6 "cannot be installed
or exercised on the Linux dev box"; it installs, and it runs under
`QT_QPA_PLATFORM=offscreen` with widgets, signals and modal dialogs all working. That was
the fifth blanket "needs Windows" label in this project to turn out false on inspection.
What genuinely needs Windows is `SetWindowDisplayAffinity` (T5.2) — an API call, not a
toolkit.

**What "unavoidable" has to mean in Qt.** `QDialog` offers several ways out that all land
on `Rejected`, and only one of them is the user saying no:

* **Esc.** `QDialog` binds it to `reject()` by default.
* **The title-bar close button.**
* **`closeEvent`** from the window manager or a programmatic `close()`.

None of those is an acknowledgement, so all of them are closed off and the only routes
out of this dialog are the two explicit buttons. Esc and the X are *neutralised* rather
than mapped to decline: a legal notice dismissed by a reflexive Esc should still be there
when the user looks back at the screen, because the alternative is an app that quits
without explanation seconds before an interview.

**Declining exits.** There is no third path where the user keeps the app without agreeing
— that would be the disclosure being avoidable, which is precisely what FR63 forbids.
The caller decides how to exit; this dialog only reports which button was pressed.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

WINDOW_TITLE = "Before you start"
ACKNOWLEDGE_LABEL = "I understand and accept responsibility"
CONTINUE_LABEL = "Continue"
DECLINE_LABEL = "Quit"


class FirstRunConsentDialog(QDialog):
    """Modal, un-dismissable disclosure. Returns acknowledgement only via `accepted`."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(WINDOW_TITLE)
        self.setModal(True)
        # No close button in the title bar. `closeEvent` is overridden as well, because
        # this flag is a hint the window manager is free to ignore — a guarantee that
        # depends on the compositor's goodwill is not a guarantee.
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowTitleHint)

        self._acknowledged = False
        self._allow_close = False

        layout = QVBoxLayout(self)
        label = QLabel(text)
        label.setWordWrap(True)
        # Explicitly plain text. The disclosure is a constant today, but a QLabel
        # defaulting to rich text would silently start interpreting markup the moment
        # this string became translatable or user-influenced.
        label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(label)

        self.checkbox = QCheckBox(ACKNOWLEDGE_LABEL)
        layout.addWidget(self.checkbox)

        buttons = QDialogButtonBox()
        self.continue_button = QPushButton(CONTINUE_LABEL)
        self.decline_button = QPushButton(DECLINE_LABEL)
        buttons.addButton(self.continue_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(self.decline_button, QDialogButtonBox.ButtonRole.RejectRole)
        layout.addWidget(buttons)

        # Two deliberate steps to agreement: tick, then press. A single button is one
        # muscle-memory Enter away from being pressed by someone who never read it.
        self.continue_button.setEnabled(False)
        self.checkbox.toggled.connect(self.continue_button.setEnabled)
        self.continue_button.clicked.connect(self._on_accept)
        self.decline_button.clicked.connect(self._on_decline)

        # `QDialogButtonBox` wires its own accepted/rejected signals to buttons by role,
        # which would let the accept role fire without the checkbox. The buttons are
        # connected individually above; these are left disconnected on purpose.

    # ---------- outcome ----------

    @property
    def acknowledged(self) -> bool:
        """True only after the checkbox was ticked and Continue was pressed.

        Read this rather than `exec()`'s return code. `Rejected` conflates "declined"
        with "dismissed", and the whole point of FR63 is that those are not the same.
        """
        return self._acknowledged

    def _on_accept(self) -> None:
        if not self.checkbox.isChecked():
            # Defence in depth: the button is disabled, but a programmatic `click()` in
            # a future refactor should not be able to manufacture consent.
            return
        self._acknowledged = True
        self.accept()

    def _on_decline(self) -> None:
        self.decline()

    # ---------- unavoidability ----------

    def accept(self) -> None:
        """Guarded so the dialog cannot be accepted without the acknowledgement it
        exists to collect, however it is reached."""
        if self._acknowledged:
            super().accept()

    def reject(self) -> None:
        """Esc and every other implicit dismissal route through here, and are ignored.

        One flag decides whether closing is permitted, and only `decline()` sets it. The
        earlier version of this method inspected `sender()` to tell a button press from
        an Esc — which is valid only during signal emission and silently wrong when
        `reject()` is called any other way, i.e. exactly in the cases it was guarding
        against.

        Mapping Esc to decline would be defensible; letting it silently *dismiss* the
        notice is not, and that is what the base implementation does. A legal notice
        dismissed by a reflexive Esc should still be on screen when the user looks back,
        because the alternative is an app that quits without explanation minutes before
        an interview.
        """
        if self._allow_close:
            super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        """The window manager's close request. Refused for the same reason as Esc."""
        event.ignore()

    def decline(self) -> None:
        """The only supported way to leave this dialog without acknowledging."""
        self._acknowledged = False
        self._allow_close = True
        try:
            super().reject()
        finally:
            self._allow_close = False


def present_disclosure(text: str, parent: QWidget | None = None) -> bool:
    """A `DisclosurePresenter` backed by the Qt dialog.

    Signature and return contract match `first_run.DisclosurePresenter`: True only on
    explicit acknowledgement.
    """
    dialog = FirstRunConsentDialog(text, parent)
    dialog.exec()
    return dialog.acknowledged
