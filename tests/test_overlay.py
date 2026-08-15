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
from dataclasses import replace

import pytest

pytest.importorskip("PySide6", reason="Qt UI tests require the [ui] extra")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QFontMetrics  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from interview_prep_recall.notes.model import SourceKind  # noqa: E402
from interview_prep_recall.session.health import Egress, Health, Status  # noqa: E402
from interview_prep_recall.ui.overlay import (  # noqa: E402  # noqa: E402
    BULLET_PX_RANGE,
    DARK_BAND_MAX,
    DEFAULT_BRIGHTNESS,
    DEGRADED_GLYPH,
    ELLIPSIS,
    HALO_OPACITY_THRESHOLD,
    HEADLINE_PX_RANGE,
    KIND_MARKS,
    LIGHT_BAND_MIN,
    MAX_BULLETS,
    MAX_SIZE,
    MIN_BULLET_LINES,
    MIN_RENDERED_PX,
    MIN_SIZE,
    NO_MATCH_TEXT,
    TAU_VISIBLE_S,
    TOP_MARGIN_PX,
    Edge,
    OverlayGeometry,
    OverlayPanel,
    RenderError,
    ScreenBounds,
    SnippetState,
    SnippetTimer,
    SnippetView,
    UnknownNoteError,
    _cursor_for,
    bullet_px,
    clamp_brightness,
    contrast_ratio,
    edges_at,
    elide_to_lines,
    from_stored_note,
    headline_px,
    line_count,
    load_geometry,
    mark_for,
    no_match_view,
    palette_for,
    resized,
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
            kind=SourceKind.PREP,
        )


def test_verbatim_strings_are_accepted() -> None:
    view = SnippetView(
        headline="Led the migration off the monolith.",
        bullets=("Cut p99 latency from 900ms to 120ms.", "Team of four, six months."),
        state=SnippetState.CONFIRMED,
        source_text=SOURCE,
        kind=SourceKind.PREP,
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
            kind=SourceKind.PREP,
        )


def test_more_than_three_bullets_is_refused() -> None:
    with pytest.raises(RenderError, match=f"at most {MAX_BULLETS}"):
        SnippetView(
            headline="Led the migration off the monolith.",
            bullets=("Team of four, six months.",) * 4,
            state=SnippetState.CONFIRMED,
            source_text=SOURCE,
            kind=SourceKind.PREP,
        )


def test_the_degraded_glyph_is_not_part_of_the_stored_text() -> None:
    """Prepended at display time, so it can never be mistaken for the user's words and the
    substring check sees what they actually wrote."""
    view = SnippetView(
        headline="Team of four, six months.",
        bullets=(),
        state=SnippetState.DEGRADED,
        source_text=SOURCE,
        kind=SourceKind.PREP,
    )
    # The kind mark rides in the same prefix (T10.7), so the assertion is on the two
    # channels and the untouched text rather than on one fixed string.
    mark = mark_for(SourceKind.PREP)
    assert view.display_headline == f"{DEGRADED_GLYPH} {mark.glyph} Team of four, six months."
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
            kind=SourceKind.PREP,
        ),
        now=0.0,
    )

    assert panel.headline.text() == (
        f"{mark_for(SourceKind.PREP).glyph} Led the migration off the monolith."
    )
    assert panel.visible_bullet_count == 1


