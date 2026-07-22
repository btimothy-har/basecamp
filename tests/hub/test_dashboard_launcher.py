"""Tests for ensuring, authenticating, and opening the agents dashboard."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from basecamp.hub.dashboard.uds import DashboardUdsError
from basecamp.hub.launcher import DashboardLaunchError, open_agents_dashboard

_BOOTSTRAP_URL = f"http://127.0.0.1:47658/bootstrap/{'n' * 43}"


class _Client:
    def __init__(self, _socket_path: str, *, url: str = _BOOTSTRAP_URL, error: DashboardUdsError | None = None) -> None:
        self.url = url
        self.error = error

    def mint_bootstrap_url(self) -> str:
        if self.error is not None:
            raise self.error
        return self.url


def _console() -> tuple[Console, StringIO]:
    stream = StringIO()
    return Console(file=stream, force_terminal=False, color_system=None), stream


def test_launcher_ensures_before_minting_and_opens_without_printing_nonce() -> None:
    events: list[object] = []
    output, stream = _console()

    def ensure() -> Path:
        events.append("ensure")
        return Path("/tmp/daemon.sock")

    def client_factory(socket_path: str) -> _Client:
        events.append(("client", socket_path))
        return _Client(socket_path)

    def browser_open(url: str) -> bool:
        events.append(("open", url))
        return True

    url = open_agents_dashboard(
        ensure=ensure,
        client_factory=client_factory,
        browser_open=browser_open,
        output=output,
    )

    assert url == _BOOTSTRAP_URL
    assert events == [
        "ensure",
        ("client", "/tmp/daemon.sock"),
        ("open", _BOOTSTRAP_URL),
    ]
    assert "Opened the Basecamp agents dashboard." in stream.getvalue()
    assert "n" * 43 not in stream.getvalue()


def test_launcher_prints_one_time_fallback_only_when_browser_fails() -> None:
    output, stream = _console()

    open_agents_dashboard(
        ensure=lambda: Path("/tmp/daemon.sock"),
        client_factory=_Client,
        browser_open=lambda _url: False,
        output=output,
    )

    assert "Browser launch failed" in stream.getvalue()
    assert _BOOTSTRAP_URL in stream.getvalue().splitlines()


def test_launcher_surfaces_dashboard_unavailability_without_opening() -> None:
    output, _stream = _console()
    opened: list[str] = []

    with pytest.raises(DashboardLaunchError, match="port 127.0.0.1:47658 is already in use"):
        open_agents_dashboard(
            ensure=lambda: Path("/tmp/daemon.sock"),
            client_factory=lambda path: _Client(
                path,
                error=DashboardUdsError(
                    "dashboard port 127.0.0.1:47658 is already in use",
                    status=503,
                ),
            ),
            browser_open=lambda url: bool(opened.append(url)),
            output=output,
        )

    assert opened == []


@pytest.mark.parametrize(
    "url",
    [
        f"http://localhost:47658/bootstrap/{'n' * 43}",
        f"http://127.0.0.1:47659/bootstrap/{'n' * 43}",
        f"http://127.0.0.1:47658/bootstrap/{'n' * 43}?leak=1",
        "https://evil.test/bootstrap/nonce",
    ],
)
def test_launcher_rejects_unexpected_bootstrap_urls(url: str) -> None:
    with pytest.raises(DashboardLaunchError, match="invalid dashboard bootstrap URL"):
        open_agents_dashboard(
            ensure=lambda: Path("/tmp/daemon.sock"),
            client_factory=lambda path: _Client(path, url=url),
            browser_open=lambda _url: True,
        )
