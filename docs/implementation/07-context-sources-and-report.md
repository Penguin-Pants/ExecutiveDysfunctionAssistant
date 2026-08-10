# Typed Context Sources & Post-Interview Report

**Status:** specified, not yet built. Milestones **M10** and **M11**.
**Origin:** user request, 2026-08-10, with three product decisions taken via D-U8/D-U9/D-U10 below.

This document owns two features. They are separable and are deliberately separated: M10 is
additive and low-risk, M11 reverses a v1 non-goal and materially changes the privacy posture.
**M10 does not depend on M11.** If M11 is abandoned, nothing in M10 needs revisiting.

---

## 0. What this changes about the product's core promise

Read this section before the requirements, because two sentences elsewhere in the plan stop
being true here and the reason matters more than the edit.

**"Nothing the user says or hears is written to disk" is no longer true.** It was the strongest
claim this product made. D-U8 trades it for a persisted transcript so reports can be regenerated
and exact wording re-read. The claim is therefore rewritten (FR16, below) rather than reinterpreted
— an unchanged FR16 next to a transcript-writing feature is worse than either choice on its own,
because the next person to read it will build against a guarantee the code does not keep.

**The overlay's retrieval-only guarantee is untouched, and must stay that way.** Everything the
overlay renders is structurally incapable of being generated: FR10's forced `tool_choice` returns
a note ID from an enum, and FR42 asserts every rendered bullet is a byte-exact substring of a
stored source. The report is generated prose. These are two different output surfaces with two
different guarantees, and the danger is not the report — it is that the report's existence gets
used later to argue the overlay path can relax. FR79 exists to make that argument impossible to
implement by accident.

**A third party's words now persist.** The interviewer did not install this software. Under D-U9
the report also characterizes them by name. That is a real obligation, not a footnote, and it
drives FR80–FR84 (encryption, retention, deletion, disclosure re-acknowledgement).

---

## 1. Product decisions taken

| ID | Decision | Consequence accepted |
|---|---|---|
| **D-U8** | **The raw transcript is persisted, not dropped after report generation.** | FR16 is rewritten. Encryption at rest, a session list, per-session delete and a retention default all become v1-of-this-feature requirements rather than niceties. Panic clear gains a much larger blast radius question (D-32). |
| **D-U9** | **The report analyzes the full meeting, both sides**, including reading the interviewer's pushback and reactions. | The saved artifact characterizes a specific named person. FR63's disclosure is no longer sufficient and must be re-acknowledged (**FR85**), not inherited. |
| **D-U10** | **All four rubric dimensions**: prep-note coverage, JD fit, resume utilisation, and general interview craft. | The report needs every context source at generation time, so M11 hard-depends on M10. A report generated without a JD loaded must say so rather than silently omitting that section (FR77). |

---

## 2. M10 — Typed context sources

### Model

Five kinds, one shared chunk type. The existing `Note` gains a `kind`; `NoteSet` becomes a
`ContextSet` holding documents of all five kinds. Reusing the chunk type is deliberate — the
embedding index, prefilter and stage-2 selector then need a category dimension and nothing else.

```
SourceKind = COMPANY | ROLE | INTERVIEWER | PREP | RESUME
```

| ID | Requirement | Verification |
|---|---|---|
| **FR66** | A context set holds documents of five kinds — company, role (job description), interviewer, prep notes, resume — each independently importable, editable and removable without touching the others. | Import all five; delete one; assert the other four are byte-identical and the set still loads. |
| **FR67** | Every chunk carries its `kind`, and `kind` is immutable after creation. Re-classifying a chunk means deleting and re-importing it. | Assert `kind` is on every chunk; assert mutation raises. |
| **FR68** | **The stage-2 candidate enum is built per kind, not globally**: at most 2 candidates per kind, merged and truncated to FR48's cap of 5. | Load 200 chunks weighted heavily toward one kind; assert no single kind supplies more than 2 enum members. |
| **FR69** | Each kind carries its own τ_floor offset from the global control (FR52), so a job description does not have to clear the same bar as a prep note to be considered. | Change the global control; assert every kind's effective threshold moves and their relative offsets are preserved. |
| **FR70** | **Only `PREP` and `RESUME` chunks are eligible as tracked talking points** (FR12). A job-description requirement is not something the user "covers" by speaking. | Assert `track_progress` cannot be set on a chunk of any other kind. |
| **FR71** | The stage-2 prompt labels each candidate with its kind, so the selector distinguishes "a thing I planned to say" from "a fact about the company". | Assert the kind label is present for every candidate on every request. |
| **FR72** | The overlay marks which kind a rendered snippet came from, distinguishably at a glance without reading (design §9b tokens). | Assert distinct styling per kind; glance test at 1 m. |
| **FR73** | A context set is complete with **any** subset of the five kinds present. No kind is mandatory, and absent kinds degrade matching rather than blocking a session. | Start a session with only prep notes; assert preflight passes and matching runs. |

