"""M6 — state machine, purge, panic clear, supervision, switches, preflight, backpressure."""

from __future__ import annotations

import pytest

from interview_prep_recall.audio.capture import (
    FALLING_BEHIND_FRAMES,
    FRAME_BYTES,
    QUEUE_FRAMES,
    BoundedFrameQueue,
)
from interview_prep_recall.session.health import (
    Egress,
    Health,
    HealthMonitor,
    MatchingStatus,
    Status,
)
from interview_prep_recall.session.manager import (
    IllegalTransition,
    PauseCause,
    PurgeHooks,
    SessionManager,
    SessionState,
)
from interview_prep_recall.session.preflight import (
    CHECKS,
    CheckClass,
    Preflight,
)


def started() -> SessionManager:
    m = SessionManager()
    m.request_start()
    m.preflight_result(blocked=False)
    return m


# ---------------- T6.1 state machine ----------------


def test_happy_path_transitions() -> None:
    m = SessionManager()
    assert m.state is SessionState.IDLE
    m.request_start()
    assert m.state is SessionState.PREFLIGHT
    m.preflight_result(blocked=False)
    assert m.state is SessionState.RUNNING
    m.end_session()
    assert m.state is SessionState.IDLE


def test_preflight_hard_failure_returns_to_idle() -> None:
    m = SessionManager()
    m.request_start()
    assert m.preflight_result(blocked=True) is SessionState.IDLE


@pytest.mark.parametrize(
    "action",
    [
        lambda m: m.pause(PauseCause.USER),
        lambda m: m.end_session(),
        lambda m: m.panic_clear(),
    ],
)
def test_illegal_transitions_from_idle_raise(action) -> None:  # type: ignore[no-untyped-def]
    """Raised, never silently absorbed — a swallowed illegal transition is a state bug
    that only shows up as impossible behaviour three steps later."""
    with pytest.raises(IllegalTransition):
        action(SessionManager())


def test_cannot_resume_from_running() -> None:
    with pytest.raises(IllegalTransition):
        started().resume()


def test_every_state_is_actually_traversed() -> None:
    """Observes real transitions via the callback.

    An earlier version added PURGING and STOPPING to the set as literals, so it passed
    even if the manager jumped RUNNING -> WIPED and skipped them entirely — asserting
    only that the enum members exist.
    """
    seen: list[SessionState] = []
    m = SessionManager(on_state_change=lambda _old, new: seen.append(new))
    m.request_start()
    m.preflight_result(blocked=False)
    m.pause(PauseCause.LOCK)
    m.resume(automatic=True)
    m.panic_clear()
    m.resume()
    m.end_session()
    assert set(seen) | {SessionState.IDLE} == set(SessionState)
    assert SessionState.PURGING in seen and SessionState.STOPPING in seen


# ---------------- pause causes ----------------


def test_user_pause_does_not_auto_resume() -> None:
    """Pausing to think must not silently undo itself."""
    m = started()
    m.pause(PauseCause.USER)
    with pytest.raises(IllegalTransition, match="user pause"):
        m.resume(automatic=True)
    m.resume()
    assert m.state is SessionState.RUNNING


@pytest.mark.parametrize("cause", [PauseCause.LOCK, PauseCause.DEVICE_LOST])
def test_machine_pauses_auto_resume(cause: PauseCause) -> None:
    m = started()
    m.pause(cause)
    m.resume(automatic=True)
    assert m.state is SessionState.RUNNING
    assert m.pause_cause is None


def test_pause_cause_is_recorded() -> None:
    m = started()
    m.pause(PauseCause.DEVICE_LOST)
    assert m.pause_cause is PauseCause.DEVICE_LOST


# ---------------- T6.2 / T6.3 purge ----------------


def test_purge_runs_hooks_in_the_specified_order() -> None:
    """Ordering is the requirement (FR59), not an implementation detail."""
    m = started()
    m.end_session()
    assert m.purge_order == [
        "cancel_network",
        "stop_capture",
        "zero_audio",
        "drop_transcript",
        "clear_overlay",
    ]


