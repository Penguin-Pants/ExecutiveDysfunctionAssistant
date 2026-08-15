"""T11.10 — the report view, its evidence rendering, and the export (FR77–FR83, FR87).

M11's logic all had tests before this and none of it had a surface. What this file
covers is the half a user touches, and three properties carry the weight:

* **Evidence is rendered, not summarised.** FR78's "resolvable" is only worth something
  where someone can resolve it, and that is here.
* **Nothing leaves the device or is destroyed without a prompt.** FR81's per-run
  confirmation, FR85's disclosure, FR83's deletion — all reachable, all asked.
* **FR79's wall holds at the UI layer too.** The report package is checked by
  `report/separation.py`; this view is the module where the shortcut around it would be
  taken, so the same assertion is made about it.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from helpers import ReversingCipher, ScriptedClient

pytest.importorskip("PySide6", reason="Qt UI tests require the [ui] extra")

from PySide6.QtWidgets import QApplication  # noqa: E402

from interview_prep_recall.app import Application  # noqa: E402
from interview_prep_recall.notes.model import ContextSet, Note, SourceKind  # noqa: E402
from interview_prep_recall.report.evidence import ReportSection  # noqa: E402
from interview_prep_recall.report.generator import SUBSTITUTED_CONTEXT_NOTICE  # noqa: E402
from interview_prep_recall.report.separation import imported_modules  # noqa: E402
from interview_prep_recall.stt.assembler import Utterance  # noqa: E402
from interview_prep_recall.ui.report_view import (  # noqa: E402
    NO_REPORT_TEXT,
    SECTION_TITLES,
    UNENCRYPTED_EXPORT_WARNING,
    UNRESOLVED_PREFIX,
    ReportView,
    document_from_stored,
    render_markdown,
)


class FlatEmbedder:
    model_id = "flat/one"
    model_version = "1.0"

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.ones((len(texts), 2), dtype=np.float32)


PREP_HEADLINE = "Tell me about a migration"


def _context() -> ContextSet:
    return ContextSet(
        name="Acme",
        notes=[
            Note(headline=PREP_HEADLINE, kind=SourceKind.PREP, track_progress=True),
            Note(headline="Senior engineer wanted", kind=SourceKind.ROLE),
        ],
    )


def _findings_payload(note_id: str) -> dict:
    """One finding of each evidence kind, both of which must resolve in the view."""
    return {
        "findings": [
            {
                "section": ReportSection.CRAFT.value,
                "text": "You answered the opening question directly.",
                "indices": [0],
            },
            {
                "section": ReportSection.PREP_COVERAGE.value,
                "text": "You never told the migration story you prepared.",
                "source_note_id": note_id,
            },
        ]
    }


def _app(tmp: Path, client: ScriptedClient | None = None) -> Application:
    return Application(
        root=tmp,
        embedder=FlatEmbedder(),
        client=client or ScriptedClient(),
        cipher=ReversingCipher(),
        context_set=_context(),
    )


def _utterance(text: str, *, stream: str = "interviewer") -> Utterance:
    return Utterance(stream_id=stream, text=text, t_start=0.0, t_end=1.0, context="")


def _session(app: Application, *, role: str = "Staff Engineer") -> str:
    app.session.request_start()
    app.session.preflight_result(blocked=False)
    app.consume(_utterance("tell me about a migration"), now=1.0)
    session_id = app.end_session(role=role)
    assert session_id is not None
    return session_id


def _legacy_session(app: Application, *, role: str = "Role") -> str:
    """A session stored **before D-58**: no context snapshot in the transcript.

    Written through the store directly, which is what the pre-snapshot `save` call did.
    The purge still runs afterwards so the rest of the flow matches a real session.
    """
    app.session.request_start()
    app.session.preflight_result(blocked=False)
    app.consume(_utterance("tell me about a migration"), now=1.0)
    session_id = app.sessions.save(app.record, role=role, missed_note_ids=frozenset())
    app.session.end_session()
    return session_id


def _view(app: Application, **kwargs) -> ReportView:  # type: ignore[no-untyped-def]
    kwargs.setdefault("confirm", lambda _size: True)
    kwargs.setdefault("acknowledge", lambda _text: True)
    kwargs.setdefault("confirm_delete", lambda _message: True)
    kwargs.setdefault("choose_path", lambda _suggested: None)
    # T11.10b: the model call is dispatched to a worker in production. Tests run it
    # inline so assertions can follow `generate()` — the signal hop is a direct call
    # within one thread, so this exercises the same slot the queued connection reaches.
    kwargs.setdefault("dispatch", lambda work: work())
    return ReportView(app, **kwargs)


# ---------- FR83: the session list ----------


def test_the_list_shows_every_stored_session(qapp: QApplication, app_data) -> None:  # type: ignore[no-untyped-def]
    app = _app(app_data)
    _session(app, role="Staff Engineer")
    _session(app, role="Principal")

    view = _view(app)

    assert len(view.rows) == 2
    assert {row[1] for row in view.rows} == {"Staff Engineer", "Principal"}


def test_an_empty_store_says_so(qapp: QApplication, app_data) -> None:  # type: ignore[no-untyped-def]
    view = _view(_app(app_data))

    assert view.rows == ()
    assert view.selected_session_id is None


def test_a_session_without_a_report_says_so_rather_than_showing_a_blank_pane(
    qapp: QApplication,
    app_data,  # type: ignore[no-untyped-def]
) -> None:
    """The diagnostics viewer's rule, and the overlay's: a blank surface is
    indistinguishable from a broken one."""
    app = _app(app_data)
    _session(app)

    view = _view(app)

    assert view.body.toPlainText() == ""
    assert view.status.text() == NO_REPORT_TEXT
    assert not view.export_button.isEnabled()


# ---------- FR77/FR78: what the reader shows ----------


def test_the_reader_renders_every_section_and_both_evidence_kinds(
    qapp: QApplication,
    app_data,  # type: ignore[no-untyped-def]
) -> None:
    """The requirement this view exists for. A presence finding shows the utterance it
    rests on; an absence finding names the note the point was expected from."""
    app = _app(app_data)
    note_id = app.context_set.notes[0].id
    app.reports.client = ScriptedClient(_findings_payload(note_id))
    app.consent.acknowledge()
    _session(app)

    view = _view(app)
    view.generate()

    assert view.document is not None
    body = view.body.toPlainText()
    for title in SECTION_TITLES.values():
        assert title.upper() in body
    assert "[0] interviewer: tell me about a migration" in body
    assert f"expected from: {PREP_HEADLINE}" in body


def test_an_absence_citation_whose_note_is_gone_is_marked_not_hidden(
    qapp: QApplication,
    app_data,  # type: ignore[no-untyped-def]
) -> None:
    """A stored report outlives the notes it cites. Dropping the finding would change
    the report's contents between two readings with nothing to explain it."""
    app = _app(app_data)
    note_id = app.context_set.notes[0].id
    app.reports.client = ScriptedClient(_findings_payload(note_id))
    app.consent.acknowledge()
    session_id = _session(app)
    app.generate_report(session_id=session_id, confirm=lambda _: True)

    app.context_set.delete(note_id)
    stored = app.sessions.load(session_id)
    document = document_from_stored(stored, headline=lambda _id: None)

    assert document is not None
    absence = document.findings_for(ReportSection.PREP_COVERAGE)
    assert absence and not absence[0].resolved
    assert absence[0].citations[0].startswith(UNRESOLVED_PREFIX)
    assert absence[0].text, "the finding is still shown"


