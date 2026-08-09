"""M7 — progress tracker and runtime echo suppression (T7.1, T7.3)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from interview_prep_recall.notes.index import EmbeddingIndex
from interview_prep_recall.notes.model import Note, NoteSet
from interview_prep_recall.stt.assembler import Utterance
from interview_prep_recall.tracker.progress import (
    ECHO_HOLD_S,
    TAU_ECHO_TEXT,
    ProgressTracker,
    jaccard,
    spans_overlap,
)


class WordEmbedder:
    """Bag-of-words vectors — similarity stays legible in the test itself."""

    model_id = "test/word"
    model_version = "1.0"
    VOCAB = ["conflict", "migration", "leadership", "mentored", "rollback", "weather"]

    def encode(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), len(self.VOCAB)), dtype=np.float32)
        for i, text in enumerate(texts):
            words = text.lower().split()
            for j, term in enumerate(self.VOCAB):
                out[i, j] = float(sum(1 for w in words if term in w))
        return out


def build(app_data: Path) -> tuple[ProgressTracker, NoteSet]:
    note_set = NoteSet(
        name="prep",
        notes=[
            Note(headline="conflict", track_progress=True),
            Note(headline="migration", track_progress=True),
            Note(headline="leadership", track_progress=True),
            Note(headline="weather", track_progress=False),
        ],
    )
    embedder = WordEmbedder()
    index = EmbeddingIndex(app_data, embedder)
    index.build(note_set)
    return ProgressTracker(note_set, index, embedder), note_set


def mic(text: str, t: float = 0.0) -> Utterance:
    return Utterance("user", text, t, t + 1.0, "")


def them(text: str, t: float = 0.0) -> Utterance:
    return Utterance("interviewer", text, t, t + 1.0, "")


# ---------------- T7.1 marking ----------------


def test_speaking_a_tracked_point_marks_it(app_data: Path) -> None:
    tracker, note_set = build(app_data)
    tracker.submit_user(mic("conflict"))
    newly = tracker.tick(ECHO_HOLD_S + 1.1)
    assert newly == [note_set.notes[0].id]
    assert note_set.notes[0].id in tracker.marked_ids


def test_untracked_notes_are_never_marked(app_data: Path) -> None:
    """Only notes the user flagged appear on the checklist.

    Carries a positive control: without it this passes even if marking were broken
    outright, since it only asserts an absence.
    """
    tracker, note_set = build(app_data)
    tracker.submit_user(mic("weather conflict"))
    marked = tracker.tick(ECHO_HOLD_S + 1.1)
    assert note_set.notes[0].id in marked, "positive control — tracked note did mark"
    assert note_set.notes[3].id not in tracker.marked_ids


def test_unrelated_speech_marks_nothing(app_data: Path) -> None:
    tracker, _ = build(app_data)
    tracker.submit_user(mic("something entirely off topic"))
    assert tracker.tick(ECHO_HOLD_S + 1.1) == []
    assert tracker.marked_ids == set()


def test_marks_are_sticky(app_data: Path) -> None:
    """Un-marking would make the checklist flicker mid-sentence."""
    tracker, note_set = build(app_data)
    tracker.submit_user(mic("conflict"))
    tracker.tick(ECHO_HOLD_S + 1.1)
    tracker.submit_user(mic("something else", t=10.0))
    tracker.tick(20.0)
    assert note_set.notes[0].id in tracker.marked_ids


def test_a_point_is_reported_newly_marked_only_once(app_data: Path) -> None:
    tracker, _ = build(app_data)
    tracker.submit_user(mic("conflict"))
    first = tracker.tick(ECHO_HOLD_S + 1.1)
    tracker.submit_user(mic("conflict", t=10.0))
    second = tracker.tick(20.0)
    assert first and second == []


def test_points_reflect_checklist_state(app_data: Path) -> None:
    tracker, _ = build(app_data)
    assert [p.mentioned for p in tracker.points()] == [False, False, False]
    tracker.submit_user(mic("conflict"))
    tracker.tick(ECHO_HOLD_S + 1.1)
    assert [p.mentioned for p in tracker.points()] == [True, False, False]
    assert len(tracker.points()) == 3, "the untracked note is not on the checklist"


def test_reset_clears_marks(app_data: Path) -> None:
    """Marks are session state and go with everything else on purge (FR15)."""
    tracker, _ = build(app_data)
    tracker.submit_user(mic("conflict"))
    tracker.tick(ECHO_HOLD_S + 1.1)
    tracker.reset()
    assert tracker.marked_ids == set()
    assert [p.mentioned for p in tracker.points()] == [False, False, False]


# ---------------- FR56 stream isolation ----------------


def test_interviewer_utterances_are_refused_by_the_tracker(app_data: Path) -> None:
    """FR56. The interviewer describing the role must not tick off your points."""
    tracker, _ = build(app_data)
    with pytest.raises(ValueError, match="mic stream only"):
        tracker.submit_user(them("conflict"))


def test_observe_interviewer_never_marks(app_data: Path) -> None:
    """The loopback-must-not-mark assertion, on the path that actually accepts them.

    The positive control matters here: an absence assertion alone would pass if the
    tracker simply never marked anything.
    """
    tracker, note_set = build(app_data)
    tracker.observe_interviewer(them("conflict", t=0.0))
    tracker.observe_interviewer(them("migration", t=2.0))
    assert tracker.tick(100.0) == []
    assert tracker.marked_ids == set()

    # Same words, this time from the mic and far from the interviewer spans.
    tracker.submit_user(mic("conflict", t=200.0))
    assert note_set.notes[0].id in tracker.tick(300.0)


def test_observe_refuses_a_mic_utterance(app_data: Path) -> None:
    tracker, _ = build(app_data)
    with pytest.raises(ValueError, match="expected an interviewer utterance"):
        tracker.observe_interviewer(mic("conflict"))


# ---------------- T7.3 echo suppression ----------------


def test_echoed_mic_span_does_not_mark(app_data: Path) -> None:
    """On speakers, the interviewer's question bleeds into the mic. That copy is the
    artefact and must not tick off a point the user never made."""
    tracker, _ = build(app_data)
    phrase = "tell me about the migration project"
    tracker.observe_interviewer(them(phrase, t=0.0))
    tracker.submit_user(mic(phrase, t=0.2))
    assert tracker.tick(10.0) == []
    assert tracker.marked_ids == set()
    assert tracker.suppressed_count == 1


def test_interviewer_utterance_is_never_the_one_suppressed(app_data: Path) -> None:
    """Both assertions are required. Passing only the first would mean the echo is
    being dropped from the wrong stream — the genuine question thrown away while the
    mic copy still marks."""
    tracker, note_set = build(app_data)
    phrase = "tell me about the migration project"
    them_u = them(phrase, t=0.0)

    tracker.observe_interviewer(them_u)
    tracker.submit_user(mic(phrase, t=0.2))
    tracker.tick(10.0)

    # 1. the mic copy did not mark
    assert note_set.notes[1].id not in tracker.marked_ids

    # 2. the interviewer utterance still reaches matching and still matches. Checking
    #    `them_u.text` instead would be vacuous — Utterance is frozen and nothing here
    #    mutates it, so that assertion would hold however the code behaved.
    from interview_prep_recall.matching.pipeline import MatchingPipeline, Outcome
    from interview_prep_recall.matching.prefilter import Prefilter

    prefilter = Prefilter(tracker.index, note_set, tracker.embedder)
    results = []
    MatchingPipeline(prefilter=prefilter, selector=None, on_result=results.append).submit(them_u)
    assert results and results[-1].outcome is not Outcome.NO_MATCH


def test_echo_arriving_after_the_mic_span_still_suppresses(app_data: Path) -> None:
    """Stream ordering is not guaranteed — the mic may finalise first."""
    tracker, _ = build(app_data)
    phrase = "walk me through the migration project"
    tracker.submit_user(mic(phrase, t=0.2))
    tracker.observe_interviewer(them(phrase, t=0.0))
    assert tracker.tick(10.0) == []
    assert tracker.suppressed_count == 1


def test_the_users_own_words_still_mark_when_similar_but_not_identical(
    app_data: Path,
) -> None:
    """The user answering *about* the migration is not an echo of being asked about it."""
    tracker, note_set = build(app_data)
    tracker.observe_interviewer(them("tell me about the migration project", t=0.0))
    tracker.submit_user(
        mic("the migration rollback took four hours and I wrote the runbook", t=2.0)
    )
    assert note_set.notes[1].id in tracker.tick(10.0)


def test_a_distant_identical_phrase_is_not_an_echo(app_data: Path) -> None:
    """Echo is bounded in time. The same words two minutes later are the user's own."""
    tracker, note_set = build(app_data)
    phrase = "the migration project"
    tracker.observe_interviewer(them(phrase, t=0.0))
    tracker.submit_user(mic(phrase, t=120.0))
    assert note_set.notes[1].id in tracker.tick(200.0)
    assert tracker.suppressed_count == 0