def test_network_is_cancelled_before_local_state_is_cleared() -> None:
    order: list[str] = []
    hooks = PurgeHooks(
        cancel_network=lambda: order.append("network"),
        zero_audio=lambda: order.append("audio"),
        drop_transcript=lambda: order.append("transcript"),
        clear_overlay=lambda: order.append("overlay"),
    )
    m = SessionManager(hooks=hooks)
    m.request_start()
    m.preflight_result(blocked=False)
    m.panic_clear()
    assert order[0] == "network", "in-flight work must not outlive the purge"


def test_panic_clear_lands_in_wiped_and_resumes_without_preflight() -> None:
    """D-U5: an unambiguous stop *and* a fast recovery."""
    m = started()
    m.panic_clear()
    assert m.state is SessionState.WIPED
    m.resume()
    assert m.state is SessionState.RUNNING


def test_panic_clear_is_not_undone_by_a_machine_event() -> None:
    """A stray device-return callback must not restart capture the user just stopped."""
    m = started()
    m.panic_clear()
    with pytest.raises(IllegalTransition, match="undone only"):
        m.resume(automatic=True)
    assert m.state is SessionState.WIPED


def test_wiped_can_end_the_session_instead() -> None:
    m = started()
    m.panic_clear()
    m.end_session()
    assert m.state is SessionState.IDLE


def test_panic_clear_from_paused() -> None:
    m = started()
    m.pause(PauseCause.USER)
    m.panic_clear()
    assert m.state is SessionState.WIPED


def test_a_second_pause_cannot_overwrite_a_deliberate_one() -> None:
    """A lock callback arriving while the user is already paused must not leave an
    auto-resumable cause behind — the next unlock would restart capture they stopped."""
    m = started()
    m.pause(PauseCause.USER)
    with pytest.raises(IllegalTransition, match="is preserved"):
        m.pause(PauseCause.LOCK)
    assert m.pause_cause is PauseCause.USER
    with pytest.raises(IllegalTransition):
        m.resume(automatic=True)


def test_purge_completes_every_step_even_when_a_hook_throws() -> None:
    """`cancel_network` closing an already-broken socket is the plausible failure, and
    it runs first — aborting there would leave capture running and nothing cleared, so
    panic clear would fail precisely on the degraded session that needs it."""
    ran: list[str] = []

    def boom() -> None:
        raise OSError("socket already closed")

    hooks = PurgeHooks(
        cancel_network=boom,
        stop_capture=lambda: ran.append("stop_capture"),
        zero_audio=lambda: ran.append("zero_audio"),
        drop_transcript=lambda: ran.append("drop_transcript"),
        clear_overlay=lambda: ran.append("clear_overlay"),
    )
    m = SessionManager(hooks=hooks)
    m.request_start()
    m.preflight_result(blocked=False)
    m.panic_clear()

    assert ran == ["stop_capture", "zero_audio", "drop_transcript", "clear_overlay"]
    assert m.state is SessionState.WIPED, "a failing hook must not strand the session"
    assert m.purge_failures == [("cancel_network", "OSError")]


def test_purge_clears_session_scoped_diagnostics() -> None:
    """FR36: diagnostics are session-scoped. Stale events would otherwise leak into the
    next session's export and crowd the bounded ring."""
    m = started()
    for _ in range(20):
        m.ring.record("tick", count=1)
    before = len(m.ring)
    m.end_session()
    assert len(m.ring) < before
    assert all(e.event != "tick" for e in m.ring.snapshot())


def test_purge_failures_survive_the_ring_clear() -> None:
    """The purge outcome is the one thing from the old session worth carrying forward."""
    hooks = PurgeHooks(cancel_network=lambda: (_ for _ in ()).throw(OSError("x")))
    m = SessionManager(hooks=hooks)
    m.request_start()
    m.preflight_result(blocked=False)
    m.panic_clear()
    events = [e.event for e in m.ring.snapshot()]
    assert "purge_hook_failed" in events


def test_purge_resets_health() -> None:
    m = started()
    m.monitor.update(loopback=Status.OK, matching=MatchingStatus.LOCAL_ONLY)
    m.panic_clear()
    assert m.monitor.health == Health()


