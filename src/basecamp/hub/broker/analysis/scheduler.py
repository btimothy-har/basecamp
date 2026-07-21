"""Event-driven analysis scheduler — run the analyzer when fresh turns land.

The daemon is a long-lived async process, so scheduling is reactive, not timed.
``notify(owner_id, seq)`` (called after a ``thread_report`` is persisted) bumps an
in-memory latest-seq and wakes a per-owner worker. Each worker is a single
sequential coroutine, which gives skip-in-flight and burst coalescing for free:
it debounces, then analyzes the newest thread only when ``latest_seq`` has advanced
past what was last analyzed (seeded from the persisted row so a daemon restart does
not re-run stale turns). "Laggy is fine" — nothing here blocks ingest.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from ...store import Store
from .analyzer import Analyzer, PydanticAIAnalyzer
from .reducer import reduce_thread
from .sections import AnalysisSections

logger = logging.getLogger(__name__)

DEFAULT_DEBOUNCE_SECONDS = 2.0

# Bound a single analyzer run so a slow/hung provider can never wedge a worker (the old
# cold subprocess had a 60s SIGKILL watchdog; this replaces it). On timeout or error the
# run is retried a bounded number of times with backoff, then abandoned until a fresh turn.
DEFAULT_ANALYSIS_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 1.0

# Provisional model policy: hardcoded for v2. The analyzer rework will move this to
# config; until then the model lives here (a broken/unavailable model is caught and
# skipped, so it never harms ingest).
DEFAULT_ANALYSIS_MODEL = "anthropic:claude-haiku-4-5"


class AnalysisScheduler:
    """Per-owner reactive scheduler over the ``Analyzer`` seam."""

    def __init__(
        self,
        store: Store,
        *,
        analyzer: Analyzer | None = None,
        model: str | None = DEFAULT_ANALYSIS_MODEL,
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
        timeout_seconds: float = DEFAULT_ANALYSIS_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
    ) -> None:
        self._store = store
        self._analyzer: Analyzer = analyzer or PydanticAIAnalyzer()
        self._model = model
        self._debounce = debounce_seconds
        self._timeout = timeout_seconds
        self._max_attempts = max(1, max_attempts)
        self._retry_backoff = retry_backoff_seconds
        self._latest: dict[str, int] = {}
        self._analyzed: dict[str, int] = {}
        self._failures: dict[str, int] = {}
        self._detached: set[str] = set()
        self._events: dict[str, asyncio.Event] = {}
        self._workers: dict[str, asyncio.Task[None]] = {}

    def notify(self, owner_id: str, seq: int) -> None:
        """Record a fresh turn and wake (or start) this owner's worker."""

        self._detached.discard(owner_id)  # a fresh turn re-attaches a draining owner
        if seq > self._latest.get(owner_id, 0):
            self._latest[owner_id] = seq
        self._ensure_worker(owner_id)
        self._events[owner_id].set()

    def forget(self, owner_id: str) -> None:
        """Detach an owner on disconnect — drain, don't cancel.

        A one-shot session disconnects right after shipping its final ``thread_report``,
        so cancelling here would drop the debounced analysis before it persists. Instead
        mark the owner detached and wake its worker: it finishes the pending run, persists,
        then self-exits (``_run_worker``). Cancellation is reserved for ``stop()``.
        """

        if owner_id in self._workers:
            self._detached.add(owner_id)
            event = self._events.get(owner_id)
            if event is not None:
                event.set()
        else:
            self._cleanup(owner_id)

    def _cleanup(self, owner_id: str) -> None:
        self._workers.pop(owner_id, None)
        self._events.pop(owner_id, None)
        self._latest.pop(owner_id, None)
        self._analyzed.pop(owner_id, None)
        self._failures.pop(owner_id, None)
        self._detached.discard(owner_id)

    async def stop(self) -> None:
        """Cancel every worker and release the analyzer (daemon shutdown)."""

        workers = list(self._workers.values())
        for worker in workers:
            worker.cancel()
        for worker in workers:
            # Suppress cancellation AND any residual worker error: shutdown must not abort
            # because a worker died (e.g. a seed-time DB error) and left an exception set.
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await worker
        self._workers.clear()
        self._events.clear()
        self._latest.clear()
        self._analyzed.clear()
        self._failures.clear()
        self._detached.clear()
        close = getattr(self._analyzer, "close", None)
        if callable(close):
            close()

    def _ensure_worker(self, owner_id: str) -> None:
        if owner_id not in self._events:
            self._events[owner_id] = asyncio.Event()
        worker = self._workers.get(owner_id)
        if worker is None or worker.done():
            self._workers[owner_id] = asyncio.create_task(self._run_worker(owner_id))

    async def _run_worker(self, owner_id: str) -> None:
        # Seed from any persisted analysis so a restart doesn't re-run already-seen turns.
        # Guard it: a seed-time store error must not kill the worker (which would also make
        # stop() re-raise on shutdown) — fall back to 0 and let the loop below recover.
        try:
            seed = await self._persisted_seq(owner_id)
        except Exception:
            logger.exception("failed to seed analysis cursor for %s; starting from 0", owner_id)
            seed = 0
        self._analyzed.setdefault(owner_id, seed)
        event = self._events[owner_id]
        while True:
            await event.wait()
            if self._debounce > 0:
                await asyncio.sleep(self._debounce)  # coalesce a burst into one run
            event.clear()
            target = self._latest.get(owner_id, 0)
            if target > self._analyzed.get(owner_id, 0):
                if await self._try_analyze(owner_id, target):
                    self._analyzed[owner_id] = target
            # Detached (client disconnected): we made a best-effort drain of the latest
            # turn above; exit and clean up now. A reconnect clears the flag via notify()
            # before we get here, so an active session is never dropped.
            if owner_id in self._detached:
                self._cleanup(owner_id)
                return

    async def _try_analyze(self, owner_id: str, target: int) -> bool:
        """Run one analysis; return True only if a new analysis was stored."""

        model = self._model
        if not model:
            logger.debug("no analysis model configured; skipping analysis for %s", owner_id)
            return False
        try:
            thread = await asyncio.to_thread(self._store.get_raw_pi_thread_nodes, owner_id)
            if not thread.live:
                return False
            context = reduce_thread(thread.live)
            prior = await asyncio.to_thread(self._store.get_analysis, owner_id)
            prior_sections = _parse_sections(prior.sections_json) if prior is not None else None
        except Exception as exc:  # noqa: BLE001 — a store error must never kill the worker or ingest
            self._note_failure(owner_id, str(exc) or type(exc).__name__)
            return False

        # v2: Phase 3's projection feeds tracked goal/task state into already_tracked.
        sections = await self._run_analyzer(owner_id, context=context, prior=prior_sections, model=model)
        if sections is None:
            return False
        try:
            await asyncio.to_thread(
                self._store.record_analysis,
                owner_id=owner_id,
                based_on_thread_seq=target,
                model=model,
                sections_json=sections.model_dump_json(by_alias=True),
            )
        except Exception as exc:  # noqa: BLE001
            self._note_failure(owner_id, str(exc) or type(exc).__name__)
            return False
        self._failures.pop(owner_id, None)  # a clean run ends the failure streak
        return True

    async def _run_analyzer(
        self, owner_id: str, *, context: str, prior: AnalysisSections | None, model: str
    ) -> AnalysisSections | None:
        """Run the analyzer with a per-call timeout and bounded retries; None on give-up."""

        for attempt in range(1, self._max_attempts + 1):
            try:
                return await asyncio.wait_for(
                    self._analyzer.analyze(context=context, already_tracked="", prior=prior, model=model),
                    timeout=self._timeout,
                )
            except TimeoutError:
                # The wait_for backstop fired: the coroutine is cancelled but a blocking
                # provider call keeps its executor thread (the analyzer's own provider
                # deadline should normally fire first and free it). Do NOT retry — a second
                # attempt would submit another blocking call and pile up on the pool. Give
                # up until the next fresh turn.
                self._note_failure(owner_id, f"timed out after {self._timeout:.0f}s")
                return None
            except Exception as exc:  # noqa: BLE001 — retry transient (fast) failures, then give up
                reason = str(exc) or type(exc).__name__
            if attempt >= self._max_attempts:
                self._note_failure(owner_id, reason)
                return None
            if self._retry_backoff > 0:
                await asyncio.sleep(self._retry_backoff * attempt)
        return None

    def _note_failure(self, owner_id: str, reason: str) -> None:
        """Log a failure once per streak (loud first, quiet after) so a persistently broken
        analyzer doesn't flood the log with a full traceback on every turn."""

        count = self._failures.get(owner_id, 0) + 1
        self._failures[owner_id] = count
        if count == 1:
            logger.warning("analysis failed for %s: %s", owner_id, reason)
        else:
            logger.debug("analysis still failing for %s (%d in a row): %s", owner_id, count, reason)

    async def _persisted_seq(self, owner_id: str) -> int:
        prior = await asyncio.to_thread(self._store.get_analysis, owner_id)
        if prior is None or prior.based_on_thread_seq is None:
            return 0
        return prior.based_on_thread_seq


def _parse_sections(sections_json: str) -> AnalysisSections | None:
    try:
        return AnalysisSections.model_validate_json(sections_json)
    except ValueError:
        return None
