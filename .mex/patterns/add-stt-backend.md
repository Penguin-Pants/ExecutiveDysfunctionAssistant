---
name: add-stt-backend
description: Integrate a new speech-to-text backend or transcription service
triggers:
  - "add STT backend"
  - "new transcriber"
  - "integrate transcription service"
  - "speech-to-text"
edges:
  - target: context/stack.md
    condition: when understanding STT library choices and constraints
  - target: context/decisions.md
    condition: when understanding why STT is abstracted via Protocol
  - target: context/conventions.md
    condition: when implementing the Transcriber Protocol
  - target: context/architecture.md
    condition: when understanding how transcription fits in the audio pipeline
  - target: patterns/debug-stt-failures.md
    condition: when troubleshooting the backend you just added
grounds_to: []
last_updated: 2026-08-16
---

# Add STT Backend

## Context

Speech-to-text is abstracted via a [`Transcriber` Protocol](mex://interview_prep_recall/stt/interface.py) so backends are swappable. The protocol defines a single method: `transcribe(audio_bytes: bytes) -> str`. Currently, two backends exist:

- `LocalWhisper` — faster-whisper running locally, no network latency
- `CloudTranscriber` — Anthropic SDK for fallback/high-confidence scoring

New backends must implement `Transcriber`, be added to the Application dependency injection, and tested with a fake backend in unit tests (no actual model invocation in CI).

## Steps

1. Create backend class implementing `Transcriber` protocol in `interview_prep_recall/stt/<backend_name>.py`
   ```python
   from interview_prep_recall.stt.interface import Transcriber
   
   class MyTranscriber(Transcriber):
       def transcribe(self, audio_bytes: bytes) -> str:
           # Your implementation here
           return transcribed_text
   ```

2. Document initialization requirements in the class docstring
   - Any environment variables, credentials, or configuration
   - Performance characteristics (latency, CPU/memory, network requirements)
   - Failure modes and how they are handled

3. Add backend factory to `interview_prep_recall/app.py` in Application constructor
   - Use a conditional (env var, config flag, or availability check)
   - Fall back gracefully if backend unavailable (e.g., network down, model not installed)

4. Add tests in `tests/test_<backend_name>.py`
   - Do NOT call the real service/model in CI
   - Use a fake audio fixture (small .wav file in `tests/fixtures/`)
   - Test error handling: malformed audio, network timeouts, service degradation

5. Update `context/stack.md` "Key Libraries" section if new external dependency added

## Gotchas

- **Don't hardcode backend choice** — inject via Application; test with fake backend
- **Don't block on network calls** — transcription must not hang the UI; consider timeouts
- **Audio format matters** — Whisper expects 16kHz mono; resample via soxr if needed
- **Don't log audio content** — transcribed text is private; never print audio bytes
- **Credential handling** — use environment variables or keyring, never hardcode secrets
- **CI environment** — your backend must not require GPU/internet/external service in test mode; use mocks

## Verify

- [ ] New class implements `Transcriber` protocol exactly (single `transcribe()` method)
- [ ] Class has docstring explaining init requirements, performance, failure modes
- [ ] Backend is conditionally added to Application in `_build_application()`
- [ ] Tests exist in `tests/test_<backend_name>.py` using real audio fixtures, fake in CI
- [ ] No real network calls in pytest run; `pytest tests/test_<backend_name>.py` passes on Linux
- [ ] Audio handling: correctly handles edge cases (silence, noise, very short clips)
- [ ] Error handling: exceptions include context (file, line, what failed)

## Debug

If `Application` fails to instantiate with your backend: check that the backend class is imported in `app.py` and the conditional logic is correct. Check logs for import errors.

If tests hang or timeout: backend is making real network calls or waiting for hardware. Add a `@pytest.mark.skip` on tests requiring real backend, or use a mock.

If transcription is wrong or slow: check audio format (Whisper needs 16kHz mono). Profile with a real audio file to measure latency. Add performance markers in logs.

## Update Scaffold

- [ ] Update `.mex/context/stack.md` "Key Libraries" if new external dependency
- [ ] Update `.mex/context/decisions.md` if this backend represents a major architectural change
- [ ] Add this pattern to `.mex/patterns/INDEX.md` if creating the first instance of this pattern type
