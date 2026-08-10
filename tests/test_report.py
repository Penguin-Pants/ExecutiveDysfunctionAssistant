"""M11 — post-interview report (T11.1, T11.3–T11.9; FR74–FR85, FR87).

No network, no Windows. The cipher and the model client are injected, exactly as the
credential backend and the STT connector are.

**The failure paths get first-class attention here**, because M10's review round found
that all three of its defects lived there — what survives when validation rejects
something. The equivalent questions for this milestone are what a declined confirmation
leaves behind, what a failed generation leaves the egress indicator claiming, and what a
partial delete leaves on disk.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from interview_prep_recall.notes.model import ContextSet, Note, SourceKind, new_id
from interview_prep_recall.report.consent import (
    REPORT_DISCLOSURE_VERSION,
    ReportConsent,
)
from interview_prep_recall.report.evidence import (
    Evidence,
    EvidenceKind,
    Finding,
    RejectionReason,
    ReportSection,
    verify,
)
from interview_prep_recall.report.generator import (
    ReportGenerator,
    ReportUnavailableError,
)
from interview_prep_recall.report.record import SessionRecord
from interview_prep_recall.report.separation import (
    OverlayLeakError,
    assert_no_overlay_dependency,
    imported_modules,
)
from interview_prep_recall.report.store import (
    CipherUnavailableError,
    SessionStore,
    default_cipher,
)
from interview_prep_recall.session.health import Egress
from interview_prep_recall.stt.assembler import Utterance
from interview_prep_recall.stt.fallback import EgressMonitor


def utterance(text: str, *, stream: str = "interviewer", start: float = 0.0) -> Utterance:
    return Utterance(stream_id=stream, text=text, t_start=start, t_end=start + 1.0, context="")


class ReversingCipher:
    """A stand-in for DPAPI that is obviously not encryption, so no test can accidentally
    depend on it being one. Satisfies the same Protocol the real cipher does."""

    def encrypt(self, plaintext: bytes) -> bytes:
        return plaintext[::-1]

    def decrypt(self, ciphertext: bytes) -> bytes:
        return ciphertext[::-1]


class ScriptedClient:
    """Returns a canned response and records what it was sent."""

    def __init__(self, payload: dict | None = None, boom: Exception | None = None) -> None:
        self.payload = payload if payload is not None else {"findings": []}
        self.boom = boom
        self.requests: list[dict] = []

    def create(self, **kwargs):  # type: ignore[no-untyped-def]
        self.requests.append(kwargs)
        if self.boom is not None:
            raise self.boom

        class _Block:
            text = json.dumps(self.payload)

        class _Response:
            content = [_Block()]

        return _Response()


# ---------- T11.1: the record (FR74, FR75, FR76) ----------


def test_the_record_keeps_both_streams_in_order() -> None:
    record = SessionRecord()
    record.add(utterance("Tell me about a migration", stream="interviewer", start=0.0))
    record.add(utterance("I led the Postgres cutover", stream="user", start=2.0))

    assert [u.index for u in record.utterances] == [0, 1]
    assert [u.stream_id for u in record.utterances] == ["interviewer", "user"]
    assert record.utterances[1].is_user


def test_the_record_stops_at_the_utterance_cap() -> None:
    """FR75/FR76. This is the only structure allowed to grow with session length, so the
    bound is the whole reason it is allowed at all."""
    record = SessionRecord(max_utterances=10)
    for i in range(50):
        record.add(utterance(f"line {i}", start=float(i)))

    assert len(record) == 10
    assert record.truncated


def test_the_record_stops_at_the_duration_cap() -> None:
    record = SessionRecord(max_duration_s=60.0)
    record.add(utterance("start", start=0.0))
    record.add(utterance("still fine", start=30.0))
    record.add(utterance("too late", start=120.0))

    assert len(record) == 2
    assert record.truncated


def test_truncation_is_reported_not_silent(app_data) -> None:  # type: ignore[no-untyped-def]
    """A cap that stops recording without saying so leaves the report claiming to cover
    a meeting it only half saw."""
    record = SessionRecord(max_utterances=1)
    record.add(utterance("kept", start=0.0))
    record.add(utterance("dropped", start=1.0))

    events = [e["event"] for e in record.ring.export()["events"]]
    assert "record_truncated" in events


def test_an_unresolvable_index_returns_none() -> None:
    """What makes an invented citation detectable rather than merely wrong."""
    record = SessionRecord()
    record.add(utterance("only one"))
    assert record.get(0) is not None
    assert record.get(1) is None
    assert record.get(-1) is None


def test_clear_drops_every_utterance() -> None:
    record = SessionRecord()
    record.add(utterance("something"))
    record.clear()
    assert len(record) == 0
    assert record.utterances == []


def test_transcript_lines_carry_the_indices() -> None:
    """The model has to cite indices back, so it has to see them. Without this, every
    presence finding it produces is an invention."""
    record = SessionRecord()
    record.add(utterance("a question", stream="interviewer"))
    record.add(utterance("an answer", stream="user"))

    lines = record.transcript_lines()
    assert lines[0].startswith("[0] INTERVIEWER:")
    assert lines[1].startswith("[1] YOU:")


# ---------- T11.5: evidence (FR78, FR78a) ----------


def _record_with(n: int) -> SessionRecord:
    record = SessionRecord()
    for i in range(n):
        record.add(utterance(f"line {i}", start=float(i)))
    return record


def test_a_finding_with_no_evidence_is_rejected() -> None:
    finding = Finding(
        section=ReportSection.CRAFT, text="You rambled.", evidence=Evidence(EvidenceKind.PRESENCE)
    )
    result = verify(
        [finding], _record_with(3), missed_note_ids=frozenset(), known_note_ids=frozenset()
    )
    assert result.accepted == ()
    assert result.rejected[0].reason is RejectionReason.NO_EVIDENCE


def test_an_invented_index_is_rejected() -> None:
    """One fabricated index inside a list of real ones is the shape a plausible-but-wrong
    citation actually takes, so every index must resolve, not just the first."""
    finding = Finding(
        section=ReportSection.CRAFT,
        text="You hedged twice.",
        evidence=Evidence(EvidenceKind.PRESENCE, utterance_indices=(0, 99)),
    )
    result = verify(
        [finding], _record_with(3), missed_note_ids=frozenset(), known_note_ids=frozenset()
    )
    assert result.rejected[0].reason is RejectionReason.UNRESOLVABLE_INDEX


def test_a_resolvable_presence_finding_is_accepted() -> None:
    """Positive control: the rejection tests above would all pass against a verifier that
    rejected everything."""
    finding = Finding(
        section=ReportSection.CRAFT,
        text="Good structure here.",
        evidence=Evidence(EvidenceKind.PRESENCE, utterance_indices=(0, 2)),
    )
    result = verify(
        [finding], _record_with(3), missed_note_ids=frozenset(), known_note_ids=frozenset()
    )
    assert result.accepted == (finding,)
    assert result.rejected == ()


def test_an_absence_finding_contradicted_by_the_tracker_is_rejected() -> None:
    """FR78a. The tracker decided during the interview, from the mic stream, at τ_track.
    A report that says "you never mentioned it" about a point the checklist ticked green
    leaves the user with two authorities and no way to choose."""
    note_id = new_id()
    finding = Finding(
        section=ReportSection.PREP_COVERAGE,
        text="You never mentioned the migration.",
        evidence=Evidence(EvidenceKind.ABSENCE, source_note_id=note_id),
    )
    result = verify(
        [finding],
        _record_with(3),
        missed_note_ids=frozenset(),  # the tracker marked it covered
        known_note_ids=frozenset({note_id}),
    )
    assert result.rejected[0].reason is RejectionReason.CONTRADICTED_BY_TRACKER


def test_an_absence_finding_agreeing_with_the_tracker_is_accepted() -> None:
    note_id = new_id()
    finding = Finding(
        section=ReportSection.PREP_COVERAGE,
        text="You never mentioned the migration.",
        evidence=Evidence(EvidenceKind.ABSENCE, source_note_id=note_id),
    )
    result = verify(
        [finding],
        _record_with(3),
        missed_note_ids=frozenset({note_id}),
        known_note_ids=frozenset({note_id}),
    )
    assert result.accepted == (finding,)


def test_an_absence_finding_naming_an_unknown_chunk_is_rejected() -> None:
    """Otherwise a hallucinated note id reads as an uncovered point."""
    finding = Finding(
        section=ReportSection.PREP_COVERAGE,
        text="You never mentioned X.",
        evidence=Evidence(EvidenceKind.ABSENCE, source_note_id=new_id()),
    )
    result = verify(
        [finding], _record_with(3), missed_note_ids=frozenset(), known_note_ids=frozenset()
    )
    assert result.rejected[0].reason is RejectionReason.UNKNOWN_SOURCE


def test_rejections_are_counted_not_silently_dropped() -> None:
    """A report that quietly discarded a third of the model's output would read as
    complete while being nothing of the sort."""
    good = Finding(
        section=ReportSection.CRAFT,
        text="ok",
        evidence=Evidence(EvidenceKind.PRESENCE, utterance_indices=(0,)),
    )
    bad = Finding(section=ReportSection.CRAFT, text="no", evidence=Evidence(EvidenceKind.PRESENCE))
    result = verify(
        [good, bad], _record_with(2), missed_note_ids=frozenset(), known_note_ids=frozenset()
    )
    assert result.accepted == (good,)
    assert result.rejection_count == 1


# ---------- T11.6: structural separation (FR79) ----------


def test_the_report_package_cannot_reach_the_overlay() -> None:
    """FR79, checked statically. A runtime check would miss an import that only happens
    on the error path — which is exactly where a desperate "just render the summary"
    would be added."""
    assert_no_overlay_dependency(Path("interview_prep_recall/report"))


def test_the_separation_check_actually_catches_a_leak(tmp_path: Path) -> None:
    """A guard that never fires is worth nothing. This project has enough history of
    tests passing while the property is broken to justify checking the checker."""
    (tmp_path / "leaky.py").write_text("from interview_prep_recall.ui.overlay import render\n")
    with pytest.raises(OverlayLeakError):
        assert_no_overlay_dependency(tmp_path)


def test_the_scanner_sees_both_import_forms(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("import interview_prep_recall.ui.overlay\n")
    (tmp_path / "b.py").write_text("from interview_prep_recall.notes.model import Note\n")
    found = imported_modules(tmp_path)
    assert "interview_prep_recall.ui.overlay" in found
    assert "interview_prep_recall.notes.model" in found


# ---------- T11.4/T11.7: generation (FR77, FR80, FR81, FR81a) ----------


def _consent(tmp: Path) -> ReportConsent:
    consent = ReportConsent(tmp / "report_consent.json")
    consent.acknowledge()
    return consent


def _context_set(kinds: list[SourceKind]) -> ContextSet:
    return ContextSet(name="Acme", notes=[Note(headline=f"{k.value} chunk", kind=k) for k in kinds])


def test_local_only_refuses_and_sends_nothing(app_data) -> None:  # type: ignore[no-untyped-def]
    """FR80: stated as unavailable, not silently producing nothing."""
    client = ScriptedClient()
    generator = ReportGenerator(consent=_consent(app_data), client=client, local_only=True)
    record = _record_with(2)

    with pytest.raises(ReportUnavailableError, match="local-only"):
        generator.generate(
            record,
            _context_set([SourceKind.PREP]),
            missed_note_ids=frozenset(),
            confirm=lambda _: True,
        )
    assert client.requests == []


def test_declining_the_confirmation_sends_nothing(app_data) -> None:  # type: ignore[no-untyped-def]
    """FR81. The failure path that matters: a decline must leave no request behind."""
    client = ScriptedClient()
    generator = ReportGenerator(consent=_consent(app_data), client=client)

    with pytest.raises(ReportUnavailableError, match="declined"):
        generator.generate(
            _record_with(2),
            _context_set([SourceKind.PREP]),
            missed_note_ids=frozenset(),
            confirm=lambda _size: False,
        )
    assert client.requests == []


def test_the_confirmation_is_asked_every_run_with_the_size(app_data) -> None:  # type: ignore[no-untyped-def]
    """Not a remembered preference: what is being confirmed is that *this* interview,
    including the other person's words, leaves the device now."""
    client = ScriptedClient()
    generator = ReportGenerator(consent=_consent(app_data), client=client)
    sizes: list[int] = []

    def confirm(size: int) -> bool:
        sizes.append(size)
        return True

    for _ in range(3):
        generator.generate(
            _record_with(2),
            _context_set([SourceKind.PREP]),
            missed_note_ids=frozenset(),
            confirm=confirm,
        )
    assert len(sizes) == 3
    assert all(size > 0 for size in sizes)


