"""M4 — prefilter, selector, sequence gate, fallback, retry, ceiling (T4.1–T4.6)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from interview_prep_recall.matching.pipeline import (
    CALL_CEILING_DEFAULT,
    MatchingPipeline,
    MatchResult,
    Outcome,
    is_retryable,
)
from interview_prep_recall.matching.prefilter import Prefilter, tau_degraded_for
from interview_prep_recall.matching.selector import (
    NONE_CHOICE,
    TOOL_NAME,
    SelectorProtocolError,
    Stage2Selector,
    build_request,
    parse_response,
)
from interview_prep_recall.notes.index import EmbeddingIndex
from interview_prep_recall.notes.model import Note, NoteSet
from interview_prep_recall.stt.assembler import Utterance

# ---------------- fakes ----------------


class WordEmbedder:
    """Bag-of-words vectors: similarity is controllable and human-legible in tests."""

    model_id = "test/word"
    model_version = "1.0"
    VOCAB = ["conflict", "leadership", "weakness", "migration", "team", "deadline", "python", "why"]

    def encode(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), len(self.VOCAB)), dtype=np.float32)
        for i, text in enumerate(texts):
            words = text.lower().split()
            for j, term in enumerate(self.VOCAB):
                out[i, j] = float(sum(1 for w in words if term in w))
        return out


@dataclass
class FakeBlock:
    type: str
    name: str | None = None
    input: dict[str, Any] | None = None


@dataclass
class FakeResponse:
    content: list[FakeBlock]


class FakeClient:
    """Records requests and returns a scripted note id, or raises."""

    def __init__(self, note_id: str | None = NONE_CHOICE, error: Exception | None = None) -> None:
        self.note_id = note_id
        self.error = error
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        if self.error is not None:
            raise self.error
        return FakeResponse([FakeBlock("tool_use", TOOL_NAME, {"note_id": self.note_id})])


class HttpError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class ManualRunner:
    """Holds calls so tests complete them in any order — the T4.3 race, deterministically."""

    def __init__(self) -> None:
        self.queue: list[tuple[Any, Any]] = []

    def submit(self, fn: Any, on_done: Any) -> None:
        self.queue.append((fn, on_done))

    def complete(self, index: int) -> None:
        fn, on_done = self.queue.pop(index)
        try:
            on_done(fn(), None)
        except Exception as exc:  # noqa: BLE001
            on_done(None, exc)


def utt(text: str, stream: str = "interviewer", context: str = "") -> Utterance:
    return Utterance(stream, text, 0.0, 1.0, context)


def build(app_data: Path, n_extra: int = 0) -> tuple[Prefilter, NoteSet]:
    notes = [
        Note(headline="Tell me about a conflict on your team?", tags=["conflict"]),
        Note(headline="Describe your leadership style?", tags=["leadership"]),
        Note(headline="What is your greatest weakness?", tags=["weakness"]),
        Note(headline="Walk me through the migration project?", tags=["migration"]),
    ]
    notes += [Note(headline=f"Filler question about python {i}?") for i in range(n_extra)]
    note_set = NoteSet(name="test", notes=notes)
    embedder = WordEmbedder()
    index = EmbeddingIndex(app_data, embedder)
    index.build(note_set)
    return Prefilter(index, note_set, embedder), note_set


# ---------------- T4.1 prefilter ----------------


def test_prefilter_returns_relevant_candidates(app_data: Path) -> None:
    prefilter, _ = build(app_data)
    got = prefilter.candidates("tell me about a conflict")
    assert got and got[0].headline.startswith("Tell me about a conflict")


def test_prefilter_returns_empty_for_unrelated_speech(app_data: Path) -> None:
    """FR50: the overlay stays empty rather than showing a guess."""
    prefilter, _ = build(app_data)
    assert prefilter.candidates("the weather is pleasant today") == []


def test_prefilter_caps_at_top_k(app_data: Path) -> None:
    prefilter, _ = build(app_data, n_extra=50)
    assert len(prefilter.candidates("python")) <= prefilter.top_k


def test_prefilter_results_are_sorted_descending(app_data: Path) -> None:
    prefilter, _ = build(app_data, n_extra=20)
    scores = [c.similarity for c in prefilter.candidates("python conflict")]
    assert scores == sorted(scores, reverse=True)


def test_prefilter_latency_under_50ms_for_200_notes(app_data: Path) -> None:
    """T4.1 acceptance criterion."""
    prefilter, _ = build(app_data, n_extra=196)
    prefilter.candidates("warmup conflict")
    start = time.perf_counter()
    for _ in range(20):
        prefilter.candidates("tell me about a conflict on the team")
    elapsed_ms = (time.perf_counter() - start) * 1000 / 20
    assert elapsed_ms < 50.0, f"prefilter took {elapsed_ms:.1f} ms"


def test_tau_floor_outside_the_control_range_is_refused(app_data: Path) -> None:
    prefilter, _ = build(app_data)
    with pytest.raises(ValueError, match="control range"):
        prefilter.tau_floor = 0.95


def test_tau_degraded_tracks_tau_floor() -> None:
    """Derived, never independent — otherwise the degraded gate becomes unconditional."""
    assert tau_degraded_for(0.35) == 0.55
    assert tau_degraded_for(0.60) == pytest.approx(0.70)
    assert tau_degraded_for(0.55) > 0.55


def test_prefilter_skips_notes_deleted_since_the_last_index_build(app_data: Path) -> None:
    prefilter, note_set = build(app_data)
    note_set.delete(note_set.notes[0].id)
    ids = {c.note_id for c in prefilter.candidates("conflict")}
    assert all(note_set.get(i) is not None for i in ids)


# ---------------- T4.2 selector ----------------


def test_request_forces_the_tool_and_bounds_the_enum(app_data: Path) -> None:
    """FR48: enum holds the prefiltered candidates only, never the whole note set."""
    prefilter, _ = build(app_data, n_extra=196)
    candidates = prefilter.candidates("tell me about a conflict")
    request = build_request(utt("tell me about a conflict"), candidates)

    assert request.tool_choice == {"type": "tool", "name": TOOL_NAME}
    enum = request.tools[0]["input_schema"]["properties"]["note_id"]["enum"]
    assert len(enum) <= 6
    assert enum[-1] == NONE_CHOICE
    assert request.max_tokens == 50
    assert request.temperature == 0


def test_request_sends_headline_and_tags_but_never_body(app_data: Path) -> None:
    prefilter, note_set = build(app_data)
    note_set.notes[0].body = "SECRET_BODY_TEXT that must not be sent"
    candidates = prefilter.candidates("conflict")
    content = build_request(utt("conflict"), candidates).messages[0]["content"]
    assert "SECRET_BODY_TEXT" not in content
    assert "conflict" in content


def test_context_is_included_in_the_prompt(app_data: Path) -> None:
    prefilter, _ = build(app_data)
    candidates = prefilter.candidates("conflict")
    content = build_request(utt("conflict", context="earlier chat"), candidates).messages[0][
        "content"
    ]
    assert "earlier chat" in content


def test_freeform_response_is_rejected(app_data: Path) -> None:
    """FR10 is structural: a helpful-looking text reply is a protocol failure."""
    prefilter, _ = build(app_data)
    candidates = prefilter.candidates("conflict")
    response = FakeResponse([FakeBlock("text")])
    with pytest.raises(SelectorProtocolError, match="no select_note tool call"):
        parse_response(response, candidates)


def test_note_id_outside_the_enum_is_rejected(app_data: Path) -> None:
    prefilter, _ = build(app_data)
    candidates = prefilter.candidates("conflict")
    response = FakeResponse([FakeBlock("tool_use", TOOL_NAME, {"note_id": "fabricated-id"})])
    with pytest.raises(SelectorProtocolError, match="not offered"):
        parse_response(response, candidates)


def test_none_parses_to_none(app_data: Path) -> None:
    prefilter, _ = build(app_data)
    candidates = prefilter.candidates("conflict")
    response = FakeResponse([FakeBlock("tool_use", TOOL_NAME, {"note_id": NONE_CHOICE})])
    assert parse_response(response, candidates) is None


def test_selector_refuses_an_empty_candidate_list(app_data: Path) -> None:
    selector = Stage2Selector(FakeClient())
    with pytest.raises(ValueError, match="empty candidate list"):
        selector.select(utt("anything"), [])


# ---------------- T4.3 sequence gate ----------------


def collect(app_data: Path, **kw: Any) -> tuple[MatchingPipeline, list[MatchResult], ManualRunner]:
    prefilter, note_set = build(app_data)
    results: list[MatchResult] = []
    runner = ManualRunner()
    client = kw.pop("client", None) or FakeClient(note_id=note_set.notes[0].id)
    pipeline = MatchingPipeline(
        prefilter=prefilter,
        selector=Stage2Selector(client),
        on_result=results.append,
        runner=runner,
        **kw,
    )
    return pipeline, results, runner


def test_out_of_order_completion_never_renders_a_stale_result(app_data: Path) -> None:
    """T4.3's explicit criterion: dispatch A(1), dispatch B(2), complete A first."""
    pipeline, results, runner = collect(app_data)

    pipeline.submit(utt("tell me about a conflict"))  # A, seq 1 -> issued
    pipeline.submit(utt("describe your leadership style"))  # B, seq 2 -> pending

    assert pipeline.latest_issued == 2, "sequence must advance at queue time, not issue time"

    runner.complete(0)  # A returns first
    assert all(r.seq != 1 for r in results), "A superseded by B must never render"

    assert runner.queue, "B must be issued once A completes"
    runner.complete(0)
    assert [r.seq for r in results] == [2]


