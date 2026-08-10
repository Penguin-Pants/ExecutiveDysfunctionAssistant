"""The structural wall between generated report text and the overlay (T11.6 — FR79).

The overlay cannot fabricate because it cannot generate. The report must generate. Those
two facts are only safe together while nothing can carry text from the second surface to
the first — and "we agreed not to" is not a mechanism.

The risk was never the report itself. It is that a generated-text surface shipping in
the same application becomes the argument, six months from now, for relaxing the overlay
path "just for this one case". `assert_no_overlay_dependency` makes that argument fail at
test time instead of in review.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPORT_PACKAGE = "interview_prep_recall.report"
OVERLAY_MODULE = "interview_prep_recall.ui.overlay"


class OverlayLeakError(AssertionError):
    """A report module imported the overlay, or overlay-bound content came from a report."""


def imported_modules(package_dir: Path) -> set[str]:
    """Every module imported anywhere under `package_dir`, by static analysis.

    Static rather than runtime: an import that only happens on the error path would
    never show up in a runtime check, and that is exactly where a desperate "just render
    the summary" would be added.
    """
    found: set[str] = set()
    for path in sorted(package_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module)
    return found


def assert_no_overlay_dependency(package_dir: Path) -> None:
    leaks = {m for m in imported_modules(package_dir) if m.startswith(OVERLAY_MODULE)}
    if leaks:
        raise OverlayLeakError(
            f"{REPORT_PACKAGE} imports {sorted(leaks)}. Report text is generated prose "
            "and must never be eligible for overlay rendering (FR79)."
        )