def test_the_egress_indicator_is_lit_during_the_call_and_dark_after(app_data) -> None:  # type: ignore[no-untyped-def]
    """FR81a. The largest upload the product ever makes."""
    seen: list[Egress] = []
    egress = EgressMonitor()

    class WatchingClient(ScriptedClient):
        def create(self, **kwargs):  # type: ignore[no-untyped-def]
            seen.append(egress.egress)
            return super().create(**kwargs)

    generator = ReportGenerator(consent=_consent(app_data), client=WatchingClient(), egress=egress)
    generator.generate(
        _record_with(2),
        _context_set([SourceKind.PREP]),
        missed_note_ids=frozenset(),
        confirm=lambda _: True,
    )

    assert seen == [Egress.LLM], "the indicator was not lit while the transcript was in flight"
    assert egress.egress is Egress.NONE


def test_a_failed_call_does_not_leave_the_indicator_lit(app_data) -> None:  # type: ignore[no-untyped-def]
    """The other failure path. An indicator stuck claiming an upload that already failed
    is a false privacy statement in the direction that matters least — but a user who
    stops trusting it stops reading it."""
    egress = EgressMonitor()
    generator = ReportGenerator(
        consent=_consent(app_data),
        client=ScriptedClient(boom=RuntimeError("api down")),
        egress=egress,
    )

    with pytest.raises(RuntimeError):
        generator.generate(
            _record_with(2),
            _context_set([SourceKind.PREP]),
            missed_note_ids=frozenset(),
            confirm=lambda _: True,
        )
    assert egress.egress is Egress.NONE


