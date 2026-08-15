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
| **M2 — STT interface & local backend** | 🟢 T2.1–T2.3 complete | Interface, local backend, assembler. T2.4 is the **AS-1 latency gate** and genuinely needs the target laptop. T2.2's model adapter is unverified (**AS-9**) |
| **M3 — Notes store & indexing** | 🟢 Logic complete | T3.1–T3.6 done. T3.7–T3.9 are Qt UI, deferred to Windows |
| **M4 — Matching pipeline** | 🟢 T4.1–T4.6 complete | T4.7 **blocked**: needs the user's labelled fixtures |
| **M5 — Overlay UI** | ⛔ Blocked | Qt + `SetWindowDisplayAffinity`; needs Windows. Fully specified (design §9b) |
| **M6 — Session lifecycle** | 🟢 Logic complete · panic on hold (D-U11) | T6.1–T6.3, T6.5 classification, T6.6 backpressure, T6.7 done. T6.4 and the OS trigger paths need Windows |
| **M7 — Progress tracker** | 🟢 T7.1 + T7.3 complete | Marking and text-domain echo suppression done. T7.2 needs paired audio fixtures; T7.4 is Qt |
| **M8 — Cloud STT backends** | 🟢 T8.1–T8.5 complete | Deepgram, ElevenLabs, fallback, egress. Protocols unverified against a live endpoint (**AS-8**) |
| **M9 — Packaging & first run** | 🟡 T9.0–T9.2, T9.6 complete | Composition root, FR63 disclosure, config store, settings surface, **entry point**. T9.3 is **blocked on M1** (three of four steps are audio). T9.6a needs FR43; T9.4 is PyInstaller; T9.5 needs live vendor docs |
| **M10 — Typed context sources** | 🟢 T10.1–T10.6 + migration complete | Five kinds, per-kind caps and thresholds, schema v1→v2 migration. T10.7 is Qt |
| **M11 — Post-interview report** | 🟢 T11.1, T11.3–T11.9 complete | Record, evidence binding, encrypted store, retention, generation. T11.2's DPAPI binding and T11.10 need Windows |

**Next action: nothing substantial in M9 is buildable here.** T9.3 needs audio hardware, T9.6a
needs FR43's active-note-set selection *and* the Windows-only embedder and cipher, T9.4 cannot
cross-compile, T9.5 needs live vendor docs. The remaining Qt work is in **M5's overlay widget**
and **T7.4's checklist rendering** — both buildable offscreen, both previously mislabelled.

That sentence has been wrong five times, so treat it as a claim to re-test rather than a fact.
What is different this time is that T9.3's blocker was *verified* rather than assumed:
`pyaudiowpatch` has no Linux distribution at all, `/dev/snd` does not exist, and there is no sound
subsystem. Three independent confirmations, unlike the Qt claim which had none.

That last sentence was written three hours after the previous version of this paragraph said
T9.4 was "the only remaining task with no hardware dependency". It was wrong, for the **fifth**
time, and this instance was the most expensive: `pyproject.toml` listed PySide6 under a
`windows` extra with the comment *"Windows-only runtime. Cannot be installed or exercised on the
Linux dev box."* Both halves are false. PySide6 ships Linux wheels, and it runs under
`QT_QPA_PLATFORM=offscreen` — widgets, signals and slots, modal dialogs, event loops. The Qt
tests for T9.1 run headless in this container and on CI's Windows runner from the same command.

What that comment hid: **M5's overlay, T9.2, T9.3, T7.4 and T10.7 — five tasks across four
milestones**, every one of them previously filed under "needs the Windows machine". The genuinely
Windows-bound piece is `SetWindowDisplayAffinity` (T5.2), a single API call, plus the actual
device I/O. Not the toolkit.

The fourth instance, for the record, was T2.2, labelled "needs Windows" from M0 with no stated
reason; `faster-whisper` installs and imports on Linux, and ~700 lines of buildable work sat
behind that one word for five milestones.

Remaining, re-sorted after the Qt discovery:

- **Buildable and testable here (Qt, offscreen):** T7.4's checklist rendering, T10.7's per-kind
  marking, and the *widget* half of M5's overlay.
- **Genuinely needs Windows:** M1 (WASAPI, AS-2 gate), T2.4 (AS-1, needs the D-U6 laptop's CPU),
  T5.2's `SetWindowDisplayAffinity`, T6.4's ProcMon trace, T9.1a's device-open enforcement,
  T9.4's PyInstaller build, T11.2's DPAPI binding, T11.10.
- **Needs the user's fixtures:** T4.7 (the OQ-1 gate), T7.2 (paired audio).
- **Needs a vendor key:** AS-8, T9.5.

The previous version of this line said nothing further was buildable on Linux. That was true of
the *then-known* scope and is now moot — but note it had already been wrong twice on its own terms
before new scope arrived. Treat any such claim here as one to re-test.
The remaining work splits cleanly:

- **Needs the Windows machine:** M1 (AS-2 gate), T2.4 (AS-1 gate — needs the D-U6 laptop's CPU,
  not merely Windows), T5.2's `SetWindowDisplayAffinity`, T6.4's ProcMon trace and M6's OS trigger
  paths, T9.1a, T9.4's PyInstaller build, T11.10's report view, and T11.2's DPAPI binding (its
  envelope and listing logic are testable here behind a Protocol). **Qt widgets are not on this
  list any more** — see the note above.
- **Needs the user's fixtures:** T4.7 (the OQ-1 gate) and T7.2 (paired headphone/speaker audio).
- **Needs a vendor key:** AS-8 — the two cloud protocols are implemented from documentation and
  have never met a live endpoint. Everything *around* them is tested; the wire format is not.

**A caution about this list, now with five instances.** An earlier version said "M7 tracker device
tests", and that blanket phrase hid two buildable tasks for a whole milestone. The very next
version said "M8–M9 — cloud backends, packaging, **both Windows**", which hid an entire milestone:
cloud STT is websockets and asyncio and has no Windows dependency whatsoever. The third was T2.2,
labelled "needs Windows" for five milestones because Whisper is *deployed* on Windows — a
statement about the product that says nothing about where the code can be written or tested.

