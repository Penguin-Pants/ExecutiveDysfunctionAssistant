"""T2.1 — the STT contract itself is checkable before any backend exists."""

from __future__ import annotations

from interview_prep_recall.stt.interface import (
    CHANNELS,
    FRAME_BYTES,
    SAMPLE_RATE,
    SttBackend,
    SttStreamState,
    TranscriptEvent,
)


class NullBackend:
    """Minimal conforming backend. Proves the Protocol is satisfiable as written."""

    name = "null"
    supports_interim = False

    def __init__(self) -> None:
        self.fed = 0

    def start(self, stream_id, sample_rate, channels, on_transcript, on_state) -> None:  # type: ignore[no-untyped-def]
        on_state(
            __import__("interview_prep_recall.stt.interface", fromlist=["StateEvent"]).StateEvent(
                stream_id=stream_id, state=SttStreamState.READY, detail=None
            )
        )

    def feed(self, pcm: bytes, t_capture: float) -> None:
        self.fed += 1

    def stop(self, flush_timeout_s: float = 2.0) -> None:
        pass

    def close(self) -> None:
        pass


def test_frame_size_matches_the_audio_contract() -> None:
    """Design §1a: 20 ms of 16 kHz mono int16."""
    assert SAMPLE_RATE == 16_000
    assert CHANNELS == 1
    assert FRAME_BYTES == 640


def test_null_backend_satisfies_the_protocol() -> None:
    backend: SttBackend = NullBackend()
    assert backend.name == "null"
    backend.feed(b"\x00" * FRAME_BYTES, 0.0)
    backend.stop()
    backend.close()


def test_transcript_event_is_immutable() -> None:
    """Events cross threads (rule 7); mutable ones would be a data race."""
    import dataclasses

    event = TranscriptEvent(
        stream_id="interviewer",
        text="hello",
        is_final=True,
        t_start=0.0,
        t_end=1.0,
        confidence=None,
        backend="null",
    )
    try:
        event.text = "changed"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("TranscriptEvent must be frozen")
