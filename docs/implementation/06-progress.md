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
| **M5–M9** | ⬜ Not started | Mostly Windows/UI |

**Next action:** nothing further is buildable on Linux without new inputs. The remaining work
splits cleanly:

- **Needs the Windows machine:** M1 (AS-2 gate), T2.2 + T2.4 (AS-1 gate), M5 overlay, M6 session
  lifecycle, M7 tracker device tests, M8 cloud backends, M9 packaging.
- **Needs the user's fixtures:** T4.7, the OQ-1 gate.
- **Buildable here if desired:** M6's session state machine and health model are pure logic and
  could be written ahead of the Windows work, at the cost of being untestable end-to-end.

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
- **This project's recurring defect is a test that passes while the guarantee is broken.** Four
  instances so far: the PRD's absolute no-disk claim, the zeroed-`bytearray` purge assertion, the
  `weakref`-on-`str` sweep, and D-13 above. When writing a test for a privacy or correctness
  guarantee, verify the property, not the claim.
- **Fixtures are the long pole and only the user can make them.** Real prep notes, two or three
  recorded mock interviews, and hand-labelled utterances. T4.7's gate and the matching regression
  suite both depend on them, and nothing in the code substitutes.
