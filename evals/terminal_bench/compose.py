"""Pinned Docker Compose bootstrap for Podman-backed Harbor runs."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import sys
import tempfile
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

_COMPOSE_VERSION: Final = "v5.3.1"
_DARWIN_ARM64_ASSET: Final = "docker-compose-darwin-aarch64"
_DARWIN_ARM64_SHA256: Final = "32691ba1196d819fa68cbdc0aad9a5569e730a35ae40c6fdd8458110ecd69488"
_RELEASE_URL: Final = f"https://github.com/docker/compose/releases/download/{_COMPOSE_VERSION}"


class ComposeBootstrapError(RuntimeError):
    """Docker Compose could not be resolved safely."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"Cannot prepare Docker Compose for Podman: {detail}")


class UnsupportedComposePlatformError(ComposeBootstrapError):
    """No pinned Docker Compose artifact exists for this platform."""

    def __init__(self, system: str, machine: str) -> None:
        super().__init__(f"unsupported platform {system}/{machine}; set DOCKER_COMPOSE_BIN")


class ComposeChecksumError(ComposeBootstrapError):
    """Downloaded Docker Compose artifact failed integrity validation."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"checksum mismatch for {path}")


class ConfiguredComposeNotFoundError(ComposeBootstrapError):
    """Configured Docker Compose path does not exist."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"DOCKER_COMPOSE_BIN does not exist: {path}")


def _cache_root() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "basecamp" / "evals" / "docker-compose" / _COMPOSE_VERSION


def _artifact() -> tuple[str, str]:
    system = sys.platform
    machine = platform.machine().lower()
    if system == "darwin" and machine in {"arm64", "aarch64"}:
        return _DARWIN_ARM64_ASSET, _DARWIN_ARM64_SHA256
    raise UnsupportedComposePlatformError(system, machine)


def _digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "basecamp-terminal-bench-eval"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def _install_cached_compose(
    target: Path,
    asset: str,
    expected_digest: str,
    downloader: Callable[[str], bytes],
) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    content = downloader(f"{_RELEASE_URL}/{asset}")
    if hashlib.sha256(content).hexdigest() != expected_digest:
        raise ComposeChecksumError(target)

    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
        temporary.write(content)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    temporary_path.chmod(0o755)
    temporary_path.replace(target)
    return target


def resolve_docker_compose(
    environment: Mapping[str, str],
    *,
    cache_root: Path | None = None,
    downloader: Callable[[str], bytes] = _download,
) -> Path:
    configured = environment.get("DOCKER_COMPOSE_BIN")
    if configured:
        path = Path(configured).expanduser().resolve()
        if not path.is_file():
            raise ConfiguredComposeNotFoundError(path)
        return path

    installed = shutil.which("docker-compose", path=environment.get("PATH"))
    if installed:
        return Path(installed).resolve()

    asset, expected_digest = _artifact()
    target = (cache_root or _cache_root()) / asset
    if target.is_file() and _digest(target) == expected_digest:
        return target
    if target.exists():
        target.unlink()

    print(f"Downloading pinned Docker Compose {_COMPOSE_VERSION} to {target}", file=sys.stderr)
    return _install_cached_compose(target, asset, expected_digest, downloader)
