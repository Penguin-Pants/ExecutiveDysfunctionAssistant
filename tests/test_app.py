"""T9.0 — the composition root (FR37, FR74, FR78a, D-23).

Every test here is about a **connection**, not a component. The components have their own
suites and pass them; the three defects this task closes were all cases where two
correct pieces were not joined, and no component-level test could have seen that.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from helpers import ReversingCipher, ScriptedClient  # noqa: F401

from interview_prep_recall.app import (
    Application,
    CloudSwitchFanout,
    ReportLocalOnlyAdapter,
)
from interview_prep_recall.notes.model import ContextSet, Note, SourceKind
from interview_prep_recall.report.generator import ReportUnavailableError
from interview_prep_recall.session.health import Egress
from interview_prep_recall.stt.assembler import Utterance


class FlatEmbedder:
    model_id = "flat/one"
    model_version = "1.0"

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.ones((len(texts), 2), dtype=np.float32)


def _context() -> ContextSet:
    return ContextSet(
        name="Acme",
        notes=[
            Note(headline="Tell me about a migration", kind=SourceKind.PREP, track_progress=True),
            Note(headline="Tell me about scaling", kind=SourceKind.PREP, track_progress=True),
            Note(headline="Senior engineer wanted", kind=SourceKind.ROLE),
        ],
    )


def _app(tmp: Path, client: ScriptedClient | None = None) -> Application:
    return Application(
        root=tmp,
        embedder=FlatEmbedder(),
        client=client or ScriptedClient(),
        cipher=ReversingCipher(),
        context_set=_context(),
    )


def _report_requests(client: ScriptedClient) -> list[dict]:
    """Requests carrying the report tool.

    The composition root deliberately shares one model client between matching and
    report generation, so `client.requests == []` proves nothing — stage 2 fires during
    `consume()` and is *supposed* to. Only the report tool distinguishes the caller, and
    getting this wrong would have made two D-23 tests pass for the wrong reason.
    """
    return [
        r for r in client.requests if any(t["name"] == "submit_report" for t in r.get("tools", []))
    ]


def _utterance(text: str, *, stream: str, start: float = 0.0) -> Utterance:
    return Utterance(stream_id=stream, text=text, t_start=start, t_end=start + 1.0, context="")


# ---------- D-23: one switch, every cloud consumer ----------


def test_the_switch_reaches_every_cloud_consumer(app_data) -> None:  # type: ignore[no-untyped-def]
    """The defect this task exists to close.

    `attach_matching` takes one target because the pipeline was the only API consumer
    when the switch was written. M11 added a second and nothing connected it — the
    switch would go off, the indicator would read local-only, and report generation would
    keep sending the whole transcript to Anthropic.

    Asserted **per consumer**, not on the switch object: checking `switches.llm_matching`
    is false is exactly the test that would have passed while the bug was live.
    """
    app = _app(app_data)
    app.session.set_switch("llm_matching", False)

    assert app.pipeline.local_only is True
    assert app.reports.local_only is True

    app.session.set_switch("llm_matching", True)
    assert app.pipeline.local_only is False
    assert app.reports.local_only is False


def test_local_only_actually_refuses_report_generation(app_data) -> None:  # type: ignore[no-untyped-def]
    """The consequence, not just the flag. A field that flips while generation still
    calls the API is the D-23 failure with an extra step."""
    client = ScriptedClient()
    app = _app(app_data, client)
    app.consent.acknowledge()
    app.consume(_utterance("a question", stream="interviewer"), now=1.0)

    app.session.set_switch("llm_matching", False)
    with pytest.raises(ReportUnavailableError, match="local-only"):
        app.generate_report(role="Role", confirm=lambda _: True)
    assert _report_requests(client) == []


def test_a_consumer_without_the_switch_shape_is_refused() -> None:
    """Registration fails loudly. A consumer added later that silently ignores the
    switch is the same defect, one generation on."""
    fanout = CloudSwitchFanout()
    with pytest.raises(TypeError, match="set_local_only"):
        fanout.register(object())


def test_flipping_the_switch_with_no_consumers_raises() -> None:
    """Otherwise the indicator reports local-only while nothing was switched."""
    with pytest.raises(RuntimeError, match="no cloud consumers"):
        CloudSwitchFanout().set_local_only(True)


def test_the_adapter_writes_through_to_the_generator(app_data) -> None:  # type: ignore[no-untyped-def]
    app = _app(app_data)
    adapter = ReportLocalOnlyAdapter(app.reports)
    adapter.set_local_only(True)
    assert app.reports.local_only is True


# ---------- FR74: the record has a producer ----------


def test_finalised_utterances_reach_the_record(app_data) -> None:  # type: ignore[no-untyped-def]
    """The record shipped in M11 with nothing feeding it."""
    app = _app(app_data)
    app.consume(_utterance("a question", stream="interviewer", start=0.0), now=1.0)
    app.consume(_utterance("an answer", stream="user", start=2.0), now=3.0)

    assert [u.text for u in app.record.utterances] == ["a question", "an answer"]


def test_the_record_gets_both_streams_not_just_the_routed_half(app_data) -> None:  # type: ignore[no-untyped-def]
    """Fed **before** routing, deliberately. The router splits by purpose — matching sees
    the interviewer, the tracker sees the mic — so recording downstream of it would
    capture half the conversation while the report claimed to cover the meeting."""
    app = _app(app_data)
    app.consume(_utterance("interviewer says", stream="interviewer", start=0.0), now=1.0)
    app.consume(_utterance("user says", stream="user", start=2.0), now=3.0)

    streams = {u.stream_id for u in app.record.utterances}
    assert streams == {"interviewer", "user"}


def test_starting_a_session_clears_the_previous_record(app_data) -> None:  # type: ignore[no-untyped-def]
    app = _app(app_data)
    app.consume(_utterance("old", stream="user"), now=1.0)
    app.reset_for_new_session()
    assert len(app.record) == 0


# ---------- FR78a: coverage has one adjudicator ----------


def test_the_reports_missed_points_come_from_the_tracker(app_data) -> None:  # type: ignore[no-untyped-def]
    """The tracker decides during the interview; the report is told. Two mechanisms
    would eventually disagree with the checklist the user watched, and nothing would
    reconcile them."""
    app = _app(app_data)
    tracked = app.context_set.tracked()
    assert len(tracked) == 2

    # Nothing said yet: every tracked point is uncovered.
    assert app.missed_note_ids() == frozenset(n.id for n in tracked)


def test_a_covered_point_leaves_the_missed_set(app_data) -> None:  # type: ignore[no-untyped-def]
    """Positive control. Without it the test above passes against a `missed_note_ids`
    that returns every tracked point unconditionally."""
    app = _app(app_data)
    # FlatEmbedder makes every similarity 1.0, so any mic utterance marks every point.
    app.consume(_utterance("I led a migration", stream="user", start=0.0), now=0.1)
    app.tracker.tick(now=99.0)

    assert app.missed_note_ids() == frozenset()


def test_the_missed_set_is_what_generation_is_given(app_data) -> None:  # type: ignore[no-untyped-def]
    """Closes the loop: the tracker's verdict has to arrive in the prompt, not merely
    be computable."""
    client = ScriptedClient()
    app = _app(app_data, client)
    app.consent.acknowledge()
    app.consume(_utterance("a question", stream="interviewer"), now=1.0)

    app.generate_report(role="Staff Engineer", confirm=lambda _: True)

    prompt = _report_requests(client)[0]["messages"][0]["content"]
    for note in app.context_set.tracked():
        assert note.id in prompt


# ---------- the report path ----------


def test_the_transcript_is_stored_before_generation_is_attempted(app_data) -> None:  # type: ignore[no-untyped-def]
    """A declined or failed generation must not cost the user the interview. Storing
    after the call would lose the session precisely when the model was unavailable."""
    app = _app(app_data)
    app.consent.acknowledge()
    app.consume(_utterance("a question", stream="interviewer"), now=1.0)

    with pytest.raises(ReportUnavailableError, match="declined"):
        app.generate_report(role="Role", confirm=lambda _: False)

    stored = app.sessions.list_sessions()
    assert len(stored) == 1
    assert stored[0].has_report is False
    assert [u.text for u in app.sessions.load(stored[0].id).utterances] == ["a question"]


def test_a_successful_report_is_attached_to_its_session(app_data) -> None:  # type: ignore[no-untyped-def]
    app = _app(app_data)
    app.consent.acknowledge()
    app.consume(_utterance("a question", stream="interviewer"), now=1.0)

    session_id, report = app.generate_report(role="Role", confirm=lambda _: True)

    loaded = app.sessions.load(session_id)
    assert loaded.report is not None
    assert loaded.report["sections"], "the report was attached empty"
    assert report.absent_sources  # resume and company were never loaded


def test_generation_is_refused_before_the_disclosure_is_acknowledged(app_data) -> None:  # type: ignore[no-untyped-def]
    """FR85 reaching the real object graph, not just the generator's own unit test."""
    client = ScriptedClient()
    app = _app(app_data, client)
    app.consume(_utterance("a question", stream="interviewer"), now=1.0)

    with pytest.raises(ReportUnavailableError, match="disclosure"):
        app.generate_report(role="Role", confirm=lambda _: True)
    assert _report_requests(client) == []


