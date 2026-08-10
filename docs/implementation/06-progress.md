# Build Progress

**Purpose:** so that after a gap of days, either of us can open this file and know exactly what
is built, what is verified, what is blocked, and what the next action is — without re-reading the
other six documents or re-deriving anything.

Updated at the end of every milestone. Newest entry at the top of the log.

---

## Current state at a glance

| Milestone | Status | Notes |
|---|---|---|
| **M0 — Scaffold** | ✅ Complete | 20 tests passing, lint + format + mypy clean |
| **M1 — Audio capture spike** | ⛔ Blocked | Needs the Windows machine. **AS-2 gate.** |
| **M2 — STT interface & local backend** | 🟡 Started | **T2.1 interface + T2.3 assembler done.** T2.2 (`faster-whisper`) and T2.4 (AS-1 gate) need Windows |
| **M3 — Notes store & indexing** | 🟢 Logic complete | T3.1–T3.6 done. T3.7–T3.9 are Qt UI, deferred to Windows |
| **M4 — Matching pipeline** | 🟢 T4.1–T4.6 complete | T4.7 **blocked**: needs the user's labelled fixtures |
| **M5 — Overlay UI** | ⛔ Blocked | Qt + `SetWindowDisplayAffinity`; needs Windows. Fully specified (design §9b) |
| **M6 — Session lifecycle** | 🟢 Logic complete · panic on hold (D-U11) | T6.1–T6.3, T6.5 classification, T6.6 backpressure, T6.7 done. T6.4 and the OS trigger paths need Windows |
| **M7 — Progress tracker** | 🟢 T7.1 + T7.3 complete | Marking and text-domain echo suppression done. T7.2 needs paired audio fixtures; T7.4 is Qt |
| **M8 — Cloud STT backends** | 🟢 T8.1–T8.5 complete | Deepgram, ElevenLabs, fallback, egress. Protocols unverified against a live endpoint (**AS-8**) |
| **M9 — Packaging & first run** | ⛔ Blocked | T9.1–T9.3 are Qt; T9.4 is PyInstaller on Windows; T9.5 needs live vendor docs |
| **M10 — Typed context sources** | 📋 Specified | Five kinds (company, role, interviewer, prep, resume). Additive. T10.1–T10.6 buildable now |
| **M11 — Post-interview report** | 📋 Specified | Reverses a v1 non-goal and rewrites FR16. Depends on M10. Most tasks buildable now |

**Next action: M10, tasks T10.1–T10.6.** The user requested two new features on 2026-08-10 and
they are specified in `07-context-sources-and-report.md`. Most of both is platform-free.

The previous version of this line said nothing further was buildable on Linux. That was true of
the *then-known* scope and is now moot — but note it had already been wrong twice on its own terms
before new scope arrived. Treat any such claim here as one to re-test.
The remaining work splits cleanly:

- **Needs the Windows machine:** M1 (AS-2 gate), T2.2 + T2.4 (AS-1 gate), M5 overlay, T6.4's
  ProcMon trace and M6's OS trigger paths, T7.4's checklist rendering, T9.1–T9.4, T10.7's per-kind
  overlay marking, T11.10's report view, and T11.2's DPAPI binding (its envelope and listing
  logic are testable here behind a Protocol).
- **Needs the user's fixtures:** T4.7 (the OQ-1 gate) and T7.2 (paired headphone/speaker audio).
- **Needs a vendor key:** AS-8 — the two cloud protocols are implemented from documentation and
  have never met a live endpoint. Everything *around* them is tested; the wire format is not.

**A caution about this list, now with two instances.** An earlier version said "M7 tracker device
tests", and that blanket phrase hid two buildable tasks for a whole milestone. The very next
version said "M8–M9 — cloud backends, packaging, **both Windows**", which hid an entire milestone:
cloud STT is websockets and asyncio and has no Windows dependency whatsoever.

Both errors were mine, both were written *into this file as a summary*, and both were then trusted
on the next read. When a milestone is marked blocked here, name the *task* and the *reason*, and
make the reason specific enough to be falsifiable — "Windows" is not; "needs
`SetWindowDisplayAffinity`" is.

---

## Environment split — read this first after any gap

Development happens in a **Linux container**; the product targets **Windows 11** (D-U4).
That split decides what can be verified where, and it is not a temporary inconvenience — it is
permanent for this project.

**Buildable and verifiable on Linux:** notes model and store, atomic write and rotation, schema
guard, importer and chunking, embedding index (against a fake embedder), the STT interface and its
conformance suite, the utterance assembler (fed by WAV fixtures), matching prefilter, sequence
gate, dispatch policy, diagnostics, credentials logic.

**Requires the Windows machine:** WASAPI capture (M1), `faster-whisper` timing (T2.4/AS-1),
`SetWindowDisplayAffinity` (T5.2), Credential Manager binding (the OS half of T0.5), the Process
Monitor privacy trace (T6.4), PyInstaller packaging (T9.4), and every `@pytest.mark.device` test.

**Python version:** the container has 3.11; the spec pins **3.12** for the Windows build. Two
settings look similar and mean different things — do not "align" them:

- **`ruff target-version = "py311"`** — the *floor*. Keeps the source runnable in the 3.11
  container, so nothing here silently adopts 3.12-only syntax.
- **`mypy python_version = "3.12"`** — the *target*. Type-checks against the version that ships.

An earlier version pinned mypy to 3.11 to match the container, which broke CI: numpy 2.5's own
stubs use `type` statements that a 3.11 parser cannot read, so mypy failed before checking any
project code. Analysing for an older version than your dependencies are written for is not a
conservative choice, just a broken one.

---

## Log

### Panic clear put on hold — now pauses only · built · 2026-08-10

