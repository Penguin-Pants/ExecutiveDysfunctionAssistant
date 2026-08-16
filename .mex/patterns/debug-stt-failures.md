---
name: debug-stt-failures
description: Diagnose and fix speech-to-text transcription failures and backend issues
triggers:
  - "STT fails"
  - "transcription error"
  - "audio not captured"
  - "silent transcript"
  - "backend unavailable"
edges:
  - target: context/stack.md
    condition: when understanding STT backend specifics and error modes
  - target: context/architecture.md
    condition: when tracing audio flow from capture through transcription
  - target: patterns/add-stt-backend.md
    condition: when implementing retry logic or backend switching
  - target: context/setup.md
    condition: when checking environment setup for audio and dependencies
grounds_to: []
last_updated: 2026-08-16
---

# Debug STT Failures

## Context

The STT pipeline is: `AudioCapture` → (WASAPI frames) → `Transcriber.transcribe()` → (text result) → overlay UI. Failures can occur at any boundary:

1. **Audio not captured** — WASAPI loopback not found, permission denied, or audio device changed
2. **Transcriber instantiation fails** — model not available, out of memory, or credentials missing
3. **Transcription hangs** — backend process stuck, network timeout, or corrupted audio
4. **Silent/empty result** — audio too quiet, wrong language, or background noise misdetected

## Diagnosis Steps

### Step 1: Verify audio capture

```python
# In test or diagnostics context:
from interview_prep_recall.audio.capture import AudioCapture
capture = AudioCapture()
frames = list(capture.read_frames(duration=2.0))
print(f"Captured {len(frames)} frames, {sum(len(f) for f in frames)} bytes total")
```

If empty: WASAPI loopback is not available or not running. Check:
- Windows Settings → Sound → Volume mixer → check for loopback device
- Run diagnostics via `python -m interview_prep_recall --diagnostics` (if implemented)
- On Linux: expected to fail; audio tests marked `@pytest.mark.device`

### Step 2: Check transcriber initialization

```python
from interview_prep_recall.stt.local_whisper import LocalWhisper
transcriber = LocalWhisper()
# Should not raise; if it does, model is not available
```

If fails:
- Local Whisper: check GPU/CPU, available disk space for model cache
- Cloud Transcriber: check `ANTHROPIC_API_KEY` env var and network connectivity

### Step 3: Test with known-good audio

```python
# Use a real .wav file from tests/fixtures/
from pathlib import Path
audio_path = Path("tests/fixtures/sample_16k.wav")
with open(audio_path, "rb") as f:
    audio_bytes = f.read()
text = transcriber.transcribe(audio_bytes)
print(f"Result: {text}")
```

If empty: check audio format (Whisper needs 16kHz mono). Resample with soxr if needed.

### Step 4: Check Application wiring

In `interview_prep_recall/app.py`, verify:
- Transcriber is instantiated in `__post_init__` and assigned to `self.transcriber`
- SessionManager receives the transcriber and uses it correctly
- Fallback logic is in place (try local, fall back to cloud if available)

## Gotchas

- **WASAPI is Windows-only** — on Linux, audio tests skip entirely; can't test audio capture off Windows
- **Model caching** — first run of Whisper downloads the model (~1.4 GB); may appear hung. Check disk space.
- **Audio format** — Whisper strictly needs 16kHz mono PCM. If audio is stereo or 44.1kHz, resample.
- **Network timeouts** — cloud transcriber has no timeout; may hang if network is slow. Add explicit timeout in retry logic.
- **Concurrent transcription** — only one transcription at a time per Transcriber instance. Queue requests if necessary.

## Verify Checklist

- [ ] Audio capture works: `AudioCapture().read_frames(1.0)` returns non-empty bytes
- [ ] Transcriber instantiates without error
- [ ] Transcriber handles test audio fixture (e.g., `tests/fixtures/sample_16k.wav`)
- [ ] If using cloud: `ANTHROPIC_API_KEY` is set and network connectivity is up
- [ ] If using local Whisper: disk space available for model cache, GPU/CPU can run inference
- [ ] Timeout handling: transcription does not block UI for > 30 seconds; has fallback or error message

## Common Issues and Fixes

**Issue: "WASAPI loopback not found"**
- Fix: Audio tests are marked `@pytest.mark.device` and skipped in CI/Linux. Enable loopback in Windows Sound settings or skip device tests.

**Issue: "Transcriber initialization hangs"**
- Fix: Whisper model downloading on first run. Check disk space, let it complete. Add progress indicator or download timeout.

**Issue: "Empty transcript despite audio captured"**
- Fix: Audio may be too quiet. Check volume levels, add gain. Audio may be wrong format; verify 16kHz mono with `pytest tests/test_audio_capture.py`.

**Issue: "Cloud transcriber timeout"**
- Fix: Add explicit timeout parameter. Implement fallback to local if cloud slow. Check network connectivity.

## Update Scaffold

- [ ] If a systematic issue found, add to `.mex/context/setup.md` "Common Issues"
- [ ] If debug workaround discovered, document in a new note or update this pattern with the fix