def test_generated_text_is_never_rendered_as_rich_text(
    qapp: QApplication,
    app_data,  # type: ignore[no-untyped-def]
) -> None:
    """The one string in the product that came from a language model. `setPlainText` is
    the whole mitigation, so it is asserted rather than assumed."""
    app = _app(app_data)
    app.reports.client = ScriptedClient(
        {
            "findings": [
                {
                    "section": ReportSection.CRAFT.value,
                    "text": "<b>bold</b> and <script>alert(1)</script>",
                    "indices": [0],
                }
            ]
        }
    )
    app.consent.acknowledge()
    _session(app)

    view = _view(app)
    view.generate()

    assert "<b>bold</b>" in view.body.toPlainText()


# ---------- FR80/FR81/FR85: nothing leaves silently ----------


def test_local_only_mode_disables_generation_with_a_reason(
    qapp: QApplication,
    app_data,  # type: ignore[no-untyped-def]
) -> None:
    """FR80. A disabled control with no reason is indistinguishable from a broken one."""
    app = _app(app_data)
    _session(app)
    app.session.set_switch("llm_matching", False)

    view = _view(app)

    assert not view.generate_button.isEnabled()
    assert "local-only" in view.generate_button.toolTip()


def test_declining_the_confirmation_sends_nothing(
    qapp: QApplication,
    app_data,  # type: ignore[no-untyped-def]
) -> None:
    """FR81. The decline path is the one that must not reach the API at all."""
    client = ScriptedClient()
    app = _app(app_data, client)
    app.consent.acknowledge()
    _session(app)

    view = _view(app, confirm=lambda _size: False)
    view.generate()

    assert view.document is None
    assert not [r for r in client.requests if any(t["name"] == "submit_report" for t in r["tools"])]
    assert "declined" in view.status.text().lower()


