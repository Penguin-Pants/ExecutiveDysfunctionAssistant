"""T7.4 — the tracker checklist in the overlay (FR12, FR37, design §9b).

Three properties carry the task's acceptance criteria and each is measured rather than
described:

* **It never displaces the snippet.** The bullets' line allowance is what elision is
  computed from, so the check is that adding a checklist does not reduce it — not that
  the widget "looks docked".
* **Max 5 rows, then scroll.** The height reserved is capped at five rows however many
  points are tracked, and the sixth point is still in the scrolled content.
* **FR37's switch removes it.** Off is gone, not greyed: a frozen checklist reads as a
  list of things you have not said yet, which is the one reading a user acts on.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="Qt UI tests require the [ui] extra")

from PySide6.QtWidgets import QApplication  # noqa: E402

from interview_prep_recall.tracker.progress import TrackedPoint  # noqa: E402
from interview_prep_recall.ui.checklist import (  # noqa: E402
    MARKED_GLYPH,
    MAX_VISIBLE_ROWS,
    UNMARKED_GLYPH,
    TrackerChecklist,
)
from interview_prep_recall.ui.overlay import (  # noqa: E402
    DARK_BAND_MAX,
    LIGHT_BAND_MIN,
    MAX_SIZE,
    MIN_BULLET_LINES,
    OverlayGeometry,
    OverlayPanel,
    SnippetState,
    SnippetView,
    bullet_px,
    contrast_ratio,
    palette_for,
)

BODY_TEXT_MIN = 4.5
"""WCAG AA for body text. The rows are 13px body copy, so they are held to it."""

SOURCE = (
    "Led the migration off the monolith. Cut p99 latency from 900ms to 120ms. "
    "Team of four, six months."
)


def points(count: int, marked: int = 0) -> list[TrackedPoint]:
    return [TrackedPoint(f"n{i}", f"talking point {i}", i < marked) for i in range(count)]


def snippet() -> SnippetView:
    return SnippetView(
        headline="Led the migration off the monolith.",
        bullets=("Cut p99 latency from 900ms to 120ms.", "Team of four, six months."),
        state=SnippetState.CONFIRMED,
        source_text=SOURCE,
    )


# ---------- FR12: what the rows say ----------


def test_marked_and_unmarked_rows_differ_by_glyph_as_well_as_colour(qapp: QApplication) -> None:
    """Colour is never the only channel: roughly 8% of men could not tell these apart
    from the green alone."""
    checklist = TrackerChecklist()
    checklist.set_points(points(2, marked=1))

    assert checklist.rows[0].startswith(MARKED_GLYPH)
    assert checklist.rows[1].startswith(UNMARKED_GLYPH)

    states = checklist.visual_state()
    assert states[2] != states[3]


def test_rows_keep_their_position_when_marked(qapp: QApplication) -> None:
    """A list whose items move as you speak has to be re-read from the top every time,
    which is the opposite of glanceable."""
    checklist = TrackerChecklist()
    checklist.set_points(points(3))
    before = [row.split(" ", 1)[1] for row in checklist.rows]

    checklist.set_points(points(3, marked=2))
    after = [row.split(" ", 1)[1] for row in checklist.rows]

    assert before == after
    assert checklist.marked_count == 2


def test_marks_are_read_from_the_tracker_not_remembered(qapp: QApplication) -> None:
    """The tracker is FR78a's one adjudicator. A widget that kept its own marks would
    eventually disagree with the report, and nothing would reconcile them."""
    checklist = TrackerChecklist()
    checklist.set_points(points(2, marked=2))
    checklist.set_points(points(2, marked=0))

    assert checklist.marked_count == 0
    assert all(row.startswith(UNMARKED_GLYPH) for row in checklist.rows)


# ---------- design §9b: max 5 rows, then scroll ----------


def test_more_than_five_points_reserve_only_five_rows(qapp: QApplication) -> None:
    checklist = TrackerChecklist()
    checklist.set_points(points(MAX_VISIBLE_ROWS + 3))

    assert checklist.visible_rows == MAX_VISIBLE_ROWS
    assert checklist.reserved_height == MAX_VISIBLE_ROWS * checklist.row_height


def test_the_sixth_point_is_scrolled_to_rather_than_dropped(qapp: QApplication) -> None:
    """The cap is on *visible* rows. Dropping the overflow would make the checklist
    silently lie about how much is left to cover."""
    checklist = TrackerChecklist()
    checklist.set_points(points(MAX_VISIBLE_ROWS + 1))

    assert len(checklist.rows) == MAX_VISIBLE_ROWS + 1
    assert checklist.widget().sizeHint().height() > checklist.height()


def test_fewer_points_reserve_less(qapp: QApplication) -> None:
    checklist = TrackerChecklist()
    checklist.set_points(points(2))

    assert checklist.reserved_height == 2 * checklist.row_height


def test_no_tracked_points_takes_no_height_at_all(qapp: QApplication) -> None:
    """A note set with nothing tracked must cost the snippet nothing."""
    checklist = TrackerChecklist()
    checklist.set_points([])

    assert checklist.showing is False
    assert checklist.reserved_height == 0


# ---------- FR37: the off switch ----------


def test_switching_tracking_off_removes_the_checklist(qapp: QApplication) -> None:
    checklist = TrackerChecklist()
    checklist.set_points(points(3))
    assert checklist.showing is True

    checklist.set_tracking(False)

    assert checklist.showing is False
    assert checklist.rows == ()
    assert checklist.reserved_height == 0


def test_switching_tracking_back_on_restores_the_rows(qapp: QApplication) -> None:
    """FR37 is mid-session and both ways: a switch that only turns off is a restart."""
    checklist = TrackerChecklist()
    checklist.set_points(points(3, marked=1))
    checklist.set_tracking(False)

    checklist.set_tracking(True)

    assert len(checklist.rows) == 3
    assert checklist.marked_count == 1


def test_the_panel_pushes_the_switch_through(qapp: QApplication) -> None:
    panel = OverlayPanel()
    panel.set_tracked_points(points(3), True)
    assert panel.checklist.showing is True

    panel.set_tracked_points(points(3), False)

    assert panel.checklist.showing is False
    assert panel.rendered_height == panel.geometry_settings.height


# ---------- design §9b: never displaces the snippet ----------


def test_the_panel_grows_by_exactly_what_the_checklist_reserved(qapp: QApplication) -> None:
    panel = OverlayPanel()
    panel.show_snippet(snippet(), now=0.0)
    before = panel.rendered_height

    panel.set_tracked_points(points(3))

    assert panel.rendered_height == before + panel.checklist.reserved_height


def test_the_bullets_keep_their_allowance_when_a_checklist_appears(qapp: QApplication) -> None:
    """The property FR12's "never displaces the snippet" actually means: the space the
    bullets are elided against does not shrink because points were tracked."""
    panel = OverlayPanel()
    panel.show_snippet(snippet(), now=0.0)
    size = bullet_px(panel.geometry_settings.height)
    before = panel.bullet_lines_available(size)

    panel.set_tracked_points(points(MAX_VISIBLE_ROWS))

    assert panel.bullet_lines_available(size) == before


def test_the_rendered_bullet_text_is_unchanged_by_the_checklist(qapp: QApplication) -> None:
    """The allowance is the mechanism; this is the behaviour a user would notice."""
    panel = OverlayPanel()
    panel.show_snippet(snippet(), now=0.0)
    before = [label.text() for label in panel.bullets]

    panel.set_tracked_points(points(MAX_VISIBLE_ROWS))

    assert [label.text() for label in panel.bullets] == before


def test_the_users_stored_height_is_not_changed_by_the_checklist(qapp: QApplication) -> None:
    """FR26 persists what the user chose. Growing `geometry_settings` instead would save
    the checklist's height as if they had dragged the panel taller — and it would compound
    on every restart."""
    panel = OverlayPanel(OverlayGeometry(width=420, height=220))

    panel.set_tracked_points(points(4))

    assert panel.geometry_settings.height == 220
    assert panel.rendered_height > 220


def test_growth_stops_at_the_fr23_maximum(qapp: QApplication) -> None:
    panel = OverlayPanel(OverlayGeometry(width=420, height=MAX_SIZE[1]))

    panel.set_tracked_points(points(MAX_VISIBLE_ROWS))

    assert panel.rendered_height == MAX_SIZE[1]


def test_at_the_maximum_the_bullets_elide_and_never_drop_below_the_floor(
    qapp: QApplication,
) -> None:
    """The one case where the panel cannot grow. The bullets give way — by eliding, which
    is FR23's behaviour — and never past the two-line floor."""
    panel = OverlayPanel(OverlayGeometry(width=420, height=MAX_SIZE[1]))
    panel.show_snippet(snippet(), now=0.0)

    panel.set_tracked_points(points(MAX_VISIBLE_ROWS))

    assert panel.bullet_lines_available(bullet_px(MAX_SIZE[1])) >= MIN_BULLET_LINES