### Migration — schema v1 → v2

**T10.1 and T10.2 as first drafted were destructive to existing installations.** Saved note files
are schema v1 and carry no `kind`; the store treats an unrecognised or malformed file as corruption
and routes it to recovery (FR44), and recovery would find every backup equally unreadable. A user
upgrading would open the app to find their prep notes gone — the exact catastrophe the whole of M3
was built to prevent, reintroduced by a feature that never mentions the notes store.

| ID | Requirement | Verification |
|---|---|---|
| **FR73a** | Loading a **schema v1** note set migrates it to v2 in memory, mapping every note to `PREP` and **preserving note IDs, order, bullets, tags and `track_progress` exactly**. IDs must survive because the embedding cache is keyed on them (FR34) and changing them silently invalidates every vector. | Load a captured real v1 file; assert every field round-trips and every ID is unchanged. |
| **FR73b** | Migration writes v2 **only through the existing atomic write and rotation path** (FR43), so a crash mid-migration leaves the v1 file intact and loadable by the old build. | SIGKILL mid-migration ×10; assert a readable note set every time. |
| **FR73c** | The pre-migration file is retained as a backup generation and the migration is stated to the user, not silent. | Assert the v1 file survives in the backup set; assert the notice appears. |

`PREP` is the correct target because it is the only kind that preserves existing behaviour: v1 notes
were trackable talking points, and `PREP` is one of the two kinds FR70 still permits to be tracked.
Mapping them anywhere else would silently disable the progress tracker for every existing user.

### The FR42 wording change

FR42 currently says bullets are **user-authored** verbatim strings. A job description is
user-*supplied* and not user-*authored*, so the JD kind would be born in violation of the wording
while fully satisfying the actual property. FR42 is amended to **"verbatim from a stored source"**,
and its test — every rendered bullet is a byte-exact substring of the stored chunk — is unchanged.
The guarantee was never about authorship; it was about the absence of generation.

---

## 3. M11 — Post-interview report

### Reversal notice

Design §11 lists "any post-call artifact" as out of scope for v1, per the PRD's non-goals.
D-U8/D-U9 reverse that deliberately. §11 is amended to point here rather than left contradicting.

### The transcript record

| ID | Requirement | Verification |
|---|---|---|
| **FR74** | A session accumulates every finalized utterance — both streams — with speaker, start and end times, in order. Interim results never enter it. | Feed a scripted session; assert the record matches expected utterance boundaries and contains no interim text. |
| **FR75** | **The record is bounded at 4 hours or 5,000 utterances, whichever comes first**, and truncation is stated in the report rather than silent. | Feed past both bounds; assert truncation and an explicit notice in the output. |
| **FR76** | The record is a deliberate, documented exception to FR33's "nothing grows with session length". It is the only such exception, and it is bounded by FR75. | Assert the bound holds; assert no *other* component grows (existing FR33 tests). |

FR76 is not bookkeeping. FR33 exists because an unbounded buffer in a 60-minute session is how
this app would die mid-interview, and a feature that needs an ever-growing structure has to say so
loudly and cap it, or the next reviewer is right to call it a regression.

### Generation

| ID | Requirement | Verification |
|---|---|---|
| **FR77** | The report covers four sections, one per D-U10 dimension: prep-note coverage, job-description fit, resume utilisation, interview craft — plus explicit "what went well" and "what to do differently" summaries. **A section whose context source was absent says so explicitly and is not silently omitted.** | Generate with each source missing in turn; assert the section is present and states the absence. |
| **FR78** | **Every judgment in the report carries resolvable evidence**, of exactly one of two kinds. **Presence** evidence cites utterance indices into the record. **Absence** evidence — "you never made this point" — cites the source chunk the point was expected from, and is valid only if the whole record was scanned and no utterance clears τ_track against that chunk. A finding with neither is rejected before the report is shown. | Assert every finding resolves. Inject an unevidenced finding and assert rejection. Inject an absence finding **contradicted** by an utterance above τ_track and assert rejection. |
| **FR78a** | **Absence findings are adjudicated by the same mechanism as the live tracker (FR12), not a second opinion.** If the tracker marked a point covered, the report may not claim it was missed, and vice versa. | Run a session; assert the report's missed-points set is exactly the tracker's unmarked trackable set. |
| **FR79** | **The report path may not reach the overlay renderer.** Report text is never eligible for on-screen snippet rendering, structurally and not by convention. | Assert the overlay renderer rejects report-sourced content; assert no import path exists from the report module to the overlay snippet API. |
| **FR80** | Report generation requires cloud LLM access and is **unavailable in local-only mode** (FR37), stated as unavailable rather than silently producing nothing. | Toggle local-only; assert the action is disabled with a reason shown. |
| **FR81** | Generation sends the full record to the LLM in one call. This is announced before it happens, with the size, and requires confirmation on every run — not a remembered preference. | Assert the confirmation appears every time; assert nothing is sent on decline. |
| **FR81a** | **The FR20 egress indicator is lit for the entire duration of the report upload**, on the LLM path, and cleared only after the call completes or fails. | Assert the indicator is lit across the call and dark after; assert a failed call does not leave it lit. |

