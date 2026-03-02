"""Container runtime management for the local dev database."""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass

from observer.constants import (
    DB_CONTAINER_NAME,
    DB_IMAGE,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
    DB_VOLUME_NAME,
)


class ContainerRuntimeNotFoundError(Exception):
    """Raised when neither docker nor podman is found on PATH."""

    def __init__(self) -> None:
        super().__init__("Neither 'docker' nor 'podman' found on PATH.")


@dataclass
class ContainerStatus:
    running: bool
    runtime: str
    container_name: str
    port: int
    volume: str
    status_text: str


def detect_runtime() -> str:
    """Return 'docker' or 'podman', whichever is found first on PATH."""
    for name in ("docker", "podman"):
        if shutil.which(name):
            return name
    raise ContainerRuntimeNotFoundError


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=check)


def inspect_container(runtime: str) -> ContainerStatus | None:
    """Return the container's status, or None if it doesn't exist."""
    result = _run(
        [runtime, "inspect", "--format", "{{.State.Status}}", DB_CONTAINER_NAME],
        check=False,
    )
    if result.returncode != 0:
        return None

    status_text = result.stdout.strip()
    return ContainerStatus(
        running=status_text == "running",
        runtime=runtime,
        container_name=DB_CONTAINER_NAME,
        port=DB_PORT,
        volume=DB_VOLUME_NAME,
        status_text=status_text,
    )


def start_container(runtime: str) -> None:
    """Create and start a new container."""
    try:
        _run([
            runtime, "run", "-d",
            "--name", DB_CONTAINER_NAME,
            "-p", f"{DB_PORT}:5432",
            "-v", f"{DB_VOLUME_NAME}:/var/lib/postgresql/data",
            "-e", f"POSTGRES_USER={DB_USER}",
            "-e", f"POSTGRES_PASSWORD={DB_PASSWORD}",
            "-e", f"POSTGRES_DB={DB_NAME}",
            "--restart", "unless-stopped",
            DB_IMAGE,
        ])  # fmt: skip
    except subprocess.CalledProcessError as exc:
        msg = f"Failed to create container '{DB_CONTAINER_NAME}': {exc.stderr.strip() or exc}"
        raise RuntimeError(msg) from exc


def restart_container(runtime: str) -> None:
    """Start an existing stopped container."""
    try:
        _run([runtime, "start", DB_CONTAINER_NAME])
    except subprocess.CalledProcessError as exc:
        msg = f"Failed to start container '{DB_CONTAINER_NAME}': {exc.stderr.strip() or exc}"
        raise RuntimeError(msg) from exc


def stop_container(runtime: str) -> None:
    """Stop the running container."""
    try:
        _run([runtime, "stop", DB_CONTAINER_NAME])
    except subprocess.CalledProcessError as exc:
        msg = f"Failed to stop container '{DB_CONTAINER_NAME}': {exc.stderr.strip() or exc}"
        raise RuntimeError(msg) from exc


def remove_container(runtime: str) -> None:
    """Remove the container (volume is preserved)."""
    try:
        _run([runtime, "rm", DB_CONTAINER_NAME])
    except subprocess.CalledProcessError as exc:
        msg = f"Failed to remove container '{DB_CONTAINER_NAME}': {exc.stderr.strip() or exc}"
        raise RuntimeError(msg) from exc


def wait_for_ready(runtime: str, *, timeout: int = 30, poll_interval: float = 1.0) -> bool:
    """Poll until PostgreSQL inside the container accepts connections.

    The entrypoint runs initdb before starting the server, so docker exec
    pg_isready can fail immediately during bootstrap. We poll in a loop
    rather than relying on pg_isready's own -t flag.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = _run(
            [runtime, "exec", DB_CONTAINER_NAME, "pg_isready", "-U", DB_USER, "-d", DB_NAME],
            check=False,
        )
        if result.returncode == 0:
            return True
        time.sleep(poll_interval)
    return False


def container_logs(runtime: str, *, lines: int = 20) -> str:
    """Return recent container logs for diagnostics."""
    result = _run([runtime, "logs", "--tail", str(lines), DB_CONTAINER_NAME], check=False)
    return result.stdout or result.stderr
