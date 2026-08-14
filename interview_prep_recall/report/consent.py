"""Consent re-acknowledgement for the report feature (T11.8 — FR85).

FR63's first-run disclosure was acknowledged against a materially weaker statement:
audio is intercepted in memory. This feature stores another person's words verbatim on
disk for thirty days and sends them to a third-party model.

Treating the first acknowledgement as covering the second would be this project's
recurring defect — a guarantee whose test passes while the property is broken — applied
to a person instead of a buffer. So the acknowledgement is **versioned**, and a version
bump invalidates the previous one rather than being assumed compatible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

REPORT_DISCLOSURE_VERSION = 1

DISCLOSURE_TEXT = (
    "Recording and analysing this interview stores a verbatim transcript of BOTH "
    "speakers on this computer, encrypted to your Windows account, for 30 days by "
    "default. Generating a report sends that entire transcript — including everything "
    "the interviewer said — to Anthropic's API for analysis.\n\n"
    "The other person has not agreed to this. Recording and interception law varies by "
    "jurisdiction and may require all-party consent, and many employers prohibit "
    "capture during interviews. You are responsible for compliance."
)


@dataclass
class ReportConsent:
    """Persisted separately from FR63's acknowledgement, deliberately.

    One combined record would make it impossible to tell which statement the user
    actually agreed to, and the two say materially different things.
    """

    path: Path

    def acknowledged_version(self) -> int | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            # Unreadable consent is absent consent. Failing open here would mean
            # inferring agreement from a corrupt file.
            return None
        if not isinstance(data, dict):
            # `json.loads("[]")` is a list, and `.get` on it raises `AttributeError` —
            # which the clause above does not catch, so a malformed file crashed rather
            # than failing closed.
            return None
        version = data.get("report_disclosure_version")
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
        """True when the disclosure must block. Covers never-acknowledged **and**
        acknowledged-at-an-older-version, since a bump means the text changed."""
        return self.acknowledged_version() != REPORT_DISCLOSURE_VERSION

    def acknowledge(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"report_disclosure_version": REPORT_DISCLOSURE_VERSION}),
            encoding="utf-8",
        )
