"""M1 — device selection, change detection, and format conversion, without a sound card.

`pyaudiowpatch` has no Linux distribution and this container has no sound subsystem, so
the one thing that cannot be tested here is the call that opens a device — **AS-2**, and
M1's spike on the Windows machine is the gate that settles it.

Everything else is ours and is tested: which device gets picked, what counts as a change,
and the format conversion that runs inside the capture callback. That last one matters
most, because a bug there produces audio that is quietly wrong rather than absent — the
failure mode that looks like a bad microphone.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from interview_prep_recall.audio.capture import (
    FRAME_BYTES,
    SAMPLE_RATE,
    FormatConverter,
    FrameAssembler,
)
from interview_prep_recall.audio.devices import (
    DefaultDeviceWatcher,
    DeviceError,
    DeviceKind,
    default_loopback,
    default_microphone,
    describe,
)


def raw_device(index: int, name: str, *, rate: int = 48_000, channels: int = 2) -> dict[str, Any]:
    return {
        "index": index,
        "name": name,
        "maxInputChannels": channels,
        "defaultSampleRate": float(rate),
    }


class FakePyAudio:
    """The slice of `pyaudiowpatch` the device layer touches."""

    def __init__(
        self,
        loopbacks: list[dict[str, Any]] | None = None,
        mic: dict[str, Any] | None = None,
        default_output: dict[str, Any] | None = None,
        *,
        has_convenience_getter: bool = True,
    ) -> None:
        self._loopbacks = loopbacks or []
        self._mic = mic
        self._default_output = default_output
        if has_convenience_getter:
            self.get_default_wasapi_loopback = self._default_wasapi_loopback  # type: ignore[method-assign]

    def _default_wasapi_loopback(self) -> dict[str, Any] | None:
        return self._loopbacks[0] if self._loopbacks else None

    def get_loopback_device_info_generator(self):  # type: ignore[no-untyped-def]
        yield from self._loopbacks

    def get_default_output_device_info(self) -> dict[str, Any]:
        return self._default_output or {}

    def get_default_input_device_info(self) -> dict[str, Any] | None:
        return self._mic


# ---------- selection ----------


def test_default_loopback_uses_the_convenience_getter() -> None:
    pa = FakePyAudio(loopbacks=[raw_device(7, "Speakers (Loopback)")])
    assert default_loopback(pa).index == 7


def test_default_loopback_falls_back_to_a_name_match() -> None:
    """The vendor API is unverified (AS-2). A second route to the same device is cheaper
    than a failed capture on the user's first run."""
    pa = FakePyAudio(
        loopbacks=[raw_device(3, "Headphones (Loopback)"), raw_device(4, "Speakers (Loopback)")],
        default_output={"name": "Speakers"},
        has_convenience_getter=False,
    )
    assert default_loopback(pa).index == 4


def test_no_loopback_device_raises_with_an_actionable_message() -> None:
    pa = FakePyAudio(
        loopbacks=[], default_output={"name": "Speakers"}, has_convenience_getter=False
    )
    with pytest.raises(DeviceError, match="default playback device"):
        default_loopback(pa)


def test_missing_microphone_raises() -> None:
    with pytest.raises(DeviceError, match="microphone"):
        default_microphone(FakePyAudio(mic=None))


def test_describe_returns_the_loopbacks_even_with_no_microphone() -> None:
    """A missing mic is a state FR39b already has to handle, not a reason to withhold
    the devices we did find."""
    pa = FakePyAudio(loopbacks=[raw_device(1, "Speakers (Loopback)")], mic=None)
    found = describe(pa)
    assert [d.kind for d in found] == [DeviceKind.LOOPBACK]


def test_float_sample_rates_become_ints() -> None:
    """PortAudio reports rates as floats. A float here fails a later exact comparison
    against `SAMPLE_RATE` and silently enables resampling that is not needed."""
    pa = FakePyAudio(loopbacks=[raw_device(0, "S", rate=48_000)])
    assert default_loopback(pa).sample_rate == 48_000
    assert isinstance(default_loopback(pa).sample_rate, int)


# ---------- change detection (FR39) ----------


def _watcher(pa: Any) -> tuple[DefaultDeviceWatcher, list[Any]]:
    seen: list[Any] = []
    return DefaultDeviceWatcher(pa, seen.append), seen


def test_priming_reports_nothing() -> None:
    """Otherwise the first poll reports every device as newly appeared and a consumer
    that re-binds on change re-binds immediately at startup."""
    pa = FakePyAudio(loopbacks=[raw_device(1, "Speakers (Loopback)")], mic=raw_device(2, "Mic"))
    watcher, _seen = _watcher(pa)
    watcher.prime()
    assert watcher.poll_once() == []


def test_a_replaced_default_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """FR39a: re-bind automatically and keep the session RUNNING."""
    pa = FakePyAudio(loopbacks=[raw_device(1, "Speakers (Loopback)")], mic=raw_device(2, "Mic"))
    watcher, _seen = _watcher(pa)
    watcher.prime()

    pa._loopbacks = [raw_device(1, "Headphones (Loopback)")]
    changes = watcher.poll_once()

    assert len(changes) == 1
    assert changes[0].kind is DeviceKind.LOOPBACK
    assert changes[0].replaced is True
    assert changes[0].lost is False


