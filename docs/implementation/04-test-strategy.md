# Test Strategy

Two properties of this system shape the whole strategy:

1. **The failure window is a live job interview.** There is no retry and no rollback. Defects
   must be found before that window, which means the risky behaviors — concurrency, purge,
   capture exclusion, degradation — need deterministic tests, not manual spot checks.
2. **The privacy guarantees are the product.** A test suite that proves matching works but cannot
   prove FR16 has tested the less important half.

---

## 1. Test Levels

| Level | Scope | Runs |
|---|---|---|
| **Unit** | Pure logic: chunking, utterance assembly, sequence gate, threshold math, rotation | Every push, Windows CI |
| **Contract** | The `SttBackend` conformance suite (T2.1), run against every backend | Every push (local); nightly (cloud, against sandbox keys) |
| **Integration** | Component pairs: capture→STT, STT→matching, matching→overlay | Every push |
| **Property/fuzz** | Notes store round-trip, chunker against malformed input | Nightly |
| **Soak** | 60-minute dual-stream session | Nightly |
| **Fault injection** | The degradation ladder, every row | Every push where mockable; nightly for the rest |
| **Manual scripted** | Capture exclusion, glance legibility, echo detection | Per milestone + pre-release |

---

## 2. Test Fixtures

The single highest-leverage investment. Without these, most requirements are only manually
verifiable and will silently stop being verified.

| Fixture | Contents | Serves |
|---|---|---|
| **`audio/scripted_*.wav`** | Recorded mock-interview audio with a ground-truth transcript and timestamps | NFR1, FR46, FR47, T2.4 |
| **`audio/echo_*.wav`** | Same session recorded twice — once over headphones, once over speakers | FR57, T7.2 |
| **`notes/*.md` / `*.txt`** | Real-shaped prep notes: bulleted, paragraph-only, malformed, empty, 200-note set | FR1a, FR2, FR42, D-6, FR48 |
| **`transcripts/labeled_*.json`** | Utterances hand-labeled with the correct note ID or `none` | T4.7, OQ-1, the matching regression suite |
| **`notesets/corrupt_*.json`** | Truncated, wrong `schema_version`, invalid UTF-8 | FR31, FR44 |

`transcripts/labeled_*.json` doubles as the **matching regression suite**: any threshold change
reruns it, so tuning τ_floor cannot silently trade recall for precision without the number moving.

---

## 3. How the Hard Requirements Get Tested

These are the ones where a naive approach produces a test that passes while the requirement is
broken.

### FR16 — nothing written to disk

Not a unit test. A **procedure**, automated as far as Windows allows:

1. Start Process Monitor filtered to the app process.
2. Run a 45-minute simulated session (scripted audio, both streams, matching active).
3. Export the trace; diff every written path against the allowlist:
   the allowlist in **design §4** — `%APPDATA%\InterviewPrepRecall\**`, `QSettings` registry keys,
   the PyInstaller `_MEI*` temp dir, the `faster-whisper` model cache, **and the HuggingFace/torch
   cache** (`%USERPROFILE%\.cache\huggingface`, `%LOCALAPPDATA%\torch`). Cite §4 rather than
   restating it — an earlier version of this list omitted the torch cache and would have failed
   any correct first run.
4. For each allowlisted file written during the session, grep for known-unique phrases from the
   scripted transcript.

**Pass:** no path outside the allowlist, and no transcript phrase inside any written file. Run
against the **packaged** build, not just the dev build — PyInstaller changes the write profile.

### FR15 / FR58 / FR59 — purge

- **Zeroing (audio only):** hold a `memoryview` of the audio buffer across purge; assert all bytes
  zero. Asserting "the variable is `None`" would pass while the memory still holds the audio.
- **Transcript:** `str` does not support weak references (`weakref.ref("x")` raises `TypeError`), so
  the sweep runs on identities and containers: record `id()` of each transcript string in a
  debug-only registry, `gc.collect()` after purge, assert `gc.get_referrers()` yields no application
  object for any recorded id, and assert no live `TranscriptEvent`/`Utterance` remains. **Do not
  assert zeroed memory** — unsatisfiable for `str` (design §6), and it would pass vacuously, which
  is the exact defect class this suite exists to catch.
- **Scope:** SHA-256 every note file before and after panic clear; assert identical (FR58).
- **In-flight:** a mock LLM client that completes 500 ms *after* purge; assert the response is
  discarded and nothing renders (FR59).

### FR32 — sequence gate

The bug the PR review caught is the primary test case:

```
dispatch A (seq 1, latency 800ms)
dispatch B (seq 2, latency 100ms)   # supersedes A
assert: B renders
assert: A is discarded on arrival, never rendered, even transiently
```

Plus: A completes *before* B is dispatched → A renders. Both branches, because a gate that
discards everything also passes the first assertion.

### FR14 / FR14a — capture exclusion

Manual and unavoidable — no automated harness can prove absence from a real screen share. The
matrix is Zoom × Teams × Meet × {full screen, single window} = 6 checks, re-run whenever the
overlay's window creation changes. The **failure path is automatable**: stub
`SetWindowDisplayAffinity` to return false and assert the persistent warning appears.