def test_an_empty_record_refuses_before_asking_to_send(app_data) -> None:  # type: ignore[no-untyped-def]
    client = ScriptedClient()
    generator = ReportGenerator(consent=_consent(app_data), client=client)
    asked: list[int] = []

    with pytest.raises(ReportUnavailableError, match="Nothing was recorded"):
        generator.generate(
            SessionRecord(),
            _context_set([SourceKind.PREP]),
            missed_note_ids=frozenset(),
            confirm=lambda size: asked.append(size) or True,  # type: ignore[func-returns-value]
        )
    assert asked == [], "the user was asked to confirm sending an empty transcript"


@pytest.mark.parametrize(
    ("missing", "section"),
    [
        (SourceKind.PREP, ReportSection.PREP_COVERAGE),
        (SourceKind.ROLE, ReportSection.ROLE_FIT),
        (SourceKind.RESUME, ReportSection.RESUME_USE),
    ],
)
def test_a_section_whose_source_is_absent_says_so(missing, section, app_data) -> None:  # type: ignore[no-untyped-def]
    """FR77. Silently omitting it would let the report read as a complete review while a
    whole dimension was never assessed, and the user cannot notice a section that was
    never there."""
    kinds = [k for k in (SourceKind.PREP, SourceKind.ROLE, SourceKind.RESUME) if k is not missing]
    generator = ReportGenerator(consent=_consent(app_data), client=ScriptedClient())

    report = generator.generate(
        _record_with(2), _context_set(kinds), missed_note_ids=frozenset(), confirm=lambda _: True
    )

    assert section in report.sections
    assert "Not assessed" in report.sections[section]
    assert missing in report.absent_sources


