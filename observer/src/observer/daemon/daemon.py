"""Daemon runtime — PID management, process lifecycle, and polling loop.

The daemon is a read-only detector: queries active transcripts, stats files,
and spawns isolated worker processes to ingest. Workers are ephemeral — lock,
ingest, update state, unlock, exit.

Extraction is inactivity-driven: when a transcript's file hasn't changed for
INACTIVITY_TIMEOUT seconds, an extraction worker fires to produce structured
sections from the refined events.
"""

import logging
import logging.handlers
import multiprocessing
import os
import signal
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from observer import constants
from observer.daemon.workers import (
    extraction_worker,
    index_worker,
    ingest_worker,
    refine_worker,
)
from observer.data.transcript import Transcript
from observer.pipeline.indexing import SearchIndexer
from observer.pipeline.refining.grouping import EventGrouper
from observer.pipeline.refining.refinement import WorkItemRefiner
from observer.services.config import get_mode
from observer.services.db import Database
from observer.services.logger import configure_logging_daemon
from observer.services.notebook import NotebookService

logger = logging.getLogger(__name__)


class Daemon:
    """Observer daemon — manages PID, lifecycle, and the polling loop.

    Public API:
        check_running() — returns PID if daemon is alive, else None
        is_process_running(pid) — check if an arbitrary PID is alive
        run(foreground) — configure, optionally fork, then poll until shutdown
    """

    def __init__(
        self,
        pid_file: Path,
        *,
        enable_viz: bool = True,
    ):
        self._pid_file = pid_file
        self._enable_viz = enable_viz
        self._mode = get_mode()
        self._shutdown_event = threading.Event()
        self._workers: list[multiprocessing.Process] = []
        self._log_queue: multiprocessing.Queue | None = None
        self._log_listener: logging.handlers.QueueListener | None = None

        # Scheduler state — interval-based stages
        self._last_index_at: float = 0.0
        self._last_refine_at: float = 0.0

        # Inactivity tracking — keyed by transcript_id
        self._last_ingest_at: dict[int, float] = {}
        self._last_extracted_at: dict[int, float] = {}

    @staticmethod
    def is_process_running(pid: int) -> bool:
        """Check whether a process with the given PID is alive."""
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    @staticmethod
    def _is_own_daemon(pid: int) -> bool:
        """Check whether a PID belongs to an observer daemon process.

        Inspects the process command line to look for "observer.daemon" or
        "observer" markers. Uses /proc on Linux, falls back to `ps` on
        macOS/other Unix. Returns False if verification cannot be performed.
        """
        try:
            # Linux: read /proc/{pid}/cmdline (null-delimited)
            cmdline_path = Path(f"/proc/{pid}/cmdline")
            if cmdline_path.exists():
                raw = cmdline_path.read_bytes().replace(b"\x00", b" ").decode()
                return Daemon._cmdline_matches(raw)

            # macOS / fallback: use ps
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return Daemon._cmdline_matches(result.stdout.strip())
        except (OSError, subprocess.TimeoutExpired, subprocess.SubprocessError):
            pass

        return False

    @staticmethod
    def _cmdline_matches(cmdline: str) -> bool:
        """Check if a command line string belongs to an observer daemon.

        Compares basenames so full paths (e.g. from uv tool install) still match.
        """
        if "observer.daemon" in cmdline:
            return True
        basenames = [Path(p).name for p in cmdline.split()]
        return "observer" in basenames

    def check_running(self) -> int | None:
        """Return the daemon PID if running, else None. Cleans stale PID files."""
        if not self._pid_file.exists():
            return None
        try:
            pid = int(self._pid_file.read_text().strip())
        except (ValueError, OSError):
            return None
        if self.is_process_running(pid) and self._is_own_daemon(pid):
            return pid
        self._pid_file.unlink(missing_ok=True)
        return None

    def run(self, *, foreground: bool = False) -> None:
        """Start the daemon: configure logging, fork if background, then poll.

        This is the single entry point for the daemon lifecycle. It handles
        logging setup, daemonization, PID file, signal registration, the poll
        loop, and cleanup on exit.
        """
        # -- Daemonize --
        if not foreground:
            if os.fork() > 0:
                os._exit(0)
            os.setsid()
            if os.fork() > 0:
                os._exit(0)

            devnull = os.open(os.devnull, os.O_RDWR)
            os.dup2(devnull, 0)
            os.dup2(devnull, 1)
            os.dup2(devnull, 2)
            os.close(devnull)

            # Restrict default permissions for all daemon-created files to owner-only.
            os.umask(0o077)

        # -- Logging (after fork so QueueListener thread lives in the final process) --
        self._log_queue, self._log_listener = configure_logging_daemon(foreground=foreground)

        # -- PID file (kill any stale daemon to prevent orphans) --
        self._pid_file.parent.mkdir(parents=True, exist_ok=True)
        old_pid = self.check_running()
        if old_pid is not None and old_pid != os.getpid():
            if self._is_own_daemon(old_pid):
                try:
                    os.kill(old_pid, signal.SIGTERM)
                    logger.info("Sent SIGTERM to previous daemon (pid=%d)", old_pid)
                except ProcessLookupError:
                    pass
            else:
                logger.warning(
                    "PID %d is alive but not an observer daemon; removing stale PID file",
                    old_pid,
                )
                self._pid_file.unlink(missing_ok=True)
        self._pid_file.write_text(str(os.getpid()))

        # -- Signals --
        self._shutdown_event.clear()
        signal.signal(signal.SIGTERM, lambda _s, _f: self._shutdown_event.set())
        signal.signal(signal.SIGINT, lambda _s, _f: self._shutdown_event.set())
        signal.signal(signal.SIGCHLD, signal.SIG_DFL)

        db = Database()
        lock_dir = constants.OBSERVER_DIR / "locks"
        lock_dir.mkdir(parents=True, exist_ok=True)

        notebook = NotebookService() if self._enable_viz else None

        # Clean stale skip markers from previous runs
        for marker in lock_dir.glob("notfound_*"):
            marker.unlink(missing_ok=True)

        logger.info("Observer daemon started (pid=%d, mode=%s)", os.getpid(), self._mode)

        try:
            if notebook:
                notebook.start()
            self._poll_loop(lock_dir, notebook)
        finally:
            self._terminate_workers()
            if notebook:
                notebook.stop()
            logger.info("Observer daemon shutting down")
            if self._log_listener is not None:
                self._log_listener.stop()
            db.close()
            self._pid_file.unlink(missing_ok=True)

    def _poll_loop(self, lock_dir: Path, notebook: NotebookService | None) -> None:
        """Dispatch to the appropriate poll loop based on mode."""
        if self._mode == "off":
            self._poll_loop_off(lock_dir, notebook)
        else:
            self._poll_loop_on(lock_dir, notebook)

    def _poll_loop_on(self, lock_dir: Path, notebook: NotebookService | None) -> None:
        """On pipeline: ingest → refine → extract (on inactivity) → index.

        Interval-based stages (refine, index) run on their configured cadence.
        Extraction is inactivity-driven — fires when a transcript's file hasn't
        changed for INACTIVITY_TIMEOUT seconds.
        """
        while not self._shutdown_event.is_set():
            self._reap_workers()
            now = time.monotonic()

            if now - self._last_index_at >= constants.INDEX_INTERVAL:
                self._try_spawn_index(lock_dir, now)
            elif now - self._last_refine_at >= constants.REFINE_INTERVAL:
                self._try_spawn_refine(lock_dir, now)
            else:
                self._tick_ingest(lock_dir)

            self._try_spawn_extractions(lock_dir, now)

            if notebook:
                notebook.check()

            self._shutdown_event.wait(timeout=constants.TICK_INTERVAL)

    def _poll_loop_off(self, lock_dir: Path, notebook: NotebookService | None) -> None:
        """Off pipeline: ingest only, no LLM calls."""
        while not self._shutdown_event.is_set():
            self._reap_workers()
            self._tick_ingest(lock_dir)

            if notebook:
                notebook.check()

            self._shutdown_event.wait(timeout=constants.TICK_INTERVAL)

    def _reap_workers(self) -> None:
        """Join finished workers and keep only those still alive."""
        alive = []
        for p in self._workers:
            if p.is_alive():
                alive.append(p)
            else:
                try:
                    p.join(timeout=1)
                except Exception:
                    logger.exception("Failed to join worker %s", p.pid)
        self._workers = alive

    def _try_spawn_index(self, lock_dir: Path, now: float) -> None:
        """Spawn indexing worker if there's pending work."""
        self._last_index_at = now
        try:
            if SearchIndexer.has_pending():
                proc = multiprocessing.Process(
                    target=index_worker,
                    args=(lock_dir,),
                    kwargs={"log_queue": self._log_queue},
                )
                proc.start()
                self._workers.append(proc)
                logger.info("Spawned indexing worker (pid=%d)", proc.pid)
        except Exception:
            logger.exception("Indexing cycle failed")

    def _try_spawn_refine(self, lock_dir: Path, now: float) -> None:
        """Spawn refining worker if there are ungrouped events or unrefined work items."""
        self._last_refine_at = now
        try:
            if EventGrouper.has_pending() or WorkItemRefiner.has_pending():
                proc = multiprocessing.Process(
                    target=refine_worker,
                    args=(lock_dir,),
                    kwargs={"log_queue": self._log_queue},
                )
                proc.start()
                self._workers.append(proc)
                logger.info("Spawned refining worker (pid=%d)", proc.pid)
        except Exception:
            logger.exception("Refining cycle failed")

    def _try_spawn_extractions(self, lock_dir: Path, now: float) -> None:
        """Spawn extraction workers for transcripts that have been inactive long enough."""
        for transcript_id, last_ingest in self._last_ingest_at.items():
            idle_time = now - last_ingest
            if idle_time < constants.INACTIVITY_TIMEOUT:
                continue

            # Don't re-extract if we already extracted after the last ingest
            last_extracted = self._last_extracted_at.get(transcript_id, 0.0)
            if last_extracted > last_ingest:
                continue

            self._last_extracted_at[transcript_id] = now

            proc = multiprocessing.Process(
                target=extraction_worker,
                args=(transcript_id, lock_dir),
                kwargs={"log_queue": self._log_queue},
            )
            proc.start()
            self._workers.append(proc)
            logger.info(
                "Spawned extraction worker for transcript %d (idle %.0fs)",
                transcript_id,
                idle_time,
            )

    def _tick_ingest(self, lock_dir: Path) -> None:
        """Run one ingest poll."""
        try:
            spawned = self._poll_once(lock_dir)
            if spawned:
                logger.info("Spawned %d ingest workers", spawned)
        except Exception:
            logger.exception("Poll cycle failed")

    def _poll_once(self, lock_dir: Path) -> int:
        """One tick: detect file changes, mark deletions, spawn ingest workers."""
        now = time.monotonic()
        to_ingest: list[tuple[int, int]] = []

        for transcript in Transcript.get_active():
            if (lock_dir / f"notfound_{transcript.id}").exists():
                continue
            path = Path(transcript.path)

            if not path.exists():
                # Grace period: file may not exist yet if just registered
                if transcript.last_mtime is None:
                    wall_now = datetime.now(UTC)
                    started = transcript.started_at.replace(tzinfo=UTC)
                    age = (wall_now - started).total_seconds()
                    if age < constants.DEFAULT_STALE_THRESHOLD:
                        continue

                transcript.ended_at = datetime.now(UTC)
                with Database().session() as session:
                    transcript.save(session)
                logger.info(
                    "Transcript %d file deleted, marking ended",
                    transcript.id,
                )
                continue

            try:
                file_mtime = path.stat().st_mtime_ns
            except OSError:
                logger.warning(
                    "Could not stat transcript %d at %s",
                    transcript.id,
                    transcript.path,
                )
                continue

            if transcript.last_mtime is not None and transcript.last_mtime == file_mtime:
                continue

            to_ingest.append((transcript.id, file_mtime))

        # Respect concurrency cap — defer overflow to next poll cycle.
        # Already-running workers for the same transcript are gated by LOCK_NB,
        # so deferred transcripts will simply be re-evaluated next tick.
        if len(to_ingest) > constants.MAX_INGEST_WORKERS:
            logger.warning(
                "%d transcripts changed but capped at %d workers; %d deferred",
                len(to_ingest),
                constants.MAX_INGEST_WORKERS,
                len(to_ingest) - constants.MAX_INGEST_WORKERS,
            )
            to_ingest = to_ingest[: constants.MAX_INGEST_WORKERS]

        for transcript_id, file_mtime in to_ingest:
            self._last_ingest_at[transcript_id] = now

            proc = multiprocessing.Process(
                target=ingest_worker,
                args=(transcript_id, file_mtime, lock_dir),
                kwargs={"log_queue": self._log_queue},
            )
            proc.start()
            self._workers.append(proc)

        return len(to_ingest)

    def _terminate_workers(self, timeout: float = 5.0) -> None:
        """Send SIGTERM to all tracked workers and wait up to timeout seconds."""
        alive = [p for p in self._workers if p.is_alive()]
        for p in alive:
            p.terminate()
        for p in alive:
            p.join(timeout=timeout)
            if p.is_alive():
                logger.warning("Worker pid=%d did not exit; sending SIGKILL", p.pid)
                p.kill()
        self._workers.clear()
