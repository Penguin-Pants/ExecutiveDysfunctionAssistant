"""Post-interview report generation (T11.4/T11.7 — FR77, FR80, FR81, FR81a).

**This module generates prose, and it is the only one in the application that does.**
The overlay's guarantee is that it cannot: a forced `tool_choice` over an id enum, and
byte-exact substring assertions on every bullet. That guarantee is untouched by this
file and must stay that way — see `report.separation` for the check that keeps it
structural rather than conventional (FR79).

The full transcript leaves the device in one call. That is the largest egress event the
product will ever make, it includes the interviewer's words, and FR81/FR81a exist so it
is never silent: confirmed every run, with the size, and with the egress indicator lit
for the whole call.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from interview_prep_recall.diagnostics.ring import DiagnosticRing
from interview_prep_recall.notes.model import ContextSet, SourceKind
from interview_prep_recall.report.consent import ReportConsent
from interview_prep_recall.report.evidence import (
    Evidence,
    EvidenceKind,
    Finding,
    ReportSection,
    VerifiedFindings,
    verify,
)
from interview_prep_recall.report.record import SessionRecord
from interview_prep_recall.stt.fallback import EgressMonitor

DEFAULT_MODEL_ID = "claude-haiku-4-5-20251001"
MAX_TOKENS = 4_000

SECTION_SOURCE: dict[ReportSection, SourceKind | None] = {
    ReportSection.PREP_COVERAGE: SourceKind.PREP,
    ReportSection.ROLE_FIT: SourceKind.ROLE,
    ReportSection.RESUME_USE: SourceKind.RESUME,
    ReportSection.CRAFT: None,
    ReportSection.WHAT_WENT_WELL: None,
    ReportSection.WHAT_TO_CHANGE: None,
}
"""FR77. `None` means the section needs no context source — interview craft is judged
from the transcript alone, which is why it survives a session with nothing imported."""

SYSTEM_PROMPT = (
    "You are reviewing a completed job interview for the candidate. Be specific and "
    "direct; vague encouragement is useless to them.\n\n"
    "Every finding MUST carry evidence, of exactly one kind:\n"
    '- presence: cite the [n] indices of the utterances it rests on, as "indices"\n'
    '- absence ("you never made this point"): cite the note id it was expected from, '
    'as "source_note_id"\n\n'
    "A finding you cannot evidence must be omitted, not softened. Do not invent an "
    "index. Do not claim a point was missed unless it appears in the supplied "
    "uncovered-points list."
)


MAX_BODY_CHARS = 1_200
"""Per-chunk cap on source body text sent for analysis.

Bodies are included (see `_build_prompt`) because prep coverage and resume use cannot be
judged from headlines alone. They are capped because a single pathological import — a
whole resume pasted as one chunk — would otherwise dominate the context window and push
the transcript out of it, which is the one thing the report actually needs.
"""

REPORT_TOOL: dict[str, Any] = {
    "name": "submit_report",
    "description": "Submit the interview review as structured, individually evidenced findings.",
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "section": {
                            "type": "string",
                            "enum": [s.value for s in ReportSection],
                        },
                        "text": {"type": "string"},
                        "indices": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "Transcript indices this rests on (presence evidence).",
                        },
                        "source_note_id": {
                            "type": "string",
                            "description": "Note id never covered (absence evidence).",
                        },
                    },
                    "required": ["section", "text"],
                },
            }
        },
        "required": ["findings"],
    },
}
"""FR77's shape, enforced by the API rather than requested in prose.

Without a forced tool the Messages API answers with ordinary text, and the parser accepts
only one undocumented JSON shape — so a perfectly good prose review would land as an
empty report whose every section reads "Nothing notable to report here." A report that
looks complete and contains nothing is worse than a failure, because nothing signals it.

Not the same mechanism as FR10's stage-2 enum, and worth not confusing them: there the
forced tool makes fabrication *impossible*, which is the retrieval-only guarantee. Here
it only fixes the response shape. Report text is generated, and evidence binding — not
the schema — is what keeps it honest.
"""


class ReportUnavailableError(Exception):
    """Generation refused, with a reason the UI shows verbatim (FR80, FR81)."""


class MessagesClient(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class Report:
    sections: dict[ReportSection, str]
    findings: VerifiedFindings
    truncated: bool
    absent_sources: tuple[SourceKind, ...]
    discarded: int = 0
    """Findings the model produced that did not survive — evidence rejections **plus**
    items too malformed to become findings at all.

    Both counted, because a report whose tally says zero while a third of the output was
    dropped at the parser reads as complete and is not."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "sections": {k.value: v for k, v in self.sections.items()},
            "findings": [
                {
                    "section": f.section.value,
                    "text": f.text,
                    "evidence": {
                        "kind": f.evidence.kind.value,
                        "indices": list(f.evidence.utterance_indices),
                        "source_note_id": f.evidence.source_note_id,
                    },
                }
                for f in self.findings.accepted
            ],
            "rejected_findings": self.discarded,
            "truncated": self.truncated,
            "absent_sources": [k.value for k in self.absent_sources],
        }