def test_a_lost_device_is_reported_as_lost() -> None:
    """FR39b: no replacement. The session pauses rather than dying."""
    pa = FakePyAudio(loopbacks=[raw_device(1, "Speakers (Loopback)")], mic=raw_device(2, "Mic"))
    watcher, _seen = _watcher(pa)
    watcher.prime()

    pa._loopbacks = []
    changes = watcher.poll_once()

    assert len(changes) == 1
    assert changes[0].lost is True


def test_reindexing_is_not_a_change() -> None:
    """PortAudio reindexes when the device list changes, so the same physical device can
    move index. Treating that as a replacement re-binds a stream that was working
    perfectly — mid-interview."""
    pa = FakePyAudio(loopbacks=[raw_device(1, "Speakers (Loopback)")], mic=raw_device(2, "Mic"))
    watcher, _seen = _watcher(pa)
    watcher.prime()

    pa._loopbacks = [raw_device(9, "Speakers (Loopback)")]
    assert watcher.poll_once() == []


def test_an_unchanged_default_is_not_reported_repeatedly() -> None:
    pa = FakePyAudio(loopbacks=[raw_device(1, "Speakers (Loopback)")], mic=raw_device(2, "Mic"))
    watcher, _seen = _watcher(pa)
    watcher.prime()
    assert watcher.poll_once() == []
    assert watcher.poll_once() == []


# ---------- format conversion (design §1a) ----------


def test_stereo_is_downmixed_by_averaging() -> None:
    """Taking one channel instead would silence anything panned away from it."""
    converter = FormatConverter(SAMPLE_RATE, channels=2)
    interleaved = np.array([1000, 3000, -2000, -4000], dtype=np.int16).tobytes()

    mono = np.frombuffer(converter.convert(interleaved), dtype=np.int16)

    assert mono.tolist() == [2000, -3000]


def test_downmix_does_not_overflow_on_loud_audio() -> None:
    """Summing two near-full-scale int16 samples overflows int16, and numpy wraps
    silently rather than raising — loud audio would come out quiet and wrong, which
    looks like a broken microphone rather than a broken pipeline."""
    converter = FormatConverter(SAMPLE_RATE, channels=2)
    loud = np.array([32000, 32000, -32000, -32000], dtype=np.int16).tobytes()

    mono = np.frombuffer(converter.convert(loud), dtype=np.int16)

    assert mono.tolist() == [32000, -32000]


def test_mono_at_the_target_rate_is_a_passthrough() -> None:
    converter = FormatConverter(SAMPLE_RATE, channels=1)
    assert converter.needs_resampling is False
    pcm = np.array([1, -1, 500], dtype=np.int16).tobytes()
    assert converter.convert(pcm) == pcm


def test_a_device_rate_other_than_16k_needs_resampling() -> None:
    assert FormatConverter(48_000, channels=2).needs_resampling is True
    assert FormatConverter(44_100, channels=1).needs_resampling is True


def test_a_bad_device_format_is_rejected() -> None:
    """A device reporting 0 channels or 0 Hz would otherwise produce a converter that
    divides by zero deep inside the capture callback."""
    with pytest.raises(ValueError, match="bad device format"):
        FormatConverter(0, channels=2)
    with pytest.raises(ValueError, match="bad device format"):
        FormatConverter(SAMPLE_RATE, channels=0)


def test_odd_channel_remainders_are_dropped_not_misaligned() -> None:
    """A truncated buffer must not shift every subsequent sample into the wrong channel."""
    converter = FormatConverter(SAMPLE_RATE, channels=2)
    truncated = np.array([100, 200, 300], dtype=np.int16).tobytes()

    mono = np.frombuffer(converter.convert(truncated), dtype=np.int16)

    assert mono.tolist() == [150]


# ---------- frame assembly (contract rule 8) ----------


def test_frames_are_exactly_the_contract_size() -> None:
    assembler = FrameAssembler()
    frames = assembler.push(b"\x00" * (FRAME_BYTES * 3))
    assert len(frames) == 3
    assert all(len(f) == FRAME_BYTES for f in frames)


def test_a_partial_buffer_is_held_not_emitted() -> None:
    """`soxr` returns a variable count per chunk and drivers hand over uneven buffers.
    Emitting a short frame would break contract rule 8 for every backend at once."""
    assembler = FrameAssembler()

    assert assembler.push(b"\x00" * (FRAME_BYTES - 2)) == []
    assert assembler.pending_bytes == FRAME_BYTES - 2

    frames = assembler.push(b"\x00" * 2)
    assert len(frames) == 1
    assert assembler.pending_bytes == 0


def test_assembly_preserves_the_byte_stream_exactly() -> None:
    """Reassembled frames must equal the input, or the transcript is of audio nobody
    played."""
    assembler = FrameAssembler()
    source = bytes(range(256)) * ((FRAME_BYTES * 4) // 256 + 1)

    # Uneven chunk sizes, cycling — the driver and `soxr` both hand over variable counts.
    sizes = [7, 13, 1024, 3, 641]
    out = b""
    position = 0
    step = 0
    while position < len(source):
        size = sizes[step % len(sizes)]
        out += b"".join(assembler.push(source[position : position + size]))
        position += size
        step += 1

    # Everything emitted must be a byte-exact prefix of the input; the remainder is held.
    assert out == source[: len(out)]
    assert len(source) - len(out) == assembler.pending_bytes
