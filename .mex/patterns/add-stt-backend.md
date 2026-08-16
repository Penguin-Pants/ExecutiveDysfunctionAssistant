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
    condition: when implementing the SttBackend Protocol
  - target: context/architecture.md
    condition: when understanding how transcription fits in the audio pipeline
  - target: patterns/debug-stt-failures.md
    condition: when troubleshooting the backend you just added
grounds_to:
  - node: "class:3bc23074079eaa3a8334ade9bd01bff9"
    fingerprint: "mh:64:7b226d696e68617368223a5b31383134343139392c38373531313530332c3137333535333538342c3234333834363135342c33393930353238382c3330353239373636302c3131373137353935382c3130333434373737352c3132323336393731322c3331393039363639362c3135303738303934362c3132353037333139332c3134303337373431382c35323931303230312c32363435373333382c32373732313037342c38343239323033342c3237343331333732312c35313835353236382c31363538383035392c3231333832353133302c32363739393939392c3331333536323535312c393832393038372c3132393338393334332c3232303531303933382c35353534343534342c37363032373137372c3132393938373839302c3230333738303130352c3631323437303432302c3134363731353938312c37383532373436342c3134343331313935322c38383736343531392c3136313432393339322c3130363838383938332c31303836393338392c35363936323936392c3133323233333533372c38383932333434302c3338303937373031332c3832363536312c34353735363338362c3235303536323032382c3132393138363339382c36383337343337332c3131323333313433372c32353838363635372c31363336343631362c3134373836373935382c3331373831383530332c35363434333039392c3432363132333339312c38353336313636392c37383932363934362c3133363036323735352c3138373633353039342c3233333238373839322c3233343231393332352c3133363233363736332c3131393833383337352c39323039313630342c31313732363932355d2c226e65696768626f7273223a5b5d2c22746f6b656e436f756e74223a38367d"
  - node: "function:d00fdd528fe603104877190bc64472bf"
    fingerprint: "mh:64:7b226d696e68617368223a5b3337323438393338372c38373531313530332c3539343634303633322c3234333834363135342c3132373334393133322c313038313930303733372c3135313431343531372c3239363439313736342c3230363531353730312c3338353236323035302c3135393330393636332c37353139393638352c3231383131373833352c3132323137353830362c3735393330393530302c32373732313037342c3131383537303232312c3133353138353636372c3230363133383832302c3438363833313539332c3231333832353133302c3135353037323538332c3331333536323535312c393832393038372c3137303139353032342c3732393430373237342c3134323037333138362c37363032373137372c3138373233373630332c3134393937313532362c3431323832323936362c3536313030303133302c3435333330333332342c3336393839393338342c38383736343531392c3136313432393339322c3131303731353836362c3934383332303638362c35363936323936392c3436303338313236372c3534333038363534362c3230373631323938322c31333034363236372c3437303938363532372c3839313939333737372c3132393138363339382c3339383634353135382c3437363135313439322c3239323130343332332c3132303632313938342c3135323936333035342c3331373831383530332c31383737353335302c3230383337353737342c3430393635353631352c37383932363934362c3330393735373533312c3334363233313338372c3532363337333230312c3331323132373035322c3133363233363736332c3939303534393830322c3134303834313135352c31313732363932355d2c226e65696768626f7273223a5b2266756e6374696f6e3a3030623837613366316434353361613966353132333537366335346633396239222c2266756e6374696f6e3a3334336138613762383736393239323763383865356330356264373464366534222c2266756e6374696f6e3a3530383631313233653538313164623033333039353361633439656334396663222c2266756e6374696f6e3a3563633137323336363135653861303035373361376562653735343464643364222c2266756e6374696f6e3a3665626462303561316331313736643265333634313137613838616365653730222c2266756e6374696f6e3a3931613461356665376235373437363930373834383166363637633336643663222c2266756e6374696f6e3a6137346263653737396132333961633235343133323236356665363764373866222c2266756e6374696f6e3a6235613237323132303365633164313934396566616136356633326134396333222c2266756e6374696f6e3a6238653364613039353630313237303161376464396531336537316533663530222c2266756e6374696f6e3a6437356264623236323536303566616538316163343639383430666334393264225d2c22746f6b656e436f756e74223a33377d"
last_updated: 2026-08-16
---

# Add STT Backend

## Context

