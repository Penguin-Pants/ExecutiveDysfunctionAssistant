---
name: setup
description: Dev environment setup and commands. Load when setting up the project for the first time or when environment issues arise.
triggers:
  - "setup"
  - "install"
  - "environment"
  - "getting started"
  - "how do I run"
  - "local development"
edges:
  - target: context/stack.md
    condition: when specific technology versions or library details are needed
  - target: context/architecture.md
    condition: when understanding how components connect during setup
  - target: patterns/debug-stt-failures.md
    condition: when troubleshooting setup issues with audio or transcription
# Ground only setup behavior implemented by specific code symbols.
# Entry shape: { node: "function:<tier-1-id>", fingerprint: "mh:64:<hex>" }
grounds_to: []
last_updated: 2026-08-16
---

# Setup

<!-- Commands and environment facts need no code grounding. For a concrete symbol:
```markdown
[`someFunction()`](mex://function:<tier-1-id>)
```
-->

## Prerequisites

- **Python 3.11+** (3.12 for type checking) — on Windows, use official installer or `winget install Python.Python.3.12`.
- **pip** (usually bundled with Python) — `python -m pip install --upgrade pip`.
- **Windows 10/11** (for shipping, but dev/CI can run on Linux with caveats) — audio capture and WASAPI are Windows-only; UI runs on Linux with QT_QPA_PLATFORM=offscreen.

## First-time Setup

1. Clone the repo: `git clone <repo-url> && cd interview-prep-recall`
2. Create a virtual environment: `python -m venv .venv && .venv\Scripts\activate` (Windows) or `source .venv/bin/activate` (Linux/Mac)
3. Install base + dev dependencies: `pip install -e ".[dev]"` (will install pytest, mypy, ruff, but NOT ui/windows extras on non-Windows)
4. On Windows, also install optional extras: `pip install -e ".[ui,windows,embeddings,cloud]"` for full feature set; tests will skip features not installed.
5. Run tests to verify: `pytest` (on Windows all tests pass; on Linux, device/windows markers are skipped)
6. Type-check: `mypy interview_prep_recall` (runs with python_version=3.12 even if dev container is 3.11; ignores warnings for Windows-only modules on non-Windows)
7. Lint: `ruff check .` (line-length 100, target Python 3.11+)

## Environment Variables

- `ANTHROPIC_API_KEY` (optional) — only if using cloud transcription. Not required if local Whisper available.
- `INTERVIEW_PREP_RECALL_DATA_ROOT` (optional) — override app data location; defaults to `{Windows AppData}/Local/interview-prep-recall` or `~/.interview-prep-recall` on Linux.

No .env files — all configuration is runtime or stored in the notes store.

## Common Commands

- `pytest` — run full test suite (skips device/windows markers on non-Windows)
- `pytest -v tests/test_session.py` — run specific test file
- `pytest -m device` — run only device tests (WASAPI, real audio) — Windows-only, requires audio hardware
- `mypy interview_prep_recall` — type check; configured for Python 3.12 strict semantics
- `ruff check . && ruff format .` — lint and format (line-length 100, no docs/ directory)
- `python -m interview_prep_recall` — run the app (Windows only; Linux needs QT_QPA_PLATFORM=offscreen and will fail on WASAPI loopback)

## Common Issues

**Import errors for optional dependencies (ui, windows, embeddings, cloud):** These extras are optional. Install the specific extra: `pip install -e ".[ui]"` for PySide6, etc. Tests skip unavailable features gracefully via fixture markers.

**Type-checking fails on non-Windows (ctypes.windll):** Expected. Windows-only modules have `warn_unused_ignores = false` in pyproject.toml so CI on Windows doesn't fail on legitimate platform-specific ignores.

**QApplication not available on Linux:** Install PySide6: `pip install -e ".[ui]"`. For headless testing, use `QT_QPA_PLATFORM=offscreen pytest`.

**WASAPI loopback not found on Windows:** Audio tests are marked `@pytest.mark.device`. Loopback device may not be enabled. Check Sound Settings → Volume mixer → App volume and device preferences.