def test_a_completing_before_b_is_dispatched_does_render(app_data: Path) -> None:
    """The other branch — a gate that discards everything also passes the first test."""
    pipeline, results, runner = collect(app_data)
    pipeline.submit(utt("tell me about a conflict"))
    runner.complete(0)
    assert [r.seq for r in results] == [1]


def test_purge_discards_an_in_flight_response(app_data: Path) -> None:
    """FR59: nonce rotation, because a reset counter alone lets seq=1 match seq=1."""
    pipeline, results, runner = collect(app_data)
    pipeline.submit(utt("tell me about a conflict"))
    pipeline.purge()
    runner.complete(0)
    assert results == []


def test_post_purge_sequence_collision_is_still_discarded(app_data: Path) -> None:
    """The precise hole the nonce closes: same seq either side of a purge."""
    pipeline, results, runner = collect(app_data)
    pipeline.submit(utt("tell me about a conflict"))  # seq 1, in flight
    pipeline.purge()  # counter back to 0
    pipeline.submit(utt("describe your leadership style"))  # also seq 1

    runner.complete(0)  # the PRE-purge call
    assert results == [], "a pre-purge response must not satisfy the new session's seq 1"

    runner.complete(0)
    assert len(results) == 1


def test_only_one_call_in_flight(app_data: Path) -> None:
    """T4.5 / D-11."""
    pipeline, _, runner = collect(app_data)
    pipeline.submit(utt("tell me about a conflict"))
    pipeline.submit(utt("describe your leadership style"))
    pipeline.submit(utt("what is your greatest weakness"))
    assert len(runner.queue) == 1


