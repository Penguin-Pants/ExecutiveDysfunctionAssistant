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
from collections.abc import Callable
from dataclasses import dataclass, field
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

MODEL_SIZE_DEFAULT = "base.en"
"""Design §"Pinned versions". **This is the model AS-1 is measured against**, which is why
it is not a free choice: `small.en` is the configured upgrade *if T2.4 shows headroom* and
`tiny.en` the fallback if it does not, so shipping anything else as the default would mean
the recorded latency result described a model no user actually runs."""

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
        model_size: str = MODEL_SIZE_DEFAULT,
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


class SpeechDetector(Protocol):
    """All the backend asks of a voice-activity detector.

    One method, so swapping `EnergyVad` for `silero-vad` touches nothing else. Detectors
    are stateful (an adaptive noise floor), so the backend takes a **factory** and builds
    a fresh one per session rather than reusing one instance across interviews.
    """

    def is_speech(self, pcm: bytes) -> bool: ...


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


@dataclass
class _Session:
    """Everything one interview owns. See `LocalWhisperBackend`'s docstring for why this
    is a separate object rather than a set of attributes on the backend."""

    stream_id: str
    on_transcript: OnTranscript | None
    on_state: OnState | None
    vad: SpeechDetector
    pending: deque[tuple[bytes, float]]
    wake: threading.Event = field(default_factory=threading.Event)
    stopping: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    span: _Span | None = None
    onset: list[tuple[bytes, float]] = field(default_factory=list)
    """Frames held while the VAD confirms speech onset, so they can be prepended to the
    span rather than thrown away."""

    last_emitted_start: float = float("-inf")
    dropped: int = 0
    degraded: bool = False


def _label(session: _Session | None) -> str:
    """Stream id for diagnostics. Never empty: the ring rejects empty strings, and
    `stop()` before `start()` is legal (rule 6), so the guard would turn a legal call
    into a crash."""
    if session is None:
        return "unstarted"
    return session.stream_id[:64] or "unstarted"