@dataclass
class ReportGenerator:
    client: MessagesClient
    consent: ReportConsent
    """FR85, enforced here and **required**, not optional.

    Generation is the moment the interviewer's words leave the device, so it is the one
    place the acknowledgement can be checked against the thing actually happening. A
    `None` default would let the whole feature ship with consent unwired and nothing
    failing — the shape of D-23, where the local-only switch lit an indicator while the
    pipeline kept calling the API.
    """

    egress: EgressMonitor = field(default_factory=EgressMonitor)
    ring: DiagnosticRing = field(default_factory=DiagnosticRing)
    model_id: str = DEFAULT_MODEL_ID
    local_only: bool = False
    """FR80. Mirrors the FR37 switch; generation is a cloud call and has no local path."""

    def generate(
        self,
        record: SessionRecord,
        context_set: ContextSet,
        *,
        missed_note_ids: frozenset[str],
        confirm: Callable[[int], bool],
    ) -> Report:
        """Build the report. `confirm` is asked **every** run, with the payload size.

        Not a remembered preference: the thing being confirmed is that this specific
        interview — including the other person's words — leaves the device now. A
        setting checked once cannot carry that.
        """
        if self.consent.required:
            raise ReportUnavailableError(
                "The report disclosure has not been acknowledged. Nothing was sent."
            )
        if self.local_only:
            raise ReportUnavailableError(
                "Report generation needs the cloud model and is unavailable in "
                "local-only mode. Nothing was sent."
            )
        if len(record) == 0:
            raise ReportUnavailableError("Nothing was recorded in this session.")

        prompt = self._build_prompt(record, context_set, missed_note_ids)
        if not confirm(len(prompt.encode("utf-8"))):
            self.ring.record("report_declined", count=len(record))
            raise ReportUnavailableError("Report generation was declined. Nothing was sent.")

        # Lit before the call and cleared in `finally`, so a raised exception cannot
        # leave the indicator claiming an upload that already failed (FR81a).
        self.egress.set_llm(True)
        try:
            response = self.client.create(
                model=self.model_id,
                max_tokens=MAX_TOKENS,
                temperature=0,
                system=SYSTEM_PROMPT,
                tools=[REPORT_TOOL],
                tool_choice={"type": "tool", "name": REPORT_TOOL["name"]},
                messages=[{"role": "user", "content": prompt}],
            )
        finally:
            self.egress.set_llm(False)

        parsed = _parse_findings(response)
        findings = verify(
            parsed.findings,
            record,
            missed_note_ids=missed_note_ids,
            known_note_ids=frozenset(n.id for n in context_set.notes),
        )
        discarded = findings.rejection_count + parsed.malformed
        self.ring.record("report_generated", count=len(findings.accepted))
        if discarded:
            self.ring.record("report_findings_rejected", count=discarded)

        absent = self._absent_sources(context_set)
        return Report(
            sections=self._sections(findings, absent, record.truncated),
            findings=findings,
            truncated=record.truncated,
            absent_sources=absent,
            discarded=discarded,
        )

    # ---------- prompt ----------

    def _build_prompt(
        self, record: SessionRecord, context_set: ContextSet, missed_note_ids: frozenset[str]
    ) -> str:
        lines = ["TRANSCRIPT", *record.transcript_lines(), ""]
        for kind in SourceKind:
            chunks = context_set.by_kind(kind)
            lines.append(f"{kind.value.upper()} ({len(chunks)} items)")
            for note in chunks:
                # **Bodies included here, unlike the stage-2 selector.** There, headline
                # and tags only: matching is question-to-question on a latency budget,
                # and bodies are the prepared *answers*, which cost hundreds of tokens
                # and bias selection toward long notes.
                #
                # The report has the opposite job and no latency budget. "Did you cover
                # your prepared points, and did you use your strongest experience" cannot
                # be judged from headlines — the answer text *is* the thing being
                # assessed. The two paths differ deliberately; the selector's exclusion
                # is still asserted by its own test.
                body = note.body.strip().replace("\n", " ")
                if len(body) > MAX_BODY_CHARS:
                    body = body[:MAX_BODY_CHARS] + " […truncated]"
                lines.append(f"- id={note.id} | {note.headline}")
                if body:
                    lines.append(f"    {body}")
            lines.append("")
        # The uncovered list comes from the tracker, and the prompt says so, because
        # FR78a makes the tracker the only adjudicator of coverage. A model asked to
        # work it out from the transcript would produce a second opinion that the
        # verifier then rejects wholesale.
        lines.append("POINTS THE TRACKER RECORDED AS NOT COVERED (the only valid absences):")
        lines.extend(f"- {note_id}" for note_id in sorted(missed_note_ids))
        return "\n".join(lines)

    # ---------- assembly ----------

    def _absent_sources(self, context_set: ContextSet) -> tuple[SourceKind, ...]:
        present = context_set.kinds_present()
        return tuple(k for k in SourceKind if k not in present)

    def _sections(
        self,
        findings: VerifiedFindings,
        absent: tuple[SourceKind, ...],
        truncated: bool,
    ) -> dict[ReportSection, str]:
        """FR77: a section whose source was absent **says so** and is not omitted.

        Silently dropping it would let the report read as a complete review of the
        interview while a whole dimension was never assessed — and the user has no way
        to notice a section that was never there.
        """
        sections: dict[ReportSection, str] = {}
        for section in ReportSection:
            source = SECTION_SOURCE[section]
            if source is not None and source in absent:
                sections[section] = (
                    f"Not assessed — no {source.value} was loaded for this interview."
                )
                continue
            body = [f.text for f in findings.accepted if f.section is section]
            sections[section] = "\n".join(body) if body else "Nothing notable to report here."

        if truncated:
            # FR75. Stated in the report, not only in a diagnostic nobody reads.
            sections[ReportSection.WHAT_TO_CHANGE] += (
                "\n\n(This session hit the recording cap; the later part of the "
                "conversation is not covered by this report.)"
            )
        return sections


