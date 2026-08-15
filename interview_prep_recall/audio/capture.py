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

FRAME_MS = 20
SAMPLE_RATE = 16_000
CHANNELS = 1
FRAME_BYTES = SAMPLE_RATE * CHANNELS * 2 * FRAME_MS // 1000
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

    **Never executed.** `pyaudiowpatch` has no Linux distribution and this container has
    no sound subsystem, so every line below is written from documentation — this is
    **AS-2**, the project's oldest and riskiest assumption, and M1 is the gate that
    settles it. The parts that are ours (`FormatConverter`, `FrameAssembler`, the queue)
    are tested; the `open()` call is not.

    **The callback does the minimum.** Convert, cut into frames, push, return. No
    allocation beyond the conversion, no logging, no locks held across work — FR45 gives
    it a p99 of 2 ms, and everything downstream is designed around that being true.
    """

    stream_id: str
    queue: BoundedFrameQueue
    device: Any
    """A `DeviceInfo`. Typed loosely to avoid a circular import with `devices`."""

    pa: Any = None
    """The `pyaudiowpatch.PyAudio` handle. Injected so the caller owns its lifetime —
    one handle is shared by both streams, and terminating it under a live stream is a
    crash in the C layer rather than an exception."""

    clock: Callable[[], float] = time.monotonic
    """Capture-side monotonic clock. Contract rule 5: every downstream timestamp derives
    from this, never from wall time or arrival time."""

    def __post_init__(self) -> None:
        self._converter = FormatConverter(self.device.sample_rate, self.device.channels)
        self._assembler = FrameAssembler()
        self._stream: Any = None
        self._callback_count = 0
        self._error: BaseException | None = None

    @property
    def frames_delivered(self) -> int:
        return self._callback_count

    @property
    def error(self) -> BaseException | None:
        """The last callback exception, if any. Surfaced rather than raised: an exception
        escaping a PortAudio callback crosses a C boundary and takes the process."""
        return self._error

    def start(self) -> None:
        pa = self.pa or _load_pyaudiowpatch().PyAudio()
        module = _load_pyaudiowpatch()
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
        )
        self._stream.start_stream()

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            stream.stop_stream()
        finally:
            stream.close()

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
            for frame in self._assembler.push(self._converter.convert(in_data)):
                self.queue.push(frame, t_capture)
                self._callback_count += 1
        except BaseException as exc:  # noqa: BLE001 — see the docstring
            self._error = exc
        return (None, _load_pyaudiowpatch().paContinue)
