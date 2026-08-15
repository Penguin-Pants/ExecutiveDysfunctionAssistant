"""The post-interview report surface (T11.10 — FR77–FR83, FR87).

The session list, the report reader, and the export. Everything M11 built has been
headless until now: transcripts are stored, reports are generated and verified, retention
sweeps run — and none of it was reachable by the person it is for.

**Evidence is rendered, not summarised.** FR78 makes every judgment carry resolvable
evidence, and this is the surface where "resolvable" is worth anything: a presence
finding shows the utterances it rests on, an absence finding names the note the point was
expected from. A report that displayed only its conclusions would satisfy the requirement
in storage and defeat it where the user reads it — they would be back to trusting an
LLM's impression of an interview it did not attend.

**One resolution path, through the store.** A freshly generated report is attached to its
session and then *re-read from disk* like any other, rather than rendered from the live
`Report` object. Two paths would eventually disagree, and the one exercised least — the
week-old report, which is the whole point of D-U8 — would be the one that broke.

**This module must never import the overlay (FR79).** Report text is generated prose and
the overlay's guarantee is that it cannot generate; `report/separation.py` enforces that
for the report package, and a UI module importing both would be the path around it. A
test asserts it here too, because this file is exactly where that shortcut would be
taken.

**Generated text is displayed as plain text, never rich text.** `QTextEdit` interprets
HTML when handed markup, and this is the one string in the product that came from a
language model. `setPlainText` is the whole mitigation, and it has to stay.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from interview_prep_recall.report.consent import DISCLOSURE_TEXT, ReportConsent
from interview_prep_recall.report.evidence import EvidenceKind, ReportSection
from interview_prep_recall.report.generator import (
    SUBSTITUTED_CONTEXT_NOTICE,
    ContextProvenance,
    PreparedReport,
    ReportUnavailableError,
)
from interview_prep_recall.report.record import RecordedUtterance
from interview_prep_recall.report.store import SessionStore, SessionSummary, StoredSession

if TYPE_CHECKING:
    from interview_prep_recall.app import Application

TITLE = "Interview reports"

COLUMNS = ("stored", "role", "size", "report")
"""FR83's row: date, role, size — plus whether a report exists, which is what decides
between the Generate and the Export button being the useful one."""

SECTION_TITLES: dict[ReportSection, str] = {
    ReportSection.PREP_COVERAGE: "Prep-note coverage",
    ReportSection.ROLE_FIT: "Job-description fit",
    ReportSection.RESUME_USE: "Resume utilisation",
    ReportSection.CRAFT: "Interview craft",
    ReportSection.WHAT_WENT_WELL: "What went well",
    ReportSection.WHAT_TO_CHANGE: "What to do differently",
}
"""Display names for FR77's six sections, in the order they are read.

Dict order is the render order — the four rubric dimensions (D-U10) first, then the two
summaries, which is how someone reads a review of themselves: the specifics, then the
verdict.
"""

EMPTY_LIST_TEXT = "No stored sessions."
NO_REPORT_TEXT = "No report has been generated for this session yet."
NO_SELECTION_TEXT = "Select a session."

EXPORT_SUFFIX = ".md"

UNENCRYPTED_EXPORT_WARNING = (
    "An exported report is a plain, unencrypted file wherever you put it, including the "
    "interviewer's words. The stored copy is encrypted to your Windows account (FR82); "
    "the export is not, and deleting the session here will not remove it."
)
"""D-56, and it is stated at the moment of export rather than in a settings page.

