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
| **D-U5** | Panic clear lifecycle | **Wipe, stop capture, stay resumable.** Purge clears buffers, transcript, and overlay; capture stops; the session holds in a `WIPED` state that resumes in ~1 s without re-running preflight. | Adds a seventh state to §6. Resolves the contradiction between a state machine that ended the session and an FR60 single-press control implying it was cheap. The user gets an unambiguous stop *and* a fast recovery — the two properties that were in tension. |
| **D-U7** | Overlay palette | **The overlay is a neutral translucent gray panel, not PRISM's plum** — stated by the user as overriding PRISM. PRISM still governs the overlay's typography, 20px radius, spacing ladder and semantic rail colours, and governs the app chrome entirely. | A saturated surface tints the video behind it; a neutral translucent one does not. Scoped to the overlay so the rest of the product stays on-brand. **D-U7a resolved: neither — brightness is a user control** (FR65), spanning a dark band and a light band with the unreadable mid-gray stepped over. Opacity stays a separate control (FR24). |
| **D-U6** | Target hardware | **Two machines: a 2025-or-newer laptop, and a desktop (AMD Ryzen, 32 GB RAM, NVIDIA RTX 5070).** | See the measurement discipline below — this one has a trap in it. |

### D-U6 measurement discipline — read before running the AS-1 gate

The desktop has a discrete GPU. `faster-whisper` will use CUDA if it finds it, and would produce an
inference-tail number several times better than any laptop achieves. **Measuring AS-1 there, with
CUDA active, validates a machine most sessions will not run on** and would green-light a local
default that misses the target in practice.

So:

1. **The AS-1 gate is measured CPU-only, on the 2025 laptop.** `device="cpu"`, CUDA explicitly
   disabled. This is the number that decides whether local STT can be the default (FR18), because
   NFR2 requires the product to work without a discrete GPU.
2. **The desktop's CUDA number is recorded separately** as an upper bound, and never substituted
   for (1).
3. **CUDA is used opportunistically at runtime** (NFR7): if a compatible GPU is present, the local
   backend uses it and the user gets a faster session for free. It is an optimisation, never a
   requirement.

If the interviews themselves will be taken on the desktop, the practical latency will be the CUDA
number — but the gate stays CPU-anchored, because a build that only works on a 5070 is not the
product described in the PRD.

## Decisions made by engineering judgement — recorded, reversible

