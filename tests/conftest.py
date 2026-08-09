"""Shared fixtures, including the T0.4 write-allowlist guard.

The guard is autouse and active from M0, deliberately. The universal definition of
done says every task must show no writes outside the design §4 allowlist; scoping
that to "once the M6 harness lands" would have left it unverifiable for the first six
milestones, which is most of the project. T6.4's Process Monitor trace is the
full-system check against a packaged build; this is the per-test one.
"""

from __future__ import annotations

import builtins
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from interview_prep_recall.diagnostics.ring import DiagnosticRing
from interview_prep_recall.platform.credentials import (
    CredentialStore,
    InMemoryCredentialBackend,
)

_WRITE_MODES = frozenset("wxa+")


def _is_write_mode(mode: str) -> bool:
    return any(ch in _WRITE_MODES for ch in mode)


def _allowed_roots() -> list[Path]:
    """Paths a test may legitimately write to.

    Everything the application itself writes lives under a tmp-path-backed app data
    directory in tests, so this list is about tooling, not product behaviour.
    """
    roots = [Path(tempfile.gettempdir()).resolve()]
    repo = Path(__file__).resolve().parent.parent
    # pytest/coverage bookkeeping inside the repo.
    roots += [repo / ".pytest_cache", repo / "htmlcov", repo / ".coverage"]
    for env in ("PYTEST_DEBUG_TEMPROOT", "TMPDIR"):
        if os.environ.get(env):
            roots.append(Path(os.environ[env]).resolve())
    return roots


class WriteOutsideAllowlist(AssertionError):
    """A test wrote somewhere design §4 does not permit."""


@pytest.fixture(autouse=True)
def write_allowlist(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    roots = _allowed_roots()
    real_open = builtins.open
    real_os_open = os.open

    def _check(path: object) -> None:
        try:
            resolved = Path(os.fspath(path)).resolve()  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return  # file descriptors and exotic objects are not paths
        for root in roots:
            try:
                resolved.relative_to(root)
                return
            except ValueError:
                continue
        raise WriteOutsideAllowlist(
            f"write to {resolved} is outside the design §4 allowlist.\n"
            "Application writes belong under the app data directory; tests should use tmp_path."
        )

    def guarded_open(file, mode="r", *args, **kwargs):  # type: ignore[no-untyped-def]
        if isinstance(mode, str) and _is_write_mode(mode):
            _check(file)
        return real_open(file, mode, *args, **kwargs)

    def guarded_os_open(path, flags, *args, **kwargs):  # type: ignore[no-untyped-def]
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND):
            _check(path)
        return real_os_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(os, "open", guarded_os_open)
    yield


@pytest.fixture
def ring() -> DiagnosticRing:
    return DiagnosticRing()


@pytest.fixture
def credentials(ring: DiagnosticRing) -> CredentialStore:
    return CredentialStore(backend=InMemoryCredentialBackend(), ring=ring)


@pytest.fixture
def app_data(tmp_path: Path) -> Path:
    """A throwaway %APPDATA%\\InterviewPrepRecall equivalent."""
    root = tmp_path / "InterviewPrepRecall"
    root.mkdir()
    return root
