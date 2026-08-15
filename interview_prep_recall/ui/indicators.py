"""Capture, egress and health indicators (T5.7 — FR7, FR14a, FR20, FR35).

These four widgets exist to answer one question the user cannot answer any other way
mid-interview: **is the panel empty because nothing matched, or because something broke?**
Design §7 calls that the worst observability property the system could have, and FR35
makes the distinction a requirement rather than a nicety.

The answer is split across two surfaces on purpose. Content states live in the panel —
`SnippetState.NO_MATCH` renders an italic muted line saying so. Health states live here,
and `Health.indicators()` deliberately never returns "no match", so **no state of this bar
can be produced by nothing matching**. That is what makes the two distinguishable: they
are not two renderings of one signal, they are two signals.

**Every state carries a shape as well as a colour.** Each row is prefixed with a severity
glyph and each dot with its path's name, because roughly 8% of men have a colour vision
deficiency that makes a red/amber distinction unreliable — and these are the indicators
read at a glance, over a video call, while talking.

**`visual_state()` is the testable surface.** FR35 requires every state in design §7 to
render distinctly, and "distinctly" is a property of the *set* of renderings, not of any
one. A per-state screenshot assertion cannot express it; a hashable description of what
was rendered can, so the tests drive every state and assert the descriptions are pairwise
different.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from interview_prep_recall.session.health import Egress, Health

# ---------- PRISM tokens (design §9b) ----------

RED_500 = "#F0473E"
"""Danger. Reserved for states where the product is not doing what the user believes."""

AMBER_500 = "#FFC93D"
"""Warning / degraded — "proceed, but know this"."""

GREEN_500 = "#34C77B"
MUTED = "#A8ADB5"
DOT_UNLIT = "#3A3145"

CHIP_SIZE = (34, 16)
CHIP_RADIUS_PX = 10
CHIP_IDLE = "#3A3145"
"""Flat when not capturing — the gradient means *live*, per PRISM §9's one-chip rule."""

ACCENT_GRADIENT = (
    "qlineargradient(x1:0, y1:0, x2:1, y2:1, "
    "stop:0 #FF4D4D, stop:0.35 #FF9D3D, stop:0.6 #FFC93D, stop:1 #B24DFF)"
)

EGRESS_DOT_PX = 8

CAPTURING_TEXT = "LIVE"
IDLE_TEXT = "OFF"
NOMINAL_TEXT = "Everything working"
NOMINAL_GLYPH = "✓"
WARNING_GLYPH = "!"
DANGER_GLYPH = "✕"
EXCLUSION_TEXT = "NOT hidden from screen share"

DANGER_INDICATORS = ("audio lost", "STT unavailable", "matching unavailable", "NOT hidden")
"""Prefixes of the design §7 indicator strings that mean the product is *not* doing what
the user believes it is doing. Everything else in §7 is a degradation the user can work
with, and painting those red would train them to ignore the colour that matters."""


def severity_of(indicator: str) -> str:
    """Red for "this is not working", amber for "this is working, less well"."""
    return RED_500 if indicator.startswith(DANGER_INDICATORS) else AMBER_500


def _glyph_for(colour: str) -> str:
    return DANGER_GLYPH if colour == RED_500 else WARNING_GLYPH


CONTAINER_STYLE = "background: transparent; border: none;"
"""Every container in this module states its own background and border.

The overlay panel styles itself with a bare `QWidget { … }` selector carrying the FR51
rail as a `border-left`, and a Qt style sheet set on a parent applies to **every** widget
under it. Without this the rail is repainted down the left of each indicator group — three
extra coloured bars on the one surface that has to be readable in a glance. The panel's
own labels already carry `border: none` for exactly this reason; these are the containers
that arrived with T5.7 and need the same.
"""


class CaptureIndicator(QLabel):
    """FR7: capture never runs without a visible indicator.

    FR20's egress indicator is defined as *visually distinct from this one*, so the two
    are deliberately different objects: a gradient chip with a word in it here, small
    amber dots there. Distinctness by shape, not only by colour.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(*CHIP_SIZE)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self._capturing = False
        self.set_capturing(False)

    def set_capturing(self, capturing: bool) -> None:
        self._capturing = capturing
        background = ACCENT_GRADIENT if capturing else CHIP_IDLE
        self.setText(CAPTURING_TEXT if capturing else IDLE_TEXT)
        self.setToolTip("Capturing audio" if capturing else "Capture stopped")
        self.setStyleSheet(
            f"background: {background}; border: none;"
            f" border-radius: {CHIP_RADIUS_PX}px;"
            f" color: {'#15171B' if capturing else MUTED}; font-size: 9px; font-weight: 600;"
        )

    @property
    def capturing(self) -> bool:
        return self._capturing

    def visual_state(self) -> tuple[str, ...]:
        return ("capture", self.text(), ACCENT_GRADIENT if self._capturing else CHIP_IDLE)


class EgressDot(QLabel):
    """One path's worth of FR20. Named, so the two paths are told apart by more than
    position — a user who sees one lit dot must know *which*."""

    def __init__(self, path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.path = path
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setLit(False)

    def setLit(self, lit: bool) -> None:  # noqa: N802 — Qt setter casing
        self._lit = lit
        colour = AMBER_500 if lit else DOT_UNLIT
        self.setText(f"● {self.path}")
        self.setToolTip(
            f"{self.path}: data is leaving this device" if lit else f"{self.path}: nothing sent"
        )
        self.setStyleSheet(
            f"color: {colour}; border: none; font-size: {EGRESS_DOT_PX + 2}px;"
            f" font-weight: {'600' if lit else '400'};"
        )

    @property
    def lit(self) -> bool:
        return self._lit

    def visual_state(self) -> tuple[str, ...]:
        return (self.path, "lit" if self._lit else "unlit")


class EgressIndicator(QWidget):
    """FR20, **one dot per path**.

    A single shared "something is leaving" dot was the obvious build and it fails the
    requirement: cloud STT sends the interviewer's audio, LLM matching sends text derived
    from it, and a user who has turned one off (FR37) needs to see that it went dark while
    the other did not. Unlit dots stay in place rather than hiding, so the row does not
    reflow and a dark dot is readable as *off* rather than as absent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(CONTAINER_STYLE)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.cloud_stt = EgressDot("cloud STT", self)
        self.llm = EgressDot("LLM", self)
        layout.addWidget(self.cloud_stt)
        layout.addWidget(self.llm)

    def set_egress(self, egress: Egress) -> None:
        self.cloud_stt.setLit(egress in (Egress.CLOUD_STT, Egress.BOTH))
        self.llm.setLit(egress in (Egress.LLM, Egress.BOTH))

    def visual_state(self) -> tuple[str, ...]:
        return ("egress", *self.cloud_stt.visual_state(), *self.llm.visual_state())


