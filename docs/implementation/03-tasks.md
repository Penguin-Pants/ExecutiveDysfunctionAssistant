# Task Breakdown

Milestone order differs from the PRD's §11 in two deliberate ways, both from the safety review:
the **STT interface is specified before any backend exists** (D-2/A8), and **notes durability
lands before the overlay** (A1 — notes are the irreplaceable asset, and building UI on an unsafe
store means every later session risks the user's real prep).

Every task states acceptance criteria that are observable. A task is not done because the code
exists; it is done when its criteria are demonstrated.

**Universal definition of done** — applies to every task below, in addition to its own criteria:

1. Acceptance criteria demonstrated, by automated test where the criteria allow.
2. Unit tests for new logic; integration test if the task crosses a component boundary.
3. No new writes to disk outside the design §4 allowlist. **Enforced from M0 by a `pytest` fixture
   that fails any test touching a path outside the allowlist** — not deferred to M6. *(Reviewer A
   and B both caught that scoping this to "once the M6 harness lands" made a mandatory criterion
   unverifiable for the first six milestones, which is most of the project. T6.4's ProcMon trace
   is the full-system check; the fixture is the per-task one.)*
4. Requirement IDs referenced in the commit message.
5. Structural events emitted to the diagnostic ring (FR36) for anything that can fail — no
   silent failure paths.
6. Any decision made while implementing is added to the decision log, or the task is not done.

---

## M0 — Scaffold

| Task | Requirements | Acceptance criteria |
|---|---|---|
| **T0.1** Project skeleton matching design §1 module layout, `pyproject.toml`, pinned deps | — | `pip install -e .` succeeds on a clean Windows 11 venv; the package imports; module tree matches design §1 exactly. |
| **T0.2** CI: lint, type-check, unit tests on Windows runner | — | CI runs on push and fails on lint, `mypy --strict` errors on `stt/interface.py`, or test failure. |
| **T0.3** Diagnostic ring buffer (`diagnostics/ring.py`) | FR36 | Bounded to **2000 events**, evicts oldest; a test asserting no method accepts transcript or note text; export produces JSON with structural fields only. |
| **T0.4** Write-allowlist pytest fixture | FR16 | Any test writing outside design §4's allowlist fails. Active for every task from M0 onward. |
| **T0.5** Credential wrapper (`platform/credentials.py`) | FR19 | Store/retrieve under service `InterviewPrepRecall`; grep test proves absence from disk. **Moved from M8** — M4's stage-2 selector needs an Anthropic key, so credentials cannot first appear in M8. |

Built first because every subsequent task's DoD items 3 and 5 depend on T0.3/T0.4 existing.

**CI audio strategy** *(review-B "missing #16")*: hosted Windows runners have no audio endpoint. So
CI never opens a device. Every test below the manual tier feeds WAV fixtures **directly into
`SttBackend.feed()`** in the §1a format, which is exactly the format the capture callback produces —
so the pipeline under test is the real one from `feed()` onward. Device-dependent tests (T1.1, T1.2,
T1.4, T5.2, T7.2) are marked `@pytest.mark.device` and run on the developer machine, reported per
milestone. The 60-minute soak runs nightly on that machine, not in CI.

---

## M1 — Audio Capture Spike ⚠️ **AS-2 gate**

| Task | Requirements | Acceptance criteria |
|---|---|---|
| **T1.1** WASAPI loopback capture | FR5 | Console prints live RMS while any app plays audio; verified against 3 different video apps. |
| **T1.2** Concurrent mic capture | FR6, D-U2 | Both streams deliver frames simultaneously for **60 minutes** with no device conflict, no dropout, and no clock drift beyond 50 ms. |
| **T1.3** Bounded queue + non-blocking callback | FR45, FR33 | Callback p99 < 2 ms under load; forced overflow drops oldest and increments a counter rather than growing memory. |
| **T1.4** Device enumeration + default-change notification | FR39 | Switching the default output device and unplugging headphones each fire a callback within 1 s. |

**Gate:** if T1.2 fails, `pyaudiowpatch` is not viable for D-U2's dual-stream requirement and the
capture library decision reopens **before** anything is built on top. Stop and escalate.

---

## M2 — STT Interface & Local Backend ⚠️ **AS-1 gate**

| Task | Requirements | Acceptance criteria |
|---|---|---|
| **T2.1** Write `stt/interface.py` — Protocol, event types, and the §2 semantic contract as docstrings | FR17, D-2 | Passes `mypy --strict`. A conformance test suite exists that any backend can be run against, written before any backend. |
| **T2.2** `local_whisper.py` with VAD-based synthesized finalization | FR18, FR47 | Passes the T2.1 conformance suite. Every acknowledged span yields exactly one final event. |
| **T2.3** Utterance assembler | FR46 | Scripted fixture produces exactly the expected utterance boundaries; sub-threshold fragments merge forward; no match fires on interim events. |
| **T2.4** Latency harness | NFR1, AS-1, NFR7 | Timestamped scripted audio → transcript; reports p50/p95 **per stage** against design §9a's budget. Run **CPU-only on the D-U6 laptop** for the gate; the D-U6 desktop's CUDA figure is recorded separately (NFR7) and never substituted. Covers the STT slice only — end-to-end NFR1 is T5.9, after the overlay exists. |

**Gate:** T2.4 p95 ≥ **900 ms of inference tail** (design §9a's STT slice — *not* 3 s end-to-end, which is the whole NFR1 budget) means AS-1 is false. Local is not the viable default, and M8 (cloud) is
promoted ahead of M5. Record the measurement in the decision log either way — this is the PRD's
own §12 open risk and it gets answered here, not assumed.

---

## M3 — Notes Store & Indexing

| Task | Requirements | Acceptance criteria |
|---|---|---|
| **T3.1** `Note`/`NoteSet` model + schema v1 | FR41, FR42, FR43 | Round-trips through JSON with byte equality; IDs are UUID4 and stable across mutations. |
| **T3.2** Atomic write + backup rotation | FR28, FR29 | **`taskkill /F` during save, 10 consecutive runs, notes intact every time.** Rotation preserves 5 generations. |
| **T3.3** Schema version guard + corruption recovery | FR31, FR44 | `schema_version` N+1 refuses cleanly and leaves the file untouched; a truncated file offers restore. |
| **T3.4** Export / import bundle | FR30 | Export → wipe → import yields deep equality on content, tags, bullets, order. |
| **T3.5** Importer: chunking + bullet proposal | FR1a, FR2, FR42 | `.md` splits on `##`/`###`, `.txt` on blank lines / `Q:`-`A:`; save is blocked until review is confirmed; every proposed bullet is a verbatim substring of the source. |
| **T3.6** Embedding index + model-version guard | FR34 | Changing the `embed_model_id` **attribute inside** the `.npz` forces a full re-embed; changing one note's headline re-embeds only that note. *(Test the attribute, not the filename — renaming the file produces a cache miss, which is a different code path from the mismatch FR34 describes.)* A corrupt `.npz` is deleted and rebuilt. |
| **T3.7** Notes editor UI (CRUD, reorder, tags, `track_progress`) | FR3, FR4, FR60 | All operations persist; IDs stable; "not overlay-optimised" flag shows for bullet-less notes (D-6); delete requires confirmation. **Saves on explicit action or 5 s idle after an edit — never per keystroke**, so FR29's 5 backup generations cannot be consumed by typing. |
| **T3.8** Note-set lifecycle UI | FR43, FR60 | Create, rename, select-active, delete a note set; active set persists in `QSettings`; delete confirms. *(Was missing — FR43 and FR60 referenced note sets that no task built.)* |
| **T3.9** Backup restore UI | FR29, FR44 | Browse the 5 generations, preview, restore. If a backup is itself corrupt, fall through to the next generation and say so. *(FR29 required "restorable from the UI" and no task built it.)* |

---

## M4 — Matching Pipeline ⚠️ **OQ-1 gate**

| Task | Requirements | Acceptance criteria |
|---|---|---|
| **T4.1** Stage-1 prefilter | FR9, FR50 | Returns top-K ≥ τ_floor; returns empty for unrelated speech; latency < 50 ms for 200 notes. |
| **T4.2** Stage-2 selector, forced tool call | FR10, FR48 | Every request has forced `tool_choice` and an enum of **≤6** members with 200 notes loaded; a mocked freeform response is rejected by the client. |
| **T4.3** Sequence gate | FR32 | Injected out-of-order completion never renders a stale result. Explicit test: dispatch A(1), dispatch B(2), complete A first — assert A is discarded, not rendered. |
| **T4.4** Degraded fallback | FR49, D-U3 | Stage-2 forced to fail: above τ_degraded emits `DEGRADED`, below emits no-match. |
| **T4.5** Debounce, retry, ceiling | FR40 | ≤1 in flight; ≤1 retry on 429/5xx; ceiling triggers local-only + FR35 signal. |
| **T4.6** Matching consumes interviewer stream only | FR53 | Mic utterances never enter the matching queue. |
| **T4.7** **Measurement: stage-1-only vs stage-1+2 accuracy** | OQ-1, AS-3, AS-7, NFR6 | On ≥3 recorded mock-interview transcripts with real notes: report precision/recall for both configurations, stage-2 call count, token spend, and p95 added latency. |

**Gate:** T4.7 decides OQ-1. If stage 2 adds little over stage 1, the hard internet dependency
(§12's own first open question) is reconsidered before it is baked into the UX.

---

## M5 — Overlay UI

| Task | Requirements | Acceptance criteria |
|---|---|---|
| **T5.1** Frameless, translucent, always-on-top teleprompter panel | FR11 | Renders headline + ≤3 verbatim bullets; every rendered string is a byte-exact substring of the stored note. |
| **T5.2** Capture exclusion + failure warning | FR14, FR14a | Overlay absent across 6 combinations (Zoom/Teams/Meet × full-screen/window). Forced API failure produces the persistent warning. |
| **T5.3** Confirmed vs degraded visual states | FR51 | Distinguishable at 1 m without reading text. |
| **T5.4** Drag, resize, opacity, **brightness**, lock, reset | FR22–24, FR27, FR55, **FR65** | Each independent; off-screen persisted coordinates recoverable via reset. **Sweep brightness end to end and assert every reachable setting clears 4.5:1 for body text and 3:1 for both rails; assert the mid-gray range is unreachable; assert rails swap variants at the crossover.** Assert the sub-70% opacity halo engages. |
| **T5.5** Transitions + auto-clear + pin | FR25, FR54, FR13 | Unpinned clears at τ_visible; pinned persists; replacement animates. |
| **T5.6** `QSettings` persistence | FR26 | Survives restart; documented as exempt from §4. |
| **T5.7** Health + egress indicators | FR7, FR20, FR35 | Every state in design §7 renders distinctly; **no-match is visually distinct from every failure state**. Egress renders **cloud STT and LLM distinguishably** (§9b), not one shared dot. Includes the FR7 capture indicator, which FR20 is defined relative to. Built to §9b's token table. |
| **T5.8** Diagnostics viewer | FR36 | In-app view of the ring buffer with export. *(FR36 required "viewable in-app"; T0.3 built only the buffer.)* |
| **T5.9** End-to-end latency harness | NFR1, NFR3 | Measures **last audio sample → overlay paint** against §9a's per-stage budget, p50/p95, CPU-only on the D-U6 laptop. Also measures video-call frame time with the overlay active vs inactive (NFR3). *(T2.4 covers the STT slice only and lands before the overlay exists, so neither NFR had a task that could verify it.)* |

---

## M6 — Session Lifecycle & Privacy

| Task | Requirements | Acceptance criteria |
|---|---|---|
| **T6.1** Session state machine | D-7 | All transitions in design §6 exercised; illegal transitions raise. |
| **T6.2** Purge | FR15 | **Audio** buffers are `bytearray` and post-purge bytes are zero. **Transcript text is `str`** — verify via the object-identity sweep in FR15 (`gc.get_referrers` over recorded `id()`s, plus weakrefs on the `TranscriptEvent`/`Utterance` containers, which unlike `str` support them). Do **not** assert transcript memory is zeroed; unsatisfiable, and it would pass vacuously. |
| **T6.3** Panic clear scope + in-flight neutralisation | FR58, FR59, FR64 | Note files byte-identical before/after. **Socket cancelled** (asyncio); **LLM response discarded via nonce** after its 5 s timeout — not cancelled, because it cannot be. No post-purge render. Resume from `WIPED` completes in ≤1 s without preflight re-run. |
| **T6.4** WER dump suppression + FR16 allowlist harness | FR16 | Process Monitor trace over a 45-min simulated session shows no writes outside the allowlist and no session content in any written file. |
| **T6.5** Preflight readiness check | FR38 | Each precondition failed in turn produces the correct block-vs-warn classification. |
| **T6.6** Backpressure + worker restart + sleep/lock | FR33, FR61, FR62 | Saturation drops oldest with flat memory; worker restarts once then holds; lock/unlock resumes. |
| **T6.7** Degradation switches | FR37 | Each toggles mid-session without restart. |

---

## M7 — Progress Tracker

| Task | Requirements | Acceptance criteria |
|---|---|---|
| **T7.1** Mic-only tracking against `track_progress` notes | FR12, FR56 | Speaking a tracked point marks it within 5 s; the same phrase played through loopback only does **not** mark it. |
| **T7.2** Echo detection in preflight | FR57 | Over speakers: warning fires. Over headphones: no warning. Measured cross-correlation logged to the ring buffer. |
| **T7.3** Runtime echo suppression | FR57, FR56, D-8 | Play a question through speakers so it reaches both streams: assert the **interviewer utterance still matches normally**, and assert the echoed **mic** utterance does **not** mark a tracked point. Both assertions required — passing only the first would mean the echo is being dropped from the wrong stream. |
| **T7.4** Checklist rendering in overlay | FR12 | Built to §9b's tracker tokens; visible without displacing the snippet; respects FR37's off switch. |

---

## M8 — Cloud STT Backends

| Task | Requirements | Acceptance criteria |
|---|---|---|
| **T8.1** Deepgram backend | FR17, FR18 | Passes the T2.1 conformance suite unmodified — the proof that D-2's interface actually abstracts. |
| **T8.2** ElevenLabs backend | FR17, FR18 | Same. |
| **T8.3** Credential storage | FR19 | Key in Credential Manager; absent from app data dir and from a diagnostic export (grep test). |
| **T8.4** Auto-fallback on drop | FR21 | Socket killed mid-session: local resumes within 5 s, notice shown. |
| **T8.5** Egress indicator wiring | FR20 | Fires for cloud STT audio and for LLM text independently and distinguishably. |

---

## M9 — Packaging & First Run

| Task | Requirements | Acceptance criteria |
|---|---|---|
| **T9.1** First-run consent disclosure | FR63 | Unavoidable on first run, blocks until acknowledged, persists. |
| **T9.2** Settings surface | FR52, FR37, D-9 | Sensitivity, thresholds, model ID, backend choice all editable and persisted. |
| **T9.3** Setup wizard | US-B3, FR38 | Walks device selection, audio test, echo check, notes import. |
| **T9.4** PyInstaller build | — | Single exe launches on a clean Windows 11 machine with no Python installed; FR16 allowlist re-verified against the packaged build, not just the dev build. |
| **T9.5** Confirm live Haiku pricing and model availability | NFR6, D-9, BC-5 | Rates confirmed against current docs before ship; §7's cost estimate updated if stale. |

**Deferred beyond v1:** `.docx` import (FR1b) · local matching model (OQ-4) · acoustic echo
cancellation · diarization.

---

## Critical Path & Parallelism

```
M0 ──► M1 ──► M2 ──┬──► M4 ──► M5 ──► M6 ──► M7 ──► M9
                   │           ▲
       M3 ─────────┘           │
       (parallel with M1/M2)   M8 (parallel with M5/M6, after M2)
```

- **M3 can start immediately after M0** — the notes store has no dependency on audio, and it
  carries the review's highest-severity finding.
- **M8 needs only M2's interface**, so cloud backends can be built in parallel with the overlay.
- **M1 and M2 are hard gates.** Both answer PRD §12's open risks with measurements. Neither may
  be assumed to pass.
