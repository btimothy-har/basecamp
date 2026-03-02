"""Notebook service — manages the marimo viz dashboard as a child process.

Spawns marimo as a subprocess, routes its output to notebook.log, and
restarts on crash with backoff (gives up after VIZ_MAX_FAILURES within
VIZ_FAILURE_WINDOW seconds).
"""

import logging
import subprocess
import sys
import time
from io import TextIOWrapper
from pathlib import Path

from observer import constants

logger = logging.getLogger(__name__)


class NotebookService:
    """Manages the marimo visualization notebook lifecycle."""

    def __init__(
        self,
        port: int = constants.VIZ_PORT,
        host: str = constants.VIZ_HOST,
    ):
        self._port = port
        self._host = host
        self._process: subprocess.Popen[bytes] | None = None
        self._log_file: TextIOWrapper | None = None
        self._failures: list[float] = []
        self._gave_up = False

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        """Spawn the marimo notebook process."""
        if self.running:
            return

        app_path = self._resolve_app_path()
        if app_path is None:
            return

        constants.NOTEBOOK_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._log_file = open(constants.NOTEBOOK_LOG_FILE, "a", encoding="utf-8")

        cmd = [
            sys.executable,
            "-m",
            "marimo",
            "run",
            str(app_path),
            "--host",
            self._host,
            "--port",
            str(self._port),
            "--headless",
        ]

        self._process = subprocess.Popen(
            cmd,
            stdout=self._log_file,
            stderr=self._log_file,
            stdin=subprocess.DEVNULL,
        )
        logger.info(
            "Notebook started (pid=%d) on http://%s:%d",
            self._process.pid,
            self._host,
            self._port,
        )

    def check(self) -> None:
        """Health check — restart if crashed, with backoff."""
        if self._gave_up or self._process is None:
            return
        if self.running:
            return

        exit_code = self._process.returncode
        logger.warning("Notebook exited (code=%s), evaluating restart", exit_code)

        now = time.monotonic()
        self._failures = [t for t in self._failures if now - t < constants.VIZ_FAILURE_WINDOW]
        self._failures.append(now)

        if len(self._failures) >= constants.VIZ_MAX_FAILURES:
            logger.error(
                "Notebook failed %d times in %ds, giving up",
                len(self._failures),
                constants.VIZ_FAILURE_WINDOW,
            )
            self._gave_up = True
            self._cleanup_log()
            return

        logger.info("Restarting notebook (failure %d/%d)", len(self._failures), constants.VIZ_MAX_FAILURES)
        self._cleanup_log()
        self.start()

    def stop(self) -> None:
        """Terminate the notebook process."""
        if self._process is None:
            return

        if self.running:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Notebook did not stop gracefully, killing")
                self._process.kill()
                self._process.wait()

        logger.info("Notebook stopped")
        self._process = None
        self._cleanup_log()

    def _cleanup_log(self) -> None:
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None

    @staticmethod
    def _resolve_app_path() -> Path | None:
        try:
            from importlib.resources import files  # noqa: PLC0415

            return Path(str(files("observer.viz").joinpath("app.py")))
        except Exception:
            logger.exception("Could not resolve notebook app path")
            return None
