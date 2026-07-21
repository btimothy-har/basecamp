from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.terminal_bench import compose


def test_configured_compose_path_wins(tmp_path: Path) -> None:
    configured = tmp_path / "docker-compose"
    configured.write_bytes(b"configured")

    resolved = compose.resolve_docker_compose(
        {"DOCKER_COMPOSE_BIN": str(configured), "PATH": ""},
        downloader=lambda _url: pytest.fail("download should not run"),
    )

    assert resolved == configured


def test_valid_cached_compose_is_reused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    content = b"cached-compose"
    digest = hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(compose, "_artifact", lambda: ("compose-test", digest))
    target = tmp_path / "compose-test"
    target.write_bytes(content)

    resolved = compose.resolve_docker_compose(
        {"PATH": ""},
        cache_root=tmp_path,
        downloader=lambda _url: pytest.fail("download should not run"),
    )

    assert resolved == target


def test_missing_compose_is_downloaded_verified_and_made_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"downloaded-compose"
    digest = hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(compose, "_artifact", lambda: ("compose-test", digest))
    requested: list[str] = []

    def download(url: str) -> bytes:
        requested.append(url)
        return content

    resolved = compose.resolve_docker_compose(
        {"PATH": ""},
        cache_root=tmp_path,
        downloader=download,
    )

    assert requested == [f"{compose._RELEASE_URL}/compose-test"]
    assert resolved.read_bytes() == content
    assert resolved.stat().st_mode & 0o111


def test_download_checksum_mismatch_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compose, "_artifact", lambda: ("compose-test", "0" * 64))

    with pytest.raises(compose.ComposeChecksumError):
        compose.resolve_docker_compose(
            {"PATH": ""},
            cache_root=tmp_path,
            downloader=lambda _url: b"tampered",
        )

    assert not (tmp_path / "compose-test").exists()