Every other copy of this material is protected by FR82's user-bound encryption. The
export is the one hole in that, deliberately — a report the user cannot get out of the
app is not much use — but a hole nobody mentioned would make FR82's promise read as
broader than it is.
"""


def retention_notice(retention_days: int | None) -> str:
    """FR84's default, stated **here** — where the sessions are — rather than in settings.

    The requirement is explicit that the retention default is stated at first use of the
    feature and not buried in a settings page, and this list is that first use: it is the
    only place a stored session is ever visible. Read from the store rather than restated,
    so a user who has changed it is told what is actually true of their machine.
    """
    if retention_days is None:
        return "Sessions are kept until you delete them."
    return (
        f"Sessions are deleted automatically after {retention_days} days. Change this in Settings."
    )


DELETE_ALL_TEXT = "Delete all sessions…"
"""FR87. With the destructive panic path on hold (D-U11), this is the only control in the
product that destroys stored history, and the requirement is that it is signposted where
someone reaching for panic would look. This is not that surface — see the module note in
the progress log; what it is, is the control itself, reachable and named plainly."""

PathChooser = Callable[[str], Path | None]
"""Returns where the user wants the export written, or None if they cancelled. Takes a
suggested filename."""

Confirmer = Callable[[int], bool]
"""FR81's every-run confirmation, given the payload size in bytes."""

Acknowledger = Callable[[str], bool]
"""FR85's disclosure gate. Returns True only if the user accepted the text shown."""

NoteHeadline = Callable[[str], str | None]
"""Resolves a note id to its headline, or None if it is no longer in the context set."""


# ---------- the document ----------

UNRESOLVED_PREFIX = "(no longer resolvable)"
"""Marks a citation that no longer points at anything, rather than hiding the finding."""


@dataclass(frozen=True)
class ResolvedFinding:
    """One finding with its evidence turned back into something a person can check."""

    section: ReportSection
    text: str
    kind: EvidenceKind
    citations: tuple[str, ...]

    @property
    def resolved(self) -> bool:
        """Whether the evidence still points at something that exists.

        A stored report can outlive the notes it cites — the user edits their prep set,
        and an absence finding's source chunk is gone. The finding is **shown with its
        citation marked unresolvable** rather than hidden: FR78 rejects unevidenced
        findings at generation, and silently dropping one later would leave the user with
        a report whose contents changed between readings for no visible reason.
        """
        return bool(self.citations) and not any(
            c.startswith(UNRESOLVED_PREFIX) for c in self.citations
        )


@dataclass(frozen=True)
class ReportDocument:
    """Everything the reader and the export render, resolved against the stored session."""

    session_id: str
    stored_at: str
    role: str
    sections: tuple[tuple[ReportSection, str], ...]
    findings: tuple[ResolvedFinding, ...]
    truncated: bool
    absent_sources: tuple[str, ...]
    discarded: int
    context_substituted: bool = False
    """D-58: this report was graded against today's notes, not the interview's own.

    Rendered at the **top** as well as inside the two sections the generator marks. The
    per-section notice is where the distortion actually is; this one is because a reader
    who skims the summaries would otherwise never meet it, and the whole failure mode is
    a report that reads as authoritative while part of it was graded against the wrong
    notes.
    """

    def findings_for(self, section: ReportSection) -> tuple[ResolvedFinding, ...]:
        return tuple(f for f in self.findings if f.section is section)


def _utterance_citation(utterances: Sequence[RecordedUtterance], index: int) -> str:
    for utterance in utterances:
        if utterance.index == index:
            speaker = "you" if utterance.is_user else "interviewer"
            return f"[{index}] {speaker}: {utterance.text}"
    return f"{UNRESOLVED_PREFIX} utterance [{index}] is not in the stored transcript"


def _absence_citation(note_id: str | None, headline: NoteHeadline) -> str:
    if not note_id:
        return f"{UNRESOLVED_PREFIX} no source was cited"
    resolved = headline(note_id)
    if resolved is None:
        return f"{UNRESOLVED_PREFIX} the source note {note_id} is no longer in your notes"
    return f"expected from: {resolved}"