class HealthStrip(QWidget):
    """FR35's session health, rendered from `Health.indicators()`.

    **Nominal is a rendering, not an empty widget.** A blank strip is what a crashed strip
    also looks like, which is the OB-1 failure one level up — so "everything working" is
    stated, in green, with a check glyph.

    Rows come from `Health.indicators()` unchanged, in its order (worst first). No copy is
    re-derived here: two places deciding what "degraded" means is how they come to
    disagree, and the health model is the one that knows.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(CONTAINER_STYLE)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self._rows: list[QLabel] = []
        self.set_health(Health())

    def set_health(self, health: Health) -> None:
        indicators = health.indicators()
        rendered = (
            [(NOMINAL_TEXT, GREEN_500)]
            if not indicators
            else [(text, severity_of(text)) for text in indicators]
        )
        self._render(rendered)

    def _render(self, rendered: list[tuple[str, str]]) -> None:
        while len(self._rows) < len(rendered):
            label = QLabel("", self)
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)
            self._layout.addWidget(label)
            self._rows.append(label)
        for index, label in enumerate(self._rows):
            if index >= len(rendered):
                label.hide()
                label.setText("")
                continue
            text, colour = rendered[index]
            glyph = NOMINAL_GLYPH if colour == GREEN_500 else _glyph_for(colour)
            label.setText(f"{glyph} {text}")
            label.setStyleSheet(f"color: {colour}; border: none; font-size: 11px;")
            label.show()
        self._rendered = tuple(rendered)

    @property
    def rows(self) -> tuple[str, ...]:
        return tuple(label.text() for label in self._rows if not label.isHidden())

    def visual_state(self) -> tuple[str, ...]:
        return ("health", *(f"{text}|{colour}" for text, colour in self._rendered))


class CaptureExclusionBar(QLabel):
    """FR14a. Shown only when `SetWindowDisplayAffinity` is known to have **failed**.

    Three states, not two, and the third is why this takes `bool | None`: before the check
    has run there is nothing truthful to say, and a bar that defaults to "you are hidden"
    would be the silent assumption of success FR14a exists to forbid. `None` renders
    nothing; `True` renders nothing; only `False` shows the bar, and it never auto-hides.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setText(EXCLUSION_TEXT)
        self.setStyleSheet(
            f"background: {RED_500}; color: #FFFFFF; border: none;"
            " font-size: 11px; font-weight: 600; padding: 2px;"
        )
        self.set_excluded(None)

    def set_excluded(self, excluded: bool | None) -> None:
        self._excluded = excluded
        self.setVisible(excluded is False)

    def visual_state(self) -> tuple[str, ...]:
        return ("exclusion", "warning" if self._excluded is False else "silent")


class IndicatorBar(QWidget):
    """The four indicators, driven from one `Health` (design §7).

    One entry point rather than four setters on the panel, because health is delivered as
    one record by the watchdog and splitting it at the UI boundary is how a state gets
    updated on one indicator and not another.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(CONTAINER_STYLE)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        self.exclusion = CaptureExclusionBar(self)
        outer.addWidget(self.exclusion)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.capture = CaptureIndicator(self)
        self.egress = EgressIndicator(self)
        row.addWidget(self.capture)
        row.addWidget(self.egress)
        row.addStretch(1)
        outer.addLayout(row)

        self.health = HealthStrip(self)
        outer.addWidget(self.health)

    def update_health(self, health: Health) -> None:
        self.capture.set_capturing(health.capturing)
        self.egress.set_egress(health.egress)
        self.health.set_health(health)
        self.exclusion.set_excluded(health.capture_excluded)

    def visual_state(self) -> tuple[str, ...]:
        return (
            *self.exclusion.visual_state(),
            *self.capture.visual_state(),
            *self.egress.visual_state(),
            *self.health.visual_state(),
        )
