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

from dataclasses import dataclass, field
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
    """What reached the running components, and what did not.

    Three outcomes, not two. An earlier version had only `applied` and `needs_restart`,
    and put a field in `applied` whenever it changed — including when the target it was
    meant to reach was absent. The docstring claimed the opposite ("without pretending it
    applied anything it could not reach") and a test asserted the buggy behaviour by
    name, which is this codebase's recurring defect reproduced in the module written to
    describe it honestly.
    """

    applied: frozenset[str]
    """Reached a live component. The component now holds this value."""

    needs_restart: frozenset[str]
    """Cannot take effect until the process restarts. **Reported on every save until it
    actually does** — see `SettingsApplier.running`."""

    persisted_only: frozenset[str]
    """Changed and saved, but the component it drives was not present to receive it."""

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

    running: AppConfig = field(default_factory=AppConfig)
    """**What the live components actually hold**, which is not the same as what is saved.

    This is the baseline every `apply()` diffs against, and it is the fix for a real bug:
    diffing against the last *persisted* config meant a restart-only change was reported
    once and then forgotten. Change `embed_model_id`, save — restart required. Save any
    unrelated setting before restarting and the field now compares equal to the persisted
    value, so `restart_required` goes false while the running index is still the old
    model. Reverting the field before restarting had the mirror-image bug, demanding a
    restart that was not needed.

    Only fields that genuinely reached a component are written back here, so a pending
    restart stays pending until the process actually restarts and rebuilds from the saved
    config.
    """

    prefilter: PrefilterTarget | None = None
    tracker: TrackerTarget | None = None
    selector: SelectorTarget | None = None
    sessions: RetentionTarget | None = None

    def apply(self, current: AppConfig) -> AppliedSettings:
        """Push `current` into the running components. Returns what happened.

        Diffs against `self.running` — the components' own state — rather than against a
        caller-supplied "previous". The components are the destination, and the whole
        question this answers is whether they match the config yet.
        """
        applied: set[str] = set()
        needs_restart: set[str] = set()
        persisted_only: set[str] = set()

        def push(name: str, target: object | None, attribute: str) -> None:
            if getattr(current, name) == getattr(self.running, name):
                return
            if target is None:
                # No component to receive it. Recording this as applied is what the
                # previous version did, and it made "applied" mean "changed", which is
                # the one thing the caller cannot use it for.
                persisted_only.add(name)
                return
            setattr(target, attribute, getattr(current, name))
            setattr(self.running, name, getattr(current, name))
            applied.add(name)

        # FR52's verification is literally "move the control; assert τ_floor changes and
        # persists". The setter validates the range, and `tau_degraded` follows from it
        # automatically — which is why that one is not a field.
        push("tau_floor", self.prefilter, "tau_floor")
        push("tau_track", self.tracker, "tau_track")
        # D-9: the model id is read per request, so a change is live.
        push("llm_model_id", self.selector, "model_id")
        # FR84: `SessionStore` reads this on each sweep.
        push("retention_days", self.sessions, "retention_days")

        for name in RESTART_ONLY_FIELDS:
            if getattr(current, name) != getattr(self.running, name):
                # `self.running` is deliberately **not** updated: the restart is still
                # outstanding, so the next save must report it again.
                needs_restart.add(name)

        return AppliedSettings(
            applied=frozenset(applied),
            needs_restart=frozenset(needs_restart),
            persisted_only=frozenset(persisted_only),
        )