User direction (**D-U11**): the panic control should only pause the program. Implemented, not just
specified — this changed merged, tested behaviour, so the code and its tests moved together.

**What changed.** `panic_clear()` now calls `pause(PauseCause.PANIC)` and nothing else. No purge,
no `WIPED`. Buffers, transcript, overlay content and tracker marks all survive; resume continues
the session. `PANIC` is a distinct cause rather than a reuse of `USER` so health and diagnostics
can tell the two apart, and so re-enabling the wipe is a change at one branch.

**What this costs, stated plainly.** The product no longer has any in-session emergency data
destruction, and it lands alongside D-U8, which made transcripts persist. Nothing is destroyable
mid-interview any more. That is a coherent position but it is a real shift from D-U5, and FR87
(delete-all, signposted at the panic surface) is now carrying weight it was not designed for.

**`WIPED` is retained but unreachable (D-35).** No edges in, none out, and
`test_wiped_is_unreachable_while_panic_is_on_hold` asserts it against the *transition table*
rather than by driving paths — the claim is that no edge exists, which sampling cannot establish.

**The WIPED branches in `resume()` and `end_session()` were deleted rather than left in place
(D-36),** because unreachable code cannot be tested and untestable branches that handle impossible
cases rot. D-22's reasoning survives in the decision record and is still enforced: `PANIC` is not
in `AUTO_RESUME_CAUSES`, so a stray unlock cannot undo it.

**Three purge tests were using `panic_clear()` as a convenient purge trigger.** They are about
purge completeness, ordering and health reset — not about which control fires it — so they now
drive `end_session()`, which still purges. Rewritten rather than deleted: the coverage was real.

**OQ-7 is closed unresolved rather than answered.** A control that destroys nothing has no blast
radius to argue about. The reasoning is preserved in `07-…` §3 so it returns intact if the hold lifts.

**Process note, third instance.** One of my string replacements silently no-op'd again — a blank
line between the two lines I targeted — and it was the *one* call in that batch where I did not
write `assert old in t`. The tests caught it, but only because they were failing for an unrelated
reason at the time. The rule has to be unconditional: every replacement asserts it matched.

**PR #10 review round — two findings, both valid.**

| Severity | Finding | Why it mattered |
|---|---|---|
| P1 | **Panic from an existing machine pause left the old cause in place.** `PAUSED -> PAUSED` is illegal, so delegating to `pause()` raised and `DEVICE_LOST`/`LOCK` survived — the next device return or unlock would auto-resume capture *after the user pressed panic*. FR64a forbids exactly that. A regression introduced by this commit: the old code accepted panic from `PAUSED`. | Panic now **promotes** the cause without a transition. Promotion only ever removes auto-resume, so it is safe from any cause and needs no per-cause branching. Tested parametrized over **every** cause, so a new auto-resumable cause added later cannot escape it. |
| P2 | **FR59, design §6 and T6.3 still prescribed the panic-purges-then-WIPEDs behaviour.** Following T6.3 as written would have restored what D-U11 removes. | FR59 **reassigned to session purge rather than deleted** — panic no longer triggers it, but the ordering guarantee is real and `end_session()` is where it lives now. Deleting it would have dropped a live guarantee along with its dead trigger. T6.3 split into purge (T6.3) and panic (T6.3a). |

The P1 is worth dwelling on: my own test asserted panic from a `USER` pause *raises*, and I wrote
that test believing the raise was correct. It is defensible for `USER` and actively unsafe for the
two machine causes, and testing the one benign case is what made the hole invisible.

288 tests passing; ruff, ruff format and mypy clean.

---

### Scope change — typed context sources & post-interview report · specified · 2026-08-10

The user asked for two features: five separately-categorized context sources (company, job
description, interviewer, prep notes, resume), and a post-interview report analyzing the whole
meeting. Specified in `07-context-sources-and-report.md` as **M10** and **M11**. Nothing built yet.

**M11 reverses a stated v1 non-goal and makes the product's strongest claim false.** Design §11
listed "any post-call artifact" as out of scope. More importantly, "nothing the user says or hears
is written to disk" was the sharpest thing this product promised, and D-U8 trades it for a
persisted transcript. **FR16 is rewritten rather than reinterpreted** — an untouched FR16 sitting
next to a transcript-writing feature is worse than either choice alone, because the next reader
builds against a guarantee the code does not keep.

Three requirements were amended in place for the same reason: FR42's "user-authored" (a job
description is supplied, not authored — the property is the absence of generation, not authorship),
FR58's panic-clear blast radius, and FR63's consent disclosure.

**The overlay's retrieval-only guarantee is untouched and FR79 exists to keep it that way.** The
risk was never the report itself; it is that a generated-text surface shipping in the same app
becomes the argument for relaxing the overlay path later. FR79 makes that structurally
unavailable — no import path from the report module to the overlay snippet API.

**D-31 is the load-bearing decision.** Every report finding must cite the utterance it rests on or
be rejected before display. The overlay cannot fabricate because it cannot generate; the report
must generate, so anchoring is the equivalent protection. Without it, the report is a model's
impression of an interview it did not attend, delivered to someone who will believe it about
themselves.

**PR #9 review round — five findings, all valid, all fixed. One was a live data-loss path.**

