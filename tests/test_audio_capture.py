"""M1 — capture-stream behaviour that needs no device (PR #19 review findings)."""

from __future__ import annotations

from typing import Any

import pytest

from interview_prep_recall.audio.capture import (
    FRAME_BYTES,
    FRAME_S,
    SAMPLE_RATE,
    BoundedFrameQueue,
    CaptureStream,
)
from interview_prep_recall.audio.devices import DeviceInfo, DeviceKind


def _device(rate: int = SAMPLE_RATE, channels: int = 1) -> DeviceInfo:
    return DeviceInfo(
        index=0, name="Fake", kind=DeviceKind.LOOPBACK, channels=channels, sample_rate=rate
    )


def _stream(**kwargs: Any) -> tuple[CaptureStream, BoundedFrameQueue]:
    queue = BoundedFrameQueue(maxlen=500)
    stream = CaptureStream(
        stream_id="interviewer", queue=queue, device=_device(**kwargs), clock=lambda: 100.0
    )
    return stream, queue


def test_frames_from_one_callback_get_consecutive_timestamps() -> None:
    """Frames from a single callback are consecutive 20 ms spans, not simultaneous.

    Stamping them all with the arrival time collapses their timeline, which surfaces
    downstream as early `t_end` values, mis-anchored cloud clocks and echo windows
    compared against the wrong instant. Long driver buffers are an explicitly supported
    path, so this is a normal case rather than an edge one.
    """
    stream, queue = _stream()

    stream._callback(b"\x00" * (FRAME_BYTES * 3), 0, {}, 0)  # noqa: SLF001

    stamps = [t for _frame, t in queue.drain()]
    assert stamps == pytest.approx([100.0, 100.0 + FRAME_S, 100.0 + 2 * FRAME_S])


def test_a_single_frame_keeps_the_arrival_timestamp() -> None:
    stream, queue = _stream()
    stream._callback(b"\x00" * FRAME_BYTES, 0, {}, 0)  # noqa: SLF001
    assert [t for _f, t in queue.drain()] == [100.0]


def test_the_callback_never_imports_the_vendor_module() -> None:
    """The one line guaranteed to run on every callback must not depend on an import that
    fails everywhere except Windows — otherwise no machine used to test the rest of the
    pipeline could run it at all."""
    stream, queue = _stream()
    result = stream._callback(b"\x00" * FRAME_BYTES, 0, {}, 0)  # noqa: SLF001
    assert result == (None, 0)
    assert stream.error is None


def test_stop_discards_buffered_audio() -> None:
    """Restarting would otherwise open the new interview with a fragment of the last one,
    and FR16's purge means audio must not outlive the session that captured it."""
    stream, _queue = _stream()
    partial = b"\x01" * (FRAME_BYTES - 4)
    stream._callback(partial, 0, {}, 0)  # noqa: SLF001
    assert stream._assembler.pending_bytes == len(partial)  # noqa: SLF001

    stream.stop()

    assert stream._assembler.pending_bytes == 0  # noqa: SLF001


def test_stop_is_safe_before_start() -> None:
    stream, _queue = _stream()
    stream.stop()


def test_a_callback_exception_is_recorded_not_raised() -> None:
    """An exception escaping a PortAudio callback crosses into C and takes the process."""
    stream, _queue = _stream(channels=2)

    result = stream._callback(b"\x00" * 3, 0, {}, 0)  # noqa: SLF001

    assert result == (None, 0)
