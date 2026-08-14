"""Local faster-whisper backend with VAD-synthesised finalisation (T2.2 — FR18, FR47).

This is the **default** backend (FR18): the one that runs when the user has entered no
API key, which is the configuration the product is actually shipped in. Everything the
cloud backends do to stay honest about privacy — the egress indicator, the local-only
switch — exists because this path is the baseline they depart from.

**The problem this module exists to solve.** Whisper is not a streaming model. It
transcribes a finite buffer and returns; there is no wire protocol, no interim result,
and above all no *final* marker. Contract rule 2 nevertheless demands that every
acknowledged span produce exactly one `is_final=True` event or a transition to FAILED.
Nothing in `faster-whisper` will supply that, so this backend synthesises it: a
voice-activity detector watches the frame stream, and a span is closed — and inference
run — at **≥700 ms of silence** or **10 s maximum span**, whichever comes first
(design §2). D-2 put the interface ahead of any backend precisely so this constraint
shaped the contract rather than being bolted onto a cloud-shaped one afterwards.

**What "acknowledged" means here, exactly.** A span is acknowledged when the VAD opens
it — that is, when speech is detected. Frames of silence that never open a span are not
a span and carry no finalisation obligation; if they did, every quiet second of an
interview would owe an event. This distinction is the whole of rule 2's applicability
to this backend, so it is stated rather than left to be inferred from the code.

**A span that transcribes to nothing still emits its final.** The VAD can open on a
cough or a door. Whisper then returns empty text, and the tempting move is to drop the
event. That would make rule 2 false in exactly the way this codebase keeps finding:
the guarantee's test still passes (all *other* spans finalise) while a span the backend
acknowledged vanished. So the empty final is emitted, and `UtteranceAssembler` discards
it downstream on its own word/character floor, where dropping text is that component's
declared job.

**Inference is injected, not imported.** `Transcriber` is a Protocol with a lazy
`FasterWhisperTranscriber` default — the same shape as `Cipher`, `Embedder` and
`Connector` elsewhere. Everything this module is actually responsible for (the VAD, the
span state machine, FR47 finalisation, capture-clock timestamps, backpressure, the
threading) is then testable without a model file, which matters more than usual here:
see **AS-9**, the model has never been loaded in this environment because the network
policy denies `huggingface.co`.

Threads and queues, not asyncio (D-1). Unlike `CloudSttBackend` there is no socket, no
reconnect and no event loop, so the shared plumbing is deliberately *not* reused —
lifting a common base out of two backends whose only overlap is "bounded deque plus a
worker thread" would couple the default path to the opt-in one for no gain.
"""

from __future__ import annotations

import math
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from interview_prep_recall.diagnostics.ring import DiagnosticRing
from interview_prep_recall.stt.interface import (
    CHANNELS,
    FRAME_BYTES,
    SAMPLE_RATE,
    OnState,
    OnTranscript,
    StateEvent,
    SttStreamState,
    TranscriptEvent,
)

FRAME_S = FRAME_BYTES / (SAMPLE_RATE * 2)
"""0.02. Seconds of audio in one frame."""

SILENCE_HANG_S = 0.700
"""FR47's finalisation boundary. Matches `UtteranceAssembler.SILENCE_GAP_S` by design:
the assembler closes an utterance on the same 700 ms, so a shorter value here would
split one utterance into spans it then rejoins, and a longer one would let the assembler
close before the backend had finalised."""

MAX_SPAN_S = 10.0
"""Force inference on a speaker who never pauses. Without it the overlay waits for a
monologue to end, which is the case where help is most needed."""

ONSET_FRAMES = 2
"""Consecutive speech frames before a span opens: 40 ms. One frame is a click, a key
press or a desk knock, and opening on it costs a whole inference pass."""

MAX_QUEUED_FRAMES = 500
"""10 seconds. Larger than the cloud backends' 5 s because the stall being absorbed here
is a *slow inference pass* — an expected, recurring event on CPU — rather than a sick
socket. Bounded regardless: `feed()` may never block (rule 1) and nothing may grow with
session length (FR33)."""

DROP_REPORT_EVERY = 50
"""One DEGRADED report per second of dropped audio after the first, as in `cloud`."""

