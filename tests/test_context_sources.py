"""M10 — typed context sources (T10.1–T10.6, FR66–FR73c).

The migration tests matter most. Everything else here is a new feature failing loudly
if it is wrong; FR73a–c are the path where getting it wrong destroys prep notes the user
cannot reproduce, silently, on upgrade.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from interview_prep_recall.matching.prefilter import (
    KIND_TAU_OFFSET,
    PER_KIND_CAP,
    TAU_FLOOR_MAX,
    TAU_FLOOR_MIN,
    Prefilter,
)
from interview_prep_recall.matching.selector import build_user_message
from interview_prep_recall.notes.importer import add_source, import_text
from interview_prep_recall.notes.index import EmbeddingIndex
from interview_prep_recall.notes.model import (
    TRACKABLE_KINDS,
    ContextSet,
    Note,
    SourceKind,
    new_id,
)
from interview_prep_recall.notes.store import NoteSetCorruptError, NotesStore

# ---------- T10.1: kind on the chunk, immutable (FR66, FR67) ----------


def test_every_kind_round_trips_through_the_store(app_data) -> None:  # type: ignore[no-untyped-def]
    store = NotesStore(app_data)
    cs = ContextSet(
        name="Acme",
        notes=[Note(headline=f"{k.value} chunk", kind=k) for k in SourceKind],
    )
    store.save(cs)
    loaded = store.load(cs.id)
    assert {n.kind for n in loaded.notes} == set(SourceKind)
    assert [n.id for n in loaded.notes] == [n.id for n in cs.notes]


def test_kind_is_immutable_after_creation() -> None:
    """FR67. A chunk's kind drives its threshold, its enum quota and its tracker
    eligibility; mutating it moves the chunk between all three while its embedding —
    keyed on the note id — stays exactly where it was."""
    note = Note(headline="q", kind=SourceKind.ROLE)
    with pytest.raises(ValueError, match="immutable"):
        note.kind = SourceKind.PREP
    assert note.kind is SourceKind.ROLE


def test_kind_defaults_to_prep() -> None:
    """So code predating kinds, and every migrated v1 note, keeps its behaviour rather
    than silently changing category."""
    assert Note(headline="q").kind is SourceKind.PREP


# ---------- T10.2: per-kind lifecycle (FR66, FR73) ----------


def test_removing_one_kind_leaves_the_others_untouched() -> None:
    cs = ContextSet(name="Acme", notes=[Note(headline=f"{k.value}", kind=k) for k in SourceKind])
    survivors = {n.id: n.headline for n in cs.notes if n.kind is not SourceKind.ROLE}

    assert cs.remove_kind(SourceKind.ROLE) == 1
    assert {n.id: n.headline for n in cs.notes} == survivors
    assert cs.by_kind(SourceKind.ROLE) == []


def test_any_subset_of_kinds_is_a_complete_set() -> None:
    """FR73. Absent kinds degrade matching; they never block a session."""
    cs = ContextSet(name="Acme", notes=[Note(headline="only prep", kind=SourceKind.PREP)])
    cs.verify()
    assert cs.kinds_present() == {SourceKind.PREP}


def test_reimporting_a_source_replaces_rather_than_appends() -> None:
    """Appending would leave the superseded job description competing for the same enum
    slots as the new one, with no way for the user to tell which won."""
    cs = ContextSet(name="Acme", notes=[Note(headline="my prep", kind=SourceKind.PREP)])
    add_source(cs, import_text("Old role duties.").proposals, SourceKind.ROLE)
    old_ids = {n.id for n in cs.by_kind(SourceKind.ROLE)}
    add_source(cs, import_text("New role duties.").proposals, SourceKind.ROLE)

    roles = [n.headline for n in cs.by_kind(SourceKind.ROLE)]
    assert roles == ["New role duties."]
    assert not old_ids & {n.id for n in cs.notes}, "superseded chunks lingered in the set"
    assert [n.headline for n in cs.by_kind(SourceKind.PREP)] == ["my prep"]


# ---------- T10.6: only prep and resume are trackable (FR70) ----------


@pytest.mark.parametrize("kind", [k for k in SourceKind if k not in TRACKABLE_KINDS])
def test_untrackable_kinds_cannot_be_talking_points(kind) -> None:  # type: ignore[no-untyped-def]
    """FR70. A job-description requirement is not something you "cover" by speaking, so
    letting it onto the checklist would tick off points the user never made — the FR56
    failure arriving through the data model instead of through the microphone."""
    with pytest.raises(ValueError, match="FR70"):
        Note(headline="q", kind=kind, track_progress=True)

    note = Note(headline="q", kind=kind)
    with pytest.raises(ValueError, match="FR70"):
        note.track_progress = True


@pytest.mark.parametrize("kind", sorted(TRACKABLE_KINDS, key=lambda k: k.value))
def test_prep_and_resume_can_be_tracked(kind) -> None:  # type: ignore[no-untyped-def]
    """Positive control. Without it the test above passes against a model that forbids
    tracking on everything."""
    note = Note(headline="q", kind=kind, track_progress=True)
    assert ContextSet(name="s", notes=[note]).tracked() == [note]


# ---------- T10.4: per-kind caps and thresholds (FR68, FR69) ----------


class ScriptedEmbedder:
    """Maps each text to a unit vector whose cosine against the query is a scripted
    value, so per-kind thresholds and caps are testable at exact similarities rather
    than at whatever a real model happens to produce."""

    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores
        self.model_id = "scripted/one"
        self.model_version = "1.0"

    def encode(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), 2), dtype=np.float32)
        for i, text in enumerate(texts):
            score = self.scores.get(text, 0.0)
            # Unit vector at the angle whose cosine against [1, 0] is `score`.
            out[i] = [score, float(np.sqrt(max(0.0, 1.0 - score * score)))]
        return out


def _prefilter_over(notes: list[Note], scores: dict[str, float], root) -> Prefilter:  # type: ignore[no-untyped-def]
    cs = ContextSet(name="Acme", notes=notes)
    embedder = ScriptedEmbedder({**scores, "QUERY": 1.0})
    index = EmbeddingIndex(root, embedder)
    index.build(cs, persist=False)
    return Prefilter(index, cs, embedder)


def test_no_kind_supplies_more_than_the_cap(app_data) -> None:  # type: ignore[no-untyped-def]
    """FR68 with the corpus skewed the way a real one is: the job description is the
    biggest document most users import, and on chunk count alone it would fill the enum
    and crowd out the prep notes the product exists to surface."""
    notes = [Note(headline=f"role {i}", kind=SourceKind.ROLE) for i in range(200)]
    notes += [Note(headline=f"prep {i}", kind=SourceKind.PREP) for i in range(3)]
    scores = {f"role {i}": 0.95 for i in range(200)}
    scores.update({f"prep {i}": 0.90 for i in range(3)})

    candidates = _prefilter_over(notes, scores, app_data).candidates("QUERY")

    by_kind: dict[SourceKind, int] = {}
    for candidate in candidates:
        by_kind[candidate.kind] = by_kind.get(candidate.kind, 0) + 1
    assert all(count <= PER_KIND_CAP for count in by_kind.values()), by_kind
    assert by_kind.get(SourceKind.PREP, 0) >= 1, (
        "prep notes were crowded out by role chunks — the failure FR68 exists to prevent"
    )
    assert len(candidates) <= 5  # FR48


def test_the_cap_does_not_truncate_before_it_applies(app_data) -> None:  # type: ignore[no-untyped-def]
    """A top-K slice taken *before* the cap would drop a second kind's candidate in
    favour of a third same-kind chunk that the cap then discards, leaving fewer
    candidates than the enum has room for."""
    notes = [Note(headline=f"role {i}", kind=SourceKind.ROLE) for i in range(5)]
    notes += [Note(headline="prep A", kind=SourceKind.PREP)]
    scores = {f"role {i}": 0.9 - i * 0.01 for i in range(5)}
    scores["prep A"] = 0.5

    candidates = _prefilter_over(notes, scores, app_data).candidates("QUERY")
    assert SourceKind.PREP in {c.kind for c in candidates}


def test_per_kind_thresholds_track_the_single_control(app_data) -> None:  # type: ignore[no-untyped-def]
    """FR69/FR52. Absolute per-kind thresholds would stop following the control and
    silently ignore the user turning sensitivity up or down — the mistake design §5
    already had to correct once for tau_degraded."""
    pf = _prefilter_over([Note(headline="a")], {"a": 0.9}, app_data)

    pf.tau_floor = 0.30
    low = {k: pf.tau_for(k) for k in SourceKind}
    pf.tau_floor = 0.50
    high = {k: pf.tau_for(k) for k in SourceKind}

    assert all(high[k] > low[k] for k in SourceKind), "a kind stopped tracking the control"
    assert all(pytest.approx(high[k] - low[k]) == 0.20 for k in SourceKind), (
        "relative offsets were not preserved across a control change"
    )


@pytest.mark.parametrize("floor", [TAU_FLOOR_MIN, TAU_FLOOR_MAX])
def test_offsets_cannot_push_a_kind_outside_the_control_range(floor, app_data) -> None:  # type: ignore[no-untyped-def]
    pf = _prefilter_over([Note(headline="a")], {"a": 0.9}, app_data)
    pf.tau_floor = floor
    for kind in SourceKind:
        assert TAU_FLOOR_MIN <= pf.tau_for(kind) <= TAU_FLOOR_MAX


def test_reference_kinds_sit_below_the_users_own_words() -> None:
    """The direction of the offsets is the design claim, and a sign flip would pass
    every other test here while quietly burying the user's prep under HR prose."""
    assert KIND_TAU_OFFSET[SourceKind.PREP] == 0.0
    assert KIND_TAU_OFFSET[SourceKind.RESUME] == 0.0
    for kind in (SourceKind.ROLE, SourceKind.COMPANY, SourceKind.INTERVIEWER):
        assert KIND_TAU_OFFSET[kind] < 0.0


