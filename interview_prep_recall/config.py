"""Persisted application settings — `config.json` (T9.2a — FR52, FR84, D-9, design §4).

**This module had no task.** T9.2 ("settings surface") is specified as *"sensitivity,
thresholds, model ID, backend choice all editable **and persisted**"*, and design §4
specifies `config.json` down to its migration semantics — but no task in `03-tasks.md`
owned building it. That is the T9.0 situation exactly: the plan named a dependency and
never gave it an ID, so nothing owned it and the work stayed invisible. Recorded as
**T9.2a** rather than quietly folded into T9.2, because the next person reading the task
list should see it.

**Config is not notes, and the difference decides the error handling.** `NotesStore`
refuses to parse a file from a newer schema — notes are irreplaceable, and guessing at a
format you do not understand is how they get destroyed. Config holds nothing that cannot
be reconstructed by moving a slider, so design §4 says the opposite: *"a missing,
unparseable, or newer-versioned file is replaced with defaults and the user is
notified."* Refusing to start because `config.json` is corrupt would be the wrong trade
in the other direction.

**"And the user is notified" is load-bearing, so it is not optional in the API.** `load()`
returns the outcome alongside the config and the caller cannot get one without the other.
A silent reset is the failure that actually happens here: the user's sensitivity setting
reverts, they do not know it, and they conclude the matching is broken. Half of what this
module owes them is telling them when it threw their settings away.

**Thresholds that are *derived* are deliberately absent from the schema.** `τ_degraded` is
`max(0.55, τ_floor + 0.10)` and design §7 explains at length why it must not be
independent: a fixed 0.55 falls below `τ_floor` as soon as the user raises sensitivity
past it, which makes the degraded gate unconditional and silently restores the behaviour
D-U3 exists to overturn. Persisting it as a field would hand that bug straight back, so
it is computed by `Prefilter` and never stored.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field, fields
from enum import Enum
from pathlib import Path
from typing import Any

from interview_prep_recall.matching.prefilter import (
    TAU_FLOOR_DEFAULT,
    TAU_FLOOR_MAX,
    TAU_FLOOR_MIN,
)
from interview_prep_recall.matching.selector import DEFAULT_MODEL_ID
from interview_prep_recall.notes.index import DEFAULT_EMBED_MODEL_ID
from interview_prep_recall.report.store import RETENTION_DAYS_DEFAULT
from interview_prep_recall.tracker.progress import TAU_TRACK

CONFIG_FILENAME = "config.json"
CONFIG_SCHEMA_VERSION = 1

TAU_TRACK_MIN = 0.30
TAU_TRACK_MAX = 0.95
"""Wider than τ_floor's range and not user-exposed as a slider.

Design §7: τ_track is deliberately stricter than τ_floor because a false "you covered
that" is worse than a missed tick — the user acts on it by *not* saying something. The
bounds exist so a hand-edited config cannot set it to 0.0 and turn the checklist into a
green wall.
"""


class SttBackendChoice(Enum):
    """Design §4's "backend choice". FR18 makes local the default."""

    LOCAL = "local"
    DEEPGRAM = "deepgram"
    ELEVENLABS = "elevenlabs"


class ConfigLoadStatus(Enum):
    """Why the returned config is what it is.

    Returned rather than logged. Design §4 requires the user be *notified* when their
    settings are replaced, and a status the caller has to unpack is the only version of
    that requirement a caller cannot forget to honour.
    """

    LOADED = "loaded"
    DEFAULTS_NO_FILE = "defaults_no_file"
    """First run. Not an error and must not be reported as one."""

    DEFAULTS_UNREADABLE = "defaults_unreadable"
    """Corrupt, unparseable, or not an object. Settings were lost."""

    DEFAULTS_FROM_FUTURE = "defaults_from_future"
    """Written by a newer build. Settings were lost — see the module docstring for why
    this resets rather than refusing, unlike `NotesStore`."""

    MIGRATED = "migrated"

    @property
    def settings_were_lost(self) -> bool:
        """The question a notification actually needs answered.

        First run and a clean load both produce defaults or values with nothing lost;
        only these two mean the user had settings and no longer does.
        """
        return self in {
            ConfigLoadStatus.DEFAULTS_UNREADABLE,
            ConfigLoadStatus.DEFAULTS_FROM_FUTURE,
        }


class ConfigError(ValueError):
    pass


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


