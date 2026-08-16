"""WASAPI loopback + mic capture (FR5, FR6) and the bounded frame queue (FR33, FR45).

The capture device half is Windows-only and lands in M1 on the target machine. The
**queue** is platform-free and lands here now, because T6.6's backpressure criterion
depends on it and the design puts it in this module (§1's layout is normative — T0.1
requires the tree to match it, so no new module was invented for this).

`pyaudiowpatch` is imported lazily so this module imports on any platform. Without
that, every test touching backpressure would need a Windows machine to run.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from interview_prep_recall.audio.devices import DeviceKind, render_device_for

FRAME_MS = 20
SAMPLE_RATE = 16_000
CHANNELS = 1
FRAME_BYTES = SAMPLE_RATE * CHANNELS * 2 * FRAME_MS // 1000
FRAME_S = FRAME_MS / 1000

PA_CONTINUE = 0
"""PortAudio's `paContinue`, as a literal.

The callback must not import the vendor module to build its return value: that import
fails everywhere except Windows, so the one line guaranteed to run on every callback
would have raised on any machine used to test the rest of it. The value is part of
PortAudio's stable ABI."""
"""640 bytes: 20 ms of 16 kHz mono int16 (design §1a)."""

QUEUE_FRAMES = 150
"""3 s of jitter buffer. Design §1a — frames, not chunks.

The distinction matters: at 3 *chunks* this would be ~60 ms and overflow continuously;
at 3 frames it would be 60 ms of buffer. Overflow drops 20 ms, never a question.
"""

FALLING_BEHIND_FRAMES = 120
"""80% full. Design §9's detection threshold for the `falling behind` indicator."""