def test_craft_is_assessed_with_no_context_loaded(app_data) -> None:  # type: ignore[no-untyped-def]
    """Interview craft is judged from the transcript alone, so it survives a session with
    nothing imported — the positive control for the parametrized test above."""
    generator = ReportGenerator(consent=_consent(app_data), client=ScriptedClient())
    report = generator.generate(
        _record_with(2),
        ContextSet(name="empty"),
        missed_note_ids=frozenset(),
        confirm=lambda _: True,
    )
    assert "Not assessed" not in report.sections[ReportSection.CRAFT]


def test_truncation_reaches_the_report_text(app_data) -> None:  # type: ignore[no-untyped-def]
    """FR75 says stated in the report — not only in a diagnostic nobody reads."""
    record = SessionRecord(max_utterances=1)
    record.add(utterance("kept", start=0.0))
    record.add(utterance("dropped", start=1.0))

    generator = ReportGenerator(consent=_consent(app_data), client=ScriptedClient())
    report = generator.generate(
        record, _context_set([SourceKind.PREP]), missed_note_ids=frozenset(), confirm=lambda _: True
    )

    assert report.truncated
    assert "recording cap" in report.sections[ReportSection.WHAT_TO_CHANGE]


def test_the_prompt_carries_the_trackers_uncovered_list(app_data) -> None:  # type: ignore[no-untyped-def]
    """FR78a. A model asked to work coverage out from the transcript produces a second
    opinion the verifier then rejects wholesale — so it is told the answer instead."""
    note_id = new_id()
    client = ScriptedClient()
    generator = ReportGenerator(consent=_consent(app_data), client=client)

    generator.generate(
        _record_with(2),
        _context_set([SourceKind.PREP]),
        missed_note_ids=frozenset({note_id}),
        confirm=lambda _: True,
    )

    prompt = client.requests[0]["messages"][0]["content"]
    assert note_id in prompt
    assert "NOT COVERED" in prompt


