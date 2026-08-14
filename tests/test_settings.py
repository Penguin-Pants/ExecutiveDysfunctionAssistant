"""T9.2 — applying settings to running components, and the Qt surface.

FR52's verification is "move the control; assert τ_floor changes **and persists**", and
FR37's is "toggle each mid-session; assert the pipeline adapts **without a restart**".
Both are properties of the wiring, so most of this file needs no display server; the Qt
tests at the end cover the widget-to-value conversions, which is where the remaining
bugs live.
"""

from __future__ import annotations

import pytest

from interview_prep_recall.config import AppConfig, SttBackendChoice
from interview_prep_recall.settings import (
    RESTART_ONLY_FIELDS,
    AppliedSettings,
    SettingsApplier,
)


class FakePrefilter:
    def __init__(self) -> None:
        self.tau_floor = 0.35


class FakeTracker:
    def __init__(self) -> None:
        self.tau_track = 0.60


class FakeSelector:
    def __init__(self) -> None:
        self.model_id = "original-model"


class FakeSessions:
    def __init__(self) -> None:
        self.retention_days: int | None = 30


@pytest.fixture
def applier() -> SettingsApplier:
    return SettingsApplier(
        prefilter=FakePrefilter(),
        tracker=FakeTracker(),
        selector=FakeSelector(),
        sessions=FakeSessions(),
    )


# ---------- FR52 ----------


def test_sensitivity_reaches_the_running_prefilter(applier: SettingsApplier) -> None:
    result = applier.apply(AppConfig(), AppConfig(tau_floor=0.50))

    assert applier.prefilter.tau_floor == 0.50  # type: ignore[union-attr]
    assert "tau_floor" in result.applied
    assert result.restart_required is False


def test_tau_degraded_follows_tau_floor_without_being_a_setting() -> None:
    """Design §7: τ_degraded is `max(0.55, τ_floor + 0.10)`, derived so that raising
    sensitivity past 0.55 cannot make the degraded gate unconditional.

    Driven through the real `Prefilter` rather than a fake, because the point is that the
    derivation happens in the component the setting is pushed into.
    """
    from interview_prep_recall.matching.prefilter import tau_degraded_for

    assert tau_degraded_for(0.35) == pytest.approx(0.55)
    assert tau_degraded_for(0.60) == pytest.approx(0.70)
    assert tau_degraded_for(0.60) > 0.60, "the degraded gate must stay above tau_floor"


def test_unchanged_settings_are_not_reported_as_applied(applier: SettingsApplier) -> None:
    """Applying nothing must say nothing changed. A surface that reports every field as
    applied on every save makes "needs restart" meaningless."""
    result = applier.apply(AppConfig(), AppConfig())
    assert result == AppliedSettings(applied=frozenset(), needs_restart=frozenset())


# ---------- the rest of the live path ----------


def test_tracker_threshold_and_model_id_apply_live(applier: SettingsApplier) -> None:
    result = applier.apply(AppConfig(), AppConfig(tau_track=0.75, llm_model_id="claude-new-model"))

    assert applier.tracker.tau_track == 0.75  # type: ignore[union-attr]
    assert applier.selector.model_id == "claude-new-model"  # type: ignore[union-attr]
    assert result.applied == {"tau_track", "llm_model_id"}


def test_retention_reaches_the_session_store(applier: SettingsApplier) -> None:
    applier.apply(AppConfig(), AppConfig(retention_days=None))
    assert applier.sessions.retention_days is None  # type: ignore[union-attr]


# ---------- what cannot apply live ----------


def test_embedding_model_change_requires_a_restart(applier: SettingsApplier) -> None:
    """Every cached vector came from the old model. Reporting this as applied while the
    running index still uses the previous one is the recurring defect in this codebase —
    a guarantee whose test passes while the property is false."""
    result = applier.apply(AppConfig(), AppConfig(embed_model_id="different/model"))

    assert result.needs_restart == {"embed_model_id"}
    assert "embed_model_id" not in result.applied
    assert result.restart_required is True


def test_backend_change_requires_a_restart(applier: SettingsApplier) -> None:
    result = applier.apply(AppConfig(), AppConfig(stt_backend=SttBackendChoice.DEEPGRAM))
    assert result.needs_restart == {"stt_backend"}


def test_restart_only_fields_are_all_real_config_fields() -> None:
    """A typo in `RESTART_ONLY_FIELDS` would silently mean "applies live" for a setting
    that does not."""
    from interview_prep_recall.config import config_fields

    assert set(config_fields()) >= RESTART_ONLY_FIELDS


def test_applier_tolerates_absent_targets() -> None:
    """Usable before every component exists, without pretending it applied anything it
    could not reach."""
    result = SettingsApplier().apply(AppConfig(), AppConfig(tau_floor=0.5))
    assert "tau_floor" in result.applied


# ---------- Qt surface ----------

pytest.importorskip("PySide6", reason="Qt UI tests require the [ui] extra")

from PySide6.QtWidgets import QApplication  # noqa: E402