class BoundedFrameQueue:
    """Drop-oldest bounded queue between the capture callback and the STT pump.

    Drop-oldest rather than drop-newest is deliberate: when the pipeline falls behind,
    the *recent* audio is the question being asked now. Discarding it to preserve
    stale audio would surface a match for a question already moved past.

    The callback side must never block (FR45, p99 < 2 ms), so `push` takes the lock
    only long enough to append.
    """

    def __init__(self, maxlen: int = QUEUE_FRAMES) -> None:
        if maxlen < 1:
            raise ValueError("maxlen must be >= 1")
        self._frames: deque[tuple[bytearray, float]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._dropped = 0
        self.maxlen = maxlen

    def push(self, frame: bytes | bytearray, t_capture: float) -> bool:
        """Store a frame. Returns False if this push evicted an older frame.

        **Always stores an independent `bytearray` copy**, whatever it is handed. Two
        separate reasons, and each alone would be sufficient:

        * `zero()` cannot wipe immutable `bytes`, so storing them would make FR15's
          audio-erasure guarantee silently false.
        * WASAPI callbacks reuse a scratch buffer. Holding the caller's `bytearray` by
          reference would let the next callback overwrite a frame already queued —
          silent audio corruption that would surface as unexplained transcription
          errors, with nothing pointing back here.

        FR45 already specifies that the callback copies the frame in, so this is the
        stated behaviour rather than an added cost.
        """
        buf = bytearray(frame)
        with self._lock:
            evicted = len(self._frames) == self.maxlen
            if evicted:
                self._dropped += 1
            self._frames.append((buf, t_capture))
        return not evicted

    def pop(self) -> tuple[bytearray, float] | None:
        with self._lock:
            return self._frames.popleft() if self._frames else None

    def drain(self) -> list[tuple[bytearray, float]]:
        with self._lock:
            out = list(self._frames)
            self._frames.clear()
            return out

    def zero(self) -> int:
        """Purge step 2 (FR15): drain and overwrite the audio bytes.

        Audio is the largest and most sensitive residue and, unlike transcript text, it
        is genuinely zeroable — `push` guarantees every stored frame is a `bytearray`.

        Returns the number of frames **actually wiped**, not the number present. An
        earlier version returned the queue length regardless, so a frame it had failed
        to zero was still reported as erased — the exact shape of defect this project
        keeps producing, where the report is true and the property is not.
        """
        with self._lock:
            wiped = 0
            for frame, _ in self._frames:
                for i in range(len(frame)):
                    frame[i] = 0
                wiped += 1
            self._frames.clear()
            self._dropped = 0
        return wiped

    @property
    def depth(self) -> int:
        with self._lock:
            return len(self._frames)

    @property
    def dropped(self) -> int:
        with self._lock:
            return self._dropped

    @property
    def falling_behind(self) -> bool:
        return self.depth >= FALLING_BEHIND_FRAMES

    def __len__(self) -> int:
        return self.depth


def _load_pyaudiowpatch() -> Any:
    """Lazy, so this module imports on Linux where the package cannot install."""
    import pyaudiowpatch  # noqa: PLC0415

    return pyaudiowpatch


class FormatConverter:
    """Device format → the pipeline's format: 16 kHz mono `int16` (design §1a).

    **Runs in the capture callback**, which design §1a specifies deliberately: it keeps a
    single format in every queue downstream, and `soxr` on a 20 ms frame costs tens of
    microseconds against FR45's 2 ms budget. Doing it in a worker instead would mean
    every queue and every backend had to know the device's rate.

    Two conversions, in this order:

    1. **Downmix to mono** by averaging channels. Loopback endpoints are almost always
       stereo, and taking one channel instead would silence anything panned away from it.
    2. **Resample to 16 kHz.** Whisper and every cloud backend want 16 kHz; WASAPI gives
       whatever the endpoint is set to, usually 44.1 or 48 kHz.

    Averaging is done in int32 and then divided: summing two int16 samples near full
    scale overflows int16, and numpy would wrap silently rather than raise — loud audio
    would come out quiet and wrong, which is the kind of failure that looks like a bad
    microphone.
    """

    def __init__(self, source_rate: int, channels: int, target_rate: int = SAMPLE_RATE) -> None:
        if source_rate <= 0 or channels <= 0:
            raise ValueError(f"bad device format: {source_rate} Hz, {channels} channels")
        self.source_rate = source_rate
        self.channels = channels
        self.target_rate = target_rate
        self._resampler: Any | None = None

    @property
    def needs_resampling(self) -> bool:
        return self.source_rate != self.target_rate

    def _ensure_resampler(self) -> Any:
        """A **stateful** `soxr` stream, not a one-shot call.

        `soxr.resample` on each frame independently would restart the filter every 20 ms
        and put a discontinuity at every frame boundary — an audible buzz at 50 Hz, and
        worse, a transcript degraded in a way that looks like a bad model rather than a
        bad pipeline.
        """
        if self._resampler is None:
            import soxr  # noqa: PLC0415 — Windows-only dependency, lazy by design

            self._resampler = soxr.ResampleStream(
                self.source_rate, self.target_rate, 1, dtype="int16"
            )
        return self._resampler

    def convert(self, raw: bytes) -> bytes:
        """One device buffer → mono 16 kHz PCM bytes."""
        samples = np.frombuffer(raw, dtype=np.int16)
        if self.channels > 1:
            usable = len(samples) - (len(samples) % self.channels)
            frames = samples[:usable].reshape(-1, self.channels)
            mono = (frames.astype(np.int32).sum(axis=1) // self.channels).astype(np.int16)
        else:
            mono = samples
        if not self.needs_resampling:
            passthrough: bytes = mono.tobytes()
            return passthrough
        out = self._ensure_resampler().resample_chunk(mono)
        converted: bytes = np.asarray(out, dtype=np.int16).tobytes()
        return converted


class FrameAssembler:
    """Cuts a stream of arbitrary-length buffers into exact 20 ms frames.

    Necessary because the device's buffer size and ours do not divide evenly once
    resampling is involved: 48 kHz → 16 kHz on a 480-sample buffer gives 160 samples,
    but the driver is free to hand over short or long buffers, and `soxr` returns a
    variable count per chunk. Contract rule 8 says backends receive **exactly**
    `FRAME_BYTES`, so something has to own the remainder — this does.
    """

    def __init__(self, frame_bytes: int = FRAME_BYTES) -> None:
        self.frame_bytes = frame_bytes
        self._buffer = bytearray()

    def push(self, pcm: bytes) -> list[bytes]:
        self._buffer.extend(pcm)
        frames: list[bytes] = []
        while len(self._buffer) >= self.frame_bytes:
            frames.append(bytes(self._buffer[: self.frame_bytes]))
            del self._buffer[: self.frame_bytes]
        return frames

    @property
    def pending_bytes(self) -> int:
        return len(self._buffer)


@dataclass
class CaptureStream:
    """One WASAPI capture endpoint feeding a `BoundedFrameQueue` (T1.1, T1.2).

    **Executed on the target machine on 2026-08-16** (M1), after being written entirely
    from documentation. Both endpoints opened and ran concurrently at 100% delivery, which
    is the first half of **AS-2**. The run also found the defect the `keep_alive` field
    documents — an idle loopback endpoint delivers nothing rather than silence — which no
    amount of reading the vendor docs had suggested.

    **The callback does the minimum.** Convert, cut into frames, push, return. No
    allocation beyond the conversion, no logging, no locks held across work — FR45 gives
    it a p99 of 2 ms, and everything downstream is designed around that being true.
    """

    stream_id: str
    queue: BoundedFrameQueue
    device: Any
    """A `DeviceInfo`. Typed loosely so tests can pass a stand-in; the module imports
    `devices` directly for the keep-alive, and no cycle exists — `devices` imports only
    the standard library."""

    pa: Any = None
    """The `pyaudiowpatch.PyAudio` handle. Injected so the caller owns its lifetime —
    one handle is shared by both streams, and terminating it under a live stream is a
    crash in the C layer rather than an exception."""

    keep_alive: bool = True
    """Hold a silent render stream open on a loopback endpoint while capturing (D-68).

    Measured on the target machine during M1: a WASAPI loopback endpoint with nothing
    playing delivers **no callbacks at all** — 0 frames in 6 s — rather than frames of
    silence. With a silent render stream open on the same endpoint, the same 6 s yields
    298 of 300 expected frames.

    That is a correctness matter, not a metrics one. `EnergyVad` closes an utterance after
    700 ms of silence and learns silence *from frames*; with none arriving, an
    interviewer's question stays open until `max_span_s` force-cuts it 10 s later, and
    every downstream gap measured from `t_end` moves with it.

    Ignored for microphone devices, which stream continuously on their own. Settable only
    so a test can turn it off."""

    clock: Callable[[], float] = time.monotonic
    """Capture-side monotonic clock. Contract rule 5: every downstream timestamp derives
    from this, never from wall time or arrival time."""

    def __post_init__(self) -> None:
        self._converter = FormatConverter(self.device.sample_rate, self.device.channels)
        self._assembler = FrameAssembler()
        self._stream: Any = None
        self._keep_alive_stream: Any = None
        self._keep_alive_error: BaseException | None = None
        self._callback_count = 0
        self._error: BaseException | None = None

    @property
    def frames_delivered(self) -> int:
        return self._callback_count

    @property
    def keep_alive_active(self) -> bool:
        """Whether the silence keep-alive is currently holding the endpoint producing.

        Exposed rather than asserted internally so a change that stops wiring it fails a
        test instead of degrading an interview — the same answer `wired_purge_hooks()`
        gives for hooks that default to reporting success.
        """
        return self._keep_alive_stream is not None

    @property
    def keep_alive_error(self) -> BaseException | None:
        """Why the keep-alive could not open, if it could not.

        Capture still runs without it: no keep-alive costs utterance boundaries during
        silence, whereas refusing to open the device costs the interview.
        """
        return self._keep_alive_error

    @property
    def _wants_keep_alive(self) -> bool:
        return self.keep_alive and getattr(self.device, "kind", None) is DeviceKind.LOOPBACK

    @property
    def error(self) -> BaseException | None:
        """The last callback exception, if any. Surfaced rather than raised: an exception
        escaping a PortAudio callback crosses a C boundary and takes the process."""
        return self._error

    def start(self) -> None:
        pa = self.pa or _load_pyaudiowpatch().PyAudio()
        module = _load_pyaudiowpatch()
        # **Before** the capture stream, not after: the endpoint has to be producing by
        # the time capture opens, or the first frames of the session are the ones lost.
        if self._wants_keep_alive:
            self._start_keep_alive(pa, module)
        # Ask the driver for ~20 ms at *its* rate. The exact count does not matter —
        # `FrameAssembler` owns the remainder — but a buffer near our frame size keeps
        # latency low without waking the callback needlessly often.
        frames_per_buffer = max(1, int(self.device.sample_rate * FRAME_MS / 1000))
        self._stream = pa.open(
            format=module.paInt16,
            channels=self.device.channels,
            rate=self.device.sample_rate,
            input=True,
            input_device_index=self.device.index,
            frames_per_buffer=frames_per_buffer,
            stream_callback=self._callback,
            # `open()` defaults to `start=True`, and calling `start_stream()` on an
            # already-running stream raises `paStreamIsNotStopped`. Opening stopped and
            # starting explicitly keeps the two-phase shape — the callback is wired before
            # any audio can arrive — without that error. Found by review on PR #19.
            start=False,
        )
        self._stream.start_stream()

    def stop(self) -> None:
        """Close the device and **discard everything buffered**.

        Two reasons, and either alone would be sufficient. Restarting the same stream
        would otherwise prepend the previous session's partial frame and resume a resampler
        primed on old audio — the new interview would open with a fragment of the last
        one. And FR16's purge means audio must not survive in memory past the session that
        captured it; a `bytearray` held on a stopped stream is exactly that.
        """
        stream, self._stream = self._stream, None
        keep_alive, self._keep_alive_stream = self._keep_alive_stream, None
        try:
            if stream is not None:
                try:
                    stream.stop_stream()
                finally:
                    stream.close()
        finally:
            try:
                # **After** the capture stream. Closing the keep-alive first would let the
                # endpoint go idle while capture is still open — the exact defect the
                # keep-alive exists to prevent, reproduced during teardown.
                if keep_alive is not None:
                    try:
                        keep_alive.stop_stream()
                    finally:
                        keep_alive.close()
            finally:
                self._assembler = FrameAssembler()
                self._converter = FormatConverter(self.device.sample_rate, self.device.channels)

    def _start_keep_alive(self, pa: Any, module: Any) -> None:
        """Open a silent render stream on the endpoint this loopback shadows.

        Failure is recorded rather than raised: capture without a keep-alive still
        transcribes, and `keep_alive_error` is what the diagnostics surface reads.
        """
        self._keep_alive_error = None
        try:
            render = render_device_for(pa, self.device)
            channels = render.channels

            def _silence(
                in_data: bytes | None, frame_count: int, time_info: dict[str, Any], status: int
            ) -> tuple[bytes, int]:
                return (b"\x00" * (frame_count * channels * 2), PA_CONTINUE)

            stream = pa.open(
                format=module.paInt16,
                channels=channels,
                rate=render.sample_rate,
                output=True,
                output_device_index=render.index,
                frames_per_buffer=max(1, int(render.sample_rate * FRAME_MS / 1000)),
                stream_callback=_silence,
                # Same two-phase shape as the capture stream: `open()` defaults to
                # `start=True`, and `start_stream()` on a running stream raises.
                start=False,
            )
            stream.start_stream()
        except Exception as exc:  # noqa: BLE001 — see the docstring
            self._keep_alive_error = exc
            self._keep_alive_stream = None
            return
        self._keep_alive_stream = stream

    # ---------- the callback ----------

    def _callback(
        self, in_data: bytes, frame_count: int, time_info: dict[str, Any], status: int
    ) -> tuple[bytes | None, int]:
        """PortAudio callback. **Must not raise** — an exception here crosses into C.

        Returns `(None, paContinue)`; the tuple shape is PortAudio's, and the first
        element is only meaningful for output streams.
        """
        try:
            t_capture = self.clock()
            frames = self._assembler.push(self._converter.convert(in_data))
            # Frames from one callback are **not** simultaneous: they are consecutive
            # 20 ms spans. Stamping them all with the arrival time collapses their
            # timeline, which shows up downstream as early `t_end` values, mis-anchored
            # cloud clocks and echo windows compared against the wrong instant. Found by
            # review on PR #19; a long driver buffer is explicitly supported, so this is
            # a normal path rather than an edge case.
            for offset, frame in enumerate(frames):
                self.queue.push(frame, t_capture + offset * FRAME_S)
                self._callback_count += 1
        except BaseException as exc:  # noqa: BLE001 — see the docstring
            self._error = exc
        return (None, PA_CONTINUE)