def test_the_confirmation_is_asked_every_run_with_the_size(
    qapp: QApplication,
    app_data,  # type: ignore[no-untyped-def]
) -> None:
    """Not a remembered preference: the thing being confirmed is that *this* interview,
    including the other person's words, leaves the device now."""
    app = _app(app_data)
    app.consent.acknowledge()
    _session(app)
    sizes: list[int] = []

    view = _view(app, confirm=lambda size: (sizes.append(size), True)[1])
    view.generate()
    view.generate()

    assert len(sizes) == 2
    assert all(size > 0 for size in sizes)


def test_the_disclosure_blocks_until_acknowledged(
    qapp: QApplication,
    app_data,  # type: ignore[no-untyped-def]
) -> None:
    """FR85. A prior FR63 acknowledgement does not carry over, and declining this one
    does not send anything — nor does it quit the app."""
    client = ScriptedClient()
    app = _app(app_data, client)
    _session(app)

    view = _view(app, acknowledge=lambda _text: False)

    view.generate()
    assert view.document is None
    assert not [r for r in client.requests if any(t["name"] == "submit_report" for t in r["tools"])]
    assert app.consent.required, "declining must not record an acknowledgement"


def test_accepting_the_disclosure_records_it_once(
    qapp: QApplication,
    app_data,  # type: ignore[no-untyped-def]
) -> None:
    app = _app(app_data)
    _session(app)
    shown: list[str] = []

    view = _view(app, acknowledge=lambda text: (shown.append(text), True)[1])
    view.generate()
    view.generate()

    assert len(shown) == 1, "the acknowledgement persists; the disclosure is not re-asked"
    assert not app.consent.required


# ---------- the export (D-56) ----------


def test_the_export_writes_markdown_where_the_user_chose(
    qapp: QApplication,
    app_data,
    tmp_path: Path,  # type: ignore[no-untyped-def]
) -> None:
    app = _app(app_data)
    note_id = app.context_set.notes[0].id
    app.reports.client = ScriptedClient(_findings_payload(note_id))
    app.consent.acknowledge()
    _session(app)
    destination = tmp_path / "report.md"

    view = _view(app, choose_path=lambda _suggested: destination)
    view.generate()
    written = view.export()

    assert written == destination
    text = destination.read_text(encoding="utf-8")
    assert "# Interview report — Staff Engineer" in text
    assert "You never told the migration story you prepared." in text
    assert f"expected from: {PREP_HEADLINE}" in text


def test_the_export_states_that_the_copy_is_unencrypted(
    qapp: QApplication,
    app_data,
    tmp_path: Path,  # type: ignore[no-untyped-def]
) -> None:
    """D-56. Every other copy of this material is under FR82's user-bound encryption;
    this one is not, and the warning travels **in the file** because that is what gets
    mailed to someone."""
    app = _app(app_data)
    app.consent.acknowledge()
    _session(app)
    destination = tmp_path / "report.md"

    view = _view(app, choose_path=lambda _suggested: destination)
    view.generate()
    view.export()

    assert UNENCRYPTED_EXPORT_WARNING in destination.read_text(encoding="utf-8")
    assert UNENCRYPTED_EXPORT_WARNING in view.status.text()


