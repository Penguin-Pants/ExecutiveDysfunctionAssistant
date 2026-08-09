"""T0.5 — credential storage (FR19)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from interview_prep_recall.diagnostics.ring import DiagnosticContentError, DiagnosticRing
from interview_prep_recall.platform.credentials import (
    SERVICE_NAME,
    CredentialStore,
    InMemoryCredentialBackend,
)

SECRET = "sk-ant-test-000111222333444555666777888999"


def test_round_trip(credentials: CredentialStore) -> None:
    credentials.set("anthropic", SECRET)
    assert credentials.get("anthropic") == SECRET
    assert credentials.has("anthropic")


def test_delete(credentials: CredentialStore) -> None:
    credentials.set("deepgram", SECRET)
    credentials.delete("deepgram")
    assert credentials.get("deepgram") is None
    assert not credentials.has("deepgram")


def test_unknown_account_rejected(credentials: CredentialStore) -> None:
    with pytest.raises(ValueError, match="unknown credential account"):
        credentials.set("openai", SECRET)


def test_empty_secret_rejected(credentials: CredentialStore) -> None:
    with pytest.raises(ValueError, match="empty secret"):
        credentials.set("anthropic", "   ")


def test_anthropic_key_is_covered_by_fr19() -> None:
    """The stage-2 matching key is a credential like any other, not a config value."""
    store = CredentialStore(backend=InMemoryCredentialBackend())
    store.set("anthropic", SECRET)
    assert store.get("anthropic") == SECRET


def test_storing_a_key_arms_the_diagnostic_guard() -> None:
    """A key is short and whitespace-free, so the ring cannot spot it unaided.

    This is the wiring that turns FR19's diagnostic clause from a convention into a
    guarantee: the store tells the ring what to refuse.
    """
    ring = DiagnosticRing()
    ring.record("llm_call", code=SECRET)  # accepted: guard not yet armed

    store = CredentialStore(backend=InMemoryCredentialBackend(), ring=ring)
    store.set("anthropic", SECRET)

    with pytest.raises(DiagnosticContentError, match="registered secret"):
        ring.record("llm_call", code=SECRET)
    with pytest.raises(DiagnosticContentError, match="registered secret"):
        ring.record("llm_call", reason=f"Bearer{SECRET}")


def test_guard_survives_purge() -> None:
    ring = DiagnosticRing()
    CredentialStore(backend=InMemoryCredentialBackend(), ring=ring).set("anthropic", SECRET)
    ring.clear()
    with pytest.raises(DiagnosticContentError):
        ring.record("llm_call", code=SECRET)


def test_repr_never_leaks_the_secret(credentials: CredentialStore) -> None:
    credentials.set("anthropic", SECRET)
    assert SECRET not in repr(credentials)
    assert SERVICE_NAME == "InterviewPrepRecall"


def test_secret_absent_from_app_data_and_diagnostics(
    credentials: CredentialStore, app_data: Path
) -> None:
    """FR19's grep test, in miniature: key in neither the data dir nor an export."""
    credentials.set("anthropic", SECRET)

    (app_data / "config.json").write_text(
        json.dumps({"llm_model_id": "claude-haiku-4-5-20251001", "backend": "local"})
    )

    ring = DiagnosticRing()
    CredentialStore(backend=InMemoryCredentialBackend(), ring=ring).set("anthropic", SECRET)
    ring.record("llm_call", status=200, latency_ms=512.0)
    with pytest.raises(DiagnosticContentError):
        ring.record("llm_call", code=SECRET)

    for path in app_data.rglob("*"):
        if path.is_file():
            assert SECRET not in path.read_text()
    assert SECRET not in json.dumps(ring.export())
