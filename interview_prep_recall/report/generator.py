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

import json
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
            "rejected_findings": self.findings.rejection_count,
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
                messages=[{"role": "user", "content": prompt}],
            )
        finally:
            self.egress.set_llm(False)

        findings = verify(
            _parse_findings(response),
            record,
            missed_note_ids=missed_note_ids,
            known_note_ids=frozenset(n.id for n in context_set.notes),
        )
        self.ring.record("report_generated", count=len(findings.accepted))
        if findings.rejection_count:
            self.ring.record("report_findings_rejected", count=findings.rejection_count)

        absent = self._absent_sources(context_set)
        return Report(
            sections=self._sections(findings, absent, record.truncated),
            findings=findings,
            truncated=record.truncated,
            absent_sources=absent,
        )

    # ---------- prompt ----------

    def _build_prompt(
        self, record: SessionRecord, context_set: ContextSet, missed_note_ids: frozenset[str]
    ) -> str:
        lines = ["TRANSCRIPT", *record.transcript_lines(), ""]
        for kind in SourceKind:
            chunks = context_set.by_kind(kind)
            lines.append(f"{kind.value.upper()} ({len(chunks)} items)")
            lines.extend(f"- id={n.id} | {n.headline}" for n in chunks)
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


def _parse_findings(response: Any) -> list[Finding]:
    """Read findings out of the model's reply.

    Anything malformed is dropped **here**, before verification, so a garbled response
    degrades into fewer findings rather than an exception mid-report. The count still
    reaches the user through the rejection tally.
    """
    text = _response_text(response)
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return []
    raw = payload.get("findings") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return []

    findings: list[Finding] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            section = ReportSection(item["section"])
        except (KeyError, ValueError):
            continue
        text_value = item.get("text")
        if not isinstance(text_value, str) or not text_value.strip():
            continue
        indices = item.get("indices") or []
        source_note_id = item.get("source_note_id")
        if isinstance(indices, list) and indices:
            evidence = Evidence(
                kind=EvidenceKind.PRESENCE,
                utterance_indices=tuple(i for i in indices if isinstance(i, int)),
            )
        else:
            evidence = Evidence(
                kind=EvidenceKind.ABSENCE,
                source_note_id=source_note_id if isinstance(source_note_id, str) else None,
            )
        findings.append(Finding(section=section, text=text_value, evidence=evidence))
    return findings


def _response_text(response: Any) -> str:
    content = getattr(response, "content", None)
    if isinstance(content, list) and content:
        return str(getattr(content[0], "text", "") or "")
    return str(content or "")
