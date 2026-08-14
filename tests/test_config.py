"""T9.2a — the `config.json` store (design §4).

Design §4 is normative here and says something different from `NotesStore`: a missing,
unparseable, or newer-versioned config is **replaced with defaults and the user is
notified**, because config holds nothing irreplaceable. The tests that matter are
therefore the ones proving the reset happens *and* that it is reported — a silent reset
is the actual failure mode, since the user's sensitivity reverts and they conclude the
matching is broken.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from interview_prep_recall.config import (
    CONFIG_SCHEMA_VERSION,
    TAU_TRACK_MAX,
    TAU_TRACK_MIN,
    AppConfig,
    ConfigError,
    ConfigLoadStatus,
    ConfigStore,
    SttBackendChoice,
    config_fields,
)
from interview_prep_recall.matching.prefilter import TAU_FLOOR_MAX, TAU_FLOOR_MIN


@pytest.fixture
def store(app_data: Path) -> ConfigStore:
    return ConfigStore(app_data)


# ---------- round trip ----------


def test_defaults_on_first_run(store: ConfigStore) -> None:
    config, status = store.load()

    assert status is ConfigLoadStatus.DEFAULTS_NO_FILE
    assert status.settings_were_lost is False, "first run is not a loss"
    assert config == AppConfig()


def test_save_then_load_round_trips_every_field(store: ConfigStore) -> None:
    """Every field, not a sample. A field added to the schema and forgotten in
    `to_dict`/`from_dict` would round-trip as its default and look like the user never
    changed it."""
    saved = AppConfig(
        tau_floor=0.45,
        tau_track=0.80,
        llm_model_id="claude-test-model",
        embed_model_id="some/other-embedder",
        stt_backend=SttBackendChoice.DEEPGRAM,
        retention_days=7,
    )
    store.save(saved)
    loaded, status = store.load()

    assert status is ConfigLoadStatus.LOADED
    assert loaded == saved
    for name in config_fields():
        assert getattr(loaded, name) == getattr(saved, name), name


def test_retention_none_round_trips(store: ConfigStore) -> None:
    """FR84's "never". `None` and "unset" must not collapse into each other."""
    store.save(AppConfig(retention_days=None))
    loaded, _ = store.load()
    assert loaded.retention_days is None


def test_saved_file_is_json_with_a_schema_version(store: ConfigStore) -> None:
    store.save(AppConfig())
    data = json.loads(store.path.read_text(encoding="utf-8"))
    assert data["schema_version"] == CONFIG_SCHEMA_VERSION


# ---------- recovery, and reporting it ----------


@pytest.mark.parametrize("payload", ["{not json", "[]", "null", '"a string"', ""])
def test_unreadable_config_resets_and_says_so(store: ConfigStore, payload: str) -> None:
    store.root.mkdir(parents=True, exist_ok=True)
    store.path.write_text(payload, encoding="utf-8")

    config, status = store.load()

    assert config == AppConfig()
    assert status is ConfigLoadStatus.DEFAULTS_UNREADABLE
    assert status.settings_were_lost is True


def test_config_from_a_newer_build_resets_rather_than_refusing(store: ConfigStore) -> None:
    """The opposite of `NotesStore`, deliberately (design §4).

    Notes are irreplaceable so an unknown format is refused; config is a slider position,
    so refusing to start would be the worse error.
    """
    store.root.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        json.dumps({"schema_version": CONFIG_SCHEMA_VERSION + 1, "tau_floor": 0.55}),
        encoding="utf-8",
    )

    config, status = store.load()

    assert config == AppConfig()
    assert status is ConfigLoadStatus.DEFAULTS_FROM_FUTURE
    assert status.settings_were_lost is True


def test_missing_schema_version_is_unreadable(store: ConfigStore) -> None:
    store.root.mkdir(parents=True, exist_ok=True)
    store.path.write_text(json.dumps({"tau_floor": 0.5}), encoding="utf-8")
    _config, status = store.load()
    assert status is ConfigLoadStatus.DEFAULTS_UNREADABLE


def test_boolean_schema_version_is_unreadable(store: ConfigStore) -> None:
    """`bool` subclasses `int`, so `true` would otherwise read as schema v1.

    The same mechanism was a live consent bypass in this codebase (PR #16). Here it would
    quietly accept a nonsense file as current.
    """
    store.root.mkdir(parents=True, exist_ok=True)
    store.path.write_text(json.dumps({"schema_version": True}), encoding="utf-8")
    _config, status = store.load()
    assert status is ConfigLoadStatus.DEFAULTS_UNREADABLE


