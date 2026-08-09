"""API key storage via Windows Credential Manager (FR19).

Moved forward from M8 to M0 (T0.5): M4's stage-2 selector needs an Anthropic key, so
credentials cannot first appear alongside the cloud STT backends.

Keys are never written to a config file, a log, or a diagnostic export. The store is
a thin wrapper over `keyring` so tests can substitute an in-memory backend without
touching the real credential vault — and so the Linux dev container, which has no
Credential Manager, can exercise everything except the OS binding itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from interview_prep_recall.diagnostics.ring import DiagnosticRing

SERVICE_NAME = "InterviewPrepRecall"
"""Design §4. Account is the backend name: deepgram | elevenlabs | anthropic."""

KNOWN_ACCOUNTS = frozenset({"deepgram", "elevenlabs", "anthropic"})


class CredentialBackend(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...
    def set_password(self, service: str, username: str, password: str) -> None: ...
    def delete_password(self, service: str, username: str) -> None: ...


class InMemoryCredentialBackend:
    """Test double. Also the fallback on platforms with no credential vault.

    Deliberately not persisted anywhere: a file-backed fallback would violate FR19 on
    exactly the platforms where nobody is watching for it.
    """

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self._store.pop((service, username), None)


def _default_backend() -> CredentialBackend:
    try:
        import keyring  # noqa: PLC0415  (optional, Windows-only dependency)

        backend: CredentialBackend = keyring
        return backend
    except Exception:
        return InMemoryCredentialBackend()


class CredentialStore:
    """Reads and writes API keys, and arms the diagnostic guard against them.

    Pass the session's DiagnosticRing so every key this store touches is registered
    as a forbidden diagnostic value. A credential is short and whitespace-free, so it
    is indistinguishable from a note ID to the ring's character-class check — the ring
    has to be told. Without this wiring FR19's "never in a diagnostic export" would be
    a convention rather than a guarantee.
    """

    def __init__(
        self,
        backend: CredentialBackend | None = None,
        ring: DiagnosticRing | None = None,
    ) -> None:
        self._backend = backend if backend is not None else _default_backend()
        self._ring = ring

    @staticmethod
    def _check(account: str) -> None:
        if account not in KNOWN_ACCOUNTS:
            raise ValueError(
                f"unknown credential account {account!r}; expected {sorted(KNOWN_ACCOUNTS)}"
            )

    def get(self, account: str) -> str | None:
        self._check(account)
        secret = self._backend.get_password(SERVICE_NAME, account)
        self._arm(secret)
        return secret

    def set(self, account: str, secret: str) -> None:
        self._check(account)
        if not secret or not secret.strip():
            raise ValueError("refusing to store an empty secret")
        self._backend.set_password(SERVICE_NAME, account, secret)
        self._arm(secret)

    def _arm(self, secret: str | None) -> None:
        if secret and self._ring is not None:
            self._ring.register_secret(secret)

    def delete(self, account: str) -> None:
        self._check(account)
        self._backend.delete_password(SERVICE_NAME, account)

    def has(self, account: str) -> bool:
        return self.get(account) is not None

    def __repr__(self) -> str:
        # Never render secrets, even accidentally via a debugger or an exception
        # traceback. FR19's grep test covers files; this covers stdout.
        return f"<CredentialStore backend={type(self._backend).__name__}>"
