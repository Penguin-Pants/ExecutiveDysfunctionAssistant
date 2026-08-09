"""M8 — cloud backends, fallback and the egress indicator (T8.1–T8.5).

No network, no vendor account, no Windows. Every rule in design §2 is a property of the
backend's own logic, so the socket is a scripted double and the tests are deterministic.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest

# Bare `conformance`, not `tests.conformance`: `tests/` has no `__init__.py`, so pytest
# inserts the test file's own directory onto `sys.path`. The dotted form only works when
# the repo root happens to be there too — true under `python -m pytest`, which adds the
# cwd, and false under the `pytest` console script that CI runs.
from conformance import run_conformance_suite, start

from interview_prep_recall.diagnostics.ring import DiagnosticRing
from interview_prep_recall.platform.credentials import CredentialStore
from interview_prep_recall.session.health import Egress, HealthMonitor
from interview_prep_recall.stt import deepgram as dg
from interview_prep_recall.stt import elevenlabs as el
from interview_prep_recall.stt.cloud import CaptureClock, CloudSttBackend
from interview_prep_recall.stt.deepgram import DeepgramBackend
from interview_prep_recall.stt.elevenlabs import ElevenLabsBackend
from interview_prep_recall.stt.fallback import (
    FALLBACK_NOTICE,
    EgressMonitor,
    FallbackSttBackend,
)
from interview_prep_recall.stt.interface import (
    FRAME_BYTES,
    StateEvent,
    SttStreamState,
)

FRAME = b"\x00" * FRAME_BYTES


class FakeConnection:
    """A scripted WebSocket. Emits queued messages, then blocks like a live socket."""

    def __init__(self, messages: list[str] | None = None, fail_on_send: bool = False) -> None:
        self.sent: list[bytes | str] = []
        self.closed = False
        self._messages = list(messages or [])
        self._fail_on_send = fail_on_send

    async def send(self, data: bytes | str) -> None:
        if self._fail_on_send:
            raise ConnectionError("socket died")
        self.sent.append(data)

    async def recv(self) -> bytes | str:
        # A real server transcribes audio it was sent, so it cannot answer before the
        # first frame goes out. Without this the double races the send loop and the
        # backend sees transcripts for audio it has not sent — which it now correctly
        # drops, so the double, not the backend, is what would be wrong.
        while not any(isinstance(m, bytes) or '"audio"' in str(m) for m in self.sent):
            await asyncio.sleep(0.005)
        if self._messages:
            return self._messages.pop(0)
        # A real socket blocks here until the server speaks. Sleeping forever models
        # that; the receiver task is cancelled on teardown.
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")

    async def close(self) -> None:
        self.closed = True


def connector_for(connection: FakeConnection):  # type: ignore[no-untyped-def]
    async def connect():  # type: ignore[no-untyped-def]
        return connection

    return connect


def failing_connector(exc: Exception):  # type: ignore[no-untyped-def]
    async def connect():  # type: ignore[no-untyped-def]
        raise exc

    return connect


def dg_result(text: str, start_s: float, duration: float, is_final: bool) -> str:
    return json.dumps(
        {
            "type": "Results",
            "is_final": is_final,
            "start": start_s,
            "duration": duration,
            "channel": {"alternatives": [{"transcript": text, "confidence": 0.95}]},
        }
    )


def el_result(text: str, start_s: float, end_s: float, is_final: bool) -> str:
    return json.dumps(
        {
            "type": "transcript" if is_final else "partial_transcript",
            "text": text,
            "start": start_s,
            "end": end_s,
        }
    )


def wait_for(predicate, timeout: float = 3.0) -> bool:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# ---------- T8.1 / T8.2: the conformance suite, unmodified ----------


def test_deepgram_passes_the_conformance_suite() -> None:
    run_conformance_suite(lambda: DeepgramBackend(connector_for(FakeConnection())))


def test_elevenlabs_passes_the_conformance_suite() -> None:
    run_conformance_suite(lambda: ElevenLabsBackend(connector_for(FakeConnection())))


def test_the_suite_actually_fails_a_broken_backend() -> None:
    """A conformance suite that passes everything is worth nothing.

    This project's recurring defect is a test that passes while the guarantee is broken,
    so the suite itself gets a negative control: a backend that raises from `feed()` —
    a direct rule 1 violation — must be rejected by it.
    """

    class RaisingBackend(DeepgramBackend):
        def feed(self, pcm: bytes, t_capture: float) -> None:
            raise RuntimeError("rule 1 violated")

    with pytest.raises(RuntimeError):
        run_conformance_suite(lambda: RaisingBackend(connector_for(FakeConnection())))


class StallingConnection(FakeConnection):
    """A socket that accepts the connection and then never drains. Models the real
    backpressure case: the network is up, the server is slow."""

    async def send(self, data: bytes | str) -> None:
        await asyncio.sleep(3600)


def test_a_stalled_socket_drops_frames_and_reports_degraded() -> None:
    """Rule 1's second half. The assertion is on the *report*, not the drop: a backend
    that silently discards audio turns speech into a gap nothing accounts for.

    This cannot live in the shared conformance suite — against a double that drains
    instantly nothing ever overflows, so the check would fail a correct backend.
    """
    backend = DeepgramBackend(connector_for(StallingConnection()), max_queued_frames=10)
    recorder = start(backend)
    for i in range(200):
        backend.feed(FRAME, i * 0.02)

    assert SttStreamState.DEGRADED in recorder.state_names, (
        "frames were dropped without reporting DEGRADED"
    )
    backend.close()


def test_the_queue_stays_bounded_under_a_stalled_socket() -> None:
    """FR33: nothing in this pipeline may grow with session length. A stalled socket is
    the case where an unbounded queue would consume memory for the whole interview."""
    backend = DeepgramBackend(connector_for(StallingConnection()), max_queued_frames=10)
    start(backend)
    for i in range(5_000):
        backend.feed(FRAME, i * 0.02)

    assert len(backend._pending) <= 10
    backend.close()


# ---------- rule 5: timestamps come from the capture clock ----------


def test_timestamps_are_capture_time_not_server_time() -> None:
    """Rule 5. The server reports offsets from the start of the audio it received; the
    consumer needs the capture-side monotonic clock. Passing server time straight
    through would shift every utterance boundary by the connection's latency."""
    connection = FakeConnection([dg_result("hello there", 0.0, 1.0, True)])
    backend = DeepgramBackend(connector_for(connection))
    recorder = start(backend)

    # Capture began at t=500.0 on the monotonic clock, not at zero.
    backend.feed(FRAME, 500.0)
    assert wait_for(lambda: recorder.finals)
    backend.stop()

    event = recorder.finals[0]
    assert event.t_start == pytest.approx(500.0), (
        f"server offset 0.0 must map to capture time 500.0, got {event.t_start}"
    )
    assert event.t_end == pytest.approx(501.0)


