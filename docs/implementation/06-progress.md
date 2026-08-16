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
| **M1 — Audio capture spike** | 🟡 Code written, **unrun** | T1.1/T1.2/T1.4 implemented from `pyaudiowpatch` docs; T1.3 already done. **Nothing has executed** — `scripts/m1_spike.py` is the AS-2 gate and needs the Windows machine. |
| **M2 — STT interface & local backend** | 🟢 T2.1–T2.3 complete | Interface, local backend, assembler. T2.4 is the **AS-1 latency gate** and genuinely needs the target laptop. T2.2's model adapter is unverified (**AS-9**) |
| **M3 — Notes store & indexing** | ✅ **Complete** | T3.1–T3.9 **and T3.7a**. Store, importer, index, editor, set lifecycle, backup restore **and the import surface**. Nothing in M3 is outstanding |
| **M4 — Matching pipeline** | 🟢 T4.1–T4.6 complete | T4.7 **blocked**: needs the user's labelled fixtures |
| **M5 — Overlay UI** | 🟢 Everything buildable here is done · **T5.10 joined it to matching** | T5.1, T5.3, T5.4, T5.4a, T5.5, T5.6, T5.7, T5.8 complete and tested offscreen. Remaining: **T5.2** (`SetWindowDisplayAffinity` — Windows) and **T5.9** (end-to-end latency, needs the D-U6 laptop). Nothing else in M5 is buildable in this container |
| **M6 — Session lifecycle** | 🟢 Logic complete · panic on hold (D-U11) | T6.1–T6.3, **T6.3b's panic surface**, T6.5 classification, T6.6 backpressure, T6.7 done. T6.4 and the OS trigger paths need Windows |
| **M7 — Progress tracker** | 🟢 Everything buildable here is done | T7.1, T7.3 and **T7.4** complete. T7.2 needs paired audio fixtures — the only M7 task left |
| **M8 — Cloud STT backends** | 🟢 T8.1–T8.5 complete | Deepgram, ElevenLabs, fallback, egress. Protocols unverified against a live endpoint (**AS-8**) |
| **M9 — Packaging & first run** | 🟡 T9.0–T9.2, T9.6 complete | Composition root, FR63 disclosure, config store, settings surface, **entry point**. T9.3 is **blocked on M1** (three of four steps are audio). **T9.6a no longer needs FR43** — T3.8 answered it and `editor.load_active_set` is the reader; it is down to the no-API-key policy (from T9.3), a real embedding model (`sentence-transformers` is in the platform-neutral `embeddings` extra — blocked **here** by network policy, same as AS-9, not by platform) and the Windows-only DPAPI cipher. T9.4 is PyInstaller; T9.5 needs live vendor docs |
| **M10 — Typed context sources** | 🟢 T10.1–T10.7 complete | Five kinds, per-kind caps and thresholds, schema v1→v2 migration, **FR72's per-kind marking**. T10.7's 1 m glance test and bundled-font glyph coverage ride with T5.9/T9.4 |
| **M11 — Post-interview report** | 🟢 T11.1, T11.3–T11.10 + a/b/c complete | Record, evidence binding, encrypted store, retention, generation, the view/export, **context snapshots (D-58) and off-thread generation (D-59)**. Only T11.2's DPAPI cipher needs Windows |

**Next action: T10.7b**, the one small thing left — the kind legend beside the import dialog's
selector as well as the editor's. After that this container is genuinely out of work: what
remains is the Windows machine, the user's fixtures, or a vendor key.

*(T7.4a was measured on 2026-08-16. Its code half turned out to be a test that asserted nothing;
its remaining half is a real-surface judgement riding with T5.9.)*

*(T3.7a landed on 2026-08-16 — the importer has a surface, so notes can finally be brought in
rather than typed.)*

**The "nothing left to build" claim was wrong a seventh time, on the line directly below this
one.** It named T11.10 as the last buildable task on 2026-08-15; T3.7 and T3.8 shipped that same
day and T3.9 the next morning, all three headless, none of them needing anything external. Every
instance has had the same cause — a milestone treated as blocked because one *task* in it is —
and the same four-minute fix. What remains genuinely external is listed below with a falsifiable
reason each; test the reason, not the milestone.

**Treat that as the claim it is.** The same sentence has now been wrong seven times, most
recently on T11.10 itself: it was filed "(Windows / Qt)" and the entire task — list, reader, generation,
export, deletion — built and tested headless. The check that has caught every one of them is the
same: try it for four minutes before believing the label. If a task below looks blocked, the
reason is written next to it; test *that reason*, not the milestone it belongs to.

The two highest-value external items, if a machine becomes available: **M1's WASAPI spike** (the
AS-2 gate, and M9's packaging is blocked behind it) and **T4.7's labelled fixtures** (the OQ-1
gate, which decides whether matching is good enough to ship at all). Neither is code.

**T10.7's two wrong claims, kept because they are the pattern.** The task note said "§9b tokens
are specified" for a section with no per-kind row at all, and the next-action line put the work
in the editor rather than the overlay. Both were written *here*, in the summary, and neither was
re-read as a claim before being acted on. See the M10/T10.7 log entry and D-55.

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

- **Buildable and testable here (Qt, offscreen):** **T10.7b** (the kind legend beside the import
  dialog's selector too). *(T10.7a and T7.4a both landed on 2026-08-16 — T7.4a's remaining half
  is a real-surface judgement, listed under T5.9 below.)* *(T3.9's backup restore and T3.7a's import surface both landed on 2026-08-16,
  completing M3.)* *(T11.10a/b/c all landed on 2026-08-15, along with T6.3b — the panic surface T11.10a
  needed, which no task had ever named.)* *(M5's overlay widget, T7.4's checklist, T10.7's
  per-kind marking and T11.10's report view were all on this list and are now done — T5.4, T5.7,
  T5.8, T7.4, T10.7 and T11.10 all landed on 2026-08-15.)*
