"""The tracker checklist row (T7.4 — FR12, FR37, design §9b).

The visible half of the progress tracker. `ProgressTracker` decides what is covered;
this renders that decision, and nothing here re-derives it — a second opinion about
coverage is how the checklist and the report come to disagree, and FR78a names the
tracker as the one adjudicator.

**Its own module rather than more of `overlay.py`**, for the reason `indicators.py`
already is: the panel is the thing that composes surfaces, and a 1,100-line widget that
also owns every surface it shows is the file nobody can review. Design §1's module list
does not name this file; neither does it name `indicators.py`, `main_window.py` or
`diagnostics_view.py`, all of which exist for the same reason.

**Colour is never the only channel.** Both states carry a glyph, so a user with a colour
vision deficiency reads the same list. Design §9b asks for a check on the marked rows;
the unmarked rows get a hollow ring so the two are distinguishable by shape *and* so the
text of every row starts at the same x — a list whose items do not line up is not a list
anyone can scan in a glance.

**The marked colour swaps at the brightness crossover**, exactly as design §9b's rails
do. PRISM's `--green-500` measures 8.3:1 on the darkest panel and **1.26:1** on the light
band's edge, so a light-band user would watch their checklist tick over in a colour they
cannot see. The overlay's palette carries both variants and this widget is told which.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontMetrics, QResizeEvent
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from interview_prep_recall.tracker.progress import TrackedPoint

CHECKLIST_FONT_PX = 13
"""Design §9b. Also PRISM's caption size, which is the floor `overlay.MIN_RENDERED_PX`
holds the snippet to — the checklist is read at a glance like everything else here."""

MAX_VISIBLE_ROWS = 5
"""Design §9b: "max 5 rows then scroll". The cap is what stops a 20-point note set from
turning the overlay into a document."""

ROW_SPACING_PX = 2

MARKED_GLYPH = "✓"
UNMARKED_GLYPH = "○"

ELLIPSIS = "…"


class TrackerChecklist(QScrollArea):
    """FR12's checklist, docked below the snippet's bullets.

    A scroll area rather than a plain column because §9b's cap is on *visible* rows, not
    on tracked points: the sixth point has to still be reachable. The widget's height is
    fixed to the rows it may show, so the panel's layout cannot be pushed around by how
    many points the user happens to be tracking.

    **`set_tracking` is FR37's off switch, and off means gone.** Not greyed, not empty:
    a checklist that is present but frozen looks exactly like a checklist of things you
    have not said yet, which is the one reading that would make the user act on it.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        # Horizontal scrolling is off because rows elide instead: a sideways scrollbar on
        # a panel read mid-sentence is a control nobody is going to operate.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # Every widget here states its own background and border, and `_render` keeps
        # them on the panel's surface colour. The border half is what `indicators.py`
        # documents: the panel styles itself with a bare `QWidget { … }` selector
        # carrying FR51's rail as a `border-left`, and a Qt style sheet on a parent
        # reaches every widget under it — so without `border: none` the rail is repainted
        # down the left of the checklist and of every row in it.
        self._body = QWidget(self)
        self._layout = QVBoxLayout(self._body)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(ROW_SPACING_PX)
        self._layout.addStretch(1)
        self.setWidget(self._body)

        self._rows: list[QLabel] = []
        self._points: tuple[TrackedPoint, ...] = ()
        self._tracking = True
        # The dark band's values, replaced by the panel's on the first `_restyle`. Stated
        # rather than left blank so a checklist built and shown before any push still
        # renders in a readable pair.
        self._surface = "#141619"
        self._muted = "#A8ADB5"
        self._marked_colour = "#34C77B"
        self._render()

    # ---------- input ----------

    def set_points(self, points: Sequence[TrackedPoint]) -> None:
        """Replace the checklist. Order is the note set's, unchanged.

        Sorting marked points to the bottom was the obvious idea and it is wrong: the
        list is read while talking, and a list whose items move as you speak has to be
        re-read from the top every time. Position is the only thing that makes it
        glanceable.
        """
        self._points = tuple(points)
        self._render()

    def set_tracking(self, enabled: bool) -> None:
        """FR37's progress-tracker switch."""
        self._tracking = enabled
        self._render()

    def apply_colours(self, surface: str, muted: str, marked: str) -> None:
        """Take the overlay's band colours.

        **The surface is one of them, and leaving it out was a real defect.** A child
        widget carrying a style sheet paints its own rect, so `background: transparent`
        does not reveal the panel's surface underneath — it clears it, and the rows then
        sit on whatever the video call is showing. Found by rendering the panel offscreen
        and sampling the pixels under a row: `#000000` where the rest of the panel was
        `#141619`. Every contrast figure in design §9b is stated against the panel
        colour, so ink on an unpainted rect is not the readability the band promises.

        Painting the surface rather than clearing it also keeps FR24 honest: opacity is a
        window-level property, so a panel-coloured fill composites exactly like the rest
        of the panel instead of becoming a hole in it.
        """
        self._surface = surface
        self._muted = muted
        self._marked_colour = marked
        self._render()

    # ---------- geometry ----------

    @property
    def showing(self) -> bool:
        """Whether the checklist has anything to say. Off, or no tracked points, is
        nothing — and design §9b's "never displaces the snippet" starts here: a checklist
        with no rows must occupy no height at all."""
        return self._tracking and bool(self._points)

    @property
    def row_height(self) -> int:
        metrics = QFontMetrics(self._row_font())
        return metrics.lineSpacing() + ROW_SPACING_PX

    @property
    def visible_rows(self) -> int:
        if not self.showing:
            return 0
        return min(len(self._points), MAX_VISIBLE_ROWS)

    @property
    def reserved_height(self) -> int:
        """The height the panel must find for this widget. Zero when it is not showing.

        Capped at `MAX_VISIBLE_ROWS` rows, which is what makes the cost of the checklist
        bounded no matter how many points the user tracks — the panel can then reserve
        for it without the reservation depending on the note set.
        """
        return self.visible_rows * self.row_height

    # ---------- rendering ----------

    def _row_font(self) -> QFont:
        font = self.font()
        font.setPixelSize(CHECKLIST_FONT_PX)
        return font

    def _render(self) -> None:
        self.setVisible(self.showing)
        surface_style = f"background: {self._surface}; border: none;"
        # Both the scroll area and the body it scrolls: each paints its own rect, so a
        # transparent one anywhere in the chain is a hole through the panel.
        self.setStyleSheet(surface_style)
        self._body.setStyleSheet(surface_style)
        self.setFixedHeight(self.reserved_height)
        font = self._row_font()
        while len(self._rows) < len(self._points):
            label = QLabel("", self._body)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(False)
            # `count() - 1` keeps every row above the trailing stretch, which is what
            # holds a short list at the top instead of centring it.
            self._layout.insertWidget(self._layout.count() - 1, label)
            self._rows.append(label)
        for index, label in enumerate(self._rows):
            if index >= len(self._points) or not self._tracking:
                label.hide()
                label.setText("")
                continue
            point = self._points[index]
            colour = self._marked_colour if point.mentioned else self._muted
            glyph = MARKED_GLYPH if point.mentioned else UNMARKED_GLYPH
            label.setFont(font)
            label.setStyleSheet(
                f"color: {colour}; border: none; background: {self._surface};"
                f" font-weight: {'600' if point.mentioned else '400'};"
            )
            label.setText(self._elided(f"{glyph} {point.headline}", label))
            label.show()

    def _elided(self, text: str, label: QLabel) -> str:
        """Trim a row to the width the panel has.

        One line, so `QFontMetrics.elidedText` is the right tool here — unlike the
        snippet's bullets, where it would throw away every line but the first. Truncation
        plus a fixed ellipsis, so a rendered row stays a prefix of the note's headline.
        """
        width = self.viewport().width()
        if width <= 0:
            return text
        return QFontMetrics(label.font()).elidedText(text, Qt.TextElideMode.ElideRight, width)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 — Qt override
        """Re-elide on width changes (FR23).

        Without this a row elided at 320px keeps its ellipsis after the user widens the
        panel to 900 — text that clips at a width where it fits, which is the failure
        FR23 names.
        """
        super().resizeEvent(event)
        for index, label in enumerate(self._rows):
            if index < len(self._points) and not label.isHidden():
                point = self._points[index]
                glyph = MARKED_GLYPH if point.mentioned else UNMARKED_GLYPH
                label.setText(self._elided(f"{glyph} {point.headline}", label))

    # ---------- testable surface ----------

    @property
    def rows(self) -> tuple[str, ...]:
        """What is rendered, in order. `isHidden`, not `isVisible`, for the reason
        `OverlayPanel.visible_bullet_count` states: the second answers "is this on
        screen", and the question here is what the widget chose to show."""
        return tuple(label.text() for label in self._rows if not label.isHidden())

    @property
    def ink_labels(self) -> tuple[QLabel, ...]:
        """The rows, for the panel's sub-70%-opacity halo.

        Checklist rows are ink over the same uncontrolled video as the bullets, so
        leaving them out would apply the readability promise to two thirds of the
        panel's text and quietly not to the rest.
        """
        return tuple(self._rows)

    @property
    def marked_count(self) -> int:
        return sum(1 for point in self._points if point.mentioned)

    def visual_state(self) -> tuple[str, ...]:
        return (
            "checklist",
            "on" if self._tracking else "off",
            self._surface,
            *(
                f"{MARKED_GLYPH if p.mentioned else UNMARKED_GLYPH}|"
                f"{self._marked_colour if p.mentioned else self._muted}|{p.headline}"
                for p in self._points
            ),
        )
