"""T9.6 — the startup sequence, without Qt.

The *order* is what carries the guarantees here, so the tests are about order: consent
before construction, a config reset reported rather than swallowed, preflight run without
being asked. Each of those is a rule this codebase already learned somewhere else, and
this is the first place they all have to hold at once.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from helpers import ReversingCipher, ScriptedClient

from interview_prep_recall.app import Application
from interview_prep_recall.config import (
    CONFIG_FILENAME,
    AppConfig,
    ConfigStore,
    SttBackendChoice,
)
from interview_prep_recall.first_run import CONSENT_FILENAME, FirstRunConsent
from interview_prep_recall.notes.model import ContextSet, Note, SourceKind
from interview_prep_recall.startup import (
    CONFIG_RESET_NOTICE,
    StartupOutcome,
    start,
)


class FlatEmbedder:
    """Same shape as `test_app.FlatEmbedder`: the `Embedder` Protocol is `encode`."""

    model_id = "flat/one"
    model_version = "1.0"

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.ones((len(texts), 2), dtype=np.float32)


def _context() -> ContextSet:
    return ContextSet(
        name="prep",
        notes=[Note(headline="Tell me about scaling", kind=SourceKind.PREP)],
    )


def _builder(calls: list[Path] | None = None):
    def build(root: Path) -> Application:
        if calls is not None:
            calls.append(root)
        return Application(
            root=root,
            embedder=FlatEmbedder(),
            client=ScriptedClient(),
            cipher=ReversingCipher(),
            context_set=_context(),
        )

    return build


def accept(_text: str) -> bool:
    return True


def decline(_text: str) -> bool:
    return False


# ---------- consent comes first ----------


def test_declining_consent_builds_nothing(tmp_path: Path) -> None:
    """FR63's disclosure is unavoidable, and a refusal must leave no trace.

    A gate that runs *after* the composition root has created directories, built an
    index and loaded the user's notes is a gate that ran too late. The strongest
    statement of "nothing was constructed" is that the factory was never called and the
    directory is still empty.
    """
    calls: list[Path] = []
    result = start(tmp_path, present=decline, build_application=_builder(calls))

    assert result.outcome is StartupOutcome.CONSENT_DECLINED
    assert result.outcome.may_run is False
    assert result.application is None
    assert calls == [], "the composition root must not be built for a declined start"
    assert list(tmp_path.iterdir()) == []


def test_accepting_consent_builds_the_application(tmp_path: Path) -> None:
    result = start(tmp_path, present=accept, build_application=_builder())

    assert result.application is not None
    assert result.outcome.may_run is True
    assert (tmp_path / CONSENT_FILENAME).exists()


def test_consent_is_not_re_asked_once_given(tmp_path: Path) -> None:
    FirstRunConsent(tmp_path / CONSENT_FILENAME).acknowledge()
    shown: list[str] = []

    def present(text: str) -> bool:
        shown.append(text)
        return True

    start(tmp_path, present=present, build_application=_builder())
    assert shown == []


# ---------- a config reset is reported ----------


def test_a_reset_config_produces_a_notice(tmp_path: Path) -> None:
    """`ConfigLoadStatus.settings_were_lost` had **no production consumer** before this
    module — D-20 again, in code I wrote while calling the notification load-bearing.

    Design §4 requires the user be told. A silent reset is the failure that actually
    happens: sensitivity reverts, they do not notice, and they conclude matching is
    broken.
    """
    FirstRunConsent(tmp_path / CONSENT_FILENAME).acknowledge()
    (tmp_path / CONFIG_FILENAME).write_text("{not json", encoding="utf-8")

    result = start(tmp_path, present=accept, build_application=_builder())

    assert CONFIG_RESET_NOTICE in result.notices


def test_a_healthy_config_produces_no_notice(tmp_path: Path) -> None:
    """A notice on every launch is a notice nobody reads."""
    FirstRunConsent(tmp_path / CONSENT_FILENAME).acknowledge()
    ConfigStore(tmp_path).save(AppConfig(tau_floor=0.42))

    result = start(tmp_path, present=accept, build_application=_builder())

    assert result.notices == ()
    assert result.application is not None
    assert result.application.config.tau_floor == pytest.approx(0.42)


def test_first_run_is_not_reported_as_a_loss(tmp_path: Path) -> None:
    result = start(tmp_path, present=accept, build_application=_builder())
    assert result.notices == ()


# ---------- FR38 preflight runs automatically ----------


def test_preflight_runs_without_being_asked(tmp_path: Path) -> None:
    """FR38: "runs **automatically** at session start", not when the user remembers.

    The product is for someone whose stated difficulty is executive function; a readiness
    step that depends on remembering to run it is designed against its own user.
    """
    result = start(tmp_path, present=accept, build_application=_builder())

    assert result.preflight is not None
    assert result.preflight.results, "preflight produced no results at all"


def test_missing_probes_block_rather_than_pass(tmp_path: Path) -> None:
    """With no audio devices there are no probes, and `Preflight` treats an unprobed
    check as unsatisfied. That is the correct answer on this machine and the honest one:
    a session cannot start."""
    result = start(tmp_path, present=accept, build_application=_builder())

    assert result.outcome is StartupOutcome.NOT_READY
    assert result.preflight is not None
    blocked_keys = {r.check.key for r in result.preflight.blockers}
    assert {"loopback_device", "mic_device"} <= blocked_keys


def test_not_ready_still_runs(tmp_path: Path) -> None:
    """An app that quits on a failed readiness check is an app the user cannot repair —
    Settings and the setup wizard are how they fix what is blocking them."""
    result = start(tmp_path, present=accept, build_application=_builder())

    assert result.outcome is StartupOutcome.NOT_READY
    assert result.outcome.may_run is True
    assert result.application is not None


def test_all_probes_passing_is_ready(tmp_path: Path) -> None:
    from interview_prep_recall.session.preflight import CHECKS

    probes = {c.key: (lambda: True) for c in CHECKS}
    result = start(tmp_path, present=accept, build_application=_builder(), probes=probes)

    assert result.outcome is StartupOutcome.READY
    assert result.preflight is not None
    assert result.preflight.blocked is False


def test_cloud_checks_only_apply_to_a_cloud_backend(tmp_path: Path) -> None:
    """Warning about an API key the user deliberately did not provide is noise, and
    FR18 makes local the default."""
    FirstRunConsent(tmp_path / CONSENT_FILENAME).acknowledge()
    ConfigStore(tmp_path).save(AppConfig(stt_backend=SttBackendChoice.LOCAL))

    result = start(tmp_path, present=accept, build_application=_builder())

    assert result.preflight is not None
    keys = {r.check.key for r in result.preflight.results}
    assert "api_key_valid" not in keys
    assert "stt_reachable" not in keys


def test_cloud_checks_apply_when_a_cloud_backend_is_configured(tmp_path: Path) -> None:
    FirstRunConsent(tmp_path / CONSENT_FILENAME).acknowledge()
    ConfigStore(tmp_path).save(AppConfig(stt_backend=SttBackendChoice.DEEPGRAM))

    result = start(tmp_path, present=accept, build_application=_builder())

    assert result.preflight is not None
    keys = {r.check.key for r in result.preflight.results}
    assert {"api_key_valid", "stt_reachable"} <= keys


def test_preflight_records_into_the_applications_ring(tmp_path: Path) -> None:
    """One ring per application, so the diagnostics viewer sees startup too."""
    result = start(tmp_path, present=accept, build_application=_builder())

    assert result.application is not None
    events = {e.event for e in result.application.ring.snapshot()}
    assert "preflight" in events
