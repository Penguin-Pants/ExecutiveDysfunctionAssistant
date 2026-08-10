"""Note import and chunking (T3.5, FR1a, FR2, FR42).

Two things here decide downstream quality, and both were unspecified until the review
rounds forced them out:

1. **Strategy selection for `.txt`** is auto-detected, not guessed per-implementer:
   if two or more lines match `^\\s*Q:` the Q/A convention wins, otherwise blank-line
   splitting. The chosen strategy is reported so the review UI can name it and let the
   user switch before saving.

2. **The headline mapping** (design §5a). Only `headline` is embedded, so which text
   lands there determines all stage-1 matching quality.

Bullets are *proposed*, never imposed, and every proposal is a verbatim substring of
the source (FR42). Nothing here generates text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from interview_prep_recall.notes.model import ContextSet, Note, SourceKind

MAX_BULLETS = 3
"""FR11 renders at most three."""

MIN_BULLET_CHARS = 12
LONG_HEADLINE_CHARS = 120
"""Above this, or with no '?', the importer flags the headline for review."""

_QA_LINE = re.compile(r"^\s*Q:", re.MULTILINE)
_MD_HEADER = re.compile(r"^(#{2,3})\s+(.*)$")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


class ChunkStrategy(StrEnum):
    MD_HEADER = "md_header"
    QA_CONVENTION = "qa_convention"
    BLANK_LINE = "blank_line"


@dataclass
class ProposedNote:
    """A chunk awaiting the FR2 review step. Not yet a Note."""

    headline: str
    body: str
    bullets: list[str]
    needs_headline_review: bool
    source_line: int


@dataclass
class ImportResult:
    strategy: ChunkStrategy
    proposals: list[ProposedNote]

    @property
    def needs_review(self) -> bool:
        """FR2: save is blocked until the user confirms. Always true by construction."""
        return True


def detect_strategy(text: str, filename: str | None = None) -> ChunkStrategy:
    if filename and filename.lower().endswith(".md"):
        return ChunkStrategy.MD_HEADER
    if len(_QA_LINE.findall(text)) >= 2:
        return ChunkStrategy.QA_CONVENTION
    return ChunkStrategy.BLANK_LINE


def propose_bullets(headline: str, body: str) -> list[str]:
    """Sentence-split the body into candidate bullets, verbatim (FR42).

    Returns [] rather than inventing structure when the body is empty — that note then
    takes the D-6 truncation path in the overlay and is flagged in the editor.
    """
    if not body.strip():
        return []
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(body.strip()) if s.strip()]
    bullets = [s for s in sentences if len(s) >= MIN_BULLET_CHARS][:MAX_BULLETS]
    haystack = f"{headline}\n{body}"
    return [b for b in bullets if b in haystack]


def _headline_needs_review(headline: str) -> bool:
    return len(headline) > LONG_HEADLINE_CHARS or "?" not in headline


def _make(headline: str, body: str, line: int) -> ProposedNote:
    headline = headline.strip()
    body = body.strip()
    return ProposedNote(
        headline=headline,
        body=body,
        bullets=propose_bullets(headline, body),
        needs_headline_review=_headline_needs_review(headline),
        source_line=line,
    )


def _chunk_md(text: str) -> list[ProposedNote]:
    out: list[ProposedNote] = []
    headline: str | None = None
    buf: list[str] = []
    start = 1
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = _MD_HEADER.match(line)
        if match:
            if headline is not None:
                out.append(_make(headline, "\n".join(buf), start))
            headline, buf, start = match.group(2), [], lineno
        elif headline is not None:
            buf.append(line)
    if headline is not None:
        out.append(_make(headline, "\n".join(buf), start))
    return out


def _chunk_qa(text: str) -> list[ProposedNote]:
    out: list[ProposedNote] = []
    headline: str | None = None
    buf: list[str] = []
    start = 1
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("Q:"):
            if headline is not None:
                out.append(_make(headline, "\n".join(buf), start))
            headline, buf, start = stripped[2:].strip(), [], lineno
        elif stripped.startswith("A:"):
            buf.append(stripped[2:].strip())
        elif headline is not None:
            buf.append(line)
    if headline is not None:
        out.append(_make(headline, "\n".join(buf), start))
    return out


def _chunk_blank_line(text: str) -> list[ProposedNote]:
    out: list[ProposedNote] = []
    lineno = 1
    for block in re.split(r"\n\s*\n", text):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if lines:
            # First line is the headline; the rest is the body (design §5a).
            out.append(_make(lines[0], "\n".join(lines[1:]), lineno))
        lineno += block.count("\n") + 2
    return out


_CHUNKERS = {
    ChunkStrategy.MD_HEADER: _chunk_md,
    ChunkStrategy.QA_CONVENTION: _chunk_qa,
    ChunkStrategy.BLANK_LINE: _chunk_blank_line,
}


def import_text(
    text: str, filename: str | None = None, strategy: ChunkStrategy | None = None
) -> ImportResult:
    chosen = strategy or detect_strategy(text, filename)
    return ImportResult(strategy=chosen, proposals=_CHUNKERS[chosen](text))


def build_context_set(
    name: str, proposals: list[ProposedNote], kind: SourceKind = SourceKind.PREP
) -> ContextSet:
    """Materialise reviewed proposals into a ContextSet (post-FR2 confirmation)."""
    context_set = ContextSet(
        name=name,
        notes=[
            Note(headline=p.headline, body=p.body, bullets=list(p.bullets), kind=kind)
            for p in proposals
        ],
    )
    context_set.verify()
    return context_set


def add_source(context_set: ContextSet, proposals: list[ProposedNote], kind: SourceKind) -> int:
    """Import one source into an existing set, replacing whatever that kind held (FR66).

    Replace rather than append: re-importing a job description means *this* is the job
    description now, and appending would leave the superseded version competing for the
    same enum slots as the new one, with no way for the user to tell which won.

    The other four kinds are untouched — FR66's actual requirement, and the reason this
    filters rather than rebuilding the set, so survivors keep their ids and vectors.
    """
    context_set.remove_kind(kind)
    for proposal in proposals:
        context_set.add(
            Note(
                headline=proposal.headline,
                body=proposal.body,
                bullets=list(proposal.bullets),
                kind=kind,
            )
        )
    context_set.verify()
    return len(proposals)
