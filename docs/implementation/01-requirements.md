# Requirements Specification

Consolidates the PRD's FR1–FR27, the safety review's amendments (A1–A23, issued as FR28–FR40),
and requirements newly derived while closing gaps (FR41+). This document supersedes the PRD's §6
where they differ; differences are marked and explained.

**Status key:** `v1` ships in the first release · `post-v1` specified but deferred · `superseded` replaced by another requirement

Every requirement below states an observable pass condition. If a requirement cannot be
verified by an automated test or a written manual procedure, it is not a requirement — it is a
preference, and belongs in the design doc instead.

---

## 1. Notes & Prep

| ID | Status | Requirement | Verification |
|---|---|---|---|
| **FR1a** | v1 | Import prep notes via paste, `.txt`, or `.md`. | Import each of the 3 paths; content round-trips exactly. |
| **FR1b** | post-v1 | `.docx` import. | Deferred per D-U1. |
| **FR2** | v1 | Auto-chunk notes into discrete items. `.md` splits on `##`/`###`. `.txt` is **auto-detected**: if ≥2 lines match `^\s*Q:`, use the `Q:`/`A:` convention; otherwise split on blank lines. The chosen strategy is named in the review UI and the user can switch it before saving. Every auto-split chunk is presented for review and is editable before save. | Import a fixture of each format and each `.txt` variant; assert boundaries and that the strategy label matches. *(Detection rule was previously unstated — two importers would chunk the same file differently: reviewer A.)* |
| **FR3** | v1 | Edit, delete, and reorder notes between sessions. Note IDs are unaffected by any of these (FR41). | Edit/delete/reorder; assert IDs stable, order persists. |
| **FR4** | v1 | Tag notes with free-form labels. Tags drive progress-tracker selection (FR12) and are shown in the editor. | Round-trip tags through save/load/export. |
| **FR41** | v1 | **Note IDs and note-set IDs are UUID4**, assigned at creation, stable across edits and reorders, and never reused after deletion. The note-set ID is also its filename and its embedding-cache key. | Delete a note, create 100 more; assert the deleted ID never recurs. Assert a renamed note set keeps its ID and filename. *(Note-set IDs previously had no stated rule despite being load-bearing in two paths — reviewer A.)* |
| **FR42** | v1 | A note carries `bullets[]` of verbatim strings **from a stored source**. *(Was "user-authored"; a job description is user-supplied and not user-authored, so the FR66 kinds would violate the wording while fully satisfying the property. The guarantee was never about authorship — it is the absence of generation, and the test is unchanged.)* The importer proposes sentence-split bullets for review; the user may accept, edit, or clear them. **No bullet text is ever machine-generated at match time.** | Assert every rendered bullet is a byte-exact substring of the stored note. (D-5.) |
| **FR43** | v1 | Multiple named note sets; exactly one is active per session. | Create 2 sets, switch active, assert matching draws only from the active set. (US-A3, D-U1.) |

## 2. Notes Durability *(review A1 — the review's highest-severity finding)*

| ID | Status | Requirement | Verification |
|---|---|---|---|
| **FR28** | v1 | All notes writes are atomic: write a temp file in the same directory, flush + `fsync`, **copy** the current target to `.bak.1` (rotating older generations first), then `os.replace` the temp over the target. **Rotation copies, never renames** — a rename would leave a window with no live file at all. | Kill the process (`taskkill /F`) during save, 10 consecutive runs; notes load intact every time. Assert a live file exists at every point in the sequence. *(Corrected: the original notation renamed `target→.bak.1`, contradicting its own rationale that a crash never loses the live file — reviewer B2.)* |
| **FR29** | v1 | The app retains the last 5 versions of each note set, rotated on save, restorable from the UI. | Corrupt the live file; restore from backup via UI; content matches the prior version. |
| **FR30** | v1 | Notes export to a plain `.md` + `.json` bundle and re-import from it, losslessly. | Export → wipe store → import; assert deep equality of content, tags, bullets, and order. |
| **FR31** | v1 | The notes store carries `schema_version`. A newer version than the app understands causes a clean refusal with an explanatory message, never a best-effort parse. | Hand-edit `schema_version` to N+1; assert refusal and that the file is left untouched. |
| **FR44** | v1 | A corrupt, unparseable, **or missing** note set offers restore-from-backup rather than failing silently or starting empty. A corrupt `.npz` embedding cache is deleted and rebuilt, since it is derived data. | Truncate the file mid-object; assert the restore prompt appears. |