def test_fewer_bullets_hides_the_spare_labels(qapp: QApplication) -> None:
    """Stale text left in a hidden label is one styling change away from being visible."""
    panel = OverlayPanel()
    three = SnippetView(
        headline="Led the migration off the monolith.",
        bullets=("Cut p99 latency from 900ms to 120ms.", "Team of four, six months.", "monolith"),
        state=SnippetState.CONFIRMED,
        source_text=SOURCE,
        kind=SourceKind.PREP,
    )
    panel.show_snippet(three, now=0.0)
    assert panel.visible_bullet_count == 3

    panel.show_snippet(
        SnippetView(
            headline="Team of four, six months.",
            bullets=(),
            state=SnippetState.CONFIRMED,
            source_text=SOURCE,
            kind=SourceKind.PREP,
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
            kind=SourceKind.PREP,
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
            kind=SourceKind.PREP,
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
        kind=SourceKind.PREP,
    )
    panel.show_snippet(first, now=0.0)
    assert panel.transition_running is False, "the first snippet is an appearance, not a replace"

    panel.show_snippet(
        SnippetView(
            headline="Led the migration off the monolith.",
            bullets=(),
            state=SnippetState.CONFIRMED,
            source_text=SOURCE,
            kind=SourceKind.PREP,
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
        kind=SourceKind.PREP,
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
        kind=SourceKind.PREP,
    )

    assert view.headline == fabricated  # accepted, and it should not have been


def test_from_stored_note_checks_against_the_store() -> None:
    """Where FR11's guarantee actually lives: the source text is resolved by id from
    storage the producer does not control."""
    store = {"n1": SOURCE}
    kinds = {"n1": SourceKind.RESUME}

    view = from_stored_note(
        store.get,
        "n1",
        "Team of four, six months.",
        (),
        SnippetState.CONFIRMED,
        resolve_kind=kinds.get,
    )

    assert view.source_text == SOURCE
    assert view.note_id == "n1"
    assert view.kind is SourceKind.RESUME


def test_from_stored_note_refuses_text_absent_from_the_stored_note() -> None:
    store = {"n1": SOURCE}

    with pytest.raises(RenderError, match="byte-exact substring"):
        from_stored_note(
            store.get,
            "n1",
            "I single-handedly rewrote the billing system.",
            (),
            SnippetState.CONFIRMED,
            resolve_kind=lambda _: SourceKind.PREP,
        )


def test_from_stored_note_refuses_an_unknown_note_id() -> None:
    with pytest.raises(UnknownNoteError, match="not in the store"):
        from_stored_note(
            {}.get,
            "missing",
            "anything",
            (),
            SnippetState.CONFIRMED,
            resolve_kind=lambda _: SourceKind.PREP,
        )


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
            kind=SourceKind.PREP,
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


# ---------- T5.4: drag, resize, lock, reset ----------


def test_the_default_position_is_top_centre(qapp: QApplication) -> None:
    """FR22. Asserted against the screen the panel reports rather than a fixed number,
    because the offscreen platform's display size is not the product's."""
    panel = OverlayPanel()
    bounds = ScreenBounds.of(panel)
    assert bounds is not None

    geometry = panel.geometry_settings

    assert geometry.x == bounds.x + (bounds.width - geometry.width) // 2
    assert geometry.y == bounds.y + TOP_MARGIN_PX


def test_persisted_geometry_beats_the_default_placement(qapp: QApplication) -> None:
    """FR26 outranks FR22 on every run after the first: a panel the user moved must come
    back where they left it, not be re-centred."""
    panel = OverlayPanel(OverlayGeometry(x=17, y=23))

    assert (panel.geometry_settings.x, panel.geometry_settings.y) == (17, 23)


def test_first_run_loads_the_top_centre_default() -> None:
    """Nothing persisted yet, so FR22's placement is what `load_geometry` hands back."""
    bounds = ScreenBounds(x=0, y=0, width=1920, height=1080)

    loaded = load_geometry(FakeSettings(), bounds)

    assert loaded.x == (1920 - loaded.width) // 2
    assert loaded.y == TOP_MARGIN_PX


def test_a_persisted_position_survives_the_bounds_argument() -> None:
    stored = FakeSettings()
    save_geometry(stored, OverlayGeometry(x=-40, y=900))

    loaded = load_geometry(stored, ScreenBounds(0, 0, 1920, 1080))

    assert (loaded.x, loaded.y) == (-40, 900)


def test_dragging_moves_the_panel(qapp: QApplication) -> None:
    """FR22."""
    panel = OverlayPanel(OverlayGeometry(x=100, y=100))

    panel.begin_manipulation(QPoint(200, 60), QPoint(500, 500))
    panel.update_manipulation(QPoint(530, 480))
    panel.end_manipulation()

    assert (panel.geometry_settings.x, panel.geometry_settings.y) == (130, 80)


def test_a_drag_is_measured_from_the_press_not_between_moves(qapp: QApplication) -> None:
    """A dropped move event must not leave the panel offset from the pointer."""
    panel = OverlayPanel(OverlayGeometry(x=100, y=100))

    panel.begin_manipulation(QPoint(200, 60), QPoint(500, 500))
    panel.update_manipulation(QPoint(510, 500))
    panel.update_manipulation(QPoint(560, 500))
    panel.end_manipulation()

    assert panel.geometry_settings.x == 160


def test_the_lock_makes_dragging_a_no_op(qapp: QApplication) -> None:
    """FR27."""
    panel = OverlayPanel(OverlayGeometry(x=100, y=100, locked=True))

    panel.begin_manipulation(QPoint(200, 60), QPoint(500, 500))
    panel.update_manipulation(QPoint(900, 900))
    panel.end_manipulation()

    assert (panel.geometry_settings.x, panel.geometry_settings.y) == (100, 100)


def test_lock_and_drag_are_independent_controls(qapp: QApplication) -> None:
    """Unlocking restores dragging; the lock is a mode, not a one-way door."""
    panel = OverlayPanel(OverlayGeometry(x=100, y=100, locked=True))
    panel.set_locked(False)

    panel.begin_manipulation(QPoint(200, 60), QPoint(0, 0))
    panel.update_manipulation(QPoint(25, 0))
    panel.end_manipulation()

    assert panel.geometry_settings.x == 125


def test_locking_mid_drag_stops_the_panel_where_it_is(qapp: QApplication) -> None:
    panel = OverlayPanel(OverlayGeometry(x=100, y=100))
    panel.begin_manipulation(QPoint(200, 60), QPoint(0, 0))
    panel.update_manipulation(QPoint(30, 0))

    panel.set_locked(True)
    panel.update_manipulation(QPoint(400, 0))

    assert panel.geometry_settings.x == 130


def test_an_edge_press_resizes_rather_than_dragging(qapp: QApplication) -> None:
    """FR23's edge drag. A frameless window has no grips, so the margin is the affordance."""
    panel = OverlayPanel(OverlayGeometry(x=100, y=100, width=420, height=220))

    panel.begin_manipulation(QPoint(419, 120), QPoint(0, 0))
    panel.update_manipulation(QPoint(60, 0))
    panel.end_manipulation()

    assert panel.geometry_settings.width == 480
    assert (panel.geometry_settings.x, panel.geometry_settings.y) == (100, 100)


def test_resizing_from_the_left_edge_pins_the_right_one(qapp: QApplication) -> None:
    start = OverlayGeometry(x=100, y=100, width=420, height=220)

    resized_geometry = resized(start, {Edge.LEFT}, dx=-40, dy=0)

    assert resized_geometry.width == 460
    assert resized_geometry.x == 60
    assert resized_geometry.x + resized_geometry.width == start.x + start.width


def test_the_panel_stops_sliding_when_the_size_clamps(qapp: QApplication) -> None:
    """The obvious implementation walks the panel sideways forever once the width has hit
    its minimum. FR23's range is a limit on the size *and* on the movement it causes."""
    start = OverlayGeometry(x=100, y=100, width=MIN_SIZE[0], height=220)

    resized_geometry = resized(start, {Edge.LEFT}, dx=400, dy=0)

    assert resized_geometry.width == MIN_SIZE[0]
    assert resized_geometry.x == 100


def test_resize_is_clamped_to_the_fr23_range(qapp: QApplication) -> None:
    start = OverlayGeometry(x=0, y=0, width=420, height=220)

    assert resized(start, {Edge.RIGHT, Edge.BOTTOM}, 5000, 5000).width == MAX_SIZE[0]
    assert resized(start, {Edge.RIGHT, Edge.BOTTOM}, 5000, 5000).height == MAX_SIZE[1]
    assert resized(start, {Edge.RIGHT, Edge.BOTTOM}, -5000, -5000).width == MIN_SIZE[0]


def test_the_lock_withholds_only_the_edges_that_move_the_panel(qapp: QApplication) -> None:
    """FR27 is about the panel wandering. Resizing from the right or bottom leaves it
    exactly where the user put it, so the lock has no business blocking it."""
    panel = OverlayPanel(OverlayGeometry(x=100, y=100, width=420, height=220, locked=True))

    assert panel.allowed_edges(QPoint(1, 110)) == set()
    assert panel.allowed_edges(QPoint(419, 110)) == {Edge.RIGHT}


def test_a_press_outside_the_panel_grabs_nothing() -> None:
    assert edges_at(QPoint(-5, 50), 420, 220) == set()
    assert edges_at(QPoint(430, 50), 420, 220) == set()


def test_an_interior_press_is_a_drag_not_a_resize() -> None:
    assert edges_at(QPoint(210, 110), 420, 220) == set()


def test_corners_grab_both_edges() -> None:
    assert edges_at(QPoint(0, 0), 420, 220) == {Edge.LEFT, Edge.TOP}
    assert edges_at(QPoint(419, 219), 420, 220) == {Edge.RIGHT, Edge.BOTTOM}


def test_a_finished_drag_is_persisted(qapp: QApplication) -> None:
    """FR26. A position that survives only until restart is not the requirement."""
    saved: list[OverlayGeometry] = []
    panel = OverlayPanel(OverlayGeometry(x=100, y=100), on_geometry_changed=saved.append)

    panel.begin_manipulation(QPoint(200, 60), QPoint(0, 0))
    panel.update_manipulation(QPoint(40, 0))
    panel.end_manipulation()

    assert saved and saved[-1].x == 140


def test_a_drag_that_changed_nothing_is_not_persisted(qapp: QApplication) -> None:
    saved: list[OverlayGeometry] = []
    panel = OverlayPanel(OverlayGeometry(x=100, y=100), on_geometry_changed=saved.append)

    panel.begin_manipulation(QPoint(200, 60), QPoint(0, 0))
    panel.end_manipulation()

    assert saved == []


def test_reset_recovers_a_panel_dragged_off_screen(qapp: QApplication) -> None:
    """FR55 end to end: persisted off-screen coordinates, restored by the control."""
    saved: list[OverlayGeometry] = []
    panel = OverlayPanel(
        OverlayGeometry(x=-9000, y=-9000, locked=True), on_geometry_changed=saved.append
    )
    bounds = ScreenBounds.of(panel)
    assert bounds is not None

    recovered = panel.reset_geometry()

    assert recovered.x == bounds.x + (bounds.width - recovered.width) // 2
    assert recovered.y == bounds.y + TOP_MARGIN_PX
    assert recovered.locked is False
    assert saved[-1] == recovered, "FR55 must survive the restart it is rescuing the user from"


def test_top_centring_uses_the_clamped_size() -> None:
    """A persisted width outside FR23's range must not push the recovered panel off the
    side of the screen it was just centred on."""
    bounds = ScreenBounds(0, 0, 1000, 800)

    centred = OverlayGeometry(width=5000).top_centred(bounds)

    assert centred.width == MAX_SIZE[0]
    assert centred.x == (1000 - MAX_SIZE[0]) // 2


# ---------- T5.4: FR23's text scaling ----------


def test_text_scales_with_panel_height() -> None:
    """FR23: text scales rather than clipping, and design §9b's formula governs."""
    assert headline_px(MIN_SIZE[1]) == HEADLINE_PX_RANGE[0]
    assert headline_px(MAX_SIZE[1]) == HEADLINE_PX_RANGE[1]
    assert bullet_px(MIN_SIZE[1]) == BULLET_PX_RANGE[0]
    assert bullet_px(MAX_SIZE[1]) == BULLET_PX_RANGE[1]


def test_scaling_is_monotonic_across_the_supported_range() -> None:
    heights = list(range(MIN_SIZE[1], MAX_SIZE[1] + 1))
    for smaller, larger in zip(heights, heights[1:], strict=False):
        assert headline_px(smaller) <= headline_px(larger)
        assert bullet_px(smaller) <= bullet_px(larger)


@pytest.mark.parametrize("height", list(range(MIN_SIZE[1], MAX_SIZE[1] + 1, 7)))
def test_nothing_renders_below_the_glanceable_floor(height: int) -> None:
    """Design §9b's first checkable rule. Below 13px the overlay stops being glanceable,
    which is the only thing it exists to be."""
    assert bullet_px(height) >= MIN_RENDERED_PX
    assert headline_px(height) >= MIN_RENDERED_PX


def test_scaling_clamps_outside_the_supported_range() -> None:
    assert headline_px(10) == HEADLINE_PX_RANGE[0]
    assert headline_px(5000) == HEADLINE_PX_RANGE[1]


def test_the_panel_applies_the_scaled_sizes(qapp: QApplication) -> None:
    small = OverlayPanel(OverlayGeometry(width=320, height=MIN_SIZE[1]))
    large = OverlayPanel(OverlayGeometry(width=320, height=MAX_SIZE[1]))

    assert small.headline.font().pixelSize() == headline_px(MIN_SIZE[1])
    assert large.headline.font().pixelSize() == headline_px(MAX_SIZE[1])
    assert large.headline.font().pixelSize() > small.headline.font().pixelSize()


def test_resizing_rescales_live_text(qapp: QApplication) -> None:
    panel = OverlayPanel(OverlayGeometry(width=420, height=MIN_SIZE[1]))
    before = panel.headline.font().pixelSize()

    panel.apply_geometry(replace(panel.geometry_settings, height=MAX_SIZE[1]))

    assert panel.headline.font().pixelSize() > before


def test_a_long_bullet_elides_rather_than_growing_unboundedly(qapp: QApplication) -> None:
    """Design §9b: two lines, then ellipsis — and only after scaling has hit the floor."""
    long_source = "word " * 400
    panel = OverlayPanel(OverlayGeometry(width=MIN_SIZE[0], height=MIN_SIZE[1]))

    panel.show_snippet(
        SnippetView(
            headline="word word",
            bullets=(long_source.strip(),),
            state=SnippetState.CONFIRMED,
            source_text=long_source,
            kind=SourceKind.PREP,
        ),
        now=0.0,
    )

    rendered = panel.bullets[0].text()
    assert rendered.endswith(ELLIPSIS)
    assert len(rendered) < len(long_source)
    metrics = QFontMetrics(panel.bullets[0].font())
    assert line_count(rendered, metrics, panel.text_width) <= MIN_BULLET_LINES


def test_a_short_bullet_is_rendered_verbatim(qapp: QApplication) -> None:
    """FR11's substring rule is what elision must not quietly break, so a bullet that
    fits is never touched."""
    panel = OverlayPanel(OverlayGeometry(width=MAX_SIZE[0], height=MAX_SIZE[1]))

    panel.show_snippet(
        SnippetView(
            headline="Led the migration off the monolith.",
            bullets=("Cut p99 latency from 900ms to 120ms.",),
            state=SnippetState.CONFIRMED,
            source_text=SOURCE,
            kind=SourceKind.PREP,
        ),
        now=0.0,
    )

    assert panel.bullets[0].text() == "Cut p99 latency from 900ms to 120ms."
    assert panel.bullets[0].text() in SOURCE


def test_elision_needs_at_least_one_line(qapp: QApplication) -> None:
    panel = OverlayPanel()
    metrics = QFontMetrics(panel.bullets[0].font())
    with pytest.raises(ValueError, match="max_lines"):
        elide_to_lines("anything", metrics, 200, max_lines=0)


def test_widening_the_panel_restores_elided_text(qapp: QApplication) -> None:
    """Width drives wrapping, height drives size — so a wider panel needs less elision at
    the same font."""
    text = "Cut p99 latency from 900 milliseconds to 120 milliseconds across the fleet."
    source = f"{text} And more."
    narrow = OverlayPanel(OverlayGeometry(width=MIN_SIZE[0], height=MIN_SIZE[1]))
    wide = OverlayPanel(OverlayGeometry(width=MAX_SIZE[0], height=MIN_SIZE[1]))
    view = SnippetView(
        headline="Cut p99",
        bullets=(text,),
        state=SnippetState.CONFIRMED,
        source_text=source,
        kind=SourceKind.PREP,
    )

    narrow.show_snippet(view, now=0.0)
    wide.show_snippet(view, now=0.0)

    assert wide.bullets[0].text() == text
    assert len(narrow.bullets[0].text()) <= len(wide.bullets[0].text())


def test_the_cursor_signals_which_edge_was_grabbed() -> None:
    """The only resize affordance a frameless window has."""
    assert _cursor_for(set()) is Qt.CursorShape.ArrowCursor
    assert _cursor_for({Edge.LEFT}) is Qt.CursorShape.SizeHorCursor
    assert _cursor_for({Edge.BOTTOM}) is Qt.CursorShape.SizeVerCursor
    assert _cursor_for({Edge.LEFT, Edge.TOP}) is Qt.CursorShape.SizeFDiagCursor
    assert _cursor_for({Edge.RIGHT, Edge.TOP}) is Qt.CursorShape.SizeBDiagCursor
    assert _cursor_for({Edge.LEFT, Edge.BOTTOM}) is Qt.CursorShape.SizeBDiagCursor


# ---------- T5.7 at the panel boundary ----------


def test_the_panel_carries_the_indicator_bar(qapp: QApplication) -> None:
    """FR14a's warning is specified as a bar across *this* panel's top, and FR20 requires
    a persistent indicator — neither works on a surface the user has to go and find."""
    panel = OverlayPanel()

    panel.update_health(Health(loopback=Status.OK, egress=Egress.LLM, capture_excluded=False))

    assert panel.indicators.capture.capturing is True
    assert panel.indicators.egress.llm.lit is True
    assert panel.indicators.exclusion.isVisibleTo(panel) is True


def test_elision_only_ever_cuts_from_the_end(qapp: QApplication) -> None:
    """FR11 across the one place a rendered string is not byte-identical to the note.

    Truncate-and-append is inside the guarantee; substituting or reordering would not be,
    and a smarter middle-elide added later would break it silently. So the property is
    asserted rather than described.
    """
    long_source = "Cut p99 latency from 900ms to 120ms across every service in the fleet. " * 12
    panel = OverlayPanel(OverlayGeometry(width=MIN_SIZE[0], height=MIN_SIZE[1]))

    panel.show_snippet(
        SnippetView(
            headline="Cut p99 latency",
            bullets=(long_source.strip(),),
            state=SnippetState.CONFIRMED,
            source_text=long_source,
            kind=SourceKind.PREP,
        ),
        now=0.0,
    )

    rendered = panel.bullets[0].text()
    assert rendered.endswith(ELLIPSIS)
    assert long_source.startswith(rendered.removesuffix(ELLIPSIS))


def test_a_drag_does_not_rebuild_the_halo_effects(qapp: QApplication) -> None:
    """A full restyle per mouse-move rebuilds a drop-shadow effect on four labels at
    pointer rate, on the surface NFR3 measures frame time against. A drag changes neither
    size nor brightness, so it must not trigger one."""
    panel = OverlayPanel(OverlayGeometry(x=100, y=100, opacity=0.5))
    assert panel.halo_engaged is True
    before = panel.headline.graphicsEffect()

    panel.begin_manipulation(QPoint(200, 60), QPoint(0, 0))
    panel.update_manipulation(QPoint(40, 20))
    panel.end_manipulation()

    assert panel.geometry_settings.x == 140
    assert panel.headline.graphicsEffect() is before


def test_a_resize_still_restyles(qapp: QApplication) -> None:
    """The lighter drag path must not cost the rescale a resize genuinely needs."""
    panel = OverlayPanel(OverlayGeometry(x=0, y=0, width=420, height=MIN_SIZE[1]))
    before = panel.headline.font().pixelSize()

    panel.begin_manipulation(QPoint(210, MIN_SIZE[1] - 1), QPoint(0, 0))
    panel.update_manipulation(QPoint(0, 300))
    panel.end_manipulation()

    assert panel.geometry_settings.height > MIN_SIZE[1]
    assert panel.headline.font().pixelSize() > before


def test_the_indicator_groups_do_not_repaint_the_state_rail(qapp: QApplication) -> None:
    """The panel's `QWidget { border-left: … }` applies to every widget under it, so a
    container without its own border would draw a second copy of the FR51 rail."""
    panel = OverlayPanel()
    panel.update_health(Health(loopback=Status.OK))

    for container in (panel.indicators, panel.indicators.egress, panel.indicators.health):
        assert "border: none" in container.styleSheet()


# ---------- PR #21 review findings ----------


def test_a_tall_panel_shows_more_lines_than_the_minimum_one(qapp: QApplication) -> None:
    """§9b's two-line sentence is a floor, not a cap (D-51).

    Read as a flat cap it clips text into two lines at every size, including a 600px panel
    with most of its height empty — which is the clipping FR23 exists to forbid.
    """
    long_source = "Cut p99 latency from 900 milliseconds to 120 milliseconds fleet-wide. " * 20
    view = SnippetView(
        headline="Cut p99",
        bullets=(long_source.strip(),),
        state=SnippetState.CONFIRMED,
        source_text=long_source,
        kind=SourceKind.PREP,
    )
    short = OverlayPanel(OverlayGeometry(width=420, height=MIN_SIZE[1]))
    tall = OverlayPanel(OverlayGeometry(width=420, height=MAX_SIZE[1]))

    short.show_snippet(view, now=0.0)
    tall.show_snippet(view, now=0.0)

    assert tall.bullet_lines_available(bullet_px(MAX_SIZE[1])) > MIN_BULLET_LINES
    assert len(tall.bullets[0].text()) > len(short.bullets[0].text())


def test_the_smallest_panel_still_honours_the_two_line_floor(qapp: QApplication) -> None:
    """At the minimum size the computed allowance is the two lines §9b describes."""
    panel = OverlayPanel(OverlayGeometry(width=MIN_SIZE[0], height=MIN_SIZE[1]))

    assert panel.bullet_lines_available(bullet_px(MIN_SIZE[1])) >= MIN_BULLET_LINES


def test_text_that_fits_the_taller_panel_is_never_cut(qapp: QApplication) -> None:
    """The FR11 consequence of the fix: a bullet only loses characters it has no room
    for, so a panel with room renders the stored text byte for byte."""
    text = "Cut p99 latency from 900 milliseconds to 120 milliseconds across the fleet."
    source = f"{text} Team of four, six months."
    panel = OverlayPanel(OverlayGeometry(width=MAX_SIZE[0], height=MAX_SIZE[1]))

    panel.show_snippet(
        SnippetView(
            headline="Cut p99",
            bullets=(text,),
            state=SnippetState.CONFIRMED,
            source_text=source,
            kind=SourceKind.PREP,
        ),
        now=0.0,
    )

    assert panel.bullets[0].text() == text


# ---------- T10.7 — per-kind marking (FR72) ----------


def test_every_kind_has_a_mark() -> None:
    """FR72 is a property of the *set* of kinds, so an unmarked kind is a gap in the
    requirement rather than a missing dictionary entry."""
    for kind in SourceKind:
        assert mark_for(kind).glyph
        assert mark_for(kind).label


def test_the_marks_are_pairwise_distinct() -> None:
    """The acceptance criterion, asserted the only way it can be: pairwise.

    A per-kind assertion cannot express "distinguishable", because distinctness is not a
    property any single kind has. Same shape as T5.7's health-state test, for the same
    reason.
    """
    glyphs = [mark_for(kind).glyph for kind in SourceKind]
    labels = [mark_for(kind).label for kind in SourceKind]

    assert len(set(glyphs)) == len(glyphs)
    assert len(set(labels)) == len(labels)


def test_the_mark_is_a_shape_not_a_colour() -> None:
    """D-55. The overlay's colour channel is fully allocated to *state* (FR51's rail,
    FR20's egress, FR14a's failure bar, FR12's marked point), and PRISM §1 forbids
    remapping its semantic dots — so a kind that arrived as a hue would either collide
    with a state or break the design system. The mark is a glyph and no colour token
    exists for it; this test is what stops one being added without revisiting D-55.
    """
    assert not hasattr(mark_for(SourceKind.PREP), "colour")
    assert set(vars(KIND_MARKS[SourceKind.PREP])) == {"glyph", "label"}


def test_the_glyph_is_never_confusable_with_the_degraded_glyph() -> None:
    """FR51's channel and FR72's channel share the headline, so they have to stay
    readable as two marks rather than one."""
    assert DEGRADED_GLYPH not in {mark_for(kind).glyph for kind in SourceKind}


def test_the_headline_carries_the_kind_mark() -> None:
    view = SnippetView(
        headline="Team of four, six months.",
        bullets=(),
        state=SnippetState.CONFIRMED,
        source_text=SOURCE,
        kind=SourceKind.ROLE,
    )

    assert view.display_headline.startswith(mark_for(SourceKind.ROLE).glyph)
    assert view.display_headline.endswith("Team of four, six months.")


def test_a_degraded_snippet_carries_both_marks_state_first() -> None:
    """Two channels, and the order is not arbitrary: how much to trust the panel is read
    before what the panel is about."""
    view = SnippetView(
        headline="Team of four, six months.",
        bullets=(),
        state=SnippetState.DEGRADED,
        source_text=SOURCE,
        kind=SourceKind.COMPANY,
    )

    rendered = view.display_headline
    assert rendered.index(DEGRADED_GLYPH) < rendered.index(mark_for(SourceKind.COMPANY).glyph)
    assert rendered.endswith("Team of four, six months.")


def test_the_mark_is_not_part_of_the_stored_text(qapp: QApplication) -> None:
    """FR11's substring check must see what the user wrote, not what the panel drew.

    The glyph is prepended at display time for exactly this reason — stored into the
    headline it would either fail the check or, worse, have to be exempted from it.
    """
    view = SnippetView(
        headline="Team of four, six months.",
        bullets=(),
        state=SnippetState.CONFIRMED,
        source_text=SOURCE,
        kind=SourceKind.PREP,
    )

    assert all(mark_for(SourceKind.PREP).glyph not in s for s in view.rendered_strings)


def test_the_no_match_line_is_unmarked(qapp: QApplication) -> None:
    """FR35's line is product copy from no source at all. Marking it with a kind would
    be a false claim about provenance on the one view that has none."""
    view = no_match_view()

    assert view.kind is None
    assert view.mark is None
    assert view.display_headline == NO_MATCH_TEXT


def test_marking_the_no_match_line_with_a_kind_is_refused() -> None:
    """The invariant behind the unmarked no-match line, asserted rather than trusted to
    the one constructor that currently honours it."""
    with pytest.raises(RenderError, match="provenance"):
        SnippetView(
            headline=NO_MATCH_TEXT,
            bullets=(),
            state=SnippetState.NO_MATCH,
            source_text="",
            kind=SourceKind.PREP,
        )


def test_clearing_drops_the_previous_snippets_source_label(qapp: QApplication) -> None:
    """The tooltip is state on a reused widget, so the no-match line would otherwise
    still claim to have come from the last snippet's source."""
    panel = OverlayPanel()
    panel.show_snippet(
        SnippetView(
            headline="Team of four, six months.",
            bullets=(),
            state=SnippetState.CONFIRMED,
            source_text=SOURCE,
            kind=SourceKind.RESUME,
        ),
        now=0.0,
    )
    assert mark_for(SourceKind.RESUME).label in panel.headline.toolTip()

    panel.clear()

    assert panel.headline.toolTip() == ""


def test_the_panel_renders_a_distinct_headline_per_kind(qapp: QApplication) -> None:
    """The end of the chain: the same stored text under five kinds paints five different
    headlines. Asserted on the widget rather than on the view, because the mark reaching
    `display_headline` and never reaching the label is exactly the failure mode T7.4's
    review found in the checklist feed."""
    panel = OverlayPanel()
    painted = set()

    for kind in SourceKind:
        panel.show_snippet(
            SnippetView(
                headline="Team of four, six months.",
                bullets=(),
                state=SnippetState.CONFIRMED,
                source_text=SOURCE,
                kind=kind,
            ),
            now=0.0,
        )
        painted.add(panel.headline.text())

    assert len(painted) == len(SourceKind)


def test_the_mark_is_learnable_from_the_panel(qapp: QApplication) -> None:
    """FR72 asks for a glance channel; a glance channel nobody can decode is a private
    code. The label is the reading channel that makes the shapes learnable."""
    panel = OverlayPanel()

    panel.show_snippet(
        SnippetView(
            headline="Team of four, six months.",
            bullets=(),
            state=SnippetState.CONFIRMED,
            source_text=SOURCE,
            kind=SourceKind.INTERVIEWER,
        ),
        now=0.0,
    )

    tooltip = panel.headline.toolTip()
    assert mark_for(SourceKind.INTERVIEWER).glyph in tooltip
    assert mark_for(SourceKind.INTERVIEWER).label in tooltip


def test_a_content_view_without_a_kind_is_refused() -> None:
    """The other half of the same invariant, and the half that fails silently: an
    unmarked confirmed snippet renders correctly and is missing only FR72's mark.

    `from_stored_note` cannot be the sole enforcement point while direct construction
    stays reachable — the field's docstring asserted this and nothing checked it, which
    is the defect shape this file exists to catch. Found by review on PR #23.
    """
    for state in (SnippetState.CONFIRMED, SnippetState.DEGRADED):
        with pytest.raises(RenderError, match="FR72"):
            SnippetView(
                headline="Team of four, six months.",
                bullets=(),
                state=state,
                source_text=SOURCE,
            )
