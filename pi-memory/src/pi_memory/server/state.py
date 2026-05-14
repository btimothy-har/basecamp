"""Local server metadata and lock handling."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

from pi_memory.constants import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    LOGS_DIR,
    MEMORY_DIR,
    SERVER_LOCK_PATH,
    SERVER_METADATA_PATH,
    SERVICE_NAME,
    SERVICE_VERSION,
)


class ServerAlreadyRunningError(Exception):
    """Raised when another local pi-memory server appears to be active."""

    def __init__(self, metadata: dict[str, object] | None) -> None:
        self.metadata = metadata
        detail = _server_detail(metadata)
        super().__init__(f"{SERVICE_NAME} is already running{detail}")


@dataclass(frozen=True)
class ServerMetadata:
    """Metadata describing the local service process."""

    service_name: str
    version: str
    pid: int
    started_at: str
    host: str
    port: int
    memory_dir: str

    @classmethod
    def create(
        cls,
        *,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        memory_dir: Path = MEMORY_DIR,
        pid: int | None = None,
        started_at: datetime | None = None,
    ) -> ServerMetadata:
        """Create metadata for a server process."""
        service_pid = os.getpid() if pid is None else pid
        service_started_at = datetime.now(UTC) if started_at is None else started_at
        return cls(
            service_name=SERVICE_NAME,
            version=SERVICE_VERSION,
            pid=service_pid,
            started_at=service_started_at.isoformat(),
            host=host,
            port=port,
            memory_dir=str(memory_dir.expanduser()),
        )

    @property
    def started_at_datetime(self) -> datetime:
        """Return the service start time as a datetime."""
        return datetime.fromisoformat(self.started_at)

    def to_dict(self) -> dict[str, object]:
        """Return JSON-serializable metadata."""
        return asdict(self)


class ServerState:
    """Filesystem-backed state for one local server instance."""

    def __init__(
        self,
        *,
        memory_dir: Path = MEMORY_DIR,
        metadata_path: Path | None = None,
        lock_path: Path | None = None,
        logs_dir: Path | None = None,
    ) -> None:
        self.memory_dir = memory_dir.expanduser()
        self.metadata_path = metadata_path or self.memory_dir / SERVER_METADATA_PATH.name
        self.lock_path = lock_path or self.memory_dir / SERVER_LOCK_PATH.name
        self.logs_dir = logs_dir or self.memory_dir / LOGS_DIR.name

    def ensure_dirs(self) -> None:
        """Create the service state directories."""
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def read_metadata(self) -> dict[str, object] | None:
        """Read server metadata, if present and valid JSON."""
        if not self.metadata_path.exists():
            return None

        try:
            content = self.metadata_path.read_text(encoding="utf-8")
            metadata = json.loads(content)
        except (OSError, json.JSONDecodeError):
            return None

        if not isinstance(metadata, dict):
            return None
        return metadata

    def register(
        self,
        *,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
    ) -> ServerRegistration:
        """Return a context manager that registers the current process."""
        return ServerRegistration(self, ServerMetadata.create(host=host, port=port, memory_dir=self.memory_dir))

    def acquire(self, metadata: ServerMetadata) -> None:
        """Acquire the local server lock and write process metadata."""
        self.ensure_dirs()
        self._acquire_lock()
        self._write_metadata(metadata)

    def release(self) -> None:
        """Remove server metadata and lock files during normal shutdown."""
        for path in (self.metadata_path, self.lock_path):
            _unlink_missing(path)

    def _acquire_lock(self) -> None:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        while True:
            try:
                descriptor = os.open(self.lock_path, flags, 0o600)
            except FileExistsError:
                metadata = self.read_metadata()
                if self._has_running_process(metadata):
                    raise ServerAlreadyRunningError(metadata) from None
                self._remove_stale_state()
                continue

            with os.fdopen(descriptor, "w", encoding="utf-8") as lock_file:
                lock_file.write(str(os.getpid()))
            return

    def _write_metadata(self, metadata: ServerMetadata) -> None:
        temporary_path = self.metadata_path.with_suffix(".json.tmp")
        temporary_path.write_text(json.dumps(metadata.to_dict(), indent=2) + "\n", encoding="utf-8")
        temporary_path.replace(self.metadata_path)

    def _remove_stale_state(self) -> None:
        for path in (self.metadata_path, self.lock_path):
            _unlink_missing(path)

    def _has_running_process(self, metadata: dict[str, object] | None) -> bool:
        pid = _metadata_pid(metadata) or _lock_pid(self.lock_path)
        return pid is not None and _pid_is_running(pid)


class ServerRegistration:
    """Context manager for a registered local server process."""

    def __init__(self, state: ServerState, metadata: ServerMetadata) -> None:
        self.state = state
        self.metadata = metadata

    def __enter__(self) -> ServerMetadata:
        self.state.acquire(self.metadata)
        return self.metadata

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.state.release()


def _unlink_missing(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _metadata_pid(metadata: dict[str, object] | None) -> int | None:
    if metadata is None:
        return None

    pid = metadata.get("pid")
    return pid if isinstance(pid, int) else None


def _lock_pid(path: Path) -> int | None:
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    if not content.isdigit():
        return None
    return int(content)


def _server_detail(metadata: dict[str, object] | None) -> str:
    if metadata is None:
        return ""

    pid = metadata.get("pid")
    host = metadata.get("host")
    port = metadata.get("port")
    if isinstance(pid, int) and isinstance(host, str) and isinstance(port, int):
        return f" at http://{host}:{port} (pid {pid})"
    if isinstance(pid, int):
        return f" (pid {pid})"
    return ""