def test_capture_clock_stays_correct_across_dropped_frames() -> None:
    """The subtle one. Anchoring on the first frame and adding the server offset is
    correct only while every frame is sent. Under backpressure frames are dropped, so
    the server's stream becomes shorter than elapsed capture time and a first-frame
    anchor drags every later timestamp earlier by the size of the gap."""
    clock = CaptureClock()
    clock.note_sent(100.0)  # sent: audio 0.00 → capture 100.00
    clock.note_sent(100.02)  # sent: audio 0.02 → capture 100.02
    # A one-second gap of dropped frames: capture time advances, sent audio does not.
    clock.note_sent(101.04)  # sent: audio 0.04 → capture 101.04

    assert clock.to_capture(0.00) == pytest.approx(100.00)
    assert clock.to_capture(0.02) == pytest.approx(100.02)
    # Naive anchoring would answer 100.04 here — a second early, in the middle of speech.
    assert clock.to_capture(0.04) == pytest.approx(101.04)


def test_a_reconnect_does_not_silence_the_stream_permanently() -> None:
    """The reconnect epoch bug, which had no test until it was found by review.

    A reconnect gives the vendor a new stream whose offsets restart at zero. If the
    capture clock keeps its old anchors, the first post-reconnect event maps tens of
    seconds backwards, the ordering guard discards it — correctly — and then discards
    every event after it too. The stream reports READY and transcribes nothing for the
    rest of the session, which is the worst available outcome: a silent failure on the
    recovery path that exists to prevent an outage.
    """
    connections = [
        FakeConnection(fail_on_send=True),
        FakeConnection([dg_result("after the reconnect", 0.0, 1.0, True)]),
    ]

    async def connect():  # type: ignore[no-untyped-def]
        return connections.pop(0) if connections else FakeConnection()

    backend = DeepgramBackend(connect, reconnect_attempts=3, backoff_s=0.05)
    recorder = start(backend)

    # First socket fails on send; the second one works. Capture time has moved on, but
    # the new server stream still numbers its offsets from zero.
    for i in range(5):
        backend.feed(FRAME, 900.0 + i * 0.02)
    assert wait_for(lambda: recorder.finals, timeout=5.0), (
        "no transcript after reconnect — the stream went silent while reporting READY"
    )
    backend.stop()

    event = recorder.finals[0]
    assert event.text == "after the reconnect"
    assert event.t_start >= 900.0, (
        f"post-reconnect timestamp fell back to the old epoch: {event.t_start}"
    )