# ---------- T10.5: kind labels in the stage-2 prompt (FR71) ----------


def test_every_candidate_is_labelled_with_its_kind(app_data) -> None:  # type: ignore[no-untyped-def]
    notes = [Note(headline=f"{k.value} chunk", kind=k) for k in SourceKind]
    scores = {f"{k.value} chunk": 0.9 for k in SourceKind}
    candidates = _prefilter_over(notes, scores, app_data).candidates("QUERY")
    assert candidates

    from interview_prep_recall.stt.assembler import Utterance

    message = build_user_message(
        Utterance(
            stream_id="interviewer",
            text="q?",
            t_start=0.0,
            t_end=1.0,
            context="",
        ),
        candidates,
    )
    for candidate in candidates:
        assert f"[{candidate.kind.value}]" in message


def test_the_body_still_never_reaches_the_prompt(app_data) -> None:  # type: ignore[no-untyped-def]
    """Adding a field to the candidate line is exactly when the body sneaks in."""
    notes = [Note(headline="h", body="SECRET PREPARED ANSWER", kind=SourceKind.PREP)]
    candidates = _prefilter_over(notes, {"h": 0.9}, app_data).candidates("QUERY")

    from interview_prep_recall.stt.assembler import Utterance

    message = build_user_message(
        Utterance(
            stream_id="interviewer",
            text="q?",
            t_start=0.0,
            t_end=1.0,
            context="",
        ),
        candidates,
    )
    assert "SECRET PREPARED ANSWER" not in message


