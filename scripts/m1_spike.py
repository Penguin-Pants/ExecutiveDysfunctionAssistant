"""M1 audio capture spike — the AS-2 gate. **Run this on the Windows machine.**

AS-2 is the project's oldest and riskiest assumption: *"`pyaudiowpatch` can open WASAPI
loopback and a mic input concurrently and stably for 60 minutes."* Everything above the
capture layer is built on it. If it is false, the capture library decision reopens before
anything else is built on top — which is why `03-tasks.md` marks M1 "**Stop and
escalate**" rather than "work around it".

This script is not part of the product. It lives in `scripts/` deliberately: it is a
diagnostic, and design §1's module layout is normative for the package.

Usage, from the repo root with the venv active:

    python scripts/m1_spike.py devices          # T1.4 — what can we capture from?
    python scripts/m1_spike.py levels           # T1.1 — live RMS, play audio at it
    python scripts/m1_spike.py dual --seconds 60    # T1.2 — both streams, short run
    python scripts/m1_spike.py dual --seconds 3600  # T1.2 — the real 60-minute gate
    python scripts/m1_spike.py watch            # T1.4 — change your default device

Every number it prints is one an acceptance criterion asks for, so the output can be
pasted straight back as the gate result.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from interview_prep_recall.audio.capture import (  # noqa: E402
    FRAME_BYTES,
    SAMPLE_RATE,
    BoundedFrameQueue,
    CaptureStream,
)
from interview_prep_recall.audio.devices import (  # noqa: E402
    DefaultDeviceWatcher,
    DeviceError,
    default_loopback,
    default_microphone,
    describe,
)

FRAME_S = FRAME_BYTES / (SAMPLE_RATE * 2)
DRIFT_BUDGET_S = 0.050
"""T1.2: "no clock drift beyond 50 ms"."""


def _pyaudio():  # type: ignore[no-untyped-def]
    try:
        import pyaudiowpatch
    except ImportError:
        print(
            "pyaudiowpatch is not installed. This script only runs on Windows:\n"
            '    pip install -e ".[dev,ui,windows]"',
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    return pyaudiowpatch.PyAudio()


def _rms(frame: bytes) -> float:
    samples = np.frombuffer(frame, dtype=np.int16).astype(np.float64)
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples * samples)))


def _bar(rms: float, width: int = 40) -> str:
    """A log-scaled meter. Linear RMS looks dead for speech, which sits far below full
    scale — and a meter that looks dead is indistinguishable from a stream that is."""
    if rms <= 1:
        return " " * width
    filled = min(width, int(width * math.log10(rms) / math.log10(32768)))
    return "#" * filled + " " * (width - filled)


# ---------- T1.4 ----------


def cmd_devices() -> int:
    pa = _pyaudio()
    try:
        print("WASAPI capture endpoints:\n")
        for device in describe(pa):
            print(f"  {device.kind.value:<11} {device.label}")
        print()
        pairs = (("default loopback", default_loopback), ("default mic", default_microphone))
        for name, getter in pairs:
            try:
                print(f"  {name}: {getter(pa).label}")
            except DeviceError as exc:
                print(f"  {name}: UNAVAILABLE — {exc}")
    finally:
        pa.terminate()
    return 0


def cmd_watch(seconds: float) -> int:
    """T1.4: switching the default output and unplugging headphones each fire within 1 s."""
    pa = _pyaudio()
    changes: list[str] = []

    def on_change(change) -> None:  # type: ignore[no-untyped-def]
        stamp = time.strftime("%H:%M:%S")
        was = change.previous.name if change.previous else "none"
        now = change.current.name if change.current else "NONE (lost)"
        line = f"[{stamp}] {change.kind.value}: {was} -> {now}"
        changes.append(line)
        print(line, flush=True)

    watcher = DefaultDeviceWatcher(pa, on_change)
    print(f"Watching default devices for {seconds:.0f}s.")
    print("Change your default playback device, or unplug your headphones.\n")
    watcher.start()
    try:
        time.sleep(seconds)
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop()
        pa.terminate()
    print(f"\n{len(changes)} change(s) detected.")
    return 0


# ---------- T1.1 ----------


def cmd_levels(seconds: float) -> int:
    """T1.1: "console prints live RMS while any app plays audio"."""
    pa = _pyaudio()
    try:
        device = default_loopback(pa)
    except DeviceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        pa.terminate()
        return 1

    print(f"Loopback: {device.label}")
    print("Play audio (YouTube, Spotify, anything). Ctrl-C to stop.\n")
    queue = BoundedFrameQueue()
    stream = CaptureStream(stream_id="interviewer", queue=queue, device=device, pa=pa)
    stream.start()
    peak = 0.0
    deadline = time.monotonic() + seconds
    try:
        while time.monotonic() < deadline:
            time.sleep(0.1)
            frames = queue.drain()
            if not frames:
                continue
            rms = max(_rms(bytes(f)) for f, _ in frames)
            peak = max(peak, rms)
            print(f"\rRMS {rms:8.1f} |{_bar(rms)}| frames={stream.frames_delivered}", end="")
    except KeyboardInterrupt:
        pass
    finally:
        stream.stop()
        pa.terminate()

    print(f"\n\nframes delivered : {stream.frames_delivered}")
    print(f"peak RMS         : {peak:.1f}")
    print(f"callback error   : {stream.error!r}")
    if stream.frames_delivered == 0:
        print("\nFAIL (T1.1): no frames captured.")
        return 1
    if peak < 1.0:
        print("\nINCONCLUSIVE (T1.1): frames captured but all silent. Was audio playing?")
        return 1
    print("\nPASS (T1.1): non-silent PCM captured from loopback.")
    return 0


# ---------- T1.2 — the AS-2 gate ----------


def cmd_dual(seconds: float) -> int:
    """T1.2: both streams for 60 minutes, no conflict, no dropout, drift < 50 ms.

    Drift is measured as the difference in *audio delivered* between the two streams.
    Each frame is exactly 20 ms, so `frames * 0.02` is how much audio each stream thinks
    it has captured; if the two clocks diverge, so do those totals. That is the number
    D-U2's dual-stream requirement actually depends on — an interviewer's question and
    the user's answer have to be placeable on one timeline.
    """
    pa = _pyaudio()
    try:
        loopback = default_loopback(pa)
        mic = default_microphone(pa)
    except DeviceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        pa.terminate()
        return 1

    print(f"Loopback : {loopback.label}")
    print(f"Mic      : {mic.label}")
    print(f"Duration : {seconds:.0f}s\n")

    queues = {"interviewer": BoundedFrameQueue(), "user": BoundedFrameQueue()}
    streams = {
        "interviewer": CaptureStream("interviewer", queues["interviewer"], loopback, pa=pa),
        "user": CaptureStream("user", queues["user"], mic, pa=pa),
    }

    for stream in streams.values():
        stream.start()

    started = time.monotonic()
    worst_drift = 0.0
    try:
        while time.monotonic() - started < seconds:
            time.sleep(1.0)
            for queue in queues.values():
                queue.drain()  # keep the queues from saturating; we only need counts
            counts = {k: s.frames_delivered for k, s in streams.items()}
            drift = abs(counts["interviewer"] - counts["user"]) * FRAME_S
            worst_drift = max(worst_drift, drift)
            elapsed = time.monotonic() - started
            print(
                f"\r{elapsed:6.0f}s  interviewer={counts['interviewer']:>8}  "
                f"user={counts['user']:>8}  drift={drift * 1000:6.1f}ms  "
                f"dropped={queues['interviewer'].dropped}/{queues['user'].dropped}",
                end="",
                flush=True,
            )
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        for stream in streams.values():
            stream.stop()
        pa.terminate()

    elapsed = time.monotonic() - started
    print("\n\n--- AS-2 gate result ---")
    print(f"elapsed            : {elapsed:.0f}s")
    for name, stream in streams.items():
        expected = elapsed / FRAME_S
        pct = 100.0 * stream.frames_delivered / expected if expected else 0.0
        print(
            f"{name:<18} : {stream.frames_delivered} frames "
            f"({pct:.1f}% of expected), error={stream.error!r}"
        )
    print(
        f"worst drift        : {worst_drift * 1000:.1f} ms (budget {DRIFT_BUDGET_S * 1000:.0f} ms)"
    )

    failures = []
    if any(s.frames_delivered == 0 for s in streams.values()):
        failures.append("a stream delivered no frames")
    if any(s.error is not None for s in streams.values()):
        failures.append("a callback raised")
    if worst_drift > DRIFT_BUDGET_S:
        failures.append(f"drift {worst_drift * 1000:.1f} ms exceeds the 50 ms budget")

    if failures:
        print("\nFAIL (T1.2 / AS-2): " + "; ".join(failures))
        print("Per 03-tasks.md, M1's gate says STOP AND ESCALATE — the capture library")
        print("decision reopens before anything else is built on top.")
        return 1
    print("\nPASS (T1.2): concurrent dual-stream capture held for the run.")
    if elapsed < 3500:
        print("NOTE: AS-2 asks for 60 minutes. Re-run with --seconds 3600 to close the gate.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["devices", "levels", "dual", "watch"], help="which check to run"
    )
    parser.add_argument("--seconds", type=float, default=30.0, help="duration for timed checks")
    args = parser.parse_args()

    if args.command == "devices":
        return cmd_devices()
    if args.command == "levels":
        return cmd_levels(args.seconds)
    if args.command == "watch":
        return cmd_watch(args.seconds)
    return cmd_dual(args.seconds)


if __name__ == "__main__":
    sys.exit(main())
