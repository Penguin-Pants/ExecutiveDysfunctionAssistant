---
name: stack
description: Technology stack, library choices, and the reasoning behind them. Load when working with specific technologies or making decisions about libraries and tools.
triggers:
  - "library"
  - "package"
  - "dependency"
  - "which tool"
  - "technology"
edges:
  - target: context/decisions.md
    condition: when the reasoning behind a tech choice is needed
  - target: context/conventions.md
    condition: when understanding how to use a technology in this codebase
  - target: context/architecture.md
    condition: when understanding how technologies integrate in the system
  - target: context/setup.md
    condition: when installing or configuring dependencies
  - target: patterns/add-stt-backend.md
    condition: when working with transcription libraries or backends
# Broad inventory: ground only claims embodied by a small number of symbols.
# Entry shape: { node: "function:<tier-1-id>", fingerprint: "mh:64:<hex>" }
grounds_to: []
last_updated: 2026-08-16
---

# Stack

<!-- Keep grounding sparse here. For a concrete wrapper or adapter mention, use:
```markdown
[`someFunction()`](mex://function:<tier-1-id>)
```
-->

## Core Technologies

- **Python 3.11+** — shipping target is 3.12 per design doc §10; type-checked via mypy with python_version = 3.12 even though dev container runs 3.11.
- **PySide6 6.6+** — Qt6 bindings; all UI is Qt-based. Runs on Linux with QT_QPA_PLATFORM=offscreen for CI; genuinely Windows-only only for SetWindowDisplayAffinity API.
- **NumPy 1.26+** — core runtime dependency, used for audio frame DSP and tensor operations throughout.

## Key Libraries

- **faster-whisper 1.0+** (not OpenAI API) — local speech-to-text, runs on Windows with optional GPU; avoids network dependency for core transcript path.
- **pyaudiowpatch 0.2.12+** (Windows-only) — WASAPI loopback audio capture; no alternative for system audio on Windows.
- **Anthropic SDK 0.39+** (cloud extra) — cloud transcription fallback and LLM-based report generation; lazily imported only when cloud backends activated.
- **pytest 8+** (not unittest) — all tests use pytest fixtures and markers; mypy for strict type checking on STT interface module.
- **pytest-cov** — coverage reporting with `filterwarnings = ["error::DeprecationWarning"]` to catch API drift early.
- **soxr 0.3.7+** — audio resampling for Whisper pipeline; critical for VAD accuracy across different sample rates.
- **sentence-transformers 2.6+** (embeddings extra) — semantic matching for notes; CI does not install; tests use a fake Protocol.

## What We Deliberately Do NOT Use

- No ORMs, no database abstractions — all storage is JSON-based via custom serializers. File-based avoids operational complexity and is testable offline.
- No async event bus or message queue — session-aware threading model is simpler and sufficient for single-user, single-session scope.
- No class-based views or handler inheritance — functional architecture with dependency injection preferred; no abstract base classes except for STT Protocol.
- No logging frameworks (no `logging` module) — diagnostics via structured exceptions with context, printed to stderr in dev; production uses QMessageBox for critical errors.

## Version Constraints

Minimum Python 3.11 enforced by type stubs (NumPy requires 3.10+, stdlib generics require 3.10+). Windows-only APIs (ctypes.windll, WASAPI) require platform-specific type: ignore annotations; CI runs mypy on Windows to avoid false unused-ignore errors for these same stubs.
