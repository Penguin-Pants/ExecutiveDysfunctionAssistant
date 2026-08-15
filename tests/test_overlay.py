"""M5 core — the overlay panel, its states, brightness bands and auto-clear.

Two guarantees carry real weight here and both are checked rather than described:

* **FR11's byte-exact substring rule.** Everything upstream exists to make fabrication
  structurally impossible; this is the last boundary where that can be verified.
* **FR65's readability bands.** Design §9b measures mid-gray at 4.39:1 and 3.71:1 — below
  the 4.5:1 body-text threshold in *both* directions — so a naive slider would let the
  user park the overlay on a setting where it cannot be read. The contrast maths is
  implemented in the module, so these tests verify the bands instead of restating the
  design's table.
"""

from __future__ import annotations

import time

import pytest

pytest.importorskip("PySide6", reason="Qt UI tests require the [ui] extra")

from PySide6.QtWidgets import QApplication  # noqa: E402

from interview_prep_recall.ui.overlay import (  # noqa: E402  # noqa: E402
    DARK_BAND_MAX,
    DEFAULT_BRIGHTNESS,
    DEGRADED_GLYPH,
    HALO_OPACITY_THRESHOLD,
    LIGHT_BAND_MIN,
    MAX_BULLETS,
    MAX_SIZE,
    MIN_SIZE,
    NO_MATCH_TEXT,
    TAU_VISIBLE_S,
    OverlayGeometry,
    OverlayPanel,
    RenderError,
    SnippetState,
    SnippetTimer,
    SnippetView,
    UnknownNoteError,
    clamp_brightness,
    contrast_ratio,
    from_stored_note,
    load_geometry,
    no_match_view,
    palette_for,
    save_geometry,
)

BODY_TEXT_MIN = 4.5
"""WCAG AA for body text."""

RAIL_MIN = 3.0
"""WCAG AA for non-text UI components. The rails are the FR51 state signal."""

SOURCE = (
    "Led the migration off the monolith. Cut p99 latency from 900ms to 120ms. "
    "Team of four, six months."
)


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


# ---------- FR11: the retrieval-only guarantee, at the render boundary ----------


def test_a_string_not_in_the_source_is_refused() -> None:
    """The whole architecture upstream exists to make this impossible. Checking it here
    means a future producer — a summariser, a template, a translation layer — cannot
    quietly become the first thing to render text the user never wrote.
    """
    with pytest.raises(RenderError, match="byte-exact substring"):
        SnippetView(
            headline="Led the migration off the monolith",
            bullets=("Reduced latency by roughly 87%",),  # true, and not what they wrote
            state=SnippetState.CONFIRMED,
            source_text=SOURCE,
        )


def test_verbatim_strings_are_accepted() -> None:
    view = SnippetView(
        headline="Led the migration off the monolith.",
        bullets=("Cut p99 latency from 900ms to 120ms.", "Team of four, six months."),
        state=SnippetState.CONFIRMED,
        source_text=SOURCE,
    )
    assert view.rendered_strings[0] in SOURCE


def test_a_near_miss_is_still_a_miss() -> None:
    """Paraphrase is the failure mode that matters: plausible, close, and not theirs."""
    with pytest.raises(RenderError):
        SnippetView(
            headline="Led the migration off of the monolith.",
            bullets=(),
            state=SnippetState.CONFIRMED,
            source_text=SOURCE,
        )


def test_more_than_three_bullets_is_refused() -> None:
    with pytest.raises(RenderError, match=f"at most {MAX_BULLETS}"):
        SnippetView(
            headline="Led the migration off the monolith.",
            bullets=("Team of four, six months.",) * 4,
            state=SnippetState.CONFIRMED,
            source_text=SOURCE,
        )


def test_the_degraded_glyph_is_not_part_of_the_stored_text() -> None:
    """Prepended at display time, so it can never be mistaken for the user's words and the
    substring check sees what they actually wrote."""
    view = SnippetView(
        headline="Team of four, six months.",
        bullets=(),
        state=SnippetState.DEGRADED,
        source_text=SOURCE,
    )
    assert view.display_headline == f"{DEGRADED_GLYPH} Team of four, six months."
    assert view.headline in SOURCE