def test_cancelling_the_chooser_writes_nothing(
    qapp: QApplication,
    app_data,
    tmp_path: Path,  # type: ignore[no-untyped-def]
) -> None:
    app = _app(app_data)
    app.consent.acknowledge()
    _session(app)

    view = _view(app, choose_path=lambda _suggested: None)
    view.generate()

    assert view.export() is None
    assert list(tmp_path.glob("*.md")) == []


def test_a_failed_write_is_reported_rather_than_swallowed(
    qapp: QApplication,
    app_data,
    tmp_path: Path,  # type: ignore[no-untyped-def]
) -> None:
    """The user is exporting because they are about to do something with the file, and
    an absent file looks exactly like a written one until they go looking for it."""
    app = _app(app_data)
    app.consent.acknowledge()
    _session(app)
    unwritable = tmp_path / "no-such-directory" / "report.md"

    view = _view(app, choose_path=lambda _suggested: unwritable)
    view.generate()

    assert view.export() is None
    assert "could not write" in view.status.text().lower()


def test_markdown_states_a_truncated_recording(qapp: QApplication, app_data) -> None:  # type: ignore[no-untyped-def]
    """FR75's notice has to survive into the artifact the user keeps."""
    app = _app(app_data)
    app.consent.acknowledge()
    session_id = _session(app)
    app.generate_report(session_id=session_id, confirm=lambda _: True)
    stored = app.sessions.load(session_id)
    payload = dict(stored.report or {})
    payload["truncated"] = True
    app.sessions.attach_report(session_id, payload)

    document = document_from_stored(app.sessions.load(session_id), headline=lambda _id: None)

    assert document is not None
    assert "recording cap" in render_markdown(document)


# ---------- FR83/FR87: deletion ----------


def test_deleting_a_session_removes_it_from_the_list(qapp: QApplication, app_data) -> None:  # type: ignore[no-untyped-def]
    app = _app(app_data)
    _session(app, role="Staff Engineer")
    _session(app, role="Principal")

    view = _view(app)
    assert view.delete_selected()

    assert len(view.rows) == 1


def test_declining_the_delete_prompt_keeps_the_session(qapp: QApplication, app_data) -> None:  # type: ignore[no-untyped-def]
    app = _app(app_data)
    _session(app)

    view = _view(app, confirm_delete=lambda _message: False)

    assert not view.delete_selected()
    assert len(view.rows) == 1


def test_delete_all_is_reachable_and_asked_once(qapp: QApplication, app_data) -> None:  # type: ignore[no-untyped-def]
    """FR87. With the destructive panic path on hold (D-U11), this is the only control
    in the product that destroys stored history."""
    app = _app(app_data)
    _session(app)
    _session(app)
    prompts: list[str] = []

    view = _view(app, confirm_delete=lambda message: (prompts.append(message), True)[1])
    deleted = view.delete_all()

    assert deleted == 2
    assert view.rows == ()
    assert len(prompts) == 1


def test_declining_delete_all_destroys_nothing(qapp: QApplication, app_data) -> None:  # type: ignore[no-untyped-def]
    app = _app(app_data)
    _session(app)

    view = _view(app, confirm_delete=lambda _message: False)

    assert view.delete_all() == 0
    assert len(app.sessions.list_sessions()) == 1


# ---------- FR79: the wall, at the UI layer ----------


def test_the_report_view_does_not_import_the_overlay() -> None:
    """The report package is checked by `report/separation.py`. This module is where the
    way around that check would be built — a UI file that imports both surfaces — so the
    same assertion is made about it directly.
    """
    module_dir = Path(__file__).resolve().parent.parent / "interview_prep_recall" / "ui"
    imports = imported_modules(module_dir / "report_view.py")

    assert not [m for m in imports if m.startswith("interview_prep_recall.ui.overlay")]


