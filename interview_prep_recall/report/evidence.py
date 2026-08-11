"""Evidence binding for report findings (T11.5 — FR78, FR78a, D-31).

The overlay cannot fabricate because it cannot generate: a forced `tool_choice` returns
a note id from an enum, and every rendered bullet is asserted to be a byte-exact
substring of a stored chunk. The report **must** generate — that is the feature — so the
equivalent protection is that every claim is anchored to something checkable.

Without it, the report is a model's impression of an interview it did not attend,
delivered to someone who will believe it about themselves. That is the whole argument
for this module.

Two kinds, because one is not enough:

* **Presence** — "you said X" — cites utterance indices into the record.
* **Absence** — "you never made this point" — cites the source chunk it was expected
  from. Two of the four rubric dimensions produce their most valuable findings this way,
  and a rule demanding an utterance index would force the generator to drop them or
  invent a citation.

Absence is adjudicated by the **live tracker's** verdict, never re-derived (FR78a). The
tracker already decided "did they say this" during the interview, at τ_track, from the
mic stream only. A report that recomputes it will eventually disagree with the checklist
the user watched, and there is no principled way for them to know which to believe.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from interview_prep_recall.report.record import SessionRecord


class ReportSection(Enum):
    """FR77. Four rubric dimensions (D-U10) plus the two summaries the user asked for."""

    PREP_COVERAGE = "prep_coverage"
    ROLE_FIT = "role_fit"
    RESUME_USE = "resume_use"
    CRAFT = "craft"
    WHAT_WENT_WELL = "what_went_well"
    WHAT_TO_CHANGE = "what_to_change"


class EvidenceKind(Enum):
    PRESENCE = "presence"
    ABSENCE = "absence"


class RejectionReason(Enum):
    NO_EVIDENCE = "no_evidence"
    UNRESOLVABLE_INDEX = "unresolvable_index"
    CONTRADICTED_BY_TRACKER = "contradicted_by_tracker"
    UNKNOWN_SOURCE = "unknown_source"


@dataclass(frozen=True)
class Evidence:
    kind: EvidenceKind
    utterance_indices: tuple[int, ...] = ()
    source_note_id: str | None = None


@dataclass(frozen=True)
class Finding:
    section: ReportSection
    text: str
    evidence: Evidence


@dataclass(frozen=True)
class Rejection:
    finding: Finding
    reason: RejectionReason


@dataclass(frozen=True)
class VerifiedFindings:
    """Survivors and casualties, both.

    Rejected findings are **counted and surfaced**, never silently dropped. A report that
    quietly discarded a third of what the model produced would read as complete while
    being nothing of the sort, and the user has no way to notice.
    """

    accepted: tuple[Finding, ...]
    rejected: tuple[Rejection, ...]

    @property
    def rejection_count(self) -> int:
        return len(self.rejected)


def verify(
    findings: list[Finding],
    record: SessionRecord,
    *,
    missed_note_ids: frozenset[str],
    known_note_ids: frozenset[str],
) -> VerifiedFindings:
    """Split findings into those that resolve and those that do not (FR78).

    `missed_note_ids` is the **tracker's** set of trackable points it never marked —
    passed in, never recomputed here (FR78a). `known_note_ids` is every chunk in the
    context set, so an absence claim naming a chunk that does not exist is caught rather
    than treated as an uncovered point.
    """
    accepted: list[Finding] = []
    rejected: list[Rejection] = []

    for finding in findings:
        reason = _reject_reason(
            finding, record, missed_note_ids=missed_note_ids, known_note_ids=known_note_ids
        )
        if reason is None:
            accepted.append(finding)
        else:
            rejected.append(Rejection(finding=finding, reason=reason))

    return VerifiedFindings(accepted=tuple(accepted), rejected=tuple(rejected))


def _reject_reason(
    finding: Finding,
    record: SessionRecord,
    *,
    missed_note_ids: frozenset[str],
    known_note_ids: frozenset[str],
) -> RejectionReason | None:
    evidence = finding.evidence

    if evidence.kind is EvidenceKind.PRESENCE:
        if not evidence.utterance_indices:
            return RejectionReason.NO_EVIDENCE
        # Every index must resolve. One invented index in a list of real ones is exactly
        # the shape a plausible-but-wrong citation takes.
        if any(record.get(i) is None for i in evidence.utterance_indices):
            return RejectionReason.UNRESOLVABLE_INDEX
        return None

    if evidence.source_note_id is None:
        return RejectionReason.NO_EVIDENCE
    if evidence.source_note_id not in known_note_ids:
        return RejectionReason.UNKNOWN_SOURCE
    if evidence.source_note_id not in missed_note_ids:
        # The tracker saw this point covered. FR78a: the report does not get a second
        # opinion — a checklist that ticked green during the interview and a report that
        # says "you never mentioned it" cannot both be authoritative.
        return RejectionReason.CONTRADICTED_BY_TRACKER
    return None
