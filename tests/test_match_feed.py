"""T5.10 — the matching pipeline's output reaching the overlay (FR11, FR35, FR49, FR51,
FR72, D-5, D-6).

The wire that did not exist. `MatchingPipeline` produced results, `Application.on_result`
defaulted to a no-op lambda, and nothing assigned it — so `OverlayPanel.show_snippet` had
no production caller and the product's central behaviour never happened. Every component
below this had passing tests; what was missing was the join, which is why the tests here
are about the *path* and not about the pieces.
"""

from __future__ import annotations

import uuid

import numpy as np
import pytest
from helpers import ReversingCipher, ScriptedClient

pytest.importorskip("PySide6", reason="Qt UI tests require the [ui] extra")

from PySide6.QtWidgets import QApplication  # noqa: E402

from interview_prep_recall.app import Application  # noqa: E402
from interview_prep_recall.matching.pipeline import MatchResult, Outcome  # noqa: E402
from interview_prep_recall.notes.model import ContextSet, Note, SourceKind  # noqa: E402
from interview_prep_recall.ui.match_feed import (  # noqa: E402
    MAX_BODY_CHARS,
    bullets_for,
    snippet_for,
    source_text,
    truncate_at_sentence,
)
from interview_prep_recall.ui.overlay import (  # noqa: E402
    DEGRADED_GLYPH,
    MAX_BULLETS,
    NO_MATCH_TEXT,
    OverlayPanel,
    SnippetState,
    mark_for,
)

HEADLINE = "Tell me about a migration"
BODY = "Led the migration off the monolith. Cut p99 latency from 900ms to 120ms."


def _note(**kwargs) -> Note:  # type: ignore[no-untyped-def]
    kwargs.setdefault("headline", HEADLINE)
    kwargs.setdefault("body", BODY)
    kwargs.setdefault("kind", SourceKind.PREP)
    return Note(**kwargs)


def _set(*notes: Note) -> ContextSet:
    return ContextSet(name="Acme", notes=list(notes))


def _result(outcome: Outcome, note_id: str | None) -> MatchResult:
    return MatchResult(outcome, note_id, seq=1, nonce=uuid.uuid4(), similarity=0.8)


# ---------- the conversion ----------


def test_a_confirmed_match_renders_the_note() -> None:
    note = _note(bullets=["Cut p99 latency from 900ms to 120ms."])
    view = snippet_for(_result(Outcome.CONFIRMED, note.id), _set(note))

    assert view.state is SnippetState.CONFIRMED
    assert view.headline == HEADLINE
    assert view.bullets == ("Cut p99 latency from 900ms to 120ms.",)
    assert view.kind is SourceKind.PREP


def test_a_degraded_match_reaches_the_panel_as_degraded() -> None:
    """FR49/FR51. Rendering the stage-1 fallback as confirmed would tell the user a model
    chose this when a cosine similarity did."""
    note = _note()
    view = snippet_for(_result(Outcome.DEGRADED, note.id), _set(note))

    assert view.state is SnippetState.DEGRADED
    assert view.display_headline.startswith(DEGRADED_GLYPH)


def test_no_match_renders_the_product_line() -> None:
    """FR35/OB-1: never a blank panel."""
    view = snippet_for(_result(Outcome.NO_MATCH, None), _set(_note()))

    assert view.state is SnippetState.NO_MATCH
    assert view.headline == NO_MATCH_TEXT


def test_a_note_deleted_between_the_match_and_the_render_is_not_an_error() -> None:
    """An ordinary race — the pipeline and the editor share a set. FR35 already says what
    the panel shows when there is nothing to show."""
    view = snippet_for(_result(Outcome.CONFIRMED, _note().id), _set())

    assert view.state is SnippetState.NO_MATCH


def test_the_kind_mark_reaches_the_panel(qapp: QApplication) -> None:
    """FR72, end to end: the mark is resolved from the stored chunk, not asserted."""
    note = _note(kind=SourceKind.RESUME)
    view = snippet_for(_result(Outcome.CONFIRMED, note.id), _set(note))

    assert view.display_headline.startswith(mark_for(SourceKind.RESUME).glyph)


def test_every_rendered_string_is_verbatim() -> None:
    """FR11, at the join. `from_stored_note` checks against the stored text, and this
    asserts the source text this module supplies is the same haystack the editor
    validates bullets against — if they disagreed, a bullet valid on save would be
    refused at render and the panel would go blank mid-interview."""
    note = _note(bullets=["Led the migration off the monolith."])

    assert source_text(note) == f"{note.headline}\n{note.body}"
    view = snippet_for(_result(Outcome.CONFIRMED, note.id), _set(note))
    for rendered in view.rendered_strings:
        assert rendered in source_text(note)