def test_no_match_renders_product_copy_not_user_content() -> None:
    view = no_match_view()
    assert view.state is SnippetState.NO_MATCH
    assert view.headline == NO_MATCH_TEXT
    assert view.bullets == ()


# ---------- FR65: the readability guarantee ----------


def test_contrast_ratio_matches_known_values() -> None:
    """Sanity-check the maths before trusting it to verify the bands."""
    assert contrast_ratio("#FFFFFF", "#000000") == pytest.approx(21.0, abs=0.05)
    assert contrast_ratio("#FFFFFF", "#FFFFFF") == pytest.approx(1.0, abs=0.01)


@pytest.mark.parametrize("brightness", list(range(0, 101)))
def test_every_reachable_brightness_is_readable(brightness: int) -> None:
    """Design §9b's sweep, as an assertion over the whole control range.

    Body text must clear 4.5:1 and both rails 3:1 at **every** setting the user can
    actually reach. This is the test that makes the two-band design a guarantee rather
    than an intention.
    """
    palette = palette_for(brightness)

    assert contrast_ratio(palette.ink, palette.panel) >= BODY_TEXT_MIN, (
        f"ink fails at brightness {brightness}"
    )
    assert contrast_ratio(palette.confirmed_rail, palette.panel) >= RAIL_MIN, (
        f"confirmed rail fails at brightness {brightness}"
    )
    assert contrast_ratio(palette.degraded_rail, palette.panel) >= RAIL_MIN, (
        f"degraded rail fails at brightness {brightness}"
    )


def test_the_mid_gray_range_is_unreachable() -> None:
    """At mid-gray neither ink clears 4.5:1. The control steps over 26–74 rather than
    stopping there, so no user can select it."""
    for value in range(DARK_BAND_MAX + 1, LIGHT_BAND_MIN):
        assert clamp_brightness(value) in {DARK_BAND_MAX, LIGHT_BAND_MIN}


def test_the_control_crosses_rather_than_sticking() -> None:
    """One slider crossing a threshold, not two settings: dragging up through the gap
    lands in the light band, dragging back returns to the dark one."""
    assert clamp_brightness(LIGHT_BAND_MIN - 1) == LIGHT_BAND_MIN
    assert clamp_brightness(DARK_BAND_MAX + 1) == DARK_BAND_MAX


def test_rails_swap_variants_at_the_crossover() -> None:
    """PRISM's `--amber-500` is near-invisible on a light ground. Without the swap the
    degraded state would silently vanish exactly when a user picked a light panel."""
    dark = palette_for(DARK_BAND_MAX)
    light = palette_for(LIGHT_BAND_MIN)

    assert dark.degraded_rail != light.degraded_rail
    assert dark.confirmed_rail != light.confirmed_rail
    assert contrast_ratio("#FFC93D", light.panel) < RAIL_MIN, (
        "the premise of the swap: the dark-band amber really is unreadable on light"
    )


def test_the_default_is_in_the_dark_band() -> None:
    """FR11's "dark semi-transparent panel, high-contrast light text"."""
    assert DEFAULT_BRIGHTNESS <= DARK_BAND_MAX
    assert clamp_brightness(DEFAULT_BRIGHTNESS) == DEFAULT_BRIGHTNESS


def test_brightness_is_clamped_to_the_control_range() -> None:
    assert clamp_brightness(-40) == 0
    assert clamp_brightness(400) == 100


# ---------- FR54 / FR13: auto-clear and pin ----------


def test_an_unpinned_snippet_clears_at_tau_visible() -> None:
    timer = SnippetTimer()
    timer.show(now=100.0)

    assert timer.should_clear(100.0 + TAU_VISIBLE_S - 0.1) is False
    assert timer.should_clear(100.0 + TAU_VISIBLE_S) is True


def test_a_pinned_snippet_persists_indefinitely() -> None:
    timer = SnippetTimer()
    timer.show(now=0.0)
    timer.pin()

    assert timer.should_clear(TAU_VISIBLE_S * 1000) is False


