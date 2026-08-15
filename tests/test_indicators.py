"""T5.7 — capture, egress, health and capture-exclusion indicators (FR7, FR14a, FR20, FR35).

FR35's hard requirement is not that any one state renders; it is that **every state in
design §7 renders distinctly**, and that "nothing matched" is distinguishable from every
failure. Distinctness is a property of the whole set, so the load-carrying test here
drives every state design §7 names and asserts the renderings are pairwise different —
a per-state assertion cannot express it and would pass with two states painted identically.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="Qt UI tests require the [ui] extra")

from PySide6.QtWidgets import QApplication  # noqa: E402

from interview_prep_recall.session.health import (  # noqa: E402
    FALLING_BEHIND_S,
    NO_AUDIO_AFTER_S,
    Egress,
    Health,
    MatchingStatus,
    Status,
)
from interview_prep_recall.ui.indicators import (  # noqa: E402
    ACCENT_GRADIENT,
    AMBER_500,
    CHIP_IDLE,
    GREEN_500,
    NOMINAL_TEXT,
    RED_500,
    CaptureIndicator,
    EgressIndicator,
    HealthStrip,
    IndicatorBar,
    severity_of,
)
from interview_prep_recall.ui.overlay import (  # noqa: E402
    NO_MATCH_TEXT,
    OverlayPanel,
    no_match_view,
)


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


CAPTURING = Health(loopback=Status.OK, mic=Status.OK, matching=MatchingStatus.OK)
"""Design §7's `capturing`: everything nominal, audio flowing."""

DESIGN_7_STATES: dict[str, Health] = {
    "capturing": CAPTURING,
    "no audio detected": CAPTURING.with_(silence_s=NO_AUDIO_AFTER_S + 1),
    "STT degraded": CAPTURING.with_(stt_interviewer=Status.DEGRADED),
    "STT unavailable (interviewer)": CAPTURING.with_(stt_interviewer=Status.FAILED),
    "STT unavailable (mic)": CAPTURING.with_(stt_user=Status.FAILED),
    "matching: local-only": CAPTURING.with_(matching=MatchingStatus.LOCAL_ONLY),
    "matching unavailable": CAPTURING.with_(matching=MatchingStatus.FAILED),
    "falling behind": CAPTURING.with_(lag=FALLING_BEHIND_S + 1),
    "audio lost": CAPTURING.with_(loopback=Status.FAILED),
    "NOT hidden from screen share": CAPTURING.with_(capture_excluded=False),
    "not capturing": Health(),
}
"""Every derived indicator state design §7 names, plus the two base states FR7 and FR35
are defined against. Keyed by the design's own wording so a state that gets renamed in
§7 and not here is visible as a mismatch rather than as a silently missing case."""


# ---------- FR35: distinctness is a property of the set ----------


def test_every_design_7_state_renders_distinctly(qapp: QApplication) -> None:
    bar = IndicatorBar()
    seen: dict[tuple[str, ...], str] = {}

    for name, health in DESIGN_7_STATES.items():
        bar.update_health(health)
        rendering = bar.visual_state()
        assert rendering not in seen, f"{name!r} renders identically to {seen[rendering]!r}"
        seen[rendering] = name


def test_no_match_is_distinct_from_every_failure_state(qapp: QApplication) -> None:
    """OB-1, the worst observability property this system could have.

    The two signals are structurally separate: nothing matching is a *content* state on
    the panel, and no health state can produce it. So the check is that the panel says so
    while the bar stays nominal — not that two colours differ.
    """
    panel = OverlayPanel()
    panel.show_snippet(no_match_view(), now=0.0)
    panel.update_health(CAPTURING)

    assert panel.headline.text() == NO_MATCH_TEXT
    assert CAPTURING.nominal is True
    assert panel.indicators.health.rows == (f"✓ {NOMINAL_TEXT}",)

    for name, health in DESIGN_7_STATES.items():
        if health.nominal:
            continue
        panel.update_health(health)
        assert panel.indicators.health.rows != (f"✓ {NOMINAL_TEXT}",), name


def test_nominal_health_is_stated_not_blank(qapp: QApplication) -> None:
    """A blank strip is what a crashed strip also looks like."""
    strip = HealthStrip()
    strip.set_health(CAPTURING)

    assert strip.rows == (f"✓ {NOMINAL_TEXT}",)
    assert GREEN_500 in strip.visual_state()[1]


def test_health_rows_come_from_the_health_model_unchanged(qapp: QApplication) -> None:
    """Two places deciding what "degraded" means is how they come to disagree."""
    health = CAPTURING.with_(stt_interviewer=Status.FAILED, lag=FALLING_BEHIND_S + 1)
    strip = HealthStrip()

    strip.set_health(health)

    assert [row.split(" ", 1)[1] for row in strip.rows] == health.indicators()