def test_a_stalled_socket_does_not_flood_the_diagnostics_ring() -> None:
    """The ring is bounded at 2000 (FR36). One record per dropped frame would evict
    every real diagnostic with repetitions of a fact already recorded."""
    ring = DiagnosticRing()
    backend = DeepgramBackend(connector_for(StallingConnection()), ring=ring, max_queued_frames=10)
    start(backend)
    for i in range(1_000):
        backend.feed(FRAME, i * 0.02)
    backend.close()

    degraded = [e for e in ring.export()["events"] if e.get("state") == "DEGRADED"]
    assert 1 <= len(degraded) <= 25, f"{len(degraded)} DEGRADED records for 1000 frames"


# ---------- rules 2 and 3 ----------


def test_interim_results_are_marked_and_finals_are_not() -> None:
    """Rule 3. Consumers must never trigger matching on an interim (FR46), which they
    can only honour if the flag is truthful."""
    connection = FakeConnection(
        [dg_result("hel", 0.0, 0.3, False), dg_result("hello there", 0.0, 1.0, True)]
    )
    backend = DeepgramBackend(connector_for(connection))
    recorder = start(backend)
    backend.feed(FRAME, 0.0)
    assert wait_for(lambda: len(recorder.transcripts) >= 2)
    backend.stop()

    assert [e.is_final for e in recorder.transcripts] == [False, True]


def test_accepted_audio_that_never_finalises_reports_failed() -> None:
    """Rule 2: acknowledged audio yields exactly one final **or** the stream FAILS.

    A backend that closed quietly here would drop the last utterance of a session with
    nothing indicating it — the failure mode that only shows up at the end of a real
    interview.
    """
    connection = FakeConnection([])  # server never returns a transcript
    backend = DeepgramBackend(connector_for(connection))
    recorder = start(backend)
    backend.feed(FRAME, 0.0)
    backend.stop(flush_timeout_s=0.3)

    assert SttStreamState.FAILED in recorder.state_names
    assert recorder.state_names[-1] is SttStreamState.STOPPED


def test_silence_transcripts_are_not_emitted_as_spans() -> None:
    """Deepgram sends empty transcripts during silence. Forwarding them would make the
    assembler treat silence as speech and break utterance boundaries (FR46)."""
    connection = FakeConnection([dg_result("", 0.0, 1.0, True), dg_result("real", 1.0, 1.0, True)])
    backend = DeepgramBackend(connector_for(connection))
    recorder = start(backend)
    backend.feed(FRAME, 0.0)
    assert wait_for(lambda: recorder.finals)
    backend.stop()

    assert [e.text for e in recorder.transcripts] == ["real"]


def test_out_of_order_events_are_dropped_not_emitted() -> None:
    """Rule 4. A reconnect that replays, or a server that reorders, would otherwise push
    a span behind one the assembler has already closed."""
    connection = FakeConnection(
        [
            dg_result("second", 5.0, 1.0, True),
            dg_result("first", 1.0, 1.0, True),
        ]
    )
    backend = DeepgramBackend(connector_for(connection))
    recorder = start(backend)
    backend.feed(FRAME, 0.0)
    assert wait_for(lambda: recorder.finals)
    time.sleep(0.15)
    backend.stop()

    texts = [e.text for e in recorder.transcripts]
    assert texts == ["second"], f"backwards event was emitted: {texts}"


def test_a_malformed_message_does_not_kill_the_stream() -> None:
    connection = FakeConnection(["not json at all", dg_result("survived", 0.0, 1.0, True)])
    backend = DeepgramBackend(connector_for(connection))
    recorder = start(backend)
    backend.feed(FRAME, 0.0)
    assert wait_for(lambda: recorder.finals)
    backend.stop()

    assert [e.text for e in recorder.finals] == ["survived"]