def test_a_new_snippet_drops_the_previous_pin() -> None:
    """Carrying the pin across would leave a stale answer on screen pinned to a question
    the user has moved past, with no way for them to know why it will not clear."""
    timer = SnippetTimer()
    timer.show(now=0.0)
    timer.pin()

    timer.show(now=1.0)

    assert timer.pinned is False
    assert timer.should_clear(1.0 + TAU_VISIBLE_S) is True


def test_nothing_shown_never_clears() -> None:
    assert SnippetTimer().should_clear(10_000.0) is False


def test_tau_visible_is_configurable() -> None:
    """OQ-2 revisits the default after real interview pacing."""
    timer = SnippetTimer(tau_visible_s=5.0)
    timer.show(now=0.0)
    assert timer.should_clear(5.0) is True


# ---------- the widget ----------


def test_panel_is_frameless_and_always_on_top(qapp: QApplication) -> None:
    from PySide6.QtCore import Qt

    panel = OverlayPanel()
    flags = panel.windowFlags()

    assert bool(flags & Qt.WindowType.FramelessWindowHint)
    assert bool(flags & Qt.WindowType.WindowStaysOnTopHint)


def test_panel_renders_headline_and_bullets(qapp: QApplication) -> None:
    panel = OverlayPanel()
    panel.show_snippet(
        SnippetView(
            headline="Led the migration off the monolith.",
            bullets=("Team of four, six months.",),
            state=SnippetState.CONFIRMED,
            source_text=SOURCE,
        ),
        now=0.0,
    )

    assert panel.headline.text() == "Led the migration off the monolith."
    assert panel.visible_bullet_count == 1


def test_fewer_bullets_hides_the_spare_labels(qapp: QApplication) -> None:
    """Stale text left in a hidden label is one styling change away from being visible."""
    panel = OverlayPanel()
    three = SnippetView(
        headline="Led the migration off the monolith.",
        bullets=("Cut p99 latency from 900ms to 120ms.", "Team of four, six months.", "monolith"),
        state=SnippetState.CONFIRMED,
        source_text=SOURCE,
    )
    panel.show_snippet(three, now=0.0)
    assert panel.visible_bullet_count == 3

    panel.show_snippet(
        SnippetView(
            headline="Team of four, six months.",
            bullets=(),
            state=SnippetState.CONFIRMED,
            source_text=SOURCE,
        ),
        now=1.0,
    )

    assert panel.visible_bullet_count == 0
    assert all(label.text() == "" for label in panel.bullets[0:])


def test_clearing_shows_the_no_match_line_not_a_blank_panel(qapp: QApplication) -> None:
    """FR35/OB-1. A blank overlay is indistinguishable from a crashed one, and the user
    cannot debug it mid-interview."""
    panel = OverlayPanel()
    panel.show_snippet(
        SnippetView(
            headline="Team of four, six months.",
            bullets=(),
            state=SnippetState.CONFIRMED,
            source_text=SOURCE,
        ),
        now=0.0,
    )

    panel.clear()

    assert panel.headline.text() == NO_MATCH_TEXT
    assert panel.view is not None
    assert panel.view.state is SnippetState.NO_MATCH


def test_tick_clears_an_expired_snippet(qapp: QApplication) -> None:
    panel = OverlayPanel(tau_visible_s=5.0)
    panel.show_snippet(
        SnippetView(
            headline="Team of four, six months.",
            bullets=(),
            state=SnippetState.CONFIRMED,
            source_text=SOURCE,
        ),
        now=0.0,
    )

    assert panel.tick(4.0) is False
    assert panel.tick(5.0) is True
    assert panel.headline.text() == NO_MATCH_TEXT


def test_the_two_states_produce_different_rails(qapp: QApplication) -> None:
    """FR51: distinguishable at a glance, without reading."""
    panel = OverlayPanel()
    palette = panel.palette_tokens

    assert palette.rail_for(SnippetState.CONFIRMED) != palette.rail_for(SnippetState.DEGRADED)
    assert palette.rail_for(SnippetState.NO_MATCH) is None