def test_newest_pending_displaces_the_older_one(app_data: Path) -> None:
    pipeline, results, runner = collect(app_data)
    pipeline.submit(utt("tell me about a conflict"))  # 1, issued
    pipeline.submit(utt("describe your leadership style"))  # 2, pending
    pipeline.submit(utt("what is your greatest weakness"))  # 3, displaces 2

    runner.complete(0)
    runner.complete(0)
    assert [r.seq for r in results] == [3]


# ---------------- T4.4 degraded fallback ----------------


def test_stage2_failure_above_tau_degraded_emits_degraded(app_data: Path) -> None:
    prefilter, note_set = build(app_data)
    results: list[MatchResult] = []
    pipeline = MatchingPipeline(
        prefilter=prefilter,
        selector=Stage2Selector(FakeClient(error=HttpError(500))),
        on_result=results.append,
        sleep=lambda _s: None,
    )
    # Identical text to a headline scores 1.0, comfortably above τ_degraded.
    pipeline.submit(utt("Tell me about a conflict on your team?"))
    assert results[-1].outcome is Outcome.DEGRADED
    assert results[-1].note_id == note_set.notes[0].id


def test_stage2_failure_below_tau_degraded_emits_no_match(app_data: Path) -> None:
    """FR49/US-D2: a weak guess is worse than nothing, especially when degraded."""
    prefilter, _ = build(app_data)
    results: list[MatchResult] = []
    pipeline = MatchingPipeline(
        prefilter=prefilter,
        selector=Stage2Selector(FakeClient(error=HttpError(500))),
        on_result=results.append,
        sleep=lambda _s: None,
    )
    prefilter.tau_floor = 0.20
    pipeline.submit(utt("team deadline"))
    assert results[-1].outcome is Outcome.NO_MATCH
    assert results[-1].note_id is None