def document_from_stored(stored: StoredSession, *, headline: NoteHeadline) -> ReportDocument | None:
    """Build the rendered document, or None when the session has no report yet.

    Reads the stored dict rather than a live `Report` so that a report generated a minute
    ago and one generated last month go through identical code. `Report.to_dict` is the
    only writer of this shape, so the keys are read defensively but not re-validated —
    a corrupt payload is a store problem, and inventing a second schema check here would
    be a second opinion about what a report is.
    """
    payload = stored.report
    if payload is None:
        return None

    raw_sections = payload.get("sections") or {}
    sections: list[tuple[ReportSection, str]] = []
    for section in SECTION_TITLES:
        body = raw_sections.get(section.value)
        if isinstance(body, str):
            sections.append((section, body))

    findings: list[ResolvedFinding] = []
    for item in payload.get("findings") or []:
        if not isinstance(item, dict):
            continue
        try:
            section = ReportSection(item.get("section"))
            kind = EvidenceKind(item.get("evidence", {}).get("kind"))
        except ValueError:
            continue
        evidence: dict[str, Any] = item.get("evidence") or {}
        if kind is EvidenceKind.PRESENCE:
            citations = tuple(
                _utterance_citation(stored.utterances, index)
                for index in evidence.get("indices") or []
                if isinstance(index, int) and not isinstance(index, bool)
            )
        else:
            citations = (_absence_citation(evidence.get("source_note_id"), headline),)
        findings.append(
            ResolvedFinding(
                section=section,
                text=str(item.get("text", "")),
                kind=kind,
                citations=citations,
            )
        )

    return ReportDocument(
        session_id=stored.id,
        stored_at=stored.stored_at,
        role=stored.role,
        sections=tuple(sections),
        findings=tuple(findings),
        truncated=bool(payload.get("truncated")),
        context_substituted=payload.get("context_provenance")
        == ContextProvenance.SUBSTITUTED.value,
        absent_sources=tuple(str(k) for k in payload.get("absent_sources") or []),
        discarded=int(payload.get("rejected_findings") or 0),
    )


# ---------- rendering ----------


def render_text(document: ReportDocument) -> str:
    """The reader's view: every section, its findings, and each finding's evidence."""
    lines: list[str] = [
        f"{document.role or 'Interview'} — stored {document.stored_at}",
        "",
    ]
    if document.context_substituted:
        lines += [SUBSTITUTED_CONTEXT_NOTICE, ""]
    if document.truncated:
        lines += ["This session hit the recording cap; its later part is not covered.", ""]
    if document.absent_sources:
        lines += [f"Context not loaded for: {', '.join(document.absent_sources)}", ""]

    for section, body in document.sections:
        lines.append(SECTION_TITLES[section].upper())
        findings = document.findings_for(section)
        if findings:
            for finding in findings:
                lines.append(f"  • {finding.text}")
                lines += [f"      {citation}" for citation in finding.citations]
            lines += _section_remainder(body, findings, indent="  ")
        else:
            # No findings, so the body is the generator's own words: "nothing notable",
            # or FR77's "not assessed — no job description was loaded".
            lines.append(body)
        lines.append("")

    if document.discarded:
        # Surfaced, never silent — the same reason `VerifiedFindings` keeps its
        # casualties. A report that dropped a third of its findings and said nothing
        # reads as complete.
        lines.append(
            f"{document.discarded} finding(s) the model produced were discarded for "
            "unusable evidence and are not shown."
        )
    return "\n".join(lines)


def render_markdown(document: ReportDocument) -> str:
    """The export. Markdown, matching FR30's notes bundle rather than inventing a format.

    Carries the unencrypted-copy warning **in the file**, not only in the dialog that
    wrote it: the file is the thing that gets mailed to a friend or synced to a drive,
    and by then the dialog is long gone.
    """
    lines: list[str] = [
        f"# Interview report — {document.role or 'untitled role'}",
        "",
        f"Session `{document.session_id}`, stored {document.stored_at}.",
        "",
        f"> {UNENCRYPTED_EXPORT_WARNING}",
        "",
    ]
    if document.context_substituted:
        lines += [f"> **{SUBSTITUTED_CONTEXT_NOTICE}**", ""]
    if document.truncated:
        lines += ["**This session hit the recording cap**; its later part is not covered.", ""]
    if document.absent_sources:
        lines += [f"**Context not loaded for:** {', '.join(document.absent_sources)}", ""]

    for section, body in document.sections:
        lines += [f"## {SECTION_TITLES[section]}", ""]
        findings = document.findings_for(section)
        if findings:
            for finding in findings:
                lines.append(f"- {finding.text}")
                lines += [f"  - _{citation}_" for citation in finding.citations]
            lines += _section_remainder(body, findings)
        else:
            lines.append(body)
        lines.append("")

    if document.discarded:
        lines += [
            f"_{document.discarded} finding(s) were discarded for unusable evidence "
            "and are not shown._",
            "",
        ]
    return "\n".join(lines)