def test_more_than_three_bullets_are_cut_to_three() -> None:
    """FR11's cap, applied before the view refuses the whole snippet."""
    sentences = [f"Sentence number {n} of the body." for n in range(5)]
    note = _note(body=" ".join(sentences), bullets=sentences)

    assert len(bullets_for(note)) == MAX_BULLETS


# ---------- D-6: the bullet-less note ----------


def test_a_note_without_bullets_renders_its_body_truncated() -> None:
    note = _note(body="First sentence here. " + "x" * 400)

    bullets = bullets_for(note)

    assert len(bullets) == 1
    assert len(bullets[0]) <= MAX_BODY_CHARS
    assert bullets[0] in note.body


def test_truncation_stops_at_a_sentence_boundary() -> None:
    """A mid-word cut on the surface someone reads in under a second is worse than
    showing less."""
    body = "First sentence. Second sentence. " + "word " * 100

    truncated = truncate_at_sentence(body)

    assert truncated.endswith(".")
    assert truncated.startswith("First sentence.")


def test_truncation_is_a_prefix_and_nothing_else() -> None:
    """D-50's rule, one layer up: FR42 permits ellipsis and forbids anything the user did
    not write, and the two only coexist while truncation cannot substitute or reorder."""
    body = "A. " + "long " * 200

    assert body.startswith(truncate_at_sentence(body))


def test_a_short_body_is_untouched() -> None:
    assert truncate_at_sentence(BODY) == BODY


def test_an_empty_body_renders_no_bullets_rather_than_an_invented_line() -> None:
    note = _note(body="")

    assert bullets_for(note) == ()
    view = snippet_for(_result(Outcome.CONFIRMED, note.id), _set(note))
    assert view.bullets == ()


def test_a_body_with_no_sentence_boundary_still_truncates() -> None:
    """A wall of text with no punctuation must not render at full length."""
    truncated = truncate_at_sentence("word " * 200)

    assert 0 < len(truncated) <= MAX_BODY_CHARS


# ---------- the panel's slot ----------


def test_the_panel_renders_a_result_it_is_sent(qapp: QApplication) -> None:
    note = _note(bullets=["Cut p99 latency from 900ms to 120ms."])
    panel = OverlayPanel()
    panel.context_set = _set(note)

    panel.show_match(_result(Outcome.CONFIRMED, note.id))

    assert panel.headline.text().endswith(HEADLINE)
    assert panel.visible_bullet_count == 1


def test_the_panel_without_a_context_set_says_nothing_matched(qapp: QApplication) -> None:
    """An unset context set is a wiring bug, not a user state — but the panel is not the
    place to raise it, and going dark is the one thing FR35 forbids."""
    panel = OverlayPanel()

    panel.show_match(_result(Outcome.CONFIRMED, _note().id))

    assert panel.headline.text() == NO_MATCH_TEXT


# ---------- the wire ----------


class FlatEmbedder:
    model_id = "flat/one"
    model_version = "1.0"

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.ones((len(texts), 2), dtype=np.float32)


def test_the_application_hands_results_to_the_panel(qapp: QApplication, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The defect this task closes, as one assertion: a result issued by the application
    reaches the widget. `on_result` defaulted to a no-op lambda and nothing assigned it,
    so this path did not exist."""
    from interview_prep_recall.ui.main_window import MainWindow

    note = _note(bullets=["Cut p99 latency from 900ms to 120ms."])
    application = Application(
        root=tmp_path,
        embedder=FlatEmbedder(),
        client=ScriptedClient(),
        cipher=ReversingCipher(),
        context_set=_set(note),
    )
    window = MainWindow(application, overlay_settings=_FakeSettings())

    application.on_result(_result(Outcome.CONFIRMED, note.id))

    assert window.overlay.headline.text().endswith(HEADLINE)
    assert window.overlay.context_set is application.context_set


def test_the_result_hook_does_not_outlive_the_window(qapp: QApplication, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The application outlives the window, and the pipeline keeps emitting: a hook
    holding a bound `emit` of a deleted widget is the segfault shape D-53 and D-54
    record."""
    from PySide6.QtCore import QCoreApplication, QEvent

    from interview_prep_recall.ui.main_window import MainWindow

    application = Application(
        root=tmp_path,
        embedder=FlatEmbedder(),
        client=ScriptedClient(),
        cipher=ReversingCipher(),
        context_set=_set(_note()),
    )
    window = MainWindow(application, overlay_settings=_FakeSettings())
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    application.on_result(_result(Outcome.NO_MATCH, None))  # must not reach a dead widget


class _FakeSettings:
    """Same stand-in `test_main_window` uses: `QSettings`' string round-trip."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def setValue(self, key: str, value: object) -> None:  # noqa: N802 — Qt casing
        self._values[key] = str(value)

    def value(self, key: str, default: object = None) -> object:
        return self._values.get(key, default)