def test_stage2_none_emits_no_match(app_data: Path) -> None:
    pipeline, results, runner = collect(app_data, client=FakeClient(note_id=NONE_CHOICE))
    pipeline.submit(utt("tell me about a conflict"))
    runner.complete(0)
    assert results[-1].outcome is Outcome.NO_MATCH


def test_protocol_violation_takes_the_degraded_path(app_data: Path) -> None:
    """A fabricated id is a failure, not a result to trust."""
    pipeline, results, runner = collect(app_data, client=FakeClient(note_id="not-a-candidate"))
    pipeline.submit(utt("Tell me about a conflict on your team?"))
    runner.complete(0)
    assert results[-1].outcome is Outcome.DEGRADED


# ---------------- T4.5 retry and ceiling ----------------


@pytest.mark.parametrize("status", [429, 500, 503])
def test_retryable_statuses(status: int) -> None:
    assert is_retryable(HttpError(status))


@pytest.mark.parametrize("status", [400, 401, 404, 422])
def test_non_retryable_statuses(status: int) -> None:
    assert not is_retryable(HttpError(status))


def test_at_most_one_retry(app_data: Path) -> None:
    prefilter, _ = build(app_data)
    client = FakeClient(error=HttpError(429))
    pipeline = MatchingPipeline(
        prefilter=prefilter,
        selector=Stage2Selector(client),
        on_result=lambda _r: None,
        sleep=lambda _s: None,
    )
    pipeline.submit(utt("Tell me about a conflict on your team?"))
    assert len(client.requests) == 2, "one attempt plus at most one retry"


def test_no_retry_on_a_non_retryable_status(app_data: Path) -> None:
    prefilter, _ = build(app_data)
    client = FakeClient(error=HttpError(400))
    pipeline = MatchingPipeline(
        prefilter=prefilter, selector=Stage2Selector(client), on_result=lambda _r: None
    )
    pipeline.submit(utt("Tell me about a conflict on your team?"))
    assert len(client.requests) == 1


def test_ceiling_switches_to_local_only_and_signals(app_data: Path) -> None:
    prefilter, _ = build(app_data)
    client = FakeClient(error=HttpError(429))
    pipeline = MatchingPipeline(
        prefilter=prefilter,
        selector=Stage2Selector(client),
        on_result=lambda _r: None,
        call_ceiling=2,
        sleep=lambda _s: None,
    )
    pipeline.submit(utt("Tell me about a conflict on your team?"))
    assert pipeline.local_only
    events = [e.event for e in pipeline.ring.snapshot()]
    assert "matching_mode" in events

    before = len(client.requests)
    pipeline.submit(utt("Describe your leadership style?"))
    assert len(client.requests) == before, "local-only must stop calling the API"


def test_local_only_still_emits_a_degraded_match(app_data: Path) -> None:
    prefilter, note_set = build(app_data)
    results: list[MatchResult] = []
    pipeline = MatchingPipeline(prefilter=prefilter, selector=None, on_result=results.append)
    assert pipeline.local_only
    pipeline.submit(utt("Tell me about a conflict on your team?"))
    assert results[-1].outcome is Outcome.DEGRADED
    assert results[-1].note_id == note_set.notes[0].id


def test_degradation_switch_is_reversible(app_data: Path) -> None:
    """FR37: toggled mid-session without a restart."""
    pipeline, _results, runner = collect(app_data)
    pipeline.set_local_only(True)
    pipeline.submit(utt("Tell me about a conflict on your team?"))
    assert runner.queue == []
    pipeline.set_local_only(False)
    pipeline.submit(utt("Describe your leadership style?"))
    assert len(runner.queue) == 1


def test_default_ceiling_matches_the_plan() -> None:
    assert CALL_CEILING_DEFAULT == 400


# ---------------- T4.6 stream isolation ----------------


