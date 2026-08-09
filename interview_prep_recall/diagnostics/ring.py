"""In-memory diagnostic ring buffer (FR36).

Records *structural* events only — timestamps, component states, latencies, error
codes, match/no-match decisions. Never transcript text and never note content.

The no-content guarantee is enforced structurally rather than by convention: field
values must be scalars, and string values must be short and free of whitespace. Any
transcript utterance or note body contains spaces and is rejected at the call site,
so a well-meaning `ring.record("match", question=utterance.text)` raises instead of
silently leaking. That is the difference between a rule and a guarantee — the safety
review's recurring finding was tests that confirm a claim rather than the property.

The buffer is never written to disk automatically (FR16). `export()` returns a
structure the *user* may choose to save (FR36).
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

DEFAULT_CAPACITY = 2000
"""T0.3. Bounded so a long session cannot grow memory (NFR5)."""

MAX_STR_LEN = 64

_SAFE_STR = re.compile(r"^[A-Za-z0-9_.:/\-]+$")
"""Identifiers, enum names, UUIDs, error codes, paths. Notably: no whitespace.

This pattern rejects prose — transcripts and note bodies contain spaces. It does NOT
reject credential-shaped strings, which are short and unbroken by design. That gap is
covered separately by `register_secret`: an API key looks exactly like a note ID to a
character-class check, so the guard has to be told what the secrets are.
"""

_ALLOWED_SCALARS = (bool, int, float)


class DiagnosticContentError(ValueError):
    """Raised when a field value could contain session content.

    Deliberately an error and not a warning. A dropped diagnostic is a nuisance; a
    transcript in an exportable buffer is a privacy failure (FR36).
    """


def _validate(key: str, value: Any, secrets: frozenset[str] = frozenset()) -> None:
    if value is None or isinstance(value, _ALLOWED_SCALARS):
        return
    if isinstance(value, str):
        for secret in secrets:
            if secret in value:
                raise DiagnosticContentError(
                    f"field {key!r} contains a registered secret. Credentials never enter "
                    "diagnostics (FR19)."
                )
        if len(value) > MAX_STR_LEN:
            raise DiagnosticContentError(
                f"field {key!r} is {len(value)} chars (max {MAX_STR_LEN}). "
                "Diagnostics record structure, not content."
            )
        if not _SAFE_STR.match(value):
            raise DiagnosticContentError(
                f"field {key!r} contains whitespace or unsafe characters. "
                "Transcript and note text must never enter the ring buffer."
            )
        return
    raise DiagnosticContentError(
        f"field {key!r} has type {type(value).__name__}; only bool/int/float/str/None allowed."
    )


@dataclass(frozen=True)
class DiagnosticEvent:
    t_monotonic: float
    t_wall: float
    event: str
    fields: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "t_monotonic": round(self.t_monotonic, 6),
            "t_wall": self.t_wall,
            "event": self.event,
            **self.fields,
        }


class DiagnosticRing:
    """Bounded, thread-safe, content-free event ring.

    Thread-safe because it is written from every thread in design §8 — capture
    callbacks, STT pumps, the matching worker, the watchdog — and read from the Qt
    main thread by the T5.8 viewer.
    """

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self._capacity = capacity
        self._events: deque[DiagnosticEvent] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._dropped = 0
        self._secrets: frozenset[str] = frozenset()

    def register_secret(self, secret: str) -> None:
        """Reject any future field containing this value (FR19).

        Called by CredentialStore whenever a key is loaded or stored. Without it, a
        credential passes every other check in this module: it has no whitespace and
        is well under the length cap, so it is indistinguishable from a note ID.
        """
        if secret and secret.strip():
            with self._lock:
                self._secrets = self._secrets | {secret}

    @property
    def capacity(self) -> int:
        return self._capacity

    def record(self, event: str, **fields: Any) -> DiagnosticEvent:
        """Append a structural event. Raises DiagnosticContentError on unsafe values."""
        with self._lock:
            secrets = self._secrets
        _validate("event", event, secrets)
        for key, value in fields.items():
            _validate(key, value, secrets)

        entry = DiagnosticEvent(
            t_monotonic=time.monotonic(), t_wall=time.time(), event=event, fields=dict(fields)
        )
        with self._lock:
            if len(self._events) == self._capacity:
                self._dropped += 1
            self._events.append(entry)
        return entry

    def snapshot(self) -> list[DiagnosticEvent]:
        with self._lock:
            return list(self._events)

    def export(self) -> dict[str, Any]:
        """User-initiated export payload (FR36). Callers write it; the ring never does."""
        with self._lock:
            events = [e.as_dict() for e in self._events]
            dropped = self._dropped
        return {
            "schema_version": 1,
            "capacity": self._capacity,
            "dropped_before_export": dropped,
            "events": events,
        }

    def clear(self) -> None:
        """Called on session purge (FR15). Diagnostics are session-scoped."""
        with self._lock:
            self._events.clear()
            self._dropped = 0
            # Registered secrets deliberately survive a purge: the credential is still
            # loaded, so the guard must stay armed for the next session.

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)
