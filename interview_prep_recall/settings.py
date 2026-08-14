"""Applying settings to running components (T9.2 — FR52, FR37, D-9).

The Qt dialog collects values; this decides what they *do*. Split for the same reason
`first_run.py` is split from `ui/consent_dialog.py`: "the change takes effect without a
restart" is a property of the wiring, not of the widget, and it is checkable without a
display server.

**Two categories of setting, and conflating them is the bug this module is shaped to
avoid.**

* **Persisted config** (`config.json`): τ_floor, τ_track, model ids, backend choice,
  retention. Survives restart. Some of it applies live, some cannot.
* **Degradation switches** (FR37): LLM matching, cloud STT, progress tracker. These are
  *mid-session* controls that must flip while running and must **not** persist — a user
  who turned off cloud STT because a network died should not find it still off next
  week, having forgotten. `SessionManager` already owns them and is the only writer.

**What applies live and what does not is stated, not discovered.** τ_floor reaches the
running prefilter immediately (FR52 requires it). `embed_model_id` cannot: every cached
vector was produced by the old model, and the index has to be rebuilt. Reporting a model
change as applied when the running index is still using the previous one would be this
codebase's recurring defect — a guarantee whose test passes while the property is false —
so `apply()` reports which changes need a restart rather than pretending.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from interview_prep_recall.config import AppConfig


class PrefilterTarget(Protocol):
    """The slice of `Prefilter` FR52 drives."""

    tau_floor: float


class TrackerTarget(Protocol):
    tau_track: float


class SelectorTarget(Protocol):
    model_id: str


class RetentionTarget(Protocol):
    retention_days: int | None


@dataclass(frozen=True)
class AppliedSettings:
    """What actually changed, and what the user still has to restart for."""

    applied: frozenset[str]
    needs_restart: frozenset[str]

    @property
    def restart_required(self) -> bool:
        return bool(self.needs_restart)


RESTART_ONLY_FIELDS = frozenset({"embed_model_id", "stt_backend"})
"""Settings that cannot take effect on a running session.

* `embed_model_id` — every cached vector came from the old model. `EmbeddingIndex`
  detects the mismatch and re-embeds on next build (BC-1), but the *running* index is
  still the old one.
* `stt_backend` — the audio streams are already open against a live backend; swapping it
  underneath them is a capture-restart, not a setting.

Named as a constant so adding a field to `AppConfig` forces a decision about which side
it falls on, rather than defaulting to "claims to apply live".
"""


@dataclass
class SettingsApplier:
    """Pushes an `AppConfig` into the live object graph.

    Targets are optional so this is usable before every component exists — and typed as
    Protocols so the tests drive it without building a real pipeline.
    """

    prefilter: PrefilterTarget | None = None
    tracker: TrackerTarget | None = None
    selector: SelectorTarget | None = None
    sessions: RetentionTarget | None = None

    def apply(self, previous: AppConfig, current: AppConfig) -> AppliedSettings:
        """Push `current` into the running components. Returns what happened.

        Takes the previous config rather than diffing against the live objects: the
        objects are the *destination*, and reading them back to decide what changed
        would report success for a write that never landed.
        """
        applied: set[str] = set()
        needs_restart: set[str] = set()

        if current.tau_floor != previous.tau_floor:
            # FR52's verification is literally "move the control; assert τ_floor changes
            # and persists". The setter validates the range and `tau_degraded` follows
            # from it automatically, which is why that one is not a field.
            if self.prefilter is not None:
                self.prefilter.tau_floor = current.tau_floor
            applied.add("tau_floor")

        if current.tau_track != previous.tau_track:
            if self.tracker is not None:
                self.tracker.tau_track = current.tau_track
            applied.add("tau_track")

        if current.llm_model_id != previous.llm_model_id:
            # D-9: the model id is read per request, so a change is live.
            if self.selector is not None:
                self.selector.model_id = current.llm_model_id
            applied.add("llm_model_id")

        for name in RESTART_ONLY_FIELDS:
            if getattr(current, name) != getattr(previous, name):
                needs_restart.add(name)

        if current.retention_days != previous.retention_days:
            # FR84. `SessionStore` reads this on each sweep, so pushing it is enough —
            # no restart, and no rescheduling of anything.
            if self.sessions is not None:
                self.sessions.retention_days = current.retention_days
            applied.add("retention_days")

        return AppliedSettings(applied=frozenset(applied), needs_restart=frozenset(needs_restart))
