"""Pre-session readiness check (T6.5, FR38 — design §6's classification table).

Runs **automatically** at session start, not when the user remembers to. The whole
product is for someone whose stated difficulty is executive function; a readiness step
that depends on remembering to perform it is designed against its own user.

Three outcomes, not two. The classification is the requirement — T6.5's criterion is
"produces the correct block-vs-warn classification", which is untestable unless the
classification exists somewhere other than in the implementer's head.

Probes are injected. The real ones touch WASAPI, the registry and the network and only
run on Windows; the classification logic they feed is platform-free and tested here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum, auto

from interview_prep_recall.diagnostics.ring import DiagnosticRing


class CheckClass(Enum):
    BLOCK = auto()
    """Hard failure. The session does not start."""

    WARN = auto()
    """Surfaced loudly; the user decides whether to proceed."""


@dataclass(frozen=True)
class Check:
    key: str
    label: str
    cls: CheckClass
    cloud_only: bool = False


CHECKS: tuple[Check, ...] = (
    Check("loopback_device", "System audio (interviewer)", CheckClass.BLOCK),
    Check("mic_device", "Microphone (you)", CheckClass.BLOCK),
    Check("notes_loaded", "Notes loaded", CheckClass.BLOCK),
    Check("windows_build", "Windows build", CheckClass.BLOCK),
    # Warn, not block: blocking would permanently strand a user whose machine always
    # fails this, with no remedy available to them. FR14a's persistent warning is the
    # mitigation, and the choice to proceed is theirs.
    Check("capture_excluded", "Hidden from screen share", CheckClass.WARN),
    Check("stt_reachable", "Transcription service", CheckClass.WARN, cloud_only=True),
    Check("api_key_valid", "Cloud transcription key", CheckClass.WARN, cloud_only=True),
    Check("llm_reachable", "Matching service", CheckClass.WARN),
    Check("echo_clear", "Headphones detected", CheckClass.WARN),
)

CHECKS_BY_KEY: Mapping[str, Check] = {c.key: c for c in CHECKS}


@dataclass(frozen=True)
class CheckResult:
    check: Check
    ok: bool
    detail: str | None = None

    @property
    def blocking(self) -> bool:
        return not self.ok and self.check.cls is CheckClass.BLOCK


@dataclass(frozen=True)
class PreflightReport:
    results: tuple[CheckResult, ...] = field(default_factory=tuple)

    @property
    def blocked(self) -> bool:
        return any(r.blocking for r in self.results)

    @property
    def blockers(self) -> list[CheckResult]:
        return [r for r in self.results if r.blocking]

    @property
    def warnings(self) -> list[CheckResult]:
        return [r for r in self.results if not r.ok and r.check.cls is CheckClass.WARN]

    @property
    def passed(self) -> list[CheckResult]:
        return [r for r in self.results if r.ok]

    def result_for(self, key: str) -> CheckResult | None:
        return next((r for r in self.results if r.check.key == key), None)


Probe = Callable[[], bool | tuple[bool, str]]


class Preflight:
    def __init__(
        self,
        probes: Mapping[str, Probe],
        *,
        cloud_enabled: bool = False,
        ring: DiagnosticRing | None = None,
    ) -> None:
        unknown = set(probes) - set(CHECKS_BY_KEY)
        if unknown:
            raise ValueError(f"probes for unknown checks: {sorted(unknown)}")
        self.probes = probes
        self.cloud_enabled = cloud_enabled
        self.ring = DiagnosticRing() if ring is None else ring

    def applicable(self) -> list[Check]:
        return [c for c in CHECKS if self.cloud_enabled or not c.cloud_only]

    def run(self) -> PreflightReport:
        results: list[CheckResult] = []
        for check in self.applicable():
            probe = self.probes.get(check.key)
            if probe is None:
                # A check with no probe is a missing capability, not a pass. Treating
                # it as satisfied would let an unimplemented check silently clear the
                # gate it exists to hold.
                results.append(CheckResult(check, ok=False, detail="no probe registered"))
            else:
                try:
                    outcome = probe()
                except Exception as exc:  # noqa: BLE001 — a throwing probe is a failure
                    results.append(CheckResult(check, ok=False, detail=type(exc).__name__))
                    continue
                if isinstance(outcome, tuple):
                    ok, detail = outcome
                else:
                    ok, detail = outcome, None
                results.append(CheckResult(check, ok=bool(ok), detail=detail))

        for r in results:
            self.ring.record(
                "preflight_check",
                reason=r.check.key,
                ok=r.ok,
                state=r.check.cls.name,
            )
        report = PreflightReport(tuple(results))
        self.ring.record("preflight", ok=not report.blocked, count=len(results))
        return report
