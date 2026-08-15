"""The overlay panel (T5.1, T5.3, T5.4, T5.5, T5.6 — FR11, FR13, FR22–27, FR51, FR54, FR55, FR65).

The product's one visible surface during an interview, and the place where the
**retrieval-only guarantee** either holds or does not. Everything upstream — the forced
`tool_choice` with an enum of note ids, the byte-exact substring assertions — exists so
that nothing reaching this widget was generated. `SnippetView.rendered_strings` is where
that is checked one last time, at the boundary, because a guarantee enforced only in the
layer that produces text is a guarantee that survives exactly until someone adds a second
producer.

**Neutral gray, not PRISM's plum (D-U7).** A saturated surface tints whatever is behind
it, and behind this one is a live video call. Design §9b: PRISM still governs typography,
radius, spacing and the semantic rail colours, so it reads as the same product without
colouring the feed.

**Brightness is two bands, not one ramp, and that is a readability guarantee.** At mid-gray
neither ink clears 4.5:1 for body text (design §9b measures 4.39:1 and 3.71:1), so a naive
slider lets the user park the overlay on a setting where it cannot be read — on the one
surface whose entire purpose is being read in under a second. The control therefore
*steps over* 26–74 rather than stopping there, and the rails swap variants at the
crossover because `--amber-500` is near-invisible on a light ground. `contrast_ratio` is
implemented here rather than trusted from the design table so the tests can **verify** the
bands instead of restating them.

**Auto-clear is pull-based** (`tick(now)`), like `UtteranceAssembler`. Nothing is emitted
from a background timer, so the FR54 behaviour is testable against a fake clock rather
than a `sleep`.

**Direct manipulation is split from its Qt events (T5.4).** Drag and edge-resize live in
`begin_manipulation` / `update_manipulation` / `end_manipulation`, which take plain
points; `mousePressEvent` and friends only translate. A frameless window has no title bar
and no system resize grips, so this code *is* the window manager for this panel — and a
window manager that can only be tested by synthesising OS mouse events is one whose
off-screen and clamping behaviour never gets tested.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum, auto

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFontMetrics, QMouseEvent
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from interview_prep_recall.session.health import Health
from interview_prep_recall.ui.indicators import IndicatorBar

# ---------- design §9b tokens ----------

MAX_BULLETS = 3
"""FR11. The panel is glanceable or it is useless."""

TAU_VISIBLE_S = 25.0
"""FR54 default. Configurable; see OQ-2, which revisits it after real interview pacing."""

TRANSITION_MS = 180
DEFAULT_SIZE = (420, 220)
MIN_SIZE = (320, 120)
MAX_SIZE = (900, 600)
CORNER_RADIUS_PX = 20
PADDING_PX = 16
RAIL_WIDTH_PX = 3

TOP_MARGIN_PX = 48
"""FR22's default position is *top*-center. Not flush to the edge: a panel at y=0 sits
under the Windows 11 snap-layout flyout, which opens on hover over any maximised window's
maximise button and would cover the overlay exactly when a call is being arranged."""

RESIZE_MARGIN_PX = 8
"""How close to an edge a press counts as a resize rather than a drag (FR23).

A frameless window has no system resize grips, so this margin is the only affordance.
8px is the smallest band that a trackpad user can reliably hit; below that the panel
reads as un-resizable."""

HEADLINE_PX_RANGE = (14, 22)
BULLET_PX_RANGE = (13, 18)
"""Design §9b's text scaling (FR23): sizes interpolate linearly with panel *height*
between MIN_SIZE[1] and MAX_SIZE[1] and clamp outside. Width drives wrapping, height
drives size, so FR23's resize and FR24's opacity stay orthogonal."""

MIN_RENDERED_PX = 13
"""PRISM's caption size is the floor. Below it the overlay stops being glanceable, which
is the only thing it exists to be — so `BULLET_PX_RANGE` starts here and a test holds it."""

MIN_BULLET_LINES = 2
"""Design §9b's two-line allowance, as a **floor rather than a cap** (D-51).