def test_hold_window_delays_but_does_not_lose_the_mark(app_data: Path) -> None:
    tracker, note_set = build(app_data)
    tracker.submit_user(mic("conflict", t=0.0))
    assert tracker.tick(1.0 + ECHO_HOLD_S / 2) == [], "still inside the hold window"
    assert tracker.tick(1.0 + ECHO_HOLD_S + 0.01) == [note_set.notes[0].id]


def test_flush_releases_everything_held(app_data: Path) -> None:
    tracker, note_set = build(app_data)
    tracker.submit_user(mic("conflict", t=0.0))
    assert tracker.flush() == [note_set.notes[0].id]


def test_held_mic_utterances_are_bounded(app_data: Path) -> None:
    """FR33. `submit_user` appends and only tick/flush drain, so a caller that never
    ticks would otherwise grow this without limit."""
    tracker, _ = build(app_data)
    for i in range(500):
        tracker.submit_user(mic(f"utterance number {i}", t=float(i)))
    assert len(tracker._held) <= 32


def test_interviewer_memory_is_bounded(app_data: Path) -> None:
    """FR33: nothing in the pipeline grows with session length."""
    tracker, _ = build(app_data)
    for i in range(200):
        tracker.observe_interviewer(them(f"question number {i}", t=float(i)))
    assert len(tracker._recent_interviewer) <= 8


