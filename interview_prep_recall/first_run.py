"""First-run legal disclosure and its gate (T9.1 — FR63).

FR63 requires a disclosure that is **unavoidable on first run**, blocks until
acknowledged, and persists that acknowledgement. This module owns the acknowledgement
record and the gate; `ui/consent_dialog.py` owns the widget that presents it.

**Why the split.** "Unavoidable" is a property of a policy, not of a widget. A dialog
can be modal, frameless and un-closable and still fail FR63 if the caller treats a
dismissed dialog as agreement — which is the failure mode that actually happens, because
Qt's `QDialog.exec()` returns `Rejected` for Esc, the title-bar X and a programmatic
`reject()` alike, and `Rejected` is falsy in a way that reads as "user said no" only if
someone remembered to check. So the decision lives here, in a function with no Qt import,
and the widget is injected. The policy is then testable without a display server and the
widget is testable without a policy.

**Versioned, like `ReportConsent`.** FR85 taught this the hard way: the report feature
could not reuse FR63's acknowledgement because the statement had materially changed, and
a bare boolean could not express that. A boolean here would make the same mistake
available again the next time this text is edited — and legal text does get edited. So
the record stores a version and a bump invalidates it.

**Separate file from the report consent, deliberately.** They say different things and
`consent.json` is FR63's home in design §4. One combined record would make it impossible
to tell which statement the user actually agreed to.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

CONSENT_FILENAME = "consent.json"
"""Design §4's on-disk layout names this file for FR63."""

FIRST_RUN_DISCLOSURE_VERSION = 1

DISCLOSURE_TEXT = (
    "This application listens to both sides of your interview — your microphone and "
    "the audio your computer plays — and transcribes them in memory to find your prep "
    "notes.\n\n"
    "Before you continue, you need to know three things:\n\n"
    "1. Recording and interception law varies by jurisdiction, and some jurisdictions "
    "require the consent of every party to the conversation. The person interviewing "
    "you has not agreed to this and may not know about it.\n\n"
    "2. Many employers and interview platforms prohibit capture during interviews. "
    "Using this may breach their terms even where the law permits it.\n\n"
    "3. You are responsible for compliance. This software cannot determine what is "
    "lawful or permitted in your situation, and it does not try to."
)
"""FR63's three required points, in the order the requirement lists them.

Written as second person and plain sentences rather than legalese. A disclosure nobody
reads satisfies the letter of FR63 and none of its purpose, and this one is shown to
somebody who is minutes away from a stressful interview.
"""


class ConsentOutcome(Enum):
    """What the gate concluded. Three states, not two.

    `ALREADY_ACKNOWLEDGED` is kept distinct from `ACKNOWLEDGED` so a caller can tell a
    silent launch from one that just showed a legal notice — and so a test can prove the
    dialog is not shown twice, which is half of "persists".
    """

    ALREADY_ACKNOWLEDGED = "already_acknowledged"
    ACKNOWLEDGED = "acknowledged"
    DECLINED = "declined"

    @property
    def may_proceed(self) -> bool:
        """The single question the caller is asking.

        A property rather than `outcome != DECLINED` at each call site: an enum member
        added later would silently become permissive at every site that wrote the
        comparison out by hand.
        """
        return self is not ConsentOutcome.DECLINED


@dataclass
class FirstRunConsent:
    """The persisted acknowledgement record."""

    path: Path

    def acknowledged_version(self) -> int | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            # Unreadable consent is absent consent. Inferring agreement from a corrupt
            # file is the one direction of error that cannot be undone by asking again.
            return None
        if not isinstance(data, dict):
            return None
        version = data.get("first_run_disclosure_version")
        # `not isinstance(version, bool)` is not pedantry: `bool` subclasses `int`, so
        # `True` passes an `isinstance(..., int)` check *and* compares equal to version 1.
        # A record of `{"..._version": true}` would satisfy the gate and skip the
        # disclosure entirely — a malformed file failing **open**, in the one place this
        # module exists to fail closed.
        if isinstance(version, bool) or not isinstance(version, int):
            return None
        return version

    @property
    def required(self) -> bool:
        """True when the disclosure must block.

        Covers never-acknowledged **and** acknowledged-at-a-different-version. Not `<`:
        a record from a *newer* version — a downgraded install, a copied profile — was
        given against text this build cannot show, so it cannot stand in for agreement
        to the text this build has.
        """
        return self.acknowledged_version() != FIRST_RUN_DISCLOSURE_VERSION

    def acknowledge(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"first_run_disclosure_version": FIRST_RUN_DISCLOSURE_VERSION}),
            encoding="utf-8",
        )


DisclosurePresenter = Callable[[str], bool]
"""Shows the disclosure text and returns True only on explicit acknowledgement.

Injected so `require_consent` has no Qt import. Anything falling short of a deliberate
"I understand" — Esc, the window closing, a decline button, an exception the caller
turns into False — must return False.
"""


def require_consent(consent: FirstRunConsent, present: DisclosurePresenter) -> ConsentOutcome:
    """FR63's gate. Call before anything that captures audio.

    Acknowledgement is written **only** on an explicit True from the presenter, and the
    write happens here rather than inside the widget so that "what counts as agreement"
    is decided in one place instead of once per UI surface.
    """
    if not consent.required:
        return ConsentOutcome.ALREADY_ACKNOWLEDGED
    if not present(DISCLOSURE_TEXT):
        # Nothing is written. The next launch asks again, which is the correct behaviour
        # for a disclosure the user has not accepted — there is no "asked once" state.
        return ConsentOutcome.DECLINED
    consent.acknowledge()
    return ConsentOutcome.ACKNOWLEDGED