MAX_SPAN_BYTES = int((MAX_SPAN_S + SILENCE_HANG_S + 1.0) * SAMPLE_RATE * 2)
"""Hard ceiling on the span buffer. The span state machine already bounds it at
`MAX_SPAN_S` plus the silence tail; this is the belt to that pair of braces, so a bug in
the state machine cannot turn into unbounded memory growth over a two-hour interview."""

JOIN_GRACE_S = 0.5

ABS_FLOOR_RMS = 120.0
"""Absolute speech threshold in int16 RMS units (~ -49 dBFS).

Below this, nothing is treated as speech no matter how quiet the room. It is what stops
a perfectly silent digital stream — a muted mic, a loopback device with no audio — from
having its noise floor collapse toward zero until dither registers as talking.
"""

MIN_NOISE_RMS = 30.0
NOISE_MARGIN = 3.0
NOISE_ALPHA = 0.05
"""Adaptive floor: silence updates a slow EMA, and speech must exceed `NOISE_MARGIN`
times it. Tracks a noisy room without needing the user to configure anything."""


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    confidence: float | None = None


class Transcriber(Protocol):
    """One blocking inference pass over a finite PCM buffer.

    Deliberately the narrowest possible surface. Everything Whisper-shaped lives behind
    it, so this module's real content — VAD, finalisation, timestamps, threading — is
    exercised in tests by a double, on a machine that cannot download a model.
    """

    def transcribe(self, pcm: bytes, sample_rate: int) -> TranscriptionResult: ...