def test_purge_never_touches_notes(app_data, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """FR58. The worst outcome this codebase can produce is a panic clear that
    destroys the user's prep, so it is asserted against real files."""
    import hashlib

    from interview_prep_recall.notes.model import Note, NoteSet
    from interview_prep_recall.notes.store import NotesStore

    store = NotesStore(app_data)
    ns = NoteSet(name="prep", notes=[Note(headline="Tell me about a conflict?")])
    path = store.save(ns)
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    m = started()
    m.panic_clear()

    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


# ---------------- T6.6 supervision ----------------


def test_worker_restarts_once_then_holds() -> None:
    m = started()
    assert m.note_worker_failure("interviewer") is True
    assert m.note_worker_failure("interviewer") is False


def test_restart_budget_resets_for_a_new_session() -> None:
    """FR61 is per session. Without a reset the counter persists for the process
    lifetime, so a stream that crashed once is held from its first crash next time."""
    m = started()
    m.note_worker_failure("interviewer")
    m.note_worker_failure("interviewer")
    m.end_session()

    m.request_start()
    m.preflight_result(blocked=False)
    assert m.note_worker_failure("interviewer") is True


def test_worker_supervision_is_per_stream() -> None:
    """FR61: a dead mic worker must never stop interviewer matching."""
    m = started()
    m.note_worker_failure("user")
    m.note_worker_failure("user")
    assert m.monitor.health.stt_user is Status.FAILED
    assert m.monitor.health.stt_interviewer is not Status.FAILED
    assert m.note_worker_failure("interviewer") is True


# ---------------- T6.7 switches ----------------


class FakeMatching:
    """Records what the switch actually did to the pipeline, not to a config object."""

    def __init__(self) -> None:
        self.local_only = False

    def set_local_only(self, value: bool) -> None:
        self.local_only = value


def test_switches_toggle_mid_session() -> None:
    m = started()
    m.attach_matching(FakeMatching())
    m.set_switch("llm_matching", False)
    assert m.switches.llm_matching is False
    assert m.monitor.health.matching is MatchingStatus.LOCAL_ONLY
    m.set_switch("llm_matching", True)
    assert m.monitor.health.matching is MatchingStatus.OK
    assert m.state is SessionState.RUNNING, "no restart required"


def test_llm_switch_reaches_the_pipeline() -> None:
    """FR37 + FR20: the indicator must not claim local-only while the API is still
    being called. A switch that only flips a config object would tell the user their
    question text stays on the device when it does not."""
    m = started()
    pipeline = FakeMatching()
    m.attach_matching(pipeline)

    m.set_switch("llm_matching", False)
    assert pipeline.local_only is True

    m.set_switch("llm_matching", True)
    assert pipeline.local_only is False


def test_llm_switch_without_a_pipeline_refuses_rather_than_lying() -> None:
    with pytest.raises(RuntimeError, match="no pipeline attached"):
        started().set_switch("llm_matching", False)


def test_non_llm_switches_need_no_pipeline() -> None:
    m = started()
    m.set_switch("progress_tracker", False)
    assert m.switches.progress_tracker is False


def test_unknown_switch_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown degradation switch"):
        started().set_switch("teleportation", True)


# ---------------- health model ----------------


def test_nominal_health_produces_no_indicators() -> None:
    """The OB-1 property: an empty overlay with healthy state means "nothing matched"."""
    h = Health(
        loopback=Status.OK,
        mic=Status.OK,
        stt_interviewer=Status.OK,
        stt_user=Status.OK,
        matching=MatchingStatus.OK,
        capture_excluded=True,
    )
    assert h.indicators() == []
    assert h.nominal


def test_no_match_is_never_an_indicator() -> None:
    """Content is not health. Conflating them is the failure FR35 exists to prevent."""
    h = Health(loopback=Status.OK, matching=MatchingStatus.OK, capture_excluded=True)
    assert not any("match" in i for i in h.indicators())


def test_capture_exclusion_failure_is_surfaced_first() -> None:
    h = Health(loopback=Status.OK, matching=MatchingStatus.OK, capture_excluded=False)
    assert h.indicators()[0] == "NOT hidden from screen share"
    assert not h.nominal


def test_per_stream_stt_failure_names_the_stream() -> None:
    h = Health(loopback=Status.OK, stt_user=Status.FAILED, matching=MatchingStatus.OK)
    assert "STT unavailable (mic)" in h.indicators()


def test_silence_and_lag_indicators() -> None:
    h = Health(loopback=Status.OK, matching=MatchingStatus.OK, silence_s=12.0, lag=4.0)
    joined = " ".join(h.indicators())
    assert "no audio detected (12s)" in joined
    assert "falling behind" in joined


def test_audio_lost_supersedes_silence() -> None:
    h = Health(loopback=Status.FAILED, matching=MatchingStatus.OK, silence_s=30.0)
    assert "audio lost" in h.indicators()
    assert not any("no audio detected" in i for i in h.indicators())


def test_egress_combinations() -> None:
    assert Egress.of(cloud_stt=False, llm=False) is Egress.NONE
    assert Egress.of(cloud_stt=True, llm=False) is Egress.CLOUD_STT
    assert Egress.of(cloud_stt=False, llm=True) is Egress.LLM
    assert Egress.of(cloud_stt=True, llm=True) is Egress.BOTH
    assert Health(egress=Egress.LLM).data_leaving_device


def test_monitor_history_is_bounded() -> None:
    monitor = HealthMonitor()
    for _ in range(500):
        monitor.update(lag=1.0)
    assert len(monitor._history) <= 64


# ---------------- T6.5 preflight ----------------


def all_pass() -> dict[str, object]:
    return {c.key: (lambda: True) for c in CHECKS}


def test_all_checks_passing_is_not_blocked() -> None:
    report = Preflight(all_pass(), cloud_enabled=True).run()  # type: ignore[arg-type]
    assert not report.blocked
    assert report.warnings == []
    assert len(report.passed) == len(CHECKS)


@pytest.mark.parametrize("check", [c for c in CHECKS if c.cls is CheckClass.BLOCK])
def test_each_hard_check_blocks(check) -> None:  # type: ignore[no-untyped-def]
    """T6.5's criterion: each precondition failed *in turn* classifies correctly."""
    probes = all_pass()
    probes[check.key] = lambda: False
    report = Preflight(probes, cloud_enabled=True).run()  # type: ignore[arg-type]
    assert report.blocked
    assert [r.check.key for r in report.blockers] == [check.key]


@pytest.mark.parametrize("check", [c for c in CHECKS if c.cls is CheckClass.WARN])
def test_each_soft_check_warns_without_blocking(check) -> None:  # type: ignore[no-untyped-def]
    probes = all_pass()
    probes[check.key] = lambda: False
    report = Preflight(probes, cloud_enabled=True).run()  # type: ignore[arg-type]
    assert not report.blocked
    assert [r.check.key for r in report.warnings] == [check.key]


def test_capture_exclusion_warns_rather_than_blocks() -> None:
    """Blocking would permanently strand a user whose machine always fails it."""
    from interview_prep_recall.session.preflight import CHECKS_BY_KEY

    assert CHECKS_BY_KEY["capture_excluded"].cls is CheckClass.WARN


def test_cloud_checks_are_skipped_when_cloud_is_off() -> None:
    report = Preflight(all_pass(), cloud_enabled=False).run()  # type: ignore[arg-type]
    keys = {r.check.key for r in report.results}
    assert "api_key_valid" not in keys
    assert "stt_reachable" not in keys


def test_missing_probe_fails_rather_than_passes() -> None:
    """An unimplemented check must not silently clear the gate it exists to hold."""
    probes = all_pass()
    del probes["loopback_device"]
    report = Preflight(probes, cloud_enabled=True).run()  # type: ignore[arg-type]
    assert report.blocked
    assert report.result_for("loopback_device").detail == "no probe registered"  # type: ignore[union-attr]


def test_throwing_probe_is_a_failure_not_a_crash() -> None:
    probes = all_pass()

    def boom() -> bool:
        raise OSError("device enumeration failed")

    probes["mic_device"] = boom
    report = Preflight(probes, cloud_enabled=True).run()  # type: ignore[arg-type]
    assert report.blocked
    assert report.result_for("mic_device").detail == "OSError"  # type: ignore[union-attr]


def test_probe_can_return_a_detail_string() -> None:
    probes = all_pass()
    probes["windows_build"] = lambda: (True, "22631")
    report = Preflight(probes, cloud_enabled=True).run()  # type: ignore[arg-type]
    assert report.result_for("windows_build").detail == "22631"  # type: ignore[union-attr]


def test_unknown_probe_key_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown checks"):
        Preflight({"not_a_check": lambda: True}, cloud_enabled=True)  # type: ignore[arg-type]


def test_preflight_records_no_content() -> None:
    p = Preflight(all_pass(), cloud_enabled=True)  # type: ignore[arg-type]
    p.run()
    assert len(p.ring) > 0


# ---------------- T6.6 backpressure ----------------


def frame() -> bytearray:
    return bytearray(FRAME_BYTES)


def test_queue_defaults_to_three_seconds_of_frames() -> None:
    """Design §1a: 150 frames, not 3 chunks. The distinction is ~400x of buffer."""
    assert QUEUE_FRAMES == 150
    assert FRAME_BYTES == 640
    assert BoundedFrameQueue().maxlen == 150


def test_overflow_drops_oldest_and_counts() -> None:
    q = BoundedFrameQueue(maxlen=4)
    for i in range(10):
        q.push(bytes([i]), float(i))
    assert q.depth == 4
    assert q.dropped == 6
    first, _ = q.pop()  # type: ignore[misc]
    assert first == bytes([6]), "the newest frames survive, not the stalest"


def test_depth_is_flat_under_sustained_overflow() -> None:
    """FR33/NFR5: nothing in the pipeline grows with session length."""
    q = BoundedFrameQueue(maxlen=16)
    for i in range(10_000):
        q.push(frame(), float(i))
    assert q.depth == 16


def test_falling_behind_threshold() -> None:
    q = BoundedFrameQueue()
    for i in range(FALLING_BEHIND_FRAMES - 1):
        q.push(frame(), float(i))
    assert not q.falling_behind
    q.push(frame(), 0.0)
    assert q.falling_behind


def test_zero_wipes_every_stored_frame() -> None:
    """FR15. `zero()` reports frames *actually* wiped, not frames present."""
    q = BoundedFrameQueue()
    for _ in range(3):
        q.push(bytearray(b"\xff" * FRAME_BYTES), 0.0)
    assert q.zero() == 3
    assert q.depth == 0


def test_immutable_bytes_are_still_zeroable() -> None:
    """`push` invites `bytes`; storing them would make the FR15 guarantee silently
    false, since immutable buffers cannot be overwritten."""
    q = BoundedFrameQueue()
    q.push(b"\xff" * FRAME_BYTES, 0.0)
    stored, _ = q.drain()[0]
    assert isinstance(stored, bytearray)

    q.push(b"\xff" * FRAME_BYTES, 0.0)
    assert q.zero() == 1


def test_push_copies_so_a_reused_callback_buffer_cannot_corrupt_the_queue() -> None:
    """WASAPI callbacks reuse a scratch buffer. Holding it by reference would let the
    next callback overwrite an already-queued frame — silent audio corruption that
    would surface as unexplained transcription errors."""
    q = BoundedFrameQueue()
    scratch = bytearray(b"\x01" * FRAME_BYTES)
    q.push(scratch, 0.0)

    scratch[:] = b"\x02" * FRAME_BYTES  # the next callback reuses the buffer

    stored, _ = q.pop()  # type: ignore[misc]
    assert set(stored) == {1}, "queued frame must not alias the caller's buffer"


def test_drain_empties_the_queue() -> None:
    q = BoundedFrameQueue()
    for i in range(5):
        q.push(frame(), float(i))
    assert len(q.drain()) == 5
    assert q.depth == 0


def test_pop_on_empty_returns_none() -> None:
    assert BoundedFrameQueue().pop() is None


def test_zero_maxlen_is_refused() -> None:
    with pytest.raises(ValueError):
        BoundedFrameQueue(maxlen=0)