# ---------- protocol specifics ----------


def test_elevenlabs_sends_base64_json_and_deepgram_sends_binary() -> None:
    """The one wire-level difference between the two, and the reason `encode_frame`
    is a hook rather than a branch in the shared send loop."""
    dg_connection = FakeConnection()
    dg_backend = DeepgramBackend(connector_for(dg_connection))
    start(dg_backend)
    dg_backend.feed(FRAME, 0.0)
    assert wait_for(lambda: dg_connection.sent)
    dg_backend.stop()
    assert isinstance(dg_connection.sent[0], bytes)

    el_connection = FakeConnection()
    el_backend = ElevenLabsBackend(connector_for(el_connection))
    start(el_backend)
    el_backend.feed(FRAME, 0.0)
    assert wait_for(lambda: len(el_connection.sent) >= 2)
    el_backend.stop()
    audio = [m for m in el_connection.sent if isinstance(m, str) and '"audio"' in m]
    assert audio, f"ElevenLabs must send base64 audio envelopes, sent {el_connection.sent}"


def test_elevenlabs_parses_absolute_start_and_end() -> None:
    """ElevenLabs reports start/end; Deepgram reports start/duration. Getting this
    backwards would make every span as long as its own start offset."""
    connection = FakeConnection([el_result("hello", 2.0, 3.5, True)])
    backend = ElevenLabsBackend(connector_for(connection))
    recorder = start(backend)
    backend.feed(FRAME, 0.0)
    assert wait_for(lambda: recorder.finals)
    backend.stop()

    event = recorder.finals[0]
    assert event.t_end - event.t_start == pytest.approx(1.5)


@pytest.mark.parametrize("backend_cls", [DeepgramBackend, ElevenLabsBackend])
def test_both_backends_send_a_finalise_message_on_stop(backend_cls) -> None:  # type: ignore[no-untyped-def]
    """Without a flush request the socket closes on a partial span and the last
    utterance of every session is lost — a rule 2 violation that only shows up at the
    end of a real interview."""
    connection = FakeConnection()
    backend = backend_cls(connector_for(connection))
    start(backend)
    backend.feed(FRAME, 0.0)
    assert wait_for(lambda: connection.sent)
    backend.stop(flush_timeout_s=1.0)
    assert wait_for(lambda: any(isinstance(m, str) for m in connection.sent)), (
        f"{backend_cls.__name__} closed without asking the server to flush finals"
    )


# ---------- T8.3: credentials never reach disk or diagnostics (FR19) ----------


def test_api_key_never_appears_in_a_diagnostic_export() -> None:
    """FR19's grep test. The ring's secret guard is armed by `CredentialStore`, so a key
    that has ever been loaded cannot enter an export whatever field it is passed as."""
    ring = DiagnosticRing()
    store = CredentialStore(ring=ring)
    secret = "dg_live_ABCDEF0123456789"
    store.set("deepgram", secret)
    assert store.get("deepgram") == secret

    with pytest.raises(ValueError):
        ring.record("stt_state", state=secret)

    ring.record("stt_state", state="READY", stream="interviewer")
    assert secret not in json.dumps(ring.export())


def test_the_key_is_not_in_the_endpoint_url() -> None:
    """A URL is the single most likely string to reach a log line. The key belongs in a
    header, which is why the connectors build one."""
    url = dg.endpoint_url()
    assert "token" not in url.lower() and "key" not in url.lower()
    assert el.ENDPOINT.startswith("wss://")


# ---------- T8.4: automatic fallback (FR21) ----------