def test_the_bottom_resize_edge_follows_the_grown_panel(qapp: QApplication) -> None:
    """The edge the user can grab is the bottom of the window. Hit-testing the stored
    height would put the resize band inside the checklist and leave the real edge inert."""
    from PySide6.QtCore import QPoint

    from interview_prep_recall.ui.overlay import Edge

    panel = OverlayPanel(OverlayGeometry(width=420, height=220))
    panel.set_tracked_points(points(3))

    at_bottom = QPoint(200, panel.rendered_height - 1)

    assert Edge.BOTTOM in panel.allowed_edges(at_bottom)


# ---------- FR65: the marked colour is readable in both bands ----------


@pytest.mark.parametrize("brightness", list(range(0, 101)))
def test_the_marked_colour_is_readable_at_every_brightness(brightness: int) -> None:
    """PRISM's `--green-500` measures 1.26:1 on the light band's edge. Without a variant
    swap the checklist would tick over in a colour a light-band user cannot see."""
    palette = palette_for(brightness)

    assert contrast_ratio(palette.marked, palette.panel) >= BODY_TEXT_MIN, (
        f"marked colour fails at brightness {brightness}"
    )


def test_the_marked_colour_swaps_at_the_crossover() -> None:
    assert palette_for(DARK_BAND_MAX).marked != palette_for(LIGHT_BAND_MIN).marked