def test_the_egress_indicator_is_shared_with_the_health_monitor(app_data) -> None:  # type: ignore[no-untyped-def]
    """FR20. A generator holding its own private `EgressMonitor` would light an
    indicator nothing displays."""
    app = _app(app_data)
    assert app.reports.egress is app.egress
    app.egress.set_llm(True)
    assert app.monitor.health.egress is Egress.LLM


# ---------- purge wiring ----------


def test_purging_the_session_drops_the_transcript(app_data) -> None:  # type: ignore[no-untyped-def]
    """The record is session state, so it has to be on the purge path — a purge that
    left the transcript in memory would contradict FR15 while reporting success."""
    app = _app(app_data)
    app.consume(_utterance("something said", stream="user"), now=1.0)
    assert len(app.record) == 1

    app.session.request_start()
    app.session.preflight_result(blocked=False)
    app.session.end_session()

    assert len(app.record) == 0


def test_the_wired_purge_hooks_are_pinned(app_data) -> None:  # type: ignore[no-untyped-def]
    """Three of the five FR59 hooks have no component to wire to yet — `stop_capture`
    and `zero_audio` need M1, `clear_overlay` needs M5.

    `PurgeHooks` defaults them to no-ops that report success, so a purge today claims
    audio was cleared. That is vacuously true while no capture exists and a **false
    statement** the moment M1 lands without revisiting this wiring. Pinning the set makes
    that a failing test then, rather than something whoever writes M1 has to remember.
    """
    app = _app(app_data)
    assert app.wired_purge_hooks() == {"cancel_network", "drop_transcript"}, (
        "the wired hook set changed — if a component was added, wire its hook; if one "
        "was removed, say why here"
    )