class LocalWhisperBackend:
    """`SttBackend` over a blocking `Transcriber`. Satisfies the contract structurally;
    `tests/conformance.py` is what proves it.

    **All mutable per-interview state lives in `_Session`, not on the backend.** That is
    not tidiness. `stop()` can return while a worker is still inside an inference pass —
    the timeout branch says so explicitly — and if that worker shared its stop flag,
    queue, callbacks and ordering high-water mark with the backend, then restarting would
    hand the *old* worker the *new* session: it would emit the previous interview's
    transcript under the new `stream_id`, raise the new ordering mark past every real
    event, and race the new worker for its queue. Giving each session its own object
    makes that structurally impossible instead of relying on a flag nobody re-checks.
    """

    name = "local-whisper"
    supports_interim = False
    """Whisper produces nothing until the buffer is complete. Rule 3 explicitly permits
    this, which is why the matching pipeline was built to trigger only on finals."""

    def __init__(
        self,
        transcriber: Transcriber | None = None,
        *,
        vad_factory: Callable[[], SpeechDetector] = EnergyVad,
        ring: DiagnosticRing | None = None,
        max_queued_frames: int = MAX_QUEUED_FRAMES,
        silence_hang_s: float = SILENCE_HANG_S,
        max_span_s: float = MAX_SPAN_S,
    ) -> None:
        self._transcriber = FasterWhisperTranscriber() if transcriber is None else transcriber
        # A factory, not an instance. A detector carries an adaptive noise floor tuned to
        # one room on one stream, so it must be rebuilt per session — but rebuilding a
        # *caller's* object means constructing `EnergyVad()` and silently discarding
        # whatever they injected, which is D-26's defect wearing different clothes.
        self._vad_factory = vad_factory
        # `is None`, never `or`: `DiagnosticRing` defines `__len__`, so an empty injected
        # ring is falsy and `or` would silently discard it (D-26).
        self.ring = DiagnosticRing() if ring is None else ring
        self._max_queued_frames = max_queued_frames
        self._silence_hang_s = silence_hang_s
        self._max_span_s = max_span_s
        self._session: _Session | None = None

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
        # A fresh session object *is* the reset. There is no list of fields to remember to
        # clear, so none can be forgotten — which is how `_last_emitted_start` survived a
        # restart in the first version of this file.
        session = _Session(
            stream_id=stream_id,
            on_transcript=on_transcript,
            on_state=on_state,
            vad=self._vad_factory(),
            pending=deque(maxlen=self._max_queued_frames),
        )
        self._session = session
        self._emit_state(session, SttStreamState.STARTING)
        session.thread = threading.Thread(
            target=self._worker, args=(session,), name=f"local-stt-{stream_id}", daemon=True
        )
        session.thread.start()
        self._emit_state(session, SttStreamState.READY)

    def feed(self, pcm: bytes, t_capture: float) -> None:
        """Enqueue one frame. Never blocks, never raises (contract rule 1).

        Runs on the audio callback under FR45's 2 ms budget. The VAD is *not* evaluated
        here — cheap as it is, inference happens on the same worker and keeping one
        thread responsible for the span state machine is what makes it lock-free.
        """
        session = self._session
        if session is None or session.stopping.is_set():
            return
        if len(session.pending) == session.pending.maxlen:
            session.dropped += 1
            if session.dropped == 1 or session.dropped % DROP_REPORT_EVERY == 0:
                session.degraded = True
                self._emit_state(
                    session, SttStreamState.DEGRADED, f"dropped {session.dropped} frames"
                )
        session.pending.append((pcm, t_capture))
        session.wake.set()

    def stop(self, flush_timeout_s: float = 2.0) -> None:
        """Drain, finalise any open span, then STOPPED (contract rule 6).

        The flush is the part that matters. An open span at `stop()` is the last thing
        the user said before the interview ended — frequently the answer they most want
        in the report — and abandoning it would drop a span the backend acknowledged,
        which rule 2 forbids in the one place nobody would notice.
        """
        session = self._session
        if session is None or session.thread is None:
            self._emit_state(session, SttStreamState.STOPPED)
            return
        session.stopping.set()
        session.wake.set()
        session.thread.join(timeout=flush_timeout_s + JOIN_GRACE_S)

        if session.thread.is_alive():
            # Stuck inside an inference pass. Its span will never finalise, so rule 2's
            # alternative applies and is stated plainly. The worker keeps running against
            # *this* session object, which the next `start()` will not share.
            self._emit_state(
                session,
                SttStreamState.FAILED,
                "worker did not stop within the timeout; callbacks detached",
            )
        self._emit_state(session, SttStreamState.STOPPED)

        # Detached after every state above is delivered, and unconditionally. A worker
        # that outlived its timeout must not be able to reach a consumer that has been
        # told the stream is over.
        session.on_transcript = None
        session.on_state = None
        self._session = None

    def close(self) -> None:
        """Idempotent (contract rule 6)."""
        session = self._session
        if session is None:
            return
        self.stop(flush_timeout_s=0.5)
        session.pending.clear()
        session.span = None

    # ---------- worker ----------

    def _worker(self, session: _Session) -> None:
        try:
            while True:
                session.wake.wait(timeout=0.05)
                session.wake.clear()
                self._drain(session)
                if session.stopping.is_set() and not session.pending:
                    break
            # Flush whatever the last frames left open. Rule 2's guarantee for the final
            # span of the session lives on this one line.
            self._finalise(session, "stop")
        except Exception as exc:  # noqa: BLE001 — the thread must not die silently
            self._emit_state(session, SttStreamState.FAILED, type(exc).__name__)

    def _drain(self, session: _Session) -> None:
        while session.pending:
            try:
                pcm, t_capture = session.pending.popleft()
            except IndexError:  # pragma: no cover — only `feed` appends; defensive
                return
            self._consume(session, pcm, t_capture)

    def _consume(self, session: _Session, pcm: bytes, t_capture: float) -> None:
        speech = session.vad.is_speech(pcm)
        frame_end = t_capture + FRAME_S

        if session.span is None:
            if not speech:
                # Silence outside a span is not an acknowledged span (see module docs)
                # and carries no finalisation obligation. The provisional buffer clears
                # so that the onset frames must be *consecutive*.
                session.onset.clear()
                return
            # Held, not counted. Discarding the frames that proved speech was starting
            # would clip the first 20 ms of every utterance — the leading phoneme, which
            # is where Whisper is least able to guess — and report a `t_start` late by
            # the same amount.
            session.onset.append((pcm, t_capture))
            if len(session.onset) < ONSET_FRAMES:
                return
            audio = bytearray()
            for frame, _ in session.onset:
                audio.extend(frame)
            session.span = _Span(
                audio=audio,
                t_start=session.onset[0][1],
                t_speech_end=frame_end,
                frames=len(session.onset),
            )
            session.onset.clear()
            return

        span = session.span
        span.frames += 1
        if len(span.audio) < MAX_SPAN_BYTES:
            span.audio.extend(pcm)
        if speech:
            span.silence_s = 0.0
            span.t_speech_end = frame_end
        else:
            span.silence_s += FRAME_S

        if span.silence_s >= self._silence_hang_s:
            self._finalise(session, "silence")
        elif span.duration >= self._max_span_s:
            # Forced cut mid-speech. The next span opens on the following speech frames
            # with a sub-700 ms gap, so `UtteranceAssembler` rejoins the two halves into
            # one utterance — which only works because `t_speech_end` is exact.
            self._finalise(session, "max_span")

    def _finalise(self, session: _Session, reason: str) -> None:
        """Run inference on the open span and emit exactly one final event."""
        span, session.span = session.span, None
        if span is None:
            return
        try:
            result = self._transcriber.transcribe(bytes(span.audio), SAMPLE_RATE)
        except Exception as exc:  # noqa: BLE001 — one bad span must not end the session
            # Rule 2 allows a final *or* FAILED, and this is the FAILED branch: the span
            # is accounted for, loudly. The stream keeps accepting audio, because a
            # single failed inference pass is not a reason to go deaf for the rest of an
            # interview; a subsequent successful span re-reports READY.
            self.ring.record(
                "stt_inference_failed", stream=_label(session), cause=type(exc).__name__
            )
            self._emit_state(
                session, SttStreamState.FAILED, f"inference failed: {type(exc).__name__}"
            )
            session.degraded = True
            return

        text = result.text.strip()
        if not text:
            # Emitted anyway. See the module docstring: swallowing this is how rule 2
            # becomes false while its tests stay green.
            self.ring.record("stt_empty_span", stream=_label(session), reason=reason)

        self._emit_transcript(
            session,
            TranscriptEvent(
                stream_id=session.stream_id,
                text=text,
                is_final=True,
                t_start=span.t_start,
                t_end=span.t_speech_end,
                confidence=result.confidence,
                backend=self.name,
            ),
        )
        if session.degraded:
            session.degraded = False
            self._emit_state(session, SttStreamState.READY, f"recovered after {reason}")

    # ---------- emission ----------

    def _emit_state(
        self, session: _Session | None, state: SttStreamState, detail: str | None = None
    ) -> None:
        self.ring.record("stt_state", state=state.name, stream=_label(session))
        if session is not None and session.on_state is not None:
            session.on_state(StateEvent(stream_id=session.stream_id, state=state, detail=detail))

    def _emit_transcript(self, session: _Session, event: TranscriptEvent) -> None:
        # Rule 4: non-decreasing `t_start` per stream. The high-water mark is per session,
        # so a new interview starting at a lower capture time is not measured against the
        # last one's — which would silently discard every event of the new session.
        if event.t_start < session.last_emitted_start:
            self.ring.record("stt_out_of_order", stream=_label(session))
            return
        session.last_emitted_start = event.t_start
        if session.on_transcript is not None:
            session.on_transcript(event)
