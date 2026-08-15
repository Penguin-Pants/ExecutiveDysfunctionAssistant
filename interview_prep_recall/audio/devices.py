"""WASAPI device enumeration and default-change detection (T1.4 — FR5, FR6, FR39).

**Written from `pyaudiowpatch` documentation and never executed.** The package has no
Linux distribution at all (`pip` reports "from versions: none"), and this container has
no `/dev/snd` and no sound subsystem, so nothing here has run. That is **AS-2**, the
project's oldest and riskiest assumption, and M1 is the gate that settles it.

**The PyAudio handle is injected.** Everything that is *ours* — picking a loopback device
for the default output, matching a mic, deciding whether the default changed — is
ordinary logic over plain records, and it is tested here against a fake. What cannot be
tested here is the one call that opens a device. Same seam as `Transcriber` (AS-9) and
`Cipher`: the unverified surface is small and named.

**Default-change detection is polled, not COM.** Design §1 says "IMMNotificationClient",
which is the right long-term answer and needs a COM MTA apartment, a callback interface
and careful thread affinity — `watchdog.py` already carries that note. FR39's acceptance
criterion is *"fire a callback within 1 s"*, and a 500 ms poll of the default device
index meets it with none of that machinery. The trade is recorded rather than hidden:
polling cannot distinguish "device replaced" from "device renamed", and it burns a wakeup
twice a second. **Upgrade path: `IMMNotificationClient` in `watchdog.py`**, where the COM
apartment already has to exist.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import Enum
from typing import Any

POLL_INTERVAL_S = 0.5
"""Half of FR39's 1 s budget, so a change is seen well inside it."""


class DeviceKind(Enum):
    LOOPBACK = "loopback"
    """System audio — what the interviewer's voice arrives on (FR5)."""

    MICROPHONE = "microphone"
    """The user's own voice (FR6)."""


@dataclass(frozen=True)
class DeviceInfo:
    """One capture endpoint, in our terms rather than PortAudio's.

    A record rather than the raw dict `pyaudiowpatch` returns, so the selection logic can
    be exercised without a sound card and so a vendor dict shape cannot leak into the
    rest of the app.
    """

    index: int
    name: str
    kind: DeviceKind
    channels: int
    sample_rate: int

    @property
    def label(self) -> str:
        return f"[{self.index}] {self.name} ({self.channels}ch @ {self.sample_rate} Hz)"


class DeviceError(RuntimeError):
    pass


def _as_info(raw: dict[str, Any], kind: DeviceKind) -> DeviceInfo:
    """Normalise one PortAudio device dict.

    Defensive about types because these come from a C library through a dict: a device
    reporting a float rate (they do) must not produce a float sample rate that later
    fails an exact comparison.
    """
    return DeviceInfo(
        index=int(raw["index"]),
        name=str(raw.get("name", "unknown")),
        kind=kind,
        channels=int(raw.get("maxInputChannels") or 0),
        sample_rate=int(float(raw.get("defaultSampleRate") or 0)),
    )


def loopback_devices(pa: Any) -> Iterator[DeviceInfo]:
    """Every WASAPI loopback endpoint.

    `pyaudiowpatch` exposes loopback devices as *input* devices that shadow each output —
    that is the whole reason this fork exists over stock PyAudio.
    """
    for raw in pa.get_loopback_device_info_generator():
        yield _as_info(raw, DeviceKind.LOOPBACK)


def default_loopback(pa: Any) -> DeviceInfo:
    """The loopback endpoint shadowing the current default output device.

    Falls back to a name match over the full list when the convenience call is missing:
    the vendor API is unverified (AS-2), and a fallback that finds the same device by a
    different route is cheaper than a failed capture on the user's first run.
    """
    getter = getattr(pa, "get_default_wasapi_loopback", None)
    if getter is not None:
        raw = getter()
        if raw:
            return _as_info(raw, DeviceKind.LOOPBACK)

    default_output = pa.get_default_output_device_info()
    wanted = str(default_output.get("name", ""))
    for device in loopback_devices(pa):
        # Loopback endpoints are conventionally named after the output they shadow, with
        # a suffix. Substring rather than equality for that reason.
        if wanted and wanted in device.name:
            return device
    raise DeviceError(
        "no WASAPI loopback device for the default output. Is anything set as the "
        "default playback device?"
    )