# ---------- per-field tolerance ----------


def test_one_bad_field_does_not_discard_the_others(store: ConfigStore) -> None:
    """A hand-edited typo should cost one setting, not all of them."""
    store.root.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        json.dumps(
            {
                "schema_version": CONFIG_SCHEMA_VERSION,
                "tau_floor": "not a number",
                "llm_model_id": "kept-model",
                "retention_days": 5,
            }
        ),
        encoding="utf-8",
    )

    config, status = store.load()

    assert status is ConfigLoadStatus.LOADED
    assert config.tau_floor == AppConfig().tau_floor
    assert config.llm_model_id == "kept-model"
    assert config.retention_days == 5


@pytest.mark.parametrize(
    ("field_name", "stored", "expected_default"),
    [
        ("tau_floor", True, True),
        ("tau_track", False, True),
        ("llm_model_id", "", True),
        ("llm_model_id", "   ", True),
        ("embed_model_id", 42, True),
        ("stt_backend", "not-a-backend", True),
        ("retention_days", 0, True),
        ("retention_days", -3, True),
        ("retention_days", True, True),
    ],
)
def test_malformed_field_values_fall_back(
    store: ConfigStore, field_name: str, stored: Any, expected_default: bool
) -> None:
    """`bool` is called out separately for the numeric fields: it subclasses `int`, so
    `true` passes an `isinstance(..., (int, float))` check and would land as τ_floor 1.0
    — out of the FR52 range entirely."""
    store.root.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        json.dumps({"schema_version": CONFIG_SCHEMA_VERSION, field_name: stored}),
        encoding="utf-8",
    )

    config, _ = store.load()
    assert (getattr(config, field_name) == getattr(AppConfig(), field_name)) is expected_default


def test_out_of_range_thresholds_are_clamped_not_rejected(store: ConfigStore) -> None:
    store.root.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        json.dumps({"schema_version": CONFIG_SCHEMA_VERSION, "tau_floor": 0.95, "tau_track": 0.01}),
        encoding="utf-8",
    )

    config, _ = store.load()

    assert config.tau_floor == TAU_FLOOR_MAX
    assert config.tau_track == TAU_TRACK_MIN


# ---------- validation ----------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"tau_floor": TAU_FLOOR_MIN - 0.01},
        {"tau_floor": TAU_FLOOR_MAX + 0.01},
        {"tau_track": TAU_TRACK_MIN - 0.01},
        {"tau_track": TAU_TRACK_MAX + 0.01},
        {"llm_model_id": "  "},
        {"embed_model_id": ""},
        {"retention_days": 0},
    ],
)
def test_construction_rejects_out_of_range_values(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ConfigError):
        AppConfig(**kwargs)


def test_save_validates_a_mutated_config(store: ConfigStore) -> None:
    """Mutation bypasses `__post_init__`, so `save` has to check again.

    Otherwise a dialog bug writes an out-of-range value that the next load silently
    clamps, and the user's setting and the stored setting differ with nothing to see.
    """
    config = AppConfig()
    config.tau_floor = 0.99
    with pytest.raises(ConfigError):
        store.save(config)


def test_tau_degraded_is_not_a_setting() -> None:
    """Design §7 makes τ_degraded derived from τ_floor, and explains why: a fixed 0.55
    falls below τ_floor once sensitivity is raised past it, making the degraded gate
    unconditional and silently restoring the behaviour D-U3 overturns.

    Persisting it would hand that bug straight back, so its absence is a requirement.
    """
    assert "tau_degraded" not in config_fields()


# ---------- migration ----------


def test_migration_runs_in_sequence_and_backs_up_first(app_data: Path) -> None:
    """The v1 schema ships with no migrations, so the machinery is exercised against a
    synthetic one — otherwise its first real use would be the first time anyone's actual
    settings depended on it working (design §4's stated reason for the hook existing
    early)."""
    calls: list[int] = []

    def fake_v0_to_v1(data: dict[str, Any]) -> dict[str, Any]:
        calls.append(0)
        return {**data, "schema_version": 1, "llm_model_id": "migrated-model"}

    store = ConfigStore(app_data, migrations={0: fake_v0_to_v1})
    app_data.mkdir(parents=True, exist_ok=True)
    original = json.dumps({"schema_version": 0, "tau_floor": 0.5})
    store.path.write_text(original, encoding="utf-8")

    config, status = store.load()

    assert calls == [0]
    assert status is ConfigLoadStatus.MIGRATED
    assert config.llm_model_id == "migrated-model"
    assert config.tau_floor == 0.5, "migration must not lose the user's other settings"
    # Design §4: the pre-migration file is preserved as `.bak.1` before any write.
    assert store.backup_path.read_text(encoding="utf-8") == original
    assert json.loads(store.path.read_text(encoding="utf-8"))["schema_version"] == 1


