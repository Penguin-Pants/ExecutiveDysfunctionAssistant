"""The startup sequence (T9.6 — FR63, FR38, design §4).

**This task did not exist.** T9.1a, T9.2b and T9.4 all record the same blocker in
different words — "no production caller", "no main window", "needs an entry point" — and
no task owned building one. That is the third time in this plan that a named prerequisite
had no ID (after T9.0's composition root and T9.2a's config store), so it is recorded as
**T9.6** rather than absorbed into whichever task tripped over it first.

Qt-free, like `app.py` and for the same reason: the *order* of startup is the part that
carries guarantees, and it should be checkable on a machine that cannot open a window.
`__main__.py` supplies the real presenter and notifier.

**The order is the requirement.** Three things must happen before anything else, and each
of them is a rule this codebase already learned the hard way:

1. **Consent first, and nothing is constructed until it passes.** FR63 says the
   disclosure is unavoidable. A gate that runs after the composition root has created
   directories and loaded the user's notes is a gate that ran too late — and "declined"
   would then leave state behind from a session the user refused.
2. **A config reset is reported.** Design §4 requires the user be told when their
   settings are replaced. `ConfigLoadStatus.settings_were_lost` existed with **no
   production consumer** until this module — the fifth-and-sixth instance of D-20 in this
   codebase, and one I introduced myself while writing that the notification was
   load-bearing.
3. **Preflight runs automatically** (FR38), not when the user remembers. On a machine
   with no audio devices it blocks, which is the correct answer and the honest one: the
   session cannot start, and `Preflight` already models exactly that.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from interview_prep_recall.app import Application
from interview_prep_recall.config import SttBackendChoice
from interview_prep_recall.first_run import (
    CONSENT_FILENAME,
    ConsentOutcome,
    DisclosurePresenter,
    FirstRunConsent,
    require_consent,
)
from interview_prep_recall.session.preflight import Preflight, PreflightReport, Probe

CONFIG_RESET_NOTICE = (
    "Your settings could not be read and have been reset to their defaults. "
    "Check them in Settings before you start."
)
"""Design §4's "and the user is notified", in words a user can act on."""

RETENTION_SWEEP_NOTICE = (
    "{count} stored interview(s) passed the retention window and were deleted. "
    "Change how long sessions are kept in Settings."
)
"""FR84 deletes on a timer the user did not press, so the deletion is **stated**.

Silent automatic deletion of a transcript the user might have been about to read is the
kind of thing that reads as data loss, and they have no way to tell the difference."""


class StartupOutcome(Enum):
    READY = "ready"
    """Consent given, config loaded, preflight clear enough to start a session."""

    CONSENT_DECLINED = "consent_declined"
    """FR63's disclosure was refused. **Nothing was constructed.**"""

    NOT_READY = "not_ready"
    """Preflight found a blocking failure (FR38). The app runs; a session cannot start."""

    @property
    def may_run(self) -> bool:
        """Whether the application should stay open at all.

        `NOT_READY` still runs — the user needs to reach Settings and the setup wizard to
        *fix* what is blocking them, and an app that quits on a failed readiness check is
        an app they cannot repair.
        """
        return self is not StartupOutcome.CONSENT_DECLINED


@dataclass(frozen=True)
class StartupResult:
    outcome: StartupOutcome
    application: Application | None = None
    preflight: PreflightReport | None = None
    notices: tuple[str, ...] = field(default_factory=tuple)
    """Things the user must be told, in order. Returned rather than shown, so the
    sequence is testable without a UI and the caller decides how to present them."""


ApplicationFactory = Callable[[Path], Application]


def start(
    root: Path,
    *,
    present: DisclosurePresenter,
    build_application: ApplicationFactory,
    probes: Mapping[str, Probe] | None = None,
) -> StartupResult:
    """Run the startup sequence. Never raises for an ordinary bad state.

    `build_application` is injected rather than constructed here because `Application`
    needs an embedder, a model client and a cipher, and which ones depend on the platform
    and on whether this is a test. The *sequence* does not.
    """
    consent = FirstRunConsent(root / CONSENT_FILENAME)
    if require_consent(consent, present) is ConsentOutcome.DECLINED:
        # Return before building anything. FR63's disclosure covers listening to an
        # interview; a refusal must not leave behind the directories, indexes and caches
        # of a session the user declined to have.
        return StartupResult(outcome=StartupOutcome.CONSENT_DECLINED)

    application = build_application(root)

    notices: list[str] = []
    if application.config_status.settings_were_lost:
        notices.append(CONFIG_RESET_NOTICE)

    # FR84's launch-time sweep. `Application.sweep_retention` carried "no production
    # caller yet — the entry point owns this, and there is no entry point until the UI
    # lands" in its docstring; the UI has landed, and T11.10's session list now *states*
    # the 30-day default to the user. A promise of automatic deletion with nothing
    # deleting is worse than no promise, and it is the promise this codebase keeps
    # making by hand (D-20). Found by review on PR #24.
    #
    # After the config load, so a user whose retention setting was reset is swept on
    # their **restored default** rather than on a value that failed to parse; before
    # preflight, so the list a user opens has already had expired sessions removed.
    swept = application.sweep_retention()
    if swept:
        notices.append(RETENTION_SWEEP_NOTICE.format(count=len(swept)))

    report = run_preflight(application, probes)
    outcome = StartupOutcome.NOT_READY if report.blocked else StartupOutcome.READY
    return StartupResult(
        outcome=outcome,
        application=application,
        preflight=report,
        notices=tuple(notices),
    )


def run_preflight(
    application: Application, probes: Mapping[str, Probe] | None = None
) -> PreflightReport:
    """FR38's readiness check. Public because it must be **re-run**, not just run once.

    Which checks apply depends on the configured backend, so a report taken at process
    start goes stale the moment the user switches to a cloud backend in Settings — they
    would see the original "ready" without the API key or service ever being validated.
    Found by review on PR #18.

    FR38 says "at session start", and the *session*-start path
    (`SessionManager.request_start` / `preflight_result`) is still unwired because nothing
    can start a session without capture. That wiring belongs to M1; this function is what
    it will call.
    """
    preflight = Preflight(
        probes or {},
        cloud_enabled=application.config.stt_backend is not SttBackendChoice.LOCAL,
        ring=application.ring,
    )
    return preflight.run()
