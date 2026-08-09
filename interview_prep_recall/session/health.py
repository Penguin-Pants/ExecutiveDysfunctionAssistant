"""Health model (design §7, FR35).

Health is **orthogonal to session state**, not part of it. A session in `RUNNING`
carries a health record; there is no `RUNNING_DEGRADED`. That is what keeps the state
count at seven instead of seven times a power of two.

The single most important property here, and the reason FR35 exists at all: **"nothing
in your notes matched" must be distinguishable from "the pipeline is broken."** Both
render an empty overlay. If they look the same, the user cannot tell working from
broken at the exact moment they most need to — so `nominal` is a first-class query and
`no match` is deliberately *not* an indicator.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum, auto


class Status(Enum):
    OK = auto()
    DEGRADED = auto()
    FAILED = auto()
    OFF = auto()


class MatchingStatus(Enum):
    OK = auto()
    LOCAL_ONLY = auto()
    FAILED = auto()
    OFF = auto()


class Egress(Enum):
    """Which paths are currently sending data off the device (FR20)."""

    NONE = auto()
    CLOUD_STT = auto()
    LLM = auto()
    BOTH = auto()

    @classmethod
    def of(cls, *, cloud_stt: bool, llm: bool) -> Egress:
        if cloud_stt and llm:
            return cls.BOTH
        if cloud_stt:
            return cls.CLOUD_STT
        if llm:
            return cls.LLM
        return cls.NONE


NO_AUDIO_AFTER_S = 8.0
"""Silence past this reads as "no audio detected", not as a quiet moment."""

FALLING_BEHIND_S = 2.0
"""Lag past this is user-visible and gets its own indicator (FR33)."""


@dataclass(frozen=True)
class Health:
    loopback: Status = Status.OFF
    mic: Status = Status.OFF
    stt_interviewer: Status = Status.OFF
    stt_user: Status = Status.OFF
    matching: MatchingStatus = MatchingStatus.OFF
    egress: Egress = Egress.NONE
    lag: float = 0.0
    """Seconds behind realtime."""

    silence_s: float = 0.0
    """Seconds since the last non-silent audio frame on the interviewer stream.

    Added beyond design §7's original field list: §7 named `no audio detected (Ns)` as
    a derived state but gave the record no field carrying N, so the state could not be
    expressed. Same class of gap as `capture_excluded` below.
    """

    capture_excluded: bool | None = None
    """FR14a. `None` before the check has run; `False` is the loud persistent warning.

    Also added beyond §7's field list, for the same reason — the section listed
    "NOT hidden from screen share" as a derived state with nothing to derive it from.
    """

    def indicators(self) -> list[str]:
        """Problem states, worst first. **Never includes "no match".**

        An empty list means everything is working. It does *not* mean nothing matched —
        that is content, not health, and conflating them is the OB-1 failure.
        """
        out: list[str] = []

        if self.capture_excluded is False:
            out.append("NOT hidden from screen share")

        if self.loopback is Status.FAILED or self.mic is Status.FAILED:
            out.append("audio lost")
        elif self.silence_s >= NO_AUDIO_AFTER_S and self.loopback is Status.OK:
            out.append(f"no audio detected ({int(self.silence_s)}s)")

        failed = [
            name
            for name, status in (
                ("interviewer", self.stt_interviewer),
                ("mic", self.stt_user),
            )
            if status is Status.FAILED
        ]
        for name in failed:
            out.append(f"STT unavailable ({name})")
        if not failed and Status.DEGRADED in (self.stt_interviewer, self.stt_user):
            out.append("STT degraded")

        if self.lag >= FALLING_BEHIND_S:
            out.append(f"falling behind — {self.lag:.0f}s")

        if self.matching is MatchingStatus.LOCAL_ONLY:
            out.append("matching: local-only")
        elif self.matching is MatchingStatus.FAILED:
            out.append("matching unavailable")

        return out

    @property
    def nominal(self) -> bool:
        """True when an empty overlay means "nothing matched", not "something broke"."""
        return not self.indicators()

    @property
    def capturing(self) -> bool:
        return self.loopback is Status.OK or self.mic is Status.OK

    @property
    def data_leaving_device(self) -> bool:
        return self.egress is not Egress.NONE

    def with_(self, **changes: object) -> Health:
        return replace(self, **changes)  # type: ignore[arg-type]


@dataclass
class HealthMonitor:
    """Mutable holder the watchdog updates and the UI reads.

    Deliberately thin: it owns no policy. Policy lives in the degradation ladder
    (design §9), and this only records what that ladder decided, so the two cannot
    drift into disagreeing about what "degraded" means.
    """

    health: Health = field(default_factory=Health)
    _history: list[Health] = field(default_factory=list)

    def update(self, **changes: object) -> Health:
        self._history.append(self.health)
        if len(self._history) > 64:
            self._history.pop(0)
        self.health = self.health.with_(**changes)
        return self.health

    def reset(self) -> Health:
        self.health = Health()
        self._history.clear()
        return self.health