# ---------- FR84: the retention default, where the sessions are ----------


def test_the_retention_default_is_stated_on_the_session_list(qapp: QApplication, app_data) -> None:  # type: ignore[no-untyped-def]
    """FR84 requires the default to be stated at first use of the feature and not buried
    in settings. This list is the only place a stored session is ever visible."""
    app = _app(app_data)
    _session(app)

    view = _view(app)

    assert "30 days" in view.retention.text()


def test_retention_set_to_never_says_that_instead(qapp: QApplication, app_data) -> None:  # type: ignore[no-untyped-def]
    """Read from the store rather than restated, so a user who changed it is told what is
    true of their machine."""
    app = _app(app_data)
    _session(app)
    app.sessions.retention_days = None

    view = _view(app)

    assert "until you delete them" in view.retention.text()


def test_availability_is_rechecked_when_the_window_reappears(
    qapp: QApplication,
    app_data,  # type: ignore[no-untyped-def]
) -> None:
    """The dialog is modeless, so FR37's switch can be flipped in Settings while it sits
    open. Generation would still be refused with a reason, but a control that looks
    available and is not is a small lie this avoids."""
    app = _app(app_data)
    _session(app)
    view = _view(app)
    assert view.generate_button.isEnabled()

    app.session.set_switch("llm_matching", False)
    view.show()

    assert not view.generate_button.isEnabled()


# ---------- PR #24 review findings ----------


def test_a_finding_is_rendered_once_not_twice(qapp: QApplication, app_data) -> None:  # type: ignore[no-untyped-def]
    """`ReportGenerator._sections` builds a section body by joining its accepted
    findings, so rendering the body *and* the findings printed every conclusion twice —
    once bare, once above its own evidence."""
    app = _app(app_data)
    note_id = app.context_set.notes[0].id
    app.reports.client = ScriptedClient(_findings_payload(note_id))
    app.consent.acknowledge()
    _session(app)

    view = _view(app)
    view.generate()
    document = view.document
    assert document is not None

    finding_text = "You answered the opening question directly."
    assert view.body.toPlainText().count(finding_text) == 1
    assert render_markdown(document).count(finding_text) == 1


def test_the_truncation_notice_survives_de_duplication(qapp: QApplication, app_data) -> None:  # type: ignore[no-untyped-def]
    """FR75's notice is appended to `WHAT_TO_CHANGE`'s body by the generator, so a
    renderer that dropped the body to avoid duplication would drop the recording-cap
    warning with it — a requirement lost to a rendering fix."""
    app = _app(app_data)
    app.reports.client = ScriptedClient(
        {
            "findings": [
                {
                    "section": ReportSection.WHAT_TO_CHANGE.value,
                    "text": "Ask about the team's on-call rotation.",
                    "indices": [0],
                }
            ]
        }
    )
    app.consent.acknowledge()
    session_id = _session(app)
    app.generate_report(session_id=session_id, confirm=lambda _: True)

    stored = app.sessions.load(session_id)
    payload = dict(stored.report or {})
    sections = dict(payload["sections"])
    sections[ReportSection.WHAT_TO_CHANGE.value] += (
        "\n\n(This session hit the recording cap; the later part of the "
        "conversation is not covered by this report.)"
    )
    payload["sections"] = sections
    app.sessions.attach_report(session_id, payload)

    document = document_from_stored(app.sessions.load(session_id), headline=lambda _id: None)
    assert document is not None
    rendered = render_markdown(document)

    assert rendered.count("Ask about the team's on-call rotation.") == 1
    assert "recording cap" in rendered


def test_a_failing_model_call_is_reported_not_raised(qapp: QApplication, app_data) -> None:  # type: ignore[no-untyped-def]
    """Offline, rate-limited, bad key: the generator lets those propagate because it is
    not the layer that knows what to tell a person, and this slot is the end of the line.
    An exception escaping a Qt callback leaves a button that did nothing."""
    app = _app(app_data, ScriptedClient(boom=ConnectionError("no route to host")))
    app.consent.acknowledge()
    _session(app)

    view = _view(app)
    view.generate()

    assert view.document is None
    assert "ConnectionError" in view.status.text()
    assert "no route to host" in view.status.text()
    assert view.generate_button.isEnabled(), "the control must come back"