def default_microphone(pa: Any) -> DeviceInfo:
    raw = pa.get_default_input_device_info()
    if not raw:
        raise DeviceError("no default input device; is a microphone connected?")
    return _as_info(raw, DeviceKind.MICROPHONE)


def describe(pa: Any) -> list[DeviceInfo]:
    """Everything we could capture from. Used by the spike script and the setup wizard."""
    found: list[DeviceInfo] = []
    try:
        found.extend(loopback_devices(pa))
    except Exception as exc:  # noqa: BLE001 — a broken enumerator must not hide the mic
        raise DeviceError(f"loopback enumeration failed: {exc}") from exc
    with contextlib.suppress(DeviceError):
        # A missing mic is a state the caller has to handle anyway (FR39b), not a reason
        # to withhold the loopback devices it did find.
        found.append(default_microphone(pa))
    return found


@dataclass(frozen=True)
class DeviceChange:
    kind: DeviceKind
    previous: DeviceInfo | None
    current: DeviceInfo | None

    @property
    def lost(self) -> bool:
        """FR39b: no replacement available. The session pauses rather than dying."""
        return self.current is None

    @property
    def replaced(self) -> bool:
        """FR39a: a different device is now the default. Re-bind and keep running."""
        return self.current is not None and self.previous is not None


OnChange = Callable[[DeviceChange], None]


class DefaultDeviceWatcher:
    """Polls the default loopback and mic, and reports changes (FR39).

    A thread rather than a timer because it has to keep working while the UI thread is
    busy; a daemon thread because a watcher must never hold the process open.
    """

    def __init__(
        self,
        pa: Any,
        on_change: OnChange,
        *,
        interval_s: float = POLL_INTERVAL_S,
    ) -> None:
        self._pa = pa
        self._on_change = on_change
        self._interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._current: dict[DeviceKind, DeviceInfo | None] = {}

    def prime(self) -> None:
        """Record the current defaults **without** reporting them as changes.

        Without this the first poll reports every device as newly appeared, and a
        consumer that re-binds on change would re-bind immediately at startup.
        """
        for kind in DeviceKind:
            self._current[kind] = self._read(kind)

    def poll_once(self) -> list[DeviceChange]:
        """One comparison pass. Separated from the loop so it is testable without
        threads, sleeps or a clock."""
        changes: list[DeviceChange] = []
        for kind in DeviceKind:
            previous = self._current.get(kind)
            current = self._read(kind)
            if _same(previous, current):
                continue
            self._current[kind] = current
            changes.append(DeviceChange(kind=kind, previous=previous, current=current))
        return changes

    def start(self) -> None:
        if self._thread is not None:
            return
        self.prime()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="device-watcher", daemon=True)
        self._thread.start()

    def stop(self, timeout_s: float = 2.0) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=timeout_s)

    def _run(self) -> None:
        while not self._stop.wait(self._interval_s):
            try:
                changes = self.poll_once()
            except Exception:  # noqa: BLE001 — enumeration throws while devices churn
                # A device being removed mid-enumeration raises from the C layer. That is
                # the exact moment this watcher exists for, so it must not be the moment
                # it dies.
                continue
            for change in changes:
                self._on_change(change)

    def _read(self, kind: DeviceKind) -> DeviceInfo | None:
        try:
            if kind is DeviceKind.LOOPBACK:
                return default_loopback(self._pa)
            return default_microphone(self._pa)
        except Exception:  # noqa: BLE001 — "no device" is a state, not an error
            return None


def _same(a: DeviceInfo | None, b: DeviceInfo | None) -> bool:
    """Compared on **name**, not index.

    PortAudio reindexes when the device list changes, so the same physical device can
    move index and would otherwise report as replaced — re-binding a stream that was
    working perfectly, mid-interview.
    """
    if a is None or b is None:
        return a is b
    return a.name == b.name