| Severity | Finding | Why it mattered |
|---|---|---|
| P1 | **No migration for existing schema-v1 note files.** T10.1 made `kind` mandatory and T10.2 replaced `NoteSet`, with no migration mentioned anywhere. Existing files would load as corrupt, and FR44's recovery would find every backup equally unreadable. | A user upgrading opens the app to find their prep notes gone — the exact catastrophe M3 was built to prevent, reintroduced by a feature that never mentions the notes store. Now T10.2a/FR73a–c/D-33. |
| P1 | **FR16's verification still said "no session content in any written file"** after its statement was rewritten for D-U8. | A conforming implementation fails its own test. Statement and test drifting apart is this project's recurring defect — notable here because for once it would have *failed correct code* rather than passing broken code. |
| P1 | **No M11 task owned the FR20 egress indicator.** The whole transcript leaving the device is the largest egress event in the product. | The report path could ship with the privacy indicator dark during the biggest upload it will ever make. D-27 in M8 was this same failure in the other direction, one milestone earlier. Now FR81a, owned by T11.7. |
| P2 | **Absence-based findings could not satisfy FR78.** | Two of four rubric dimensions produce their best findings by absence — the point you meant to make and never did. Demanding an utterance index forces the generator to drop the best findings or fabricate a citation. Now two evidence kinds, plus FR78a making the tracker the single adjudicator of coverage. |
| P2 | D-U9 pointed at FR84 (retention) for consent re-acknowledgement instead of FR85. | Anyone implementing from the decision table builds the wrong gate. |

**Open and flagged: OQ-7 / D-32.** Panic clear is scoped to the in-progress session only, sparing
previously saved ones. Argued both ways in the spec. Wants confirmation before T11.9 is built.

---

### M8 — Cloud STT backends · T8.1–T8.5 complete · 2026-08-09

**This milestone was labelled "Windows" and was not.** The status table said "M8–M9 — cloud
backends, packaging — both Windows". Cloud STT is a WebSocket client and an asyncio loop; it has
no Windows dependency at all. That is the second time a blanket label in this file hid buildable
work, one milestone after the first, so the caution above has been rewritten to demand a
falsifiable reason rather than a platform name.

**Delivered** — 35 new tests, 286 total. `ruff`, `ruff format`, `mypy` clean.

| Task | What exists | Notable coverage |
|---|---|---|
| **T2.1 (completed)** | `tests/conformance.py` — the T2.1 suite as a reusable artifact | It did not previously exist. `test_stt_interface.py` checked that a null object satisfied the Protocol *shape*, which is a typing check: a backend could violate all eight semantic rules and pass |
| T8.1 | `stt/deepgram.py` over raw `websockets` | Passes the conformance suite unmodified |
| T8.2 | `stt/elevenlabs.py` | Same suite, same plumbing, zero shared protocol code |
| T8.3 | Key in the credential store, header not URL | Grep test over a diagnostic export; the ring's secret guard rejects the key in any field |
| T8.4 | `stt/fallback.py` — `FallbackSttBackend` | Socket dies → local takes over → FR21 notice; switches once under repeated failures; primary closed even after the switch |
| T8.5 | `EgressMonitor` | Both paths independently settable and independently reported (FR20); dark after fallback, lit while cloud runs |

`stt/cloud.py` holds everything structural — the loop, the bounded queue, the capture clock, the
finalisation guarantee — so the two backends share all of the plumbing and none of the protocol.
That is what makes "both pass the same suite" a real claim rather than a coincidence.

**The conformance suite got a negative control.** `test_the_suite_actually_fails_a_broken_backend`
feeds it a backend that raises from `feed()` and asserts the suite rejects it. A conformance suite
that passes everything is worth nothing, and this project has enough history of tests that pass
while the property is broken to justify checking the checker.

**Two checks were deliberately kept *out* of the shared suite.** Rule 1's drop-and-report-DEGRADED
half needs a stalled transport — against a double that drains instantly nothing overflows, so
asserting DEGRADED there would fail a *correct* backend. Rules 2, 3 and 5 need scripted server
output only a specific protocol can produce. Both live per backend, with the reason recorded in
the suite's docstring so nobody "completes" it later by moving them in.

**Decisions made while implementing**

> **D-25 — the capture clock re-anchors on every connect.** Found in self-review, with no test
> covering it. A reconnect gives the vendor a new stream numbered from zero while `sent_s` keeps
> accumulating, so the first post-reconnect event mapped tens of seconds backwards; the ordering
> guard then correctly discarded it — *and every event after it*. The stream would report READY
> and transcribe nothing for the rest of the session. The worst shape available: a silent failure
> on the recovery path that exists to prevent an outage.

> **D-26 — `x = y or Default()` is banned for injected collaborators.** `DiagnosticRing.__len__`
> makes an empty ring falsy, so the idiom silently discarded an injected ring and wrote to an
> orphan object with no reader. **This was live in already-merged code** — `MatchingPipeline`,
> `SessionManager` and `Preflight` all had it. Every affected site now uses `is None`, and
> `test_every_component_keeps_the_ring_it_was_given` asserts *identity* at each one.
>
> The project's recurring defect in dependency-injection form, and the **eleventh** instance: the
> injection appears to succeed, the component behaves perfectly, and the only symptom is an empty
> export nobody reads until they need it. I found it because a test I wrote asserted on an
> injected ring and got zero events — had I asserted on behaviour instead, it would still be there.

> **D-27 — cloud egress is lit before the socket opens, cleared only after it closes.** Fixed a
> real ordering bug: a primary that fails inside `start()` triggers the fallback on the backend
> thread, which put the indicator out — and then `start()` lit it again, leaving it claiming cloud
> egress for the rest of a session running entirely locally. The error is now always in the
> over-reporting direction, which is the only safe one for a privacy indicator.

> **D-28 — frames in flight during a fallback are dropped, not replayed.** Replaying
> double-transcribes the overlap, so the assembler builds two utterances from one span and matching
> fires twice on the same question. A missing half-second beats a duplicated question.

