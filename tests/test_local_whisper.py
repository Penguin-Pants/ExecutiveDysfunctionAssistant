"""T2.2 — the local Whisper backend's VAD, finalisation and threading.

No model file, no download, no Windows. `Transcriber` is a Protocol precisely so the
part of this backend that is *ours* — the VAD, FR47's synthesised finalisation, the
capture-clock timestamps, backpressure and the worker lifecycle — is checkable here.
`FasterWhisperTranscriber` itself is untested and recorded as **AS-9**: the container's
network policy denies `huggingface.co`, so no model has ever been loaded.

The acceptance criterion is "every acknowledged span yields exactly one final event",
and the tests that matter are the ones that could catch it being false: a span that
transcribes to nothing, a span open when `stop()` arrives, a span the transcriber
raises on, and a forced cut at `MAX_SPAN_S`.
"""

from __future__ import annotations

import math
import threading
import time

import pytest

# Bare `conformance`, not `tests.conformance` — see the note in `test_cloud_stt.py`.
from conformance import run_conformance_suite, start

from interview_prep_recall.diagnostics.ring import DiagnosticRing
from interview_prep_recall.stt.interface import FRAME_BYTES, SttStreamState
from interview_prep_recall.stt.local_whisper import (
    FRAME_S,
    ONSET_FRAMES,
    EnergyVad,
    LocalWhisperBackend,
    TranscriptionResult,
    _rms,
)

SILENCE = b"\x00" * FRAME_BYTES


def speech_frame(amplitude: int = 8_000) -> bytes:
    """A frame the energy VAD must classify as speech.

    A square wave rather than a constant: a DC offset has the RMS of speech but none of
    its structure, and building the fixture out of something a real detector would also
    accept keeps the test honest about what it is asserting.
    """
    half = FRAME_BYTES // 4
    sample = amplitude.to_bytes(2, "little", signed=True)
    negative = (-amplitude).to_bytes(2, "little", signed=True)
    return (sample * half + negative * half)[:FRAME_BYTES]


SPEECH = speech_frame()


class FakeTranscriber:
    """Records every buffer it is asked to transcribe, and answers from a script."""

    def __init__(self, texts: list[str] | None = None, raises: bool = False) -> None:
        self.calls: list[bytes] = []
        self._texts = list(texts or [])
        self._raises = raises
        self.lock = threading.Lock()

    def transcribe(self, pcm: bytes, sample_rate: int) -> TranscriptionResult:
        with self.lock:
            self.calls.append(pcm)
            if self._raises:
                raise RuntimeError("model exploded")
            text = self._texts.pop(0) if self._texts else "hello there"
        return TranscriptionResult(text=text, confidence=0.9)


def feed_frames(backend: LocalWhisperBackend, frames: list[bytes], t0: float = 0.0) -> float:
    """Feed frames on a synthetic capture clock. Returns the next capture time."""
    t = t0
    for frame in frames:
        backend.feed(frame, t)
        t += FRAME_S
    return t


