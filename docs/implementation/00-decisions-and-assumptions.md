# Decision Log & Assumptions

Every decision that closes an ambiguity in the PRD or the safety review is recorded here with
an ID. Requirements, design, tasks, and tests cite these IDs. If a decision is reversed, the
citing artifacts are the change list.

**Source artifacts:** [`../interviewpreprecallprd.md`](../interviewpreprecallprd.md) (product plan),
[`../build-plan-safety-review.md`](../build-plan-safety-review.md) (pre-implementation review, amendments A1–A23).

---

## Decisions requiring the user — resolved

| ID | Question | Decision | Consequence |
|---|---|---|---|
| **D-U1** | v1 scope | **In:** multiple note sets (US-A3), cloud STT (FR18–21), progress tracker (Epic G). **Out of v1:** `.docx` import (FR1b), deferred to post-v1 (M9 is the last v1 milestone, so "M9" was an ambiguous label for the deferred bucket). | Epic G moves from stretch to core. Data model is multi-set from day one. |
| **D-U2** | Both audio streams | **Both interviewer (loopback) and user (mic) capture are mandatory in v1.** FR6's "optionally capture microphone" is superseded. | Mic is no longer an Epic G dependency that can be dropped; it is a session prerequisite. Preflight must validate both devices. |
| **D-U3** | LLM failure behavior | **Show the stage-1 fallback match, visually marked as degraded**, gated behind a higher confidence bar (τ_degraded). | Resolves the §10b vs US-D2 contradiction. Overlay has two visual states for content: confirmed and degraded. |
| **D-U4** | Target platform | **Windows 11.** | FR14 capture exclusion is available. The startup check (FR38) is still built, but as a guard, not a gate on an uncertain platform. |

## Decisions made by engineering judgement — recorded, reversible

