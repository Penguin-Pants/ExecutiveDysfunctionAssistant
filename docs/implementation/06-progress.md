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
| **M2 — STT interface & local backend** | 🟡 Partly doable here | Interface + assembler + conformance suite can be written on Linux; `faster-whisper` and the AS-1 gate need Windows |
| **M3 — Notes store & indexing** | ⏭ Next | Non-UI parts fully buildable here |
| **M4 — Matching pipeline** | ⬜ Not started | Buildable here except the T4.7 measurement, which needs real fixtures |
| **M5–M9** | ⬜ Not started | Mostly Windows/UI |

**Next action:** implement M3 tasks T3.1–T3.6 (model, store, schema guard, export, importer, index).

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

**Python version:** the container has 3.11; the spec pins **3.12** for the Windows build. Code is
written to run on both and `target-version` is set to `py311`, so nothing here depends on 3.12
syntax. CI runs 3.12 on `windows-latest`, which is the version that actually ships.

---

## Log

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