class FasterWhisperTranscriber:
    """The real adapter. Thin on purpose, and **never executed in this environment**.

    See AS-9: the container's network policy denies `huggingface.co`, so the model has
    never been downloaded and this class has never transcribed anything. It is written
    from the `faster-whisper` API documentation, exactly as the Deepgram and ElevenLabs
    protocol adapters were written from vendor docs under AS-8. Treat the argument names
    and the `Segment` field names below as the unverified part; the code above and around
    it is not.
    """

    def __init__(
        self,
        model_size: str = "small.en",
        *,
        device: str = "cpu",
        compute_type: str = "int8",
        beam_size: int = 1,
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size
        self._model: Any | None = None

    def _ensure_model(self) -> Any:
        """Loaded on first use, not in `__init__`.

        Constructing the backend must stay cheap and side-effect free: the settings UI
        builds one to ask its `name`, and a constructor that pulled a gigabyte from the
        network would make that a download.
        """
        if self._model is None:
            from faster_whisper import WhisperModel  # noqa: PLC0415 — lazy by design

            self._model = WhisperModel(
                self.model_size, device=self.device, compute_type=self.compute_type
            )
        return self._model

    def transcribe(self, pcm: bytes, sample_rate: int) -> TranscriptionResult:
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = self._ensure_model().transcribe(
            audio,
            language="en",
            beam_size=self.beam_size,
            # The backend's own VAD already chose this span. Letting faster-whisper's
            # bundled Silero re-cut it would mean two detectors disagreeing about where
            # the span ends, and the one that owns the FR47 guarantee is this one.
            vad_filter=False,
        )
        parts: list[str] = []
        logprobs: list[float] = []
        for segment in segments:
            parts.append(segment.text)
            logprob = getattr(segment, "avg_logprob", None)
            if logprob is not None:
                logprobs.append(float(logprob))
        confidence = None
        if logprobs:
            confidence = math.exp(sum(logprobs) / len(logprobs))
        return TranscriptionResult(text=" ".join(parts).strip(), confidence=confidence)


def _rms(pcm: bytes) -> float:
    """Int16 RMS. numpy rather than `audioop`, which is deprecated in 3.12 (and this
    project turns DeprecationWarning into an error) and removed in 3.13.

    Accumulated in float64: squaring int16 samples overflows int16, and the same
    calculation in the array's own dtype silently returns a small wrong number rather
    than failing — which would read as silence during the loudest speech.
    """
    # An odd byte count cannot be int16 samples. Rule 8 says it cannot happen, but this
    # runs on the worker thread where the alternative to trimming is a ValueError that
    # takes the whole stream to FAILED over one malformed frame.
    usable = len(pcm) - (len(pcm) % 2)
    if usable == 0:
        return 0.0
    samples = np.frombuffer(pcm[:usable], dtype=np.int16).astype(np.float64)
    return float(np.sqrt(np.mean(samples * samples)))


class EnergyVad:
    """Per-frame speech detection by RMS energy against an adaptive noise floor.

    **This is the weakest component in the module and is documented as such.** Energy
    alone cannot tell speech from a fan, a keyboard or the interviewer's dog, and on the
    loopback stream it cannot tell speech from notification chimes. It is here because
    it has no model to download, no extra dependency, and completely deterministic
    behaviour under test — which is what lets FR47's guarantee be verified rather than
    asserted.

    **Upgrade path:** `silero-vad`, which ships inside `faster-whisper` (design §10
    lists it as a dependency for exactly this). Swapping it in is a change to this class
    only; `LocalWhisperBackend` asks nothing of a detector beyond `is_speech(frame)`.
    """

    def __init__(self) -> None:
        self._noise = ABS_FLOOR_RMS

    def is_speech(self, pcm: bytes) -> bool:
        rms = _rms(pcm)
        threshold = max(ABS_FLOOR_RMS, self._noise * NOISE_MARGIN)
        if rms > threshold:
            return True
        # Only silence updates the floor. Adapting on speech would chase the speaker's
        # own level upward until they had to shout to stay detected.
        self._noise = max(MIN_NOISE_RMS, self._noise + NOISE_ALPHA * (rms - self._noise))
        return False


@dataclass
class _Span:
    """One acknowledged region of speech, accumulating until finalisation."""

    audio: bytearray
    t_start: float
    t_speech_end: float
    """Capture time at the end of the last **speech** frame.

    Not the end of the buffer. The trailing silence is fed to Whisper because clipping a
    word's decay hurts accuracy, but it must not appear in the event's `t_end` — the
    assembler measures inter-utterance gaps from that field, and 700 ms of padding on
    every span would suppress the gap that closes utterances.
    """

    silence_s: float = 0.0
    frames: int = 1
    """Frames accepted into this span, whether or not they fit in `audio`.

    The span's duration is counted here rather than measured from `len(audio)`, because
    `MAX_SPAN_BYTES` can stop the buffer growing. Deriving duration from a buffer that
    has stopped growing freezes it below `max_span_s`, and the forced cut — the thing
    that guarantees a non-stop speaker still gets finalised — would never fire again.
    A safety cap must not be able to switch off a guarantee.
    """

    @property
    def duration(self) -> float:
        return self.frames * FRAME_S


class LocalWhisperBackend:
    """`SttBackend` over a blocking `Transcriber`. Satisfies the contract structurally;
    `tests/conformance.py` is what proves it."""

    name = "local-whisper"
    supports_interim = False
    """Whisper produces nothing until the buffer is complete. Rule 3 explicitly permits
    this, which is why the matching pipeline was built to trigger only on finals."""

    def __init__(
        self,
        transcriber: Transcriber | None = None,
        *,
        vad: EnergyVad | None = None,
        ring: DiagnosticRing | None = None,
        max_queued_frames: int = MAX_QUEUED_FRAMES,
        silence_hang_s: float = SILENCE_HANG_S,
        max_span_s: float = MAX_SPAN_S,
    ) -> None:
        self._transcriber = FasterWhisperTranscriber() if transcriber is None else transcriber
        self._vad = EnergyVad() if vad is None else vad
        # `is None`, never `or`: `DiagnosticRing` defines `__len__`, so an empty injected
        # ring is falsy and `or` would silently discard it (D-26).
        self.ring = DiagnosticRing() if ring is None else ring
        self._silence_hang_s = silence_hang_s
        self._max_span_s = max_span_s

        self._pending: deque[tuple[bytes, float]] = deque(maxlen=max_queued_frames)
        self._wake = threading.Event()
        self._stopping = threading.Event()

        self._stream_id = ""
        self._thread: threading.Thread | None = None
        self._on_transcript: OnTranscript | None = None
        self._on_state: OnState | None = None
        self._closed = False
        self._dropped = 0
        self._onset = 0
        self._span: _Span | None = None
        self._last_emitted_start = float("-inf")
        self._degraded = False

    # ---------- SttBackend ----------

    def start(
        self,
        stream_id: str,
        sample_rate: int,
        channels: int,
        on_transcript: OnTranscript,
        on_state: OnState,
    ) -> None:
        if sample_rate != SAMPLE_RATE or channels != CHANNELS:
            # Raised, not coerced. Resampling silently would put the VAD's thresholds and
            # every derived timestamp on the wrong time base, and the resulting transcript
            # would look plausible while being wrong about when everything was said.
            raise ValueError(
                f"{self.name} requires {SAMPLE_RATE} Hz mono; got {sample_rate} Hz, "
                f"{channels} channel(s)"
            )
        self._stream_id = stream_id
        self._on_transcript = on_transcript
        self._on_state = on_state
        self._closed = False
        self._stopping.clear()
        self._wake.clear()
        self._dropped = 0
        self._degraded = False
        # Every per-session variable is reset here, and `_last_emitted_start` is the one
        # that matters. `FallbackSttBackend` restarts a backend mid-interview; the new
        # session's capture clock is not guaranteed to resume above the old one's last
        # timestamp, and a stale high-water mark would make the rule-4 ordering guard
        # discard every event of the new session. The stream would report READY and stay
        # permanently silent — the same failure `CaptureClock.reset` exists to prevent,
        # in the other backend.
        self._last_emitted_start = float("-inf")
        self._pending.clear()
        self._span = None
        self._onset = 0
        self._vad = EnergyVad()
        self._emit_state(SttStreamState.STARTING)

        self._thread = threading.Thread(
            target=self._worker, name=f"local-stt-{stream_id}", daemon=True
        )
        self._thread.start()
        self._emit_state(SttStreamState.READY)

    def feed(self, pcm: bytes, t_capture: float) -> None:
        """Enqueue one frame. Never blocks, never raises (contract rule 1).

        Runs on the audio callback under FR45's 2 ms budget. The VAD is *not* evaluated
        here — cheap as it is, inference happens on the same worker and keeping one
        thread responsible for the span state machine is what makes it lock-free.
        """
        if self._closed or self._stopping.is_set():
            return
        if len(self._pending) == self._pending.maxlen:
            self._dropped += 1
            if self._dropped == 1 or self._dropped % DROP_REPORT_EVERY == 0:
                self._degraded = True
                self._emit_state(SttStreamState.DEGRADED, f"dropped {self._dropped} frames")
        self._pending.append((pcm, t_capture))
        self._wake.set()

    def stop(self, flush_timeout_s: float = 2.0) -> None:
        """Drain, finalise any open span, then STOPPED (contract rule 6).

        The flush is the part that matters. An open span at `stop()` is the last thing
        the user said before the interview ended — frequently the answer they most want
        in the report — and abandoning it would drop a span the backend acknowledged,
        which rule 2 forbids in the one place nobody would notice.
        """
        if self._thread is None:
            self._emit_state(SttStreamState.STOPPED)
            return
        self._stopping.set()
        self._wake.set()
        self._thread.join(timeout=flush_timeout_s + JOIN_GRACE_S)
        alive = self._thread.is_alive()

        if alive:
            # The worker is stuck inside an inference pass. Its span will never finalise,
            # so rule 2's alternative applies and is stated plainly.
            self._emit_state(
                SttStreamState.FAILED,
                "worker did not stop within the timeout; callbacks detached",
            )
        self._emit_state(SttStreamState.STOPPED)

        # Detached after every state above is delivered, and unconditionally. A worker
        # that outlived its timeout must not be able to reach a consumer that has been
        # told the stream is over.
        self._on_transcript = None
        self._on_state = None
        self._thread = None

    def close(self) -> None:
        """Idempotent (contract rule 6)."""
        if self._closed:
            return
        self._closed = True
        if self._thread is not None:
            self.stop(flush_timeout_s=0.5)
        self._pending.clear()
        self._span = None

    # ---------- worker ----------

    def _worker(self) -> None:
        try:
            while True:
                self._wake.wait(timeout=0.05)
                self._wake.clear()
                self._drain()
                if self._stopping.is_set() and not self._pending:
                    break
            # Flush whatever the last frames left open. Rule 2's guarantee for the final
            # span of the session lives on this one line.
            self._finalise("stop")
        except Exception as exc:  # noqa: BLE001 — the thread must not die silently
            self._emit_state(SttStreamState.FAILED, type(exc).__name__)

    def _drain(self) -> None:
        while self._pending:
            try:
                pcm, t_capture = self._pending.popleft()
            except IndexError:  # pragma: no cover — only `feed` appends; defensive
                return
            self._consume(pcm, t_capture)

    def _consume(self, pcm: bytes, t_capture: float) -> None:
        speech = self._vad.is_speech(pcm)
        frame_end = t_capture + FRAME_S

        if self._span is None:
            if not speech:
                # Silence outside a span is not an acknowledged span (see module docs)
                # and carries no finalisation obligation. Onset counting resets so that
                # two speech frames must be *consecutive*.
                self._onset = 0
                return
            self._onset += 1
            if self._onset < ONSET_FRAMES:
                return
            self._onset = 0
            self._span = _Span(audio=bytearray(pcm), t_start=t_capture, t_speech_end=frame_end)
            return

        span = self._span
        span.frames += 1
        if len(span.audio) < MAX_SPAN_BYTES:
            span.audio.extend(pcm)
        if speech:
            span.silence_s = 0.0
            span.t_speech_end = frame_end
        else:
            span.silence_s += FRAME_S

        if span.silence_s >= self._silence_hang_s:
            self._finalise("silence")
        elif span.duration >= self._max_span_s:
            # Forced cut mid-speech. The next span opens on the following speech frame
            # with a sub-700 ms gap, so `UtteranceAssembler` rejoins the two halves into
            # one utterance — which only works because `t_speech_end` is exact.
            self._finalise("max_span")

    def _finalise(self, reason: str) -> None:
        """Run inference on the open span and emit exactly one final event."""
        span, self._span = self._span, None
        if span is None:
            return
        try:
            result = self._transcriber.transcribe(bytes(span.audio), SAMPLE_RATE)
        except Exception as exc:  # noqa: BLE001 — one bad span must not end the session
            # Rule 2 allows a final *or* FAILED, and this is the FAILED branch: the span
            # is accounted for, loudly. The stream keeps accepting audio, because a
            # single failed inference pass is not a reason to go deaf for the rest of an
            # interview; a subsequent successful span re-reports READY.
            self.ring.record("stt_inference_failed", stream=self._label, cause=type(exc).__name__)
            self._emit_state(SttStreamState.FAILED, f"inference failed: {type(exc).__name__}")
            self._degraded = True
            return

        text = result.text.strip()
        if not text:
            # Emitted anyway. See the module docstring: swallowing this is how rule 2
            # becomes false while its tests stay green.
            self.ring.record("stt_empty_span", stream=self._label, reason=reason)

        self._emit_transcript(
            TranscriptEvent(
                stream_id=self._stream_id,
                text=text,
                is_final=True,
                t_start=span.t_start,
                t_end=span.t_speech_end,
                confidence=result.confidence,
                backend=self.name,
            )
        )
        if self._degraded:
            self._degraded = False
            self._emit_state(SttStreamState.READY, f"recovered after {reason}")

    # ---------- emission ----------

    @property
    def _label(self) -> str:
        """Never empty: the ring rejects empty strings, and `stop()` before `start()` is
        legal (rule 6), so the guard would turn a legal call into a crash."""
        return self._stream_id[:64] or "unstarted"

    def _emit_state(self, state: SttStreamState, detail: str | None = None) -> None:
        self.ring.record("stt_state", state=state.name, stream=self._label)
        if self._on_state is not None:
            self._on_state(StateEvent(stream_id=self._stream_id, state=state, detail=detail))

    def _emit_transcript(self, event: TranscriptEvent) -> None:
        # Rule 4: non-decreasing `t_start` per stream. Spans are sequential by
        # construction here, so this should never fire — which is the reason to keep it
        # and record it rather than assume it: if the construction ever stops holding,
        # the alternative is silently corrupted utterance boundaries.
        if event.t_start < self._last_emitted_start:
            self.ring.record("stt_out_of_order", stream=self._label)
            return
        self._last_emitted_start = event.t_start
        if self._on_transcript is not None:
            self._on_transcript(event)