def test_mic_utterances_never_enter_matching(app_data: Path) -> None:
    """FR53/D-10. Matching on the user's own speech surfaces notes about what they said."""
    pipeline, _, _ = collect(app_data)
    with pytest.raises(ValueError, match="interviewer stream only"):
        pipeline.submit(utt("I handled that conflict by writing a doc", stream="user"))


# ---------------- diagnostics ----------------


def test_pipeline_records_no_transcript_content(app_data: Path) -> None:
    """FR36: the ring holds structure, and the pipeline is a heavy writer to it."""
    pipeline, _, runner = collect(app_data)
    phrase = "tell me about a conflict"
    pipeline.submit(utt(phrase))
    runner.complete(0)
    blob = str(pipeline.ring.export())
    assert phrase not in blob


def test_empty_candidates_short_circuits_without_a_call(app_data: Path) -> None:
    pipeline, results, runner = collect(app_data)
    pipeline.submit(utt("the weather is pleasant today"))
    assert runner.queue == []
    assert results[-1].outcome is Outcome.NO_MATCH


# ---------------- purge resets session-scoped state ----------------


def test_purge_preserves_the_attempt_counter(app_data: Path) -> None:
    """Panic clear is resumable (D-U5/FR64) — same session, so the budget must survive.

    Resetting here would hand a fresh 400-call budget to anyone pressing the panic
    button. `start_session()` is the transition that resets.
    """
    prefilter, _ = build(app_data)
    client = FakeClient(error=HttpError(429))
    pipeline = MatchingPipeline(
        prefilter=prefilter,
        selector=Stage2Selector(client),
        on_result=lambda _r: None,
        call_ceiling=4,
        sleep=lambda _s: None,
    )
    pipeline.submit(utt("Tell me about a conflict on your team?"))
    assert pipeline.attempts == 2

    pipeline.purge()
    assert pipeline.attempts == 2

    pipeline.start_session()
    assert pipeline.attempts == 0


def test_new_session_clears_a_ceiling_induced_local_only(app_data: Path) -> None:
    prefilter, _ = build(app_data)
    pipeline = MatchingPipeline(
        prefilter=prefilter,
        selector=Stage2Selector(FakeClient(error=HttpError(429))),
        on_result=lambda _r: None,
        call_ceiling=2,
        sleep=lambda _s: None,
    )
    pipeline.submit(utt("Tell me about a conflict on your team?"))
    assert pipeline.local_only

    pipeline.purge()
    assert pipeline.local_only, "a panic clear resumes the same session; degradation stands"

    pipeline.start_session()
    assert not pipeline.local_only, "a new session must not inherit the old one's degradation"


def test_purge_preserves_a_user_chosen_local_only(app_data: Path) -> None:
    """The FR37 switch is a preference, not a failure state."""
    pipeline, _results, _runner = collect(app_data)
    pipeline.set_local_only(True)
    pipeline.purge()
    assert pipeline.local_only
    pipeline.start_session()
    assert pipeline.local_only, "a user preference is not a failure state to clear"


def test_context_is_capped(app_data: Path) -> None:
    """Context enters every stage-2 prompt, so it is a per-call token cost."""
    from interview_prep_recall.stt.assembler import (
        MAX_CONTEXT_CHARS,
        UtteranceAssembler,
    )
    from interview_prep_recall.stt.interface import TranscriptEvent

    a = UtteranceAssembler("interviewer")
    t = 0.0
    for i in range(15):
        a.feed(
            TranscriptEvent(
                stream_id="interviewer",
                text=f"padding sentence number {i} " + ("long " * 30),
                is_final=True,
                t_start=t,
                t_end=t + 0.5,
                confidence=None,
                backend="fake",
            )
        )
        a.tick(t + 1.3)
        t += 1.4
    a.feed(
        TranscriptEvent(
            stream_id="interviewer",
            text="and now the actual question please",
            is_final=True,
            t_start=t,
            t_end=t + 0.5,
            confidence=None,
            backend="fake",
        )
    )
    out = a.tick(t + 1.3)
    assert out and len(out[0].context) <= MAX_CONTEXT_CHARS


# ---------------- fixes from the local review ----------------


