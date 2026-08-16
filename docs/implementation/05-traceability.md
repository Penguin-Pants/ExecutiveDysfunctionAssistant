# Traceability Matrix

Every v1 requirement resolves to a design section, a task, and a test. A row with a gap in any
column is a requirement nobody will build or verify.

**Legend:** D§ = [technical design](./02-technical-design.md) section · T = [task](./03-tasks.md) ·
TS§ = [test strategy](./04-test-strategy.md) section

| Req | Origin | Design | Task | Test |
|---|---|---|---|---|
| FR1a | PRD | D§4 | T3.5 | Unit + fixture `notes/*` |
| FR2 | PRD | D§4 | T3.5 | Unit + fixture |
| FR3 | PRD | D§4 | T3.7 | Unit |
| FR4 | PRD | D§4 | T3.7 | Unit |
| FR5 | PRD | D§1 | T1.1 | Manual × 3 apps |
| FR6 | PRD (superseded by D-U2) | D§1, D§8 | T1.2 | Soak, TS§4 |
| FR7 | PRD | D§6, D§9b | T6.1, T5.7 ✅ | Unit (no thread in IDLE) + chip state |
| FR8 | PRD | D§1 | T1.3, T2.2 | Unit |
| FR9 | PRD | D§5 | T4.1 ✅, T4.2 ✅ | Integration |
| FR10 | PRD | D§5 | T4.2 | Unit (request shape) |
| FR11 | PRD | **D§9b**, D-5 | T5.1 | Unit (verbatim substring) + manual |
| FR12 | PRD (v1 per D-U1) | D§1, D§5 (τ_track) | T7.1, T7.4 | Integration |
| FR13 | PRD | D§9b | T5.5 | Unit |
| FR14 | PRD | D§1 | T5.2 | **Manual 6-way matrix**, TS§3 |
| FR14a | Review A15 | D§7, D§9 | T5.2, T5.7 ✅ | Unit (stubbed failure). T5.7 renders the warning bar from `capture_excluded`; T5.2 supplies the failure it renders |
| FR15 | PRD | D§6 | T6.2 | Audio-zeroing + reference-sweep, TS§3 |
| FR16 | PRD (rewritten, review A3) | D§4 | T6.4, T9.4 | **ProcMon allowlist**, TS§3 |
| FR17 | PRD | **D§2** | T2.1 | Conformance suite |
| FR18 | PRD | D§2 | T2.2, T8.1–2 | Config test |
| FR19 | PRD | D§4 | **T0.5**, T8.3 | Grep test |
| FR20 | PRD | D§7, D§9b | T5.7 ✅, T8.5 ✅ | Unit per egress path |
| FR21 | PRD | D§9 | T8.4 | Fault injection |
| FR22–27 | PRD | **D§9b** | T5.4 ✅, T5.4a ✅, T5.5 ✅, T5.6 ✅ | Unit |
| FR65 | D-U7a | **D§9b** | T5.4 | **Sweep the full control; every reachable setting clears 4.5:1** |
| FR28 | Review A1 | D§4 | T3.2 | **`taskkill` × 10**, TS§3 |
| FR29 | Review A1 | D§4 | T3.2, **T3.9** | Unit + restore UI |
| FR30 | Review A1 | D§4 | T3.4 | Round-trip |
| FR31 | Review A1 | D§4 | T3.3 | Unit |
| FR32 | Review A6 (corrected) | **D§5** | T4.3 ✅ | **Out-of-order test**, TS§3 |
| FR33 | Review A7 | D§8 | T6.6 | Saturation + soak, TS§3 |
| FR34 | Review A10 | D§4 | T3.6 | Unit |
| FR35 | Review A11 | **D§7** | T5.7 ✅ | Pairwise-distinctness over every D§7 state |
| FR36 | Review A12 | D§1 | T0.3 ✅, **T5.8** ✅ | Content-leak grep, TS§3 |
| FR37 | Review A13 | D§9 | T6.7, T9.2, T9.2b | Integration |
| FR38 | Review A14 | **D§6 (classification table)** | T6.5, T9.6 | Unit per precondition |
| FR39a | Review A16 | D§9 | T1.4 | Manual device switch |
| FR39b | Review-B C6 | D§9 | T1.4, T6.6 | Device-loss pause + auto-resume |
| FR40 | Review A18 | D§5 | T4.5 ✅ | Fault injection |
| FR41 | New (BC-2) | D§4 | T3.1 | Unit |
| FR42 | New (D-5) | D§4 | T3.5, T5.1 | Substring assertion |
| FR43 | New (US-A3) | D§4 | T3.1, **T3.8** | Unit |
| FR44 | New (DI-1) | D§4 | T3.3, **T3.9** | Corrupt fixture + the offer it routes to |
| FR45 | New (RC-1) | D§8 | T1.3 | Callback timing |
| FR46 | New (D-4) | **D§3** | T2.3 ✅ | Fixture boundaries |
| FR47 | New (D-2) | D§2 | T2.2 | Conformance |
| FR48 | Review A5 | D§5 | T4.2 ✅ | Enum size, 200 notes |
| FR49 | D-U3 | D§5 | T4.4 ✅ | Both branches |
| FR50 | US-D2 | D§5, D§7 | T4.1 ✅, T5.7 | Unrelated-speech test |
| FR51 | D-U3 | **D§9b** | T5.3 | Manual glance + non-colour channel |
| FR52 | US-D3 | D§5 | T9.2, T9.2a | Unit + Qt (offscreen) |
| FR53 | D-10 | D§1 | T4.6 ✅ | Unit |
| FR54 | New (FR13 gap) | D§5 | T5.5 | Unit |
| FR55 | Review A22 | D§1 | T5.4 ✅ | Off-screen recovery |
| FR56 | US-G2 | D§1 | T7.1 | **Loopback-must-not-mark**, with a positive control |
| FR57 | D-8 | D§1, **D§5a** | T7.2 (blocked), **T7.3 done** | Both directions of arrival; interviewer span proven still to match |
| FR58 | Review A2 | **D§6** | T6.3 | SHA before/after |
| FR59 | Review A2 | D§6 | T6.3 | Late-response test, **on session end** (reassigned by D-U11) |
| FR60 | New (DI-3) | D§4 | T3.7, T3.8 | Unit |
| FR61 | Review RB-2 | D§9 | T6.6 | Kill worker × 2 |
| FR62 | Review RB-2 | D§9 | T6.6 | Manual lock/unlock |
| FR63 | Review A19 | D§4 | T9.1, T9.1a, T9.6 | Unit + Qt (offscreen) |
| ~~FR64~~ | D-U5 | **D§6** | ~~T6.3~~ | *Superseded by FR64a (D-U11)* |
| FR64a | D-U11 | **D§6** | T6.3a | Panic pauses; no purge hook fires |
| NFR1 | PRD §7 | **D§9a** | **T2.4** | Per-stage latency harness |
| NFR2 | PRD §7 | D§10 | T9.4 | CPU-only run, CUDA disabled |
| NFR7 | D-U6 | D§10 | T2.4 | Recorded separately from the AS-1 gate |
| NFR3 | PRD §7 | D§8 | T5.1 | Frame-time measurement |
| NFR4 | D-U4 | D§10 | T6.5 | Build check |
| NFR5 | Review RC-2 | D§8 | T6.6 | 60-min soak |
| NFR6 | PRD §7 | D§5 | T4.7 | Token/call count |

## Deferred — specified, not built in v1

| Req | Reason | Revisit |
|---|---|---|
| FR1b (`.docx`) | D-U1 | Post-v1 |
| OQ-4 (local matching model) | Depends on OQ-1's answer | After T4.7 |
| Acoustic echo cancellation | D-8 warns instead | After OQ-3 |
| Diarization | AS-5 accepts the limitation | Post-v1 |

## Gates

| Gate | Task | Falsifies | If it fails |
|---|---|---|---|
| Dual-stream 60-min stability | T1.2 | AS-2 | Capture library decision reopens before anything is built on it |
| Local STT p95 < 900 ms inference tail, **CPU-only on the D-U6 laptop** | T2.4 | AS-1 | Local cannot be the default; M8 promoted ahead of M5; FR18 inverts |
| Stage-2 beats stage-1 | T4.7 | OQ-1 | The hard internet dependency is reconsidered before it is baked into the UX |
