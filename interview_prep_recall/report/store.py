"""Encrypted session storage, listing, deletion and retention (T11.2/T11.3 — FR82–FR84).

This is where D-U8's cost is paid. The product's strongest claim used to be that nothing
said or heard reached the disk; a persisted transcript trades that away, and what has to
come back in return is encryption at rest, a list the user can see, deletion they can
actually perform, and a retention default that runs without being asked.

**A third party's words are in these files.** The interviewer did not install this
software. That is the reason the key is bound to the current OS user rather than being
"good enough" ambient protection — a copied file must be inert.

Ciphers are injected through a Protocol, exactly as `CredentialBackend` is. On Windows
the default binds to DPAPI. **Elsewhere there is no default**: this module raises rather
than falling back to something weaker, because a silent downgrade to unencrypted or
obfuscated storage is precisely the kind of false guarantee this codebase keeps having
to dig out of its own tests.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from interview_prep_recall.diagnostics.ring import DiagnosticRing
from interview_prep_recall.notes.model import new_id, validate_id
from interview_prep_recall.report.record import RecordedUtterance, SessionRecord

RETENTION_DAYS_DEFAULT = 30
"""FR84. `None` means never."""

INDEX_NAME = "sessions.index"


class SessionStoreError(Exception):
    pass


class CipherUnavailableError(SessionStoreError):
    """No user-bound cipher on this platform, and none injected.

    Raised rather than degraded. Storing an interview transcript under weaker protection
    than FR82 promises would be a false privacy statement about another person's words.
    """


class Cipher(Protocol):
    """User-bound encryption. On Windows, DPAPI with the current account's key."""

    def encrypt(self, plaintext: bytes) -> bytes: ...
    def decrypt(self, ciphertext: bytes) -> bytes: ...


def default_cipher() -> Cipher:
    """DPAPI on Windows, nothing anywhere else.

    Imported lazily so a Linux dev container can import this module and run every test
    that injects its own cipher — which is all of them except the DPAPI binding itself.
    """
    if os.name != "nt":
        raise CipherUnavailableError(
            "no user-bound cipher outside Windows; inject one explicitly. Session "
            "transcripts are not written unencrypted (FR82)."
        )
    from interview_prep_recall.platform.win_dpapi import DpapiCipher

    return DpapiCipher()


@dataclass(frozen=True)
class SessionSummary:
    """FR83's list row. Deliberately thin — the point of a session list is to let the
    user find and delete a session, not to preview its contents outside the encryption
    boundary."""

    id: str
    stored_at: str
    """When the session was **written**, not when the interview began.

    Named for what it is: the record's timestamps are monotonic-clock seconds with no
    wall-clock origin, so a start time cannot be derived from them. It matters because
    this is the field the retention sweep deletes on, and a field that decides deletion
    must not be named for something it is not measuring.
    """

    role: str
    bytes_stored: int
    has_report: bool


@dataclass(frozen=True)
class StoredSession:
    id: str
    stored_at: str
    role: str
    utterances: tuple[RecordedUtterance, ...]
    report: dict[str, Any] | None
    missed_note_ids: frozenset[str] = frozenset()


def _now() -> datetime:
    return datetime.now(UTC)