def test_request_carries_a_hard_timeout(app_data: Path) -> None:
    """FR59 leans on this: the call cannot be cancelled, so it must be bounded."""
    from interview_prep_recall.matching.selector import REQUEST_TIMEOUT_S

    prefilter, _ = build(app_data)
    candidates = prefilter.candidates("conflict")
    client = FakeClient()
    Stage2Selector(client).select(utt("conflict"), candidates)
    assert client.requests[0]["timeout"] == REQUEST_TIMEOUT_S


def test_retry_backs_off_before_the_second_attempt(app_data: Path) -> None:
    """FR40 says "with backoff" — an instant retry spends the attempt while the limit holds."""
    from interview_prep_recall.matching.pipeline import RETRY_BACKOFF_S

    prefilter, _ = build(app_data)
    slept: list[float] = []
    pipeline = MatchingPipeline(
        prefilter=prefilter,
        selector=Stage2Selector(FakeClient(error=HttpError(429))),
        on_result=lambda _r: None,
        sleep=slept.append,
    )
    pipeline.submit(utt("Tell me about a conflict on your team?"))
    assert slept == [RETRY_BACKOFF_S]


def test_no_backoff_when_the_error_is_not_retryable(app_data: Path) -> None:
    prefilter, _ = build(app_data)
    slept: list[float] = []
    pipeline = MatchingPipeline(
        prefilter=prefilter,
        selector=Stage2Selector(FakeClient(error=HttpError(400))),
        on_result=lambda _r: None,
        sleep=slept.append,
    )
    pipeline.submit(utt("Tell me about a conflict on your team?"))
    assert slept == []


def test_freeform_response_is_rejected_through_the_selector(app_data: Path) -> None:
    """T4.2 phrases this as "rejected by the client", i.e. end-to-end, not just the parser."""

    class FreeformClient:
        def create(self, **kwargs: Any) -> Any:
            return FakeResponse([FakeBlock("text")])

    prefilter, _ = build(app_data)
    candidates = prefilter.candidates("conflict")
    with pytest.raises(SelectorProtocolError):
        Stage2Selector(FreeformClient()).select(utt("conflict"), candidates)


def test_runner_does_not_emit_twice_when_the_callback_raises(app_data: Path) -> None:
    """A try wrapping both fn() and on_done() re-enters the callback as a failure."""
    from interview_prep_recall.matching.pipeline import InlineRunner

    calls: list[tuple[Any, Any]] = []

    def on_done(value: Any, exc: BaseException | None) -> None:
        calls.append((value, exc))
        raise RuntimeError("consumer blew up")

    with pytest.raises(RuntimeError, match="consumer blew up"):
        InlineRunner().submit(lambda: "ok", on_done)
    assert len(calls) == 1, "one request must produce exactly one completion"


def test_stale_completion_cannot_free_the_in_flight_slot(app_data: Path) -> None:
    """A fourth hole in the same mechanism, found in local review.

    Sequences restart at every purge, so a pre-purge completion can carry the same seq
    as a live post-purge call. Clearing `_in_flight` on seq alone freed the slot while
    that call was still running, letting a second call be issued — silently breaking
    the one-in-flight invariant the whole gate rests on.
    """
    pipeline, _results, runner = collect(app_data)

    pipeline.submit(utt("Tell me about a conflict on your team?"))  # A: pre-purge, seq 1
    pipeline.purge()
    pipeline.submit(utt("Describe your leadership style?"))  # B: post-purge, also seq 1
    assert len(runner.queue) == 2  # A (orphaned) and B (live)

    runner.complete(0)  # stale A completes
    assert pipeline.in_flight, "B is still running; the slot must not be freed"

    pipeline.submit(utt("What is your greatest weakness?"))  # C must queue, not issue
    assert len(runner.queue) == 1, "C was issued while B was still in flight"


def test_ceiling_reached_via_a_non_retryable_error_still_degrades(app_data: Path) -> None:
    """The budget is spent regardless of why the last call failed (FR40)."""
    prefilter, _ = build(app_data)
    pipeline = MatchingPipeline(
        prefilter=prefilter,
        selector=Stage2Selector(FakeClient(error=HttpError(400))),
        on_result=lambda _r: None,
        call_ceiling=1,
        sleep=lambda _s: None,
    )
    pipeline.submit(utt("Tell me about a conflict on your team?"))
    assert pipeline.attempts == 1
    assert pipeline.local_only, "ceiling exhausted by a 400 must still be announced"