The fourth was T2.2. The fifth was **Qt itself**, and it was the worst because it was written into
`pyproject.toml` as a dependency comment rather than into this file — so it was load-bearing for
five tasks across four milestones and was never re-read as a claim.

The pattern in all five: a true fact about the milestone's *hardware* was allowed to stand in for
a claim about its *code*. The two are unrelated, and only the second one blocks work. **The
check that would have caught every one of them is the same: try it.** Installing PySide6 and
running one dialog headless took four minutes.

Both errors were mine, both were written *into this file as a summary*, and both were then trusted
on the next read. When a milestone is marked blocked here, name the *task* and the *reason*, and
make the reason specific enough to be falsifiable — "Windows" is not; "needs
`SetWindowDisplayAffinity`" is.

---

## Environment split — read this first after any gap

Development happens in a **Linux container**; the product targets **Windows 11** (D-U4).
That split decides what can be verified where, and it is not a temporary inconvenience — it is
permanent for this project.

**Qt runs here.** `QT_QPA_PLATFORM=offscreen` gives PySide6 a platform plugin with no display
server; widgets, signals/slots, modal dialogs and event loops all work, and the same tests run
unchanged on CI's Windows runner. Install with `pip install -e ".[dev,ui]"`. The container needed
`libegl1 libgl1 libxkbcommon0 libdbus-1-3 libfontconfig1` from apt — that, not the wheel, was the
only real obstacle. `pyproject.toml` previously asserted the opposite; see the caution above.

**Buildable and verifiable on Linux:** notes model and store, atomic write and rotation, schema
guard, importer and chunking, embedding index (against a fake embedder), the STT interface and its
conformance suite, **the local Whisper backend's VAD, finalisation, timestamps and threading**
(behind a `Transcriber` Protocol), the utterance assembler (fed by WAV fixtures), matching
prefilter, sequence gate, dispatch policy, diagnostics, credentials logic, **and Qt widgets and
dialogs under `QT_QPA_PLATFORM=offscreen`**.

**Requires the Windows machine:** WASAPI capture (M1), `faster-whisper` timing *and the model
adapter itself* (T2.4/AS-1, AS-9),
`SetWindowDisplayAffinity` (T5.2), Credential Manager binding (the OS half of T0.5), the Process
Monitor privacy trace (T6.4), PyInstaller packaging (T9.4), and every `@pytest.mark.device` test.

**Python version:** the container has 3.11; the spec pins **3.12** for the Windows build. Two
settings look similar and mean different things — do not "align" them:

- **`ruff target-version = "py311"`** — the *floor*. Keeps the source runnable in the 3.11
  container, so nothing here silently adopts 3.12-only syntax.
- **`mypy python_version = "3.12"`** — the *target*. Type-checks against the version that ships.

**Blocked network egress.** The container's proxy denies `huggingface.co` (403 to CONNECT;
`curl -sS "$HTTPS_PROXY/__agentproxy/status"` lists the rejections). PyPI, npm and crates are
allowlisted; model hubs are not. So any component that needs a *downloaded model* — Whisper
weights, and `all-MiniLM-L6-v2` for real embedding runs — is verifiable only on the Windows
machine, regardless of whether its library installs here. This is why both have Protocol seams
with fake implementations, and it is the reason for AS-9.

An earlier version pinned mypy to 3.11 to match the container, which broke CI: numpy 2.5's own
stubs use `type` statements that a 3.11 parser cannot read, so mypy failed before checking any
project code. Analysing for an older version than your dependencies are written for is not a
conservative choice, just a broken one.

---

## Log

### T9.6 — Application entry point · complete · 2026-08-14

`interview_prep_recall/startup.py`, `interview_prep_recall/__main__.py`,
`interview_prep_recall/ui/main_window.py`, plus `tests/test_startup.py` (13) and
`tests/test_main_window.py` (13). 565 passing.

**T9.3 was the planned next phase and it is genuinely blocked.** Three of its four steps — device
selection, audio test, echo check — are audio, and this was *verified* rather than assumed:
`pyaudiowpatch` has **no Linux distribution at all** (`pip` reports "from versions: none"),
`/dev/snd` does not exist, and there is no `/proc/asound`. Three independent confirmations. That
matters because the last five "needs Windows" labels turned out to be false on inspection; this
one is not.

**So the phase became the thing three tasks were waiting on.** T9.1a ("no production caller"),
T9.2b ("no main window") and T9.4 ("needs an entry point") all record the same blocker in
different words, and **no task owned building it** — the third unowned prerequisite in this plan
after T9.0's composition root and T9.2a's config store. Recorded as **T9.6**.

**Closed by it:**

* **T9.2b.** Something in production now constructs `SettingsDialog`, feeds `on_switch` to
  `SessionManager.set_switch`, and passes the result to `Application.apply_settings`.
* **The startup half of T9.1a.** FR63's gate runs before anything is constructed. The capture-open
  enforcement still belongs to M1.
* **A D-20 instance I created last phase.** `ConfigLoadStatus.settings_were_lost` had **no
  production consumer** — I wrote in the config module's docstring that "the user is notified" was
  load-bearing, and then gave the notification nowhere to go. It now produces a startup notice.

**The order is the requirement, and one ordering is load-bearing.** Consent is checked *before*
`build_application` is called, and the test asserts the factory was never invoked and the
directory is still empty. A gate that runs after the composition root has created directories,
built an index and loaded notes is a gate that ran too late — "declined" would leave behind the
state of a session the user refused.

**Preflight now runs automatically (FR38), and on this machine it correctly blocks.** `Preflight`
treats a check with no probe as unsatisfied rather than passed, so with no audio devices the
window shows real blocking reasons instead of a fake Start button. That is the honest screen for
"you cannot start yet", and it is specified behaviour rather than scaffolding.

