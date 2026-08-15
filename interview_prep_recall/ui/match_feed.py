"""The matching pipeline's output, turned into what the overlay shows (T5.10 — FR11,
FR35, FR49, FR51, FR72, D-5, D-6).

**This wire did not exist.** `MatchingPipeline` produced a `MatchResult`, `app.py` handed
it to a default no-op lambda, and `main_window.py` — which wires the tracker checklist and
the health strip — never assigned it. `OverlayPanel.show_snippet` had no production caller
anywhere, and neither did `from_stored_note`. Every piece was built and tested: the
prefilter, the forced-tool selector, the sequence gate, the panel, FR11's substring check,
FR51's states, FR72's marks. Nothing joined them, so the product's central behaviour — a
snippet appearing when the interviewer asks a question — did not happen. Found by a sweep
for exactly this shape, after the same defect turned up in the retention sweep (PR #24)
and the health indicator (PR #25).

**Pure conversion, no Qt.** `snippet_for` takes a result and a context set and returns a
`SnippetView`, so the mapping — which outcome becomes which visual state, what a
bullet-less note renders — is testable without a widget. The window owns only the thread
hop and the call.

**Nothing here composes text.** Bullets come from the note's own `bullets`, and a note
without them takes D-6's path: the body truncated at a sentence boundary. Truncation is a
prefix and nothing else, so what reaches the panel is still a byte-exact substring of what
the user stored — the property `from_stored_note` then checks against the store rather
than against anything this module asserts.
"""

from __future__ import annotations

from interview_prep_recall.matching.pipeline import MatchResult, Outcome
from interview_prep_recall.notes.model import ContextSet, Note
from interview_prep_recall.ui.overlay import (
    MAX_BULLETS,
    SnippetState,
    SnippetView,
    from_stored_note,
    no_match_view,
)

MAX_BODY_CHARS = 240
"""D-6: a bullet-less note renders its body truncated at a sentence boundary, ≤240 chars.

The limit is the design's; the sentence boundary is what keeps the result readable rather
than merely short. A mid-word cut on the surface someone reads in under a second is worse
than showing less.
"""

SENTENCE_ENDINGS = (". ", "! ", "? ", ".\n", "!\n", "?\n")

STATE_FOR: dict[Outcome, SnippetState] = {
    Outcome.CONFIRMED: SnippetState.CONFIRMED,
    Outcome.DEGRADED: SnippetState.DEGRADED,
    Outcome.NO_MATCH: SnippetState.NO_MATCH,
}
"""FR51 and FR49. `DEGRADED` is the stage-1 fallback above τ_degraded, and it must reach
the panel as such — rendering it as `CONFIRMED` would tell the user a model chose this
when a cosine similarity did."""


def source_text(note: Note) -> str:
    """What the note's rendered strings must be substrings of.

    Identical to `Note.verify_bullets_verbatim`'s haystack, deliberately: if the two ever
    disagreed, a bullet that passed validation on save would be refused at render, and
    the panel would go blank mid-interview on a note the editor called valid.
    """
    return f"{note.headline}\n{note.body}"


def truncate_at_sentence(body: str, limit: int = MAX_BODY_CHARS) -> str:
    """D-6's fallback text: a prefix of the body, ending at a sentence boundary.

    **A prefix, never a rewrite.** FR42 permits ellipsis and forbids anything the user did
    not write, and the two only coexist while truncation cannot substitute or reorder —
    the same rule D-50 states for the overlay's own elision. Returns "" for an empty body,
    which renders as a headline with no bullets rather than as an invented line.
    """
    text = body.strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    window = text[:limit]
    cut = max(window.rfind(ending) for ending in SENTENCE_ENDINGS)
    if cut > 0:
        # +1 keeps the terminator: the sentence is the user's, punctuation and all.
        return window[: cut + 1].strip()
    return window.rstrip()


def bullets_for(note: Note) -> tuple[str, ...]:
    """FR11's at-most-three, from the note's own text (D-5, D-6)."""
    if note.bullets:
        return tuple(note.bullets[:MAX_BULLETS])
    truncated = truncate_at_sentence(note.body)
    return (truncated,) if truncated else ()


def snippet_for(result: MatchResult, context_set: ContextSet) -> SnippetView:
    """Turn a pipeline result into what the panel renders.

    A result naming a note the set no longer holds becomes the no-match line rather than
    an error: the pipeline and the editor run against the same set, but a note deleted
    between the match and the render is an ordinary race, and FR35 already says what the
    panel shows when there is nothing to show. `from_stored_note` still raises for a
    *fabricated* id — the difference is that this checks first and that one is the
    guarantee.
    """
    if result.outcome is Outcome.NO_MATCH or result.note_id is None:
        return no_match_view()

    note = context_set.get(result.note_id)
    if note is None:
        return no_match_view()

    # The store lookup **is** `context_set.get(result.note_id)` above; the resolver then
    # closes over what that returned. Keeping the id-to-note step here rather than inside
    # the closure is what lets the missing-note case become the no-match line instead of
    # an exception, without weakening the check: the text still comes from a note found
    # by the id the pipeline supplied, never from anything this module composed.
    return from_stored_note(
        lambda _id: source_text(note),
        note.id,
        note.headline,
        bullets_for(note),
        STATE_FOR[result.outcome],
        # FR72's mark, resolved from the stored chunk like the text is — never asserted
        # by this module.
        resolve_kind=lambda _id: note.kind,
    )