**A defect I introduced and caught: `switched` meant two different things.** The re-entry guard is
set at the *top* of `_switch()` so a second FAILED event cannot start a second switch. Exposing
that same flag as the public `switched` property told callers the local backend was live and the
egress indicator settled while both were still mid-flight — and a test waiting on it then read the
indicator too early. Split into `_switching` (guard) and `_switch_complete` (an `Event`, with
`wait_for_switch()` for callers verifying FR21's 5 s bound).

**Repository hygiene, folded in at the user's direction.** `__pycache__/*.pyc` and
`interview_prep_recall.egg-info/` were tracked on `main` despite `.gitignore` covering both — they
predated the ignore rules, so git kept tracking them. 24 files untracked. The `.pyc` files were
also stale 3.11 bytecode for a 3.12 target.

**CI went red on mypy, and the cause is worth a standing note.** `websockets` is in the `[cloud]`
extra; CI installs `[dev]`. I had `pip install`ed it into the dev container to build against, so
mypy resolved it locally and failed on the runner. **The dev container is not the CI environment,
and a green local run is not evidence about CI whenever a new dependency is involved.** The fix
puts `websockets` in the same `ignore_missing_imports` override as the Windows-only packages —
it is imported lazily inside the connector factories, so nothing needs it to type-check or to run
the suite. Verified by uninstalling it and re-running both mypy and pytest, rather than by
re-running with it still present.

**PR #8 review round — three findings, all valid, all fixed.**

| Severity | Finding | Why it mattered |
|---|---|---|
| P1 | **`_final_seen` latched on the first final of the session and never cleared.** | Rule 2 is a *per-span* guarantee. Audio accepted after the first final that the server never finalised reported STOPPED instead of FAILED — the end of the interview dropped silently, by the mechanism written to make that impossible. My tests missed it because none of them fed a second utterance. |
| P1 | **`stop()` reported STOPPED with the worker still running.** `close()` allows 0.5 s while the flush tail waited a fixed 1.5 s, so the join could not succeed. The worker then emitted callbacks after `stop()` returned, and `FallbackSttBackend` cleared the egress indicator while the cloud socket was still open — FR20's false privacy statement, in its worst direction. | The internal tail is now bounded by the caller's timeout, the join gets a grace period, a surviving worker reports FAILED, and callbacks are detached unconditionally before `stop()` returns. |
| P1 | **`additional_headers` requires `websockets >= 14`; the floor was `>= 12`.** 12.x and 13.x call it `extra_headers`, so at the declared minimum every connect raised `TypeError` before opening a socket and cloud STT fell back to local 100% of the time. | Floor raised to 14, with the coupling noted at both call sites. Nothing caught this locally because the container had 17.0.1 installed. |

**A second CI-vs-local divergence in one milestone.** After the mypy failure, `pytest` then failed
to collect: `from tests.conformance import ...` needs the repo root on `sys.path`, which
`python -m pytest` provides by adding the cwd and the `pytest` console script that CI runs does
not. Now imported as bare `conformance`, which works under both. **The dev container is not the
CI environment**, and this milestone produced two separate failures whose entire cause was
assuming otherwise. Reproduce with `PYTHONSAFEPATH=1 python -m pytest` before pushing anything
that adds a dependency or a cross-module test import.

**Not verified, and cannot be here — AS-8.** Both protocols are written from documentation and
have never met a live endpoint. Message names (`CloseStream`, `start`/`end`), envelope shapes and
timestamp semantics are all assumptions. Everything *around* the wire is tested; the wire is not.
Deepgram's flush message is the specific one I am least sure of — `CloseStream` closes the stream,
where `Finalize` may be the correct request to flush pending finals. Verify with a real key
alongside T9.5, and do not treat the green suite as evidence about the protocol.

---

### M6 — Session lifecycle · logic complete · 2026-08-09

**M5 was skipped deliberately, not overlooked.** It is next on the critical path and entirely
Qt + `SetWindowDisplayAffinity`, so it cannot be built or verified here. It is fully specified
(design §9b/§9c) and waits on the Windows machine. M6's state machine and health model were named
in this document as the buildable-ahead work, so that is what was built.

**Delivered** — 59 new tests, 217 total. `ruff`, `ruff format`, `mypy` clean.

| Task | What exists | Notable coverage |
|---|---|---|
| T6.1 | `session/manager.py` — seven states, explicit transition table, illegal transitions raise | Every state observed as actually traversed; each illegal transition from IDLE raises |
| T6.2 | Purge with fixed hook ordering | `cancel_network` proven to run **first**; health reset; **note files SHA-identical across a panic clear** |
| T6.3 | Panic clear → `WIPED`, resumable | Resume needs no preflight re-run; a machine event cannot undo it |
| T6.5 | `session/preflight.py` — the block/warn classification with injected probes | Each of the 9 checks failed **in turn**; missing probe fails rather than passes; throwing probe is a failure not a crash |
| T6.6 | `BoundedFrameQueue` (design §1a) + per-stream worker supervision | Depth flat across 10,000 pushes; drop-oldest verified; restart budget per stream **and per session** |
| T6.7 | Degradation switches | Toggle mid-session with no restart, health follows |

**Decisions made while implementing**

> **D-20 — the restart budget resets when preflight passes.** `reset_supervision()` existed with
> zero call sites, so the counter persisted for the process lifetime: a stream that crashed in one
> session was held from its *first* crash in the next. FR61 is worded per session.

> **D-21 — `BoundedFrameQueue.push` always copies into a `bytearray`.** Two independent reasons,
> either sufficient: `zero()` cannot wipe immutable `bytes`, so storing them made FR15's audio
> guarantee silently false; and WASAPI callbacks reuse a scratch buffer, so holding the caller's
> array by reference would let the next callback overwrite an already-queued frame. That second one
> is silent audio corruption which would have surfaced as unexplained transcription errors with
> nothing pointing back at the queue.

> **D-22 — a panic clear is undone only by the user.** `resume()` from `WIPED` now refuses
> `automatic=True`. A stray device-return callback firing after the button was pressed would
> otherwise restart capture the user had just deliberately stopped.

> **Design §7 gained two fields.** It named `no audio detected (Ns)` and `NOT hidden from screen
> share` as derived states but carried no field either could be derived from, so neither was
> expressible. `silence_s` and `capture_excluded` added.

**Two tests were passing for the wrong reason and were rewritten.** `test_every_state_is_reachable`
added `PURGING` and `STOPPING` to its set as *literals*, so it passed even if the manager skipped
both entirely — it asserted only that the enum members exist. And the zeroing test covered only the
`bytearray` path, so `zero()`'s silent no-op on `bytes` went uncaught. **Ninth and tenth instances
of this project's recurring defect**, and the first time two landed in the same phase.

**PR #6 review round — four more findings, all valid, all fixed**

| Severity | Finding | Fix |
|---|---|---|
| P1 | **A second `pause()` overwrote the cause before validating.** A lock callback arriving while the user was already paused left `LOCK` behind even though the transition raised — so the next unlock would restart capture the user had deliberately stopped. The same failure D-22 closed on the panic-clear path, reachable by a different route. | Validate before recording. |
| P1 | **The LLM switch never reached the pipeline.** `set_switch("llm_matching", False)` flipped a detached config object and lit the local-only indicator while `MatchingPipeline` kept calling the API. The UI would have told the user their question text stayed on the device while it did not. | `attach_matching()`; toggling unattached now raises rather than degrading quietly. |
| P1 | **A throwing purge hook aborted the whole purge.** `cancel_network` runs first and closing an already-broken socket is the plausible failure — so capture would keep running with nothing cleared, and panic clear would fail precisely on the degraded session that needs it. | Every step runs; failures are collected and reported. |
| P2 | **`ring.clear()` had zero call sites** despite a docstring saying "called on session purge". Ended-session events leaked into the next session's export and crowded the bounded ring. | Cleared during purge, with the purge outcome recorded after so it survives. |

Two of these — the LLM switch and `ring.clear()` — are the **same shape as D-20**: a method that exists, is documented as being called, and is called by nothing. That is now three in one milestone. Worth checking for directly rather than waiting for review to find the next one.

**A process note.** One of these fixes silently did not apply: a string replacement missed because `ruff format` had reshaped the target onto one line, and the test suite still passed because the *old* behaviour was what the existing test expected. Only re-reading the file caught it. A patch that fails to match is not an error — it is a no-op that looks like success.

**Deferred — genuinely out of scope here, not forgotten**

| Item | Why | Where it lands |
|---|---|---|
| **T6.4** ProcMon FR16 allowlist trace | Windows-only tooling | Windows machine |
| **T6.5** real device/network probes | WASAPI, registry, network | Windows; classification logic is done and tested |
| **T6.6 sleep/lock + device-loss triggers** | Needs `WM_POWERBROADCAST` and `IMMNotificationClient`, which design §1 places in `audio/devices.py` and `watchdog.py` | M1/T1.4 on Windows |

**Stated plainly: T6.6's "lock/unlock resumes" criterion is not met by this phase.** The state
machine reacts correctly *if* something calls `pause(PauseCause.LOCK)`, and that something does not
exist yet. `PauseCause.LOCK` and `DEVICE_LOST` are currently reachable only from test code.

---

### PRISM design system adopted · 2026-08-09

The user supplied **PRISM**, their personal-brand design system, and asked for a UI mockup and for
it to be folded into the plan. Both done.

- **`docs/prism-design-system.md`** — the system itself, committed so the plan cites a versioned copy.
- **Design §9b rewritten** from invented per-component tokens to PRISM's. **§9c added** for the app
  chrome (editor, preflight, settings).
- **Mockup published** covering all four overlay states, import review, preflight, and session
  controls, plus the conflict resolutions.
- **D-17/D-18/D-19** recorded; **OQ-5** opened.

**Conflicts resolved rather than merged** — PRISM wins everywhere it disagreed with §9b: panel
surface `#0B0F14 → --plum-950`, radius `12px → 20px`, confirmed state `#4C9AFF → --blue-500`,
typography now specified as Plex Mono display / Plex Sans body.

**Two findings worth carrying forward**

> **D-18 — the overlay cannot follow PRISM's core layout rule.** §6 requires labels outside and
> below the card, on the canvas. The overlay floats over someone else's video call and has no
> canvas, so "outside the card" would mean drawing onto the call. It is the single documented
> exemption; every other surface obeys the rule.

> **OQ-5 — PRISM has no warning token, and this product needs one.** Its four semantic dots are
> danger, info, success, highlight. A degraded match and data-leaving-the-device are none of those:
> both mean "proceed, but know this", where red overstates and purple already means "new". Proposed
> `--amber-500: #FFC93D`, taken from the existing `--grad-3` stop so it stays in-family. **The
> mockup and §9b already assume it** — needs the user's approval or the documented `--purple-500`
> fallback.

**PR #5 review round.** Three findings, all valid, all fixed:

1. **FR23's text-scaling contract was lost** in the §9b rewrite — I replaced the section wholesale
   and dropped the height bounds and scaling rule, leaving only widths. That permitted a fixed-font
   build that satisfies the tokens and still fails FR23. Restored with explicit bounds, an
   interpolation formula, and a 13px floor.
2. **The tracker's visual tokens were lost the same way** — T7.4's acceptance criterion cites §9b
   for them. Restored, PRISM-native.
3. **PRISM's dark-mode secondary token fails WCAG AA** — see OQ-6. My own mockup had the same
   failure in two places, including the "nothing matched" message, which is the state the whole
   observability argument rests on. Fixed and republished.

Findings 1 and 2 share a cause worth remembering: **replacing a spec section wholesale silently
drops requirements that other documents depend on.** Neither was a wrong decision — both were
content that simply vanished. A section rewrite needs a diff read, not just a quality read.

**D-U7 — the overlay leaves PRISM's palette.** The user directed that the overlay be translucent
neutral gray rather than purple, overriding PRISM. Scoped to the overlay's surface, border and text
only: PRISM keeps the typography, radius, spacing ladder and semantic rails there, and keeps the app
chrome entirely. The reasoning holds independently of preference — a saturated panel tints the video
behind it, a neutral translucent one does not.

**D-U7a resolved — brightness is a user control (FR65), not a fixed pick.** Along with opacity
(FR24), both are sliders. The measurement that shaped it: **a continuous brightness ramp has an
unreadable middle.** At mid-gray, light text is 4.39:1 and dark text 3.71:1 — neither reaches the
4.5:1 body copy needs. A free slider would let the user park the overlay on a setting where it
cannot be read. So the control spans two bands (dark 0–25, light 75–100) and steps over the dead
zone, with ink and both state rails swapping variants at the crossover.

A second finding fell out of it: **PRISM's `--amber-500` is 1.0:1 on a light panel.** Adding a
brightness control means every accent has to work at both ends of the range, not just the end it
was designed for — so the degraded rail darkens to `#8A5A00` in the light band. Without that, the
degraded state would have silently vanished at exactly the setting someone picks for a bright room.

**OQ-5 and OQ-6 both resolved — PRISM absorbed both changes.** `--amber-500` is now its fifth
palette dot; `--ink-400 #9C94A8` is now the dark-mode secondary text token. `docs/prism-design-system.md`
carries a changelog recording why.

~~**D-U7a is open and needs one word from the user:** "light gray" could mean dark-neutral with light
text (which is what FR11, the user's own wording, describes) or a genuinely light panel with dark
text. Both are rendered side by side in the mockup. A is the working default; the loser gets deleted
rather than kept as a setting.~~

**New build consequence:** IBM Plex Mono and Sans must ship inside the executable. OFL-licensed so
bundling is permitted; a Latin subset adds roughly 1–2 MB, and a silent fallback to Consolas would
quietly undo the identity.

---

### M4 — Matching pipeline (+ T2.3) · T4.1–T4.6 complete · 2026-08-09

**Delivered** — 72 new tests, 158 total. `ruff`, `ruff format`, `mypy` clean.

| Task | Module | Notable coverage |
|---|---|---|
| **T2.3** | `stt/assembler.py` — utterance assembly, fragment merge-forward, context window, `StreamRouter` | Boundary cases per design §3; interim events never emit; fragment dropped at session stop; history bounded |
| T4.1 | `matching/prefilter.py` | Top-K ≥ τ_floor; empty on unrelated speech; **<50 ms for 200 notes**; τ_degraded derived from τ_floor |
| T4.2 | `matching/selector.py` | Forced `tool_choice`; enum ≤6 with 200 notes loaded; body never sent; freeform rejected end-to-end |
| T4.3 | `matching/pipeline.py` | Dispatch A(1), B(2), complete A first → A discarded; the inverse branch also asserted |
| T4.4 | same | Above τ_degraded → `DEGRADED`; below → no-match |
| T4.5 | same | ≤1 in flight; ≤1 retry with backoff; ceiling → local-only + FR35 signal |
| T4.6 | same | Mic utterances rejected at the pipeline boundary |

T2.3 was pulled forward because M4 consumes `Utterance`; building M4 on an invented type would have
diverged from the plan.

**Local review — confirmed issues, all fixed before push**

| # | Issue | Why it mattered |
|---|---|---|
| 1 | `_on_complete` cleared `_in_flight` on `seq` alone, without the nonce | Sequences restart at every purge, so a stale pre-purge completion could free the slot while a live post-purge call was still running — a second call would then be issued, breaking the one-in-flight invariant the entire gate rests on. **A fourth hole in this mechanism**, after the three found at specification stage. |
| 2 | Ceiling reached via a *non-retryable* error never degraded to local-only | `is_retryable(exc) and attempts >= ceiling` meant a budget exhausted by a 400 was silently not announced, contradicting FR40's "the user is told, not silently downgraded". |
| 3 | `_close()` merged a held fragment with no age check, and `tick()` expired *after* closing | A 40-second-old "mm" was glued onto an unrelated question and dragged the utterance's `t_start` backwards, which also corrupts the context-window anchor. Contradicts design §3's 30 s drop rule. |
| 4 | `purge()` reset semantics were wrong in both directions | First written to preserve `_attempts` (leaking the per-session ceiling across sessions), then over-corrected to reset it (refilling the budget on every panic clear). Both wrong: `purge()` is *within* a session (D-U5/FR64, `WIPED → RUNNING`), so a separate `start_session()` now owns the per-session resets. |
| 5 | No backoff between retries | FR40 says "retried at most once **with backoff**". An instant retry spends the second attempt while the rate limit is still in force. |
| 6 | No request timeout | Design §5 makes a 5 s hard timeout load-bearing for FR59 — the call cannot be cancelled, so without it the window for a pre-purge response is unbounded. |
| 7 | `InlineRunner` wrapped `on_done` in its own try | An exception raised *by the callback* re-entered it as a failure, emitting twice for one request. |
| 8 | Context string unbounded | It enters every stage-2 prompt, so it is a per-call token cost (NFR6). Capped at 600 chars. |

Two of my own tests asserted the wrong semantics for #4 and were rewritten rather than kept green.

**Possible risks — recorded, not fixed**

- **Prompt injection via interviewer speech.** The utterance is interpolated into the stage-2
  prompt. FR10's forced enum bounds the damage to selecting a *wrong note from the user's own
  set* — it cannot produce new text — so this is a match-quality risk, not a content risk. Revisit
  if the prompt ever gains freeform output.
- **Prefilter/index drift.** `Prefilter` holds a `NoteSet` and an `EmbeddingIndex` built at some
  earlier point. Deleted notes are skipped; notes *added* since the build are silently unmatchable.
  Rebuild-on-change belongs to the wiring in M6.
- **Unhandled embedder failure in `submit()`.** The exception propagates to the caller. The
  matching worker's restart policy is M6's `FR61` work; there is no worker yet to restart.
- **`StreamRouter` is not yet wired to the pipeline.** Both enforce FR53 independently. Connecting
  them is M6.

**Blocked, not attempted**

- **T4.7** (stage-1-only vs stage-1+2 accuracy) — the OQ-1 gate. Requires ≥3 recorded mock-interview
  transcripts with real prep notes and hand-labelled utterances. Only the user can produce these,
  and inventing fixtures would produce a number that decides the architecture on fabricated
  evidence. **Not started, deliberately.**
- **T2.2 / T2.4** — `faster-whisper` and the AS-1 latency gate need Windows.

---

### PR #3 review round · 2026-08-09

CI's first Windows run went red, and the automated review found five issues. All valid.

**CI failure — mypy version pin.** `python_version = "3.11"` matched the container; CI runs 3.12,
where numpy 2.5's stubs use `type` statements a 3.11 parser cannot read, so mypy died parsing a
dependency before checking any project code. Fixed to 3.12. The two settings mean opposite things
and must not be "aligned": ruff's `target-version` is the floor that keeps source runnable in the
container, mypy's `python_version` is the target that ships.

**Review findings, all fixed**

| Severity | Finding | Fix |
|---|---|---|
| P1 | **Path traversal via imported note-set id.** A JSON-controlled `id` reached `path_for()`, so a bundle with `"id": "../../escaped"` would make a later save write outside the app root. | `validate_id()` enforces canonical UUID at every construction and load boundary. Store surfaces it as `NoteSetCorruptError`. |
| P1 | **Missing `notes` key read as an empty note set.** `data.get("notes", [])` meant a file that lost its notes array loaded "successfully" with zero notes — `recovered=False`, backups never consulted, UI showing every note deleted. The exact opposite of FR44. | Missing or mistyped `notes` is now corruption and routes to recovery. |
| P1 | **Diagnostics value heuristic was insufficient.** Rejecting whitespace and long strings still accepts `"yes"`, `"No."`, or any single token, so `ring.record("stt", text=utterance)` leaked whenever the utterance was short. | Added `ALLOWED_FIELDS` — a **field-name** allowlist. The value heuristic remains as a second layer, but the name check is what holds the guarantee, because it fires regardless of what the value looks like. |
| P2 | **`stt/interface.py` did not exist** although mypy's strict override named it, so CI passed without type-checking any STT contract. | Wrote it (T2.1). It is the D-2 "written first" module and was fully specified in design §2. |
| P2 | **Export filename taken from the raw note-set name.** "Product / Program Manager" is an ordinary role title and became a non-existent subdirectory; an imported `../` name escaped the chosen destination. | `safe_stem()` sanitises the filename; the original name is preserved inside the content. |

**Decision recorded**

> **D-16 — Content guards must reject field *names*, not just values.** The ring's original design
> validated only what was passed. No value-shaped rule can separate a short transcript token from a
> structural identifier, so the guarantee was unenforceable at exactly the point it mattered. The
> allowlist inverts it: an unregistered field name fails at the call site whatever the value is.
>
> Same shape as D-13 two commits earlier — that one was credentials passing the value check, this
> one is short content passing it. Both were the value heuristic being asked to do a job it cannot
> do. **Seventh instance of this project's characteristic defect.**

**Note on tests.** Adding the field allowlist made two existing tests pass for the *wrong reason* —
they used unregistered field names, so they raised on the name check rather than the length/type
rule they claimed to test. Both were rewritten to use registered fields. A test that passes for the
wrong reason is the same failure mode in miniature.

---

### M3 — Notes store & indexing · logic complete · 2026-08-09

**Delivered** — 51 new tests (89 total after the PR #3 review round). `ruff`, `ruff format`, `mypy` clean.

| Task | What exists | Notable coverage |
|---|---|---|
| T3.1 | `notes/model.py` — `Note`, `NoteSet`, UUID4 identity, schema v1, `order_index` authoritative on load | IDs stable across edit + reorder; deleted IDs never reused across 100 creations |
| T3.2 | `notes/store.py` — atomic write (tmp → fsync → copy-rotate → `os.replace`), 5 generations | **SIGKILL mid-save × 10 consecutive runs, notes intact every time**; live file proven to exist at every point of rotation |
| T3.3 | Schema guard + corruption recovery | Newer schema refused with file byte-identical after; 4 corruption shapes recover; fall-through when `.bak.1` is itself corrupt; no readable backup raises rather than starting empty |
| T3.4 | Export/import `.md` + `.json` bundle | Round-trip preserves content, tags, bullets, order, IDs, `track_progress` |
| T3.5 | `notes/importer.py` — strategy detection, chunking, headline mapping, bullet proposal | Every proposed bullet asserted verbatim across all three strategies; single stray `Q:` does not trigger the Q/A convention |
| T3.6 | `notes/index.py` — `.npz` cache, `Embedder` Protocol | Model-version change forces full re-embed; headline edit re-embeds one note; **body edit re-embeds nothing**; corrupt cache rebuilt |

**Decisions made while implementing**

> **D-14 — Stale `.tmp` files are swept on store construction.** The SIGKILL test passed its
> durability assertion on the first run — notes intact all ten times — but left an orphaned
> `.tmp` behind each time. `os.replace` is atomic, so a surviving temp means the process died
> before the swap: the live file is fine and the temp is a worthless partial write. Left alone
> they accumulate one per crash, forever. The sweep runs in `NotesStore.__init__`.
>
> Worth noting the shape of this: the *guarantee* held and the *housekeeping* did not, and only
> an assertion beyond the requirement's literal wording caught it.

> **D-15 — `verify_bullets_verbatim()` runs on every save, not just at import.** FR42 is phrased
> as an import-time property, but the overlay renders `bullets` directly, so a non-verbatim
> bullet introduced by any later path — the editor, a migration, a hand-edited file — is
> generated content reaching the screen. Checking at the store boundary makes it unbypassable.

**Deliberately deferred to the Windows machine**

- **T3.7** notes editor UI, **T3.8** note-set lifecycle UI, **T3.9** backup-restore UI — all Qt.
  The store-side operations they drive (`save`, `delete`, `reorder`, `list_backups`,
  `restore_latest_readable`, `export_bundle`) are implemented and tested, so the UI work is
  wiring rather than logic.
- The `taskkill /F` form of T3.2's criterion. SIGKILL is the equivalent here and is genuinely
  hostile — it cannot be caught or cleaned up after — but the Windows run should still happen,
  since NTFS `os.replace` semantics are what actually ship.

**Not yet verified**

- Real `sentence-transformers` embeddings. Everything runs against `FakeEmbedder`, which satisfies
  the same Protocol. The swap is what FR17-style indirection is for, but it is untested until the
  extra is installed.

---

### M0 — Scaffold · complete · 2026-08-09

**Delivered**

| Task | What exists | Verified by |
|---|---|---|
| T0.1 | Package tree matching design §1 exactly, 31 modules (implemented + stubs), `pyproject.toml` with dependency groups | Import test; tree matches §1 |
| T0.2 | `.github/workflows/ci.yml` — ruff check, ruff format, mypy, pytest on `windows-latest`/3.12, excluding `device` and `slow` marks | Not yet observed green on a real runner (see Open items) |
| T0.3 | `diagnostics/ring.py` — bounded 2000, thread-safe, content-refusing, JSON export, never auto-writes | 10 tests incl. 8-thread concurrency |
| T0.4 | `tests/conftest.py` autouse write-allowlist guard patching `builtins.open` and `os.open` | Active on every test from now on |
| T0.5 | `platform/credentials.py` — `CredentialStore` over a `CredentialBackend` Protocol, in-memory double, `keyring` at runtime | 10 tests |

`pytest -q` → **20 passed**. `ruff check`, `ruff format --check`, `mypy interview_prep_recall` → clean.

**Decision made while implementing** (per DoD item 6)

> **D-13 — Diagnostics must be told what the secrets are.** The FR36 content guard rejects prose by
> requiring short, whitespace-free field values. An API key satisfies that check perfectly — it is
> short and unbroken — so the guard gave **zero** protection against credentials, and FR19's "never
> in a diagnostic export" rested on discipline. `DiagnosticRing.register_secret()` now exists and
> `CredentialStore` calls it on every get/set, so a key that has ever been loaded cannot enter the
> ring. Registered secrets deliberately survive `clear()`, because the credential is still loaded
> after a purge and the guard must stay armed.
>
> This surfaced as a failing test I had written on a wrong assumption. Worth recording because it is
> the fourth instance of this project's characteristic defect: **a guarantee whose test passes while
> the property is broken.** The fix was to change the code, not the test.

**Deviations from the spec, and why**

1. **`sentence-transformers` is not a hard dependency.** It is in the `embeddings` extra. The index
   will take an `Embedder` Protocol so unit tests run against a deterministic fake and CI needs no
   torch. Real embeddings still run behind the same interface. This strengthens FR17's swappability
   argument rather than weakening it.
2. **`mypy --strict` is scoped to `stt/interface.py`**, per T0.2's wording, with default strictness
   elsewhere. Optional Windows-only imports are in an `ignore_missing_imports` override.
3. **`docs/` excluded from ruff**, after a format pass rewrote fenced code blocks in the design doc
   and created pointless diff churn.

**Open items carried forward**

- CI has never run on a real Windows runner. First push will tell us whether the Windows-only
  extras resolve there. If `pyaudiowpatch` fails to install on the hosted runner, split the install
  so CI takes only `[dev]` and the Windows extras are exercised on the target machine.
- The OS half of T0.5 (actual Credential Manager binding) is unverified until Windows.

---

## Standing reminders for whoever picks this up

- **The three gates are not checkboxes.** T1.2, T2.4 and T4.7 are measurements that can change the
  architecture. A bad number changes the plan; it does not get waived.
- **This project's recurring defect is a test that passes while the guarantee is broken.** Eleven
  instances so far, the latest being an injected `DiagnosticRing` silently replaced by an orphan
  because an empty ring is falsy (D-26). Four early instances: the PRD's absolute no-disk claim, the zeroed-`bytearray` purge assertion, the
  `weakref`-on-`str` sweep, and D-13 above. When writing a test for a privacy or correctness
  guarantee, verify the property, not the claim.
- **Fixtures are the long pole and only the user can make them.** Real prep notes, two or three
  recorded mock interviews, and hand-labelled utterances. T4.7's gate and the matching regression
  suite both depend on them, and nothing in the code substitutes.