| ID | Decision | Rationale | Reverse cost |
|---|---|---|---|
| **D-1** | **Concurrency backbone is threads + bounded queues + Qt signals.** `asyncio` is confined inside the cloud STT backend, which owns a private event loop in its own thread. No application-wide event loop. | The default path (local STT) needs no async. Making the whole app async to serve an optional backend inverts the cost. `faster-whisper`/CTranslate2 and torch release the GIL during inference, so threads genuinely parallelize the CPU-bound work. Qt's queued signal/slot connections are the supported way to cross into the GUI thread. | High after M3. This is the load-bearing decision — pick it now or fork the codebase later. |
| **D-2** | **The STT interface is specified before any backend is written** (§2 of the design doc), and is written against the *local* backend's constraints first. | Review A8/BC-4. PRD Phase 2 builds cloud first, which would shape the interface around WebSocket conveniences (native interim results, server-side finalization) that local Whisper cannot provide. | Low now, high later. |
| **D-3** | **Notes persist as one JSON file per note set** under `%APPDATA%`, atomic-write + 5-deep backup rotation. Embeddings cache to a separate `.npz` keyed by note-set UUID + embedding-model slug, with per-note content hashes stored inside it for selective re-embedding (design §4). | Human-readable, diffable, trivially exportable (FR30), no DB dependency. The corpus is a few thousand words — no query engine is warranted. | Low. Format is versioned (FR31). |
| **D-4** | **"Utterance" is defined as a finalized transcript span**, terminated by ≥700 ms silence, 10 s max duration, or session stop; minimum 3 words and 12 characters. Matching runs per utterance, never per audio chunk. | PRD FR8 (2–4 s audio chunks) and FR9 ("each transcribed utterance") are different units. Matching per audio chunk would fire mid-sentence and multiply LLM calls ~3×. | Low. Tunable constants. |
| **D-5** | **Overlay content is user-authored verbatim text only.** Notes carry an explicit `bullets[]` field, authored or confirmed by the user at import. Nothing is summarized at match time. | Resolves FR11 ("headline + 1–3 bullets") against §4 retrieval-only. Structure is chosen by the user at import, which FR2 already requires to be reviewable, so no generation is needed at match time. | Low. |
| **D-6** | **A note with no bullets renders as headline + verbatim body truncated at a sentence boundary (≤240 chars)**, and is flagged "not overlay-optimised" in the editor. | Degrades honestly rather than blocking, and still emits zero generated text. | Low. |
| **D-7** | **Session lifecycle is an explicit state machine**; health is an orthogonal attribute, not a state. | Prevents the combinatorial `RUNNING_BUT_STT_DEGRADED_AND_CLOUD_FALLEN_BACK` state explosion that ad-hoc booleans produce. | Medium. |
| **D-8** | **Speaker attribution is stream-based with echo detection**, not diarization. Preflight cross-correlates mic and loopback; high correlation warns the user that headphones are needed. At runtime the **echoed mic span is dropped from the tracker**; the interviewer utterance is never suppressed (design §5a). | RC-8. D-U2/D-U1 promote this from a stretch caveat to a v1 correctness concern. Full acoustic echo cancellation is out of scope for v1. | Medium. |
| **D-9** | **The Anthropic model ID is configuration, not a constant** (default `claude-haiku-4-5-20251001`). | BC-5. Pinning is right; hard-coding it into a PyInstaller exe means a deprecation requires a rebuild. | Low. |
| **D-10** | **Matching runs only on the interviewer stream.** The mic stream feeds the progress tracker exclusively. | The product surfaces prep in response to what the interviewer asks (D-U2's stated intent). Matching on the user's own speech would surface notes about what they just said. | Low. |
| **D-11** | **One stage-2 LLM call in flight at a time, plus one pending slot; latest-issued wins.** A superseded in-flight request is **not cancelled** — Python cannot cancel a blocking call on a pool thread — it runs to its 5 s timeout and its response is discarded by the sequence gate. See design §5a for the dispatch policy. *(Corrected: this previously said superseded requests "are cancelled", which the design explicitly says is impossible and must never be relied on.)* | FR32 as amended. Also bounds cost and rate-limit exposure (RC-5). | Low. |
| **D-20** | **The STT worker restart budget resets when preflight passes.** | FR61 is per session; the counter previously persisted for the process lifetime. | Low. |
| **D-21** | **`BoundedFrameQueue.push` always copies into a `bytearray`.** | `zero()` cannot wipe immutable `bytes` (FR15 would be silently false), and WASAPI callbacks reuse a scratch buffer, so storing the caller's array by reference would corrupt queued frames. | Low. |
| **D-22** | **A panic clear is undone only by the user** — `resume(automatic=True)` from `WIPED` raises. | A device-return callback firing after the button was pressed would restart capture the user deliberately stopped. | Low. |
| **D-23** | **The LLM degradation switch is applied to the pipeline before the indicator changes**, and toggling it with no pipeline attached raises. | An indicator claiming local-only while the API is still being called is a privacy-facing false statement, not a cosmetic lag. | Low. |
| **D-24** | **Purge runs every step even when a hook throws**, collecting failures rather than aborting. | `cancel_network` runs first and is the most likely to fail; aborting there leaves capture running and nothing cleared, on the degraded session that most needs the purge. | Low. |
| **D-25** | **The capture clock is re-anchored on every (re)connect.** A reconnect starts a new server-side stream numbered from zero. | Without it the first post-reconnect event maps tens of seconds backwards, the ordering guard discards it and every event after it, and the stream goes permanently silent while reporting READY. | Low. |
| **D-26** | **`x = y or Default()` is banned for injected collaborators; use `if y is None`.** | `DiagnosticRing.__len__` makes an empty ring falsy, so the idiom silently discarded an injected ring and wrote to an orphan. It was present in already-merged code (`MatchingPipeline`, `SessionManager`, `Preflight`). | Low, but it was live. |
| **D-27** | **Cloud egress is lit before the socket opens and cleared only after it closes.** | The error is then always in the over-reporting direction. An indicator saying "not leaving the device" while a socket is open is a false privacy statement; saying it a handshake early is cosmetic. | Low. |
| **D-35** | **`WIPED` is retained as an enum member with no edges in or out**, and a test asserts it stays unreachable. | The state still describes a real behaviour that may return. Deleting it loses the vocabulary; leaving it wired loses the guarantee. The test is against the transition table, not against a handful of driven paths — the point is that *no* edge exists, which sampling cannot show. | Low. |
| **D-36** | **The WIPED branches in `resume()` and `end_session()` were deleted, not disabled in place.** | Unreachable code cannot be tested, and untestable branches that "handle" impossible cases rot into wrong answers. D-22's reasoning — a machine event must never undo a deliberate stop — survives in this record and is still *enforced*, because `PANIC` is absent from `AUTO_RESUME_CAUSES`. | Low. |
| **D-33** | **Schema v1 note sets migrate to v2 mapped to `PREP`, preserving IDs.** | `PREP` is the only kind that preserves existing behaviour, since v1 notes were trackable and FR70 still permits tracking on `PREP`. IDs must survive because the embedding cache is keyed on them (FR34). Without the migration, every existing user's notes load as corrupt and recovery finds every backup equally unreadable. | **Was a live data-loss path** in the first draft of M10 — found in review. |
| **D-34** | **Report findings carry either presence or absence evidence**, and absence is adjudicated by the tracker's mechanism (FR78a), not re-derived. | Two of four rubric dimensions produce their best findings by absence, which cannot cite an utterance. And a report that re-derives coverage will eventually disagree with the checklist the user watched live, with no principled way to know which to believe. | Low. |
| **D-29** | **`SourceKind` is immutable on a chunk**; reclassifying means delete and re-import. | A chunk's kind drives its threshold, its tracker eligibility and its enum quota. Mutating it in place would silently move a chunk between those regimes with a stale embedding still in the index. | Low. |
| **D-30** | **Stage-2 candidates are capped per kind (2), not globally.** | Otherwise a long job description dominates the enum by sheer chunk count and crowds out the prep notes the product exists to surface. | Low. |
| **D-31** | **Every report finding must cite the utterance it rests on**, or it is rejected before display. | The overlay cannot fabricate because it cannot generate. The report must generate, so the equivalent protection is anchoring. Without it the report is a model's impression of an interview it did not attend, told to someone who will believe it about themselves. | Medium — it is the whole trustworthiness argument for M11. |
| **D-32** | **Panic clear destroys the in-progress session only; previously saved sessions survive.** | Panic clear is single-action and unconfirmed (FR60). Destroying earlier interviews on one keypress is an irreversible surprise. FR83's delete-all is the deliberate route and FR87 signposts it there. | **Open — OQ-7.** Argued both ways in `07-…` §3. |
| **D-28** | **Frames in flight during a cloud→local fallback are dropped, not replayed.** | Replaying the tail double-transcribes the overlap, so the assembler builds two utterances from one span and matching fires twice on the same question. A missing half-second beats a duplicated question. | Low. |
| **D-12** | **`keyring` (Windows Credential Manager backend) for API keys**; no custom credential code. | FR19. | Low. |
| **D-17** | **PRISM is the design system for every UI surface.** It supersedes the tokens design §9b previously invented for the overlay. | A real design system beats per-component tokens, and this is the user's own brand system. | Low now; high once the overlay is built. |
| **D-18** | **The overlay is exempt from PRISM §6's "labels sit outside the card" rule.** Every other surface obeys it. | The overlay floats over a video call and has no canvas; "outside the card" would mean drawing onto the call. | Low. |
| **D-19** | **Headline in Plex Mono, bullets in Plex Sans.** | PRISM assigns mono to display and sans to body, and the split serves legibility: monospace scans more slowly, and the bullets are what gets read mid-sentence. | Low. |

## User product decisions — 2026-08-10 context sources & report

| ID | Decision | Consequence accepted |
|---|---|---|
| **D-U8** | The raw transcript is **persisted**, not dropped after report generation. | FR16 rewritten. Encryption at rest, session list, per-session delete and a retention default become requirements, not niceties. |
| **D-U9** | The report analyzes the **full meeting, both sides**, including the interviewer's reactions. | The saved artifact characterizes a specific named person. FR63's disclosure becomes insufficient; FR85 requires re-acknowledgement. |
| **D-U11** | **The panic control is on hold and now only pauses.** No wipe, no purge, no `WIPED` state. | The product loses its only in-session emergency data destruction, arriving alongside D-U8 which made transcripts persist — so nothing is destroyable mid-interview any more. FR64 superseded by FR64a; FR86 moot; OQ-7 closed unresolved. D-U5's "wipe, stop capture, stay resumable" is withdrawn. |
| **D-U10** | **All four rubric dimensions** — prep coverage, JD fit, resume utilisation, interview craft. | M11 hard-depends on M10; a missing source must be declared in the report, not silently skipped (FR77). |

## Assumptions — unverified, and what breaks if wrong

| ID | Assumption | If wrong |
|---|---|---|
| **AS-1** | `faster-whisper` `base.en` int8, **CPU-only on the 2025 laptop** (D-U6), achieves **p95 < 900 ms of inference tail** after utterance finalisation — the STT slice of the NFR1 budget in design §9a, not the whole 3 s. | Local default is not viable; cloud STT (already in v1 per D-U1) becomes the default and §10a's recommendation inverts. **Measured in M2 — this is a gate, not a hope.** |
| **AS-2** | `pyaudiowpatch` can open WASAPI loopback and a mic input device concurrently and stably for 60 minutes. | D-U2's dual-stream requirement needs a different capture library. **Measured in M1.** |
| **AS-3** | `all-MiniLM-L6-v2` cosine similarity separates relevant from irrelevant notes well enough that τ_floor suppresses most small talk. | Stage-2 call volume and cost rise sharply; may need a question-detection heuristic before stage 2. **Measured in M4.** |
| **AS-4** | The user authors or confirms bullet-shaped notes at import (D-5). | Most notes fall to the D-6 truncation path and the overlay is less glanceable than FR11 intends. Mitigated by the importer nudging toward bullets. |
| **AS-5** | Interviews are single-interviewer or the user tolerates degraded attribution on panels. | PRD §12 already flags this. No v1 mitigation. |
| **AS-6** | Sentence-level chunking of `.md` by `##`/`###` headers matches how the user actually writes notes. | Import produces poor chunks; mitigated because FR2 requires review-before-save. |
| **AS-8** | **The Deepgram and ElevenLabs wire protocols are as implemented** — message names (`CloseStream`, `start`/`end`), envelope shapes, and timestamp semantics (Deepgram start+duration, ElevenLabs start/end). Written from documentation, **not verified against a live endpoint**. | The backends connect and transcribe nothing, or finals never flush. Contained: both are off the default path (FR18) and FR21 falls back to local. **Verify with a real key alongside T9.5.** |
| **AS-7** | Anthropic API p95 latency for a ~500-token request stays within the **800 ms stage-2 allocation in design §9a's latency budget**. *(Previously cited §7, which is the health model and contains no budget, and said "a few hundred ms", which is not the number the design commits to.)* | The 2–3 s overall target is missed on the matching path; D-11's supersession keeps it from compounding. **Measured in M4.** |

## Open questions — do not block v1, revisit at the stated milestone

| ID | Question | Revisit |
|---|---|---|
| **OQ-1** | Does stage 2 (LLM) measurably beat stage-1-only matching on real transcripts? Review A21. | **M4 gate.** If the delta is small, D-U3's degraded path becomes the normal path and the hard internet dependency is reconsidered. |
| **OQ-2** | Is τ_visible (snippet auto-clear, 25 s default) right for real interview pacing? | M5, then rehearsal in G2. |
| **OQ-3** | Should the progress tracker require headphones outright rather than warning? | M7, after D-8's echo detection is measured. |
| **OQ-4** | Local matching model (Ollama) as a fully-offline alternative to stage 2. PRD §10b. | Post-v1, informed by OQ-1. |
| ~~**OQ-6**~~ **RESOLVED — PRISM absorbed the fix.** `--ink-400 #9C94A8` is now the dark-mode secondary text token in PRISM itself. Original finding: | ~~PRISM's dark-mode secondary text token fails WCAG AA, and dark is the default mode.** `--ink-600` at 80% over `--plum-900` composites to `#504B59` — **1.96:1**, against the 4.5:1 required for 15px body copy; solid over `--plum-950` it is 2.51:1. PRISM §1 explicitly asks for this to be re-verified, and it does not pass. Proposal: `--ink-400 #9C94A8` (5.69:1 / 6.06:1). This app uses `--ink-400` now rather than waiting — an inaccessible default is not shippable while a token question is open — but PRISM itself should probably absorb the fix. | **Needs the user**, as a change to their design system. Not blocking: the app already uses the accessible value. |
| ~~**OQ-5**~~ **RESOLVED — `--amber-500 #FFC93D` added to PRISM** as its fifth palette dot, semantic "warning / degraded". Original finding: | ~~PRISM has no warning token. Its four semantic dots are danger, info, success, highlight. Two states here are none of those: a degraded match, and data leaving the device. Both mean "proceed, but know this" — red overstates them and purple already means "new". Proposal: add `--amber-500: #FFC93D`, taken from the existing `--grad-3` stop so it stays in-family. Implemented in the mockup and in §9b pending approval; the fallback is `--purple-500` for both, at the cost that blue and purple are harder to separate at a glance than blue and amber, on the one surface where glanceability is the point. | **Needs the user.** Blocks nothing, but the mockup already assumes the proposal. |