def test_a_missing_migration_step_resets_rather_than_crashing(app_data: Path) -> None:
    store = ConfigStore(app_data, migrations={})
    app_data.mkdir(parents=True, exist_ok=True)
    store.path.write_text(json.dumps({"schema_version": 0}), encoding="utf-8")

    config, status = store.load()

    assert config == AppConfig()
    assert status is ConfigLoadStatus.DEFAULTS_UNREADABLE


def test_migrated_config_is_not_migrated_again(app_data: Path) -> None:
    calls: list[int] = []

    def fake(data: dict[str, Any]) -> dict[str, Any]:
        calls.append(0)
        return {**data, "schema_version": 1}

    store = ConfigStore(app_data, migrations={0: fake})
    app_data.mkdir(parents=True, exist_ok=True)
    store.path.write_text(json.dumps({"schema_version": 0}), encoding="utf-8")

    store.load()
    _config, status = store.load()

    assert calls == [0], "the migrated file was rewritten, so the second load is a plain load"
    assert status is ConfigLoadStatus.LOADED


# ---------- found in local review ----------


def test_backend_is_validated_like_every_other_field() -> None:
    """The one field with no validation until review.

    `SettingsDialog.config()` reads `QComboBox.currentData()`, which is `None` when the
    index is -1 — producing an `AppConfig` that validated cleanly and then crashed in
    `to_dict()` on `.value`.
    """
    with pytest.raises(ConfigError):
        AppConfig(stt_backend="deepgram")  # type: ignore[arg-type]
    with pytest.raises(ConfigError):
        AppConfig(stt_backend=None)  # type: ignore[arg-type]


def test_a_migration_that_raises_anything_resets_rather_than_propagating(
    app_data: Path,
) -> None:
    """`load()` is the startup path and promises never to raise.

    Only `ConfigError` was caught, so a migration failing on a `KeyError` — ordinary code
    failing in an ordinary way — meant the app refused to launch over a settings file.
    """

    def exploding(data: dict[str, Any]) -> dict[str, Any]:
        raise KeyError("some field the migration expected")

    store = ConfigStore(app_data, migrations={0: exploding})
    app_data.mkdir(parents=True, exist_ok=True)
    store.path.write_text(json.dumps({"schema_version": 0}), encoding="utf-8")

    config, status = store.load()

    assert config == AppConfig()
    assert status is ConfigLoadStatus.DEFAULTS_UNREADABLE


def test_a_migration_returning_a_non_dict_resets(app_data: Path) -> None:
    store = ConfigStore(app_data, migrations={0: lambda _data: ["not", "a", "dict"]})  # type: ignore[dict-item,return-value]
    app_data.mkdir(parents=True, exist_ok=True)
    store.path.write_text(json.dumps({"schema_version": 0}), encoding="utf-8")

    _config, status = store.load()
    assert status is ConfigLoadStatus.DEFAULTS_UNREADABLE


def test_an_unrepresentable_number_falls_back_rather_than_raising(store: ConfigStore) -> None:
    """JSON has no integer bound, so `999...9` parses to a Python int that `float()`
    cannot represent.

    `from_dict` runs outside `load`'s recovery block, so this raised `OverflowError` out
    of `Application.__post_init__` — the app refusing to start over a hand-edited config
    value, which is exactly what this module promises not to do.
    """
    store.root.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        f'{{"schema_version": {CONFIG_SCHEMA_VERSION}, "tau_floor": {"9" * 400}}}',
        encoding="utf-8",
    )

    config, status = store.load()

    assert config.tau_floor == AppConfig().tau_floor
    assert status is ConfigLoadStatus.LOADED


@pytest.mark.parametrize("literal", ["1e999", "-1e999", "NaN", "Infinity", "-Infinity"])
def test_nan_and_infinity_fall_back(store: ConfigStore, literal: str) -> None:
    """`json.loads` accepts these and `float()` keeps them.

    NaN is the dangerous one: it fails every comparison, so a clamp returns it unchanged
    and it then passes `validate`'s range check by failing both halves of it.
    """
    store.root.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        f'{{"schema_version": {CONFIG_SCHEMA_VERSION}, "tau_floor": {literal}}}',
        encoding="utf-8",
    )

    config, _status = store.load()

    assert config.tau_floor == AppConfig().tau_floor