**T9.6a is deliberately unimplemented.** `_build_application` raises rather than guessing, because
two of its four dependencies need decisions that are not this task's to make: FR43's active
note-set selection (nothing reads or writes `QSettings` yet) and what an absent API key means
(D-U3's local-only path — a product decision belonging with T9.3). Inventing answers here would
ship them as decisions nobody made.

**Five defects found in the local two-pass review:**

1. **`python -m interview_prep_recall` crashed with a traceback.** Found by *running* it, not by
   reading it. An entry point's job is to start or say why it cannot; a stack trace is neither.
   Now caught, printed to stderr and shown, with a distinct exit code.
2. **`test_switch_names_are_accepted_by_the_session_manager` asserted nothing.** It toggled each
   checkbox and then asserted `hasattr(switches, name)` — trivially true, unrelated to whether the
   toggle landed, and named for a guarantee it did not check. Written minutes earlier, by me.
3. **Two more near-vacuous tests** restated library behaviour rather than checking this module.
   Deleted; one was replaced by real coverage of finding 1.
4. **`vars()` on a dataclass** where `asdict` states the intent and will not silently start
   offering a non-field attribute added later.
5. **`EXIT_OK` defined and never used.**

**PR #18 review round (Codex) — one finding, half fixable now.** FR38 says the readiness check
runs "at **session** start"; the entry point runs it at *process* start, and the report then goes
stale — switch to a cloud backend in Settings and the window still shows the original "ready"
without the API key or service ever being validated. The staleness half is fixed: applying
settings re-runs the checks, and `run_preflight` is now public because it has to be re-runnable
rather than run once. The other half — feeding `SessionManager.request_start()` /
`preflight_result()` — cannot be wired until something can start a session, which is M1. Recorded
as **T9.6b**.

**A constraint recorded for T9.4:** a failed startup shows a *modal* message box, which is correct
for a human and a hang for automation — verified by running the entry point headless, where it
blocked until timeout. Any non-interactive smoke test of the packaged exe must drive or suppress
it.

Finding 2 is the third time in three phases that a test I wrote asserted something weaker than its
name claimed. The pattern is specific enough to name: **when a test's assertion is a `hasattr`, a
truthiness check, or an equality against a value the code under test never touched, it is
measuring the test's own setup.**

---

### T9.2 + T9.2a — Settings surface and the `config.json` store · complete · 2026-08-14

`interview_prep_recall/config.py`, `interview_prep_recall/settings.py`,
`interview_prep_recall/ui/settings.py`, plus `tests/test_config.py` (40),
`tests/test_settings.py` (20) and composition-root tests in `test_app.py`. 530 passing.

**A missing prerequisite, and it was the T9.0 shape again.** T9.2's acceptance criterion is
"sensitivity, thresholds, model ID, backend choice all editable **and persisted**", and design §4
specifies `config.json` down to its migration semantics — but **no task owned building it**. The
plan named a dependency and never gave it an ID, so nothing owned it and the work was invisible
in the task list. Recorded as **T9.2a** rather than folded silently into T9.2. This is now the
second time this exact gap has appeared (T9.0 was the first), which suggests reading acceptance
criteria for *nouns that must already exist* is worth doing as a habit.

**Config recovers where notes refuse, and the difference is deliberate.** `NotesStore` refuses to
parse a newer schema because notes are irreplaceable. Design §4 says the opposite for config: a
missing, unparseable or newer-versioned file is replaced with defaults, because a slider position
can be re-set and refusing to launch cannot be undone by the user. The two stores now sit side by
side doing opposite things, and both docstrings say why.

**"And the user is notified" is in the API, not in a log line.** `load()` returns
`(AppConfig, ConfigLoadStatus)` and the caller cannot get one without the other, with
`settings_were_lost` distinguishing a first run from an actual loss. A silent reset is the failure
that really happens: sensitivity reverts, the user does not notice, and they conclude the matching
is broken.

**τ_degraded is deliberately absent from the schema.** Design §7 makes it `max(0.55, τ_floor +
0.10)` and explains at length why it must be derived — a fixed 0.55 falls below τ_floor once the
user raises sensitivity past it, making the degraded gate unconditional and silently restoring the
behaviour D-U3 exists to overturn. Persisting it as a field would hand that bug straight back, so
a test asserts it is *not* a config field.

**Persisted settings and FR37 switches are kept apart on purpose.** τ_floor, τ_track, model ids,
backend and retention go to `config.json`. The three degradation switches are mid-session controls
that fire on toggle and persist nowhere — a user who killed cloud STT during one bad network
moment must not find it still off next week having forgotten. The dialog has two output channels
for that reason.

**What applies live is stated, not discovered.** `SettingsApplier.apply` returns both what took
effect and what needs a restart. `embed_model_id` cannot apply live (every cached vector came from
the old model) and neither can `stt_backend` (the streams are already open). Reporting those as
applied would be the recurring defect here — a guarantee whose test passes while the property is
false.

**Four defects found in the local two-pass review, all with negative controls:**

1. **`apply_settings` assigned `self.config` before saving.** A failed write left three different
   answers to "what are the current settings" — new value in memory, old value on disk, old value
   in the components — and the next call would diff against a `previous` that had never been real.
   Worse, the docstring already claimed it saved first. Save now happens before anything moves.
2. **`load()` promised never to raise but only caught `ConfigError` around migrations.** A
   migration failing on a `KeyError` — ordinary code failing in an ordinary way — meant refusing
   to launch over a settings file, exactly the trade design §4 rejects.
3. **`stt_backend` was the one field with no validation.** `SettingsDialog.config()` reads
   `QComboBox.currentData()`, which is `None` at index -1, producing an `AppConfig` that validated
   cleanly and then crashed in `to_dict()` on `.value`.
4. **The dialog was written as `ui/settings_dialog.py` beside the `ui/settings.py` stub.** Design
   §1 names `ui/settings.py` and T0.1 requires the tree to match it. Moved; the stub is gone.

**A caution about negative controls, since this file relies on them heavily.** Reverting fix 1 for
its negative control swapped two lines of *identical total length* within the same second, which
left a stale `.pyc` that Python happily reused — the restored fix appeared to still be broken for
several minutes. `find . -name __pycache__ -exec rm -rf {} +` before re-running is now part of the
technique. A negative control that lies is worse than none.

**PR #17 review round (Codex) — three findings, all real:**

1. **A pending restart was reported once and then forgotten.** `apply` diffed against the last
   *persisted* config, so changing `embed_model_id` reported a restart — and then any unrelated
   save compared the field to its new persisted value, found them equal, and reported
   `restart_required` false while the running index still held the old model. Reverting the field
   before restarting had the mirror-image bug, demanding a restart that was not needed. Fixed by
   giving `SettingsApplier` a `running` config — what the components actually hold — and writing
   back to it *only* for fields that genuinely reached a component.
2. **`applied` was reported for a change whose target was absent.** The module docstring said
   "without pretending it applied anything it could not reach"; the code did exactly that, and a
   test named `test_applier_tolerates_absent_targets` asserted the buggy behaviour. Test and
   docstring disagreed and the test won, which made `applied` mean "changed" and useless to a
   caller deciding whether to tell the user the change took effect. `AppliedSettings` now has a
   third outcome, `persisted_only`.
3. **`float()` overflowed on a large JSON integer.** JSON has no integer bound, so a hand-edited
   `999…9` parses to a Python int that `float()` cannot represent — and `from_dict` runs *outside*
   `load`'s recovery block, so this raised out of `Application.__post_init__`. The app refused to
   start over a config value, which is the exact promise this module makes and breaks. Fixed with
   NaN and infinity handled at the same time, NaN being the dangerous one: it fails every
   comparison, so a clamp returns it unchanged and it then passes the range check by failing both
   halves of it.

Finding 2 deserves the same note T9.1's finding 3 got. My local two-pass review had already run
over this file and passed it, because the docstring asserted the correct behaviour and I read the
docstring. The test that would have caught it was the one asserting the bug, written by me in the
same sitting. **A test and a docstring that disagree are a defect regardless of which is right,
and neither reviews the other.**

**Deferred as T9.2b:** nothing in production constructs `SettingsDialog`. The pieces exist and are
tested, but there is no main window to open them from — the same gap as T9.1a, and the same one
that will close when T9.3 lands an entry point. Recorded as a task rather than as silence.

**Also noted:** `Application.retention_days` is now a deprecated override of
`config.retention_days`, kept so existing callers keep working. Two sources of truth for one
setting is how they drift; it should go once callers move.

---

### T9.1 — First-run consent disclosure (FR63) · complete · 2026-08-14

`interview_prep_recall/first_run.py`, `interview_prep_recall/ui/consent_dialog.py`,
`tests/test_first_run.py` (15), `tests/test_consent_dialog.py` (16), plus composition-root wiring
and three tests in `test_app.py`. 461 passing.

**The headline is not the dialog — it is that Qt was never blocked.** `pyproject.toml` listed
PySide6 under a `windows` extra with the comment *"Windows-only runtime. Cannot be installed or
exercised on the Linux dev box."* Both halves are false, and the claim had gone unexamined since
M0 while five tasks across four milestones (M5's overlay, T9.2, T9.3, T7.4, T10.7) were filed as
Windows-blocked on the strength of it. Verifying it took four minutes: `pip install PySide6`,
five apt packages for EGL/xkb, and one dialog under `QT_QPA_PLATFORM=offscreen`. **Fifth instance
of the blanket-label error**, and the first one recorded in a dependency comment rather than in
this file, which is why nobody re-read it as a claim.

**Policy and widget are separate modules, and the split is the design.** "Unavoidable" is a
property of a policy, not of a widget: a dialog can be modal, frameless and un-closable and still
fail FR63 if the caller treats a dismissal as agreement. So `require_consent(consent, present)`
has no Qt import and takes an injected presenter, and the dialog is tested independently for the
one thing only it can guarantee — that nothing except tick-then-press produces an
acknowledgement.

**What Qt gives you for free, and why all of it is closed off.** `QDialog` routes Esc, the
title-bar X, `close()` and a programmatic `reject()` to the same `Rejected` code, and `Rejected`
is falsy in a way that reads as "the user declined" only if someone checked. Every implicit route
is neutralised rather than mapped to decline: a legal notice dismissed by a reflexive Esc should
still be on screen when the user looks back, because the alternative is an app that quits without
explanation minutes before an interview. `accept()` is guarded too, since it is public on
`QDialog` and reachable from any future signal wiring. All four guards have negative controls.

**Versioned, like `ReportConsent`.** A bare boolean is what made FR85 impossible to express, and
legal text does get edited. `required` compares with `!=`, not `<`: a record from a *newer*
version — a downgraded install, a copied profile — was given against text this build cannot
display.

**Found in the local review and fixed:** two tests named `test_present_disclosure_*` never called
`present_disclosure`. They built their own presenters and merely imported the real one, with an
`__all__` line in the test module laundering the unused import. The production seam — the
function the app actually wires — had zero coverage while two tests asserted its contract by
name. Now driven for real through `QTimer.singleShot` into the modal event loop, with a negative
control confirming the decline path fails when the return value is forced to True.

**PR #16 review round (Codex) — one finding, real, and it was also live in merged code:**

`{"first_run_disclosure_version": true}` satisfied the gate. `bool` subclasses `int`, so `True`
passes `isinstance(version, int)` **and** compares equal to version 1 — a malformed consent file
failing **open**, skipping the legal disclosure entirely, in the module whose entire purpose is
to fail closed. Fixed with an explicit bool rejection.

The same line existed in `report/consent.py`, merged since M11, with the same bypass against
FR85's re-acknowledgement — so the fix went to both. That module also lacked a non-dict guard:
`json.loads("[]")` returns a list and `.get` on it raises `AttributeError`, which its `except`
clause does not catch, so a malformed file crashed instead of failing closed. Both now covered by
parametrised tests, with a negative control confirming the boolean case fails without the fix.

Worth noting how it got in: the guard was copied from `ReportConsent` on the reasoning that the
pattern was already reviewed and merged. It was — and it was already wrong. Copying a defect
across modules is how one bug becomes two, and reviewing the copy on its own terms is what would
have caught it.

**Deferred, deliberately, and split out as T9.1a:** the gate has no *enforcement* point. FR63
gates capture, and capture is M1 (blocked on the Windows machine), so the call that refuses to
open a device on DECLINED cannot be written against anything real. Guarding `Application.consume`
instead was considered and rejected: by the time an utterance exists, the audio has already been
captured — it would look like enforcement at the wrong layer, which is this project's defect
class exactly. The gate is constructed and exercised in the composition root so it is not
unwired glue (D-20, five instances), and the missing half is a task rather than a silence.

**Also deferred:** `closeEvent` refuses unconditionally, which may block an OS-initiated session
end (`WM_QUERYENDSESSION`). Evaluating that needs real Windows shutdown behaviour. Recorded as a
follow-up on T9.1a rather than guessed at.

---

### T2.2 — Local Whisper backend · complete · 2026-08-14

`interview_prep_recall/stt/local_whisper.py` (+ `tests/test_local_whisper.py`, 21 tests). M2 is
now green except T2.4, which is a latency measurement on specific hardware rather than code.

**This task was labelled "needs Windows" from M0 and that was wrong.** No reason was ever
recorded for it; `faster-whisper` installs and imports on Linux. See the caution at the top of
this file — third instance, same shape each time.

**The blocking issue, documented rather than worked around (AS-9).** The container's network
policy denies `huggingface.co` — the agent proxy answers 403 to CONNECT, confirmed via
`$HTTPS_PROXY/__agentproxy/status`, which lists the rejection explicitly. No model file can be
downloaded here, so `FasterWhisperTranscriber` has never run. Per the standing instruction, that
is recorded as an assumption and not invented around: **AS-9**, alongside AS-8's unverified cloud
wire protocols. It is verified on the Windows machine during T2.4, which loads a real model anyway.

**What that forced, and why it was an improvement.** Inference sits behind a `Transcriber`
Protocol — the same shape as `Cipher`, `Embedder`, `Connector` and `MessagesClient`. The real
adapter is ~20 unverified lines; everything the backend is genuinely responsible for is on the
tested side of the boundary. AS-9's blast radius is that 20 lines, not the milestone.

**How FR47 is synthesised.** Whisper has no final marker, so an energy VAD watches the frame
stream and a span closes at ≥700 ms silence or 10 s max span (design §2). Three decisions in that
mechanism are load-bearing:

- **"Acknowledged" means the VAD opened a span.** Silence that never opens one owes no event —
  otherwise every quiet second of an interview would carry a finalisation obligation.
- **An empty transcription still emits its final.** The VAD opens on coughs; Whisper returns "".
  Dropping that event leaves rule 2's tests green (every *other* span finalises) while a span the
  backend acknowledged vanishes. `UtteranceAssembler` discards it downstream, where dropping text
  is a declared job rather than a silent one.
- **`t_end` excludes the trailing silence.** The 700 ms hang is fed to the model (clipping a
  word's decay hurts accuracy) but must not reach the event, because the assembler measures
  inter-utterance gaps from `t_end` and padding every span by the full budget would consume the
  gap that closes utterances.

**Two defects found in the local two-pass review, both with negative controls:**

1. **`start()` did not reset `_last_emitted_start`.** `FallbackSttBackend` restarts a backend
   mid-interview, and the new session's capture clock need not resume above the old one's last
   timestamp — so the rule-4 ordering guard would reject every event of the second session. READY,
   no errors, permanently silent. This is `CaptureClock.reset`'s bug (D-25) in the other backend,
   which is why it was worth looking for. All per-session state now resets in `start()`.
2. **Span duration was measured from `len(audio)`, which `MAX_SPAN_BYTES` caps.** A `max_span_s`
   above the byte ceiling freezes the measured duration below its own threshold and the forced cut
   never fires again — a memory-safety cap silently switching off FR47's monologue guarantee.
   Duration is now counted in frames, which the cap cannot touch.

Both were reverted and the new tests re-run to confirm they fail against the pre-fix code. Given
this project's history, a regression test that has never been seen to fail is not evidence.

**PR #15 review round (Codex) — four findings, all real, all fixed with negative controls:**

1. **P1 — default model was `small.en`, spec says `base.en`.** Design's "Pinned versions" makes
   `base.en` the default and `small.en` an upgrade *conditional on T2.4 showing headroom*.
   Shipping the larger model would have meant AS-1's recorded latency described a model nobody
   runs — on the no-key default path, which is what almost everyone runs. Now `MODEL_SIZE_DEFAULT`,
   with the conditionality written next to it.
2. **P1 — a timed-out worker could be handed the next session.** `stop()` can return while a
   worker is inside an inference pass; it shared the stop flag, queue, callbacks and ordering
   high-water mark with the backend, so restarting gave the stalled worker the new interview: the
   previous session's transcript emitted under the new `stream_id`, the ordering mark pushed past
   every real event, two workers racing one queue. **Fixed structurally**: all per-interview state
   moved into a `_Session` object that `start()` replaces wholesale. This also subsumes the
   `_last_emitted_start` bug found in the local review — a fresh object cannot forget a field.
3. **P2 — `start()` discarded the injected VAD.** My own local-review fix introduced this:
   rebuilding the detector per session is right (its noise floor is tuned to one room), but doing
   it by constructing `EnergyVad()` inside `start()` meant a caller's tuned detector — or the
   documented Silero replacement — never had `is_speech` called. **D-26's defect, reintroduced by
   the fix for a different bug.** Now a `vad_factory` with a `SpeechDetector` Protocol.
4. **P2 — onset frames were discarded.** With `ONSET_FRAMES = 2`, the first speech frame only
   incremented a counter and the span opened from the second, so every utterance lost its leading
   20 ms — the initial phoneme, where Whisper has least context — and reported `t_start` late by
   the same amount, which then propagated into the assembler's gap arithmetic. The provisional
   frames are now held and prepended.

Finding 3 is worth dwelling on: it was created by a fix, in the same session, for a bug of the
same family. A review pass over one's own changes is not a substitute for a second reader.

**Deliberate non-reuse.** `CloudSttBackend` was not factored into a shared base. The overlap is
"bounded deque plus a worker thread"; the differences are a socket, reconnection and an asyncio
loop. Lifting a base out of that would couple the default path to the opt-in one for no gain.

**`audioop` was the obvious tool for RMS and is the wrong one** — deprecated in 3.12 (and
`filterwarnings = ["error::DeprecationWarning"]` turns that into a test failure) and removed in
3.13. numpy is already a core dependency, and the RMS accumulates in float64 because squaring
int16 in its own dtype wraps to a small wrong number — which reads as silence during the loudest
speech.

**Known weakness, recorded not hidden.** `EnergyVad` is energy-only: it cannot distinguish speech
from a fan, a keyboard, or notification chimes on the loopback stream. It is here because it needs
no download and is deterministic under test, which is what lets FR47 be *verified*. The upgrade
path is `silero-vad`, already listed in design §10 and bundled with `faster-whisper`; it is a
change to one class, since the backend asks a detector only for `is_speech(frame)`.

---

### T9.0 — Headless composition root · complete · 2026-08-11

**The plan named "the composition root" as the blocker for two follow-ups but never gave it a
task**, so nothing owned it and it read as unbuildable. Added as T9.0 in `03-tasks.md` before
implementing, rather than quietly widening scope.

**Delivered** — 24 new tests, 401 total. `ruff`, `ruff format` clean; `mypy` clean on both the
local platform and `--platform win32`.

`app.py` constructs and wires every component. No Qt: the UI will build *on* an `Application`
rather than contain one, which is what makes the wiring testable on a machine that cannot run the
UI at all. Every test in `test_app.py` is about a **connection**, not a component — the three
defects this closes were all cases where two correct pieces were not joined, which no
component-level test could see.

| Guarantee | Was |
|---|---|
| **One switch, every cloud consumer** (D-23) | `llm_matching` reached the pipeline only. M11 added report generation and nothing connected it — the indicator would read local-only while the whole transcript still went to the API |
| **Finalised utterances reach the record** (FR74) | The record shipped with no producer |
| **Coverage has one adjudicator** (FR78a) | The tracker's verdict had no route to report generation |

**`CloudSwitchFanout` rather than a wider Protocol.** `attach_matching` takes one target because
the pipeline was the only API consumer when the switch was written; the shape had no way to express
a second. The fan-out refuses registration of anything without `set_local_only`, and refuses to
flip with no consumers registered — because a switch that reports success having switched nothing
is precisely D-23.

**The record is fed before routing**, deliberately. The router splits by purpose (matching sees the
interviewer, the tracker the mic), so recording downstream of it captures half the conversation
while the report claims to cover the meeting.

**The transcript is stored before generation is attempted.** A declined, offline or rate-limited
generation must not cost the user the interview.

**Review round — three confirmed issues, all fixed before push**

| # | Issue | Fix |
|---|---|---|
| 1 | **Three of five purge hooks are unwired**, and `PurgeHooks` defaults them to no-ops that report success — so a purge claims audio was cleared. Vacuously true with no capture; a **false statement** the moment M1 lands without revisiting the wiring. | `wired_purge_hooks()` names the current set and a test pins it, so M1 gets a failing test instead of relying on memory. |
| 2 | **`Application.start_session` collided with `SessionManager.start_session`**, doing something entirely different and not transitioning the state machine. | Renamed `reset_for_new_session`. |
| 3 | `CloudSwitchFanout.targets` was `list[object]` with a `type: ignore`. | `LocalOnlyTarget` Protocol; suppression gone. |

**PR #14 review round — three findings, all valid, all fixed.**

| Severity | Finding | Why it mattered |
|---|---|---|
| P1 | **Ending a session destroyed the transcript before anything could store it.** `drop_transcript` is wired to `record.clear`, and there was no application-level stop path — so `SessionManager.end_session()` purged the record, and the report call that followed saved an empty transcript and raised "Nothing was recorded". Ending an interview lost the report **and** the persisted record D-U8 traded the no-disk guarantee for. | `Application.end_session(role=...)` stores first, then purges. **My own test enshrined the bug**: it drove `SessionManager.end_session()` directly, asserted the record was cleared, and called that correct — which it is, in isolation. The missing thing was a caller, and a test of the callee cannot see that. |
| P1 | **Stage 2 ran inline on the consuming thread.** No `runner` means `InlineRunner`, so the model request executes inside `consume()` — blocking span routing for the 5 s timeout plus a retry, during which later finalised spans are neither recorded nor queued. The one-in-flight/one-pending policy exists so calls can overlap arrivals; inline makes it unreachable. | `BackgroundCallRunner`, one worker (the pipeline already permits one call in flight, so more threads could only add concurrency the design forbids). |
| P2 | **The `progress_tracker` switch changed a field and nothing else.** `consume()` kept feeding the tracker, so the checklist went on marking while the switch reported tracking as off. | Read live on every call. D-23's shape a third time, in the one place the user can watch it be wrong. |

**Regeneration forced a real design correction.** D-U8's stated purpose is that reports can be
regenerated later — but a week later there is no live record *and no live tracker*, and FR78a makes
the tracker's verdict the only valid basis for an absence finding. So `missed_note_ids` is now
stored **with** the transcript, and `generate_report(session_id=...)` rehydrates both. Deriving
coverage from a reset tracker would have reported every point as uncovered, confidently.

**Deferred:** `sweep_retention()` has no production caller and deliberately is not called from
`__post_init__` — constructing an `Application` must not delete stored interviews as a side effect.
The entry point owns it, and there is no entry point until the UI. Recorded rather than left to be
noticed, since a documented-but-uncalled method is this codebase's most repeated defect (D-20).

**A test-assertion trap worth recording.** Two D-23 tests originally asserted `client.requests == []`
to prove nothing was sent. The composition root shares one model client between matching and report
generation, and stage 2 fires during `consume()` — correctly. Both tests were passing on the raise
while their central assertion was wrong for the wrong reason. They now filter on the report tool.

**And the sys.path rule was broken in the milestone right after it was written.** `tests/helpers.py`
was first imported as `tests.helpers`, which CI's `pytest` console script cannot resolve. The
`PYTHONSAFEPATH=1` pre-push check caught it locally — which is the entire reason that check exists.

---

### M11 — Post-interview report · T11.1, T11.3–T11.9 complete · 2026-08-10

**Delivered** — 52 new tests, 377 total. `ruff`, `ruff format`, `mypy` clean.

| Task | What exists |
|---|---|
| T11.1 | `report/record.py` — ordered, bounded, finals-only `SessionRecord` |
| T11.2 | `report/store.py` — encrypted store, listing, deletion; `platform/win_dpapi.py` for the binding |
| T11.3 | Retention sweep, 30-day default, `None` means never |
| T11.4 | `report/generator.py` — four sections plus both summaries, absent sources declared |
| T11.5 | `report/evidence.py` — presence and absence evidence, verified before display |
| T11.6 | `report/separation.py` — static import guard, FR79 |
| T11.7 | Per-run confirmation with payload size; egress lit across the call |
| T11.8 | `report/consent.py` — versioned re-acknowledgement, FR85 |
| T11.9 | `delete_all()` — the only route to destroying history under D-U11 |

**The record is the only structure allowed to grow with session length.** FR33 forbids that
everywhere else, so FR76 makes the exception explicit and FR75 bounds it at 4 hours or 5,000
utterances. **Truncation stops recording rather than dropping the oldest** — dropping oldest would
silently lose the opening while the report claimed to cover the whole meeting. Both are bad; only
one is visible, and the report states it.

**Evidence is what makes this feature trustworthy at all.** The overlay cannot fabricate because it
cannot generate. The report must generate, so every finding is anchored: presence cites utterance
indices that must all resolve, absence cites a source chunk. `test_an_invented_index_is_rejected`
uses `(0, 99)` deliberately — one fabricated index inside real ones is the shape a
plausible-but-wrong citation actually takes, so partial validation would miss it.

**FR78a gives coverage a single adjudicator.** The prompt is *told* which points the tracker
recorded as uncovered, rather than being asked to work it out. A model that re-derives coverage
produces a second opinion the verifier then rejects wholesale — and if it slipped through, the user
would hold a report contradicting the checklist they watched during the interview, with no
principled way to choose.

**Rejected findings are counted and surfaced, never silently dropped.** A report that quietly
discarded a third of the model's output would read as complete while being nothing of the sort.

**No cipher fallback off Windows.** `default_cipher()` raises rather than degrading. Storing an
interview transcript under weaker protection than FR82 promises would be a false privacy statement
about a third party's words — the exact class of defect this project keeps digging out of its own
tests, aimed at a person instead of a buffer.

**Review round — four confirmed issues, all fixed before push**

| # | Issue | Why it mattered |
|---|---|---|
| 1 | **`ReportConsent` had zero call sites.** | Fourth instance of D-20 in this codebase. Consent is now **required** by `ReportGenerator` — no `None` default — and checked at generation, the moment the interviewer's words actually leave the device. Checking only in a UI that does not exist yet is precisely D-23, where the local-only switch lit an indicator while the pipeline kept calling the API. |
| 2 | **`purge_root()` had zero call sites**, with a docstring claiming the UI used it. | Same shape, no redeeming enforcement value. Deleted rather than kept "for later". |
| 3 | **`delete_all()` was O(n²) decryptions.** Each `delete()` reindexed, and reindexing decrypts every remaining transcript. | On the one operation a user runs when they want their data gone quickly. Now deletes files first and reindexes once. |
| 4 | **`started_at` was actually store time**, and it is the field the retention sweep deletes on. | Renamed `stored_at`. A field that decides deletion must not be named for something it is not measuring. |

**PR #13 review round — four findings, all valid, all fixed.**

| Severity | Finding | Why it mattered |
|---|---|---|
| P1 | **The request forced no response shape.** With the real Messages API this permits ordinary prose, and the parser accepted only one undocumented JSON shape — so a perfectly good review would land as an **empty report whose every section read "Nothing notable to report here."** | A report that looks complete and contains nothing is worse than a failure, because nothing signals it. Now a forced `submit_report` tool with the section enum in its schema. **Not the same mechanism as FR10's stage-2 enum** and worth not conflating: there the forced tool makes fabrication impossible; here it only fixes the shape. Evidence binding, not the schema, is what keeps report text honest. |
| P1 | **Only headlines were sent, never bodies.** `headline` is the anticipated question; `body` is the prepared answer. | Prep coverage, resume use and role fit are precisely judgments about the answer text, so three of the four rubric dimensions were being assessed against material the model never saw. Bodies now included, capped per chunk so one pasted resume cannot push the transcript out of the context window. **The stage-2 selector still excludes bodies deliberately** — that path is question-to-question on a latency budget, and its exclusion test still passes. The two paths differ on purpose. |
| P2 | **Mixed-type indices were filtered, not rejected.** `[0, "99"]` became `(0,)`, which resolves, so the finding was accepted although an index the model supplied never did. | Defeats the all-indices rule for exactly the shape a sloppy response takes — and the all-indices rule is the reason `test_an_invented_index_is_rejected` uses `(0, 99)` in the first place. Now rejected whole. |
| P2 | **Parser-discarded items were never counted.** Malformed entries never reach `verify()`, so the tally read zero while the parser had thrown away most of the response. | Same failure as silently dropping rejected findings, one layer earlier. `Report.discarded` now counts evidence rejections **and** parse failures together. |

The first two are the ones worth remembering: **every test in this milestone passed against a
generator that could not have worked against the real API.** The doubles returned exactly the shape
the parser wanted, so the missing schema constraint was invisible, and no test asserted that source
bodies reached the prompt because none of them looked at what the model was actually told.

**CI went red on mypy again, and the cause is the mirror image of last time.** `ctypes.windll` does
not exist off Windows, so `win_dpapi.py` needs `type: ignore[attr-defined]` for mypy in the Linux
container — and CI runs mypy *on Windows*, where those same ignores are unused and
`warn_unused_ignores` turns them into errors. **No single annotation satisfies both.** Fixed with a
per-module override disabling unused-ignore warnings for the three `platform/win_*` modules only.

M8's failure was "the container has a package CI does not". This one is "the container type-checks a
different platform than CI does". Same root cause, opposite direction, and the second one was not
prevented by learning the first.

**The pre-push check is now two commands, not one:**

```
PYTHONSAFEPATH=1 python -m pytest -q -m "not device and not slow"   # CI's sys.path
python -m mypy --platform win32 interview_prep_recall              # CI's platform
```

`--platform win32` reproduces the failure exactly — verified by re-enabling the warning and watching
the same four errors appear, rather than assuming the flag was equivalent.

**Deferred, named at task level**

| Item | Why |
|---|---|
| **T11.2's DPAPI binding** | `platform/win_dpapi.py` is written and cannot be exercised here. Everything around it is tested through the injected `Cipher` Protocol |
| **T11.10** report view and export | Qt |
| **`local_only` is not driven by `DegradationSwitches`** | Needs the composition root. `app.py` is a stub; inventing an attach mechanism without it would be speculative. **This is the D-23 shape and must be wired when `app.py` lands** |
| **`SessionRecord` is not attached to the assembler** | Same reason. Nothing feeds the record in production yet |

---

### M10 — Typed context sources · T10.1–T10.6 + migration complete · 2026-08-10

**Delivered** — 32 new tests, 325 total. `ruff`, `ruff format`, `mypy` clean.

| Task | What exists |
|---|---|
| T10.1 | `SourceKind` on the chunk, immutable after creation, defaulting to `PREP` |
| T10.2 | `NoteSet` → `ContextSet` with `by_kind` / `kinds_present` / `remove_kind` |
| **T10.2a** | **Schema v1 → v2 migration**: every v1 note becomes `PREP`, ids preserved |
| T10.3 | `add_source()` — per-kind import that replaces that kind and leaves the others alone |
| T10.4 | Per-kind candidate cap (2) and per-kind τ offsets from the single control |
| T10.5 | Kind labels in the stage-2 prompt, and the kinds explained in the system prompt |
| T10.6 | `track_progress` refused on any kind but `PREP`/`RESUME` |

**A flat chunk list, not five nested documents.** "The job description" is exactly "every chunk of
kind `ROLE`", so a separate per-kind container would be a second source of truth about membership
and the two would eventually disagree. `remove_kind` filters rather than rebuilding, so survivors
keep their ids and their cached vectors.

**The per-kind cap is on supply, not rank.** A long job description is the biggest document most
users import, so on chunk count alone an unweighted top-5 fills with role requirements and crowds
out the prep notes the product exists to surface. The best two of a kind still compete on score
with everything else. `test_no_kind_supplies_more_than_the_cap` asserts **both** halves — that no
kind exceeds the cap *and* that prep still appears — because the first alone would pass against an
implementation that returned nothing.

**τ offsets, never absolutes.** Prep and resume sit at the user's control exactly; the three
reference kinds sit 0.05 below, because HR prose will not match a spoken question as tightly as a
note written in the user's own voice. Absolutes would stop tracking the control and silently ignore
the sensitivity slider — the mistake design §5 already had to correct once for `tau_degraded`.
`test_reference_kinds_sit_below_the_users_own_words` pins the *direction*, since a sign flip would
pass every other test here while quietly burying the user's prep under the job description.

**Decisions made while implementing**

> **D-37 — FR70 is enforced by rejection in code and by coercion on load.** Constructing a note
> with `track_progress` on an untrackable kind raises; that is a bug at the call site. On the load
> path the same rule would be a disaster: `ContextSet.from_dict` turns a `ValueError` into
> `NoteSetCorruptError`, so **one stray flag on one chunk would make the user's entire note set
> unloadable** and send them to backup recovery. FR70's purpose is that an untrackable kind never
> reaches the checklist; dropping the flag achieves exactly that, refusing the file achieves it at
> the cost of everything else in the file.
>
> This is silent-fixing, which this codebase usually distrusts. The difference is that the safe
> interpretation is unambiguous and the alternative destroys access to data.

> **D-38 — the prefilter walks the full ranked list, so it needs its own early exit.** Per-kind
> thresholds killed the single `break` on "below τ_floor". Restored as a break below
> `min(tau_for(k))`, which is sound because the list is sorted descending and no kind's floor is
> lower. The note lookup also moved from `note_set.get` (a linear scan) to a dict — inside a loop
> that can now walk the whole corpus, the scan made the prefilter O(n²) against NFR's 50 ms budget
> for 200 notes.

**Review round, before push.** Three findings, all mine, all fixed above: the FR70 load-path
rejection (D-37), the O(n²) lookup and the missing early exit (D-38). The first is the one that
mattered — it was a new way for a nearly-valid file to cost the user their notes, in a milestone
whose headline feature is *not* doing that.

**PR #12 review round — three findings, all valid, all fixed.**

| Severity | Finding | Why it mattered |
|---|---|---|
| P1 | **`__setattr__` committed the value before validating it.** A caller setting `track_progress` on a role chunk and catching the `ValueError` kept a tracked role chunk: `tracked()` returned it and the checklist would tick off a job requirement never spoken — **FR70 violated by the code written to enforce it.** | Validate before assignment. My own test asserted the raise and never checked the state afterwards, so it passed against exactly this bug. Same defect class as always, in mutation form. |
| P2 | **Migration status was invisible to callers.** `load()` returned a plain `ContextSet`, so nothing could distinguish an upgraded file from an ordinary one — making FR73c's notice *unimplementable* rather than merely unbuilt. | `ContextSet.migrated_from`, excluded from `to_dict` and from equality. Provenance of one load, not a property of the data; persisting it would make every later load claim to have been migrated. |
| P2 | **`add_source` removed the old source before validating the new one.** One non-verbatim bullet destroyed the job description the caller was updating and left a partial replacement behind. | Build and verify first, then swap. |

**Deferred, named at task level**

| Item | Why |
|---|---|
| **T10.7** per-kind overlay marking | Qt. §9b tokens are specified |
| FR73b's SIGKILL-mid-migration run | The migration reaches disk only through the existing atomic write path, which already has the ×10 SIGKILL test. A migration-specific run belongs with the Windows NTFS pass |

---

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