def test_a_failed_generation_is_recorded_structurally(qapp: QApplication, app_data) -> None:  # type: ignore[no-untyped-def]
    """FR36: the failure is in the diagnostics ring, by error type and nothing else."""
    app = _app(app_data, ScriptedClient(boom=ConnectionError("no route to host")))
    app.consent.acknowledge()
    _session(app)

    _view(app).generate()

    assert any(event.event == "report_failed" for event in app.ring.snapshot())


# ---------- D-58 / T11.10c: the substitution is visible where it is read ----------


def test_a_substituted_report_says_so_at_the_top_of_the_reader(
    qapp: QApplication,
    app_data,  # type: ignore[no-untyped-def]
) -> None:
    """The generator marks the two sections the substitution distorts; the reader also
    says it up front, because a reader who skims to the summaries would otherwise never
    meet the notice."""
    app = _app(app_data)
    app.consent.acknowledge()
    _legacy_session(app)

    view = _view(app)
    view.generate()

    assert SUBSTITUTED_CONTEXT_NOTICE in view.body.toPlainText()


def test_the_export_carries_the_substitution_notice(
    qapp: QApplication,
    app_data,
    tmp_path: Path,  # type: ignore[no-untyped-def]
) -> None:
    """The exported file outlives the dialog, and this is the caveat a reader most needs
    attached to the document rather than to the app that produced it."""
    app = _app(app_data)
    app.consent.acknowledge()
    _legacy_session(app)
    destination = tmp_path / "report.md"

    view = _view(app, choose_path=lambda _suggested: destination)
    view.generate()
    view.export()

    assert SUBSTITUTED_CONTEXT_NOTICE in destination.read_text(encoding="utf-8")


def test_a_snapshotted_report_carries_no_such_notice(
    qapp: QApplication,
    app_data,  # type: ignore[no-untyped-def]
) -> None:
    """The ordinary case must stay clean, or the notice becomes furniture."""
    app = _app(app_data)
    app.consent.acknowledge()
    _session(app)

    view = _view(app)
    view.generate()

    assert SUBSTITUTED_CONTEXT_NOTICE not in view.body.toPlainText()


# ---------- T11.10b: the model call does not run on the GUI thread ----------


def test_the_confirmation_is_asked_before_anything_is_dispatched(
    qapp: QApplication,
    app_data,  # type: ignore[no-untyped-def]
) -> None:
    """FR81 must be asked on the thread that owns dialogs, and the worker must not start
    before the answer. A modal opened from a worker is undefined behaviour in Qt — the
    defect PR #22 found in the tracker feed."""
    app = _app(app_data)
    app.consent.acknowledge()
    _session(app)
    order: list[str] = []

    view = _view(
        app,
        confirm=lambda _size: (order.append("confirm"), True)[1],
        dispatch=lambda work: (order.append("dispatch"), work())[1],
    )
    view.generate()

    assert order == ["confirm", "dispatch"]


def test_declining_dispatches_nothing(qapp: QApplication, app_data) -> None:  # type: ignore[no-untyped-def]
    """The decline path must not reach the worker, let alone the socket."""
    client = ScriptedClient()
    app = _app(app_data, client)
    app.consent.acknowledge()
    _session(app)
    dispatched: list[str] = []

    view = _view(
        app,
        confirm=lambda _size: False,
        dispatch=lambda work: dispatched.append("ran"),
    )
    view.generate()

    assert dispatched == []
    assert not [r for r in client.requests if any(t["name"] == "submit_report" for t in r["tools"])]


def test_a_refusal_dispatches_nothing(qapp: QApplication, app_data) -> None:  # type: ignore[no-untyped-def]
    """FR80/FR85's refusals are raised while preparing, which is before the worker."""
    app = _app(app_data)  # consent deliberately not acknowledged
    _session(app)
    dispatched: list[str] = []

    view = _view(
        app,
        acknowledge=lambda _text: False,
        dispatch=lambda work: dispatched.append("ran"),
    )
    view.generate()

    assert dispatched == []


