# Safety & Architecture Review — Interview Prep Recall Build Plan

**Reviewer role:** Principal Engineer / Production Risk Architect
**Artifact reviewed:** `interviewpreprecallprd.md` (Requirements & Build Plan)
**Status:** Pre-implementation. No application code exists in this repository at time of review.
**Date:** 2026-08-08

---

## 0. Scope Note — What "Production Risk" Means Here

The review request framed this against rolling deployments, microservices, database
migrations, and API contracts. This system has none of those. It is a single-user Windows
desktop application with no server, no shared state, no multi-tenant data, and no
deployment fleet. Reviewing it against a distributed-systems checklist would generate
findings for failure modes that cannot occur.

The five dimensions still map cleanly, but onto different things:

| Requested dimension | Real analogue in this system |
|---|---|
| Production safety & data integrity | The user's prep notes — the only persisted asset, and irreplaceable before an interview |
| Backwards compatibility | Notes-store schema, `QSettings` keys, embedding-model version, and the STT interface across app upgrades |
| Rollback & recovery | Downgrading a PyInstaller single-exe, and **in-session** recovery when a component fails mid-interview |
| Edge cases & race conditions | Audio device churn, STT backpressure, out-of-order async LLM responses, API rate limits |
| Observability & blast radius | Diagnosability under a hard no-persistence rule; blast radius = one live interview, unrecoverable |

The severity driver is unusual and should be stated plainly: **the failure window is a live
job interview.** There is no retry. A crash, a frozen overlay, a leaked note on a screen
share, or a wrong snippet at the wrong moment cannot be rolled back. That single property
is what lifts several otherwise-minor findings into High.

---

## 1. Executive Summary & Risk Rating

### Overall risk rating: **HIGH**

Not because the plan is careless — it is unusually thoughtful for a personal project, and
the guardrails in §4 are real engineering constraints rather than aspirational copy. The
rating is driven by four specific things:

**Justification:**

1. **The single most valuable asset in the system has no protection.** Prep notes are the
   only thing written to disk, they represent hours of irreplaceable work, and the plan
   specifies no backup, no export, no atomic write, no schema version, and no corruption
   recovery. A crash during a note save the night before an interview destroys the entire
   value of the product at the exact moment it is needed. This is the clearest
   data-integrity gap in the document and it is not mentioned anywhere in §12.