| ID | Decision | Rationale | Reverse cost |
|---|---|---|---|
| **D-1** | **Concurrency backbone is threads + bounded queues + Qt signals.** `asyncio` is confined inside the cloud STT backend, which owns a private event loop in its own thread. No application-wide event loop. | The default path (local STT) needs no async. Making the whole app async to serve an optional backend inverts the cost. `faster-whisper`/CTranslate2 and torch release the GIL during inference, so threads genuinely parallelize the CPU-bound work. Qt's queued signal/slot connections are the supported way to cross into the GUI thread. | High after M3. This is the load-bearing decision — pick it now or fork the codebase later. |
| **D-2** | **The STT interface is specified before any backend is written** (§2 of the design doc), and is written against the *local* backend's constraints first. | Review A8/BC-4. PRD Phase 2 builds cloud first, which would shape the interface around WebSocket conveniences (native interim results, server-side finalization) that local Whisper cannot provide. | Low now, high later. |
| **D-3** | **Notes persist as one JSON file per note set** under `%APPDATA%`, atomic-write + 5-deep backup rotation. Embeddings cache to a separate `.npz` keyed by content hash. | Human-readable, diffable, trivially exportable (FR30), no DB dependency. The corpus is a few thousand words — no query engine is warranted. | Low. Format is versioned (FR31). |
| **D-4** | **"Utterance" is defined as a finalized transcript span**, terminated by ≥700 ms silence, 10 s max duration, or session stop; minimum 3 words and 12 characters. Matching runs per utterance, never per audio chunk. | PRD FR8 (2–4 s audio chunks) and FR9 ("each transcribed utterance") are different units. Matching per audio chunk would fire mid-sentence and multiply LLM calls ~3×. | Low. Tunable constants. |
| **D-5** | **Overlay content is user-authored verbatim text only.** Notes carry an explicit `bullets[]` field, authored or confirmed by the user at import. Nothing is summarized at match time. | Resolves FR11 ("headline + 1–3 bullets") against §4 retrieval-only. Structure is chosen by the user at import, which FR2 already requires to be reviewable, so no generation is needed at match time. | Low. |
| **D-6** | **A note with no bullets renders as headline + verbatim body truncated at a sentence boundary (≤240 chars)**, and is flagged "not overlay-optimised" in the editor. | Degrades honestly rather than blocking, and still emits zero generated text. | Low. |
| **D-7** | **Session lifecycle is an explicit state machine**; health is an orthogonal attribute, not a state. | Prevents the combinatorial `RUNNING_BUT_STT_DEGRADED_AND_CLOUD_FALLEN_BACK` state explosion that ad-hoc booleans produce. | Medium. |
| **D-8** | **Speaker attribution is stream-based with echo detection**, not diarization. Preflight cross-correlates mic and loopback; high correlation warns the user that headphones are needed. Runtime suppresses interviewer-stream matching when a span is detected as mic echo. | RC-8. D-U2/D-U1 promote this from a stretch caveat to a v1 correctness concern. Full acoustic echo cancellation is out of scope for v1. | Medium. |
| **D-9** | **The Anthropic model ID is configuration, not a constant** (default `claude-haiku-4-5-20251001`). | BC-5. Pinning is right; hard-coding it into a PyInstaller exe means a deprecation requires a rebuild. | Low. |
| **D-10** | **Matching runs only on the interviewer stream.** The mic stream feeds the progress tracker exclusively. | The product surfaces prep in response to what the interviewer asks (D-U2's stated intent). Matching on the user's own speech would surface notes about what they just said. | Low. |
| **D-11** | **One stage-2 LLM call in flight at a time**, latest-issued wins. Superseded requests are cancelled and their responses discarded on arrival. | FR32 as amended. Also bounds cost and rate-limit exposure (RC-5). | Low. |
| **D-12** | **`keyring` (Windows Credential Manager backend) for API keys**; no custom credential code. | FR19. | Low. |

## Assumptions — unverified, and what breaks if wrong

| ID | Assumption | If wrong |
|---|---|---|
| **AS-1** | `faster-whisper` on the target CPU achieves p95 < 3 s end-to-end for a 4 s chunk. | Local default is not viable; cloud STT (already in v1 per D-U1) becomes the default and §10a's recommendation inverts. **Measured in M2 — this is a gate, not a hope.** |
| **AS-2** | `pyaudiowpatch` can open WASAPI loopback and a mic input device concurrently and stably for 60 minutes. | D-U2's dual-stream requirement needs a different capture library. **Measured in M1.** |
| **AS-3** | `all-MiniLM-L6-v2` cosine similarity separates relevant from irrelevant notes well enough that τ_floor suppresses most small talk. | Stage-2 call volume and cost rise sharply; may need a question-detection heuristic before stage 2. **Measured in M4.** |
| **AS-4** | The user authors or confirms bullet-shaped notes at import (D-5). | Most notes fall to the D-6 truncation path and the overlay is less glanceable than FR11 intends. Mitigated by the importer nudging toward bullets. |
| **AS-5** | Interviews are single-interviewer or the user tolerates degraded attribution on panels. | PRD §12 already flags this. No v1 mitigation. |
| **AS-6** | Sentence-level chunking of `.md` by `##`/`###` headers matches how the user actually writes notes. | Import produces poor chunks; mitigated because FR2 requires review-before-save. |
| **AS-7** | Anthropic API p95 latency for a ~500-token request stays within the few-hundred-ms budget in §7. | The 2–3 s overall target is missed on the matching path; D-11's supersession keeps it from compounding. **Measured in M4.** |

## Open questions — do not block v1, revisit at the stated milestone

| ID | Question | Revisit |
|---|---|---|
| **OQ-1** | Does stage 2 (LLM) measurably beat stage-1-only matching on real transcripts? Review A21. | **M4 gate.** If the delta is small, D-U3's degraded path becomes the normal path and the hard internet dependency is reconsidered. |
| **OQ-2** | Is τ_visible (snippet auto-clear, 25 s default) right for real interview pacing? | M5, then rehearsal in G2. |
| **OQ-3** | Should the progress tracker require headphones outright rather than warning? | M7, after D-8's echo detection is measured. |
| **OQ-4** | Local matching model (Ollama) as a fully-offline alternative to stage 2. PRD §10b. | Post-v1, informed by OQ-1. |