class LocalDouble:
    """Stands in for the local Whisper backend, which needs Windows."""

    name = "local"
    supports_interim = False

    def __init__(self) -> None:
        self.started = False
        self.frames = 0
        self.closed = False

    def start(self, stream_id, sample_rate, channels, on_transcript, on_state) -> None:  # type: ignore[no-untyped-def]
        self.started = True
        on_state(StateEvent(stream_id=stream_id, state=SttStreamState.READY, detail=None))

    def feed(self, pcm: bytes, t_capture: float) -> None:
        self.frames += 1

    def stop(self, flush_timeout_s: float = 2.0) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def test_a_dropped_socket_falls_back_to_local_with_a_notice() -> None:
    """FR21. The connector fails outright, so the backend exhausts its reconnects and
    reports FAILED — which is what the wrapper watches for."""
    primary = DeepgramBackend(
        failing_connector(ConnectionError("socket killed")), reconnect_attempts=0
    )
    local = LocalDouble()
    backend = FallbackSttBackend(primary, lambda: local)
    recorder = start(backend)

    assert wait_for(lambda: local.started, timeout=5.0), "local backend never took over"
    backend.feed(FRAME, 0.0)
    assert local.frames == 1, "frames after the switch must reach the local backend"

    details = [e.detail for e in recorder.states if e.detail]
    assert FALLBACK_NOTICE in details, f"FR21 requires a notice; got {details}"
    backend.close()


def test_fallback_switches_only_once() -> None:
    """A flapping primary must not spawn a new local backend per failure event."""
    primary = DeepgramBackend(failing_connector(ConnectionError("dead")), reconnect_attempts=0)
    created: list[LocalDouble] = []

    def factory() -> LocalDouble:
        local = LocalDouble()
        created.append(local)
        return local

    backend = FallbackSttBackend(primary, factory)
    start(backend)
    assert wait_for(lambda: created, timeout=5.0)
    backend._watch_state(  # a second FAILED arriving after the switch
        StateEvent(stream_id="interviewer", state=SttStreamState.FAILED, detail=None)
    )
    assert len(created) == 1
    backend.close()


def test_close_closes_the_primary_even_after_a_switch() -> None:
    """After a fallback the primary's socket and thread are still live. Closing only
    the active backend would leave a cloud connection open for the rest of the process
    — egress the indicator has already reported as finished."""
    connection = FakeConnection()
    primary = DeepgramBackend(connector_for(connection))
    local = LocalDouble()
    backend = FallbackSttBackend(primary, lambda: local)
    start(backend)
    backend._switch()
    backend.close()

    assert local.closed
    assert wait_for(lambda: connection.closed, timeout=3.0), "the cloud socket stayed open"


# ---------- T8.5: the egress indicator (FR20) ----------


def test_egress_distinguishes_the_two_paths() -> None:
    """FR20 requires cloud-STT egress and LLM egress to be independently visible.
    "Something is leaving the device" is not the requirement."""
    monitor = HealthMonitor()
    egress = EgressMonitor(monitor)

    assert egress.set_cloud_stt(True) is Egress.CLOUD_STT
    assert egress.set_llm(True) is Egress.BOTH
    assert egress.set_cloud_stt(False) is Egress.LLM
    assert egress.set_llm(False) is Egress.NONE
    assert monitor.health.egress is Egress.NONE
    assert not monitor.health.data_leaving_device


def test_the_indicator_goes_dark_when_the_cloud_backend_falls_back() -> None:
    """The failure this pairing exists to prevent: the indicator still claiming audio is
    leaving the device after the cloud socket is gone — or, in the direction that
    actually matters, claiming it is not while the socket is open."""
    primary = DeepgramBackend(failing_connector(ConnectionError("dead")), reconnect_attempts=0)
    egress = EgressMonitor()
    backend = FallbackSttBackend(primary, LocalDouble, egress=egress)

    start(backend)
    # No assertion that the indicator is lit here: this connector fails instantly, so
    # the fallback can complete before `start()` returns and the indicator is correctly
    # already dark. The lit case has its own positive control below — asserting it here
    # too would make this test depend on losing a race.
    assert backend.wait_for_switch(timeout=5.0)
    assert egress.egress is Egress.NONE, "indicator stayed lit after the cloud socket closed"
    backend.close()


def test_egress_is_lit_while_a_healthy_cloud_backend_runs() -> None:
    """The positive control. The previous test would pass if the indicator were never
    lit at all."""
    connection = FakeConnection()
    backend = FallbackSttBackend(DeepgramBackend(connector_for(connection)), LocalDouble)
    start(backend)
    assert backend.egress.egress is Egress.CLOUD_STT
    backend.stop()
    assert backend.egress.egress is Egress.NONE
    backend.close()


# ---------- FR18: cloud is opt-in ----------


def test_a_cloud_backend_cannot_be_built_without_a_connector() -> None:
    """FR18: cloud backends are inactive without a key. The connector is the key's only
    route in, so requiring one makes "no key, no cloud" structural."""
    with pytest.raises(TypeError):
        DeepgramBackend()  # type: ignore[call-arg]