FR78 is the discipline that makes this feature trustworthy. The overlay cannot fabricate because
it cannot generate. The report *must* generate, so the equivalent protection is that every claim
is anchored. Without it the report is an LLM's impression of an interview it did not attend,
delivered to someone who will believe it about themselves.

**Absence needed its own evidence kind, and the first draft of FR78 did not have one.** Two of the
four rubric dimensions produce their most valuable findings by *absence* — the prep point you meant
to make and never did, the resume experience that would have answered a question better than what
you said. Those rest on nothing having been uttered, so a rule demanding an utterance index forces
the generator to either drop the best findings or fabricate a citation. Requiring a scanned record
and a named source chunk keeps the claim falsifiable, which is the actual goal.

**FR78a exists so coverage has one adjudicator.** The live tracker already decides "did they say
this", at τ_track, from the mic stream only (FR56). A report that re-derives the same judgment from
the transcript will eventually disagree with the checklist the user watched during the interview —
and there is no principled way for the user to know which to believe. One mechanism, two surfaces.

### Storage, retention, deletion

| ID | Requirement | Verification |
|---|---|---|
| **FR82** | Transcripts and reports are encrypted at rest with a key bound to the current Windows user (DPAPI). A copied file does not open on another machine or under another account. | Write, copy to a second profile, assert decryption fails. |
| **FR83** | A session list shows every stored session with date, role and size, and supports per-session delete and delete-all. Deletion removes transcript, report and index entry together. | Delete one session; assert all three artifacts are gone and the rest are intact. |
| **FR84** | **Sessions auto-delete after 30 days by default**, user-configurable including "never". The default is stated at first use of the feature, not buried in settings. | Age a session past the window; assert deletion on next launch; assert "never" suppresses it. |
| **FR85** | The FR63 consent disclosure is **re-shown and re-acknowledged** when this feature is first enabled, covering the persisted verbatim record of another party. A prior FR63 acknowledgement does not carry over. | Acknowledge FR63, enable the feature, assert a fresh disclosure blocks until acknowledged. |

FR85 matters because the original acknowledgement was to a weaker statement. Treating consent to
"audio is intercepted in memory" as consent to "the other person's words are stored on my disk for
30 days and analyzed by a third-party model" would be the same defect this project keeps producing
— a guarantee whose test passes while the property is broken — applied to a person instead of a buffer.

### Panic clear (D-32)

| ID | Requirement | Verification |
|---|---|---|
| ~~**FR86**~~ | **Moot under D-U11.** The panic control no longer destroys anything, so it has no blast radius to scope. Restore this requirement only if the destructive behaviour comes off hold. | — |
| **FR87** | **FR83's delete-all is the only route to destroying stored sessions**, and — since the panic control no longer destroys anything (D-U11) — the one a user reaching for panic actually needs. The panic surface says so. | Assert the affordance is present at the panic surface. |

**Resolved by D-U11, not by answering the question.** The user put the destructive panic path on
hold: the control now only pauses. A control that destroys nothing has no blast radius to argue
about, so FR86 is moot and OQ-7 is closed unresolved rather than decided.

Worth keeping the reasoning, because it returns intact if the hold lifts: panic clear is
single-action with no confirmation (FR60), so someone hitting it during interview #4 and thereby
destroying #1–3 has suffered a catastrophic, irreversible surprise; against that, a user hitting
panic plausibly means "remove this from my machine". FR87 survives regardless and gets *more*
important under the hold — with panic now inert, delete-all is the only thing that destroys
anything, and it is what a user reaching for panic actually wants.

---

## 4. Tasks

### M10 — Typed context sources

