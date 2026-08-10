"""Matching pipeline: sequence gate, dispatch policy, degraded fallback (T4.3–T4.6).

Design §5 and §5a. Three properties here have each had a hole found in them at
specification stage, so they are written to be checked rather than believed:

1. **The gate compares against the latest *issued* sequence, not the last rendered
   one.** With A and B both outstanding, a "greater than last rendered" test lets A
   render when it returns first, even though B already supersedes it.
2. **Sequence numbers advance at queue time, not issue time.** Otherwise, with A in
   flight and B merely pending, A still matches `_latest_issued` and renders a snippet
   for the previous question.
3. **A session nonce accompanies the sequence.** Purge resets the counter, so without
   a nonce a pre-purge response carrying seq=1 satisfies a post-purge session's seq=1
   and renders wiped content — violating FR59 through the mechanism meant to enforce it.

Cancellation is deliberately *not* part of any of this. The stage-2 call is a blocking
HTTP request on a worker thread and Python cannot cancel it from outside, so
correctness rests on the gate discarding late results, never on a cancel landing.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Protocol

from interview_prep_recall.diagnostics.ring import DiagnosticRing
from interview_prep_recall.matching.prefilter import Candidate, Prefilter
from interview_prep_recall.matching.selector import Stage2Selector
from interview_prep_recall.stt.assembler import Utterance

INTERVIEWER_STREAM = "interviewer"

CALL_CEILING_DEFAULT = 400
"""Per-session stage-2 attempt ceiling (FR40).

