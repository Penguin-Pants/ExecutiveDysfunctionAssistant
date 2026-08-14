"""T9.1 — FR63's first-run disclosure gate, without Qt.

FR63's verification is "assert it appears on first run, blocks until acknowledged, and
that acknowledgement persists". Two of those three are properties of the *policy*, not
of the widget, and they are checked here against an injected presenter. The widget's own
half — that nothing short of a deliberate acknowledgement gets out of the dialog — is in
`test_consent_dialog.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from interview_prep_recall.first_run import (
    DISCLOSURE_TEXT,
    FIRST_RUN_DISCLOSURE_VERSION,
    ConsentOutcome,
    FirstRunConsent,
    require_consent,
)


class Presenter:
    """Records every showing and answers from a script."""

    def __init__(self, answer: bool = True) -> None:
        self.shown: list[str] = []
        self.answer = answer

    def __call__(self, text: str) -> bool:
        self.shown.append(text)
        return self.answer


@pytest.fixture
def consent(app_data: Path) -> FirstRunConsent:
    return FirstRunConsent(app_data / "consent.json")


# ---------- appears on first run ----------


def test_first_run_shows_the_disclosure(consent: FirstRunConsent) -> None:
    presenter = Presenter(answer=True)
    outcome = require_consent(consent, presenter)

    assert outcome is ConsentOutcome.ACKNOWLEDGED
    assert presenter.shown == [DISCLOSURE_TEXT]


def test_disclosure_covers_all_three_required_points() -> None:
    """FR63 names three points. A disclosure missing one is not this disclosure.

    Asserted on substance rather than exact wording — the text will be edited, and a test
    pinning the whole string would only ever be updated by copying the new value in,
    which checks nothing.
    """
    text = DISCLOSURE_TEXT.lower()
    assert "jurisdiction" in text and "consent of every party" in text
    assert "employers" in text and "prohibit" in text
    assert "you are responsible for compliance" in text


# ---------- blocks until acknowledged ----------


def test_declining_writes_nothing_and_refuses_to_proceed(consent: FirstRunConsent) -> None:
    presenter = Presenter(answer=False)
    outcome = require_consent(consent, presenter)

    assert outcome is ConsentOutcome.DECLINED
    assert outcome.may_proceed is False
    assert not consent.path.exists(), "a declined disclosure must leave no record"
    assert consent.required is True


def test_declining_asks_again_next_launch(consent: FirstRunConsent) -> None:
    """There is no "asked once" state. A disclosure the user has not accepted is a
    disclosure that must be shown again, or FR63's "unavoidable" lasts one launch."""
    first = Presenter(answer=False)
    require_consent(consent, first)
    second = Presenter(answer=True)
    outcome = require_consent(consent, second)

    assert second.shown == [DISCLOSURE_TEXT]
    assert outcome is ConsentOutcome.ACKNOWLEDGED


# ---------- persists ----------


def test_acknowledgement_persists_across_launches(consent: FirstRunConsent) -> None:
    require_consent(consent, Presenter(answer=True))

    reloaded = FirstRunConsent(consent.path)
    presenter = Presenter(answer=True)
    outcome = require_consent(reloaded, presenter)

    assert outcome is ConsentOutcome.ALREADY_ACKNOWLEDGED
    assert presenter.shown == [], "a legal notice shown every launch is a notice nobody reads"
    assert outcome.may_proceed is True


def test_acknowledged_version_is_recorded(consent: FirstRunConsent) -> None:
    require_consent(consent, Presenter(answer=True))
    assert consent.acknowledged_version() == FIRST_RUN_DISCLOSURE_VERSION


# ---------- the record itself ----------


def test_corrupt_record_is_absent_consent(consent: FirstRunConsent) -> None:
    """Inferring agreement from an unreadable file is the one error that cannot be
    undone by asking again."""
    consent.path.parent.mkdir(parents=True, exist_ok=True)
    consent.path.write_text("{not json", encoding="utf-8")

    assert consent.acknowledged_version() is None
    assert consent.required is True


@pytest.mark.parametrize("payload", ['{"first_run_disclosure_version": "1"}', "[]", "null", "{}"])
def test_malformed_payloads_are_absent_consent(consent: FirstRunConsent, payload: str) -> None:
    consent.path.parent.mkdir(parents=True, exist_ok=True)
    consent.path.write_text(payload, encoding="utf-8")
    assert consent.required is True


def test_a_different_version_invalidates_the_acknowledgement(consent: FirstRunConsent) -> None:
    """A bump means the text changed, so the old agreement was to something else.

    Checked in **both** directions. A record from a newer version — a downgraded install,
    a copied profile — was given against text this build cannot display, so it cannot
    stand in for agreement to the text this build shows. `!=`, not `<`.
    """
    consent.path.parent.mkdir(parents=True, exist_ok=True)
    for version in (FIRST_RUN_DISCLOSURE_VERSION - 1, FIRST_RUN_DISCLOSURE_VERSION + 1):
        consent.path.write_text(f'{{"first_run_disclosure_version": {version}}}', encoding="utf-8")
        assert consent.required is True, f"version {version} must not satisfy the gate"


def test_it_is_a_separate_file_from_the_report_consent(app_data: Path) -> None:
    """FR85's re-acknowledgement is a different statement about different data.

    One combined record would make it impossible to say which the user agreed to — and
    FR85 exists precisely because FR63's acknowledgement could not be reused.
    """
    from interview_prep_recall.report.consent import ReportConsent

    first_run = FirstRunConsent(app_data / "consent.json")
    report = ReportConsent(app_data / "report_consent.json")

    require_consent(first_run, Presenter(answer=True))

    assert first_run.required is False
    assert report.required is True, "FR63 consent must not satisfy FR85"


def test_outcome_may_proceed_is_derived_not_hand_written() -> None:
    assert ConsentOutcome.ACKNOWLEDGED.may_proceed is True
    assert ConsentOutcome.ALREADY_ACKNOWLEDGED.may_proceed is True
    assert ConsentOutcome.DECLINED.may_proceed is False


def test_presenter_is_not_called_when_consent_is_current(consent: FirstRunConsent) -> None:
    consent.acknowledge()
    presenter = Presenter(answer=False)
    assert require_consent(consent, presenter) is ConsentOutcome.ALREADY_ACKNOWLEDGED
    assert presenter.shown == []