@dataclass
class AppConfig:
    """Everything design §4 assigns to `config.json`.

    Overlay geometry and the active note set live in `QSettings` instead (design §4's
    settings split) and are deliberately not here.
    """

    tau_floor: float = TAU_FLOOR_DEFAULT
    """FR52's sensitivity control."""

    tau_track: float = TAU_TRACK
    llm_model_id: str = DEFAULT_MODEL_ID
    """D-9: a model id is configuration, not a constant. Hard-coding it into a
    PyInstaller exe means a deprecation requires a rebuild."""

    embed_model_id: str = DEFAULT_EMBED_MODEL_ID
    """Changing this invalidates every cached embedding. `EmbeddingIndex` already
    detects the mismatch and re-embeds (BC-1), so the setting is safe to change — but it
    is not *free*, and the settings surface says so."""

    stt_backend: SttBackendChoice = SttBackendChoice.LOCAL
    retention_days: int | None = RETENTION_DAYS_DEFAULT
    """FR84. `None` means never delete."""

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Raise on anything out of range. Called on construction and before every save.

        Validation on *save* as well as load is the half that matters: a settings dialog
        that writes an out-of-range τ_floor produces a file that the next load silently
        clamps, so the user's setting and the stored setting disagree with no way to see
        it.
        """
        if not TAU_FLOOR_MIN <= self.tau_floor <= TAU_FLOOR_MAX:
            raise ConfigError(
                f"tau_floor {self.tau_floor} outside the FR52 control range "
                f"[{TAU_FLOOR_MIN}, {TAU_FLOOR_MAX}]"
            )
        if not TAU_TRACK_MIN <= self.tau_track <= TAU_TRACK_MAX:
            raise ConfigError(
                f"tau_track {self.tau_track} outside [{TAU_TRACK_MIN}, {TAU_TRACK_MAX}]"
            )
        if not self.llm_model_id.strip():
            raise ConfigError("llm_model_id must not be empty")
        if not self.embed_model_id.strip():
            raise ConfigError("embed_model_id must not be empty")
        if not isinstance(self.stt_backend, SttBackendChoice):
            # The only field with no validation until review. `SettingsDialog.config()`
            # reads `QComboBox.currentData()`, which is `None` when the index is -1 — an
            # `AppConfig` that validated cleanly and then crashed in `to_dict()` on
            # `.value`.
            raise ConfigError(f"stt_backend must be a SttBackendChoice, got {self.stt_backend!r}")
        if self.retention_days is not None and self.retention_days < 1:
            raise ConfigError("retention_days must be >= 1, or None for never")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CONFIG_SCHEMA_VERSION,
            "tau_floor": self.tau_floor,
            "tau_track": self.tau_track,
            "llm_model_id": self.llm_model_id,
            "embed_model_id": self.embed_model_id,
            "stt_backend": self.stt_backend.value,
            "retention_days": self.retention_days,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppConfig:
        """Build from a parsed payload, **field by field**.

        Every value is checked for type and range, and anything wrong falls back to that
        field's default rather than failing the whole load. A single hand-edited typo
        should cost one setting, not all of them.

        `bool` is rejected explicitly for the numeric fields: `bool` subclasses `int`, so
        `true` passes an `isinstance(..., (int, float))` check and would be read as
        τ_floor 1.0. That exact mechanism was a live consent bypass in this codebase
        (PR #16), which is reason enough to write it out here rather than trust the
        check to read correctly.
        """
        defaults = cls()
        return cls(
            tau_floor=_number(
                data.get("tau_floor"), defaults.tau_floor, TAU_FLOOR_MIN, TAU_FLOOR_MAX
            ),
            tau_track=_number(
                data.get("tau_track"), defaults.tau_track, TAU_TRACK_MIN, TAU_TRACK_MAX
            ),
            llm_model_id=_text(data.get("llm_model_id"), defaults.llm_model_id),
            embed_model_id=_text(data.get("embed_model_id"), defaults.embed_model_id),
            stt_backend=_backend(data.get("stt_backend"), defaults.stt_backend),
            retention_days=_retention(data.get("retention_days"), defaults.retention_days),
        )


def _number(value: Any, default: float, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    try:
        number = float(value)
    except (OverflowError, ValueError):
        # JSON has no integer bound, so a hand-edited `999...9` parses to a Python int
        # that `float()` cannot represent. `from_dict` runs outside `load`'s recovery
        # block, so this raised out of `Application.__post_init__` — the app refusing to
        # start over a config value, which is precisely what this module promises not to
        # do.
        return default
    if number != number or number in (float("inf"), float("-inf")):
        # NaN and infinity survive `float()` (JSON's `1e999` parses to `inf`). NaN fails
        # every comparison, so a clamp would return it unchanged and it would then pass
        # `validate`'s range check by failing both halves of it.
        return default
    return _clamp(number, low, high)


def _text(value: Any, default: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return default
    return value


def _backend(value: Any, default: SttBackendChoice) -> SttBackendChoice:
    if not isinstance(value, str):
        return default
    try:
        return SttBackendChoice(value)
    except ValueError:
        return default


def _retention(value: Any, default: int | None) -> int | None:
    if value is None:
        return None  # FR84's "never", and a legitimate stored value.
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return default
    return value


Migration = Callable[[dict[str, Any]], dict[str, Any]]

MIGRATIONS: dict[int, Migration] = {}
"""Forward-only, applied in sequence: `MIGRATIONS[n]` takes v`n` to v`n+1`.

Empty at v1 by design (§4): *"v1 ships with none, but the hook exists from the start —
retrofitting a migration path onto a format already in users' hands is how data gets
lost."* The mechanism is tested against a synthetic migration so the hook is known to
work before anything depends on it.
"""


@dataclass
class ConfigStore:
    root: Path
    migrations: dict[int, Migration] = field(default_factory=lambda: MIGRATIONS)
    """Injectable so the migration machinery is testable while `MIGRATIONS` is empty.

    Without this the sequencing, the `.bak.1` write and the version bump would all be
    unexercised until v2 — that is, the first time anyone's real settings depended on
    them working."""

    @property
    def path(self) -> Path:
        return self.root / CONFIG_FILENAME

    @property
    def backup_path(self) -> Path:
        return self.root / f"{CONFIG_FILENAME}.bak.1"

    # ---------- load ----------

    def load(self) -> tuple[AppConfig, ConfigLoadStatus]:
        """Read the config. Never raises; always returns something usable.

        The status is returned rather than logged because design §4 requires the user be
        notified when settings are replaced, and a caller cannot unpack the config
        without also receiving the reason.
        """
        if not self.path.exists():
            return AppConfig(), ConfigLoadStatus.DEFAULTS_NO_FILE

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return AppConfig(), ConfigLoadStatus.DEFAULTS_UNREADABLE
        if not isinstance(raw, dict):
            return AppConfig(), ConfigLoadStatus.DEFAULTS_UNREADABLE

        version = raw.get("schema_version")
        if isinstance(version, bool) or not isinstance(version, int):
            return AppConfig(), ConfigLoadStatus.DEFAULTS_UNREADABLE
        if version > CONFIG_SCHEMA_VERSION:
            # Reset, not refuse — the opposite of `NotesStore`, and deliberately so. See
            # the module docstring.
            return AppConfig(), ConfigLoadStatus.DEFAULTS_FROM_FUTURE

        migrated = version < CONFIG_SCHEMA_VERSION
        if migrated:
            try:
                raw = self._migrate(raw, version)
            except Exception:  # noqa: BLE001 — see below
                # Broad on purpose. `load()` is the startup path and promises never to
                # raise; a migration function is ordinary code that can fail on a
                # `KeyError` as easily as on a `ConfigError`, and refusing to launch over
                # an unmigratable settings file is exactly the trade design §4 rejects.
                return AppConfig(), ConfigLoadStatus.DEFAULTS_UNREADABLE

        if not isinstance(raw, dict):
            # A migration that returned something else.
            return AppConfig(), ConfigLoadStatus.DEFAULTS_UNREADABLE
        config = AppConfig.from_dict(raw)
        if migrated:
            # The pre-migration file is preserved **before** the migrated form is
            # written (design §4).
            self._backup()
            self.save(config)
            return config, ConfigLoadStatus.MIGRATED
        return config, ConfigLoadStatus.LOADED

    def _migrate(self, data: dict[str, Any], version: int) -> dict[str, Any]:
        while version < CONFIG_SCHEMA_VERSION:
            migrate = self.migrations.get(version)
            if migrate is None:
                raise ConfigError(f"no migration from config schema v{version}")
            data = migrate(data)
            version += 1
        return data

    def _backup(self) -> None:
        if self.path.exists():
            self.backup_path.write_bytes(self.path.read_bytes())

    # ---------- save ----------

    def save(self, config: AppConfig) -> None:
        """Validate, then write atomically.

        Validated here as well as on construction: a caller that mutated a field after
        building the object would otherwise persist a value the next load has to clamp,
        leaving the stored setting and the user's intent silently different.
        """
        config.validate()
        self.root.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(config.to_dict(), indent=2, ensure_ascii=False)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)


def config_fields() -> tuple[str, ...]:
    """Field names in declaration order. Used by the settings surface so a new setting
    cannot be added to the schema and forgotten in the UI."""
    return tuple(f.name for f in fields(AppConfig))