def drain(backend: LocalWhisperBackend, recorder, expected: int, timeout: float = 3.0) -> None:
    """Wait for the worker to catch up. Polls rather than sleeps a fixed interval so a
    slow CI box does not turn a correct backend into a flake."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and len(recorder.finals) < expected:
        time.sleep(0.01)


def silence_run(seconds: float) -> list[bytes]:
    return [SILENCE] * (int(seconds / FRAME_S) + 1)


# ---------- the conformance suite (T2.1) ----------


def test_passes_the_conformance_suite() -> None:
    """The acceptance criterion, run against the same suite the cloud backends pass.

    This is the payoff of D-2: the interface was written from *this* backend's
    constraints, and the suite it produced turns out to bind a WebSocket backend and a
    blocking-inference backend equally.
    """
    run_conformance_suite(lambda: LocalWhisperBackend(transcriber=FakeTranscriber()))


# ---------- FR47: exactly one final per acknowledged span ----------


def test_silence_finalises_a_span() -> None:
    transcriber = FakeTranscriber(["what is your greatest weakness"])
    backend = LocalWhisperBackend(transcriber=transcriber)
    recorder = start(backend)

    t = feed_frames(backend, [SPEECH] * 25)
    feed_frames(backend, silence_run(0.8), t0=t)
    drain(backend, recorder, expected=1)
    backend.stop(flush_timeout_s=1.0)

    assert len(recorder.finals) == 1
    assert recorder.finals[0].text == "what is your greatest weakness"
    assert recorder.finals[0].is_final is True


def test_each_span_yields_exactly_one_final() -> None:
    """Three spans separated by silence produce three finals — not two, not four.

    The acceptance criterion in one assertion. Miscounting in either direction is a
    real defect: a lost final is speech that never reaches matching, and a duplicate is
    an utterance the overlay answers twice.
    """
    transcriber = FakeTranscriber(["one", "two", "three"])
    backend = LocalWhisperBackend(transcriber=transcriber)
    recorder = start(backend)

    t = 0.0
    for _ in range(3):
        t = feed_frames(backend, [SPEECH] * 15, t0=t)
        t = feed_frames(backend, silence_run(0.8), t0=t)
    drain(backend, recorder, expected=3)
    backend.stop(flush_timeout_s=1.0)

    assert [e.text for e in recorder.finals] == ["one", "two", "three"]


def test_open_span_is_finalised_by_stop() -> None:
    """The last thing said before the interview ends.

    Nothing closes this span — no trailing silence, no max-span cut — so if `stop()` did
    not flush, the answer the user most wants in their report would vanish with a clean
    STOPPED and a fully green suite.
    """
    transcriber = FakeTranscriber(["still talking when it ended"])
    backend = LocalWhisperBackend(transcriber=transcriber)
    recorder = start(backend)

    feed_frames(backend, [SPEECH] * 20)
    backend.stop(flush_timeout_s=2.0)

    assert [e.text for e in recorder.finals] == ["still talking when it ended"]
    assert recorder.state_names[-1] is SttStreamState.STOPPED


def test_empty_transcription_still_emits_its_final() -> None:
    """A cough opens a span; Whisper returns nothing. The final is emitted regardless.

    Dropping it would leave the guarantee's own tests passing while a span the backend
    acknowledged disappeared — this project's recurring defect class, reached through
    the code written to prevent it.
    """
    transcriber = FakeTranscriber([""])
    ring = DiagnosticRing()
    backend = LocalWhisperBackend(transcriber=transcriber, ring=ring)
    recorder = start(backend)

    t = feed_frames(backend, [SPEECH] * 10)
    feed_frames(backend, silence_run(0.8), t0=t)
    drain(backend, recorder, expected=1)
    backend.stop(flush_timeout_s=1.0)

    assert len(recorder.finals) == 1
    assert recorder.finals[0].text == ""
    assert any(e.event == "stt_empty_span" for e in ring.snapshot())


def test_max_span_forces_a_cut_without_silence() -> None:
    """A monologue that never pauses is still cut at MAX_SPAN_S."""
    transcriber = FakeTranscriber(["part one", "part two"])
    backend = LocalWhisperBackend(transcriber=transcriber, max_span_s=0.5)
    recorder = start(backend)

    feed_frames(backend, [SPEECH] * 60)
    drain(backend, recorder, expected=2)
    backend.stop(flush_timeout_s=2.0)

    assert len(recorder.finals) >= 2


def test_inference_failure_reports_failed_and_keeps_going() -> None:
    """Rule 2's other branch: a final *or* FAILED, never a silent drop.

    And the stream survives it — one bad inference pass is not a reason to go deaf for
    the rest of an interview.
    """
    transcriber = FakeTranscriber(raises=True)
    ring = DiagnosticRing()
    backend = LocalWhisperBackend(transcriber=transcriber, ring=ring)
    recorder = start(backend)

    t = feed_frames(backend, [SPEECH] * 10)
    feed_frames(backend, silence_run(0.8), t0=t)
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and SttStreamState.FAILED not in recorder.state_names:
        time.sleep(0.01)
    backend.stop(flush_timeout_s=1.0)

    assert SttStreamState.FAILED in recorder.state_names
    assert recorder.finals == []
    assert any(e.event == "stt_inference_failed" for e in ring.snapshot())


# ---------- rule 5: capture-clock timestamps ----------


def test_timestamps_are_on_the_capture_clock() -> None:
    """Rule 5. The events describe when the audio was *captured*, not when a CPU-bound
    inference pass happened to finish — which on a laptop can be seconds later."""
    backend = LocalWhisperBackend(transcriber=FakeTranscriber(["said at ninety seconds"]))
    recorder = start(backend)

    t = feed_frames(backend, [SPEECH] * 25, t0=90.0)
    feed_frames(backend, silence_run(0.8), t0=t)
    drain(backend, recorder, expected=1)
    backend.stop(flush_timeout_s=1.0)

    event = recorder.finals[0]
    assert event.t_start == pytest.approx(90.0, abs=0.05)
    assert event.t_end == pytest.approx(90.0 + 25 * FRAME_S, abs=0.05)


def test_t_end_excludes_the_trailing_silence() -> None:
    """The 700 ms hang is fed to the model but must not land in `t_end`.

    `UtteranceAssembler` measures inter-utterance gaps from `t_end`, so padding every
    span by the full silence budget would consume the gap that closes utterances and
    two separate answers would merge into one.
    """
    backend = LocalWhisperBackend(transcriber=FakeTranscriber(["short"]))
    recorder = start(backend)

    speech_end = feed_frames(backend, [SPEECH] * 10)
    feed_frames(backend, silence_run(0.9), t0=speech_end)
    drain(backend, recorder, expected=1)
    backend.stop(flush_timeout_s=1.0)

    assert recorder.finals[0].t_end == pytest.approx(speech_end, abs=0.03)


# ---------- rule 1: backpressure ----------


def test_overflow_drops_and_reports_degraded() -> None:
    """Rule 1's drop-half, which the generic suite cannot check because it needs a
    stalled backend — here, a transcriber that blocks the worker mid-pass."""
    release = threading.Event()

    class StalledTranscriber:
        def transcribe(self, pcm: bytes, sample_rate: int) -> TranscriptionResult:
            release.wait(timeout=5.0)
            return TranscriptionResult(text="late")

    backend = LocalWhisperBackend(transcriber=StalledTranscriber(), max_queued_frames=10)
    recorder = start(backend)
    try:
        t = feed_frames(backend, [SPEECH] * 4)
        t = feed_frames(backend, silence_run(0.8), t0=t)
        # The worker is now inside `transcribe`. Everything after this overflows.
        feed_frames(backend, [SPEECH] * 400, t0=t)
        assert SttStreamState.DEGRADED in recorder.state_names
    finally:
        release.set()
        backend.close()


def test_feed_does_not_block_the_audio_callback() -> None:
    """FR45 gives the audio callback 2 ms. `feed()` must return in a fraction of it even
    while the worker is stuck inside a slow inference pass."""
    release = threading.Event()

    class StalledTranscriber:
        def transcribe(self, pcm: bytes, sample_rate: int) -> TranscriptionResult:
            release.wait(timeout=5.0)
            return TranscriptionResult(text="late")

    backend = LocalWhisperBackend(transcriber=StalledTranscriber(), max_queued_frames=10)
    start(backend)
    try:
        t = feed_frames(backend, [SPEECH] * 4)
        feed_frames(backend, silence_run(0.8), t0=t)
        started = time.perf_counter()
        for i in range(200):
            backend.feed(SPEECH, 10.0 + i * FRAME_S)
        per_call = (time.perf_counter() - started) / 200
        assert per_call < 0.002, f"feed() averaged {per_call * 1000:.3f} ms"
    finally:
        release.set()
        backend.close()


# ---------- the VAD ----------


def test_vad_separates_speech_from_digital_silence() -> None:
    vad = EnergyVad()
    assert vad.is_speech(SPEECH) is True
    assert vad.is_speech(SILENCE) is False


def test_digital_silence_never_becomes_speech() -> None:
    """The adaptive floor must not collapse toward zero on a muted stream.

    If it did, the noise floor would sink until dither registered as talking, and the
    backend would transcribe a silent mic all interview — burning CPU and filling the
    overlay from nothing.
    """
    vad = EnergyVad()
    for _ in range(5_000):
        assert vad.is_speech(SILENCE) is False
    assert vad.is_speech(speech_frame(100)) is False


def test_quiet_speech_is_still_detected_after_a_long_silence() -> None:
    vad = EnergyVad()
    for _ in range(1_000):
        vad.is_speech(SILENCE)
    assert vad.is_speech(speech_frame(4_000)) is True


def test_single_frame_transients_do_not_open_a_span() -> None:
    """ONSET_FRAMES: a click costs nothing, a whole inference pass is expensive."""
    transcriber = FakeTranscriber()
    backend = LocalWhisperBackend(transcriber=transcriber)
    recorder = start(backend)

    t = 0.0
    for _ in range(5):
        t = feed_frames(backend, [SPEECH], t0=t)
        t = feed_frames(backend, silence_run(0.2), t0=t)
    backend.stop(flush_timeout_s=1.0)

    assert transcriber.calls == []
    assert recorder.finals == []
    assert ONSET_FRAMES > 1


def test_rms_does_not_overflow_on_loud_audio() -> None:
    """Squaring int16 in its own dtype wraps and returns a small wrong number, which
    reads as silence during the loudest speech."""
    assert _rms(speech_frame(32_000)) == pytest.approx(32_000, abs=1.0)
    assert _rms(SILENCE) == 0.0
    assert not math.isnan(_rms(b""))


# ---------- lifecycle ----------


def test_start_rejects_a_mismatched_format() -> None:
    """Coercing silently would put the VAD's thresholds and every timestamp on the wrong
    time base, producing a transcript that looks plausible and is wrong about when."""
    backend = LocalWhisperBackend(transcriber=FakeTranscriber())
    with pytest.raises(ValueError, match="16000 Hz mono"):
        backend.start("user", 44_100, 1, lambda e: None, lambda e: None)


def test_injected_ring_is_used() -> None:
    """D-26: `DiagnosticRing` defines `__len__`, so an empty ring is falsy and `or`
    would silently discard the injected one."""
    ring = DiagnosticRing()
    backend = LocalWhisperBackend(transcriber=FakeTranscriber(), ring=ring)
    assert backend.ring is ring


def test_no_callbacks_after_stop_returns() -> None:
    """A worker that outlives its timeout must not reach a consumer that has been told
    the stream is over."""
    backend = LocalWhisperBackend(transcriber=FakeTranscriber())
    recorder = start(backend)
    feed_frames(backend, [SPEECH] * 10)
    backend.stop(flush_timeout_s=2.0)
    before = len(recorder.transcripts)

    backend.feed(SPEECH, 99.0)
    time.sleep(0.1)
    assert len(recorder.transcripts) == before


# ---------- restart (found in review) ----------


def test_restarting_does_not_discard_the_new_session() -> None:
    """`FallbackSttBackend` restarts a backend mid-interview, and the new session's
    capture clock need not resume above the old one's last timestamp.

    A `_last_emitted_start` carried across `start()` makes the rule-4 ordering guard
    reject every event of the second session: READY, no errors, permanently silent. This
    is the same defect `CaptureClock.reset` was written for in the cloud backend, which
    is why it was worth looking for here.
    """
    backend = LocalWhisperBackend(transcriber=FakeTranscriber(["first", "second"]))

    first = start(backend)
    t = feed_frames(backend, [SPEECH] * 15, t0=500.0)
    feed_frames(backend, silence_run(0.8), t0=t)
    drain(backend, first, expected=1)
    backend.stop(flush_timeout_s=1.0)
    assert [e.text for e in first.finals] == ["first"]

    # New session, clock starting far below where the last one ended.
    second = start(backend)
    t = feed_frames(backend, [SPEECH] * 15, t0=0.0)
    feed_frames(backend, silence_run(0.8), t0=t)
    drain(backend, second, expected=1)
    backend.stop(flush_timeout_s=1.0)

    assert [e.text for e in second.finals] == ["second"]


def test_span_buffer_cap_cannot_disable_the_forced_cut() -> None:
    """`MAX_SPAN_BYTES` stops the buffer growing; it must not stop the clock.

    With duration measured from `len(audio)`, a `max_span_s` above the byte cap freezes
    the measured duration below the threshold and the forced cut never fires again — a
    memory-safety cap silently switching off FR47's monologue guarantee.
    """
    backend = LocalWhisperBackend(
        transcriber=FakeTranscriber(),
        max_span_s=15.0,
        max_queued_frames=4_000,
    )
    recorder = start(backend)
    try:
        feed_frames(backend, [SPEECH] * 900)  # 18 s, no silence anywhere
        drain(backend, recorder, expected=1)
        assert len(recorder.finals) >= 1
    finally:
        backend.close()