2. **Two hard guardrails are stated more strongly than the design can deliver.** FR16
   ("no audio file is ever written to disk") and US-F2 ("confirmation that nothing was
   written to disk") cannot be honestly satisfied on Windows, because the OS writes process
   memory to `pagefile.sys` outside the application's control, and crash dumps, PyInstaller
   temp extraction, and HTTP client buffers all bypass the application's own file
   discipline. Promising a user a guarantee the platform does not permit is a trust and
   integrity defect, not merely a wording issue — and this product's entire premise is
   trust.

3. **The LLM fallback path silently violates the product's core promise.** §10b says that
   on LLM failure or timeout, fall back to the top stage-1 embedding match. US-D2 and the
   Retrieval-only principle in §4 say the overlay shows nothing rather than a guess. These
   are in direct contradiction: the fallback shows the user a lower-confidence guess
   *precisely when the system is degraded*, and nothing in the plan tells the user this
   happened. A user who has been trained to trust "it only shows me real matches" gets a
   guess at the worst possible moment.

4. **There is no in-session recovery story.** The plan has a rollback strategy for neither
   deployment (expected — it is a desktop exe) nor, more importantly, for the failure that
   actually matters: a component dying at minute 12 of a 45-minute interview. FR21 covers
   exactly one case (cloud STT connection drop). Audio device loss, STT process crash,
   overlay hang, LLM rate-limiting, and memory exhaustion are all unhandled.

**What is genuinely strong and should not be traded away:** the two-stage matching design
with a forced `tool_choice` enum (FR10/§10b) is the right architectural call — it converts
an anti-fabrication *prompt* into an anti-fabrication *type constraint*, which is the
correct instinct. The capture-exclusion requirement (FR14) is a real risk caught early.
Phasing the audio spike first (Phase 1) correctly de-risks the highest-uncertainty
component before anything is built on it. Credential Manager for keys (FR19) is right.

**Recommended gate:** Do not begin Phase 5 (Overlay UI) until the P0 amendments in §3 are
folded into the plan. Phases 1–4 can proceed as written, with the Phase 2 and Phase 4
amendments noted.

---

## 2. Gaps & Vulnerabilities Discovered

### 2.1 Production Safety & Data Integrity

**DI-1 — Notes have no durability guarantees. [Critical]**
Notes are the only persisted user data and the only irreplaceable asset. The plan never
specifies the storage format, write strategy, or recovery behavior. A non-atomic write
interrupted by a crash, a power loss, or a `PyInstaller` process kill leaves a truncated or
empty notes file. FR3 (edit/delete/reorder) implies repeated rewrites, multiplying exposure.
*Loss scenario:* user reorganizes notes at 11pm, app crashes mid-save, notes file is
zero-length, interview is at 9am.

**DI-2 — No export or backup path. [High]**
US-A3 introduces multiple note sets, increasing the stored corpus, but nothing in FR1–FR4
lets a user get their notes back *out*. The data is trapped in an app-private store with no
disaster recovery and no portability. This also creates lock-in that the user has no reason
to accept for their own text.

**DI-3 — Destructive operations are unguarded. [High]**
FR3 specifies delete. US-F3 specifies a "panic clear" that *instantly wipes* the session.
Neither has a confirmation, an undo, or a defined blast radius. Specifically: **it is not
stated whether panic-clear touches notes.** It must not — but the plan does not say so, and
an implementer could reasonably wire "wipe everything" to that control. A panic-clear that
deletes prep notes mid-interview is the worst single outcome this codebase can produce.

**DI-4 — Notes store has no schema version. [Medium]**
FR2 chunking rules, FR4 tags, and note IDs will change shape as the product evolves. Without
a version field written from day one, a future release cannot safely distinguish "old
format" from "corrupt", and will either crash or silently drop tags.

**DI-5 — "Nothing written to disk" is unenforceable as stated. [High]**
FR16 and US-F2 promise more than Windows allows. Uncontrolled write paths include:
`pagefile.sys` (transcript strings paged out of RAM), Windows Error Reporting crash dumps
(which contain heap memory, i.e. transcript text), the `PyInstaller` one-file bootloader's
temp extraction directory, `faster-whisper` model cache and any temp files, HTTP/WebSocket
client debug logging if ever enabled, and Qt clipboard contents if snippet copy is added.
None are addressed.

**DI-6 — Purge is specified as an intent, not a mechanism. [Medium]**
FR15/US-F1 say buffers are "immediately cleared". In Python, `del` and reassignment do not
zero memory; strings are immutable and their backing buffers linger until GC and may be
reused or paged. A literal implementation of FR15 will leave transcript text recoverable in
process memory long after "purge". If the guarantee is worth stating, it needs a real
implementation (mutable buffers, explicit zeroing) or an honest downgrade of the claim.

### 2.2 Backwards Compatibility

The relevant contracts here are between **app versions on one machine**, and between
**in-process components** — not between services.

**BC-1 — Embedding model version is an implicit, unversioned contract. [High]**
Notes are embedded at import time (§9 component 3, Phase 3). If a later release changes the
`sentence-transformers` model, changes its version, or changes normalization, previously
stored embeddings become silently incomparable with newly computed query embeddings.
Similarity scores degrade in a way that produces *no error* — just quietly worse matching,
which is nearly undetectable to the user and directly attacks the product's core function.
This is the classic silent-corruption failure of embedding systems and the plan has no
guard for it.

**BC-2 — Note IDs are load-bearing across two boundaries and have no stability rule. [High]**
Note IDs appear in the LLM tool enum (§10b), in the index, and implicitly in the overlay's
selected result. Nothing states whether IDs are stable across edits, reorders (FR3), or
re-imports. If IDs are positional or regenerated on save, then editing one note can silently
remap every match. If IDs are reused after deletion, a stale in-flight LLM response can
resolve to the *wrong note* (see RC-3).

**BC-3 — `QSettings` keys are an unversioned upgrade contract. [Medium]**
FR26 persists position, size, and opacity to the Windows registry. A future release that
changes units, multi-monitor coordinate handling, or key names inherits stale values with no
migration path — the common concrete failure being an overlay restored to coordinates on a
monitor that is no longer attached, rendering it invisible with no obvious reset.

**BC-4 — The "common streaming STT interface" (FR17) is asserted, never specified. [High]**
It is the plan's main extensibility claim and Phase 2's primary deliverable, but the
document never defines its surface: partial vs. final results, timestamps, error and
reconnect semantics, backpressure signalling, or cancellation. Local Whisper (batch-ish,
chunked, no network) and Deepgram/ElevenLabs (true streaming, interim results, WebSocket
lifecycle) have *materially different* semantics. An interface designed around whichever is
built first will leak that backend's assumptions and make FR18/FR21 swapping far harder than
the plan assumes. Phase 2 explicitly builds cloud first, so the interface will be shaped by
the cloud model and then have local retrofitted into it.

**BC-5 — Anthropic model pin will age out. [Low]**
`claude-haiku-4-5-20251001` is hard-pinned in §10b. Pinning is correct, but there is no
stated policy for what happens on deprecation, and no config surface to change it without a
rebuild.

### 2.3 Rollback & Recovery

The plan has **no rollback section at all**. Two distinct kinds are missing.

**RB-1 — No application-version rollback. [Medium]**
`PyInstaller` single-exe (§10) with no versioning scheme, no side-by-side install, and no
statement about whether a downgraded build can read a newer notes store or newer
`QSettings`. In practice the forward-compatibility direction is the dangerous one: v1.2
writes a settings/notes shape, user reverts to v1.1, v1.1 crashes on load or discards data.

**RB-2 — No in-session degradation ladder. This is the important one. [High]**
The only in-flight recovery specified is FR21 (cloud STT drop → local). There is no defined
behavior for: WASAPI device disappearing or the default output device changing mid-call
(headphones connected/disconnected — extremely common on a video call), the local Whisper
worker crashing or OOMing, the overlay process hanging, Anthropic API returning 429/5xx
repeatedly, or the machine sleeping/locking mid-session. Each of these leaves the user
silently unassisted, which US-C3 explicitly says must never happen — but US-C3's guarantee
is only wired to audio capture failure.

**RB-3 — Recovery from a failed notes migration is undefined. [Medium]**
Related to DI-4/BC-1: if a future version re-chunks or re-embeds on upgrade, there is no
statement that the original is preserved until the migration verifies.

### 2.4 Edge Cases & Race Conditions

**RC-1 — STT backpressure is unbounded. [High]**
FR8 streams audio in 2–4s rolling chunks. NFR §7 concedes local CPU latency is ~2–3s and
*unverified*. If per-chunk processing time exceeds chunk duration on the user's actual
hardware, the queue grows without bound: latency drifts steadily, memory climbs across a
45-minute session, and snippets arrive answering questions from minutes ago — worse than
useless mid-interview, because it actively misleads. No queue bound, no drop policy, and no
"falling behind" signal are specified.

**RC-2 — Transcript buffer growth is unbounded. [Medium]**
"Live Transcript Buffer — in memory" (§9) has no cap. A 45-minute session is small in
absolute terms, but combined with RC-1's backlog and no eviction policy, memory is a
function of session length with no ceiling — and paging it out defeats FR16 (DI-5).

**RC-3 — Async LLM responses can arrive out of order. [High]**
Each utterance triggers a stage-2 call with a few hundred ms of latency (§7). Utterances
arrive every 2–4s, but latency is variable and retries make it more so. Nothing in the plan
sequences responses. Concretely: utterance A dispatches, utterance B dispatches 2s later, B
returns first, then A returns and **overwrites the overlay with a stale match** for a
question the interviewer already moved past. This is a real, likely, user-visible race and
the plan has no generation counter, no cancellation of superseded requests, and no
ordering guarantee.

**RC-4 — Panic-clear (US-F3) races in-flight network calls. [High]**
The user hits panic-clear. There may be an in-flight cloud STT WebSocket carrying audio and
an in-flight Anthropic request carrying question text. The plan defines panic-clear as
wiping local state only. Without explicit cancellation, data the user just demanded be
destroyed is still in transit, and a late response can repopulate the overlay *after* the
wipe — visually contradicting the guarantee at the exact moment the user is anxious enough
to have hit the panic button.

**RC-5 — API rate limiting and cost runaway are unhandled. [Medium]**
One LLM call per transcribed utterance, with no debounce, no coalescing, no retry policy,
and no rate-limit handling. Continuous speech at 2–4s chunks is ~15–30 calls/minute
sustained. §7's "few cents per interview" assumes the stage-1 prefilter suppresses most
calls, but the floor threshold is unspecified and untuned — set it low and nearly every
utterance escalates. 429s are not mentioned anywhere.

**RC-6 — The enum has no size bound. [Medium]**
`enum: [*current_note_ids, "none"]` (§10b) is populated from the *currently loaded notes*.
The stage-1 prefilter returns 3–5 candidates, but the code as written puts **all** note IDs
into the enum, not the candidates. With a large note set that inflates every request, and
diverges from the stated design ("selects among the prefiltered candidates", FR9). This is
a concrete bug in the reference snippet, not just a doc ambiguity.

**RC-7 — Overlay always-on-top vs. screen sharing has a residual leak path. [Medium]**
FR14 uses `WDA_EXCLUDEFROMCAPTURE`, which is the correct API. But it is not a total
guarantee: it is bypassed by hardware capture, by a phone camera pointed at the screen, and
its behavior differs across capture methods and older Windows builds. NFR §7 sets the
minimum to build 19041+, which is right, but the plan should state the *failure* behavior:
what happens if the API call fails at runtime? As written, a silent failure produces an
overlay that the user believes is hidden and is not.

**RC-8 — Speaker separation assumption is fragile. [Medium — already noted in §12]**
Loopback-vs-mic separation breaks when the user's own voice is echoed into the loopback
stream (speakers rather than headphones), which is common. The progress tracker (FR12/US-G2)
would then mark points "mentioned" from the interviewer's speech. §12 flags panel interviews
but not the acoustic echo case.

**RC-9 — Multi-monitor and DPI changes. [Low]**
FR22/FR26 persist position. Docking/undocking a laptop, changing DPI scaling, or losing an
external monitor between sessions can restore the overlay off-screen with no recovery
control specified.

### 2.5 Observability & Blast Radius

**OB-1 — Observability and the no-persistence principle are in unresolved tension. [High]**
The plan has no logging, metrics, or diagnostics story at all — understandably, since §4
forbids persisting session content. But the result is that when the tool fails during a real
interview, there is *no way to find out why afterwards*, and the user cannot even tell the
difference between "nothing in my notes matched" (working as designed, US-D2) and "the
matching pipeline is broken" (a defect). These two states are visually identical: an empty
overlay. That is the single worst observability property a system like this can have.

**OB-2 — No user-facing health surface. [High]**
US-C3 asks for clear notification of audio failure. Nothing equivalent exists for STT health,
LLM health, latency drift (RC-1), or fallback state. FR21 mentions "a brief notice" for one
case. The user needs a persistent, glanceable health signal, because the cost of *not
noticing* degradation is measured in interview outcomes.

**OB-3 — Blast radius controls are absent. [Medium]**
No feature flags, no kill switches, no staged enablement. For a desktop app this does not
mean canary deployments — it means the ability to turn off a misbehaving subsystem *without
uninstalling*, ideally mid-session: disable LLM matching and fall back to local-only, disable
the progress tracker, disable cloud STT. Phase 8 mentions a settings screen but no
degradation switches.

**OB-4 — Phase 6 verification is asserted, not designed. [Medium]**
"verify nothing touches disk" is a phase deliverable with no method. This needs a real
procedure (e.g. Process Monitor capture over a full simulated session, filtered to the
process, reviewed against an allowlist of expected paths) or it will be verified by
assumption.

**OB-5 — No first-run / pre-flight validation as a gate. [Medium]**
US-B3 wants an audio test. This should be broadened into a pre-session readiness check —
audio device present, notes loaded, STT backend reachable, API key valid, Windows build
sufficient for FR14, overlay exclusion actually applied — and it should be *run
automatically before session start*, not left as a thing the user remembers to do. The whole
product is for someone whose stated difficulty is executive function; a readiness step that
depends on the user remembering to perform it is designed against its own user.

### 2.6 Cross-Cutting: Legal & Consent [High]

Not one of the five requested dimensions, but it is a genuine blast-radius issue and the
plan touches it only glancingly (§3 non-goals, §4 note on employer policies).

The app intercepts the other party's speech in real time. Several US states and many other
jurisdictions have all-party consent wiretap statutes whose trigger is **interception**, not
retention — so "we never write it to disk" is not necessarily a defense. Separately, many
employers' interview terms prohibit capture. The plan's own §4 acknowledges the employer-policy
angle as a *reason to prefer local processing*, which is the right instinct but stops short
of the actual exposure. The consequences (rescinded offer, legal exposure) are severe and
land entirely on the user. This warrants an explicit, unavoidable first-run disclosure —
not buried in settings.

---

## 3. Concrete Recommendations & Plan Amendments

Exact modifications to make to `interviewpreprecallprd.md`. P0 items should land before
Phase 5; P1 before packaging (Phase 8).

### P0 — Required before further build

**A1. Add FR28–FR31 under a new "Notes Durability" subsection in §6.** *(fixes DI-1, DI-2, DI-3, DI-4)*
- **FR28:** All notes writes are atomic — write to a temp file in the same directory, `fsync`,
  then atomic rename over the target. Never write in place.
- **FR29:** The app retains the last N (suggest 5) prior versions of each note set, rotated on
  save, so an accidental delete or a bad edit is recoverable without user action.
- **FR30:** Notes can be exported to a plain `.md`/`.json` bundle from the UI, and re-imported.
  No user data is trapped in an app-private format.
- **FR31:** The notes store carries an explicit `schema_version` from the first release. On
  encountering a newer version, the app refuses to load and says so rather than
  best-effort-parsing.

**A2. Amend FR15/US-F3 to state the panic-clear blast radius explicitly.** *(fixes DI-3, RC-4)*
Add verbatim to FR15: *"Panic clear and session purge affect audio buffers, the transcript,
and current overlay state only. They never touch stored notes, note sets, or settings under
any circumstance."* Add: *"Panic clear also cancels all in-flight network requests (cloud STT
socket, LLM matching call) before clearing local state, and any response arriving after a
purge is discarded rather than rendered."*

**A3. Rewrite FR16 and US-F2 to be truthful.** *(fixes DI-5, DI-6)*
Replace "no audio file is ever written to disk" with a scoped, defensible claim:
*"The application never writes audio, transcripts, or matched-snippet content to disk. Note
that the operating system may page process memory to `pagefile.sys` and may write crash dumps
containing process memory; these are outside application control. The app disables Windows
Error Reporting dumps for its own process and sets no-cache options where available."*
Rewrite US-F2's AC from "confirmation that nothing was written" to *"a documented, repeatable
verification procedure (Process Monitor trace over a full simulated session) demonstrating the
application process performs no writes outside its settings and notes directories."*
Add to FR15 that transcript buffers use mutable byte/char buffers that are explicitly zeroed
on purge, rather than relying on Python string reassignment.

**A4. Resolve the retrieval-only contradiction in §10b.** *(fixes the §1.3 finding)*
The current "fall back to the top stage-1 embedding match" directly contradicts US-D2 and the
Retrieval-only principle. Choose one and state it. Recommended: *"On LLM failure or timeout,
fall back to the top stage-1 match **only if it clears a second, higher confidence threshold
than the normal prefilter floor**, and mark the snippet visually as a degraded/low-confidence
match. If it does not clear that bar, show nothing, consistent with US-D2."* The user must be
able to tell a degraded match from a confirmed one.

**A5. Fix the enum-population bug in the §10b code sample.** *(fixes RC-6)*
`enum: [*current_note_ids, "none"]` must be `enum: [*candidate_note_ids, "none"]`, populated
from the 3–5 stage-1 survivors, not the whole note set. Add a stated cap (e.g. max 5 candidates)
so request size is bounded regardless of corpus size.

**A6. Add FR32: response ordering.** *(fixes RC-3)*
*"Each matching request carries a monotonically increasing sequence number. The overlay only
renders a result whose sequence number is greater than the last rendered result; superseded
in-flight requests are cancelled. A stale response never replaces a newer one."*

**A7. Add FR33: pipeline backpressure.** *(fixes RC-1, RC-2)*
*"The audio→STT queue is bounded (suggest 3 chunks). On overflow, the oldest unprocessed chunk
is dropped rather than queued, and the health indicator (FR35) shows a degraded state. The
transcript buffer retains a bounded rolling window (suggest the last 5 minutes), not the full
session."* Dropping audio is the correct trade here: a fresh match beats a complete transcript,
because the transcript is discarded anyway.

**A8. Specify the STT interface in §10 before Phase 2 begins.** *(fixes BC-4)*
Add a subsection defining, at minimum: `start()`, `feed(pcm_chunk)`, `stop()`; an event stream
distinguishing *interim* from *final* transcripts; explicit `error` and `reconnecting` states;
a backpressure signal; and cancellation. Write it against the **local** backend's constraints
first even though cloud is integrated first, so the interface is not shaped by the cloud
backend's conveniences.

**A9. Add note ID stability rules to FR2/FR3.** *(fixes BC-2)*
*"Note IDs are UUIDs assigned at creation, stable across edits and reorders, and never reused
after deletion."*

### P1 — Before packaging

**A10. Add FR34: embedding index versioning.** *(fixes BC-1)*
*"The notes index records the embedding model name and version. On mismatch at load, the app
transparently re-embeds all notes and reports it, rather than comparing incompatible vectors."*

**A11. Add FR35: a persistent session health indicator.** *(fixes OB-1, OB-2)*
A small always-visible element on the overlay showing pipeline state: `capturing` / `no audio
detected for Ns` / `STT degraded` / `matching offline (local-only)` / `falling behind`. Crucially,
it must **disambiguate "no match found" from "pipeline broken"** — the empty overlay must be
readable as intentional.

**A12. Add FR36: in-memory diagnostic ring buffer.** *(fixes OB-1)*
*"The app keeps a bounded in-memory ring buffer of structural events — timestamps, component
states, latencies, error codes, match/no-match decisions, but never transcript or note content.
The user can view it during or after a session and explicitly export it for troubleshooting.
It is never written to disk automatically."* This gives diagnosability without breaching §4.

**A13. Add FR37: degradation switches.** *(fixes OB-3)*
Mid-session toggles for: LLM matching on/off (falls back to local embedding-only), cloud STT
on/off, progress tracker on/off. Each independently switchable while a session is running.

**A14. Add FR38: pre-session readiness check, run automatically.** *(fixes OB-5)*
Validates audio device, notes loaded, backend reachable, API key valid, Windows build ≥19041,
and that `SetWindowDisplayAffinity` actually returned success. Blocks session start on hard
failures, warns on soft ones.

**A15. Amend FR14 with explicit failure behavior.** *(fixes RC-7)*
*"If `SetWindowDisplayAffinity` returns failure, the app displays a prominent persistent
warning that the overlay is NOT excluded from screen capture. It never silently assumes
exclusion succeeded."*

**A16. Add FR39: audio device change handling.** *(fixes RB-2)*
*"On default-output-device change or device loss mid-session, the app re-binds to the new
default automatically, notifies the user, and does not end the session."* Headphone
connect/disconnect during a call is routine, not an edge case.

**A17. Add §13 "Recovery & Degradation Ladder" to the document.** *(fixes RB-1, RB-2, RB-3)*
Define, per component, what happens on failure — see the table in §4 below. Also state the
app-version rollback policy: semantic versioning in the exe, notes/settings schema version
checked on load, older builds refuse rather than mangle newer data, and the export from FR30
is the supported downgrade path.

**A18. Add FR40: rate limiting and cost control.** *(fixes RC-5)*
*"Matching calls are debounced (no more than one in flight per N seconds), retried at most
once with backoff on 429/5xx, and the app enforces a per-session call ceiling. On sustained
rate-limiting it degrades to local-only matching and signals via FR35."* Also state the
stage-1 floor threshold's initial value and that it is tuned in Phase 4 against real
transcripts.

**A19. Add a first-run consent and legal disclosure.** *(fixes §2.6)*
Unavoidable on first run, covering: recording/interception laws vary by jurisdiction and may
require all-party consent; many employers prohibit capture during interviews; the user is
responsible for compliance. Not buried in settings, not a checkbox in an EULA wall.

**A20. Amend §12 to add the risks it currently omits.**
Add: notes durability (DI-1); embedding version drift (BC-1); local STT falling behind under
sustained load (RC-1); acoustic echo defeating loopback-vs-mic separation (RC-8); legal
exposure (§2.6).

### P2 — Worth considering

- **A21.** Reconsider whether the LLM call earns its place. §12 already raises this. Given that
  stage 1 is a local embedding search over the user's own few-thousand-word corpus, and stage 2
  can only pick from 3–5 pre-filtered candidates, the marginal quality gain may be small
  relative to what it costs: a hard internet dependency, per-utterance latency, an external data
  egress path, rate-limit exposure, and the fallback contradiction in A4. Recommend Phase 4
  explicitly measure stage-1-only accuracy against stage-1+2 on real transcripts before
  committing to the LLM as the default.
- **A22.** Phase 5 should include a "reset overlay position" control for the off-screen case (RC-9).
- **A23.** Consider making the progress tracker (FR12) require headphones, or detect echo, before
  trusting mic-vs-loopback separation (RC-8).

---

## 4. Recovery & Degradation Ladder (proposed §13 content)

| Failure | Detection | Automatic response | User-visible signal |
|---|---|---|---|
| Cloud STT connection drop | WebSocket close/timeout | Fall back to local `faster-whisper`, resume streaming | Notice + health state `local STT (fallback)` |
| Local STT worker crash | Process/thread exit, watchdog | Restart worker once; if it fails again, stop STT and hold session open | `STT unavailable` — never silent |
| STT falling behind (RC-1) | Queue depth > bound | Drop oldest chunks | `falling behind` |
| Default audio device changed | Device-notification callback | Re-bind to new default, continue session | Brief notice |
| Audio device lost entirely | Capture read error | Retry bind for 10s, then pause session | `audio lost` — prominent |
| LLM call timeout/error | Request exception | Retry once; then degraded stage-1-only match per A4 | Degraded-match styling + `matching: local-only` |
| LLM rate limited (429) | HTTP status | Backoff; on sustained, switch to local-only for the session | `matching: local-only` |
| Overlay hang | UI watchdog heartbeat | Recreate overlay window, restore persisted geometry | Brief notice |
| Capture-exclusion API failure | `SetWindowDisplayAffinity` returns false | None possible | **Prominent persistent warning** (A15) |
| Notes store corrupt on load | Schema/parse failure | Offer restore from rotated backup (FR29) | Explicit prompt, never silent |
| Machine sleep / lock mid-session | Power/session notification | Pause capture, purge nothing, resume on unlock | State shown on resume |

---

## 5. Go / No-Go Deployment Checklist

Since there is no fleet deployment, "deployment" here means: **shipping a build the user will
rely on during a real interview.** Two gates.

### Gate 1 — Build acceptance (before the exe is trusted for any live use)

**Data integrity**
- [ ] Kill the process (`taskkill /F`) during a notes save, 10 consecutive times; notes load
      intact every time (FR28).
- [ ] Delete a note, restore it from rotated backup (FR29).
- [ ] Export a note set, wipe the store, re-import; content and tags round-trip exactly (FR30).
- [ ] Confirm panic-clear leaves notes and settings fully intact (A2).
- [ ] Load a notes store with a bumped `schema_version`; app refuses cleanly rather than
      parsing (FR31).

**Privacy guarantees**
- [ ] Process Monitor trace across a full 45-minute simulated session; the only writes by this
      process are to the settings and notes paths (OB-4 / A3).
- [ ] Verify Windows Error Reporting dumps are disabled for the process (A3).
- [ ] Confirm `SetWindowDisplayAffinity` returns success, then verify the overlay is absent in
      a real Zoom/Teams/Meet share of both full screen and single window (FR14).
- [ ] Verify the failure path: force the exclusion call to fail; confirm the prominent warning
      appears (A15).
- [ ] Confirm the egress indicator (FR20) is visible whenever cloud STT **or** LLM matching is
      active, and distinguishable from the capture indicator.
- [ ] Confirm the API key is in Credential Manager and appears in no config file, log, or
      diagnostic export (FR19).

**Correctness & races**
- [ ] Force out-of-order LLM responses (inject artificial latency); confirm no stale snippet
      ever renders (FR32 / RC-3).
- [ ] Trigger panic-clear with an in-flight LLM call and an open STT socket; confirm both are
      cancelled and no post-clear render occurs (A2 / RC-4).
- [ ] Saturate the STT queue; confirm bounded memory, oldest-drop behavior, and the
      `falling behind` state (FR33 / RC-1).
- [ ] Run a 60-minute continuous session; memory is flat, not monotonically rising (RC-2).
- [ ] Confirm the LLM enum contains only prefiltered candidates, not the full note set (A5).
- [ ] Edit and reorder notes; confirm IDs are stable and matches still resolve correctly (A9).
- [ ] Change the embedding model version; confirm automatic re-embed rather than silent
      degradation (FR34 / BC-1).

**Resilience**
- [ ] Disconnect network mid-session: confirm STT fallback (FR21) and matching degradation
      (A4), both signalled.
- [ ] Connect/disconnect headphones mid-session: session survives, re-binds (FR39).
- [ ] Kill the STT worker mid-session: restarts or reports; never silently unassisted (US-C3).
- [ ] Simulate 429 from the Anthropic API: backoff, then local-only, signalled (FR40).
- [ ] Sleep/lock/unlock the machine mid-session: defined behavior, no crash.
- [ ] Undock from an external monitor between sessions: overlay is still reachable; reset
      control works (A22 / RC-9).

**Observability**
- [ ] Confirm "no match" and "pipeline broken" are visually distinguishable (FR35 / OB-1).
- [ ] Confirm the diagnostic ring buffer contains no transcript or note content (FR36).
- [ ] Confirm each degradation switch works mid-session (FR37).
- [ ] Confirm the readiness check runs automatically at session start and blocks on hard
      failures (FR38).

**Latency (the plan's own open question)**
- [ ] Measure end-to-end speech→overlay latency on the actual target laptop, local backend,
      p50 and p95. If p95 exceeds ~3s, the local default is not viable and §10a's cloud
      recommendation becomes the default rather than the upgrade.

### Gate 2 — Live-use readiness (before relying on it in a real interview)

- [ ] At least two full-length rehearsal sessions with a real person on a real video call,
      end-to-end, with real prep notes.
- [ ] Notes exported and backed up outside the app (FR30) — treat this as mandatory pre-flight,
      every time.
- [ ] First-run legal/consent disclosure reviewed and understood; jurisdiction and employer
      policy checked for the specific interview (A19).
- [ ] Fallback rehearsed: the user has practiced continuing the interview with the overlay
      showing nothing, so a mid-call failure is a non-event rather than a disruption.
- [ ] Confirm the plan is to **glance**, not read — a tool that pulls attention off the
      conversation for 4 seconds costs more than the recall it restores.

---

## 6. Closing Assessment

The architecture is sound and the guardrails are the right guardrails. The defects are
almost entirely of one kind: **guarantees stated at a strength the implementation cannot
deliver, with no defined behavior when they fail.** No-persistence, retrieval-only, capture
exclusion, and auto-fallback are each promised absolutely and each has an unhandled failure
path where the user is told nothing.

For a product whose entire value rests on being trustworthy in a high-stakes, unrepeatable
moment, that pattern is the risk. Fixing it is mostly a matter of writing down what happens
when things break — the P0 amendments in §3 are additive to the plan, not a redesign of it.

The one substantive design question worth reopening before Phase 4 is A21: whether the LLM
call earns the hard internet dependency, given how much work the local prefilter is already
doing over a small, user-authored corpus.
