"""Event-driven analysis scheduler — run the analyzer when fresh turns land.

The daemon is a long-lived async process, so scheduling is reactive, not timed.
``notify(owner_id, seq)`` (called after a ``thread_report`` is persisted) bumps an
in-memory latest-seq and wakes a per-owner worker. Each worker is a single
sequential coroutine, which gives skip-in-flight and burst coalescing for free:
it debounces, then analyzes the newest thread only when ``latest_seq`` has advanced
past what was last analyzed (seeded from the persisted row so a daemon restart does
not re-run stale turns). "Laggy is fine" — nothing here blocks ingest. See
docs/design/companion-daemon-broker.md §6.1.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from ..store import Store
from .analyzer import Analyzer, PydanticAIAnalyzer
from .reducer import reduce_thread
from .sections import AnalysisSections

logger = logging.getLogger(__name__)

DEFAULT_DEBOUNCE_SECONDS = 2.0

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
    ) -> None:
        self._store = store
        self._analyzer: Analyzer = analyzer or PydanticAIAnalyzer()
        self._model = model
        self._debounce = debounce_seconds
        self._latest: dict[str, int] = {}
        self._analyzed: dict[str, int] = {}
        self._events: dict[str, asyncio.Event] = {}
        self._workers: dict[str, asyncio.Task[None]] = {}

    def notify(self, owner_id: str, seq: int) -> None:
        """Record a fresh turn and wake (or start) this owner's worker."""

        if seq > self._latest.get(owner_id, 0):
            self._latest[owner_id] = seq
        self._ensure_worker(owner_id)
        self._events[owner_id].set()

    def forget(self, owner_id: str) -> None:
        """Cancel and drop an owner's worker (e.g. on disconnect)."""

        worker = self._workers.pop(owner_id, None)
        if worker is not None:
            worker.cancel()
        self._events.pop(owner_id, None)
        self._latest.pop(owner_id, None)
        self._analyzed.pop(owner_id, None)

    async def stop(self) -> None:
        """Cancel every worker (daemon shutdown)."""

        workers = list(self._workers.values())
        for worker in workers:
            worker.cancel()
        for worker in workers:
            with contextlib.suppress(asyncio.CancelledError):
                await worker
        self._workers.clear()
        self._events.clear()
        self._latest.clear()
        self._analyzed.clear()

    def _ensure_worker(self, owner_id: str) -> None:
        if owner_id not in self._events:
            self._events[owner_id] = asyncio.Event()
        worker = self._workers.get(owner_id)
        if worker is None or worker.done():
            self._workers[owner_id] = asyncio.create_task(self._run_worker(owner_id))

    async def _run_worker(self, owner_id: str) -> None:
        # Seed from any persisted analysis so a restart doesn't re-run already-seen turns.
        self._analyzed.setdefault(owner_id, await self._persisted_seq(owner_id))
        event = self._events[owner_id]
        while True:
            await event.wait()
            if self._debounce > 0:
                await asyncio.sleep(self._debounce)  # coalesce a burst into one run
            event.clear()
            target = self._latest.get(owner_id, 0)
            if target <= self._analyzed.get(owner_id, 0):
                continue
            if await self._try_analyze(owner_id, target):
                self._analyzed[owner_id] = target

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
            sections = await self._analyzer.analyze(
                context=context,
                already_tracked="",  # v2: Phase 3's projection feeds tracked goal/task state
                prior=_parse_sections(prior.sections_json) if prior is not None else None,
                model=model,
            )
            await asyncio.to_thread(
                self._store.record_analysis,
                owner_id=owner_id,
                based_on_thread_seq=target,
                model=model,
                sections_json=sections.model_dump_json(by_alias=True),
            )
        except Exception:  # noqa: BLE001 — a broken analyzer must never kill the worker or ingest
            logger.exception("analysis run failed for %s", owner_id)
            return False
        return True

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