Speech-to-text is abstracted via the [`SttBackend` Protocol](mex://class:3bc23074079eaa3a8334ade9bd01bff9) in `interview_prep_recall/stt/interface.py` so backends are swappable. It is a *streaming* contract, not a one-shot call: `start()`, `feed()`, `stop()`, `close()`, plus the `name` and `supports_interim` attributes. The docstring's eight numbered binding rules are the contract — a backend that breaks one is broken even if its own tests pass.

Three implementations exist:

- `LocalWhisperBackend` (`stt/local_whisper.py`) — faster-whisper, no network. Note the module also defines its own `Transcriber` Protocol; that is a Whisper-internal one-shot inference adapter, not the backend contract, and a new backend has no use for it
- `CloudSttBackend` (`stt/cloud.py`) — shared WebSocket plumbing; `DeepgramBackend` and `ElevenLabsBackend` subclass it and supply protocol specifics only
- `FallbackSttBackend` (`stt/fallback.py`) — itself an `SttBackend`, runs a primary and switches to a local one on failure (FR21)

The Protocol is structural, so a new backend satisfies it by shape, not by subclassing. The acceptance criterion is the [T2.1 conformance suite](mex://function:d00fdd528fe603104877190bc64472bf) in `tests/conformance.py`, which every backend must pass **unmodified**.

## Steps

1. Create the backend class in `interview_prep_recall/stt/<backend_name>.py`
   - Implement `start`, `feed`, `stop`, `close`, and declare `name` and `supports_interim`
   - For a streaming cloud service, subclass `CloudSttBackend` and supply only the connector and the protocol-specific frame/result handling
   - Read the eight rules in the `SttBackend` docstring first — finalisation, ordering and the capture clock are yours to honour, not the wire protocol's

2. Document initialization requirements in the class docstring
   - Any environment variables, credentials, or configuration
   - Performance characteristics (latency, CPU/memory, network requirements)
   - Failure modes and which `SttStreamState` each one reports

3. Add a member to `SttBackendChoice` in `interview_prep_recall/config.py`
   - The settings UI enumerates the enum, so the choice appears without extra UI work
   - Injection happens at the composition root; `_build_application()` in `__main__.py` still raises `NotImplementedError` (T9.6a), so there is no real construction site to edit yet
   - Cloud choices are what `startup.py` uses to decide the egress checks — a backend that leaves the device belongs to the non-`LOCAL` set

4. Add tests in `tests/test_<backend_name>.py`
   - Write a zero-argument factory and pass it to `run_conformance_suite(factory)` — that is the whole generic contract, inherited
   - Cover rules 2, 3 and 5 per backend, with scripted server output; a generic factory cannot produce those conditions
   - Do NOT call the real service or download a model in CI; use a double for the transport or the transcriber
   - Test error handling: dropped connections, malformed results, service degradation

5. Update `context/stack.md` "Key Libraries" section if new external dependency added

## Gotchas

- **Don't hardcode backend choice** — inject via the composition root; test with a double
- **`feed()` must never block or raise** — it enqueues and returns; a backend that cannot keep up drops internally and reports `DEGRADED`. Blocking there stalls the audio callback and breaks FR45's 2 ms budget
- **Audio format is fixed, not negotiated** — `feed()` receives exactly one `FRAME_BYTES` frame (640 bytes, 20 ms of 16 kHz mono int16). Resampling already happened upstream in `audio/capture.py`; reject a mismatched rate as `LocalWhisperBackend` does, never resample inside the backend
- **Use the capture clock** — timestamps derive from the `t_capture` value passed to `feed()`, never wall-clock or arrival time, or cloud latency corrupts utterance boundaries
- **Don't log audio content** — transcribed text is private; never print audio bytes
- **Credential handling** — use environment variables, never hardcode secrets
- **CI environment** — your backend must not require GPU/internet/external service in test mode; use doubles

## Verify

- [ ] Class satisfies `SttBackend` structurally: `start`/`feed`/`stop`/`close`, `name`, `supports_interim`
- [ ] Class has docstring explaining init requirements, performance, failure modes
- [ ] New `SttBackendChoice` member exists and round-trips through config load/save
- [ ] `run_conformance_suite(factory)` passes **unmodified** from `tests/test_<backend_name>.py`
- [ ] Rules 2 (finalisation), 3 (interim advisory) and 5 (capture clock) are checked per backend
- [ ] No real network calls or model downloads in `pytest tests/test_<backend_name>.py`
- [ ] `mypy interview_prep_recall` clean; `stt/interface.py` is strict
- [ ] Error handling: exceptions include context (what failed, which stream)

## Debug

If the conformance suite fails: read the failing `check_*` name — each maps to one numbered rule in the `SttBackend` docstring. Fix the rule, not the check; the suite is the contract.

If tests hang or timeout: the backend is making real network calls or waiting for hardware. Inject a double for the connector or the transcriber instead.

If the settings page does not show your backend: the `SttBackendChoice` member is missing or the persisted config still holds an older value.

If transcription is wrong or misplaced in time: check that timestamps come from `t_capture` and that `stream_id` ordering is non-decreasing. Profile with a captured PCM fixture to measure latency.

## Update Scaffold

- [ ] Update `.mex/context/stack.md` "Key Libraries" if new external dependency
- [ ] Update `.mex/context/decisions.md` if this backend represents a major architectural change
- [ ] Add this pattern to `.mex/patterns/INDEX.md` if creating the first instance of this pattern type