def test_the_controls_are_disabled_while_generating_and_restored_after(
    qapp: QApplication,
    app_data,  # type: ignore[no-untyped-def]
) -> None:
    """A control that is working says so. Without this the second click starts a second
    upload of the same interview — FR81 confirmed both, but the user meant one."""
    app = _app(app_data)
    app.consent.acknowledge()
    _session(app)
    during: list[bool] = []

    def dispatch(work):  # type: ignore[no-untyped-def]
        during.append(view.generate_button.isEnabled())
        work()

    view = _view(app, dispatch=dispatch)
    view.generate()

    assert during == [False], "disabled for the duration"
    assert view.generate_button.isEnabled(), "restored afterwards"


def test_a_second_click_while_running_starts_nothing(qapp: QApplication, app_data) -> None:  # type: ignore[no-untyped-def]
    """The re-entrancy guard, asserted directly rather than trusted to the disabled
    button — a slot is still reachable from a shortcut or a test."""
    app = _app(app_data)
    app.consent.acknowledge()
    _session(app)
    runs: list[str] = []

    def dispatch(work):  # type: ignore[no-untyped-def]
        runs.append("ran")
        view.generate()  # re-entered while the first is still running
        work()

    view = _view(app, dispatch=dispatch)
    view.generate()

    assert runs == ["ran"]


def test_the_default_dispatch_really_leaves_the_gui_thread(
    qapp: QApplication,
    app_data,  # type: ignore[no-untyped-def]
) -> None:
    """The claim this task exists to make true, tested against the production path
    rather than the injected one — the inline dispatcher every other test uses would
    pass whether or not a thread was ever created."""
    import threading
    import time

    app = _app(app_data)
    app.consent.acknowledge()
    _session(app)
    calling_thread = threading.current_thread().name
    seen: list[str] = []

    class ThreadRecordingClient(ScriptedClient):
        def create(self, **kwargs):  # type: ignore[no-untyped-def]
            seen.append(threading.current_thread().name)
            return super().create(**kwargs)

    app.reports.client = ThreadRecordingClient()

    view = ReportView(app, confirm=lambda _size: True, acknowledge=lambda _text: True)
    view.generate()

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and view.status.text().startswith("Generating"):
        qapp.processEvents()
        time.sleep(0.01)

    assert seen and seen[0] != calling_thread, "the model call ran off the GUI thread"
    assert view.status.text() == "Report generated."


def test_an_absence_citation_uses_the_headline_the_finding_came_from(
    qapp: QApplication,
    app_data,  # type: ignore[no-untyped-def]
) -> None:
    """Note ids are stable across edits (FR41), so resolving through today's set finds
    the right note and renders the wrong words — the same substitution D-58 removed from
    generation, one layer down and harder to spot because the citation still resolves.
    Found by review on PR #25."""
    app = _app(app_data)
    note_id = app.context_set.notes[0].id
    app.reports.client = ScriptedClient(_findings_payload(note_id))
    app.consent.acknowledge()
    session_id = _session(app)
    app.generate_report(session_id=session_id, confirm=lambda _: True)

    edited = "Completely rewritten after the interview"
    app.context_set.get(note_id).headline = edited  # type: ignore[union-attr]

    view = _view(app)
    body = view.body.toPlainText()

    assert f"expected from: {PREP_HEADLINE}" in body
    assert edited not in body


def test_delete_all_is_blocked_while_a_report_is_generating(
    qapp: QApplication,
    app_data,  # type: ignore[no-untyped-def]
) -> None:
    """Delete-all removes the transcript the worker is still generating against, and the
    view would then announce success for an interview the user had just deleted."""
    app = _app(app_data)
    app.consent.acknowledge()
    _session(app)
    during: list[bool] = []

    def dispatch(work):  # type: ignore[no-untyped-def]
        during.append(view.delete_all_button.isEnabled())
        work()

    view = _view(app, dispatch=dispatch)
    view.generate()

    assert during == [False]
    assert view.delete_all_button.isEnabled(), "restored afterwards"