### FR33 / NFR5 — backpressure and memory

Inject an STT backend with an artificial 3× realtime processing delay. Assert: queue depth stays
bounded, oldest chunks drop, health reports `falling behind`, and RSS is flat across 60 minutes.
A test that only checks "it doesn't crash" would pass while latency drifts to minutes.

### FR57 — echo detection

**Preflight:** paired headphone/speaker fixtures. Speaker recording must warn; headphone recording
must not. Assert the measured cross-correlation is logged, so a threshold regression is diagnosable
rather than a flipped boolean.

**Runtime — both assertions are required, and the second is the one that catches a backwards
implementation.** Play a question through speakers so it reaches both streams:

1. The **interviewer** utterance still reaches matching and can produce a snippet.
2. The echoed **mic** utterance does **not** mark a tracked point.

A suppressor wired to the wrong stream passes a test that checks only "no duplicate processing" —
it would silently discard the real question while the echo still marked the checklist.

### FR36 — diagnostics contain no content

Run a full session, export the ring buffer, assert no substring from the scripted transcript or
from any loaded note appears. Complements the FR16 grep and catches the likelier leak: a
well-intentioned debug field added later.

---

## 4. Concurrency Testing

The design's threading model (D-1) is where the expensive, intermittent bugs live.

- **Determinism:** all queues and the sequence gate are tested against a fake clock and injected
  latencies, not `sleep()`. Timing-dependent tests that pass on CI and fail on a loaded laptop are
  worse than no tests.
- **Qt thread affinity:** an assertion helper that raises if a widget is touched off the main
  thread, enabled in all test runs. This catches the class of bug that otherwise appears only as
  a rare crash in front of a real interviewer.
- **Soak:** 60-minute dual-stream run nightly, asserting flat memory (NFR5), no dropped
  finalizations (FR47), and no thread leaks.
- **Fault injection:** every row of design §9 has a test that forces the failure and asserts both
  the response and the signal. The signal assertion matters as much as the response — silent
  recovery violates FR35's purpose.

---

## 5. Measurement, Not Just Pass/Fail

Three tasks produce **numbers that decide the architecture**, and their results belong in the
decision log:

| Measurement | Task | Decides |
|---|---|---|
| Local STT p50/p95 on the target machine | T2.4 | AS-1 — whether local can be the default at all |
| Stage-1-only vs stage-1+2 precision/recall, call count, token spend, added latency | T4.7 | OQ-1 — whether the LLM dependency is worth its cost |
| Dual-stream 60-min stability | T1.2 | AS-2 — whether `pyaudiowpatch` supports D-U2 |

Each is a **gate**. If the number is bad, the plan changes; it does not get waived because the
milestone is otherwise complete.

---

## 6. Release Gates

The review's two-gate checklist is the release procedure. Gate 1 is build acceptance (data
integrity, privacy, correctness, resilience, observability, latency). Gate 2 is live-use
readiness (rehearsals, notes exported, consent understood, fallback practiced).

The base checklist lives in [`../build-plan-safety-review.md` §5](../build-plan-safety-review.md).
This section holds **only the delta** added since that review — the two are read together and
neither restates the other. *(An earlier version claimed "one copy, so they cannot drift" and then
added five items immediately below, creating the second copy it warned about — review-B C9.)*

### Release definition of done

Gates alone are not a release criterion; they omit roughly a dozen `v1` requirements. v1 ships when
**all four** hold:

1. Every `v1`-status requirement in [`01-requirements.md`](./01-requirements.md) has passed the
   verification named in its own row. This is the binding condition — the gate checklists are a
   prioritised subset, not a superset.
2. Safety-review §5 Gate 1 (build acceptance) passes in full, against the **packaged** build.
3. The delta items below pass.
4. Safety-review §5 Gate 2 (live-use readiness) passes, including two full rehearsals.

The three architecture gates (AS-1, AS-2, OQ-1) are **not** release gates — they are decision
points earlier in the plan that may change what gets built.

### Gate 1 delta — added since the review:

- [ ] Mic and loopback both captured for 60 min without conflict (D-U2 / AS-2).
- [ ] Progress tracker does not mark from loopback audio (FR56).
- [ ] Echo warning fires over speakers, not over headphones (FR57).
- [ ] Degraded matches are visually distinguishable from confirmed at a glance (FR51 / D-U3).
- [ ] Every rendered overlay string is a byte-exact substring of a stored note (FR42 / D-5).

---

## 7. What Is Not Tested, and Why

Recorded so these are decisions rather than oversights:

- **Real interview accuracy.** Cannot be tested pre-release; approximated by labeled transcripts
  (T4.7) and rehearsals (Gate 2).
- **Panel interviews.** AS-5 accepts degraded attribution. No fixture.
- **Every Windows audio device combination.** Tested against the target machine plus one
  Bluetooth headset; broader coverage is not affordable and the FR39 re-bind path is the mitigation.
- **Third-party STT accuracy.** Vendor responsibility. Tested only for interface conformance
  (T8.1/T8.2) and fallback behavior (T8.4).
