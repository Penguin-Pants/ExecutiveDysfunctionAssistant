# Implementation Documents

Read in order. Each builds on the one before, and later documents cite earlier IDs rather than
restating them — so a change in one place propagates by reference, not by copy.

| # | Document | Answers |
|---|---|---|
| 00 | [Decisions & Assumptions](./00-decisions-and-assumptions.md) | What was ambiguous, what we chose, what we're assuming, and what breaks if the assumption is wrong |
| 01 | [Requirements](./01-requirements.md) | What the system must do, each with an observable pass condition |
| 02 | [Technical Design](./02-technical-design.md) | How it is built: components, concurrency, STT contract, data model, state machine |
| 03 | [Tasks](./03-tasks.md) | The work, in dependency order, with acceptance criteria |
| 04 | [Test Strategy](./04-test-strategy.md) | How each guarantee is verified, including the ones that resist automation |
| 05 | [Traceability](./05-traceability.md) | Requirement → design → task → test, with no gaps |

**Upstream sources:** [product plan](../interviewpreprecallprd.md) ·
[safety review](../build-plan-safety-review.md)

## ID scheme

| Prefix | Meaning |
|---|---|
| `FR` / `NFR` | Requirement. FR1–27 from the PRD, FR28–40 from the safety review's amendments, FR41+ derived while closing gaps. |
| `D-U` | Decision that required the user. Do not reverse without asking. |
| `D-` | Engineering decision. Reversible; the cost is recorded. |
| `AS-` | Assumption. Unverified, with a named milestone that verifies it. |
| `OQ-` | Open question. Deliberately unresolved, with a revisit point. |
| `T` | Task. |
| `A-` | Amendment from the safety review, retained so review findings stay traceable. |
| `US-` | User story from the PRD §8. Referenced for intent; not itself a requirement — every `US-` that survived is realised by one or more `FR`. |
| `DI-` `BC-` `RB-` `RC-` `OB-` | Safety-review finding categories: data integrity, backwards compatibility, rollback, race conditions, observability. Cited so each requirement traces back to the finding that motivated it. |

## Three gates that can change the plan

These are measurements, not checkboxes. Each answers an open risk the PRD's own §12 raised, and
a bad number changes the architecture rather than being waived:

1. **T1.2** — dual-stream capture stable for 60 min? Falsifies **AS-2**.
2. **T2.4** — local STT p95 < **900 ms inference tail** (design §9a's STT slice, not the whole NFR1 budget), CPU-only on the D-U6 laptop? Falsifies **AS-1**; inverts FR18.
3. **T4.7** — does the LLM stage beat the local prefilter? Answers **OQ-1**; decides whether the
   hard internet dependency stays.

## Where the highest risk sits

From the safety review, unchanged by the planning work: **the user's prep notes are the only
irreplaceable asset in the system.** That is why notes durability (M3) precedes the overlay (M5),
and why FR28's crash-during-save test is a hard acceptance criterion rather than a nice-to-have.
