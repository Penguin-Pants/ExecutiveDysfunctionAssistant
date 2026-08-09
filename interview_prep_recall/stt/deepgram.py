"""Deepgram streaming backend (T8.1 — FR17, FR18, FR19).

Protocol specifics only. Everything structural — the loop, the bounded queue, the
capture-clock mapping, the finalisation guarantee — lives in `cloud.py` and is shared
with ElevenLabs, so both pass the same conformance suite unmodified. That equivalence
is the whole point of D-2's interface, and it is only meaningful if the two backends
share no protocol code and all of the plumbing.
"""

from __future__ import annotations

from urllib.parse import urlencode

from interview_prep_recall.stt.cloud import CloudSttBackend, Connector
from interview_prep_recall.stt.interface import CHANNELS, SAMPLE_RATE, TranscriptEvent

ENDPOINT = "wss://api.deepgram.com/v1/listen"

DEFAULT_PARAMS = {
    "encoding": "linear16",
    "sample_rate": str(SAMPLE_RATE),
    "channels": str(CHANNELS),
    "model": "nova-2",
    "interim_results": "true",
    "punctuate": "true",
}


def endpoint_url(params: dict[str, str] | None = None) -> str:
    return f"{ENDPOINT}?{urlencode({**DEFAULT_PARAMS, **(params or {})})}"


def websocket_connector(api_key: str, params: dict[str, str] | None = None) -> Connector:
    """A real socket connector. Imported lazily so `[dev]` installs need no `websockets`.

    The key travels in the `Authorization` header, never in the query string — a URL
    is the single most likely thing to reach a log line or a diagnostic export, which
    is precisely what FR19 forbids.
    """

    async def connect():  # type: ignore[no-untyped-def]
        import websockets

        return await websockets.connect(
            endpoint_url(params),
            additional_headers={"Authorization": f"Token {api_key}"},
        )

    return connect


class DeepgramBackend(CloudSttBackend):
    name = "deepgram"
    supports_interim = True

    def build_finalise_message(self) -> str:
        """Asks Deepgram to flush pending finals before the socket closes.

        Without it, `stop()` would close on a partial span and the last utterance of
        every session would be lost — a rule 2 violation that only shows up at the end
        of a real interview, which is the worst possible place to discover it.
        """
        return '{"type": "CloseStream"}'

    def parse(self, message: bytes | str) -> list[TranscriptEvent]:
        payload = self.loads(message)
        if payload.get("type") not in (None, "Results"):
            return []
        alternatives = payload.get("channel", {}).get("alternatives", [])
        if not alternatives:
            return []
        best = alternatives[0]
        text = (best.get("transcript") or "").strip()
        if not text:
            # Deepgram emits empty transcripts during silence. They are not spans and
            # must not reach the assembler, which would treat them as speech.
            return []
        start = float(payload.get("start", 0.0))
        duration = float(payload.get("duration", 0.0))
        confidence = best.get("confidence")
        return [
            self.make_event(
                text,
                is_final=bool(payload.get("is_final", False)),
                server_start=start,
                server_end=start + duration,
                confidence=float(confidence) if confidence is not None else None,
            )
        ]
