"""ElevenLabs streaming backend (T8.2 — FR17, FR18, FR19).

Same shape as `deepgram.py`: protocol only, plumbing inherited. The two differ in
message envelope, in how audio is framed, and in the shape of their timestamps —
ElevenLabs reports absolute start/end rather than start+duration — and in nothing else.
"""

from __future__ import annotations

import base64
import json

from interview_prep_recall.stt.cloud import CloudSttBackend, Connector
from interview_prep_recall.stt.interface import SAMPLE_RATE, TranscriptEvent

ENDPOINT = "wss://api.elevenlabs.io/v1/speech-to-text/stream"


def websocket_connector(api_key: str, model_id: str = "scribe_v1") -> Connector:
    """Lazy import, and the key in a header rather than the URL — see FR19."""

    async def connect():  # type: ignore[no-untyped-def]
        import websockets

        return await websockets.connect(
            f"{ENDPOINT}?model_id={model_id}",
            additional_headers={"xi-api-key": api_key},
        )

    return connect


class ElevenLabsBackend(CloudSttBackend):
    name = "elevenlabs"
    supports_interim = True

    def build_start_message(self) -> str:
        return json.dumps(
            {
                "type": "start",
                "audio_format": {"encoding": "pcm_s16le", "sample_rate": SAMPLE_RATE},
            }
        )

    def build_finalise_message(self) -> str:
        return json.dumps({"type": "end"})

    def parse(self, message: bytes | str) -> list[TranscriptEvent]:
        payload = self.loads(message)
        kind = payload.get("type")
        if kind not in ("transcript", "partial_transcript"):
            return []
        text = (payload.get("text") or "").strip()
        if not text:
            return []
        return [
            self.make_event(
                text,
                is_final=kind == "transcript",
                server_start=float(payload.get("start", 0.0)),
                server_end=float(payload.get("end", payload.get("start", 0.0))),
                confidence=(
                    float(payload["confidence"]) if payload.get("confidence") is not None else None
                ),
            )
        ]

    def encode_frame(self, pcm: bytes) -> bytes | str:
        """Base64 in a JSON envelope, not a binary frame — the one wire-level
        difference from Deepgram, and the reason `encode_frame` is a hook."""
        return json.dumps({"type": "audio", "audio": base64.b64encode(pcm).decode("ascii")})
