"""Stage-2 constrained selector (T4.2, FR10, FR48 — design §5a).

FR10 is an *architectural* guarantee, not a prompting convention: `tool_choice` is
forced to a single tool whose only field is an enum of the candidate note IDs plus
"none". The model structurally cannot emit freeform text, so it cannot fabricate a
note the user did not write.

Two things this module refuses to do, both deliberate:
  * put more than the prefiltered candidates in the enum (FR48 — the PRD's own code
    sample had this bug, sending every note ID on every call);
  * accept a response that is not a `select_note` tool call, even if it looks helpful.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from interview_prep_recall.matching.prefilter import Candidate
from interview_prep_recall.stt.assembler import Utterance

TOOL_NAME = "select_note"
NONE_CHOICE = "none"

DEFAULT_MODEL_ID = "claude-haiku-4-5-20251001"
MAX_TOKENS = 50
TEMPERATURE = 0

REQUEST_TIMEOUT_S = 5.0
"""Hard per-request timeout (design §5).

Load-bearing for FR59: the call cannot be cancelled, so this bounds how long a
pre-purge request can still be outstanding. Without it "no response from before the
purge reaches the screen" would rest solely on the gate, with an unbounded window.
"""

SYSTEM_PROMPT = (
    "You match a live interview question to the candidate's own prepared material. "
    "Each option is labelled with its source: prep (a point they planned to make), "
    "resume (their own experience), role (the job description), company (facts about "
    "the employer), interviewer (about the person asking). "
    "Select the single option that answers what was just asked. If none of them "
    'genuinely addresses the question, select "none". Prefer "none" over a weak '
    "match — a wrong note shown mid-interview is worse than no note."
)
"""FR71. The kinds are named here, not just stamped on each line, because a bare
`kind=role` tells the model nothing about what role *means* in this product."""


class SelectorProtocolError(Exception):
    """The response was not a forced `select_note` tool call, or named an ID we did
    not offer. Treated as a failure so the FR49 degraded path handles it, rather than
    trusting whatever came back."""


class MessagesClient(Protocol):
    """The slice of the Anthropic Messages API this module uses.

    Narrow on purpose: tests substitute a fake without the SDK installed, and the
    surface we depend on stays visible in one place.
    """

    def create(self, **kwargs: Any) -> Any: ...


def build_tool(candidates: list[Candidate]) -> dict[str, Any]:
    """One tool, one field, an enum of exactly the candidates plus "none" (FR48)."""
    return {
        "name": TOOL_NAME,
        "description": (
            "Select the single best-matching prepared note for the live question, or none."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "string",
                    "enum": [c.note_id for c in candidates] + [NONE_CHOICE],
                }
            },
            "required": ["note_id"],
        },
    }


def build_user_message(utterance: Utterance, candidates: list[Candidate]) -> str:
    lines = [
        "Recent conversation (context only, do not match against this):",
        utterance.context,
        "",
        "The interviewer just asked:",
        utterance.text,
        "",
        "Candidate material:",
    ]
    for candidate in candidates:
        tags = ", ".join(candidate.tags)
        # headline, kind and tags only — never body. Bodies are prepared *answers*;
        # including them costs hundreds of tokens and biases selection toward long notes.
        lines.append(
            f"- id={candidate.note_id} | [{candidate.kind.value}] "
            f"{candidate.headline} | tags: {tags}"
        )
    return "\n".join(lines)


@dataclass(frozen=True)
class Stage2Request:
    model: str
    max_tokens: int
    temperature: int
    system: str
    tools: list[dict[str, Any]]
    tool_choice: dict[str, str]
    messages: list[dict[str, str]]
    timeout: float = REQUEST_TIMEOUT_S

    def as_kwargs(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "system": self.system,
            "tools": self.tools,
            "tool_choice": self.tool_choice,
            "messages": self.messages,
            "timeout": self.timeout,
        }


def build_request(
    utterance: Utterance, candidates: list[Candidate], model_id: str = DEFAULT_MODEL_ID
) -> Stage2Request:
    return Stage2Request(
        model=model_id,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        system=SYSTEM_PROMPT,
        tools=[build_tool(candidates)],
        tool_choice={"type": "tool", "name": TOOL_NAME},
        messages=[{"role": "user", "content": build_user_message(utterance, candidates)}],
    )


def parse_response(response: Any, candidates: list[Candidate]) -> str | None:
    """Return the selected note ID, or None for "none".

    Raises `SelectorProtocolError` if the response is anything other than a
    `select_note` tool call naming an offered ID. A freeform reply is not a soft
    failure to be salvaged — accepting it would convert FR10's structural guarantee
    back into a hope.
    """
    blocks = getattr(response, "content", None) or []
    allowed = {c.note_id for c in candidates} | {NONE_CHOICE}

    for block in blocks:
        if getattr(block, "type", None) != "tool_use":
            continue
        if getattr(block, "name", None) != TOOL_NAME:
            continue
        payload = getattr(block, "input", None) or {}
        note_id = payload.get("note_id")
        if not isinstance(note_id, str) or note_id not in allowed:
            raise SelectorProtocolError(f"select_note returned {note_id!r}, which was not offered")
        return None if note_id == NONE_CHOICE else note_id

    raise SelectorProtocolError("response contained no select_note tool call")


class Stage2Selector:
    def __init__(self, client: MessagesClient, model_id: str = DEFAULT_MODEL_ID) -> None:
        self.client = client
        self.model_id = model_id

    def select(self, utterance: Utterance, candidates: list[Candidate]) -> str | None:
        if not candidates:
            raise ValueError("stage 2 must never be called with an empty candidate list")
        request = build_request(utterance, candidates, self.model_id)
        response = self.client.create(**request.as_kwargs())
        return parse_response(response, candidates)