§9b states it without qualifying the height: "a bullet clips only after scaling has hit
the floor: 2 lines maximum, then ellipsis". Read as a flat cap that is wrong at every
size above the minimum — the font is a function of height alone (§9b's second rule), so
"after scaling has hit the floor" is not an event elision can wait for, and a 600px panel
would clip text into two lines with most of its height empty. That is precisely the
clipping FR23 forbids.

So the allowance is computed from the space the panel actually has, and never drops below
this. At the minimum size the computed value *is* two, which is the height §9b's sentence
was written about."""

ELLIPSIS = "…"

DEGRADED_GLYPH = "~"
"""FR51's second channel. Colour alone fails for a colour-blind user, and the rails differ
in hue rather than luminance — so the degraded state carries a glyph as well."""

NO_MATCH_TEXT = "Nothing in your notes matched that."
"""FR35/OB-1: **never a blank panel.** A blank overlay is indistinguishable from a crashed
one, and the user cannot debug it mid-interview."""

DARK_BAND_MAX = 25
LIGHT_BAND_MIN = 75
DEFAULT_BRIGHTNESS = 12
"""Design §9b: FR11's "dark semi-transparent panel, high-contrast light text"."""

HALO_OPACITY_THRESHOLD = 0.70
"""Below this the panel composites with content nobody controls, so the measured contrast
figures stop being guarantees. Ink gets a 1 px contrasting halo — the technique broadcast
captions use — and the settings copy says the figures are best-effort. An honest limit
stated is better than a promise the physics does not support."""


class SnippetState(Enum):
    """FR51. Two content states plus the one the design insists is never blank."""

    CONFIRMED = "confirmed"
    """Stage 2 selected this note."""

    DEGRADED = "degraded"
    """FR49's stage-1 fallback. The user must be able to tell, without reading."""

    NO_MATCH = "no_match"


@dataclass(frozen=True)
class OverlayPalette:
    panel: str
    ink: str
    muted: str
    confirmed_rail: str
    degraded_rail: str

    def rail_for(self, state: SnippetState) -> str | None:
        if state is SnippetState.CONFIRMED:
            return self.confirmed_rail
        if state is SnippetState.DEGRADED:
            return self.degraded_rail
        return None


DARK_BAND = (
    OverlayPalette("#141619", "#F2F4F6", "#A8ADB5", "#2D7DF6", "#FFC93D"),
    OverlayPalette("#2A2D31", "#F2F4F6", "#A8ADB5", "#2D7DF6", "#FFC93D"),
)
LIGHT_BAND = (
    OverlayPalette("#C2C5CA", "#15171B", "#4A4F57", "#0B4EA8", "#8A5A00"),
    OverlayPalette("#E8EAEE", "#15171B", "#4A4F57", "#0B4EA8", "#8A5A00"),
)


def _srgb_channel(value: float) -> float:
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_colour: str) -> float:
    """WCAG 2.x relative luminance."""
    raw = hex_colour.lstrip("#")
    r, g, b = (int(raw[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _srgb_channel(r) + 0.7152 * _srgb_channel(g) + 0.0722 * _srgb_channel(b)


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG contrast ratio.

    Implemented rather than taken from design §9b's table so the tests can *verify* the
    brightness bands. A table copied into an assertion checks that someone transcribed it
    correctly, which is not the property anyone cares about.
    """
    a, b = relative_luminance(foreground), relative_luminance(background)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def clamp_brightness(value: int) -> int:
    """Snap out of the unreadable middle (design §9b).

    The control **steps over** 26–74 rather than stopping there: the user experiences one
    slider crossing a threshold, not two settings. Values land on whichever band edge is
    nearer, so dragging upward through the gap arrives in the light band and dragging back
    returns to the dark one.
    """
    value = max(0, min(100, value))
    if DARK_BAND_MAX < value < LIGHT_BAND_MIN:
        midpoint = (DARK_BAND_MAX + LIGHT_BAND_MIN) / 2
        return LIGHT_BAND_MIN if value >= midpoint else DARK_BAND_MAX
    return value


def palette_for(brightness: int) -> OverlayPalette:
    """The palette for a brightness setting.

    **Two stops per band, not a continuous interpolation.** An earlier docstring here
    said "interpolated"; the code picks the nearer stop, and a docstring describing a
    behaviour the code does not have is the defect this project keeps finding. Discrete
    stops are also the right design: the measured contrast figures in design §9b are
    stated for these exact panel colours, and interpolating between them would produce
    values nobody measured.
    """
    brightness = clamp_brightness(brightness)
    if brightness <= DARK_BAND_MAX:
        band, position = DARK_BAND, brightness / DARK_BAND_MAX if DARK_BAND_MAX else 0.0
    else:
        band = LIGHT_BAND
        span = 100 - LIGHT_BAND_MIN
        position = (brightness - LIGHT_BAND_MIN) / span if span else 0.0
    # Two stops per band, and the panel is the only channel that moves: ink and rails are
    # fixed per band precisely so their measured contrast holds across the whole band.
    return band[0] if position < 0.5 else band[1]


def scaled_px(height: int, size_range: tuple[int, int]) -> int:
    """Design §9b's `size(h)`, for FR23's "text scales rather than clipping".

    The design states this as a formula *and* as a table of three anchor heights, and the
    two disagree by 1px on the bullets at the default height (the formula gives 14, the
    table says 15). The formula is what §9b calls checkable, and a table transcribed into
    an assertion checks transcription rather than behaviour — so the formula governs and
    the table now carries the correction. See D-45.
    """
    low, high = size_range
    span = MAX_SIZE[1] - MIN_SIZE[1]
    raw = low + (high - low) * (height - MIN_SIZE[1]) / span
    return int(round(max(low, min(high, raw))))


def headline_px(height: int) -> int:
    return scaled_px(height, HEADLINE_PX_RANGE)


def bullet_px(height: int) -> int:
    return scaled_px(height, BULLET_PX_RANGE)


def line_count(text: str, metrics: QFontMetrics, width: int) -> int:
    """How many wrapped lines `text` needs at `width`. 0 for empty text."""
    if not text or width <= 0:
        return 0 if not text else 1
    box = metrics.boundingRect(0, 0, width, 0, int(Qt.TextFlag.TextWordWrap), text)
    return max(1, round(box.height() / max(1, metrics.lineSpacing())))


def elide_to_lines(
    text: str, metrics: QFontMetrics, width: int, max_lines: int = MIN_BULLET_LINES
) -> str:
    """Trim `text` to at most `max_lines` wrapped lines, ending in an ellipsis.

    The last resort, not the first (design §9b): the caller passes the allowance the panel
    actually has at its current size, and only text exceeding *that* is cut. A binary
    search over the cut point rather than `QFontMetrics.elidedText`, which elides to a
    *single* line and would throw away every other line the panel could show.

    **This is the one place a rendered string is not byte-identical to the stored note**,
    and it stays inside FR11 because the only operations are *truncation* and appending
    `ELLIPSIS`: what remains is a prefix of what the user wrote, and the ellipsis is fixed
    product copy that no note content can forge into something else. Nothing is
    substituted, reordered or rephrased. A test holds that property, because "we only cut
    from the end" is exactly the kind of claim that survives until someone adds a smarter
    middle-elide.
    """
    if max_lines < 1:
        raise ValueError("max_lines must be >= 1")
    if line_count(text, metrics, width) <= max_lines:
        return text
    low, high = 0, len(text)
    best = ""
    while low <= high:
        mid = (low + high) // 2
        candidate = text[:mid].rstrip() + ELLIPSIS
        if line_count(candidate, metrics, width) <= max_lines:
            best = candidate
            low = mid + 1
        else:
            high = mid - 1
    return best or ELLIPSIS


@dataclass(frozen=True)
class ScreenBounds:
    """The usable area of the display the overlay lives on.

    A value type rather than a `QScreen`, so FR22's default placement and FR55's recovery
    are testable against a stated geometry instead of whatever display the test host has.
    """

    x: int
    y: int
    width: int
    height: int

    @classmethod
    def of(cls, widget: QWidget) -> ScreenBounds | None:
        """The widget's screen, or the primary one, or `None` on a host with no screens.

        `None` rather than a made-up 1920×1080: a default position derived from an
        invented display is worse than the fixed fallback, because it looks deliberate.
        """
        screen = widget.screen()
        if screen is None:
            from PySide6.QtGui import QGuiApplication

            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return None
        area = screen.availableGeometry()
        return cls(area.x(), area.y(), area.width(), area.height())


class RenderError(ValueError):
    """A string reached the panel that is not verbatim from the user's notes."""


@dataclass(frozen=True)
class SnippetView:
    """What the panel is asked to show.

    **The check here is a consistency check, not the guarantee.** Every rendered string
    must be a byte-exact substring of `source_text` — but `source_text` is supplied by the
    same caller, so a producer that passed generated text as both would satisfy it
    trivially. An earlier version of this docstring claimed the boundary enforced
    retrieval-only on its own; it does not, and saying so was the more dangerous half of
    the mistake.

    **`from_stored_note` is the guarantee.** It resolves the source text from the note
    store by id, so the text being rendered is checked against what is actually persisted
    rather than against whatever the caller asserted. Construct through it on any path
    that renders user content; direct construction is for the fixed product copy in
    `no_match_view` and for tests. Found by review on PR #20.
    """

    headline: str
    bullets: tuple[str, ...]
    state: SnippetState
    source_text: str = ""
    """The stored chunk these strings came from. Empty only for `NO_MATCH`, which renders
    fixed product copy rather than user content."""

    note_id: str = ""

    def __post_init__(self) -> None:
        if len(self.bullets) > MAX_BULLETS:
            raise RenderError(f"FR11 allows at most {MAX_BULLETS} bullets, got {len(self.bullets)}")
        if self.state is SnippetState.NO_MATCH:
            return
        for rendered in self.rendered_strings:
            if rendered and rendered not in self.source_text:
                raise RenderError(
                    f"{rendered!r} is not a byte-exact substring of the stored note. "
                    "The overlay renders retrieved text only (FR11)."
                )

    @property
    def rendered_strings(self) -> tuple[str, ...]:
        return (self.headline, *self.bullets)

    @property
    def display_headline(self) -> str:
        """FR51's second channel for the degraded state.

        Prepended at display time rather than stored, so the glyph can never be mistaken
        for part of the user's text — and so the substring check above sees what the user
        actually wrote.
        """
        if self.state is SnippetState.DEGRADED:
            return f"{DEGRADED_GLYPH} {self.headline}"
        return self.headline


NoteResolver = Callable[[str], str | None]
"""Returns the stored text for a note id, or None if there is no such note."""


class UnknownNoteError(RenderError):
    """A snippet claimed a note id the store does not have."""


def from_stored_note(
    resolve: NoteResolver,
    note_id: str,
    headline: str,
    bullets: tuple[str, ...],
    state: SnippetState,
) -> SnippetView:
    """Build a view whose source text comes from the **store**, not from the caller.

    This is where FR11's retrieval-only guarantee actually lives. `SnippetView`'s own
    check compares the rendered strings against a `source_text` the caller supplied, which
    a fabricating producer would simply supply to match — so the trust boundary has to be
    a lookup the producer does not control.
    """
    source = resolve(note_id)
    if source is None:
        raise UnknownNoteError(
            f"note {note_id!r} is not in the store; the overlay renders stored text only (FR11)."
        )
    return SnippetView(
        headline=headline,
        bullets=bullets,
        state=state,
        source_text=source,
        note_id=note_id,
    )


def no_match_view() -> SnippetView:
    return SnippetView(
        headline=NO_MATCH_TEXT, bullets=(), state=SnippetState.NO_MATCH, source_text=""
    )


@dataclass
class OverlayGeometry:
    """FR26. Position, size, opacity and brightness across restarts.

    Design §4 exempts `QSettings` from the no-persistence principle explicitly: this is
    window chrome, not session content, and losing it every launch would make the overlay
    hostile to the person it is for.
    """

    x: int = 100
    y: int = 100
    width: int = DEFAULT_SIZE[0]
    height: int = DEFAULT_SIZE[1]
    opacity: float = 1.0
    brightness: int = DEFAULT_BRIGHTNESS
    locked: bool = False

    def clamped(self) -> OverlayGeometry:
        """FR23's size range, plus the brightness and opacity bounds.

        **Position is deliberately not clamped here.** An earlier version of this
        docstring claimed clamping made an off-screen position recoverable, which the code
        never did — clamping to a screen needs the screen list, and a persisted position
        can be legitimately off the *primary* display on a multi-monitor setup. FR27's
        answer is `reset()`, and that is what implements it.
        """
        return OverlayGeometry(
            x=self.x,
            y=self.y,
            width=max(MIN_SIZE[0], min(MAX_SIZE[0], self.width)),
            height=max(MIN_SIZE[1], min(MAX_SIZE[1], self.height)),
            opacity=max(0.2, min(1.0, self.opacity)),
            brightness=clamp_brightness(self.brightness),
            locked=self.locked,
        )

    def top_centred(self, bounds: ScreenBounds) -> OverlayGeometry:
        """FR22's default placement: horizontally centred, near the top of the screen.

        Applied to the *clamped* size, so a persisted width outside FR23's range cannot
        push the centred panel off the side of the display it was just recovered onto.
        """
        clamped = self.clamped()
        return replace(
            clamped,
            x=bounds.x + (bounds.width - clamped.width) // 2,
            y=bounds.y + TOP_MARGIN_PX,
        )

    def reset(self, bounds: ScreenBounds | None = None) -> OverlayGeometry:
        """FR55. Back to defaults, keeping nothing that could still be unreachable.

        Position and lock go, because those are what make the panel unreachable. Size,
        opacity and brightness **stay**: they are preferences, and none of them can hide
        the overlay, so discarding them would make reset cost more than it fixes. Found by
        review on PR #20.

        With `bounds` the position becomes FR22's top-centre on that screen; without it,
        the fixed fallback. Reset is the recovery route for coordinates persisted off the
        current display (FR55), so recovering onto a *stated* screen is the whole point —
        the no-bounds path exists only for a host that reports no screens at all.
        """
        recovered = OverlayGeometry(
            width=self.width,
            height=self.height,
            opacity=self.opacity,
            brightness=self.brightness,
        )
        return recovered.top_centred(bounds) if bounds else recovered


SETTINGS_KEYS = ("x", "y", "width", "height", "opacity", "brightness", "locked")

SETTINGS_ORGANISATION = "InterviewPrepRecall"
SETTINGS_APPLICATION = "Overlay"


def default_settings() -> object:
    """The production `QSettings` for overlay chrome (design §4's registry row).

    Returned as `object` because everything here writes through `setValue`/`value` and
    takes a dict double in tests — the store is an implementation detail of FR26, and
    typing the callers to `QSettings` would make the double a lie rather than a stand-in.
    """
    from PySide6.QtCore import QSettings

    return QSettings(SETTINGS_ORGANISATION, SETTINGS_APPLICATION)


def save_geometry(settings: object, geometry: OverlayGeometry) -> None:
    """Write to anything with `setValue` — `QSettings` in production, a dict double in
    tests. FR26 is about the values surviving, not about the registry."""
    for key in SETTINGS_KEYS:
        settings.setValue(f"overlay/{key}", getattr(geometry, key))  # type: ignore[attr-defined]


def load_geometry(settings: object, bounds: ScreenBounds | None = None) -> OverlayGeometry:
    """Read back, clamped. Missing or unreadable values fall back to defaults per key —
    a corrupt registry entry should cost one setting, not the whole layout.

    `bounds` supplies FR22's first-run default: with nothing persisted the panel opens
    top-centre on that screen. It is only a *default*, so a persisted position still
    wins — FR26 outranks FR22 on every run after the first, and FR55's reset is the way
    back.
    """
    defaults = OverlayGeometry().top_centred(bounds) if bounds else OverlayGeometry()
    values: dict[str, object] = {}
    for key in SETTINGS_KEYS:
        raw = settings.value(f"overlay/{key}", getattr(defaults, key))  # type: ignore[attr-defined]
        values[key] = raw
    return OverlayGeometry(
        x=_as_int(values["x"], defaults.x),
        y=_as_int(values["y"], defaults.y),
        width=_as_int(values["width"], defaults.width),
        height=_as_int(values["height"], defaults.height),
        opacity=_as_float(values["opacity"], defaults.opacity),
        brightness=_as_int(values["brightness"], defaults.brightness),
        locked=_as_bool(values["locked"], defaults.locked),
    ).clamped()


def _as_int(value: object, default: int) -> int:
    # `QSettings` round-trips through strings on some backends, so "420" has to parse.
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _as_float(value: object, default: float) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _as_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1"}:
        return True
    if text in {"false", "0"}:
        return False
    return default


class Edge(Enum):
    """Which border a press grabbed (FR23's edge-drag resize)."""

    LEFT = auto()
    RIGHT = auto()
    TOP = auto()
    BOTTOM = auto()


MOVING_EDGES = frozenset({Edge.LEFT, Edge.TOP})
"""Dragging these moves the panel's origin as well as its size, so FR27's lock
withholds them. The lock is about the panel wandering, not about its size — resizing
from the right or bottom leaves the panel exactly where the user put it."""


def edges_at(local: QPoint, width: int, height: int, margin: int = RESIZE_MARGIN_PX) -> set[Edge]:
    """Which resize edges a press at `local` (panel coordinates) grabbed.

    Empty means the press is interior, which is a drag. A press outside the panel grabs
    nothing: a synthesised or stale coordinate must not silently resize from the nearest
    edge.
    """
    if not (0 <= local.x() <= width and 0 <= local.y() <= height):
        return set()
    grabbed: set[Edge] = set()
    if local.x() <= margin:
        grabbed.add(Edge.LEFT)
    elif local.x() >= width - margin:
        grabbed.add(Edge.RIGHT)
    if local.y() <= margin:
        grabbed.add(Edge.TOP)
    elif local.y() >= height - margin:
        grabbed.add(Edge.BOTTOM)
    return grabbed


def resized(start: OverlayGeometry, edges: set[Edge], dx: int, dy: int) -> OverlayGeometry:
    """FR23's resize, with the un-dragged edges pinned.

    Size is clamped to FR23's range **and then** the origin is recomputed from the
    clamped size. Moving `x` by the raw delta and clamping the width separately is the
    obvious version and it is wrong: at the size limit the panel keeps sliding sideways
    while its width no longer changes, so a user dragging the left edge past the minimum
    walks the panel off the screen.
    """
    width = (
        start.width - dx
        if Edge.LEFT in edges
        else start.width + dx
        if Edge.RIGHT in edges
        else start.width
    )
    height = (
        start.height - dy
        if Edge.TOP in edges
        else start.height + dy
        if Edge.BOTTOM in edges
        else start.height
    )
    proposed = replace(start, width=width, height=height).clamped()
    x = start.x + (start.width - proposed.width) if Edge.LEFT in edges else start.x
    y = start.y + (start.height - proposed.height) if Edge.TOP in edges else start.y
    return replace(proposed, x=x, y=y)


_BACK_DIAGONAL = ({Edge.RIGHT, Edge.TOP}, {Edge.LEFT, Edge.BOTTOM})
"""Corners running ↗↙. The other two run ↖↘."""


def _cursor_for(edges: set[Edge]) -> Qt.CursorShape:
    """The resize affordance for a grabbed edge set.

    A frameless window draws no grips, so the cursor is the *only* signal that an edge is
    draggable. Corners get the diagonal cursors; an interior press gets the arrow, because
    a move cursor over the whole panel would suggest the drag is the only thing on offer.
    """
    horizontal = edges & {Edge.LEFT, Edge.RIGHT}
    vertical = edges & {Edge.TOP, Edge.BOTTOM}
    if horizontal and vertical:
        if edges in _BACK_DIAGONAL:
            return Qt.CursorShape.SizeBDiagCursor
        return Qt.CursorShape.SizeFDiagCursor
    if horizontal:
        return Qt.CursorShape.SizeHorCursor
    if vertical:
        return Qt.CursorShape.SizeVerCursor
    return Qt.CursorShape.ArrowCursor


@dataclass
class SnippetTimer:
    """FR54's auto-clear, and FR13's pin that suppresses it.

    Pull-based: `tick(now)` returns whether the snippet should clear. Nothing fires from a
    background timer, so this is testable against a fake clock instead of a `sleep` — the
    same choice `UtteranceAssembler` makes for the same reason.
    """

    tau_visible_s: float = TAU_VISIBLE_S
    shown_at: float | None = None
    pinned: bool = False

    def show(self, now: float) -> None:
        self.shown_at = now
        # A new snippet is not the old one. Carrying the pin across would leave a stale
        # answer on screen with no way for the user to know it was pinned to something
        # they have moved past.
        self.pinned = False

    def clear(self) -> None:
        self.shown_at = None
        self.pinned = False

    def pin(self) -> None:
        self.pinned = True

    def should_clear(self, now: float) -> bool:
        if self.shown_at is None or self.pinned:
            return False
        return (now - self.shown_at) >= self.tau_visible_s


class OverlayPanel(QWidget):
    """Frameless, always-on-top, translucent teleprompter panel (T5.1).

    **Capture exclusion is not here.** `SetWindowDisplayAffinity` is T5.2 and Windows-only;
    this widget is deliberately ignorant of it so the panel can be built and tested
    headless. The affinity call takes a window handle and belongs in
    `platform/win_capture_exclusion.py`.
    """

    def __init__(
        self,
        geometry: OverlayGeometry | None = None,
        *,
        tau_visible_s: float = TAU_VISIBLE_S,
        on_geometry_changed: Callable[[OverlayGeometry], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.timer = SnippetTimer(tau_visible_s=tau_visible_s)
        self.view: SnippetView | None = None
        self.on_geometry_changed = on_geometry_changed
        # Set before `apply_geometry`, which the constructor reaches through `_restyle`.
        self._bullet_texts: tuple[str, ...] = ()
        self._drag_from: QPoint | None = None
        self._press_geometry: OverlayGeometry | None = None
        self._grabbed_edges: set[Edge] = set()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Without this the panel only sees a move event while a button is held, which is
        # enough for dragging but leaves the resize cursor never appearing — so the edge
        # affordance a frameless window depends on would be invisible.
        self.setMouseTracking(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PADDING_PX, PADDING_PX, PADDING_PX, PADDING_PX)

        self.indicators = IndicatorBar(self)
        layout.addWidget(self.indicators)

        self.headline = QLabel("")
        self.headline.setWordWrap(True)
        self.headline.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.headline)

        self.bullets = [QLabel("") for _ in range(MAX_BULLETS)]
        for label in self.bullets:
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.hide()
            layout.addWidget(label)
        layout.addStretch(1)

        # FR22's default is top-centre, and only the widget knows which screen it is on.
        # A caller that supplied geometry keeps it: that is FR26's persisted layout.
        resolved = (geometry or OverlayGeometry()).clamped()
        if geometry is None:
            bounds = ScreenBounds.of(self)
            if bounds is not None:
                resolved = resolved.top_centred(bounds)
        self.geometry_settings = resolved
        self.apply_geometry(self.geometry_settings)
        self._clock_timer: object | None = None

    def start_clock(self, interval_ms: int = 500) -> None:
        """Drive `tick` from the Qt event loop (FR54).

        `tick` was pull-based and **nothing called it**, so an unpinned snippet stayed on
        screen for the whole interview despite the 25 s lifetime — the auto-clear existed
        only in its tests. Found by review on PR #20.

        The timer delegates to the same `tick(now)` rather than reimplementing expiry, so
        the deterministic fake-clock tests still cover the logic that actually runs.
        """
        from PySide6.QtCore import QTimer

        timer = QTimer(self)
        timer.setInterval(interval_ms)
        timer.timeout.connect(self._on_clock_tick)
        timer.start()
        self._clock_timer = timer

    def _on_clock_tick(self) -> None:
        import time

        self.tick(time.monotonic())

    # ---------- content ----------

    def show_snippet(self, view: SnippetView, now: float) -> None:
        """Replace the visible snippet, with FR25's transition rather than a hard pop."""
        replacing = self.view is not None
        self.view = view
        self.timer.show(now)
        self.headline.setText(view.display_headline)
        self._bullet_texts = view.bullets
        for index, label in enumerate(self.bullets):
            if index < len(view.bullets):
                label.show()
            else:
                label.setText("")
                label.hide()
        # Sizes then text: elision depends on the font that is about to be applied, so
        # setting the bullets first would elide against the previous panel height.
        self._rescale_text()
        self._restyle()
        if replacing:
            self.run_transition()

    def run_transition(self) -> None:
        """FR25: a replacement animates. Never a hard pop.

        A cross-fade on the panel's own opacity, restored to the user's FR24 setting at
        the end — animating to 1.0 instead would quietly discard their opacity choice
        every time a snippet changed. Held on the instance because a `QPropertyAnimation`
        that goes out of scope is garbage-collected mid-flight and the effect silently
        stops happening.
        """
        from PySide6.QtCore import QPropertyAnimation

        target = self.geometry_settings.opacity
        animation = QPropertyAnimation(self, b"windowOpacity", self)
        animation.setDuration(TRANSITION_MS)
        animation.setStartValue(max(0.0, target * 0.4))
        animation.setEndValue(target)
        self._animation = animation
        animation.start()

    @property
    def transition_running(self) -> bool:
        from PySide6.QtCore import QAbstractAnimation

        animation = getattr(self, "_animation", None)
        return animation is not None and animation.state() == QAbstractAnimation.State.Running

    def clear(self) -> None:
        """FR13's dismiss. Clears to the no-match view rather than to nothing, because a
        blank panel is indistinguishable from a crashed one (FR35/OB-1)."""
        # `timer.clear()` after, not a fabricated `now`: the no-match line is not a
        # snippet with a lifetime, so it must not be on the auto-clear clock at all.
        self.show_snippet(no_match_view(), now=0.0)
        self.timer.clear()

    def tick(self, now: float) -> bool:
        """Advance FR54's clock. Returns True if the snippet was cleared."""
        if self.timer.should_clear(now):
            self.clear()
            return True
        return False

    @property
    def visible_bullet_count(self) -> int:
        """`isHidden`, not `isVisible`.

        `isVisible()` is False for every child while the top-level window has not been
        shown, so it answers "is this on screen" rather than "did we choose to show it" —
        and the second is what FR11's "at most 3 bullets" is about.
        """
        return sum(1 for label in self.bullets if not label.isHidden())

    # ---------- appearance ----------

    def apply_geometry(self, geometry: OverlayGeometry) -> None:
        self.geometry_settings = geometry.clamped()
        self.setMinimumSize(*MIN_SIZE)
        self.setMaximumSize(*MAX_SIZE)
        self.resize(self.geometry_settings.width, self.geometry_settings.height)
        self.move(self.geometry_settings.x, self.geometry_settings.y)
        self.setWindowOpacity(self.geometry_settings.opacity)
        self._rescale_text()
        self._restyle()

    def move_to(self, geometry: OverlayGeometry) -> None:
        """Position-only update, for FR22's drag.

        Skips the text rescale and the restyle. Both depend on size and brightness and a
        drag changes neither, but `_apply_halo` builds a fresh `QGraphicsDropShadowEffect`
        for four labels every time it runs — at pointer rate, on the surface NFR3
        measures frame time against, with a video call already on the GPU.
        """
        self.geometry_settings = geometry.clamped()
        self.move(self.geometry_settings.x, self.geometry_settings.y)

    def reset_geometry(self) -> OverlayGeometry:
        """FR55's recovery control: back to a top-centred default on the current screen.

        Persists through the same callback a drag does, so the recovered position is what
        the next launch loads — a reset that only survives until restart would leave the
        user back on the off-screen coordinates it just rescued them from.
        """
        recovered = self.geometry_settings.reset(ScreenBounds.of(self))
        self.apply_geometry(recovered)
        self._persist()
        return self.geometry_settings

    # ---------- text scaling (FR23) ----------

    @property
    def text_width(self) -> int:
        """The width text actually wraps in, which is the panel minus its padding."""
        return max(1, self.geometry_settings.width - 2 * PADDING_PX)

    def _rescale_text(self) -> None:
        """Design §9b: height drives size, width drives wrapping.

        Applied to fonts rather than to a stylesheet `font-size`, because elision has to
        measure the font that will actually render — and a stylesheet is not resolved
        until paint, which is after the point where the decision has to be made.
        """
        headline_font = self.headline.font()
        headline_font.setPixelSize(headline_px(self.geometry_settings.height))
        self.headline.setFont(headline_font)

        size = bullet_px(self.geometry_settings.height)
        allowance = self.bullet_lines_available(size)
        for index, label in enumerate(self.bullets):
            font = label.font()
            font.setPixelSize(size)
            label.setFont(font)
            if index >= len(self._bullet_texts):
                continue
            label.setText(
                elide_to_lines(
                    self._bullet_texts[index], QFontMetrics(font), self.text_width, allowance
                )
            )

    def bullet_lines_available(self, bullet_size_px: int) -> int:
        """How many wrapped lines each bullet may use at the panel's current size.

        **Measured, not tabulated.** Design §9b gives a scaling table for font size and
        says nothing about line counts by height, so a table here would be invented. The
        panel's own layout already knows the answer: total height, less the padding, less
        the indicator strip, less the headline, split between the bullets on screen.

        Never below `MIN_BULLET_LINES` — see that constant for why §9b's two-line sentence
        is a floor rather than a cap. A tall panel that clipped bullets to two lines with
        most of its height empty would be the clipping FR23 exists to forbid.
        """
        metrics = QFontMetrics(self.bullets[0].font())
        headline_metrics = QFontMetrics(self.headline.font())
        content = self.geometry_settings.height - 2 * PADDING_PX
        headline_height = (
            line_count(self.headline.text(), headline_metrics, self.text_width)
            * headline_metrics.lineSpacing()
        )
        spare = content - self.indicators.sizeHint().height() - headline_height
        shown = max(1, len(self._bullet_texts))
        # `bullet_size_px` rather than the metrics' own line spacing for the divisor floor:
        # the font on the label has not been updated yet on the first pass, and a stale
        # spacing would misjudge the allowance for the size about to be applied.
        spacing = max(bullet_size_px, metrics.lineSpacing())
        return max(MIN_BULLET_LINES, int(spare // shown) // spacing)

    # ---------- health (FR7, FR20, FR35) ----------

    def update_health(self, health: Health) -> None:
        """Push design §7's record at the indicator bar (T5.7).

        The panel owns the indicators because FR14a's warning is specified as a bar across
        *this* panel's top — the thing the user is looking at — and because an indicator
        surface the user has to go and find is not the persistent one FR20 requires.
        """
        self.indicators.update_health(health)

    # ---------- direct manipulation (FR22, FR23, FR27) ----------

    @property
    def locked(self) -> bool:
        return self.geometry_settings.locked

    def set_locked(self, locked: bool) -> None:
        """FR27's toggle. Ends any manipulation in progress, so locking mid-drag stops the
        panel where it is rather than leaving a grab that resumes on the next move."""
        self.end_manipulation()
        self.apply_geometry(replace(self.geometry_settings, locked=locked))
        self._persist()

    def allowed_edges(self, local: QPoint) -> set[Edge]:
        """Resize edges available at `local`, after FR27's lock has taken its share."""
        grabbed = edges_at(local, self.geometry_settings.width, self.geometry_settings.height)
        if self.locked:
            grabbed -= MOVING_EDGES
        return grabbed

    def begin_manipulation(self, local: QPoint, global_pos: QPoint) -> None:
        """Start a drag or an edge resize. A no-op under the lock unless an edge that
        does not move the panel was grabbed."""
        edges = self.allowed_edges(local)
        if not edges and self.locked:
            return
        self._grabbed_edges = edges
        self._drag_from = global_pos
        self._press_geometry = self.geometry_settings

    @property
    def manipulating(self) -> bool:
        return self._drag_from is not None

    def update_manipulation(self, global_pos: QPoint) -> None:
        """Apply the movement since the press.

        Deltas are measured from the *press* rather than accumulated between moves, so a
        clamp at the size or a dropped move event cannot leave the panel offset from the
        pointer for the rest of the gesture.
        """
        if self._drag_from is None or self._press_geometry is None:
            return
        dx = global_pos.x() - self._drag_from.x()
        dy = global_pos.y() - self._drag_from.y()
        start = self._press_geometry
        if self._grabbed_edges:
            self.apply_geometry(resized(start, self._grabbed_edges, dx, dy))
        else:
            self.move_to(replace(start, x=start.x + dx, y=start.y + dy))

    def end_manipulation(self) -> None:
        """Release, and persist what the user left behind (FR26)."""
        changed = (
            self._press_geometry is not None and self._press_geometry != self.geometry_settings
        )
        self._drag_from = None
        self._press_geometry = None
        self._grabbed_edges = set()
        if changed:
            self._persist()

    def _persist(self) -> None:
        if self.on_geometry_changed is not None:
            self.on_geometry_changed(self.geometry_settings)

    # ---------- Qt event plumbing ----------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 — Qt override
        if event.button() is Qt.MouseButton.LeftButton:
            self.begin_manipulation(event.position().toPoint(), event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 — Qt override
        if self.manipulating:
            self.update_manipulation(event.globalPosition().toPoint())
        else:
            self.setCursor(_cursor_for(self.allowed_edges(event.position().toPoint())))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 — Qt override
        if event.button() is Qt.MouseButton.LeftButton:
            self.end_manipulation()
        super().mouseReleaseEvent(event)

    @property
    def palette_tokens(self) -> OverlayPalette:
        return palette_for(self.geometry_settings.brightness)

    @property
    def halo_engaged(self) -> bool:
        """Below 70% opacity the measured contrast stops being a guarantee, so ink gets a
        contrasting halo and the promise is downgraded honestly."""
        return self.geometry_settings.opacity < HALO_OPACITY_THRESHOLD

    def _restyle(self) -> None:
        palette = self.palette_tokens
        state = self.view.state if self.view else SnippetState.NO_MATCH
        rail = palette.rail_for(state)
        border_left = f"{RAIL_WIDTH_PX}px solid {rail}" if rail else "0px"
        self.setStyleSheet(
            f"QWidget {{ background: {palette.panel};"
            f" border-radius: {CORNER_RADIUS_PX}px;"
            f" border-left: {border_left}; }}"
        )
        ink = palette.muted if state is SnippetState.NO_MATCH else palette.ink
        style = "italic" if state is SnippetState.NO_MATCH else "normal"
        self.headline.setStyleSheet(f"color: {ink}; font-style: {style}; border: none;")
        for label in self.bullets:
            label.setStyleSheet(f"color: {palette.muted}; border: none;")
        self._apply_halo(palette)

    def _apply_halo(self, palette: OverlayPalette) -> None:
        """The contrasting outline promised below 70% opacity.

        `halo_engaged` was computed and then never consulted, so the ink was bare over
        arbitrary video content in exactly the range where the fixed contrast figures stop
        holding — the promise was in a docstring and a property and nowhere else. Found by
        review on PR #20.

        A drop shadow in the *opposing* tone rather than a literal 1 px stroke: Qt style
        sheets have no text-shadow, and an effect reads correctly against both a light and
        a dark ground because the halo colour follows the band.
        """
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QGraphicsDropShadowEffect

        for label in (self.headline, *self.bullets):
            if not self.halo_engaged:
                # `setGraphicsEffect(None)` is the documented way to clear one; the stub
                # types it as non-optional, so the ignore is about the stub, not the call.
                label.setGraphicsEffect(None)  # type: ignore[arg-type]
                continue
            effect = QGraphicsDropShadowEffect(label)
            effect.setBlurRadius(4)
            effect.setOffset(0, 0)
            effect.setColor(QColor(palette.panel))
            label.setGraphicsEffect(effect)
