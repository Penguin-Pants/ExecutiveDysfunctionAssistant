"""T2.3 — utterance assembly (FR46, design §3)."""

from __future__ import annotations

import pytest

from interview_prep_recall.stt.assembler import (
    MAX_FRAGMENT_HOLD_S,
    StreamRouter,
    Utterance,
    UtteranceAssembler,
)
from interview_prep_recall.stt.interface import TranscriptEvent


def ev(text: str, t_start: float, t_end: float, *, final: bool = True, stream: str = "interviewer"):
    return TranscriptEvent(
        stream_id=stream,
        text=text,
        is_final=final,
        t_start=t_start,
        t_end=t_end,
        confidence=None,
        backend="fake",
    )


def test_interim_events_never_produce_an_utterance() -> None:
    """Contract rule 3: matching must never fire on an interim result."""
    a = UtteranceAssembler("interviewer")
    assert a.feed(ev("tell me about a time you", 0.0, 1.0, final=False)) == []
    assert a.tick(5.0) == []


def test_silence_gap_closes_an_utterance() -> None:
    a = UtteranceAssembler("interviewer")
    assert a.feed(ev("tell me about a conflict you handled", 0.0, 2.0)) == []
    out = a.tick(2.8)
    assert len(out) == 1
    assert out[0].text == "tell me about a conflict you handled"
    assert out[0].t_start == 0.0


def test_consecutive_finals_within_the_gap_join() -> None:
    a = UtteranceAssembler("interviewer")
    a.feed(ev("tell me about", 0.0, 1.0))
    a.feed(ev("a conflict you handled", 1.2, 2.0))
    out = a.tick(2.9)
    assert out[0].text == "tell me about a conflict you handled"


def test_gap_before_next_event_closes_the_previous() -> None:
    a = UtteranceAssembler("interviewer")
    a.feed(ev("what is your greatest weakness", 0.0, 2.0))
    out = a.feed(ev("and how do you handle it", 3.0, 4.0))
    assert len(out) == 1
    assert out[0].text == "what is your greatest weakness"


def test_max_span_forces_a_close() -> None:
    """A speaker who never pauses still gets cut, or the overlay waits forever."""
    a = UtteranceAssembler("interviewer")
    out: list[Utterance] = []
    for i in range(12):
        out += a.feed(ev(f"word{i} and more text", float(i), float(i) + 0.9))
    assert out, "a 10 s span must close without waiting for silence"
    assert out[0].duration >= 10.0


def test_short_fragment_merges_forward() -> None:
    a = UtteranceAssembler("interviewer")
    assert a.feed(ev("why?", 0.0, 0.3)) == []
    assert a.tick(1.2) == []  # held, not emitted
    a.feed(ev("tell me more about that project", 2.0, 3.0))
    out = a.tick(3.9)
    assert len(out) == 1
    assert out[0].text.startswith("why? tell me more")


def test_fragment_older_than_the_hold_window_is_dropped() -> None:
    a = UtteranceAssembler("interviewer")
    a.feed(ev("mm", 0.0, 0.2))
    a.tick(1.0)
    assert a.has_pending_fragment
    a.tick(MAX_FRAGMENT_HOLD_S + 1.0)
    assert not a.has_pending_fragment

    a.feed(ev("what did you learn from that", 40.0, 41.0))
    out = a.tick(42.0)
    assert out[0].text == "what did you learn from that"


def test_held_fragment_is_dropped_at_session_stop() -> None:
    """Firing a match on "why?" as the session ends serves nobody."""
    a = UtteranceAssembler("interviewer")
    a.feed(ev("why?", 0.0, 0.3))
    a.tick(1.2)
    assert a.stop() == []


def test_stop_emits_a_qualifying_open_span() -> None:
    a = UtteranceAssembler("interviewer")
    a.feed(ev("what motivates you in this role", 0.0, 2.0))
    out = a.stop()
    assert len(out) == 1


def test_context_carries_preceding_text_but_not_the_utterance_itself() -> None:
    a = UtteranceAssembler("interviewer")
    a.feed(ev("first question about your background", 0.0, 2.0))
    a.tick(2.8)
    a.feed(ev("second question about your leadership", 3.0, 5.0))
    out = a.tick(5.8)
    assert "first question" in out[0].context
    assert "second question" not in out[0].context


def test_context_window_excludes_old_text() -> None:
    a = UtteranceAssembler("interviewer")
    a.feed(ev("ancient history from long ago", 0.0, 2.0))
    a.tick(2.8)
    a.feed(ev("a much later question entirely", 100.0, 102.0))
    out = a.tick(102.8)
    assert out[0].context == ""


def test_crossed_streams_are_refused() -> None:
    a = UtteranceAssembler("interviewer")
    with pytest.raises(ValueError, match="streams must not be crossed"):
        a.feed(ev("hello there friend", 0.0, 1.0, stream="user"))


def test_reset_clears_all_transcript_state() -> None:
    a = UtteranceAssembler("interviewer")
    a.feed(ev("something said earlier here", 0.0, 2.0))
    a.tick(2.8)
    a.feed(ev("mm", 3.0, 3.2))
    a.tick(4.0)
    a.reset()
    assert not a.has_pending_fragment
    a.feed(ev("a brand new question follows", 10.0, 12.0))
    out = a.tick(12.8)
    assert out[0].context == ""


def test_history_is_bounded() -> None:
    """FR33: nothing in the pipeline grows with session length."""
    a = UtteranceAssembler("interviewer")
    for i in range(200):
        a.feed(ev(f"question number {i} with padding text", i * 3.0, i * 3.0 + 2.0))
        a.tick(i * 3.0 + 2.9)
    assert len(a._history) <= 16


# ---------- FR53 routing ----------


def test_router_sends_interviewer_to_matching_and_mic_to_tracking() -> None:
    router = StreamRouter()
    router.route(Utterance("interviewer", "their question", 0.0, 1.0, ""))
    router.route(Utterance("user", "my answer", 1.0, 2.0, ""))
    assert [u.stream_id for u in router.drain_matching()] == ["interviewer"]
    assert [u.stream_id for u in router.drain_tracking()] == ["user"]


def test_router_rejects_unknown_streams() -> None:
    with pytest.raises(ValueError, match="unknown stream"):
        StreamRouter().route(Utterance("someone-else", "x", 0.0, 1.0, ""))


def test_stale_fragment_is_not_merged_when_the_close_comes_from_feed() -> None:
    """Found in local review: `_close` merged unconditionally, and `tick` expired too late.

    A held "mm" 40 s old was glued onto an unrelated question and dragged the
    utterance's `t_start` back with it, which also corrupts the context-window anchor.
    """
    a = UtteranceAssembler("interviewer")
    a.feed(ev("mm", 0.0, 0.2))
    a.tick(1.0)
    assert a.has_pending_fragment

    # No intervening tick near the expiry boundary — the close arrives via feed().
    a.feed(ev("what did you learn from that project", 41.0, 42.0))
    out = a.tick(43.0)

    assert len(out) == 1
    assert out[0].text == "what did you learn from that project"
    assert out[0].t_start == 41.0, "a stale fragment must not drag t_start backwards"