def test_a_recovered_state_clears_the_rows(qapp: QApplication) -> None:
    """The rows are reused across updates, so a shrinking list must not leave stale text
    on screen — a warning that outlives its cause is worse than no warning."""
    strip = HealthStrip()
    strip.set_health(CAPTURING.with_(stt_interviewer=Status.FAILED, lag=FALLING_BEHIND_S + 1))

    strip.set_health(CAPTURING)

    assert strip.rows == (f"✓ {NOMINAL_TEXT}",)


def test_severity_separates_broken_from_degraded() -> None:
    """Painting every degradation red trains the user to ignore the colour that matters."""
    assert severity_of("audio lost") == RED_500
    assert severity_of("STT unavailable (mic)") == RED_500
    assert severity_of("matching unavailable") == RED_500
    assert severity_of("NOT hidden from screen share") == RED_500
    assert severity_of("STT degraded") == AMBER_500
    assert severity_of("matching: local-only") == AMBER_500
    assert severity_of("falling behind — 3s") == AMBER_500


def test_every_health_indicator_string_gets_a_severity() -> None:
    """`severity_of` matches on prefixes, so a §7 state renamed upstream would quietly
    fall through to amber. This asserts each one lands where it was meant to."""
    expected_red = {"audio lost", "STT unavailable", "matching unavailable", "NOT hidden"}
    for health in DESIGN_7_STATES.values():
        for indicator in health.indicators():
            wanted = RED_500 if indicator.startswith(tuple(expected_red)) else AMBER_500
            assert severity_of(indicator) == wanted, indicator


# ---------- FR7: the capture indicator ----------


def test_the_capture_chip_shows_whether_capture_is_running(qapp: QApplication) -> None:
    chip = CaptureIndicator()

    chip.set_capturing(False)
    idle = chip.visual_state()
    chip.set_capturing(True)
    live = chip.visual_state()

    assert idle != live
    assert CHIP_IDLE in idle
    assert ACCENT_GRADIENT in live


def test_capture_follows_either_stream(qapp: QApplication) -> None:
    """FR7 is about capture running at all, so one open stream is enough to light it."""
    bar = IndicatorBar()

    bar.update_health(Health(loopback=Status.OK))
    assert bar.capture.capturing is True

    bar.update_health(Health(mic=Status.OK))
    assert bar.capture.capturing is True

    bar.update_health(Health())
    assert bar.capture.capturing is False


# ---------- FR20: egress, one dot per path ----------


def test_each_egress_path_lights_independently(qapp: QApplication) -> None:
    egress = EgressIndicator()

    egress.set_egress(Egress.CLOUD_STT)
    assert (egress.cloud_stt.lit, egress.llm.lit) == (True, False)

    egress.set_egress(Egress.LLM)
    assert (egress.cloud_stt.lit, egress.llm.lit) == (False, True)

    egress.set_egress(Egress.BOTH)
    assert (egress.cloud_stt.lit, egress.llm.lit) == (True, True)

    egress.set_egress(Egress.NONE)
    assert (egress.cloud_stt.lit, egress.llm.lit) == (False, False)


def test_the_two_paths_are_named_not_just_positioned(qapp: QApplication) -> None:
    """A user who sees one lit dot must know which path is sending."""
    egress = EgressIndicator()

    assert egress.cloud_stt.text() != egress.llm.text()
    assert "STT" in egress.cloud_stt.text()
    assert "LLM" in egress.llm.text()


def test_an_unlit_dot_stays_in_place(qapp: QApplication) -> None:
    """Hiding it would reflow the row and make "off" look like "absent"."""
    egress = EgressIndicator()
    egress.set_egress(Egress.BOTH)
    lit_text = egress.llm.text()

    egress.set_egress(Egress.NONE)

    assert egress.llm.text() == lit_text


def test_egress_is_visually_distinct_from_capture(qapp: QApplication) -> None:
    """FR20 is defined relative to FR7's indicator: distinct by shape, not only colour."""
    bar = IndicatorBar()
    bar.update_health(Health(loopback=Status.OK, egress=Egress.BOTH))

    assert bar.capture.text() not in (bar.egress.cloud_stt.text(), bar.egress.llm.text())
    assert ACCENT_GRADIENT not in bar.egress.cloud_stt.styleSheet()


# ---------- FR14a: the capture-exclusion warning ----------


def test_the_exclusion_warning_shows_only_on_a_known_failure(qapp: QApplication) -> None:
    """Three states, and the unknown one must not claim success — that silent assumption
    is exactly what FR14a forbids."""
    bar = IndicatorBar()

    bar.update_health(Health(capture_excluded=None))
    assert bar.exclusion.isVisibleTo(bar) is False

    bar.update_health(Health(capture_excluded=True))
    assert bar.exclusion.isVisibleTo(bar) is False

    bar.update_health(Health(capture_excluded=False))
    assert bar.exclusion.isVisibleTo(bar) is True


def test_the_exclusion_warning_is_persistent(qapp: QApplication) -> None:
    """It never auto-hides: while the check says failed, the bar stays up."""
    bar = IndicatorBar()
    bar.update_health(Health(capture_excluded=False))

    bar.update_health(Health(loopback=Status.OK, capture_excluded=False))

    assert bar.exclusion.isVisibleTo(bar) is True