@dataclass(frozen=True)
class ParsedFindings:
    findings: list[Finding]
    malformed: int
    """Items the parser could not turn into a finding at all.

    Returned rather than swallowed. These never reach `verify()`, so they would otherwise
    be invisible in the rejection tally — a report claiming zero discards while the
    parser threw away half the response.
    """


def _parse_findings(response: Any) -> ParsedFindings:
    """Read findings out of the model's reply.

    Malformed items degrade into a count rather than an exception, so a partly-garbled
    response still produces the findings that survived — but the user is told how many
    did not.
    """
    payload = _response_payload(response)
    raw = payload.get("findings") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return ParsedFindings(findings=[], malformed=0)

    findings: list[Finding] = []
    malformed = 0
    for item in raw:
        if not isinstance(item, dict):
            malformed += 1
            continue
        try:
            section = ReportSection(item["section"])
        except (KeyError, ValueError):
            malformed += 1
            continue
        text_value = item.get("text")
        if not isinstance(text_value, str) or not text_value.strip():
            malformed += 1
            continue

        indices = item.get("indices") or []
        if isinstance(indices, list) and indices:
            # **Rejected whole, never filtered.** Dropping the non-integer element from
            # [0, "99"] leaves (0,) — which resolves, so the finding is accepted even
            # though an index the model supplied never did. That defeats the
            # all-indices rule for exactly the shape a sloppy response takes.
            if not all(isinstance(i, int) and not isinstance(i, bool) for i in indices):
                malformed += 1
                continue
            evidence = Evidence(kind=EvidenceKind.PRESENCE, utterance_indices=tuple(indices))
        else:
            source_note_id = item.get("source_note_id")
            evidence = Evidence(
                kind=EvidenceKind.ABSENCE,
                source_note_id=source_note_id if isinstance(source_note_id, str) else None,
            )
        findings.append(Finding(section=section, text=text_value, evidence=evidence))
    return ParsedFindings(findings=findings, malformed=malformed)


def _response_payload(response: Any) -> dict[str, Any]:
    """The forced tool call's input, or `{}`.

    A response carrying no tool_use block is not something to salvage: `tool_choice`
    required one, so its absence means the call did not do what was asked, and guessing
    at prose would reintroduce the shape-drift the forced tool exists to remove.
    """
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "tool_use":
            payload = getattr(block, "input", None)
            if isinstance(payload, dict):
                return payload
        # Some SDK shapes expose the parsed input without a discriminating `type`.
        payload = getattr(block, "input", None)
        if isinstance(payload, dict):
            return payload
    return {}
