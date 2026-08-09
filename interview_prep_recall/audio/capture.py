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
from collections import deque
from dataclasses import dataclass
from typing import Any

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


@dataclass
class CaptureStream:
    """Placeholder for the M1 device binding. Windows-only; not implemented here."""

    stream_id: str
    queue: BoundedFrameQueue

    def start(self) -> None:
        raise NotImplementedError(
            "WASAPI capture lands in M1 on the Windows target machine (AS-2 gate). "
            "The bounded queue above is platform-free and is implemented."
        )


def _load_pyaudiowpatch() -> Any:
    """Lazy, so this module imports on Linux where the package cannot install."""
    import pyaudiowpatch  # noqa: PLC0415

    return pyaudiowpatch
