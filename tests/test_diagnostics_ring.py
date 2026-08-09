"""T0.3 — diagnostic ring buffer (FR36)."""

from __future__ import annotations

import json
import threading

import pytest

from interview_prep_recall.diagnostics.ring import (
    DEFAULT_CAPACITY,
    DiagnosticContentError,
    DiagnosticRing,
)

TRANSCRIPT = "So tell me about a time you had to handle conflict on your team"
NOTE_BODY = "In Q3 the design review deadlocked and I wrote a trade-off document."


def test_capacity_is_bounded_and_evicts_oldest() -> None:
    ring = DiagnosticRing(capacity=10)
    for i in range(25):
        ring.record("tick", n=i)
    assert len(ring) == 10
    assert [e.fields["n"] for e in ring.snapshot()] == list(range(15, 25))


def test_default_capacity_matches_task_spec() -> None:
    assert DEFAULT_CAPACITY == 2000
    assert DiagnosticRing().capacity == 2000


@pytest.mark.parametrize("text", [TRANSCRIPT, NOTE_BODY])
def test_rejects_transcript_and_note_text(ring: DiagnosticRing, text: str) -> None:
    """The FR36 guarantee: content cannot enter, even by mistake."""
    with pytest.raises(DiagnosticContentError):
        ring.record("match_selected", question=text)
    assert len(ring) == 0


def test_rejects_long_strings(ring: DiagnosticRing) -> None:
    with pytest.raises(DiagnosticContentError):
        ring.record("x", detail="a" * 65)


def test_rejects_non_scalar_values(ring: DiagnosticRing) -> None:
    with pytest.raises(DiagnosticContentError):
        ring.record("x", payload={"text": TRANSCRIPT})
    with pytest.raises(DiagnosticContentError):
        ring.record("x", payload=[TRANSCRIPT])


def test_accepts_structural_fields(ring: DiagnosticRing) -> None:
    ring.record("stale_response_discarded", seq=7, latency_ms=812.5, degraded=True)
    ring.record("stt_state", stream="interviewer", state="DEGRADED", code="ws-1006")
    ring.record("note_selected", note_id="3a71f0c2-8d44-4a1e-9f22-b0c1d2e3f405")
    assert len(ring) == 3


def test_export_is_json_serialisable_and_content_free(ring: DiagnosticRing) -> None:
    ring.record("match_no_candidates", candidates=0)
    ring.record("llm_call", latency_ms=643.0, status=200)
    payload = ring.export()
    blob = json.dumps(payload)
    assert TRANSCRIPT not in blob
    assert NOTE_BODY not in blob
    assert payload["schema_version"] == 1
    assert len(payload["events"]) == 2


def test_export_does_not_write_to_disk(ring: DiagnosticRing) -> None:
    """FR36: never auto-written. The autouse allowlist would catch a stray write."""
    ring.record("tick")
    assert isinstance(ring.export(), dict)


def test_clear_empties_the_ring(ring: DiagnosticRing) -> None:
    ring.record("tick")
    ring.clear()
    assert len(ring) == 0
    assert ring.export()["events"] == []


def test_thread_safe_under_concurrent_writers() -> None:
    """Written from every thread in design §8, so contention is the normal case."""
    ring = DiagnosticRing(capacity=5000)

    def worker(worker_id: int) -> None:
        for i in range(200):
            ring.record("tick", worker=worker_id, n=i)

    threads = [threading.Thread(target=worker, args=(w,)) for w in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(ring) == 1600
