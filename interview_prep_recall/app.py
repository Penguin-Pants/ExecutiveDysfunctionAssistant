"""Headless composition root (T9.0).

Every component so far has been built to be constructed by somebody else — Protocols for
the cipher, the embedder, the STT connector, the model client, injected rings and
monitors everywhere. This is the somebody else. No Qt: the UI layer builds on top of an
`Application`, it does not *contain* one, which is what makes the wiring testable on a
machine that cannot run the UI at all.

**The wiring is the point, not the plumbing.** Three guarantees in this codebase are
properties of how the pieces are connected rather than of any piece:

* **One switch, every cloud consumer** (D-23). `llm_matching` off must reach matching
  *and* report generation. It reached the pipeline only, because the pipeline was the
  only consumer when the switch was written. A second consumer arrived in M11 and
  nothing connected it — the indicator would have said local-only while report
  generation still called the API.
* **Finalised utterances reach the record** (FR74). The record existed with no producer.
* **Coverage has one adjudicator** (FR78a). The tracker decides; the report is *told*.

Each of those was recorded as a follow-up "needs the composition root". This is it.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from interview_prep_recall.diagnostics.ring import DiagnosticRing
from interview_prep_recall.matching.pipeline import MatchingPipeline, MatchResult
from interview_prep_recall.matching.prefilter import Prefilter
from interview_prep_recall.matching.selector import Stage2Selector
from interview_prep_recall.notes.index import Embedder, EmbeddingIndex
from interview_prep_recall.notes.model import ContextSet
from interview_prep_recall.report.consent import ReportConsent
from interview_prep_recall.report.generator import (
    MessagesClient,
    Report,
    ReportGenerator,
    ReportUnavailableError,
)
from interview_prep_recall.report.record import SessionRecord
from interview_prep_recall.report.store import Cipher, SessionStore
from interview_prep_recall.session.health import HealthMonitor
from interview_prep_recall.session.manager import PurgeHooks, SessionManager
from interview_prep_recall.stt.assembler import StreamRouter, Utterance
from interview_prep_recall.stt.fallback import EgressMonitor
from interview_prep_recall.tracker.progress import ProgressTracker


class BackgroundCallRunner:
    """Runs stage-2 calls off the caller's thread (design D-1).

    Without this, `MatchingPipeline` falls back to `InlineRunner` and the model request
    executes inside `consume()` — on the thread delivering utterances. With the real
    client that blocks span routing for the 5 s request timeout, plus a retry, so
    subsequent finalised spans are neither recorded nor queued while it waits. The
    one-in-flight/one-pending policy exists precisely so calls can overlap arrivals, and
    an inline runner makes it unreachable.

    **One worker**, not a pool: the pipeline already permits at most one call in flight,
    so extra threads could only add concurrency the design forbids.
    """

    def __init__(self) -> None:
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stage2")

    def submit(
        self, fn: Callable[[], Any], on_done: Callable[[Any, BaseException | None], None]
    ) -> None:
        def run() -> None:
            # The try wraps `fn()` alone. Wrapping `on_done` too means an exception
            # raised *by the callback* re-enters it as a failure and emits twice for one
            # request — the defect `InlineRunner` already documents.
            try:
                result = fn()
            except BaseException as exc:  # noqa: BLE001 — reported, never swallowed
                on_done(None, exc)
                return
            on_done(result, None)

        self._pool.submit(run)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


class LocalOnlyTarget(Protocol):
    """Anything that talks to the API and must honour FR37."""

    def set_local_only(self, value: bool) -> None: ...


@dataclass
class CloudSwitchFanout:
    """Applies the FR37 `llm_matching` switch to **every** consumer that calls the API.

    `SessionManager.attach_matching` takes one `MatchingTarget`, because when the switch
    was written the pipeline was the only thing that talked to Anthropic. M11 added a
    second consumer and the single-target design had no way to express it — so the switch
    would have gone off, the indicator would have read local-only, and report generation
    would have kept sending the whole transcript.

    A fan-out rather than a wider Protocol: consumers get added, and the next one should
    fail loudly at registration rather than be silently omitted. `targets` is asserted
    non-empty for exactly that reason.
    """

    targets: list[LocalOnlyTarget] = field(default_factory=list)

    def register(self, target: LocalOnlyTarget) -> None:
        if not hasattr(target, "set_local_only"):
            raise TypeError(f"{type(target).__name__} has no set_local_only; it cannot honour FR37")
        self.targets.append(target)

    def set_local_only(self, value: bool) -> None:
        if not self.targets:
            raise RuntimeError(
                "no cloud consumers registered — flipping the switch would light the "
                "local-only indicator while nothing had actually been switched (D-23)"
            )
        for target in self.targets:
            target.set_local_only(value)


class ReportLocalOnlyAdapter:
    """Gives `ReportGenerator` the `set_local_only` shape the fan-out registers.

    A one-line adapter rather than renaming the generator's field: `local_only` reads
    correctly at the generator (it is a property of that generator), and `set_local_only`
    reads correctly at the switch (it is an instruction). Making one of them wrong to
    avoid four lines here would be the wrong trade.
    """

    def __init__(self, generator: ReportGenerator) -> None:
        self._generator = generator

    def set_local_only(self, value: bool) -> None:
        self._generator.local_only = value


@dataclass
class Application:
    """Everything wired, nothing rendered.

    Constructed with the pieces that differ by environment — the embedder, the model
    client, the cipher — so a test builds one with doubles and gets the *real* wiring.
    That is the whole point: the defects this closes were all in the connections, and a
    composition root that could only be exercised with real dependencies would leave them
    exactly as untested as they were.
    """

    root: Path
    embedder: Embedder
    client: MessagesClient
    cipher: Cipher
    context_set: ContextSet
    on_result: Callable[[MatchResult], None] = lambda _result: None
    retention_days: int | None = 30

    ring: DiagnosticRing = field(init=False)
    monitor: HealthMonitor = field(init=False)
    egress: EgressMonitor = field(init=False)
    index: EmbeddingIndex = field(init=False)
    prefilter: Prefilter = field(init=False)
    pipeline: MatchingPipeline = field(init=False)
    tracker: ProgressTracker = field(init=False)
    router: StreamRouter = field(init=False)
    record: SessionRecord = field(init=False)
    sessions: SessionStore = field(init=False)
    consent: ReportConsent = field(init=False)
    reports: ReportGenerator = field(init=False)
    session: SessionManager = field(init=False)
    switches: CloudSwitchFanout = field(init=False)
    runner: BackgroundCallRunner = field(init=False)

    def __post_init__(self) -> None:
        self.ring = DiagnosticRing()
        self.monitor = HealthMonitor()
        self.egress = EgressMonitor(self.monitor)

        self.index = EmbeddingIndex(self.root, self.embedder)
        self.index.build(self.context_set)
        self.prefilter = Prefilter(self.index, self.context_set, self.embedder)
        self.runner = BackgroundCallRunner()
        self.pipeline = MatchingPipeline(
            prefilter=self.prefilter,
            selector=Stage2Selector(self.client),
            on_result=self.on_result,
            ring=self.ring,
            runner=self.runner,
        )

        self.tracker = ProgressTracker(
            note_set=self.context_set,
            index=self.index,
            embedder=self.embedder,
            ring=self.ring,
        )
        self.router = StreamRouter()
        self.record = SessionRecord(ring=self.ring)

        self.sessions = SessionStore(
            self.root, cipher=self.cipher, ring=self.ring, retention_days=self.retention_days
        )
        self.consent = ReportConsent(self.root / "report_consent.json")
        self.reports = ReportGenerator(
            client=self.client,
            consent=self.consent,
            egress=self.egress,
            ring=self.ring,
        )

        # The fan-out, and the reason this class exists.
        self.switches = CloudSwitchFanout()
        self.switches.register(self.pipeline)
        self.switches.register(ReportLocalOnlyAdapter(self.reports))

        # **Only two of the five purge hooks have a component to wire to yet.**
        # `stop_capture` and `zero_audio` belong to M1, `clear_overlay` to M5, and
        # neither exists. `PurgeHooks` defaults them to no-ops, so a purge today reports
        # every step as run and audio as cleared — vacuously true while there is no
        # capture, and a false statement the moment M1 lands without touching this line.
        # `wired_purge_hooks()` names the current set so a test can pin it and force the
        # question then, rather than trusting whoever writes M1 to remember.
        self.session = SessionManager(
            hooks=PurgeHooks(
                cancel_network=self.pipeline.purge,
                drop_transcript=self.record.clear,
            ),
            ring=self.ring,
            monitor=self.monitor,
        )
        self.session.attach_matching(self.switches)

    # ---------- the utterance path ----------

    def consume(self, utterance: Utterance, now: float) -> None:
        """One finalised span, routed to everything that needs it.

        **The record is fed here, before routing**, and from both streams. FR74 wants the
        whole meeting; the router splits by purpose (matching sees the interviewer only,
        the tracker the mic only), so feeding the record downstream of it would silently
        record half the conversation.

        **The FR37 tracker switch is read every call**, not captured at construction.
        `set_switch("progress_tracker", False)` only writes a field on `SessionManager`;
        nothing downstream consults it, so without this the checklist keeps marking
        points while the switch reports tracking as off — the D-23 shape again, in the
        one place the user can watch it being wrong.
        """
        self.record.add(utterance)
        self.router.route(utterance)

        tracking = self.session.switches.progress_tracker
        for question in self.router.drain_matching():
            self.pipeline.submit(question)
            if tracking:
                self.tracker.observe_interviewer(question)
        for answer in self.router.drain_tracking():
            if tracking:
                self.tracker.submit_user(answer, now)
        if tracking:
            self.tracker.tick(now)

    # ---------- the report path ----------

    def missed_note_ids(self) -> frozenset[str]:
        """FR78a. The tracker's verdict, and the report is told rather than asked.

        Derived here rather than inside the generator so there is exactly one place the
        answer comes from. A generator that re-derived it would eventually disagree with
        the checklist the user watched, and nothing would reconcile them.

        **Flushes the tracker, so it is not a pure query.** Held mic utterances have to be
        adjudicated before "what was missed" means anything — asking while spans are still
        in the hold window reports points as uncovered that are one `tick` from marked.
        """
        self.tracker.flush()
        marked = self.tracker.marked_ids
        return frozenset(n.id for n in self.context_set.tracked() if n.id not in marked)

    def end_session(self, *, role: str) -> str | None:
        """Stop the session. **Persists the record before the purge clears it.**

        Ordering is the entire content of this method. `SessionManager.end_session()`
        runs the purge, and `drop_transcript` is wired to `record.clear` — so ending an
        interview without storing first destroys the transcript, and with it both the
        report and the persisted record D-U8 traded the no-disk guarantee for. There was
        no application-level stop path at all before this, which meant the only way to
        end a session was the one that lost it.

        Returns the stored id, or `None` if nothing was recorded.
        """
        session_id: str | None = None
        if len(self.record):
            session_id = self.sessions.save(
                self.record, role=role, missed_note_ids=self.missed_note_ids()
            )
        self.session.end_session()
        return session_id

    def generate_report(
        self,
        *,
        confirm: Callable[[int], bool],
        session_id: str | None = None,
        role: str = "",
    ) -> tuple[str, Report]:
        """Generate a report and attach it to its stored session. Returns (id, report).

        **Reads from the store, not from live memory**, whenever `session_id` is given.
        Regenerating an old report is precisely what D-U8 bought, and a week later there
        is no live record and no live tracker — so the transcript *and* the tracker's
        coverage verdict both have to come off disk (FR78a).

        With no `session_id` the live record is stored first, so the interview survives a
        declined, offline or rate-limited generation instead of being lost exactly when
        the model was unavailable.
        """
        if session_id is None:
            if not len(self.record):
                raise ReportUnavailableError("Nothing was recorded in this session.")
            missed = self.missed_note_ids()
            session_id = self.sessions.save(self.record, role=role, missed_note_ids=missed)
            record = self.record
        else:
            stored = self.sessions.load(session_id)
            record = SessionRecord.rehydrate(stored.utterances)
            missed = stored.missed_note_ids

        report = self.reports.generate(
            record, self.context_set, missed_note_ids=missed, confirm=confirm
        )
        self.sessions.attach_report(session_id, report.to_dict())
        return session_id, report

    # ---------- lifecycle ----------

    def reset_for_new_session(self) -> None:
        """Clear per-session data. **Does not drive the state machine.**

        Renamed off `start_session` because `SessionManager` owns starting a session and
        had a method by that name doing something else entirely. Two `start_session`s in
        one object graph, one of which silently does not transition, reads fine and wires
        wrong.
        """
        self.pipeline.start_session()
        self.record.clear()
        self.tracker.reset()

    def wired_purge_hooks(self) -> frozenset[str]:
        """Which FR59 purge hooks actually reach a component (see `__post_init__`).

        Exists to be asserted. The unwired hooks are no-ops that report success, so
        nothing else would notice them staying unwired once the components they need get
        built.
        """
        return frozenset({"cancel_network", "drop_transcript"})

    def sweep_retention(self) -> list[str]:
        """FR84's launch-time sweep.

        **No production caller yet**, and deliberately not called from `__post_init__`:
        constructing an `Application` must not delete the user's stored interviews as a
        side effect. The entry point owns this, and there is no entry point until the UI
        lands — recorded rather than left to be noticed, because a documented-but-uncalled
        method is this codebase's most repeated defect (D-20).
        """
        return self.sessions.sweep_expired()