def test_a_malformed_response_degrades_to_no_findings(app_data) -> None:  # type: ignore[no-untyped-def]
    """A garbled reply must not raise mid-report."""

    class GarbledClient(ScriptedClient):
        def create(self, **kwargs):  # type: ignore[no-untyped-def]
            self.requests.append(kwargs)

            class _Block:
                text = "not json at all"

            class _Response:
                content = [_Block()]

            return _Response()

    generator = ReportGenerator(consent=_consent(app_data), client=GarbledClient())
    report = generator.generate(
        _record_with(2),
        _context_set([SourceKind.PREP]),
        missed_note_ids=frozenset(),
        confirm=lambda _: True,
    )
    assert report.findings.accepted == ()


def test_findings_survive_the_round_trip_into_the_report(app_data) -> None:  # type: ignore[no-untyped-def]
    payload = {
        "findings": [
            {"section": "craft", "text": "You gave a concrete number.", "indices": [0]},
        ]
    }
    generator = ReportGenerator(consent=_consent(app_data), client=ScriptedClient(payload))
    report = generator.generate(
        _record_with(2),
        _context_set([SourceKind.PREP]),
        missed_note_ids=frozenset(),
        confirm=lambda _: True,
    )

    assert len(report.findings.accepted) == 1
    assert "concrete number" in report.sections[ReportSection.CRAFT]
    assert report.to_dict()["findings"][0]["evidence"]["indices"] == [0]


# ---------- T11.2/T11.3: storage, listing, deletion, retention (FR82–FR84) ----------


def _store(root: Path, retention_days: int | None = 30) -> SessionStore:
    return SessionStore(root, cipher=ReversingCipher(), retention_days=retention_days)


def test_a_transcript_round_trips_through_the_store(app_data) -> None:  # type: ignore[no-untyped-def]
    store = _store(app_data)
    record = SessionRecord()
    record.add(utterance("a question", stream="interviewer"))
    record.add(utterance("an answer", stream="user", start=2.0))

    sid = store.save(record, role="Staff Engineer")
    loaded = store.load(sid)

    assert loaded.role == "Staff Engineer"
    assert [u.text for u in loaded.utterances] == ["a question", "an answer"]
    assert [u.stream_id for u in loaded.utterances] == ["interviewer", "user"]