def _section_remainder(
    body: str, findings: Sequence[ResolvedFinding], indent: str = ""
) -> list[str]:
    """Whatever the section body says **beyond** the findings it was built from.

    `ReportGenerator._sections` builds a section's body by joining its accepted findings,
    so rendering the body *and* the findings printed every conclusion twice — once bare
    and once above its own evidence. Found by review on PR #24.

    The body is not simply discarded, because it is not always only the findings: FR75's
    truncation notice is appended to `WHAT_TO_CHANGE` there, and dropping the body would
    take the recording-cap warning with it — a requirement lost to a de-duplication.
    """
    remainder = body
    for finding in findings:
        remainder = remainder.replace(finding.text, "", 1)
    extra = [line for line in remainder.splitlines() if line.strip()]
    return ["", *(f"{indent}{line}" for line in extra)] if extra else []


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


# ---------- the view ----------


class ReportView(QDialog):
    """FR83's session list and the report reader, with generation and export.

    **Every destructive and every outbound action goes through an injected callable**
    (`confirm`, `acknowledge`, `choose_path`, `confirm_delete`), defaulting to a Qt
    dialog. That is what makes this surface testable headless without synthesising
    clicks on modal windows — and modal windows are exactly where the requirements live:
    FR81's per-run confirmation, FR85's disclosure, FR83's deletion.
    """

    generation_finished = Signal(str, object)
    """The thread hop for T11.10b: (session id, error or None).

    **Producers must emit this, not touch widgets.** `_run` executes on a worker, and
    Qt's default connection is queued across threads — so the slot runs on the GUI
    thread, which is the only place a `QWidget` may be read or written. Same contract
    as `OverlayPanel.tracker_updated`, and the same defect if it is bypassed.
    """

    def __init__(
        self,
        application: Application,
        *,
        confirm: Confirmer | None = None,
        dispatch: Callable[[Callable[[], None]], None] | None = None,
        acknowledge: Acknowledger | None = None,
        choose_path: PathChooser | None = None,
        confirm_delete: Callable[[str], bool] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        self.application = application
        self._confirm = confirm if confirm is not None else self._ask_to_send
        self._acknowledge = acknowledge if acknowledge is not None else self._ask_to_acknowledge
        self._choose_path = choose_path if choose_path is not None else self._ask_for_path
        self._confirm_delete = confirm_delete if confirm_delete is not None else self._ask_to_delete
        self._dispatch = dispatch if dispatch is not None else self._default_dispatch
        self._document: ReportDocument | None = None
        self._running = False
        # Populated by `refresh()` below; stated here because `selected_session_id` is
        # reachable from the signal wiring before that call returns.
        self._summaries: list[SessionSummary] = []

        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, len(COLUMNS), self)
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self.refresh_report)
        layout.addWidget(self.table)

        self.body = QTextEdit(self)
        self.body.setReadOnly(True)
        layout.addWidget(self.body)

        self.retention = QLabel(retention_notice(self.sessions.retention_days), self)
        self.retention.setTextFormat(Qt.TextFormat.PlainText)
        self.retention.setWordWrap(True)
        layout.addWidget(self.retention)

        self.status = QLabel("", self)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        self.generate_button = QPushButton("Generate report…", self)
        self.generate_button.clicked.connect(self.generate)
        self.export_button = QPushButton("Export…", self)
        self.export_button.clicked.connect(self.export)
        self.delete_button = QPushButton("Delete session…", self)
        self.delete_button.clicked.connect(self.delete_selected)
        self.delete_all_button = QPushButton(DELETE_ALL_TEXT, self)
        self.delete_all_button.clicked.connect(self.delete_all)
        buttons.addWidget(self.delete_all_button)
        buttons.addStretch(1)
        for button in (self.delete_button, self.generate_button, self.export_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        self.generation_finished.connect(self._on_finished)
        self.refresh()

    @property
    def document(self) -> ReportDocument | None:
        """What the reader is showing, once generation has finished."""
        return self._document

    # ---------- listing ----------

    @property
    def sessions(self) -> SessionStore:
        return self.application.sessions

    def refresh(self) -> None:
        """Re-read the session list (FR83). Newest first, as the store returns them."""
        summaries = self.sessions.list_sessions()
        self._summaries = list(summaries)
        self.table.setRowCount(len(summaries))
        for row, summary in enumerate(summaries):
            for column, text in enumerate(
                (
                    summary.stored_at,
                    summary.role,
                    _format_size(summary.bytes_stored),
                    "yes" if summary.has_report else "—",
                )
            ):
                self.table.setItem(row, column, QTableWidgetItem(text))
        if summaries:
            self.table.selectRow(0)
        self.refresh_report()

    @property
    def rows(self) -> tuple[tuple[str, ...], ...]:
        """What the list is showing, for tests."""
        return tuple(
            tuple(self._cell(row, column) for column in range(self.table.columnCount()))
            for row in range(self.table.rowCount())
        )

    def _cell(self, row: int, column: int) -> str:
        item = self.table.item(row, column)
        return item.text() if item is not None else ""

    @property
    def selected_session_id(self) -> str | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._summaries) or not self.table.selectionModel().hasSelection():
            return None
        return self._summaries[row].id

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 — Qt override
        """Re-check availability every time the window comes back.

        This dialog is modeless, so FR37's switch can be flipped in Settings while it
        sits open — leaving an enabled Generate button that the generator would then
        refuse. Refusing is safe and says why; a control that looks available and is not
        is still a small lie, and this is four lines.
        """
        super().showEvent(event)
        self._sync_buttons()

    # ---------- reading ----------

    def refresh_report(self) -> None:
        """Render the selected session's report, or say why there is nothing to render."""
        session_id = self.selected_session_id
        if session_id is None:
            self._document = None
            self.body.setPlainText("")
            self.status.setText(EMPTY_LIST_TEXT if not self._summaries else NO_SELECTION_TEXT)
            self._sync_buttons()
            return

        stored = self.sessions.load(session_id)
        self._document = document_from_stored(stored, headline=self._headline_for(stored))
        # `setPlainText`, never `setHtml` or `setText`: this is generated prose, and a
        # rich-text widget handed markup renders it. See the module docstring.
        self.body.setPlainText("" if self._document is None else render_text(self._document))
        self.status.setText("" if self._document is not None else NO_REPORT_TEXT)
        self._sync_buttons()

    def _headline_for(self, stored: StoredSession) -> NoteHeadline:
        """Resolve citations against **the notes the finding was generated from** (D-58).

        Note ids are stable across edits (FR41), so resolving through today's set finds
        the right note and renders the wrong words: an absence finding says "expected
        from: <today's headline>" while it was produced from the snapshot's. The same
        substitution D-58 removed from generation, one layer down in the rendering — and
        harder to notice, because the citation still resolves.

        Falls back to the current set only for a session that genuinely has no snapshot,
        which is the case the report already marks on its face. Found by review on PR #25.
        """
        source = (
            stored.context_set if stored.context_set is not None else self.application.context_set
        )

        def headline(note_id: str) -> str | None:
            note = source.get(note_id)
            return None if note is None else note.headline

        return headline

    def _sync_buttons(self) -> None:
        """FR80: local-only mode disables generation **and says why**.

        A disabled control with no reason is indistinguishable from a broken one, and the
        user's next move would be to look for the bug rather than for the switch.
        """
        has_selection = self.selected_session_id is not None and not self._running
        # Read straight off the generator, not through a defaulted `getattr`: a default
        # of False here would *enable* the button if the attribute ever moved, which is
        # FR80 failing open on the one control that sends an interview off the device.
        local_only = self.application.reports.local_only
        self.generate_button.setEnabled(has_selection and not local_only)
        self.generate_button.setToolTip(
            "Report generation needs the cloud model and is unavailable in local-only mode (FR37)."
            if local_only
            else ""
        )
        self.export_button.setEnabled(self._document is not None)
        self.delete_button.setEnabled(has_selection)
        # **Also gated on `_running`.** Delete-all removes the transcript the worker is
        # still generating against; `attach_report` would then write a report file for a
        # session that no longer exists, and the view would announce success for an
        # interview the user had just deleted. Found by review on PR #25.
        self.delete_all_button.setEnabled(bool(self._summaries) and not self._running)

    # ---------- generating ----------

    def generate(self) -> None:
        """FR80, FR81, FR85 — and the model call goes to a worker (T11.10b).

        The order is the requirement. Refusals and the prompt are built here, on the GUI
        thread, because FR81's confirmation must be asked here — a modal dialog opened
        from a worker is undefined behaviour in Qt, which is the defect PR #22 found in
        the tracker feed. Only `send_report`, which is the network, is dispatched.

        **This is also what makes FR81a true rather than nominal.** The egress indicator
        is set for the duration of the upload; on a blocked event loop it is lit in
        memory and dark on screen for exactly the seconds it exists to announce.

        Returns nothing: the report arrives on `_finished`, which may be after this
        returns. `document` is the property to read once it has.
        """
        session_id = self.selected_session_id
        if session_id is None or self._running:
            return
        if not self._ensure_consent():
            self.status.setText("The disclosure was not accepted. Nothing was sent.")
            return

        try:
            session_id, prepared = self.application.prepare_report(session_id=session_id)
        except ReportUnavailableError as error:
            # The generator's message is shown verbatim (FR80): it names which of the
            # several refusals happened, and paraphrasing it here would lose that.
            self.status.setText(str(error))
            return

        if not self._confirm(prepared.size_bytes):
            self.application.reports.decline(prepared)
            self.status.setText("Report generation was declined. Nothing was sent.")
            return

        self._set_running(True)
        self._dispatch(lambda: self._run(session_id, prepared))

    def _run(self, session_id: str, prepared: PreparedReport) -> None:
        """The worker body. **Returns through a signal, never by touching a widget.**

        Whatever the client raises is carried back rather than thrown here: an exception
        on a worker thread has nowhere to go, and the user would be left watching a
        dialog that says "Generating…" for the rest of the session.

        **The store is touched from this thread**, which is safe for the reason the
        store was built that way: every write goes through `os.replace` onto its own
        per-session path, so a reader on the GUI thread sees either the old file or the
        new one. It is not safe *in general* — a second generation running concurrently
        would race on the same session — which is what `_running` prevents.
        """
        try:
            self.application.send_report(session_id, prepared)
        except Exception as error:  # noqa: BLE001 — marshalled, not swallowed
            self.generation_finished.emit(session_id, error)
            return
        self.generation_finished.emit(session_id, None)

    def _on_finished(self, session_id: str, error: object) -> None:
        """Back on the GUI thread. Qt's queued connection is the whole of the hop."""
        self._set_running(False)
        if error is not None:
            # Anything the model client raises: offline, rate-limited, bad key, a socket
            # reset. An exception that reached here has already crossed a thread, so the
            # type and message are all that is left of it — both are shown, and the
            # failure is recorded structurally (FR36).
            self.application.ring.record("report_failed", code=type(error).__name__)
            self.status.setText(
                f"The report could not be generated: {type(error).__name__}: {error}. "
                "Nothing was saved; you can try again."
            )
            return
        self.refresh()
        self._select(session_id)
        self.status.setText("Report generated.")

    def _set_running(self, running: bool) -> None:
        """A control that is working says so, and cannot be pressed twice.

        Without this the second click starts a second upload of the same interview —
        FR81 would have confirmed both, but the user meant one.
        """
        self._running = running
        if running:
            self.status.setText("Generating… this can take a few seconds.")
        self._sync_buttons()

    def _default_dispatch(self, work: Callable[[], None]) -> None:
        """Run the network half off the GUI thread.

        A plain daemon thread rather than the application's executor: that pool serves
        the matching pipeline on a latency budget during a live interview (D-11), and a
        multi-second report upload parked in it would sit in front of a stage-2 call.
        """
        import threading

        threading.Thread(target=work, name="report-generation", daemon=True).start()

    def _ensure_consent(self) -> bool:
        """FR85. A prior FR63 acknowledgement does not carry over, and a bump re-asks."""
        consent: ReportConsent = self.application.reports.consent
        if not consent.required:
            return True
        if not self._acknowledge(DISCLOSURE_TEXT):
            return False
        consent.acknowledge()
        return True

    def _select(self, session_id: str) -> None:
        for row, summary in enumerate(self._summaries):
            if summary.id == session_id:
                self.table.selectRow(row)
                return

    # ---------- exporting ----------

    def export(self) -> Path | None:
        """Write the rendered report as Markdown, wherever the user chooses (D-56).

        Nothing is written without a destination the user picked, and a failed write is
        reported rather than swallowed — the same reasoning as the diagnostics export:
        the user is exporting because they are about to do something with the file, and
        an absent file looks exactly like a written one until they go looking.
        """
        if self._document is None:
            return None
        suggested = f"interview-report-{self._document.session_id}{EXPORT_SUFFIX}"
        destination = self._choose_path(suggested)
        if destination is None:
            return None
        try:
            destination.write_text(render_markdown(self._document), encoding="utf-8")
        except OSError as error:
            self.status.setText(f"Could not write the export: {error}")
            return None
        self.status.setText(f"Exported to {destination}. {UNENCRYPTED_EXPORT_WARNING}")
        return destination

    # ---------- deleting (FR83, FR87) ----------

    def delete_selected(self) -> bool:
        session_id = self.selected_session_id
        if session_id is None:
            return False
        if not self._confirm_delete(
            f"Delete this session? Its transcript and report are removed together, "
            f"and this cannot be undone.\n\nSession {session_id}"
        ):
            return False
        deleted = self.sessions.delete(session_id)
        self.refresh()
        self.status.setText("Session deleted." if deleted else "That session was already gone.")
        return deleted

    def delete_all(self) -> int:
        """FR87's control. Named plainly and asked once — destroying every stored
        interview is not something to do on a mis-click, and it is also the thing a user
        reaching for panic actually wants (D-U11 left it carrying that weight)."""
        if not self._summaries:
            return 0
        if not self._confirm_delete(
            f"Delete all {len(self._summaries)} stored sessions? Every transcript and "
            "report is removed. This cannot be undone."
        ):
            return 0
        count = self.sessions.delete_all()
        self.refresh()
        self.status.setText(f"Deleted {count} session(s).")
        return count

    # ---------- default Qt prompts ----------

    def _ask_to_send(self, size_bytes: int) -> bool:
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self,
            "Send this interview for analysis?",
            f"This sends the whole transcript — {_format_size(size_bytes)}, including "
            "everything the interviewer said — to Anthropic's API in one call.\n\n"
            "You are asked every time; this is not remembered.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _ask_to_acknowledge(self, text: str) -> bool:
        from PySide6.QtWidgets import QMessageBox

        box = QMessageBox(self)
        box.setWindowTitle("Before generating a report")
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        # **Cancel does not quit the app**, unlike FR63's first-run disclosure. This
        # feature is optional; declining it means not using it, and reusing the
        # first-run dialog would have made "no thanks" mean "exit".
        return box.exec() == QMessageBox.StandardButton.Ok

    def _ask_to_delete(self, message: str) -> bool:
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self,
            "Delete stored sessions?",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _ask_for_path(self, suggested: str) -> Path | None:
        from PySide6.QtWidgets import QFileDialog

        chosen, _filter = QFileDialog.getSaveFileName(
            self, "Export report", suggested, "Markdown (*.md)"
        )
        return Path(chosen) if chosen else None