def test_the_panel_repaints_the_checklist_when_brightness_changes(qapp: QApplication) -> None:
    """A colour applied once at construction would be the dark band's forever."""
    from dataclasses import replace

    panel = OverlayPanel(OverlayGeometry(brightness=DARK_BAND_MAX))
    panel.set_tracked_points(points(2, marked=1))
    dark = panel.checklist.visual_state()

    panel.apply_geometry(replace(panel.geometry_settings, brightness=LIGHT_BAND_MIN))

    assert panel.checklist.visual_state() != dark


def test_the_rows_are_painted_on_the_panel_surface(qapp: QApplication) -> None:
    """Every contrast figure in design §9b is stated against the panel colour, so ink on
    an unpainted rect is not the readability the band promises.

    A rendered pixel rather than the style sheet string, because the defect this catches
    was a style sheet that read correctly — `background: transparent` — and cleared the
    panel's surface instead of revealing it. Grabbed from the **panel**, not from the
    checklist: grabbing a child renders it against its parent's palette and reports the
    surface either way, which is how the first version of this test passed against the
    defect it was written for.
    """
    panel = _opaque_panel(brightness=0)
    panel.set_tracked_points(points(MAX_VISIBLE_ROWS + 1))

    assert _checklist_surface(panel) == palette_for(0).panel.lower()


def test_the_surface_follows_the_brightness_band(qapp: QApplication) -> None:
    """A fixed surface would be a dark rectangle on a light panel — the same defect in
    the other direction."""
    from dataclasses import replace

    panel = _opaque_panel(brightness=0)
    panel.set_tracked_points(points(MAX_VISIBLE_ROWS + 1))
    panel.apply_geometry(replace(panel.geometry_settings, brightness=100))

    assert _checklist_surface(panel) == palette_for(100).panel.lower()


def _opaque_panel(*, brightness: int) -> OverlayPanel:
    """A panel that renders its surface into a grab.

    `WA_TranslucentBackground` is what the product ships and what makes the panel sit
    over a video call; it also means an offscreen grab returns transparent black
    everywhere the compositor would show the call through. Turning it off is what makes
    "is this pixel the panel's colour" a question with an answer at all.

    Returned **unshown**, and `_checklist_surface` shows it. An unshown panel grabs as if
    every child painted its parent's colour, and a panel shown before its rows exist does
    too — the first two versions of this test passed identically against the defect they
    were written for. Points first, then the show, is the ordering where a child that
    clears its rect actually leaves a black one.
    """
    from PySide6.QtCore import Qt

    panel = OverlayPanel(OverlayGeometry(x=0, y=0, brightness=brightness))
    panel.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
    return panel


def _checklist_surface(panel: OverlayPanel) -> str:
    """The rendered colour inside the checklist, sampled where no glyph reaches."""
    panel.show()
    QApplication.processEvents()
    image = panel.grab().toImage()
    box = panel.checklist.geometry()
    return str(image.pixelColor(box.right() - 2, box.bottom() - 2).name()).lower()


def test_the_halo_reaches_the_checklist_rows(qapp: QApplication) -> None:
    """Below 70% opacity the ink gets a contrasting halo. Rows are ink over the same
    uncontrolled video, so leaving them bare would apply the promise to part of the
    panel's text and quietly not to the rest."""
    panel = OverlayPanel(OverlayGeometry(opacity=0.4))
    panel.set_tracked_points(points(2))

    assert panel.halo_engaged is True
    assert all(label.graphicsEffect() is not None for label in panel.checklist.ink_labels)


# ---------- FR23: rows follow the panel's width ----------


def test_a_long_row_is_elided_rather_than_clipped(qapp: QApplication) -> None:
    checklist = TrackerChecklist()
    checklist.resize(120, 100)
    checklist.set_points([TrackedPoint("n0", "a talking point with a very long headline " * 3)])

    assert checklist.rows[0].endswith("…")


def test_widening_the_panel_restores_an_elided_row(qapp: QApplication) -> None:
    """Text that clips at a width where it fits is the failure FR23 names."""
    long_point = [TrackedPoint("n0", "a talking point with a moderately long headline")]
    checklist = TrackerChecklist()
    checklist.resize(120, 100)
    checklist.set_points(long_point)
    narrow = checklist.rows[0]

    checklist.resize(880, 100)

    assert checklist.rows[0] != narrow
    assert not checklist.rows[0].endswith("…")