def test_nothing_readable_is_written_in_plaintext(app_data) -> None:  # type: ignore[no-untyped-def]
    """FR82/FR16. The whole justification for D-U8's trade is that what lands on disk is
    not readable by whoever picks the machine up."""
    store = _store(app_data)
    record = SessionRecord()
    record.add(utterance("the interviewer said something private"))
    sid = store.save(record, role="Role")

    raw = store.transcript_path(sid).read_bytes()
    assert b"the interviewer said something private" not in raw


def test_deleting_a_session_removes_transcript_and_report_together(app_data) -> None:  # type: ignore[no-untyped-def]
    """FR83. Partial deletion is the failure that matters: a user told their words are
    gone, with a model's characterisation of the interviewer still on disk."""
    store = _store(app_data)
    record = _record_with(2)
    sid = store.save(record, role="Role")
    store.attach_report(sid, {"sections": {}})
    keep = store.save(_record_with(1), role="Other")

    assert store.delete(sid)

    assert not store.transcript_path(sid).exists()
    assert not store.report_path(sid).exists()
    assert store.transcript_path(keep).exists(), "an unrelated session was destroyed"


def test_delete_all_clears_every_session(app_data) -> None:  # type: ignore[no-untyped-def]
    """FR87: the only route to destroying stored history, and the one a user reaching for
    the panic control actually needs now that panic destroys nothing (D-U11)."""
    store = _store(app_data)
    for _ in range(3):
        store.attach_report(store.save(_record_with(1), role="Role"), {"sections": {}})

    assert store.delete_all() == 3
    assert store.list_sessions() == []
    assert list(store.sessions_dir.glob("*.transcript")) == []
    assert list(store.sessions_dir.glob("*.report")) == []


def test_the_session_list_reports_size_and_report_presence(app_data) -> None:  # type: ignore[no-untyped-def]
    store = _store(app_data)
    bare = store.save(_record_with(1), role="Bare")
    withreport = store.save(_record_with(1), role="Reported")
    store.attach_report(withreport, {"sections": {}})

    by_id = {s.id: s for s in store.list_sessions()}
    assert by_id[bare].has_report is False
    assert by_id[withreport].has_report is True
    assert by_id[bare].bytes_stored > 0
    assert by_id[withreport].role == "Reported"


def test_one_unreadable_session_does_not_hide_the_others(app_data) -> None:  # type: ignore[no-untyped-def]
    store = _store(app_data)
    good = store.save(_record_with(1), role="Good")
    store.transcript_path(new_id()).write_bytes(b"\x00 not decryptable")

    assert good in [s.id for s in store.list_sessions()]


