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
import sys
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


@pytest.fixture(scope="session", autouse=True)
def qt_settings_sandbox(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Point `QSettings` at a throwaway directory for the whole test session.

    **Session-scoped, and that is not an optimisation.** `setDefaultFormat` and `setPath`
    are process-global Qt state. Setting and restoring them around every test churns the
    configuration underneath `QSettings` objects created inside a test and destroyed after
    it, which segfaults the interpreter once enough have accumulated — found while adding
    the overlay geometry store, and it cost more to diagnose than the fixture saves.

    The T0.4 guard above cannot see these writes: `QSettings` persists through Qt's C++
    layer, not through Python's `open`, so a test that constructs one and stores a value
    writes to the user's real registry or `~/.config` and the allowlist never fires. That
    is the one hole in an otherwise per-test guarantee, and T5.4 made it reachable —
    `MainWindow` now owns the overlay's geometry store (FR26).

    `IniFormat` is forced because `setPath` has no effect on the native backend, which on
    the Windows target is the registry. Redirecting only the format we do not ship on
    would have looked like protection and provided none.
    """
    try:
        from PySide6.QtCore import QSettings
    except ImportError:  # the [ui] extra is optional; nothing to sandbox without it
        yield
        return

    previous_format = QSettings.defaultFormat()
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(tmp_path_factory.mktemp("qsettings")),
    )
    yield
    QSettings.setDefaultFormat(previous_format)


@pytest.fixture(scope="session")
def qapp() -> Iterator[object]:
    """The one `QApplication` for the test session, **with a teardown**.

    Six test modules each defined their own copy of this and none of them tore anything
    down, which left every widget ever built alive until interpreter shutdown — where Qt
    destroys them in whatever order it likes, after the `QApplication` may already be
    gone. That is an intermittent segfault at exit, and it became reachable once
    `MainWindow` started owning an overlay and a dialog: the suite reported all tests
    passing and then the process died with 139, which on CI is a red build with a green
    test report.

    Closing and deleting the top-level widgets here destroys them **while the application
    is still alive**, which is the ordering Qt actually supports.

    **Only parentless roots are deleted, and never a widget Qt has already destroyed.**
    A `QDialog` parented to a window is *both* a top-level widget and that window's
    child, so a loop that calls `deleteLater` on everything `topLevelWidgets()` returns
    queues a deletion for objects their parent is about to delete on the same pass — a
    double free, which on Windows is an access violation in `processEvents` and on Linux
    is silently survivable. Deleting the roots and letting Qt cascade is the ordering it
    documents; `isValid` guards the wrappers whose C++ object went with an earlier root.

    `hide()` first because `close()` may legitimately be **refused** — `NotesEditor` does
    exactly that when a save was rejected and closing would lose the edits (T3.7) — and
    destroying a *visible* top-level widget is its own hazard. Both were found by CI on
    PR #27, which is the fourth destroy-order defect in this fixture's history (D-53,
    D-54) and the first that only Windows could see.
    """
    from PySide6.QtWidgets import QApplication
    from shiboken6 import isValid

    app = QApplication.instance() or QApplication([])
    yield app
    for widget in list(app.topLevelWidgets()):
        if not isValid(widget) or widget.parent() is not None:
            continue
        widget.hide()
        widget.deleteLater()
    app.processEvents()


@pytest.fixture(autouse=True)
def drain_qt_events():
    """Flush Qt's event queue after every test, **while that test's widgets are alive**.

    An unparented `QDialog` is owned by Python, not by a parent, so it is destroyed the
    instant a test's last reference goes — immediately, not deferred. Anything still
    queued for it is then dispatched against freed memory by whichever test next pumps
    the loop. In this suite that is the overlay's clock test and its two-second
    `processEvents` spin, which is where the segfault landed: a crash whose cause was
    twenty test files earlier.

    Draining here keeps each test's events and its objects inside one lifetime, which is
    the property the session-scoped teardown above cannot provide. **The fifth
    destroy-order defect in this harness** (D-53, D-54, and PR #27's two), and the second
    to surface as a crash with every test passing.

    A no-op when Qt is not loaded: the guard keeps this off the non-Qt tests entirely
    rather than standing a `QApplication` up for them.
    """
    yield
    qt = sys.modules.get("PySide6.QtWidgets")
    if qt is None:
        return
    app = qt.QApplication.instance()
    if app is not None:
        app.processEvents()
