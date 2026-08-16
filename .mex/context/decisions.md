---
name: decisions
description: Key architectural and technical decisions with reasoning. Load when making design choices or understanding why something is built a certain way.
triggers:
  - "why do we"
  - "why is it"
  - "decision"
  - "alternative"
  - "we chose"
edges:
  - target: context/architecture.md
    condition: when a decision relates to system structure
  - target: context/stack.md
    condition: when a decision relates to technology choice
  - target: patterns/add-stt-backend.md
    condition: when understanding why STT is abstracted via Protocol injection
  - target: patterns/track-session-progress.md
    condition: when understanding why file-based storage was chosen
# Decisions usually ground sparsely; add only symbols that implement the decision.
# Entry shape: { node: "function:<tier-1-id>", fingerprint: "mh:64:<hex>" }
grounds_to: []
last_updated: 2026-08-16
---

# Decisions

<!-- If a decision names its concrete implementation point, link it as below;
     do not anchor vague concepts:
```markdown
[`someFunction()`](mex://function:<tier-1-id>)
```
-->

<!-- HOW TO USE THIS FILE:
     Each decision follows the format below.
     When a decision changes: DO NOT delete the old entry.
     Mark it as superseded, add the new entry above it.
     The history must be preserved — this is the event clock. -->

## Decision Log

### Local-first speech-to-text with cloud fallback
**Date:** 2024-06-01 (from git history: initial architecture)
**Status:** Active
**Decision:** Use faster-whisper for local transcription on Windows; Anthropic API as fallback when local unavailable or confidence too low.
**Reasoning:** Privacy (no audio leaves device in happy path), low latency (no network round-trip), resilience (works offline). Cloud adds redundancy without being required path.
**Alternatives considered:** OpenAI API only (rejected — requires internet, higher cost for continuous transcription). Local-only without cloud (rejected — no recovery path for hardware failures or performance issues).
**Consequences:** Must maintain STT protocol abstraction so backends are swappable. Requires GPU or CPU capacity on device. Tests use a fake Transcriber Protocol, not real models.

### File-based storage instead of database server
**Date:** 2024-05-15
**Status:** Active
**Decision:** All persistent state (notes, session data, settings) is JSON files in AppData; no database server.
**Reasoning:** Single-user tool with no multi-process concurrency. File-based avoids operational overhead (no migration scripts, no connection pools, no transaction management). Enables offline-first workflow. Backups are trivial (copy directory).
**Alternatives considered:** SQLite (rejected — adds schema versioning burden). PostgreSQL (rejected — overkill for single user, complicates deployment). Cloud storage (rejected — relies on network, session restore would be slow).
**Consequences:** No transactions across files. Concurrent writes from same process don't happen (no worker threads). Backup/restore is straightforward: cp -r appdata to external drive.

### PySide6 for cross-platform GUI with Windows-specific overlays
**Date:** 2024-04-01
**Status:** Active
**Decision:** PySide6 for all UI; Windows-specific APIs (SetWindowDisplayAffinity, WASAPI) used directly via ctypes only where necessary.
**Reasoning:** PySide6 has Linux wheels and runs under QT_QPA_PLATFORM=offscreen for dev/CI. Only SetWindowDisplayAffinity (always-on-top overlay) is genuinely Windows-only. Everything else works cross-platform or has Linux equivalents.
**Alternatives considered:** PyQt5 (rejected — licensing ambiguity). tkinter (rejected — too basic for complex overlays). WPF/.NET (rejected — limits to Windows, blocks dev on Linux).
**Consequences:** Windows-only modules use `type: ignore[attr-defined]` for ctypes.windll. Type-checking diverges by platform; CI runs mypy on Windows. Tests run on Linux with QT_QPA_PLATFORM=offscreen.

### Dependency injection for STT backends, not factory functions
**Date:** 2024-03-20
**Status:** Active
**Decision:** STT backends injected into Application via constructor; SessionManager accesses via app.transcriber (protocol type), not by importing backend modules.
**Reasoning:** Testability (fake backends substituted in tests without monkeypatch). Flexibility (backends chosen at startup, not compile-time). Avoids circular imports at module load.
**Alternatives considered:** Factory functions in each backend (rejected — requires import of all backends in Application, defeats testability). Service locator/registry (rejected — implicit dependencies, harder to trace). Environment variables for backend selection (rejected — not composable in tests).
**Consequences:** All backends must implement Transcriber protocol. Application constructor has many optional parameters. Tests inject fake backends at composition root.