def test_sessions_past_the_retention_window_are_swept(app_data) -> None:  # type: ignore[no-untyped-def]
    """FR84."""
    store = _store(app_data, retention_days=30)
    old = store.save(_record_with(1), role="Old")
    fresh = store.save(_record_with(1), role="Fresh")

    # Age the old one by rewriting its stored start date.
    data = store._read_encrypted(store.transcript_path(old))
    data["stored_at"] = (
        (datetime.now(UTC) - timedelta(days=60))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    store._write_encrypted(store.transcript_path(old), data)

    assert store.sweep_expired() == [old]
    assert [s.id for s in store.list_sessions()] == [fresh]


def test_retention_never_means_never(app_data) -> None:  # type: ignore[no-untyped-def]
    """A sweep that treated None as zero would delete everything on the first launch
    after the user chose to keep it all."""
    store = _store(app_data, retention_days=None)
    sid = store.save(_record_with(1), role="Kept")

    data = store._read_encrypted(store.transcript_path(sid))
    data["stored_at"] = "2000-01-01T00:00:00Z"
    store._write_encrypted(store.transcript_path(sid), data)

    assert store.sweep_expired() == []
    assert [s.id for s in store.list_sessions()] == [sid]


def test_a_session_id_that_is_not_a_uuid_is_refused(app_data) -> None:  # type: ignore[no-untyped-def]
    """Same path-traversal boundary as the notes store: an id reaches a filename."""
    from interview_prep_recall.notes.model import InvalidIdError

    store = _store(app_data)
    with pytest.raises(InvalidIdError):
        store.transcript_path("../../escaped")


@pytest.mark.skipif(
    __import__("os").name == "nt", reason="DPAPI is available on Windows, so this cannot raise"
)
def test_there_is_no_cipher_fallback_off_windows() -> None:
    """FR82. Storing an interview transcript under weaker protection than promised would
    be a false privacy statement about another person's words, so this raises rather than
    degrading."""
    with pytest.raises(CipherUnavailableError):
        default_cipher()


# ---------- T11.8: consent re-acknowledgement (FR85) ----------


def test_the_report_disclosure_blocks_until_acknowledged(app_data) -> None:  # type: ignore[no-untyped-def]
    consent = ReportConsent(app_data / "report_consent.json")
    assert consent.required

    consent.acknowledge()
    assert not consent.required
    assert consent.acknowledged_version() == REPORT_DISCLOSURE_VERSION


def test_an_older_acknowledgement_does_not_carry_over(app_data) -> None:  # type: ignore[no-untyped-def]
    """FR85. The first acknowledgement was to a materially weaker statement, and a
    version bump means the text changed. Treating consent to "audio is intercepted in
    memory" as consent to "the other person's words are stored and analysed" is this
    project's recurring defect applied to a person instead of a buffer."""
    path = app_data / "report_consent.json"
    path.write_text(json.dumps({"report_disclosure_version": REPORT_DISCLOSURE_VERSION - 1}))

    assert ReportConsent(path).required


def test_unreadable_consent_is_absent_consent(app_data) -> None:  # type: ignore[no-untyped-def]
    """Failing open here would mean inferring agreement from a corrupt file."""
    path = app_data / "report_consent.json"
    path.write_text("{ not json")
    assert ReportConsent(path).required


def test_generation_refuses_until_the_disclosure_is_acknowledged(app_data) -> None:  # type: ignore[no-untyped-def]
    """FR85 enforced where it can actually be enforced.

    Generation is the moment the interviewer's words leave the device. Checking consent
    only in the UI would leave the guarantee dependent on wiring that does not exist
    yet — the shape of D-23, where the local-only switch lit an indicator while the
    pipeline kept calling the API.
    """
    client = ScriptedClient()
    unacknowledged = ReportConsent(app_data / "report_consent.json")
    generator = ReportGenerator(consent=unacknowledged, client=client)

    with pytest.raises(ReportUnavailableError, match="disclosure has not been acknowledged"):
        generator.generate(
            _record_with(2),
            _context_set([SourceKind.PREP]),
            missed_note_ids=frozenset(),
            confirm=lambda _: True,
        )
    assert client.requests == [], "the transcript was sent without an acknowledged disclosure"

    unacknowledged.acknowledge()
    generator.generate(
        _record_with(2),
        _context_set([SourceKind.PREP]),
        missed_note_ids=frozenset(),
        confirm=lambda _: True,
    )
    assert len(client.requests) == 1


def test_delete_all_reindexes_once_not_per_session(app_data) -> None:  # type: ignore[no-untyped-def]
    """Rebuilding the index decrypts every remaining transcript, so a per-session
    reindex makes delete-all O(n²) decryptions — on the one operation a user runs when
    they want their data gone quickly."""
    decrypts = 0

    class CountingCipher(ReversingCipher):
        def decrypt(self, ciphertext: bytes) -> bytes:
            nonlocal decrypts
            decrypts += 1
            return super().decrypt(ciphertext)

    store = SessionStore(app_data, cipher=CountingCipher(), retention_days=None)
    for _ in range(8):
        store.save(_record_with(1), role="Role")

    decrypts = 0
    store.delete_all()

    assert store.list_sessions() == []
    assert decrypts <= 8, f"delete-all decrypted {decrypts} times for 8 sessions"
