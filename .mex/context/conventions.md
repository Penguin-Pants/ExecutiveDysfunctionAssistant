---
name: conventions
description: How code is written in this project — naming, structure, patterns, and style. Load when writing new code or reviewing existing code.
triggers:
  - "convention"
  - "pattern"
  - "naming"
  - "style"
  - "how should I"
  - "what's the right way"
edges:
  - target: context/architecture.md
    condition: when a convention depends on understanding the system structure
  - target: context/stack.md
    condition: when understanding library-specific usage patterns
  - target: patterns/add-ui-widget.md
    condition: when following Qt/widget naming and structure conventions
  - target: patterns/track-session-progress.md
    condition: when implementing data models following project conventions
# Add only nodes that embody the documented convention; do not ground examples broadly.
# grounds_to:
#   - node: "function:<tier-1-id>"
#     fingerprint: "mh:64:<hex>"
grounds_to: []
last_updated: 2026-08-16
---

# Conventions

<!-- Read broad, ground tight. Anchor concrete symbols while keeping prose readable:
```markdown
[`someFunction()`](mex://function:<tier-1-id>)
```
-->

## Naming

- **Files:** snake_case (`audio_capture.py`, `local_whisper.py`), module structure mirrors class/domain hierarchy.
- **Classes:** PascalCase, concrete implementation names are specific (`SessionManager`, `AudioCapture`), Protocol names end with protocol suffix or concept is clear from imports.
- **Functions/methods:** snake_case, verb-first when imperative (`run_preflight()`, `transcribe_audio()`), noun-first for properties/accessors (`state`, `settings`).
- **Constants:** UPPER_SNAKE_CASE with semantic grouping by module (e.g., all exit codes grouped in `__main__.py`).
- **Variables:** Descriptive, avoid abbreviations except where universally known (`VAD` for voice activity detection, `STT` for speech-to-text, `LLM` for language model).

## Structure

- **Module organization:** Each major component (audio, stt, ui, session, notes, report) is a separate package under `interview_prep_recall/`, with `__init__.py` exporting public symbols only.
- **Test layout:** Tests live in separate `tests/` directory with mirror structure. Test files named `test_<module>.py`.
- **Class pattern:** One primary class per file where possible (e.g., `SessionManager` in `session/manager.py`). Data classes and Protocols colocated in their usage file.
- **No internal imports:** Avoid circular imports by declaring Protocol contracts at module boundaries. Dependency injection preferred over global state.

## Patterns

**STT abstraction — use Protocol, never concrete implementations directly:**
```python
# Correct
class Application:
    transcriber: Transcriber  # Protocol type hint

def transcribe(app: Application, audio: bytes) -> str:
    return app.transcriber.transcribe(audio)

# Wrong
from interview_prep_recall.stt.local_whisper import LocalWhisper
transcriber = LocalWhisper()  # Hard-coded dependency
```

**Data classes for domain models — use @dataclass, not dicts:**
```python
# Correct
@dataclass
class TranscriptEvent:
    text: str
    timestamp: float

# Wrong
event = {"text": "...", "timestamp": 0.5}
```

**Session state management — only SessionManager mutates Application state:**
```python
# Correct (in session manager)
app.session.pause()
app.settings.update(new_value)

# Wrong (elsewhere in the app)
app.session.is_active = False  # Direct mutation
```

## Verify Checklist

Before presenting any code:
- [ ] No circular imports (run `python -c "import interview_prep_recall"` to verify)
- [ ] Data models use @dataclass, not dicts or plain objects
- [ ] STT backends are injected via Application, not imported directly
- [ ] UI state is owned by MainWindow, not scattered across widgets
- [ ] Tests do not mock the notes store — use a real tmp_path fixture
- [ ] Type hints present on public functions; internal functions may be omitted if obvious
- [ ] No print() statements except in __main__.py for diagnostics; use logging context in exceptions
- [ ] Tests use pytest style (fixtures, markers), not unittest TestCase