# ---------- T10.2a: schema v1 -> v2 migration (FR73a, FR73b, FR73c) ----------


def _v1_payload(noteset_id: str, note_id: str) -> dict:
    """A real schema-v1 file: no `kind` anywhere."""
    return {
        "schema_version": 1,
        "id": noteset_id,
        "name": "My prep",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "notes": [
            {
                "id": note_id,
                "headline": "Tell me about a migration you led",
                "bullets": ["Tell me about a migration you led"],
                "body": "Cut deploy time by 60%.",
                "tags": ["systems"],
                "order_index": 0,
                "track_progress": True,
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ],
    }


def test_v1_notes_load_and_become_prep(app_data) -> None:  # type: ignore[no-untyped-def]
    """FR73a. Without the migration a v1 file has no `kind`, loads as corrupt, and
    recovery walks backups that are all equally v1 — the user opens the app after an
    upgrade to find their prep gone."""
    store = NotesStore(app_data)
    noteset_id, note_id = new_id(), new_id()
    store.path_for(noteset_id).write_text(json.dumps(_v1_payload(noteset_id, note_id)))

    loaded = store.load(noteset_id)

    note = loaded.notes[0]
    assert note.kind is SourceKind.PREP
    assert note.id == note_id, "ids must survive — the embedding cache is keyed on them"
    assert note.headline == "Tell me about a migration you led"
    assert note.body == "Cut deploy time by 60%."
    assert note.bullets == ["Tell me about a migration you led"]
    assert note.tags == ["systems"]
    assert note.track_progress is True


def test_migrated_notes_are_still_trackable(app_data) -> None:  # type: ignore[no-untyped-def]
    """The reason PREP is the right target. Mapping v1 notes to any other kind would
    trip FR70 and silently switch off the progress tracker for every existing user."""
    store = NotesStore(app_data)
    noteset_id, note_id = new_id(), new_id()
    store.path_for(noteset_id).write_text(json.dumps(_v1_payload(noteset_id, note_id)))

    assert [n.id for n in store.load(noteset_id).tracked()] == [note_id]


def test_a_v1_file_with_no_notes_key_is_still_corruption(app_data) -> None:  # type: ignore[no-untyped-def]
    """The migration must not paper over damage. Substituting an empty list would make
    a damaged file migrate "successfully" into an empty note set — the exact failure
    FR44 exists to prevent, one layer earlier."""
    store = NotesStore(app_data)
    noteset_id = new_id()
    payload = _v1_payload(noteset_id, new_id())
    del payload["notes"]
    store.path_for(noteset_id).write_text(json.dumps(payload))

    with pytest.raises(NoteSetCorruptError):
        store.load(noteset_id)


def test_migration_does_not_clobber_an_existing_kind(app_data) -> None:  # type: ignore[no-untyped-def]
    """A v1 file should not carry a kind, but a hand-edited or half-migrated one might,
    and overwriting it would be the lossy read SchemaTooNewError exists to refuse."""
    store = NotesStore(app_data)
    noteset_id = new_id()
    payload = _v1_payload(noteset_id, new_id())
    payload["notes"][0]["kind"] = "resume"
    store.path_for(noteset_id).write_text(json.dumps(payload))

    assert store.load(noteset_id).notes[0].kind is SourceKind.RESUME


def test_saving_a_migrated_set_writes_v2(app_data) -> None:  # type: ignore[no-untyped-def]
    """FR73b: migration reaches disk only through the existing atomic write path, so a
    crash mid-migration leaves the v1 file intact and loadable by the old build."""
    store = NotesStore(app_data)
    noteset_id, note_id = new_id(), new_id()
    store.path_for(noteset_id).write_text(json.dumps(_v1_payload(noteset_id, note_id)))

    loaded = store.load(noteset_id)
    store.save(loaded)

    on_disk = json.loads(store.path_for(noteset_id).read_text())
    assert on_disk["schema_version"] == 2
    assert on_disk["notes"][0]["kind"] == "prep"
    assert on_disk["notes"][0]["id"] == note_id


def test_the_v1_file_survives_as_a_backup(app_data) -> None:  # type: ignore[no-untyped-def]
    """FR73c. The pre-migration file is the only copy of the old format, and it is what
    a downgrade or a botched migration falls back to."""
    store = NotesStore(app_data)
    noteset_id, note_id = new_id(), new_id()
    store.path_for(noteset_id).write_text(json.dumps(_v1_payload(noteset_id, note_id)))

    store.save(store.load(noteset_id))

    backups = store.list_backups(noteset_id)
    assert backups, "the v1 file was replaced with no backup generation"
    original = json.loads(backups[0].path.read_text())
    assert original["schema_version"] == 1


# ---------- review-round fixes ----------


def test_a_stray_track_flag_on_disk_does_not_make_the_set_unloadable(app_data) -> None:  # type: ignore[no-untyped-def]
    """FR70 is coerced on load, not enforced by rejection.

    Constructing such a note in code raises, correctly — that is a bug at the call site.
    But `ContextSet.from_dict` turns a ValueError into `NoteSetCorruptError`, so on the
    load path one stray flag on one chunk would make the user's *entire* note set
    unloadable and send them to backup recovery. Dropping the flag satisfies FR70
    exactly; refusing the file satisfies it at the cost of everything else in the file.
    """
    store = NotesStore(app_data)
    noteset_id, note_id = new_id(), new_id()
    payload = _v1_payload(noteset_id, note_id)
    payload["schema_version"] = 2
    payload["notes"][0]["kind"] = "role"
    payload["notes"][0]["track_progress"] = True
    store.path_for(noteset_id).write_text(json.dumps(payload))

    loaded = store.load(noteset_id)

    assert loaded.notes[0].kind is SourceKind.ROLE
    assert loaded.notes[0].track_progress is False, "FR70 was not enforced on load"
    assert loaded.tracked() == []
    assert loaded.notes[0].headline == "Tell me about a migration you led", (
        "the rest of the note must survive the coercion"
    )


def test_a_legitimate_track_flag_still_loads(app_data) -> None:  # type: ignore[no-untyped-def]
    """Positive control: the coercion must not simply clear every flag on load."""
    store = NotesStore(app_data)
    noteset_id, note_id = new_id(), new_id()
    payload = _v1_payload(noteset_id, note_id)
    payload["schema_version"] = 2
    payload["notes"][0]["kind"] = "prep"
    store.path_for(noteset_id).write_text(json.dumps(payload))

    assert [n.id for n in store.load(noteset_id).tracked()] == [note_id]


def test_the_prefilter_stops_once_no_kind_can_clear(app_data) -> None:  # type: ignore[no-untyped-def]
    """The loop walks the whole corpus rather than a top-K slice, so it needs both an
    early exit and an id lookup that is not a linear scan — otherwise it is O(n^2)
    against the 50 ms budget for 200 notes."""
    import time

    notes = [Note(headline=f"n {i}", kind=SourceKind.PREP) for i in range(200)]
    scores = {f"n {i}": 0.05 for i in range(200)}  # nothing clears any floor
    pf = _prefilter_over(notes, scores, app_data)

    began = time.perf_counter()
    assert pf.candidates("QUERY") == []
    assert (time.perf_counter() - began) < 0.05