def test_low_opacity_engages_the_halo(qapp: QApplication) -> None:
    """Below 70% the panel composites with content nobody controls, so the measured
    contrast stops being a guarantee and the ink gets a halo instead."""
    assert OverlayPanel(OverlayGeometry(opacity=1.0)).halo_engaged is False
    assert OverlayPanel(OverlayGeometry(opacity=HALO_OPACITY_THRESHOLD)).halo_engaged is False
    assert OverlayPanel(OverlayGeometry(opacity=0.5)).halo_engaged is True


# ---------- FR26 / FR23 / FR27: geometry ----------


class FakeSettings:
    """`QSettings` round-trips through strings on some backends, so the double does too —
    a loader that only handles native types passes against a dict and fails on Windows."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def setValue(self, key: str, value: object) -> None:  # noqa: N802 — Qt's name
        self.store[key] = str(value)

    def value(self, key: str, default: object = None) -> object:
        return self.store.get(key, default)


def test_geometry_survives_a_round_trip() -> None:
    settings = FakeSettings()
    saved = OverlayGeometry(x=42, y=99, width=500, height=300, opacity=0.8, brightness=80)

    save_geometry(settings, saved)
    loaded = load_geometry(settings)

    assert (loaded.x, loaded.y) == (42, 99)
    assert (loaded.width, loaded.height) == (500, 300)
    assert loaded.opacity == pytest.approx(0.8)
    assert loaded.brightness == 80


def test_missing_settings_fall_back_to_defaults() -> None:
    loaded = load_geometry(FakeSettings())
    assert loaded.width == OverlayGeometry().width
    assert loaded.brightness == DEFAULT_BRIGHTNESS


def test_one_corrupt_value_costs_one_setting() -> None:
    settings = FakeSettings()
    save_geometry(settings, OverlayGeometry(width=500))
    settings.store["overlay/width"] = "not a number"

    loaded = load_geometry(settings)

    assert loaded.width == OverlayGeometry().width
    assert loaded.x == OverlayGeometry().x


def test_sizes_are_clamped_to_the_fr23_range() -> None:
    tiny = OverlayGeometry(width=10, height=10).clamped()
    huge = OverlayGeometry(width=9999, height=9999).clamped()

    assert (tiny.width, tiny.height) == MIN_SIZE
    assert (huge.width, huge.height) == MAX_SIZE


def test_a_persisted_unreadable_brightness_is_snapped_on_load() -> None:
    """A config written by an older build, or hand-edited, must not resurrect the
    unreadable middle."""
    settings = FakeSettings()
    settings.store["overlay/brightness"] = "50"

    assert load_geometry(settings).brightness in {DARK_BAND_MAX, LIGHT_BAND_MIN}


# ---------- found in local review ----------


def test_a_replacement_runs_a_transition(qapp: QApplication) -> None:
    """FR25: never a hard pop.

    `TRANSITION_MS` existed as a constant with nothing using it — a requirement declared
    and not implemented, with a value implying otherwise.
    """
    panel = OverlayPanel()
    first = SnippetView(
        headline="Team of four, six months.",
        bullets=(),
        state=SnippetState.CONFIRMED,
        source_text=SOURCE,
    )
    panel.show_snippet(first, now=0.0)
    assert panel.transition_running is False, "the first snippet is an appearance, not a replace"

    panel.show_snippet(
        SnippetView(
            headline="Led the migration off the monolith.",
            bullets=(),
            state=SnippetState.CONFIRMED,
            source_text=SOURCE,
        ),
        now=1.0,
    )

    assert panel.transition_running is True


def test_the_transition_returns_to_the_users_opacity(qapp: QApplication) -> None:
    """Animating to 1.0 would quietly discard the FR24 opacity setting every time a
    snippet changed."""
    panel = OverlayPanel(OverlayGeometry(opacity=0.6))
    view = SnippetView(
        headline="Team of four, six months.",
        bullets=(),
        state=SnippetState.CONFIRMED,
        source_text=SOURCE,
    )
    panel.show_snippet(view, now=0.0)
    panel.show_snippet(view, now=1.0)

    assert panel._animation.endValue() == pytest.approx(0.6)  # noqa: SLF001


def test_reset_recovers_an_off_screen_overlay() -> None:
    """FR27. The user cannot see the panel, so preserving position or lock state would
    preserve exactly what they are trying to escape."""
    lost = OverlayGeometry(x=-9000, y=-9000, width=900, height=600, locked=True, brightness=80)

    recovered = lost.reset()

    assert (recovered.x, recovered.y) == (OverlayGeometry().x, OverlayGeometry().y)
    assert recovered.locked is False
    assert recovered.brightness == 80, "brightness is a preference, not a way to lose the panel"


# ---------- PR #20 review findings ----------


def test_the_substring_check_alone_does_not_stop_a_fabricating_producer() -> None:
    """The finding, stated as a test: `source_text` comes from the same caller.

    A producer passing generated text as both the headline and the source satisfies the
    consistency check trivially. This test documents the limit so nobody re-reads the
    check as the guarantee — which the docstring previously invited.
    """
    fabricated = "I single-handedly rewrote the billing system."

    view = SnippetView(
        headline=fabricated,
        bullets=(),
        state=SnippetState.CONFIRMED,
        source_text=fabricated,
    )

    assert view.headline == fabricated  # accepted, and it should not have been


def test_from_stored_note_checks_against_the_store() -> None:
    """Where FR11's guarantee actually lives: the source text is resolved by id from
    storage the producer does not control."""
    store = {"n1": SOURCE}

    view = from_stored_note(
        store.get, "n1", "Team of four, six months.", (), SnippetState.CONFIRMED
    )

    assert view.source_text == SOURCE
    assert view.note_id == "n1"


def test_from_stored_note_refuses_text_absent_from_the_stored_note() -> None:
    store = {"n1": SOURCE}

    with pytest.raises(RenderError, match="byte-exact substring"):
        from_stored_note(
            store.get,
            "n1",
            "I single-handedly rewrote the billing system.",
            (),
            SnippetState.CONFIRMED,
        )


def test_from_stored_note_refuses_an_unknown_note_id() -> None:
    with pytest.raises(UnknownNoteError, match="not in the store"):
        from_stored_note({}.get, "missing", "anything", (), SnippetState.CONFIRMED)


def test_the_clock_drives_auto_clear(qapp: QApplication) -> None:
    """`tick` was pull-based and nothing called it, so an unpinned snippet stayed on
    screen for the whole interview despite the 25 s lifetime."""
    panel = OverlayPanel(tau_visible_s=0.0)
    panel.show_snippet(
        SnippetView(
            headline="Team of four, six months.",
            bullets=(),
            state=SnippetState.CONFIRMED,
            source_text=SOURCE,
        ),
        now=0.0,
    )
    panel.start_clock(interval_ms=1)

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and panel.headline.text() != NO_MATCH_TEXT:
        qapp.processEvents()
        time.sleep(0.01)

    assert panel.headline.text() == NO_MATCH_TEXT, "the clock never fired"


def test_low_opacity_applies_a_halo_effect(qapp: QApplication) -> None:
    """`halo_engaged` was computed and never consulted, so the ink was bare over arbitrary
    video content in exactly the range where the contrast figures stop holding."""
    faint = OverlayPanel(OverlayGeometry(opacity=0.5))
    solid = OverlayPanel(OverlayGeometry(opacity=1.0))

    assert faint.headline.graphicsEffect() is not None
    assert solid.headline.graphicsEffect() is None


def test_reset_keeps_preferences_that_cannot_hide_the_panel() -> None:
    """Size, opacity and brightness are preferences; none of them can make the overlay
    unreachable, so discarding them would make reset cost more than it fixes."""
    tuned = OverlayGeometry(
        x=-9000, y=-9000, width=880, height=560, opacity=0.55, brightness=80, locked=True
    )

    recovered = tuned.reset()

    assert (recovered.x, recovered.y) == (OverlayGeometry().x, OverlayGeometry().y)
    assert recovered.locked is False
    assert (recovered.width, recovered.height) == (880, 560)
    assert recovered.opacity == pytest.approx(0.55)
    assert recovered.brightness == 80