Counts **attempts**, retries included, because cost and rate-limit pressure are per
attempt. The design left this ambiguous; counting attempts is the honest reading.
"""

MAX_RETRIES = 1
"""FR40: at most one retry, on 429/5xx only."""

RETRY_BACKOFF_S = 0.5
"""FR40 says "retried at most once **with backoff**". Retrying a 429 instantly is
worse than not retrying at all — it spends the second attempt while the limit is
still in force."""


class Outcome(Enum):
    CONFIRMED = auto()
    """Stage 2 selected this note."""

    DEGRADED = auto()
    """Stage-1 fallback above τ_degraded, rendered in the FR51 degraded visual state."""

    NO_MATCH = auto()
    """Nothing cleared the bar. The overlay shows nothing (FR50)."""


@dataclass(frozen=True)
class MatchResult:
    outcome: Outcome
    note_id: str | None
    seq: int
    nonce: uuid.UUID
    similarity: float | None = None


def is_retryable(exc: BaseException) -> bool:
    """429 and 5xx only. A protocol violation or a bad request is not worth repeating."""
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    if not isinstance(status, int):
        return False
    return status == 429 or 500 <= status < 600


class CallRunner(Protocol):
    """Runs a stage-2 call off the matching worker.

    Abstracted so tests can complete calls out of order deterministically — the T4.3
    race is not reproducible with `sleep()`, and a timing-dependent test that passes on
    CI and fails on a loaded laptop is worse than no test.
    """

    def submit(
        self, fn: Callable[[], Any], on_done: Callable[[Any, BaseException | None], None]
    ) -> None: ...


class InlineRunner:
    """Runs the call immediately on the calling thread."""

    def submit(
        self, fn: Callable[[], Any], on_done: Callable[[Any, BaseException | None], None]
    ) -> None:
        # The try must wrap `fn()` alone. Wrapping the `on_done` call as well means an
        # exception raised *by the callback* re-enters it as a failure, emitting twice
        # for one request.
        try:
            value, error = fn(), None
        except Exception as exc:  # noqa: BLE001 — the pipeline classifies it
            value, error = None, exc
        on_done(value, error)


class MatchingPipeline:
    def __init__(
        self,
        prefilter: Prefilter,
        selector: Stage2Selector | None,
        on_result: Callable[[MatchResult], None],
        ring: DiagnosticRing | None = None,
        runner: CallRunner | None = None,
        call_ceiling: int = CALL_CEILING_DEFAULT,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.prefilter = prefilter
        self.selector = selector
        self.on_result = on_result
        self.ring = DiagnosticRing() if ring is None else ring
        self.runner = runner or InlineRunner()
        self.call_ceiling = call_ceiling
        self._sleep = sleep

        self._nonce = uuid.uuid4()
        self._latest_issued = 0
        self._in_flight: tuple[Utterance, int, list[Candidate], uuid.UUID] | None = None
        self._pending: tuple[Utterance, int, list[Candidate]] | None = None
        self._attempts = 0
        self._local_only = selector is None
        self._ceiling_degraded = False
        """True when local-only was forced by the ceiling rather than chosen by the user."""

    # ---------- state ----------

    @property
    def nonce(self) -> uuid.UUID:
        return self._nonce

    @property
    def latest_issued(self) -> int:
        return self._latest_issued

    @property
    def in_flight(self) -> bool:
        return self._in_flight is not None

    @property
    def attempts(self) -> int:
        """Stage-2 HTTP attempts this session, retries included."""
        return self._attempts

    @property
    def local_only(self) -> bool:
        """True once the ceiling is hit, the switch is off, or no selector exists."""
        return self._local_only

    def set_local_only(self, value: bool) -> None:
        """FR37 mid-session degradation switch. User-initiated: survives a purge."""
        self._local_only = value or self.selector is None
        self._ceiling_degraded = False
        self.ring.record("matching_mode", degraded=self._local_only)

    def _degrade_for_ceiling(self) -> None:
        """Forced degradation (FR40). Distinguished from the user's own switch so a
        purge can clear it without also undoing a deliberate preference."""
        self._local_only = True
        self._ceiling_degraded = True
        self.ring.record("matching_mode", degraded=True, cause="ceiling")

    def purge(self) -> None:
        """Panic clear / purge **within** a session (FR15, FR59, FR64).

        Rotates the nonce so anything in flight can never render, and resets the
        sequence. It deliberately does **not** reset the attempt counter or clear a
        ceiling-induced degradation: D-U5 makes panic clear resumable — `WIPED → RUNNING`
        is the same session — so FR40's *per-session* budget must survive it. Resetting
        here would hand a fresh 400-call budget to anyone who pressed the panic button.
        """
        self._nonce = uuid.uuid4()
        self._latest_issued = 0
        self._in_flight = None
        self._pending = None
        self.ring.record("matching_purged")

    def start_session(self) -> None:
        """Begin a new session (`IDLE → RUNNING`). Resets everything purge preserves.

        The distinction matters: `purge()` alone served both paths, which meant either
        the ceiling leaked across sessions or a panic clear refilled it. They are
        different transitions in design §6 and need different resets.
        """
        self.purge()
        self._attempts = 0
        if self._ceiling_degraded:
            self._ceiling_degraded = False
            self._local_only = self.selector is None
        self.ring.record("matching_session_started")

    # ---------- input ----------

    def submit(self, utterance: Utterance) -> int:
        """Queue an interviewer utterance. Returns its sequence number.

        Rejects any other stream (FR53/D-10): the mic feeds the progress tracker, and
        matching on the user's own speech would surface notes about what they just said.
        """
        if utterance.stream_id != INTERVIEWER_STREAM:
            raise ValueError(
                f"matching consumes the interviewer stream only; got {utterance.stream_id!r}"
            )

        # Sequence advances here, at queue time. See module docstring, property 2.
        self._latest_issued += 1
        seq = self._latest_issued

        candidates = self.prefilter.candidates(utterance.text)
        self.ring.record("prefilter", seq=seq, candidates=len(candidates))

        if not candidates:
            self._emit(MatchResult(Outcome.NO_MATCH, None, seq, self._nonce))
            return seq

        if self._local_only:
            self._emit(self._fallback(candidates, seq))
            return seq

        self._dispatch(utterance, seq, candidates)
        return seq

    # ---------- dispatch ----------

    def _dispatch(self, utterance: Utterance, seq: int, candidates: list[Candidate]) -> None:
        if self._in_flight is None:
            self._issue(utterance, seq, candidates)
        else:
            # One pending slot, newest wins. A displaced utterance is dropped without a
            # call — that is what bounds cost and rate-limit exposure (FR40).
            if self._pending is not None:
                self.ring.record("pending_displaced", seq=self._pending[1])
            self._pending = (utterance, seq, candidates)

    def _issue(self, utterance: Utterance, seq: int, candidates: list[Candidate]) -> None:
        nonce = self._nonce
        self._in_flight = (utterance, seq, candidates, nonce)
        self.ring.record("stage2_issued", seq=seq, candidates=len(candidates))

        def call() -> Any:
            return self._call_with_retry(utterance, candidates)

        def done(value: Any, exc: BaseException | None) -> None:
            self._on_complete(seq, nonce, candidates, value, exc)

        self.runner.submit(call, done)

    def _call_with_retry(self, utterance: Utterance, candidates: list[Candidate]) -> str | None:
        assert self.selector is not None
        last: BaseException | None = None
        for attempt in range(MAX_RETRIES + 1):
            if self._attempts >= self.call_ceiling:
                raise RuntimeError("stage-2 call ceiling reached")
            self._attempts += 1
            try:
                return self.selector.select(utterance, candidates)
            except Exception as exc:  # noqa: BLE001
                last = exc
                if attempt >= MAX_RETRIES or not is_retryable(exc):
                    break
                self.ring.record("stage2_retry", retry=attempt + 1)
                self._sleep(RETRY_BACKOFF_S)
        assert last is not None
        raise last

    def _on_complete(
        self,
        seq: int,
        nonce: uuid.UUID,
        candidates: list[Candidate],
        value: Any,
        exc: BaseException | None,
    ) -> None:
        # Match on (nonce, seq), not seq alone. Sequences restart at every purge, so a
        # stale pre-purge completion can carry the same seq as a live post-purge call;
        # clearing on seq alone would free the slot while that call is still running and
        # let a second call be issued — silently breaking the one-in-flight invariant the
        # whole gate depends on.
        if (
            self._in_flight is not None
            and self._in_flight[1] == seq
            and self._in_flight[3] == nonce
        ):
            self._in_flight = None

        if exc is not None:
            self._handle_failure(exc, seq, nonce, candidates)
        else:
            note_id = value
            result = (
                MatchResult(Outcome.NO_MATCH, None, seq, nonce)
                if note_id is None
                else MatchResult(
                    Outcome.CONFIRMED,
                    note_id,
                    seq,
                    nonce,
                    self._similarity_of(candidates, note_id),
                )
            )
            self._emit(result)

        if self._pending is not None and self._in_flight is None:
            pending, self._pending = self._pending, None
            self._issue(*pending)

    def _handle_failure(
        self, exc: BaseException, seq: int, nonce: uuid.UUID, candidates: list[Candidate]
    ) -> None:
        ceiling_hit = isinstance(exc, RuntimeError) and "ceiling" in str(exc)
        code = "ceiling" if ceiling_hit else type(exc).__name__
        self.ring.record("stage2_failed", seq=seq, cause=code[:64])

        # Retryability is irrelevant here: the budget is spent either way, and gating
        # on it meant a ceiling reached via a 400 was never announced (FR40 requires the
        # user be told, not silently downgraded).
        if ceiling_hit or self._attempts >= self.call_ceiling:
            self._degrade_for_ceiling()

        # FR49: fall back only above τ_degraded, and mark it. Below that, show nothing.
        result = self._fallback(candidates, seq, nonce)
        self._emit(result)

    def _fallback(
        self, candidates: list[Candidate], seq: int, nonce: uuid.UUID | None = None
    ) -> MatchResult:
        nonce = nonce if nonce is not None else self._nonce
        best = candidates[0]
        if best.similarity >= self.prefilter.tau_degraded:
            return MatchResult(Outcome.DEGRADED, best.note_id, seq, nonce, best.similarity)
        return MatchResult(Outcome.NO_MATCH, None, seq, nonce)

    @staticmethod
    def _similarity_of(candidates: list[Candidate], note_id: str) -> float | None:
        return next((c.similarity for c in candidates if c.note_id == note_id), None)

    # ---------- gate ----------

    def _emit(self, result: MatchResult) -> None:
        """The sequence gate. Nothing reaches the overlay except through here."""
        if result.nonce != self._nonce or result.seq != self._latest_issued:
            self.ring.record("stale_response_discarded", seq=result.seq)
            return
        self.ring.record(
            "match_emitted", seq=result.seq, state=result.outcome.name, note_id=result.note_id
        )
        self.on_result(result)
