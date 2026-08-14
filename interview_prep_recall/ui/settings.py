"""The settings dialog (T9.2 — FR52, FR37, D-9).

Design §1 names this module `ui/settings.py`, so it lives here rather than in a
`settings_dialog.py` beside the stub it replaces — T0.1 requires the module tree to match
§1. The top-level `settings.py` is a different thing: it applies settings to running
components. Policy top-level, widget under `ui/`, as with `first_run.py`.

Presents two things that look alike on screen and must never be confused underneath:

* **Persisted settings** — sensitivity, thresholds, model ids, backend, retention. These
  are edited into an `AppConfig` and written to `config.json` on accept.
* **FR37 degradation switches** — LLM matching, cloud STT, progress tracker. These flip a
  *running* session immediately and are **not** written anywhere. A user who turns off
  cloud STT because the network died must not find it still off next week having
  forgotten; FR37 calls them mid-session controls and that is exactly what they are.

The dialog therefore has two output channels: `config()` returns the edited settings, and
the switches fire a callback the moment they are toggled. Collecting them into one "save"
would make the switches persist and the settings live, which is backwards on both counts.

**The slider is integer-only, and that is where the bug would be.** `QSlider` has no
float mode, so FR52's 0.20–0.60 range is held as 20–60 and divided on read. Every
conversion is funnelled through two functions here rather than written inline at each
site, because a rounding difference between the write path and the read path produces a
setting that silently moves each time the dialog is opened.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from interview_prep_recall.config import (
    TAU_TRACK_MAX,
    TAU_TRACK_MIN,
    AppConfig,
    SttBackendChoice,
)
from interview_prep_recall.matching.prefilter import TAU_FLOOR_MAX, TAU_FLOOR_MIN

WINDOW_TITLE = "Settings"

SLIDER_SCALE = 100
"""Sliders are integers. One scale factor, used by both conversions below."""

RETENTION_NEVER = 0
"""The spin box's "never" sentinel. `AppConfig` uses `None`; 0 is not a legal retention
value, so the mapping is unambiguous in both directions."""

SWITCH_LABELS = {
    "llm_matching": "LLM matching (off = local-only)",
    "cloud_stt": "Cloud speech-to-text",
    "progress_tracker": "Progress tracker",
}
"""FR37's three switches. Keys match `DegradationSwitches` field names, which is what
`SessionManager.set_switch` validates against — a typo here becomes a `ValueError` at
click time rather than a silently dead toggle."""

SwitchCallback = Callable[[str, bool], None]


def to_slider(value: float) -> int:
    return round(value * SLIDER_SCALE)


def from_slider(value: int) -> float:
    """Inverse of `to_slider`, to the precision the slider can represent.

    Rounded rather than left as raw float division: `24 / 100` is not exactly 0.24, and
    the difference is enough for an equality check against the stored value to report a
    change on every open, writing the file each time.
    """
    return round(value / SLIDER_SCALE, 2)


class SettingsDialog(QDialog):
    """Edits an `AppConfig`; drives FR37's switches live."""

    def __init__(
        self,
        config: AppConfig,
        *,
        switches: dict[str, bool] | None = None,
        on_switch: SwitchCallback | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(WINDOW_TITLE)
        self._on_switch = on_switch
        self._initial = config

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_matching_group(config))
        layout.addWidget(self._build_models_group(config))
        layout.addWidget(self._build_switches_group(switches or {}))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ---------- construction ----------

    def _build_matching_group(self, config: AppConfig) -> QGroupBox:
        group = QGroupBox("Matching")
        form = QFormLayout(group)

        self.sensitivity = QSlider(Qt.Orientation.Horizontal)
        self.sensitivity.setRange(to_slider(TAU_FLOOR_MIN), to_slider(TAU_FLOOR_MAX))
        self.sensitivity.setValue(to_slider(config.tau_floor))
        self.sensitivity_value = QLabel()
        self.sensitivity.valueChanged.connect(self._update_sensitivity_label)
        self._update_sensitivity_label(self.sensitivity.value())
        form.addRow("Sensitivity (τ_floor)", self.sensitivity)
        form.addRow("", self.sensitivity_value)

        self.tau_track = QSlider(Qt.Orientation.Horizontal)
        self.tau_track.setRange(to_slider(TAU_TRACK_MIN), to_slider(TAU_TRACK_MAX))
        self.tau_track.setValue(to_slider(config.tau_track))
        form.addRow("Progress-tracker threshold", self.tau_track)

        self.retention = QSpinBox()
        self.retention.setRange(RETENTION_NEVER, 3_650)
        self.retention.setSpecialValueText("Never delete")
        self.retention.setValue(
            RETENTION_NEVER if config.retention_days is None else config.retention_days
        )
        form.addRow("Keep transcripts for (days)", self.retention)
        return group

    def _build_models_group(self, config: AppConfig) -> QGroupBox:
        group = QGroupBox("Models and backend")
        form = QFormLayout(group)

        self.llm_model_id = QLineEdit(config.llm_model_id)
        form.addRow("LLM model id", self.llm_model_id)

        self.embed_model_id = QLineEdit(config.embed_model_id)
        form.addRow("Embedding model id", self.embed_model_id)
        note = QLabel("Changing the embedding model re-embeds every note on next start.")
        note.setWordWrap(True)
        note.setTextFormat(Qt.TextFormat.PlainText)
        form.addRow("", note)

        self.stt_backend = QComboBox()
        for choice in SttBackendChoice:
            self.stt_backend.addItem(choice.value, choice)
        self.stt_backend.setCurrentIndex(self.stt_backend.findData(config.stt_backend))
        form.addRow("Speech-to-text backend", self.stt_backend)
        return group

    def _build_switches_group(self, switches: dict[str, bool]) -> QGroupBox:
        """FR37: each independently switchable **while running**.

        Wired to fire on toggle rather than on OK. Waiting for the dialog to be accepted
        would mean a user killing cloud STT mid-interview has to find and press a button
        before anything happens — and FR37's verification is "toggle each mid-session;
        assert the pipeline adapts without a restart".
        """
        group = QGroupBox("Degradation switches (this session only)")
        box = QVBoxLayout(group)
        self.switches: dict[str, QCheckBox] = {}
        for name, label in SWITCH_LABELS.items():
            checkbox = QCheckBox(label)
            checkbox.setChecked(switches.get(name, False))
            checkbox.toggled.connect(
                lambda checked, switch=name: self._emit_switch(switch, checked)
            )
            box.addWidget(checkbox)
            self.switches[name] = checkbox
        return group

    # ---------- behaviour ----------

    def _update_sensitivity_label(self, value: int) -> None:
        self.sensitivity_value.setText(f"{from_slider(value):.2f}")

    def _emit_switch(self, name: str, value: bool) -> None:
        if self._on_switch is not None:
            self._on_switch(name, value)

    def config(self) -> AppConfig:
        """The edited settings.

        Constructs a new `AppConfig`, which validates in `__post_init__` — so a value the
        widgets should not have been able to produce raises here rather than being
        written to disk and clamped on the next load.
        """
        return AppConfig(
            tau_floor=from_slider(self.sensitivity.value()),
            tau_track=from_slider(self.tau_track.value()),
            llm_model_id=self.llm_model_id.text().strip() or self._initial.llm_model_id,
            embed_model_id=self.embed_model_id.text().strip() or self._initial.embed_model_id,
            stt_backend=self.stt_backend.currentData(),
            retention_days=(
                None if self.retention.value() == RETENTION_NEVER else self.retention.value()
            ),
        )
