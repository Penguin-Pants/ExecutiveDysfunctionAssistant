"""T3.5 — chunking, strategy detection, headline mapping, bullet proposal."""

from __future__ import annotations

import pytest

from interview_prep_recall.notes.importer import (
    ChunkStrategy,
    build_note_set,
    detect_strategy,
    import_text,
    propose_bullets,
)

MD = """\
# Acme prep

## Tell me about a conflict you handled?
Design review deadlocked in Q3. I wrote a trade-off document. We shipped two weeks early.

### Why do you want this role?
The product problem is one I have lived. I have shipped in this space before.
"""

QA = """\
Q: What is your greatest weakness?
A: I over-index on detail. I now timebox reviews explicitly.

Q: Why are you leaving?
A: I want more ownership of outcomes.
"""

BLANK = """\
Tell me about a time you failed?
The migration rollback took four hours. I wrote the runbook afterwards.

Where do you see yourself in five years?
Leading a small platform team.
"""


def test_md_detected_by_extension() -> None:
    assert detect_strategy(MD, "notes.md") is ChunkStrategy.MD_HEADER


def test_qa_detected_by_two_or_more_q_lines() -> None:
    assert detect_strategy(QA, "notes.txt") is ChunkStrategy.QA_CONVENTION


def test_blank_line_is_the_fallback() -> None:
    assert detect_strategy(BLANK, "notes.txt") is ChunkStrategy.BLANK_LINE


def test_single_q_line_does_not_trigger_qa_convention() -> None:
    """One stray 'Q:' in prose should not reshape the whole file."""
    text = "Q: only one\n\nSome other paragraph entirely.\n"
    assert detect_strategy(text, "notes.txt") is ChunkStrategy.BLANK_LINE


def test_md_splits_on_h2_and_h3_and_maps_headline() -> None:
    result = import_text(MD, "notes.md")
    assert result.strategy is ChunkStrategy.MD_HEADER
    assert [p.headline for p in result.proposals] == [
        "Tell me about a conflict you handled?",
        "Why do you want this role?",
    ]
    assert result.proposals[0].body.startswith("Design review deadlocked")


def test_qa_maps_q_to_headline_and_a_to_body() -> None:
    result = import_text(QA, "notes.txt")
    assert [p.headline for p in result.proposals] == [
        "What is your greatest weakness?",
        "Why are you leaving?",
    ]
    assert result.proposals[0].body.startswith("I over-index on detail")


def test_blank_line_maps_first_line_to_headline() -> None:
    result = import_text(BLANK, "notes.txt")
    assert result.proposals[0].headline == "Tell me about a time you failed?"
    assert result.proposals[0].body.startswith("The migration rollback")


def test_user_can_override_the_detected_strategy() -> None:
    """FR2: the review UI names the strategy and lets the user switch it."""
    forced = import_text(QA, "notes.txt", strategy=ChunkStrategy.BLANK_LINE)
    assert forced.strategy is ChunkStrategy.BLANK_LINE
    assert len(forced.proposals) == 2


def test_every_proposed_bullet_is_verbatim() -> None:
    """FR42. The single most important property of the importer."""
    for text, name in ((MD, "n.md"), (QA, "n.txt"), (BLANK, "n.txt")):
        for proposal in import_text(text, name).proposals:
            haystack = f"{proposal.headline}\n{proposal.body}"
            for bullet in proposal.bullets:
                assert bullet in haystack


def test_bullets_capped_at_three() -> None:
    body = " ".join(f"Sentence number {i} is here." for i in range(10))
    assert len(propose_bullets("q?", body)) == 3


def test_empty_body_yields_no_bullets_rather_than_invented_ones() -> None:
    """D-6: that note takes the truncation path instead."""
    assert propose_bullets("Just a headline?", "") == []


def test_headline_flagged_when_not_question_shaped() -> None:
    result = import_text("Leadership philosophy\nI delegate early.\n", "n.txt")
    assert result.proposals[0].needs_headline_review


def test_headline_not_flagged_when_question_shaped() -> None:
    result = import_text(BLANK, "n.txt")
    assert not result.proposals[0].needs_headline_review


def test_import_always_requires_review_before_save() -> None:
    assert import_text(MD, "n.md").needs_review is True


def test_build_note_set_verifies_bullets() -> None:
    result = import_text(MD, "notes.md")
    note_set = build_note_set("Acme", result.proposals)
    note_set.verify()
    assert len(note_set.notes) == 2
    assert all(n.id for n in note_set.notes)


def test_empty_input_produces_no_proposals() -> None:
    assert import_text("", "n.txt").proposals == []
    assert import_text("   \n\n  \n", "n.txt").proposals == []


@pytest.mark.parametrize("text", ["## only a header\n", "Q: only a question\nQ: and another\n"])
def test_chunks_without_bodies_are_still_valid(text: str) -> None:
    for proposal in import_text(text, "n.md" if text.startswith("##") else "n.txt").proposals:
        assert proposal.headline
        assert proposal.bullets == []