| Task | Requirements | Acceptance |
|---|---|---|
| **T10.1** `SourceKind` + `kind` on the chunk model, immutable | FR66, FR67 | Round-trips through store and index; mutation raises |
| **T10.2** `ContextSet` replacing `NoteSet`, five documents, independent lifecycle | FR66, FR73 | Delete one kind, others byte-identical; any subset loads |
| **T10.2a** **Schema v1 → v2 migration**, notes mapped to `PREP`, IDs preserved, atomic, backed up | FR73a, FR73b, FR73c | Real v1 file round-trips with IDs unchanged; SIGKILL mid-migration ×10 leaves a readable set; v1 retained as a backup generation |
| **T10.3** Per-kind importers (JD paste, resume `.md`, interviewer notes) | FR66 | Each proposes verbatim chunks for review (FR2) |
| **T10.4** Per-kind prefilter with the 2-per-kind cap | FR68, FR69 | 200 skewed chunks, no kind exceeds 2 enum members |
| **T10.5** Kind labels in the stage-2 prompt | FR71 | Label present on every candidate, every request |
| **T10.6** Tracker restricted to PREP + RESUME | FR70 | `track_progress` on other kinds raises |
| **T10.7** Overlay per-kind visual marking | FR72 | Distinct tokens; glance test **(Windows)** |

### M11 — Post-interview report

| Task | Requirements | Acceptance |
|---|---|---|
| **T11.1** `SessionRecord` — bounded, ordered, finals-only | FR74, FR75, FR76 | Boundary and truncation tests |
| **T11.2** Encrypted store, session list, delete, delete-all | FR82, FR83 | Cross-account decryption fails **(Windows for DPAPI)** |
| **T11.3** Retention sweep, 30-day default | FR84 | Aged session deleted on launch; "never" suppresses |
| **T11.4** Report generator, four sections + summaries | FR77, FR80 | Each source absent in turn → section states absence |
| **T11.5** Evidence binding — presence and absence kinds — and rejection of unevidenced or contradicted findings | FR78, FR78a | Unevidenced finding rejected; absence finding contradicted above τ_track rejected; missed-points set equals the tracker's |
| **T11.6** Structural separation from the overlay path | FR79 | Renderer rejects report content; no import path |
| **T11.7** Pre-send confirmation with size, every run, **and ownership of the FR20 egress indicator across the upload** | FR81, FR81a | Decline sends nothing; preference is not remembered; indicator lit for the whole call and dark after, including on failure |
| **T11.8** Consent re-acknowledgement on first enable | FR85 | Fresh disclosure blocks despite prior FR63 ack |
| **T11.9** Signposted delete-all at the panic surface | FR87 | Affordance present. *(Scoping half dropped — D-U11 leaves panic with nothing to scope.)* |
| **T11.10** Report view and export | — | **(Windows / Qt)** |

### Buildable on Linux now

T10.1–T10.2a, T10.3–T10.6, T11.1, T11.3–T11.9. **T10.7 and T11.10 are Qt. T11.2's DPAPI binding is Windows**,
though the store's envelope, listing and deletion logic are testable here behind the same
`CredentialBackend`-style Protocol already used for the credential store.

Naming the blocked *tasks* rather than the milestones is deliberate — twice now a milestone-level
"Windows" label in the progress doc hid work that had no platform dependency at all.

---

## 5. Amendments required in existing documents

Not optional, and not deferrable to "when we build it" — a plan that contradicts itself is the
failure mode this documentation set exists to prevent.

| Document | Change |
|---|---|
| `01-requirements.md` **FR16** | Rewrite. Audio is still never written. Transcripts and reports are written **only** to the encrypted session store, and only when the feature is enabled. |
| `01-requirements.md` **FR42** | "user-authored" → "verbatim from a stored source". Test unchanged. |
| `01-requirements.md` **FR58** | Add: panic clear also spares previously saved sessions (FR86). |
| `01-requirements.md` **FR63** | Add pointer to FR85's re-acknowledgement. |
| `02-technical-design.md` **§11** | "any post-call artifact" is no longer out of scope; point here. |
| `02-technical-design.md` **§4** | Data model gains `SourceKind` and `ContextSet`. |
| `00-decisions-and-assumptions.md` | D-U8/D-U9/D-U10 and D-29–D-32 recorded. |

---

## 6. Open questions

| ID | Question | Needs |
|---|---|---|
| ~~**OQ-7**~~ | **Closed unresolved by D-U11.** Panic no longer destroys anything, so the question has no subject. Reopen with the destructive path. | — |
| **OQ-8** | Does the report's quality justify a full-transcript call per session at Haiku rates on a 60-minute interview? Cost is bounded and small, but unmeasured. | Measure during T11.4, alongside T9.5 |
| **OQ-9** | Should the interviewer kind support fetching from a public profile URL, or stay paste-only? Paste-only for now; fetching adds a network path and a scraping dependency to a product whose selling point is that little leaves the device. | Post-M10 |