# ---------- concurrency ----------


def test_feed_from_the_audio_thread_never_raises_under_contention() -> None:
    """Rule 1 under the condition it exists for: `feed()` racing the backend's own
    loop teardown. A raise here would propagate into the WASAPI callback."""
    backend = DeepgramBackend(connector_for(FakeConnection()))
    start(backend)
    errors: list[BaseException] = []

    def hammer() -> None:
        try:
            for i in range(500):
                backend.feed(FRAME, i * 0.02)
        except BaseException as exc:  # noqa: BLE001 — the point of the test
            errors.append(exc)

    threads = [threading.Thread(target=hammer) for _ in range(4)]
    for t in threads:
        t.start()
    backend.close()
    for t in threads:
        t.join()

    assert not errors, f"feed() raised into the audio thread: {errors}"


def test_base_class_parse_is_not_silently_optional() -> None:
    """A subclass that forgets `parse` must fail loudly, not transcribe nothing."""
    backend = CloudSttBackend(connector_for(FakeConnection()))
    with pytest.raises(NotImplementedError):
        backend.parse("{}")


# ---------- PR #8 review round: rule 2 and rule 6, per span rather than per session ----


def test_a_later_unfinalised_utterance_still_reports_failed() -> None:
    """Rule 2 is a per-span guarantee, not a per-session one.

    `_final_seen` latched on the **first** final and never cleared, so audio accepted
    afterwards that the server never finalised reported STOPPED. That is the end of the
    interview dropped silently — by the mechanism written to make exactly that
    impossible. The original test passed because it only ever fed one utterance.
    """
    connection = FakeConnection([dg_result("first answer", 0.0, 1.0, True)])
    backend = DeepgramBackend(connector_for(connection))
    recorder = start(backend)

    backend.feed(FRAME, 0.0)
    assert wait_for(lambda: recorder.finals), "the first utterance never finalised"

    # More audio arrives; the server says nothing further about it.
    for i in range(5):
        backend.feed(FRAME, 10.0 + i * 0.02)
    backend.stop(flush_timeout_s=0.3)

    assert SttStreamState.FAILED in recorder.state_names, (
        "audio accepted after the last final was silently unaccounted for"
    )
    assert recorder.state_names[-1] is SttStreamState.STOPPED


def test_a_clean_single_utterance_does_not_report_failed() -> None:
    """Positive control for the test above, which would pass if FAILED were reported
    unconditionally."""
    connection = FakeConnection([dg_result("all finalised", 0.0, 1.0, True)])
    backend = DeepgramBackend(connector_for(connection))
    recorder = start(backend)
    backend.feed(FRAME, 0.0)
    assert wait_for(lambda: recorder.finals)
    backend.stop(flush_timeout_s=1.0)

    assert SttStreamState.FAILED not in recorder.state_names


def test_no_callbacks_arrive_after_stop_returns() -> None:
    """Rule 6. `close()` allows 0.5 s while the flush tail waited a fixed 1.5 s, so the
    join returned with the worker and socket still live — and `FallbackSttBackend` then
    cleared the egress indicator while the cloud socket was open. Callbacks are detached
    unconditionally before `stop()` returns."""
    connection = FakeConnection([dg_result("late", 0.0, 1.0, True)])
    backend = DeepgramBackend(connector_for(connection))
    recorder = start(backend)
    backend.feed(FRAME, 0.0)
    backend.stop(flush_timeout_s=0.05)

    seen = len(recorder.transcripts) + len(recorder.states)
    time.sleep(0.5)
    assert len(recorder.transcripts) + len(recorder.states) == seen, (
        "the worker emitted into a consumer that had been told the stream was over"
    )


def test_the_flush_tail_never_outlasts_the_callers_timeout() -> None:
    """The mechanism behind the test above: a fixed internal wait longer than the
    caller's timeout guarantees the join races the worker."""
    connection = FakeConnection()
    backend = DeepgramBackend(connector_for(connection))
    start(backend)
    backend.feed(FRAME, 0.0)

    began = time.monotonic()
    backend.stop(flush_timeout_s=0.2)
    elapsed = time.monotonic() - began
    assert elapsed < 1.5, f"stop() took {elapsed:.2f}s against a 0.2s flush timeout"