class SessionStore:
    def __init__(
        self,
        root: Path,
        cipher: Cipher | None = None,
        ring: DiagnosticRing | None = None,
        retention_days: int | None = RETENTION_DAYS_DEFAULT,
    ) -> None:
        self.root = Path(root)
        self.sessions_dir = self.root / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.cipher = default_cipher() if cipher is None else cipher
        self.ring = DiagnosticRing() if ring is None else ring
        self.retention_days = retention_days

    # ---------- paths ----------

    def transcript_path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{validate_id(session_id, label='session id')}.transcript"

    def report_path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{validate_id(session_id, label='session id')}.report"

    @property
    def index_path(self) -> Path:
        return self.sessions_dir / INDEX_NAME

    # ---------- write ----------

    def save(
        self,
        record: SessionRecord,
        *,
        role: str,
        session_id: str | None = None,
        missed_note_ids: frozenset[str] = frozenset(),
    ) -> str:
        """Persist a transcript. Returns the session id.

        `missed_note_ids` is the **tracker's** coverage verdict, stored alongside the
        spans. It is session state that dies with the session, and FR78a makes it the
        only valid basis for an absence finding — so a report regenerated next week has
        to read it from here or it cannot produce those findings at all, which is half of
        what D-U8 bought.
        """
        sid = session_id or new_id()
        validate_id(sid, label="session id")
        payload = {
            "id": sid,
            "stored_at": _now().isoformat(timespec="seconds").replace("+00:00", "Z"),
            "role": role,
            "missed_note_ids": sorted(missed_note_ids),
            "utterances": [
                {
                    "index": u.index,
                    "stream_id": u.stream_id,
                    "text": u.text,
                    "t_start": u.t_start,
                    "t_end": u.t_end,
                }
                for u in record.utterances
            ],
        }
        self._write_encrypted(self.transcript_path(sid), payload)
        self._reindex()
        self.ring.record("session_stored", session=sid, count=len(record))
        return sid

    def attach_report(self, session_id: str, report: dict[str, Any]) -> None:
        self._write_encrypted(self.report_path(session_id), report)
        self._reindex()

    def _write_encrypted(self, path: Path, payload: dict[str, Any]) -> None:
        blob = self.cipher.encrypt(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "wb") as fh:
            fh.write(blob)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)

    def _read_encrypted(self, path: Path) -> dict[str, Any]:
        parsed = json.loads(self.cipher.decrypt(path.read_bytes()).decode("utf-8"))
        if not isinstance(parsed, dict):
            raise SessionStoreError(f"{path.name} did not decrypt to an object")
        return parsed

    # ---------- read ----------

    def load(self, session_id: str) -> StoredSession:
        data = self._read_encrypted(self.transcript_path(session_id))
        report_path = self.report_path(session_id)
        report = self._read_encrypted(report_path) if report_path.exists() else None
        return StoredSession(
            id=data["id"],
            stored_at=data["stored_at"],
            role=data.get("role", ""),
            utterances=tuple(
                RecordedUtterance(
                    index=u["index"],
                    stream_id=u["stream_id"],
                    text=u["text"],
                    t_start=u["t_start"],
                    t_end=u["t_end"],
                )
                for u in data.get("utterances", [])
            ),
            report=report,
            missed_note_ids=frozenset(data.get("missed_note_ids", [])),
        )

    def list_sessions(self) -> list[SessionSummary]:
        """FR83. Newest first."""
        summaries: list[SessionSummary] = []
        for path in sorted(self.sessions_dir.glob("*.transcript")):
            sid = path.stem
            try:
                data = self._read_encrypted(path)
            except Exception:  # noqa: BLE001 — one unreadable session must not hide the rest
                self.ring.record("session_unreadable", session=sid)
                continue
            report_path = self.report_path(sid)
            summaries.append(
                SessionSummary(
                    id=sid,
                    stored_at=data.get("stored_at", ""),
                    role=data.get("role", ""),
                    bytes_stored=path.stat().st_size
                    + (report_path.stat().st_size if report_path.exists() else 0),
                    has_report=report_path.exists(),
                )
            )
        return sorted(summaries, key=lambda s: s.stored_at, reverse=True)

    # ---------- delete ----------

    def _delete_files(self, session_id: str) -> bool:
        """Unlink both artifacts. No reindex — the caller batches that."""
        removed = False
        for path in (self.transcript_path(session_id), self.report_path(session_id)):
            if path.exists():
                path.unlink()
                removed = True
        return removed

    def delete(self, session_id: str) -> bool:
        """FR83: transcript, report and index entry go together.

        Partial deletion is the failure that matters here. A user who deletes a session
        and leaves the report behind has been told their words are gone while a
        third-party model's characterisation of the interviewer is still on disk.
        """
        removed = self._delete_files(session_id)
        if removed:
            self._reindex()
            self.ring.record("session_deleted", session=session_id)
        return removed

    def delete_all(self) -> int:
        """FR83/FR87. The only route to destroying stored history, and — since the panic
        control no longer destroys anything (D-U11) — the one a user reaching for panic
        actually needs.

        Deletes files first and reindexes **once**. Calling `delete()` per session would
        rebuild the index after each one, and rebuilding decrypts every remaining
        transcript — O(n²) decryptions on the one operation a user runs when they want
        their data gone quickly.
        """
        count = 0
        for session_id in [p.stem for p in self.sessions_dir.glob("*.transcript")]:
            if self._delete_files(session_id):
                count += 1
        # Anything left is an orphaned report whose transcript is already gone.
        for stray in self.sessions_dir.glob("*.report"):
            stray.unlink()
        self._reindex()
        self.ring.record("sessions_deleted_all", count=count)
        return count

    # ---------- retention (FR84) ----------

    def sweep_expired(self, now: datetime | None = None) -> list[str]:
        """Delete sessions past the retention window. Returns the ids removed.

        `retention_days=None` means never, and must genuinely mean never — a sweep that
        treats None as zero would delete everything on the first launch after the user
        chose to keep it all.
        """
        if self.retention_days is None:
            return []
        cutoff = (now or _now()) - timedelta(days=self.retention_days)
        expired: list[str] = []
        for summary in self.list_sessions():
            started = _parse(summary.stored_at)
            if started is not None and started < cutoff:
                self.delete(summary.id)
                expired.append(summary.id)
        if expired:
            self.ring.record("sessions_expired", count=len(expired))
        return expired

    # ---------- index ----------

    def _reindex(self) -> None:
        """The index is derived, encrypted, and never authoritative.

        Rebuilt from the files on every change rather than maintained incrementally, so
        it cannot drift into listing a session that no longer exists or hiding one that
        does. It exists for speed and for FR83's "index entry goes with the delete", not
        as a source of truth.
        """
        rows = [
            {
                "id": s.id,
                "stored_at": s.stored_at,
                "role": s.role,
                "bytes": s.bytes_stored,
                "has_report": s.has_report,
            }
            for s in self.list_sessions()
        ]
        self._write_encrypted(self.index_path, {"sessions": rows})


def _parse(stamp: str) -> datetime | None:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
