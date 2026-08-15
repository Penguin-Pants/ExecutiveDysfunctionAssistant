"""T5.8 — the in-app diagnostics viewer and its export (FR36).

T0.3 built the buffer and its no-content guarantee; FR36 also required it to be
**viewable in-app and explicitly exportable**, and neither existed. The privacy half of
FR36 is enforced in the ring, so the tests that matter here are the ones about the two
halves the viewer owns: that what is displayed is what was recorded, and that a file
appears only when the user asked for one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="Qt UI tests require the [ui] extra")

from PySide6.QtWidgets import QApplication  # noqa: E402

from interview_prep_recall.diagnostics.ring import (  # noqa: E402
    DiagnosticContentError,
    DiagnosticRing,
)
from interview_prep_recall.ui.diagnostics_view import (  # noqa: E402
    EMPTY_TEXT,
    DiagnosticsView,
    format_fields,
)


@pytest.fixture
def populated_ring() -> DiagnosticRing:
    ring = DiagnosticRing()
    ring.record("stt_connected", backend="deepgram", latency_ms=42)
    ring.record("match", candidates=7, similarity=0.81)
    ring.record("stt_degraded", degraded=True, reason="timeout")
    return ring


# ---------- viewing ----------


def test_the_view_shows_every_recorded_event(qapp: QApplication, populated_ring) -> None:
    view = DiagnosticsView(populated_ring)

    assert len(view.rows) == 3
    assert [row[1] for row in view.rows] == ["stt_connected", "match", "stt_degraded"]


def test_an_empty_ring_says_so_rather_than_showing_a_blank_table(qapp: QApplication) -> None:
    view = DiagnosticsView(DiagnosticRing())

    assert view.rows == ()
    assert view.status.text() == EMPTY_TEXT


def test_refresh_picks_up_events_recorded_after_opening(qapp: QApplication) -> None:
    """The user opens this *because* something is going wrong, so the window has to be
    able to show what happened after it opened."""
    ring = DiagnosticRing()
    view = DiagnosticsView(ring)
    ring.record("stt_reconnect", retry=1)

    view.refresh()

    assert [row[1] for row in view.rows] == ["stt_reconnect"]


def test_fields_are_rendered_in_a_stable_order() -> None:
    ring = DiagnosticRing()
    event = ring.record("match", similarity=0.5, candidates=3, threshold=0.4)

    assert format_fields(event) == "candidates=3 similarity=0.5 threshold=0.4"


def test_the_view_cannot_display_content_the_ring_refused(qapp: QApplication) -> None:
    """FR36's no-content guarantee lives at `record()`, and this states the consequence:
    there is no path by which transcript text reaches the table, because there is no path
    by which it reaches the buffer."""
    ring = DiagnosticRing()

    with pytest.raises(DiagnosticContentError):
        ring.record("stt_final", text="tell me about a time you disagreed with your manager")

    assert DiagnosticsView(ring).rows == ()


# ---------- export (FR36: user-initiated, never automatic) ----------


def test_export_writes_where_the_user_chose(qapp: QApplication, populated_ring, tmp_path) -> None:
    destination = tmp_path / "diagnostics.json"
    view = DiagnosticsView(populated_ring, choose_path=lambda: destination)

    written = view.export()

    assert written == destination
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert [event["event"] for event in payload["events"]] == [
        "stt_connected",
        "match",
        "stt_degraded",
    ]


def test_opening_the_view_writes_nothing(qapp: QApplication, populated_ring, tmp_path) -> None:
    """FR36: the buffer is never auto-written to disk. Opening a window is not consent."""
    DiagnosticsView(populated_ring).refresh()

    assert list(tmp_path.iterdir()) == []


def test_a_cancelled_export_writes_nothing(qapp: QApplication, populated_ring, tmp_path) -> None:
    view = DiagnosticsView(populated_ring, choose_path=lambda: None)

    assert view.export() is None
    assert list(tmp_path.iterdir()) == []


def test_a_failed_export_is_reported_and_recorded(
    qapp: QApplication, populated_ring, tmp_path
) -> None:
    """A file that was never written looks exactly like one that was, until the user goes
    looking for it — and they are exporting because they are about to send it to someone.
    """
    unwritable = tmp_path / "no-such-directory" / "diagnostics.json"
    view = DiagnosticsView(populated_ring, choose_path=lambda: unwritable)

    assert view.export() is None
    assert not unwritable.exists()
    assert "Could not write" in view.status.text()
    assert populated_ring.snapshot()[-1].fields["ok"] is False


def test_a_successful_export_is_recorded_structurally(
    qapp: QApplication, populated_ring, tmp_path: Path
) -> None:
    """Universal definition of done, item 5: no silent path through anything that can fail."""
    view = DiagnosticsView(populated_ring, choose_path=lambda: tmp_path / "out.json")

    view.export()

    last = populated_ring.snapshot()[-1]
    assert last.event == "diagnostics_export"
    assert last.fields == {"ok": True, "count": 3}