from interview_prep_recall.ui.settings import (  # noqa: E402
    RETENTION_NEVER,
    SWITCH_LABELS,
    SettingsDialog,
    from_slider,
    to_slider,
)


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_slider_conversion_round_trips_every_step() -> None:
    """`QSlider` is integer-only, so FR52's 0.20–0.60 range is scaled. A rounding
    mismatch between the write and read paths would move the user's setting a little
    every time the dialog is opened."""
    value = 20
    while value <= 60:
        assert to_slider(from_slider(value)) == value
        value += 1


def test_dialog_round_trips_a_config_untouched(qapp: QApplication) -> None:
    """Opening and accepting without touching anything must not change the settings.

    This is the test that catches the slider rounding bug in its real form: an equality
    check reporting a change on every open, rewriting the file each time.
    """
    config = AppConfig(
        tau_floor=0.45,
        tau_track=0.75,
        llm_model_id="model-x",
        embed_model_id="embed-y",
        stt_backend=SttBackendChoice.ELEVENLABS,
        retention_days=14,
    )
    dialog = SettingsDialog(config)
    assert dialog.config() == config


def test_moving_the_sensitivity_control_changes_tau_floor(qapp: QApplication) -> None:
    """FR52's verification, at the widget."""
    dialog = SettingsDialog(AppConfig(tau_floor=0.35))
    dialog.sensitivity.setValue(to_slider(0.50))
    assert dialog.config().tau_floor == pytest.approx(0.50)


def test_sensitivity_slider_cannot_leave_the_fr52_range(qapp: QApplication) -> None:
    from interview_prep_recall.matching.prefilter import TAU_FLOOR_MAX, TAU_FLOOR_MIN

    dialog = SettingsDialog(AppConfig())
    dialog.sensitivity.setValue(to_slider(0.99))
    assert dialog.config().tau_floor == pytest.approx(TAU_FLOOR_MAX)
    dialog.sensitivity.setValue(to_slider(0.01))
    assert dialog.config().tau_floor == pytest.approx(TAU_FLOOR_MIN)


def test_retention_never_maps_to_none(qapp: QApplication) -> None:
    dialog = SettingsDialog(AppConfig(retention_days=30))
    dialog.retention.setValue(RETENTION_NEVER)
    assert dialog.config().retention_days is None


def test_retention_none_shows_as_never(qapp: QApplication) -> None:
    dialog = SettingsDialog(AppConfig(retention_days=None))
    assert dialog.retention.value() == RETENTION_NEVER
    assert dialog.config().retention_days is None


def test_blank_model_id_falls_back_rather_than_raising(qapp: QApplication) -> None:
    """`AppConfig` rejects an empty model id, so the dialog must not be able to build
    one — clearing the box is a user action, not a crash."""
    dialog = SettingsDialog(AppConfig(llm_model_id="keep-me"))
    dialog.llm_model_id.setText("   ")
    assert dialog.config().llm_model_id == "keep-me"


# ---------- FR37 ----------


def test_switches_fire_immediately_not_on_accept(qapp: QApplication) -> None:
    """FR37: "toggle each mid-session; assert the pipeline adapts without a restart".

    Waiting for OK would mean a user killing cloud STT during an interview has to find
    and press a button before anything happens.
    """
    fired: list[tuple[str, bool]] = []
    dialog = SettingsDialog(
        AppConfig(),
        switches={"llm_matching": True, "cloud_stt": False, "progress_tracker": True},
        on_switch=lambda name, value: fired.append((name, value)),
    )

    dialog.switches["cloud_stt"].setChecked(True)
    assert fired == [("cloud_stt", True)]
    assert dialog.result() == 0, "no accept was needed"


def test_every_switch_is_independently_toggleable(qapp: QApplication) -> None:
    fired: list[tuple[str, bool]] = []
    dialog = SettingsDialog(
        AppConfig(),
        switches=dict.fromkeys(SWITCH_LABELS, False),
        on_switch=lambda name, value: fired.append((name, value)),
    )

    for name in SWITCH_LABELS:
        dialog.switches[name].setChecked(True)

    assert [name for name, _ in fired] == list(SWITCH_LABELS)
    assert all(value for _, value in fired)


def test_switch_names_match_the_real_degradation_switches() -> None:
    """`SessionManager.set_switch` validates against `DegradationSwitches` field names
    and raises on an unknown one, so a typo here is a dead toggle that raises at click
    time."""
    from dataclasses import fields

    from interview_prep_recall.session.manager import DegradationSwitches

    assert set(SWITCH_LABELS) == {f.name for f in fields(DegradationSwitches)}


def test_switches_are_not_part_of_the_persisted_config(qapp: QApplication) -> None:
    """FR37 switches are mid-session controls. Persisting them would leave cloud STT off
    next week for a user who turned it off during one bad network moment."""
    from interview_prep_recall.config import config_fields

    dialog = SettingsDialog(AppConfig(), switches=dict.fromkeys(SWITCH_LABELS, True))
    dialog.switches["cloud_stt"].setChecked(False)

    assert dialog.config() == AppConfig()
    assert not set(SWITCH_LABELS) & set(config_fields())
