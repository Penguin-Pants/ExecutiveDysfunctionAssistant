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
3. No new writes to disk outside the §4 allowlist (checked by the FR16 harness once M6 lands).
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
| **T0.3** Diagnostic ring buffer (`diagnostics/ring.py`) | FR36 | Bounded to N events, evicts oldest; a test asserting no method accepts transcript or note text; export produces JSON with structural fields only. |

Built first because every subsequent task's DoD item 5 depends on the ring existing.

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
| **T2.4** Latency harness | NFR1, AS-1 | Timestamped scripted audio → transcript; reports p50/p95 on the **target machine**. |

**Gate:** T2.4 p95 ≥ 3 s means AS-1 is false. Local is not the viable default, and M8 (cloud) is
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
| **T3.6** Embedding index + model-version guard | FR34 | Changing `model_id` in the cache forces full re-embed; changing one note's content re-embeds only that note. |
| **T3.7** Notes editor UI (CRUD, reorder, tags, `track_progress`) | FR3, FR4 | All operations persist; IDs stable; "not overlay-optimised" flag shows for bullet-less notes (D-6). |

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
| **T5.4** Drag, resize, opacity, lock, reset | FR22–24, FR27, FR55 | Each independent; off-screen persisted coordinates recoverable via reset. |
| **T5.5** Transitions + auto-clear + pin | FR25, FR54, FR13 | Unpinned clears at τ_visible; pinned persists; replacement animates. |
| **T5.6** `QSettings` persistence | FR26 | Survives restart; documented as exempt from §4. |
| **T5.7** Health + egress indicators | FR20, FR35 | Every state in design §7 renders distinctly; **no-match is visually distinct from every failure state**; egress indicator fires independently for cloud STT and LLM. |

---

## M6 — Session Lifecycle & Privacy

| Task | Requirements | Acceptance criteria |
|---|---|---|
| **T6.1** Session state machine | D-7 | All transitions in design §6 exercised; illegal transitions raise. |
| **T6.2** Purge with zeroing | FR15 | Transcript buffers are `bytearray`; post-purge bytes are zero; no live references remain. |
| **T6.3** Panic clear scope + in-flight cancellation | FR58, FR59 | Note files byte-identical before/after; in-flight LLM and socket cancelled; no post-purge render. |
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
| **T7.3** Runtime echo suppression | FR57, D-8 | Spans detected as mic echo are excluded from the interviewer stream. |
| **T7.4** Checklist rendering in overlay | FR12 | Visible without displacing the snippet; respects FR37's off switch. |

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