- **Genuinely needs Windows:** M1 (WASAPI, AS-2 gate), T2.4 (AS-1, needs the D-U6 laptop's CPU),
  T5.2's `SetWindowDisplayAffinity`, T6.4's ProcMon trace, T9.1a's device-open enforcement,
  T9.4's PyInstaller build, T11.2's DPAPI cipher. **T11.10 is off this list** — it was on it, and
  the export writes an ordinary file to an ordinary path.
- **Needs the real surface (not merely Windows):** T5.9's end-to-end latency; **FR72's
  1 m glance test and the bundled-font glyph coverage** — Qt substitutes a fallback font per
  missing glyph, which is invisible headless and wrong only where it is looked at; and
  **T7.4a's readability judgement** — measured here as 7 bullet lines falling to 5 under a full
  checklist at FR23's maximum, and 2 at the minimum. Whether those densities *read* is not a
  number this container can produce.
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

### T7.4a — the checklist at FR23's ceiling · measured · 2026-08-16

`tests/test_checklist.py`: one vacuous test replaced by three that bite. No production
change. **1216 passing**, ruff, format and `python -m mypy interview_prep_recall` clean.

**Scope first, and the scope turned out to be smaller and different than the plan said.**
T7.4a is written as "confirm against the real surface in T5.9", which is a hardware check,
not code. So the question was what — if anything — is verifiable here. The answer was
found by measuring rather than reading, and it was not what the note claimed.

**The floor is not where the plan put it.** T7.4's note said the bullets give way at
FR23's 600px maximum "and never past `MIN_BULLET_LINES`". Measured: at 600px the allowance
falls from **7 lines to 5** when a full checklist appears, and the floor is nowhere near.
It engages at the **minimum** size, where the unfloored measurement comes out at **zero**
and two lines is the whole of what §9b guarantees.

**So the test written for that paragraph asserted nothing.** It read
`assert panel.bullet_lines_available(...) >= MIN_BULLET_LINES` at the maximum size — a
comparison of 5 against 2, on a path where the floor is never reached. It would have
passed against a panel that ignored the checklist's height entirely, which is the one
thing it existed to catch. **The fifteenth instance of this project's characteristic
defect**, and the first found by asking what a documented number actually is rather than
by a test failing.

Three tests replace it, each run against its own defect:

| Test | Defect it was run against |
|---|---|
| The allowance **falls** when the checklist appears at the maximum | `bullet_lines_available` ignoring `reserved_height` |
| The two-line floor holds **at the minimum size**, where it is reached | the `max(MIN_BULLET_LINES, …)` floor removed |
| A squeezed bullet **elides** rather than clips (FR23) | `elide_to_lines` returning its input |

**What is still blocked, and it is the half T7.4a was actually about.** Whether five lines
of bullet under a five-row checklist *reads* well — and whether two lines at the minimum
size is usable rather than merely non-clipping — is a judgement about a real surface at a
real distance. It rides with T5.9, alongside FR72's glance test and the bundled-font glyph
coverage. Nothing in this container can answer it, and no test here should pretend to.

**This container is now out of buildable work**, with one exception named below.


### T10.7a — the kind legend · complete · 2026-08-16

`ui/editor.py` gains a legend and marked note rows; `overlay.legend_entries` publishes the
marks in order. `tests/test_editor.py` +6. **1216 passing**, ruff, format and
`python -m mypy interview_prep_recall` clean.

**A code with no key.** T10.7 gave each kind a shape (D-55) and a tooltip, and the tooltip
is on the overlay — so the only way to learn what ▲ meant was to hover it *during an
interview*, the one moment the user has no attention to spare for learning a code. FR72
asks for the kind to be distinguishable without reading, which the shapes achieve; being
distinguishable and being *identifiable* are not the same property.

**Two halves, and the second is what makes it teach.** The legend names all five beside
the kind selector, which is where the question is actually asked. And every note's row in
the editor now carries the same glyph it will show on the overlay — so the user sees ■
beside their prep notes every time they edit, and the shape is already familiar the first
time one appears mid-interview. A legend alone is a thing you read once and forget;
repetition against your own notes is what makes it stick.

**Derived, never restated.** `legend_text` is built from `overlay.legend_entries`, and a
test replaces a mark at runtime and asserts the legend follows. A legend that drifts from
the marks it explains is worse than no legend, because the reader has no way to tell which
of the two is lying — and this project has already shipped one doc that disagreed with the
code it described.

**PR #31 review — one finding, valid, fixed.** Prefixing each row with the glyph broke
Qt's type-to-select: incremental search matches `Qt.DisplayRole` from the start of the
string, so typing a headline's first letters no longer reached that note. **Keyboard
navigation traded for a decoration**, and an accessibility regression introduced by a task
about making the product easier to read.

The mark now trails the headline (D-67). Leading would read better — a column of shapes
scans faster than a ragged right edge — and overriding `keyboardSearch` would buy that
back, but reimplementing Qt's multi-key timeout, cycling and wrap-around semantics is real
complexity for a placement. The association still forms; the glyph is on every row either
way.

**A near miss worth recording.** Running each test against its own defect, the row-marking
test *passed* against an unmarked list — which would have meant a test asserting nothing.
It was not a weak test: the `sed` that was supposed to break the code had silently matched
nothing, so the "defect" was never applied. Repeating it with an assertion that the
substitution took effect showed the test failing correctly. **The discipline needs its own
check:** verify that the mutation landed before trusting what the run says about it,
because a no-op edit and a vacuous test look identical from the outside.

**Not done, and unchanged from T10.7.** FR72's acceptance is a glance test at 1 m, and
glyph coverage in the bundled Plex faces is still unverified — both ride with T5.9 and
T9.4. The legend does not change either: it makes the shapes learnable, not legible at a
metre.

**Follow-up T10.7b:** the import dialog assigns kinds in bulk and has no legend beside its
own kind selector. Deliberately out of this task, which the plan scoped to the editor.


### T3.7a — the import surface · complete · 2026-08-16

New `ui/import_notes.py`, wired into `ui/editor.py`; `headline_needs_review` published from
the importer. New `tests/test_import_notes.py` (31 cases), plus a drain fixture in `conftest`. **1207 passing**, ruff, format
and `python -m mypy interview_prep_recall` clean.

**Two modules with passing tests and no caller, joined at last.** T3.5 built the chunkers,
the strategy detection and the verbatim bullet proposal; T10.3 built `add_source`, the
per-kind replacement. Neither had ever been called from the product, so **a `.md` of prep
notes could not be brought in at all**, and FR66's five kinds could only be created by hand
in the editor, one note at a time. The user's first contact with the app was the piece with
no way in — the fifth instance of this shape after T5.10, T3.7, T3.9 and the health
indicator.

**FR2 is the shape of the dialog, not a step inside it.** The requirement asks that every
auto-split chunk is *presented for review and editable before save*, that the strategy is
*named*, and that the user can *switch it* before saving. So the review list is the main
body rather than a confirmation at the end, the strategy is a control rather than a label
(with names a person reads — `md_header` is an identifier), and the Import button is the
block FR2 describes: it does nothing until there are reviewed chunks on screen.

**Importing replaces one kind and leaves the other four alone** (FR66). That is what
re-importing a job description means, and it is destructive, so it takes FR60's
confirmation **with the count in it** — "cannot be undone" is only fair if it says how
much. Refused mid-session, for D-61's reason arriving by another route: it removes every
note of a kind that the tracker's verdict and the report's D-58 snapshot both describe.

**Three defects found reviewing this branch before pushing**, all fixed:

| Severity | Finding | Why it mattered |
|---|---|---|
| Fix now | **Detection never ran on the paste path.** `analyse` passed the combo box's value unconditionally, so pasted `Q:`/`A:` notes were chunked as Markdown headings — producing nothing — with the box showing a strategy the user never picked. | FR2 makes `.txt` auto-detected, and paste has no filename to detect from. Detection now runs until the user overrides it, and stops once they do (D-64). |
| Fix now | **A bad bullet elsewhere in the set would have raised out of a Qt slot.** `add_source` verifies the incoming notes; `NotesStore.save` verifies the whole set. Between them sits the modeless editor, which can make the *rest* of the set unsavable while the dialog is open — leaving the set replaced in memory and unchanged on disk. | The survivors are verified before anything is removed (D-65), preserving the property `add_source` was built around. |
| Fix now | **`dialog.strategy` was annotated `ChunkStrategy` and returned `str`.** `ChunkStrategy` is a `StrEnum` and Qt stores a `str` subclass as a plain `str`. | Everything worked, because a `StrEnum` compares as its value — which is exactly why it was worth fixing. mypy cannot see through Qt's `Any`, and the first caller to write `is ChunkStrategy.MD_HEADER` would have been quietly wrong. Found by a test asserting `is`. |

**Ten tests were run against their own defect**, one at a time: no re-embed, no
mid-session guard, a strategy switch that does not re-chunk, a headline warning never
recomputed, an editor that opens the import without flushing, a missing suffix check, and
the two fixes above. All eight failed, then passed.

**One thing the tests found that the plan did not name.** Opening the import while the
editor holds unsaved edits writes those edits as a side effect, because the import saves
the same `ContextSet` object. The editor now flushes first and **does not open the dialog
if the flush refuses** — the same rule as `activate` and `_on_restored`. A refusal that
means different things at different exits is not a refusal.

**PR #30 review — two findings, both valid, both fixed.** Both were the same mistake in
two places: **the review UI describing something other than what would actually be
imported.**

| Severity | Finding | Why it mattered |
|---|---|---|
| P1 | **Changing the source did not invalidate the review.** Pasting a second source, or opening another file, left the previous source's chunks on screen with Import still live. | Importing replaces every note of the chosen kind, so pressing it would have destroyed the user's notes in favour of a file they were not looking at. Staleness is now a comparison against the exact text that was chunked — so the import is *disabled*, not discarded, and undoing the change re-enables it rather than costing the user their review edits. |
| P2 | **Declining the re-chunk warning left the selector on the declined strategy**, naming one the chunks were never made with. | FR2 requires the review UI to *name* the strategy that was applied. The box goes back. |

**And a segfault, found by running the suite rather than by reading it.** Adding 28 Qt
tests made the full run crash roughly two times in three — on Linux, where the previous
teardown crashes had only ever appeared on Windows. Every test passed; the process died.

The stack said `processEvents`, in the overlay's clock test, which is the only test that
pumps the loop for two seconds. Four experiments narrowed it: `main` was clean 3/3, this
branch crashed 2/3, this branch **without the new test file** was clean 3/3 — so the new
*tests*, not the new code — and neither half of the file crashed alone. Cumulative, then,
not one bad test.

The mechanism: an unparented `QDialog` is owned by Python and dies the instant a test's
last reference goes, immediately rather than deferred. Anything still queued for it gets
dispatched against freed memory by whichever test next pumps the loop — so the crash
landed twenty files from its cause, and the session-scoped teardown could not help,
because by then the objects are long gone. `tests/conftest.py` now drains after every
test, while that test's widgets are still alive (D-66). Clean 4/4 after.

**That is the fifth destroy-order defect in this harness** (D-53, D-54, and the two on PR
#27) and the second to present as a crash with the suite reporting green. Worth stating
plainly: had this branch been pushed after a single clean local run, it would have been a
flaky Windows CI failure with nothing pointing at the import surface.


### T3.9 — backup restore · complete · 2026-08-16

New `ui/restore.py`, three new store methods, wired into `ui/editor.py`. New
`tests/test_restore.py` (26 cases). **1176 passing**, ruff, format and
`python -m mypy interview_prep_recall` clean.

**The last unbuilt M3 task, and the same shape as the four before it.** FR29 keeps five
generations and says they are *restorable from the UI*; the rotation, the atomic write and
`restore_latest_readable`'s fall-through were all built in T3.2/T3.3 with passing tests,
and **nothing in the product ever opened them**. A backup that cannot be reached is a
file, not a recovery — and this is the one requirement whose entire purpose is the moment
something has already gone wrong.

**Three properties carry the surface.**

* **Preview never writes.** `read_backup` parses and returns; `restore_generation` is a
  separate call. Looking at a backup must not be able to cost the user their live file,
  and a preview routed through restore would rotate the generations out from under the
  list they are reading — the row they click would stop being the version they saw
  (D-62).
* **A corrupt generation is not the end of the list.** Every row says whether it can be
  read and why not, and "Restore newest readable" falls through the unreadable ones and
  **names the ones it skipped**. Landing quietly on version 3 leaves the user believing 1
  and 2 are still there to go back to.
* **Restoring the active set re-points everything that reads it.** D-61 again: the index,
  the prefilter and the tracker each hold their own reference, so a restore that only
  rewrote the file would leave matching drawing from the version just replaced. It goes
  through `activate_context_set` — and asks `can_change_context_set` **before** the write,
  because discovering the mid-session refusal afterwards would leave disk and memory
  describing different sets, which is worse than either outcome alone.

**FR44 was the half nobody had built.** The requirement is "a corrupt, unparseable **or
missing** note set *offers restore* rather than failing silently or starting empty", and
the product met a corrupt set in exactly two places. `NotesEditor.activate` reported the
error and stopped — five readable copies on disk and nothing connecting them. Worse,
`load_active_set` **fell through to a brand-new empty set**: the user's notes intact in
five backups, and the app opening on nothing. That is the literal "starting empty" the
requirement forbids, and the failure most likely to be read as *the app lost my notes*.
Both are now wired (D-63), with `SchemaTooNewError` deliberately excluded — the backups
are the newer format too, so restoring one would be this build overwriting data it cannot
read.

**Every test was run against its own defect.** Six of them, one at a time: assigning
`context_set` instead of activating, dropping the dirty-flag clear, moving the session
check after the write, restoring the fall-through's silence, reverting the startup
recovery, and routing preview through save. All six failed, then passed. That check is
this project's standing answer to its recurring defect, and it earned its place again —
one of the tests had been passing for the wrong reason before the helper was fixed (the
history fixture minted a fresh id per version, so **nothing rotated** and eleven tests
were asserting against sets with no backups at all).

**PR #28 review — two findings, both valid, both fixed.** Both were about the *other* set:
the one not being restored.

| Severity | Finding | Why it mattered |
|---|---|---|
| P1 | **Restoring a different set discarded the current set's unsaved edits.** The dirty flag was cleared unconditionally, and the dialog's unsaved-changes notice only covers the active set — so edits typed while the modeless dialog was open vanished with no write and no warning. | Who owns the pending write decides what happens to it. Restoring *this* set drops them (they belong to the version being replaced); restoring another one flushes them, and a refused flush blocks the switch — the same rule `activate` already followed. |
| P2 | **A set that was corrupt when the editor opened was not listed at all**, so `activate` never ran on it and the restore was never offered. Its five generations were on disk with no control anywhere that could reach them. | The recovery path built by this task was unreachable for the case it exists for. Unreadable sets are now listed and marked; selecting one runs the offer. |

**One thing worth flagging rather than fixing.** `load_active_set`'s new `ring` argument
has no production caller, because `load_active_set` itself still has none — T9.6a is the
entry point that will call it, and it remains blocked on the no-API-key policy and the
network-blocked embedding model and the Windows-only cipher. This is the D-20 shape by
the letter of it. It is
recorded here rather than dressed up: the recovery is reachable and tested, the *notice*
needs a surface that does not exist yet.

**M3 is complete.** T3.1–T3.9, all nine.

### T3.7 + T3.8 — the notes editor and the set lifecycle · complete · 2026-08-15

`ui/editor.py` (was a four-line placeholder), `Application.activate_context_set`, wired into
`ui/main_window.py`. New `tests/test_editor.py` (28 cases), `tests/test_main_window.py` +2.
**1137 passing**, ruff, format and `mypy interview_prep_recall` clean.

**Notes could be imported, matched, tracked, embedded and reported on — and not written.** The
store, the model, the importer and the index all had tests, and the product had no way to create
a note. Same shape as T5.10, one layer further out.

**Three properties carry this surface.**

* **Saving is debounced, never per keystroke.** `NotesStore.save` rotates FR29's five backup
  generations on every write, so a save per keystroke leaves the user's recovery window covering
  the last twelve characters they typed. Edits mark dirty; `flush` writes; the timer is a
  convenience over `flush`, so what the tests drive is what ships. Closing flushes, because the
  alternative discards five seconds of typing to a race with a timer.
* **Ids survive edits** (FR41). The editor mutates the note the set holds rather than replacing
  it — the embedding cache is keyed on note id, and a new id per edit is BC-1's stale-vector
  failure arriving through the editor.
* **FR42 is checked before the write.** A bullet that is not a substring of its note is generated
  content one match away from the overlay. Refusing at save keeps the user in a fixable state;
  writing it would leave notes that are stored and unusable, because the render boundary refuses
  them later.

**Switching sets was the trap (D-61).** `self.context_set` is not the only holder: the index is
*built* from the set and `Prefilter` keeps its own reference. Assigning the attribute would have
left matching drawing from the previous corpus — silent, and indistinguishable from bad
retrieval. `activate_context_set` rebuilds both, and **refuses mid-session**: changing the corpus
under a running interview leaves the tracker's verdict and the report's D-58 snapshot describing
two different sets.

**T5.10a is closed by the same wire.** The overlay holds the set it was handed once, so the switch
notifies it through `on_context_set_change` — with D-60's loud default, so an unwired build
records `context_set_change_unrendered` instead of rendering the old corpus under the new one's
name.

**One thing the tests found that the plan did not name.** An `Application` can be constructed with
a set that has never been saved — the composition root does that on a first run — and until it
exists on disk it cannot be listed, cannot be switched back to, and vanishes the moment the user
creates a second set. The editor persists it on open. A write as a side effect of opening a window
is worth stating out loud; the alternative is a surface that quietly loses the thing it is editing.

**PR #27 review — six findings, all valid, all fixed.** Five were P1 and three of them are the
same sentence: *more than one object holds the active set, and more than one holds its vectors.*

| Severity | Finding | Why it mattered |
|---|---|---|
| P1 | **The tracker kept the previous set.** `reset()` clears session state, not the reference, so the checklist rendered the old set and tracking intersected the old tracked ids with the new index — no point in the newly active set could ever be marked. | Third holder of the same object, after the index and the prefilter. The count is the argument for `activate_context_set` existing at all. |
| P1 | **Saving wrote JSON and not vectors.** A note added or re-headlined in the editor was matched on its previous text — absent entirely if new — until the user switched sets or restarted. | `Application.notes_changed`, on the application because the index is the application's; FR34's content hashes make it cheap enough per save. |
| P1 | **A failed flush did not block a set switch.** `flush` refuses a non-verbatim set and leaves it dirty *on purpose*; switching anyway replaced `context_set` and put those edits where the user could not reach them. | The refusal says "you can fix it" and this made that false. |
| P1 | **A failed flush did not block closing**, for the same reason and with a worse ending: the next editor opens clean against the mutated object, no timer is pending, and quitting loses the work. | |
| P1 | **Deleting a set left its backups.** FR29 keeps five generations, so up to five complete copies of the notes stayed on disk under a control whose confirmation says "cannot be undone" — true of the user's access, false of the data. | |
| P2 | **`ACTIVE_SET_KEY` had no reader.** The id was written and never read, so FR43's across-restart persistence did not exist. | D-20's shape, in the requirement this task is *for*. |

**The last one is worth more than its severity.** `__main__._build_application` names FR43's
active-set selection as one of three blockers keeping T9.6a unimplemented — so writing an id
nobody read left the entry point blocked on a decision that had just been made and not connected.
`editor.load_active_set` is that reader: the persisted set, else the only one, else a new empty
one, and it never raises for an ordinary state because a first run and a set deleted on another
machine are both situations the entry point has to survive. **T9.6a is down to two blockers** —
the no-API-key policy, a real embedding model (network, not platform) and the
Windows-only DPAPI cipher.

**Follow-up T3.7a:** the editor lists sets and cannot *import* into one — T3.5's importer has no
surface either, so a `.md` of prep notes still cannot be brought in through the UI. That is the
next instance of this same pattern, and it is now named rather than waiting to be tripped over.

**Three Windows CI failures, and what they cost.** PR #27's Windows job died with *"Windows fatal
exception: access violation"* in the `qapp` fixture's teardown, after every test had passed and
with Linux green on the same commit. The crash does not reproduce here, so each attempt was a
guess until the third one stopped being one.

1. **Hide before delete.** The editor's `closeEvent` can refuse a close (a non-verbatim set), so a
   dialog could still be visible when `deleteLater` ran. Plausible; wrong.
2. **Delete only parentless roots, and check `isValid` first.** `topLevelWidgets()` returns
   objects the C++ side may already have freed, and deleting a parented child double-frees. Also
   real, also not it — the third stack pointed at the same `app.processEvents()` line.
3. **The clock.** `processEvents()` dispatches **timers**, not just deferred deletions. T5.10 had
   `MainWindow.__init__` call `overlay.start_clock()`, and `start_clock` built a *new* `QTimer`
   every call — so every overlay any test ever constructed left a repeating 500 ms timer alive for
   the rest of the session, firing into widgets queued for deletion. That is the access violation,
   and it is a leak on the real product too: a panel the user never sees still ticks.

   The fix puts the clock's lifetime where it belongs — `showEvent` starts it, `hideEvent` stops
   it, one timer reused — so FR54's auto-clear runs exactly while the panel is on screen. Three
   tests cover it, including that showing twice does not stack timers.

**The lesson is about method, not about Qt.** The first two fixes were written from a reading of
the code; the third was written from the stack trace, which had named `processEvents` all along.
*Ask what else that line does* before proposing what to change around it. And a teardown crash
with all tests passing is the same family as this project's recurring defect — the suite reported
green while the process was dying.

### T5.10 — the match feed · complete · 2026-08-15

New `ui/match_feed.py`, wired in `ui/main_window.py`. New `tests/test_match_feed.py` (17
cases). **1107 passing**, ruff, format and `mypy interview_prep_recall` clean.

**The product's central behaviour was not connected.** `MatchingPipeline` produced a
`MatchResult`, `Application.on_result` defaulted to `lambda _result: None`, and nothing ever
assigned it. `OverlayPanel.show_snippet` had **no production caller anywhere**, and neither did
`from_stored_note` — the function made to take a required `resolve_kind` in T10.7 precisely so
FR72's mark could not be omitted. Every component below the join had passing tests: the
prefilter, the forced-tool selector with its sequence gate, the panel, FR11's substring check,
FR51's two states, FR72's marks. A snippet appearing when the interviewer asks a question is the
one thing this product is for, and it did not happen.

**Found by looking, not by tripping over it.** After the retention sweep (PR #24) and the health
indicator (PR #25) turned out to be the same defect, a `grep` over every `on_*` hook took about a
minute. That is now **D-60**: a hook whose absence breaks a feature does not get a no-op default,
and the sweep runs when a feature's surface is built. A no-op default makes an unwired hook
indistinguishable from a wired one at runtime *and* at type-check time, which is why four of
these survived six milestones of tests that all passed.

**Two more uncalled things fell out of the same wire.** `start_clock` — FR54's auto-clear, whose
absence would have left the first snippet on screen for the rest of the interview — and **D-6's
truncation**, which was specified in the decision log, referenced by `Note.is_overlay_optimised`,
and implemented nowhere. A bullet-less note would have rendered as a bare headline.

**What the module does and does not do.** `snippet_for` is a pure conversion — result plus
context set in, `SnippetView` out — so which outcome becomes which visual state is testable
without a widget. It composes nothing: bullets come from the note's own `bullets`, and D-6's
fallback is a *prefix* of the body ending at a sentence boundary, which is what lets FR42's
verbatim rule and truncation coexist (D-50's reasoning, one layer up). `source_text` returns the
same haystack `Note.verify_bullets_verbatim` uses, deliberately: if those two disagreed, a bullet
valid on save would be refused at render and the panel would go blank mid-interview.

**A note deleted between the match and the render is the no-match line, not an error.** The
pipeline and the editor share a set, so it is an ordinary race, and FR35 already says what the
panel shows when there is nothing to show. `from_stored_note` still raises for a fabricated id —
the difference is that this checks first and that one is the guarantee.

**PR #26 review — one finding, P1, and it was the same defect one layer in.** `MatchingPipeline`
was constructed with `on_result=self.on_result`, which **copies** the field's value — the no-op
default — so assigning `application.on_result` from the window changed nothing the pipeline calls.
The fix for the missing wire did not fix the missing wire.

**My end-to-end test masked it**, and that is the part worth keeping. It called
`application.on_result(...)` directly, which proves the hook is assigned and nothing about the
path a real interview takes. A test that skips the producer cannot see a producer holding a stale
callback. The replacement drives an interviewer utterance through `consume` and asserts on the
widget, and was checked by reverting the fix and watching it fail — a test written for a defect
that was never observed failing is a guess.

Two changes came out of it: the pipeline is given a **delegating** lambda so the field is a hook
rather than a constructor argument that looks like one, and `on_result`'s default now **records**
`match_unrendered` to the diagnostic ring instead of discarding silently. It cannot raise —
a headless `Application` is legitimate, every test is one — but it can be the difference between
"no surface is attached" and "the surface is attached and broken". That distinction is what was
missing for six milestones, and D-60 is the rule; this is D-60 applied to the very hook that
taught it.

**Follow-up T5.10a:** the panel's `context_set` is assigned once, at window construction. Switching
note sets (T3.8, unbuilt) must re-assign it, or the overlay renders against the previous set.
Written down now because that is exactly the kind of wire this entry is about.

### T11.10a/b/c + T6.3b — the report follow-ups · complete · 2026-08-15

All three follow-ups from PR #24's review, plus the task that was blocking one of them.
**1082 passing**, ruff, format and `mypy interview_prep_recall` clean.

**T11.10c — a report is graded against the interview's own context (D-58).** The transcript
already travelled with the tracker's coverage verdict for exactly this reason, and the rest of
the context did not: a report regenerated a week later graded its JD-fit and resume sections
against whatever notes happened to be loaded that day. Silently, and confidently, in a document
the user reads about themselves. A session now carries a snapshot of its context set, inside the
same encrypted envelope so FR82 covers it and beside the transcript so FR84 deletes it. The set
*id* was the tempting cheap answer and is useless — the set is mutable, so a week later the id
resolves to something else. A session with no readable snapshot still generates, against today's
notes, and says so on the two sections the substitution distorts; prep coverage stays unmarked
because it rests on the tracker's stored verdict and survives intact. Marking it too would
overstate the damage and train the reader to ignore the notice where it is true.

**T11.10b — generation off the GUI thread (D-59).** `ReportGenerator` splits into `prepare` (the
refusals and the prompt — no socket, no indicator) and `send` (the network). The split is at the
*payload* rather than at the confirmation, which is what keeps FR81 honest under threading: the
size shown and the size sent come from one `PreparedReport`. The confirmation stays on the GUI
thread because a modal opened from a worker is undefined behaviour in Qt — PR #22's defect. Not
the application's executor: that pool serves matching on a latency budget during a live interview
(D-11), and a multi-second upload parked in it would sit in front of a stage-2 call.

**FR81a was the real casualty, and it is worth stating plainly.** The egress indicator was set for
the duration of the upload on a thread that could not repaint — lit in memory and dark on screen
for exactly the seconds it exists to announce. The requirement's test passed the whole time,
because it asserted the flag and not the pixels. That is this project's signature defect, and it
survived two review rounds on the surface that renders the indicator.

**T11.10a — FR87's signpost, and T6.3b, the task that had to exist first.** The blocker was never
a decision: T6.3a built the state machine's half of the panic control and **nothing could press
it**, so the surface FR87 names did not exist. Recorded as T6.3b rather than absorbed into
whichever task tripped over it — the fourth time in this plan a named prerequisite turned out to
have no ID (after T9.0, T9.2a and T9.6). Single action, no confirmation (FR60), pressing it before
a session says so rather than raising, the paused state visible in words, and a signpost carrying
both halves: that panic destroys nothing, and where the deliberate route is. A test asserts the
route it names actually exists, because a signpost pointing at an absent control satisfies the
wording and fails the reader.

**PR #25 review — five findings, all valid, all fixed.** Two of them were wires that did not
exist, which is this codebase's most repeated defect and the reason D-20 has a number.

| Severity | Finding | Why it mattered |
|---|---|---|
| P1 | **Nothing forwarded `HealthMonitor` changes to the overlay.** The monitor recorded every state design §7 specifies, `IndicatorBar` rendered them, `OverlayPanel.update_health` existed — and no line connected them. FR20's egress lamp and FR35's health states were correct in memory and never drawn. | It also makes the FR81a claim above only half true: freeing the event loop was necessary and not sufficient. Both halves had passing tests; the wire between them was the part nobody owned. |
| P1 | **The panic button was refreshed once, at construction.** A window built at IDLE — which is every real launch — left the emergency control disabled for the entire session that started afterwards. | Dead in exactly the case it exists for. My own tests hid it by starting the session *before* building the window, which is the reverse of what a user does. |
| P1 | **Delete-all stayed enabled during an upload.** The worker then wrote a report for a transcript the user had just deleted, and the view announced success. | Fixed at both ends: the control is gated, and `attach_report` refuses to write for a session with no transcript — the half that holds for any caller. |
| P2 | **`_parse_context_set` caught a named tuple of exceptions.** A `notes` list containing `null` raises `AttributeError` from the sort key, which escaped and failed `load()` — making the transcript unreadable, the exact outcome the fallback exists to prevent. | A guarantee stated in a docstring and enumerated in an `except` clause is only as good as the enumeration. |
| P2 | **Absence citations resolved through today's notes.** Ids are stable across edits (FR41), so an edited headline rendered today's words under a finding generated from the snapshot. | The same substitution D-58 removed from generation, one layer down — and harder to notice, because the citation still resolves. |

**Wiring the monitor cost a segfault first, and the fix is worth reading.** Handing the
application a bound `emit` of a widget makes the app outlive a reference into a deleted C++
object; the next health update walks into it. That is the third time this project has produced
that shape (D-53, D-54). Both hooks are now cleared on the window's `destroyed`, through lambdas
that close over the *application* and never over `self`.

**The two tests worth keeping.** `test_the_default_dispatch_really_leaves_the_gui_thread` drives
the *production* dispatcher and asserts the model call ran on another thread — every other test
injects an inline dispatcher and would pass whether or not a thread was ever created. And
`test_regeneration_uses_the_snapshot_not_todays_notes` asserts on the prompt: today's notes must
not appear in it. Both are about the property rather than the plumbing.

### M11 — T11.10 · complete · 2026-08-15

New `ui/report_view.py` (`ReportView`, `ReportDocument`, `render_markdown`), reached from
`ui/main_window.py`. Tests: new `tests/test_report_view.py` (24 cases), `tests/test_main_window.py`
+3. **1054 passing**, ruff, format and `mypy interview_prep_recall` clean.

**Qt was not the Windows half, for the sixth time.** T11.10 was filed "(Windows / Qt)" and the
whole of it — session list, reader, generation, export, deletion — is built and tested headless.
The export writes an ordinary file to an ordinary path; there is nothing platform-bound left in
this task. What remains Windows-only in M11 is T11.2's DPAPI cipher, which was always named
correctly.

**The task row had no acceptance criteria at all** — `T11.10 | — | (Windows / Qt)`. Rather than
inventing some, the scope came from the requirements that had logic and no surface: FR83's list,
FR78's evidence, FR80's disabled-with-a-reason, FR81's per-run confirmation, FR85's disclosure,
FR84's retention notice, FR83/FR87's deletion. 07's table now carries that list, so the next
reader is not deriving it again.

**What the surface is for, stated once.** FR78 makes every judgment carry resolvable evidence,
and until now nothing resolved it: presence evidence was a list of integers in an encrypted file.
The reader shows the utterance behind each finding and the note behind each absence. A view that
displayed conclusions alone would satisfy FR78 in storage and defeat it exactly where the user
reads it — back to an LLM's impression of an interview it did not attend.

**Three choices worth re-reading before changing them.**

* **One resolution path, through the store.** A freshly generated report is attached and then
  *re-read from disk*, not rendered from the live `Report`. Two paths diverge, and the one
  exercised least — the week-old report, which is the whole point of D-U8 — is the one that breaks.
* **`setPlainText`, never rich text (D-57).** `QTextEdit` renders HTML. This is the only string
  in the product that came from a language model.
* **Every outbound and destructive action is an injected callable.** `confirm`, `acknowledge`,
  `choose_path`, `confirm_delete` — defaulting to Qt dialogs. The requirements *live* in those
  modal windows (FR81 every run, FR85 blocking, FR83 deletion), and a surface whose modals can
  only be driven by synthesised clicks is one whose requirements are never tested.

**A stored citation can outlive what it cites**, and the finding is shown with the citation marked
unresolvable rather than dropped. Silently hiding it would change a report's contents between two
readings with nothing to explain the difference.

**Review round before push — three findings, all mine, all fixed.**

| Severity | Finding | Why it mattered |
|---|---|---|
| P1 | **FR84 had no surface anywhere.** The requirement says the 30-day default is stated at first use of the feature and *not buried in settings*; the session list is the only place a stored session is ever visible, and it said nothing. | `retention_notice()`, read from the store rather than restated, so a user who changed it is told what is true of their machine. |
| P2 | **`getattr(self.application.reports, "local_only", False)`** — FR80 failing **open**. If the attribute ever moved, the default would *enable* the button that sends an interview off the device. Same defaulted-collaborator shape as D-26. | Read straight off the generator. Same fix for the consent lookup. |
| P3 | The dialog is modeless, so FR37's switch can be flipped in Settings while it sits open, leaving an enabled Generate button. | `showEvent` re-syncs. Generation was already safe — the generator refuses and says why — but a control that looks available and is not is still a small lie. |

**`report/separation.py`'s `imported_modules` now accepts a file as well as a directory.** FR79's
wall is checked against the report package, and this new module renders generated prose from
*inside* `ui/`, next to the overlay — the one place the way around that check would be built.
Passing a file to the directory-only version globbed nothing and asserted nothing: a check that
could not fail. It now checks `ui/report_view.py` directly.

**PR #24 review — five findings, all valid. Three fixed, two raised as decisions.**

| Severity | Finding | Outcome |
|---|---|---|
| P1 | **FR84's sweep had no production caller** while the new session list told the user sessions are deleted automatically. `Application.sweep_retention` carried "no production caller yet — the entry point owns this, and there is no entry point until the UI lands"; the entry point landed in T9.6 and nobody went back. | Fixed. Called from `startup.start` after the config load and before preflight, and the deletion is **stated** — silent automatic deletion of a transcript the user was about to read is indistinguishable from data loss. |
| P2 | **Every finding rendered twice.** `_sections` builds a section body by joining its accepted findings, so the body *and* the findings printed each conclusion once bare and once above its evidence. | Fixed. Findings render once with citations; the body's remainder is kept, because FR75's truncation notice lives there and a de-duplication that swallowed it would lose a requirement. |
| P2 | **Any client exception escaped the Qt slot** — offline, rate-limited, bad key — leaving a button that did nothing. | Fixed. Caught at the UI boundary, type and message shown, recorded structurally, controls restored. |
| P1 | **Generation blocks the GUI thread** (T11.10b). | Raised, not fixed. Changes `ReportGenerator`'s contract — see 07's follow-up table. |
| P1 | **A historical session is analysed against the current context set** (T11.10c). | Raised, not fixed. A decision about stored data, not a cleanup. |

The first one is the instructive one: **my own label created the false promise.** The requirement
had no surface, I gave it one, and giving a requirement a surface is also how you find out nothing
implements it. The docstring naming the gap had been sitting there since T9.0 and was not enough —
which is the whole D-20 pattern, in the file that documents D-20.

**Follow-up T11.10a:** FR87 asks for delete-all to be signposted **at the panic surface**. The
control exists here and is named plainly, but the panic surface itself has no UI yet, so the
signpost has nowhere to live. That is a gap in FR87's coverage, not a gap in this task.

### M10 — T10.7 · complete · 2026-08-15

FR72's per-kind marking, in `ui/overlay.py`. `tests/test_overlay.py` +15 (**1027 passing**),
ruff and format clean; mypy's error count is unchanged from the pre-change baseline (49, all
pre-existing and all raised by a mypy newer than the one this tree was last checked against —
none of them in the changed code, and a stash-and-recheck confirmed the count rather than
assuming it).

**What it is.** A `KindMark` (glyph + label) per `SourceKind`, prefixed to the headline at
display time exactly as FR51's degraded `~` is, with the kind's name as the headline's tooltip.
`SnippetView` gains a `kind`, and `from_stored_note` gains a **required** `resolve_kind`.

**The design gap this task actually had, and why it was not treated as a blocker.** Both the
task table and this file said "§9b tokens are specified". They are not: §9b's token table has a
row for every state the panel can be in and **no row for source kind at all** — the one thing
T10.7 was supposed to render to spec. That is the same failure mode as D-45's contradictory
scaling table, found the same way, by trying to implement from the document rather than reading
it. It is resolved rather than escalated because the surrounding documents decide it: §9b already
requires colour never to be the only channel, PRISM §1 forbids remapping semantic dots, and every
hue on this panel is already spoken for by a *state* (FR51's rail, FR20's amber, FR14a's red,
FR12's green). Shape is the only channel left, and it is the one FR72's "without reading" wants.
Recorded as **D-55**, and §9b now carries the kind table it was missing.

**Three choices worth re-reading before changing them.**

* **`resolve_kind` is required, not defaulted.** FR72's mark is the kind of guarantee that fails
  invisibly — the panel renders, the text is right, and only the provenance is missing. A
  defaulted resolver makes that failure one omitted argument away; a defaulted *kind* would be
  worse, asserting a provenance the store never stated. Same reasoning as `from_stored_note`
  itself, which exists because `source_text` from the caller is not a guarantee.
* **The glyph is prepended at display time, never stored.** FR11's substring check has to see
  what the user wrote. Stored into the headline the mark would either fail that check or have to
  be exempted from it, and an exemption is how the guarantee ends.
* **State glyph first, then kind, then text.** How far to trust the panel is read before what
  the panel is about.

**Two review findings on the same invariant, and the second one is the interesting half.**
`SnippetView` documented "kind is `None` only for `NO_MATCH`" on the field and enforced it
nowhere.

* **Mine, before push:** a caller could mark the FR35 no-match line with a source it never came
  from — a false statement about provenance on the one view that has none, which is the class of
  defect FR11 exists to prevent, aimed at *where* text came from rather than at what it says.
* **PR #23 review, P2, valid:** the opposite direction, which I fixed only half of and then
  wrote a docstring claiming both. A directly-constructed `CONFIRMED` or `DEGRADED` view with no
  `kind` was accepted and rendered **unmarked** — FR72 quietly unmet, and invisible, because the
  panel renders and the text is right. Requiring `resolve_kind` in `from_stored_note` does not
  cover it: direct construction stays reachable from every producer.

Both are now rejected in `__post_init__` with tests. **This is the third time in this milestone
that a guarantee was written where it is read rather than where it is checked** — the field's
docstring stated the invariant, and half of it was enforced. A docstring is not an enforcement
point; that sentence should be read as a to-do every time it is written.

Two existing tests changed with it: content views now always carry a mark, so the two assertions
that pinned the headline to a fixed string assert the two prefix channels and the untouched text
instead.

**Not done, and it is the half that needs the hardware.** FR72's acceptance is a *glance test at
1 m*, and glyph coverage in the bundled Plex faces is unverified — Qt will substitute a fallback
font per glyph, which is invisible here and is exactly the sort of thing that looks wrong only on
the real surface. Both ride with T5.9 and T9.4. What is verified here is distinctness (pairwise,
over the whole set, because distinctness is not a property any one kind has), that the mark never
enters the FR11-checked strings, and that the no-match line stays unmarked and does not inherit
the previous snippet's source label.

**Follow-up T10.7a:** the shapes are learnable only by hovering the overlay. A legend in the
editor, beside the per-kind sources it already lists, is where a user would actually look. Small,
and outside FR72 as written. ✅ **Done on 2026-08-16** — legend plus a mark on every note row.

### M7 — T7.4 · complete · 2026-08-15

New `ui/checklist.py` (`TrackerChecklist`), wired into `ui/overlay.py`, fed by a new
`Application.on_tracker_update` and pushed at the panel by `ui/main_window.py`. Tests: new
`tests/test_checklist.py` (125 cases, most of them the 101-value brightness sweep),
`tests/test_app.py` +4, `tests/test_main_window.py` +4. **1012 passing**, ruff, format and
`mypy` clean.

**Run `mypy` as `python -m mypy`, not `mypy`.** The `mypy` on this container's PATH is a `uv`
tool install with its own environment: it cannot see `numpy` or `PySide6` and reports 23 errors
on a clean checkout of `main`. Twenty minutes went into "which of these did I cause" before that
was the answer. `python -m ruff` for the same reason.

#### What T7.4 closed

**FR12's checklist, docked below the bullets.** Design §9b's row: `--font-secondary` 13px,
unmarked muted, marked `--green-500` with a check glyph, max 5 rows then scroll, never
displacing the snippet. Both states carry a glyph — the marked one a check, the unmarked one a
hollow ring — so the list is readable without the colour and every row's text starts at the
same x.

**"Never displaces the snippet" is implemented as growth, and that is what makes it checkable.**
The panel's window height becomes the user's height *plus* the checklist's reservation, so the
bullets keep the space they had before the checklist existed. `geometry_settings.height` stays
the user's own value, so FR26 persists what they chose and §9b's height-driven text scaling does
not jump a size every time a point is marked. Two tests hold it: the bullets' line allowance is
unchanged when a checklist appears, and so is the rendered bullet text.

**The one place it cannot hold is FR23's 600px maximum**, where there is no room to grow and the
checklist's height comes out of the bullets' allowance instead. They elide rather than clip.
Recorded as **T7.4a** rather than hidden: it is a real limit of §9b's "grows downward *within*
the FR23 max height", and the panel is at that height only if the user dragged it there.

> **Corrected on 2026-08-16 (T7.4a).** The sentence above originally ended "and never past
> `MIN_BULLET_LINES`", which put the floor at the maximum size. It is not there: at 600px the
> allowance falls from 7 lines to 5 and the floor is never reached. It engages at the *minimum*
> size, where the measurement comes out at zero. The test written for this paragraph asserted
> `>= MIN_BULLET_LINES` against a value of 5 — a comparison that could not fail.

**The marked colour swaps at the brightness crossover.** PRISM's `--green-500` measures 8.29:1
on the darkest panel and **1.26:1** at the light band's edge, so a single value would have made
the checklist tick over invisibly for a light-band user — the same failure the degraded rail
already has a variant for. `OverlayPalette` carries both; the 101-value sweep now covers the
marked colour alongside the ink and the rails.

**FR37's switch travels with the points**, from `SessionManager` through `on_tracker_update`,
rather than being read by the widget. Two readers of one piece of state are free to disagree
about it, and the disagreement here would be a checklist that keeps ticking while the switch
reports tracking as off — the D-23 shape, in the one place the user can watch it be wrong. Off
removes the rows entirely: a frozen checklist reads as "things you have not said yet", which is
the one reading a user acts on.

#### The checklist update crosses threads (PR #22 review)

`Application.consume` runs on whichever thread the STT backend chose — the STT contract's item
7 says so in as many words: *"callbacks run on whichever thread the backend chooses… consumers
must enqueue and return."* The first wiring stored the panel's bound setter as
`on_tracker_update`, which is not enqueueing: it mutates `QWidget` state from that thread. Qt
prints `QObject::setParent: Cannot set parent, new parent is in a different thread` and the real
consequences are torn paints or a crash mid-interview.

`OverlayPanel.tracker_updated` is now the hop — a `Signal(list, bool)` connected to
`set_tracked_points`. Qt's default connection is queued across threads and direct within one, so
a backend thread's emit lands on the GUI thread and `MainWindow`'s own redraws pay nothing. The
signal is on the *panel*, not the window, so the application's reference graph still does not
reach the window.

**The same shape exists on `on_result`** and is not a live defect only because nothing Qt
consumes it yet — `MatchingPipeline._emit` runs on the stage-2 worker thread. Whoever wires the
snippet path to the panel must use a signal too; there is now one to copy.

#### Two defects found in local review, both fixed here

**A stale checklist survived a purge.** `reset_for_new_session` clears the tracker's marks and
nothing told the panel, so the next interview would have opened showing the previous one's
coverage — points the user has not made this time, presented as already covered.

**The rows were painted on nothing.** `background: transparent` on the scroll area reads
correctly and is wrong: a child widget carrying a style sheet paints its own rect, so it cleared
the panel's surface rather than revealing it, leaving the rows over whatever the video call was
showing. Every contrast figure in §9b is stated against the panel colour, so that is not the
readability the band promises. The widget is now told the surface colour along with the ink.

**The test for it passed three times before it tested anything**, which is the more useful half
of this entry. Grabbing the *child* widget renders it against its parent's palette and reports
the panel colour whether or not the child painted it. Grabbing the panel with the checklist
unshown does the same. So does grabbing it with only two rows. The difference appears only with
the panel shown, translucency off, and enough rows to scroll — and it was found by running the
assertion against a deliberately broken implementation and watching it pass. **Any test written
for a defect should be run against that defect once.** Three of these did not fail until the
fourth attempt.

### M5 — T5.4, T5.7, T5.8 · complete · 2026-08-15

`ui/overlay.py` (direct manipulation, FR22's default placement, FR23's text scaling),
`ui/indicators.py` (built out from a four-line stub), the new `ui/diagnostics_view.py`, and a
route to it from `ui/main_window.py`. Tests: `tests/test_overlay.py` +49, new
`tests/test_indicators.py` (15), new `tests/test_diagnostics_view.py` (10),
`tests/test_main_window.py` +11. **879 passing**, ruff and `mypy` clean, and the suite's *exit
code* verified across five consecutive runs — see the review round below for why that is stated
separately from the pass count.

**M5's Qt half is finished.** What is left is T5.2's `SetWindowDisplayAffinity` and T5.9's
latency harness, and both were re-tested against the standing caution above rather than
inherited: T5.2 is one `ctypes` call into `user32` that does not exist off Windows, and T5.9
measures p50/p95 on the D-U6 laptop's CPU, which is a machine and not a toolkit. Neither is a
"needs Windows" label standing in for unexamined code.

#### What each task actually closed

**T5.4 (FR22, FR23, FR27, FR55).** Drag, edge-resize and lock, plus the two things the task row
listed and the code did not have: FR22's *top-centre* default (the geometry default was 100,100)
and FR23's text scaling, which §9b specifies and nothing implemented — a fixed-font panel would
have satisfied the size range and still failed the requirement.

The manipulation logic is split from the Qt events: `begin_manipulation` / `update_manipulation`
/ `end_manipulation` take plain points, and `mousePressEvent` and friends only translate. A
frameless window has no title bar and no system grips, so this code *is* the window manager for
the panel; testing it through synthesised OS input would have left its clamping untested, which
is the half that can lose the panel off-screen.

Three findings came out of building it, all recorded as decisions:

* **D-47** — clamping the size and moving the origin independently lets a left-edge drag walk the
  panel sideways forever once the width is at its minimum. It is a *new* way to reach the state
  FR55 exists to recover from, so the origin is now recomputed from the clamped size.
* **D-46** — the lock withholds dragging and the left/top edges only. FR27 is about the panel
  wandering; a right-edge drag moves nothing.
* **D-45** — design §9b states text scaling as a formula *and* an anchor table, and they disagree
  by 1px on the bullets at the default height. The formula governs, the table's derived middle
  row was corrected in §9b, and `bullet_px(220)` is 14.

**T5.7 (FR7, FR14a, FR20, FR35).** `indicators.py` was a four-line stub. FR35's requirement is
not that any state renders but that **every state in design §7 renders distinctly**, which is a
property of the *set* — so the test drives all eleven states and asserts the renderings are
pairwise different. A per-state assertion would pass with two states painted identically, which
is the failure the requirement names.

OB-1's "no match vs broken" distinction holds structurally rather than by colour choice: nothing
matching is a **content** state on the panel, `Health.indicators()` never returns it, and no
health state can produce it. They are two signals, not two renderings of one.

FR20 is one dot per path, not a shared "something is leaving" dot — a user who has switched one
path off (FR37) has to see that one went dark and the other did not. FR14a's bar takes
`bool | None` and shows only on a known failure: before the check has run there is nothing
truthful to say, and a bar defaulting to "you are hidden" is the silent assumption of success
FR14a exists to forbid. **T5.2 still owns producing that failure**; T5.7 only renders it.

**T5.8 (FR36).** T0.3 built the buffer and its no-content guarantee; FR36 also required it to be
viewable in-app and exportable, and neither existed. New module (**D-49**), reached from the main
window — the same gap T9.2b closed for settings, where the piece existed and nothing constructed
it. The viewer re-validates nothing: the guarantee lives at `record()`, and a second filter here
would let unsafe events into the buffer and hide them from one reader.

#### Found in self-review, fixed before the push

* **The panel's style sheet was about to repaint the FR51 rail three more times.** `OverlayPanel`
  styles itself with a bare `QWidget { … border-left: 3px solid … }`, and a Qt style sheet on a
  parent applies to every widget beneath it. The panel's own labels already carried
  `border: none` for this reason; the three containers that arrived with T5.7 did not, so each
  indicator group would have drawn its own copy of the state rail. Every container now states its
  own background and border, and a test holds it.
* **A drag was doing a full restyle per mouse-move** (**D-48**), rebuilding a
  `QGraphicsDropShadowEffect` on four labels at pointer rate on the surface NFR3 measures. Drags
  now take a position-only path; resizes still restyle, and both are tested.
* **Elision is the one place a rendered string is not byte-identical to the note** (**D-50**).
  FR23 permits it and FR11 forbids anything the user did not write, and the two only coexist
  because the operation is truncate-and-append: what remains is a prefix, and the ellipsis is
  fixed product copy. That is now asserted, not described — a middle-elide added later would look
  like a cosmetic improvement and would quietly end the guarantee.

#### Review round on PR #21 — three findings, all correct, all fixed

An automated review made three P2 findings. Two of them contradicted a "done" claim above, and
the correction is recorded rather than quietly absorbed.

**1 & 2 — `set_locked` and `reset_geometry` had no production caller.** Both existed only as
methods. FR27 asks for a *toggle* and FR55 for a *control*, and a method is neither. Worse for
FR55 specifically: the case it exists for is a panel the user cannot reach, so a button on that
panel is not a recovery route.

`MainWindow` now owns the overlay and carries three controls: **Reset overlay position** (FR55),
**Lock overlay position** (FR27) and a **Show overlay** toggle so the user can see what they are
adjusting. `main_window.py`'s own docstring predicted this — *"when M5 lands, the overlay becomes
the session surface and this stays the readiness-and-settings shell around it"* — so it was the
plan's instruction, not new scope. The panel's `on_geometry_changed` now has a production
subscriber, which closes the first deferred item from the previous round.

**3 — elision applied at every panel height.** Correct, and the deeper problem was in how §9b was
read. See **D-51**: the two-line allowance is a floor, and the real allowance is measured from
the space the panel has.

#### Three defects found while fixing those, none of them in the review

* **`MainWindow` was building its own `QSettings`** (**D-52**). Every test that constructed a
  window would have reached the user's real registry, and the T0.4 allowlist guard cannot see it
  — `QSettings` writes through Qt's C++ layer, not Python's `open`. The store is injected now,
  and required, so the one production call site is the only place it is chosen.
* **Two segfaults from Qt ownership** (**D-53**). A parentless top-level widget destroyed through
  a Python reference, and a window→panel→bound-method→window cycle left to the cyclic collector.
  Both let Qt destroy objects in an order nobody chose. The cycle killed the interpreter only
  after about twenty windows, so it surfaced as an unrelated test crashing on construction —
  which is why the diagnosis took several passes down the wrong path.
* **The `qapp` fixture never tore down** (**D-54**). Six modules each had their own copy and none
  closed anything, so every widget survived to interpreter shutdown. The suite reported 879
  passing and the process then died with 139 on roughly two runs in three. On CI that is a red
  build with a green test report. One fixture in `conftest.py` now closes and deletes top-level
  widgets while the application is still alive; five consecutive full runs exit 0.

The last one is worth keeping in mind: **an exit-time crash does not appear in the test report.**
Checking `pytest`'s exit code, not its summary line, is what caught it.

#### Deferred, with reasons

* **The overlay renders no session content.** It is constructed, positioned, persisted and
  controllable, but nothing feeds it snippets or health — capture is M1 and matching needs a
  running session. The geometry half of the wiring is done; the content half belongs to whichever
  task first has a session. **Recorded as a follow-up, not as done.**
* **T5.9's harness is not stubbed.** Writing a latency harness that cannot run measures nothing
  and would report a number from this container's CPU as if it were the D-U6 laptop's.

#### The environment note, re-tested

Qt again ran headless here without incident, including `QFontMetrics` text measurement, graphics
effects and `QTableWidget`. Worth stating because font metrics are the one part of this that
plausibly *could* have differed under `offscreen` — they do not; the platform plugin still
resolves a real font. The elision tests assert relative properties (fewer characters, at most two
lines, a prefix of the source) rather than pixel counts, so they hold on CI's Windows runner where
the font stack is different.

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
- **This project's recurring defect is a test that passes while the guarantee is broken.** Twelve
  instances so far, the latest being T7.4's rendered-surface check, which reported the panel's
  colour whether or not the checklist painted it — three separate versions of it passed against a
  deliberately broken implementation before the fourth failed. **Run any test written for a defect
  against that defect once.** The instance before it was an injected `DiagnosticRing` silently
  replaced by an orphan because an empty ring is falsy (D-26). Four early instances: the PRD's absolute no-disk claim, the zeroed-`bytearray` purge assertion, the
  `weakref`-on-`str` sweep, and D-13 above. When writing a test for a privacy or correctness
  guarantee, verify the property, not the claim.
- **Fixtures are the long pole and only the user can make them.** Real prep notes, two or three
  recorded mock interviews, and hand-labelled utterances. T4.7's gate and the matching regression
  suite both depend on them, and nothing in the code substitutes.
