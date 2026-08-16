---
name: architecture
description: How the major pieces of this project connect and flow. Load when working on system design, integrations, or understanding how components interact.
triggers:
  - "architecture"
  - "system design"
  - "how does X connect to Y"
  - "integration"
  - "flow"
edges:
  - target: context/stack.md
    condition: when specific technology details are needed
  - target: context/decisions.md
    condition: when understanding why the architecture is structured this way
  - target: context/conventions.md
    condition: when understanding how components communicate and share state
  - target: patterns/add-ui-widget.md
    condition: when adding a new UI component or integrating with MainWindow
  - target: patterns/add-stt-backend.md
    condition: when integrating a new transcription backend
  - target: patterns/track-session-progress.md
    condition: when implementing session state tracking or report generation
# Broad overview: keep this empty unless a claim depends on a few specific symbols.
# Entry shape: { node: "function:<tier-1-id>", fingerprint: "mh:64:<hex>" }
grounds_to: []
last_updated: 2026-08-16
---

# Architecture

<!-- Read broad, ground tight. Architecture usually grounds sparsely. When a
     specific symbol is worth navigating to, use this inline form:
```markdown
[`someFunction()`](mex://function:<tier-1-id>)
```
-->

## System Overview

User speaks → audio capture via WASAPI loopback → transcribed by STT (local Whisper or cloud) → transcript streamed to overlay UI → user edits/annotates in editor → session tracker records progress → reports generated from session data → notes/findings persisted to local store.

## Key Components

- **MainWindow** — PySide6 top-level window holding overlay, editor, checklist, and report views. Composition root for UI state and settings.
- **SessionManager** — tracks session state (active/paused), coordinates with audio capture, STT transcription, and report generation.
- **AudioCapture** — WASAPI loopback for system audio, VAD (voice activity detection), frames buffered for transcription.
- **STT Interface** — protocol for local (Whisper) and cloud transcription; abstraction so backends are swappable.
- **ContextSet** — in-memory session context holding notes, decisions, and findings; serialized to notes store.
- **ReportGenerator** — builds findings from session context, formats for display in report view.
- **NotesStore** — persistent JSON-based storage, handles backups and session restoration.

## External Dependencies

- **PySide6** — GUI framework; all UI components are Qt-based. Cannot be unit-tested on Linux without QT_QPA_PLATFORM=offscreen.
- **faster-whisper** — local speech-to-text, runs on Windows with GPU acceleration optional. Cloud fallback available for resilience.
- **pyaudiowpatch** — Windows-only, WASAPI loopback for capturing system audio during interviews.
- **Anthropic SDK** — cloud transcription and LLM analysis; used when local Whisper unavailable or for confidence scoring.
- **NumPy** — core dependency, used throughout for audio frame manipulation and DSP operations.

## What Does NOT Exist Here

- No database server — all persistence is file-based (JSON). Session state lives in `AppData\Local\interview-prep-recall\`.
- No background processes or workers — everything runs in the foreground process on the interview session thread.
- No network infrastructure — cloud services are called directly by the app; no message queues or async event bus.
- No admin UI or dashboard — this is a single-user tool built for the interview candidate, not SaaS.