## 3. Audio Capture

| ID | Status | Requirement | Verification |
|---|---|---|---|
| **FR5** | v1 | Capture system audio output via WASAPI loopback, independent of the video application. | Capture during playback from 3 different apps; assert non-silent PCM. |
| **FR6** | v1 | **Capture microphone input as a separate concurrent stream.** *(Supersedes the PRD's "optionally" — D-U2 makes both streams mandatory.)* | Assert both streams deliver frames concurrently for 60 min without drift or device conflict. |
| **FR7** | v1 | Capture starts and stops only via explicit user control; it never runs in the background without a visible indicator. | Assert no capture thread exists in `IDLE`; assert indicator visible whenever any stream is open. |
| **FR39a** | v1 | On default-device **change** with a replacement available, re-bind automatically, notify, and keep the session `RUNNING`. | Switch default device mid-session; session survives without pausing. (Review A16.) |
| **FR39b** | v1 | On device **loss** with no replacement, retry for 10 s, then enter `PAUSED` with `audio lost`; auto-resume when a device returns. | Remove all output devices mid-session; assert pause, then restore and assert auto-resume. *(Split from a single FR39 that claimed the session always survives while design §9 said it paused — review-B C6.)* |
| **FR45** | v1 | The audio callback never blocks: it copies the frame into a bounded queue and returns. Queue overflow drops the oldest frame and increments a counter. | Instrument callback duration; assert p99 < 2 ms and that overflow drops rather than grows. |

## 4. Transcription

| ID | Status | Requirement | Verification |
|---|---|---|---|
| **FR8** | v1 | `SttBackend.feed()` receives **one 20 ms frame at a time** (design §1a). Chunking into ~2–4 s windows happens **inside** the local backend; cloud backends stream frames straight onto the socket. | Assert the pump calls `feed()` once per frame and never aggregates; assert the local backend's internal window is 2–4 s. |
| **FR17** | v1 | STT sits behind a common streaming interface (specified in design §2) so backends are swappable without changes elsewhere. | Swap backends via config with no edits outside the backend package; full pipeline test passes on both. |
| **FR18** | v1 | Default backend is local `faster-whisper`. Cloud backends (Deepgram, ElevenLabs) are opt-in, enabled by entering an API key. | Assert default config selects local; assert cloud inactive without a key. |
| **FR19** | v1 | API keys are stored in Windows Credential Manager, never in a config file, log, or diagnostic export. | Grep the entire app data directory and a diagnostic export for the key string; assert absent. |
| **FR21** | v1 | If a cloud connection drops mid-session, fall back to local automatically and surface a brief notice. | Kill the socket mid-session; assert transcripts resume from local within 5 s and the notice appears. |
| **FR46** | v1 | **An utterance is a finalized transcript span** terminated by ≥700 ms silence, 10 s max duration, or session stop; minimum 3 words and 12 characters, otherwise merged forward. Matching triggers per utterance, never per audio chunk. | Feed scripted audio; assert utterance boundaries and that no match fires on an interim result. (D-4.) |
| **FR47** | v1 | Local backends synthesize finalization from silence detection, since Whisper emits no native final marker. Every acknowledged speech span produces exactly one final event or a transition to `FAILED`. | Assert final-event count equals expected utterance count on a scripted fixture. |

## 5. Matching

| ID | Status | Requirement | Verification |
|---|---|---|---|
| **FR9** | v1 | Two-stage pipeline: local embedding prefilter, then an LLM selector over the prefiltered candidates. | Integration test asserts both stages run and stage 2 receives only stage-1 survivors. |
| **FR10** | v1 | The stage-2 call is structurally constrained: one forced tool call whose only output is a note ID from an enum, or `"none"`. Freeform text is impossible by construction. | Assert `tool_choice` is forced and the schema enum is present on every request. |
| **FR48** | v1 | **The stage-2 enum contains only the prefiltered candidate IDs (max 5) plus `"none"` — never the full note set.** *(Fixes the concrete bug in PRD §10b's code sample.)* | Load 200 notes; assert every request enum has ≤6 members. (Review A5 / RC-6.) |
| **FR32** | v1 | Each matching request carries a monotonically increasing sequence number. A response renders only if its sequence equals the **latest issued** sequence. Older responses are discarded on arrival regardless of whether cancellation succeeded. | Inject artificial latency to force out-of-order completion; assert no stale snippet ever renders. (Review A6, as corrected.) |
| **FR40** | v1 | Matching calls are debounced to at most one in flight, retried at most once with backoff on 429/5xx, and subject to a per-session call ceiling. On sustained rate-limiting, degrade to local-only matching and signal via FR35. | Simulate sustained 429; assert ≤1 retry per call, degradation, and signalling. |
| **FR34** | v1 | The embedding index records model name and version. On mismatch at load, re-embed all notes transparently and report it. | Change the model ID in the cache; assert automatic re-embed, not silent vector comparison. (Review A10 / BC-1.) |
| **FR49** | v1 | **On stage-2 failure or timeout, fall back to the top stage-1 match only if it clears τ_degraded (a higher bar than τ_floor), and render it in the degraded visual state (FR51). Below τ_degraded, render nothing.** | Force stage-2 failure at similarities above and below τ_degraded; assert both branches. (D-U3, resolving §10b vs US-D2.) |
| **FR50** | v1 | When no candidate clears τ_floor, the overlay shows nothing. The system never surfaces a note it did not select. | Feed unrelated speech; assert empty overlay and `matching=ok` health. (US-D2.) |
| **FR52** | v1 | Match sensitivity is user-adjustable on a single control mapping to τ_floor. | Move the control; assert τ_floor changes and persists. (US-D3.) |
| **FR53** | v1 | Matching consumes the interviewer (loopback) stream only. | Assert mic utterances never enter the matching queue. (D-10.) |

## 6. Overlay UI

| ID | Status | Requirement | Verification |
|---|---|---|---|
| **FR11** | v1 | Frameless, always-on-top, teleprompter-styled panel: dark semi-transparent, high-contrast text, minimal chrome. Renders headline + up to 3 verbatim bullets. | Visual check against the spec; assert ≤3 bullets rendered. |
| **FR51** | v1 | The overlay has two distinct content states: **confirmed** (stage-2 selected) and **degraded** (FR49 fallback), visually distinguishable at a glance without reading. | Assert distinct styling tokens; manual glance test at 1 m distance. |
| **FR13** | v1 | Manual controls: pause capture, dismiss snippet, pin snippet (suppresses auto-clear). | Exercise each; assert behavior. |
| **FR54** | v1 | An unpinned snippet auto-clears after τ_visible (default 25 s, configurable). | Assert clear at τ_visible; assert a pinned snippet persists indefinitely. |
| **FR14** | v1 | The overlay is excluded from screen capture via `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`. | Share full screen and single window in Zoom/Teams/Meet; overlay absent in all six combinations. |
| **FR14a** | v1 | **If `SetWindowDisplayAffinity` returns failure, display a prominent persistent warning that the overlay is NOT excluded. Never silently assume success.** | Force the call to fail; assert the warning. (Review A15 / RC-7.) |
| **FR22** | v1 | Drag to reposition; default position top-center. | Drag; assert position changes and default is correct on first run. |
| **FR23** | v1 | Resize by edge drag or settings control; text scales with the window rather than clipping. | Resize across the supported range; assert no clipping at any size. |
| **FR24** | v1 | Continuous opacity control, 20–100%, independent of size, position and brightness. **Below 70% the overlay renders ink with a 1px contrasting halo**, and the setting states that contrast is best-effort below that point — a translucent panel composites with the call, so no fixed guarantee is possible. | Assert opacity applies independently; assert the halo engages below 70%; assert the caveat text is shown. |
| **FR65** | v1 | **Overlay brightness is user-adjustable**, independent of opacity. The control spans two bands — dark `#141619`–`#2A2D31` with light ink, light `#C2C5CA`–`#E8EAEE` with dark ink — and **steps over the mid-gray range where neither ink clears 4.5:1**. Ink and both state rails switch variants at the crossover. Default is the dark band. | Sweep the full control; assert every reachable setting clears 4.5:1 for body text and 3:1 for the rails; assert mid-gray is unreachable; assert the degraded rail stays visible in the light band. (D-U7a.) |
| **FR25** | v1 | Snippet replacement transitions (fade/slide), never a hard pop. | Assert a transition animation runs on replace. |
| **FR26** | v1 | Position, size, and opacity persist between sessions via `QSettings`. Explicitly exempt from the §4 no-persistence principle, which governs audio and transcript content only. | Set, restart, assert restored. |
| **FR27** | v1 | A lock-position toggle prevents accidental dragging. | Assert drag is a no-op while locked. |
| **FR55** | v1 | A "reset overlay position" control restores the default position, for recovery when persisted coordinates land off-screen. | Persist off-screen coordinates, restart, assert recovery via the control. (Review A22 / RC-9.) |

## 7. Progress Tracker *(promoted to v1 by D-U1)*

| ID | Status | Requirement | Verification |
|---|---|---|---|
| **FR12** | v1 | A checklist of notes with `track_progress: true`, marked "mentioned" when a mic utterance embeds within τ_track (0.60) of the note's headline. Marks are sticky for the session and never un-mark. | Speak a tracked point into the mic; assert it marks within 5 s. Assert an unrelated utterance does not mark it. *(Algorithm and threshold were previously unspecified, making the acceptance criterion unimplementable.)* |
| **FR56** | v1 | Tracking consumes the mic stream only. | Play a tracked phrase through the loopback stream only; assert it does **not** mark. (US-G2.) |
| **FR57** | v1 | **Echo detection:** preflight cross-correlates mic and loopback (τ_echo 0.70) and warns that headphones are required if speaker output is bleeding into the mic. At runtime, a **mic** utterance that duplicates a recent interviewer utterance (token overlap ≥ τ_echo_text within ±1.5 s) is **dropped from the progress tracker**. The interviewer utterance is never suppressed — on speakers the duplicate *is* the real question leaking into the mic, so discarding the interviewer span would throw away the question while the echoed mic copy still falsely marked a talking point, which is the exact FR56 failure this prevents. | Run preflight over speakers; assert the warning. Run over headphones; assert no warning. (D-8 / RC-8.) |

## 8. Session Lifecycle & Privacy

| ID | Status | Requirement | Verification |
|---|---|---|---|
| **FR15** | v1 | Ending a session (manual or on app close) clears audio buffers, transcripts, and overlay content from memory. **Audio buffers are `bytearray` and explicitly zeroed. Transcript text is `str` and cannot be zeroed in Python** — purge drops every application reference and clears widget content, and the app states this limit to the user rather than implying erasure. | Assert audio buffer bytes are zero post-purge. Verify by **object-identity sweep**: record `id()` of every transcript string created during the session in a debug-only registry, then after purge run `gc.collect()` and assert `gc.get_referrers()` returns no application object for any of them, and that no live `TranscriptEvent`/`Utterance` instance remains (those *are* weakref-able; the raw `str` is not — `weakref.ref("x")` raises `TypeError`). Do **not** assert transcript memory is zero — unsatisfiable, and it would pass vacuously. (Review A3 / DI-6; scope corrected per design §6.) |
| **FR16** | v1 | **The application never writes audio to disk.** Transcripts and reports are written **only** to the encrypted session store (FR82), **only** while the post-interview report feature is enabled; with it disabled the original absolute holds for transcripts too. *(Weakened deliberately by D-U8 — see `07-context-sources-and-report.md` §0. The prior wording said transcripts are never written, which this feature makes false; it is rewritten rather than reinterpreted.)* The OS may page process memory and may write crash dumps containing process memory; these are outside application control, and the app disables Windows Error Reporting dumps for its own process. *(Rewritten from the PRD's unkeepable absolute claim.)* | Process Monitor trace against an expected-path allowlist. Assert **no audio bytes in any written file**, and **no plaintext session content anywhere** — including outside the session store. Encrypted session-store artifacts are expected and permitted when the feature is enabled; assert they are unreadable without the user's DPAPI key. *(Gate corrected: the statement was rewritten for D-U8 and this verification was left saying "no session content in any written file", which a conforming implementation fails by design. Statement and test drifting apart is this project's recurring defect — here it would have failed correct code rather than passing broken code.)* (Review A3 / DI-5.) |
| **FR58** | v1 | Panic clear and session purge affect audio buffers, transcript, and overlay state **only**. They never touch stored notes, note sets, or settings under any circumstance. **Nor previously saved sessions (FR86)** — destroying earlier interviews on a single unconfirmed keypress would be a catastrophic surprise; FR83's delete-all is the deliberate route, signposted per FR87. | Panic-clear with notes loaded; assert byte-identical note files before and after. (Review A2 / DI-3.) |
| **FR64** | v1 | Panic clear stops capture and leaves the session in `WIPED`: buffers cleared, overlay empty, **progress-tracker marks cleared** (they are session state, and a panic clear that left a visible record of what you had said would defeat the control's purpose), devices still open and preflight still valid, resumable with one click in ≤1 s. The capture indicator shows a hollow ring in `WIPED` — devices held, nothing captured — so "not listening" is visible rather than inferred. It does not end the session, and it does not leave capture running. | Panic-clear mid-session; assert capture stopped, assert resume needs no preflight re-run and completes within 1 s. (D-U5.) |
| **FR59** | v1 | Panic clear neutralises all in-flight network work before clearing local state: the cloud STT socket is **cancelled** (asyncio, genuinely cancellable); the LLM request is **bounded by a 5 s timeout and its response discarded via the session nonce**, because Python cannot cancel a blocking call on a pool thread. No response from before the purge ever reaches the screen. | Panic-clear with both in flight; assert the socket closes, assert a late LLM response is discarded and nothing renders. *(Wording corrected — the original asserted symmetric cancellation of something that cannot be cancelled: review-B C8.)* |
| **FR60** | v1 | Destructive actions (delete note, delete note set, panic clear) require confirmation, except panic clear which is deliberately single-action but scoped by FR58. | Assert confirmation dialogs; assert panic clear is single-action. |

## 9. Resilience & Backpressure

| ID | Status | Requirement | Verification |
|---|---|---|---|
| **FR33** | v1 | The audio→STT queue is bounded at **150 frames of 20 ms (3 s)** per design §1a. Overflow drops the **oldest frame** — never a whole chunk or question — and sets a degraded health state. **No rolling transcript buffer is retained**: the only transcript held anywhere is the assembler's ≤10 s `context` window, which is discarded as it slides. *(Corrected: the original said "3 chunks" and posited a 5-minute transcript buffer that no component owned, read, or needed — retained transcript with no consumer is a privacy cost with no benefit.)* | Saturate with slow STT; assert flat memory, oldest-drop, and the `falling behind` state. (Review A7 / RC-1, RC-2.) |
| **FR61** | v1 | A crashed STT worker restarts once automatically; a second failure stops **that stream only**, holds the session open, and reports `STT unavailable (interviewer)` or `(mic)`. A dead mic worker never stops interviewer matching, and vice versa. The user is never silently unassisted. | Kill each worker twice independently; assert per-stream isolation. *(Per-stream scope was ambiguous with two workers — review-B A13.)* |
| **FR62** | v1 | On machine sleep/lock mid-session, capture pauses and resumes on unlock; nothing is purged and no crash occurs. | Lock and unlock during a session; assert resume. |

## 10. Observability

| ID | Status | Requirement | Verification |
|---|---|---|---|
| **FR20** | v1 | A persistent, unmissable indicator shows whenever data leaves the device — cloud STT audio **or** LLM matching text — visually distinct from the capture indicator. | Assert the egress indicator appears for each path independently and is distinguishable from FR7's. |
| **FR35** | v1 | A persistent session health indicator distinguishes at minimum: `capturing`, `no audio detected`, `STT degraded`, `matching: local-only`, `falling behind`, `audio lost`. **STT health is tracked per stream** so FR61's `STT unavailable (interviewer)` / `(mic)` is expressible. **It must make "no match found" and "pipeline broken" visually distinguishable** — an empty overlay must be readable as intentional. | Drive each state; assert distinct rendering. Assert the no-match state is distinct from every failure state. (Review A11 / OB-1, OB-2.) |
| **FR36** | v1 | A bounded in-memory diagnostic ring buffer records structural events only — timestamps, component states, latencies, error codes, match/no-match decisions — and **never transcript or note content**. Viewable in-app and explicitly exportable by the user. Never auto-written to disk. | Run a session, export, assert no transcript substring appears; assert the buffer is bounded. (Review A12.) |
| **FR37** | v1 | Mid-session degradation switches for: LLM matching on/off (falls back to local-only), cloud STT on/off, progress tracker on/off. Each independently switchable while running. | Toggle each mid-session; assert the pipeline adapts without a restart. (Review A13 / OB-3.) |
| **FR38** | v1 | A pre-session readiness check runs **automatically** at session start, validating: loopback device, mic device, notes loaded, STT backend reachable, API key valid (if cloud), Windows build ≥ 19041, and that `SetWindowDisplayAffinity` returned success. Blocks start on hard failures, warns on soft ones. | Fail each precondition in turn; assert block vs warn classification. (Review A14 / OB-5.) |

## 11. Legal & Consent

| ID | Status | Requirement | Verification |
|---|---|---|---|
| **FR63** | v1 | *(Insufficient on its own once reports are enabled — **FR85** requires a fresh disclosure and re-acknowledgement, because this one was acknowledged against a weaker statement.)* An unavoidable first-run disclosure covering: recording/interception law varies by jurisdiction and may require all-party consent; many employers prohibit capture during interviews; the user is responsible for compliance. Not buried in settings. | Assert it appears on first run and blocks until acknowledged; assert acknowledgement persists. (Review A19 / §2.6.) |

## 12. Non-Functional

| ID | Status | Requirement | Verification |
|---|---|---|---|
| **NFR1** | v1 | End-to-end p95 < 3 s, measured from **the last audio sample of the utterance** to overlay paint, per the stage budget in design §9a. Measured CPU-only on the D-U6 laptop. | Scripted-audio harness with timestamped ground truth; report p50/p95 per stage. |
| **NFR2** | v1 | Runs without a discrete GPU. **The AS-1 gate is measured CPU-only** so this is validated, not assumed (D-U6). | Full suite on CPU only, CUDA explicitly disabled. |
| **NFR7** | v1 | If a CUDA-capable GPU is present, the local STT backend uses it automatically. This is an optimisation only — no requirement, gate, or acceptance criterion may depend on a GPU being present. | Run on the D-U6 desktop; assert CUDA is used and the result is recorded separately from the AS-1 gate number. |
| **NFR3** | v1 | Overlay CPU/GPU cost does not visibly degrade a concurrent video call. | Measure frame time during a live call with the overlay active vs inactive. |
| **NFR4** | v1 | Windows 11 (D-U4); code path still checks build ≥ 19041 per FR38. | Assert the check runs. |
| **NFR5** | v1 | Memory is flat across a 60-minute session — bounded by FR33's windows, not a function of session length. | 60-min soak; assert no monotonic growth. |
| **NFR6** | v1 | Stage-2 cost stays within a few cents per 45-minute interview under expected utterance rates. | Count calls and tokens in the M4 measurement; extrapolate. |

---

## Supersession Notes

Where this document differs from the PRD, the PRD is wrong or incomplete, for these reasons:

- **FR6** — "optionally capture microphone" → mandatory. D-U2.
- **FR16** — absolute no-disk claim → scoped, honest claim. The original could not be satisfied on Windows (DI-5).
- **FR12 / Epic G** — stretch → v1. D-U1.
- **FR1** — `.docx` split into FR1a (v1) and FR1b (deferred). D-U1.
- **PRD §10b code sample** — enum populated from all note IDs → prefiltered candidates only. FR48.
- **PRD §10b fallback prose** — unconditional fallback → τ_degraded-gated and visually marked. FR49, resolving the contradiction with US-D2.