def test_tracker_records_no_transcript_content(app_data: Path) -> None:
    """FR36 — the tracker handles the user's own speech, so this matters here."""
    tracker, _ = build(app_data)
    phrase = "conflict resolution on the platform team"
    tracker.submit_user(mic(phrase))
    tracker.tick(10.0)
    assert phrase not in str(tracker.ring.export())


def test_tracker_writes_nothing_to_disk(app_data: Path) -> None:
    """The autouse allowlist would already fail this; asserted explicitly for FR16."""
    tracker, _ = build(app_data)
    before = {
        p: hashlib.sha256(p.read_bytes()).hexdigest() for p in app_data.rglob("*") if p.is_file()
    }
    tracker.submit_user(mic("conflict"))
    tracker.tick(10.0)
    after = {
        p: hashlib.sha256(p.read_bytes()).hexdigest() for p in app_data.rglob("*") if p.is_file()
    }
    assert before == after


# ---------------- helpers ----------------


def test_jaccard_bounds() -> None:
    assert jaccard("a b c", "a b c") == 1.0
    assert jaccard("a b c", "x y z") == 0.0
    assert jaccard("", "anything") == 0.0
    assert 0.0 < jaccard("a b c d", "a b c x") < 1.0


def test_jaccard_is_case_insensitive() -> None:
    assert jaccard("Tell Me About", "tell me about") == 1.0


def test_echo_threshold_is_the_documented_value() -> None:
    assert TAU_ECHO_TEXT == 0.80


def test_spans_overlap_window() -> None:
    a = Utterance("user", "x", 0.0, 1.0, "")
    assert spans_overlap(a, Utterance("interviewer", "x", 2.0, 3.0, ""))
    assert not spans_overlap(a, Utterance("interviewer", "x", 5.0, 6.0, ""))
