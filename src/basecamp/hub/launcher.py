"""User-facing launcher for the authenticated agents dashboard."""

from __future__ import annotations

import re
import webbrowser
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from rich.console import Console

from basecamp.core.console import console
from basecamp.core.exceptions import LauncherError

from .dashboard.app import DASHBOARD_HOST, DASHBOARD_PORT
from .dashboard.uds import DashboardUdsClient, DashboardUdsError
from .ensure import ensure_hub

_BOOTSTRAP_PATH = re.compile(r"^/bootstrap/[A-Za-z0-9_-]{32,128}$")


class DashboardLaunchError(LauncherError):
    """Dashboard could not be authenticated or opened safely."""

    @classmethod
    def unavailable(cls, detail: str) -> DashboardLaunchError:
        return cls(f"Dashboard unavailable: {detail}")

    @classmethod
    def invalid_url(cls) -> DashboardLaunchError:
        return cls("The hub returned an invalid dashboard bootstrap URL.")


def _open_browser(url: str) -> bool:
    return webbrowser.open(url, new=2, autoraise=True)


def open_agents_dashboard(
    *,
    ensure: Callable[[], Path] = ensure_hub,
    client_factory: Callable[[str], DashboardUdsClient] = DashboardUdsClient,
    browser_open: Callable[[str], bool] = _open_browser,
    output: Console = console,
) -> str:
    """Ensure the hub, mint a one-time URL, and open or print it."""

    socket_path = ensure()
    try:
        url = client_factory(str(socket_path)).mint_bootstrap_url()
    except DashboardUdsError as error:
        raise DashboardLaunchError.unavailable(error.detail) from error
    if not _is_expected_bootstrap_url(url):
        raise DashboardLaunchError.invalid_url()

    try:
        opened = browser_open(url)
    except (OSError, webbrowser.Error):
        opened = False

    if opened:
        output.print("Opened the Basecamp agents dashboard.")
    else:
        output.print("Browser launch failed. Open this one-time URL within 30 seconds:")
        output.print(url, markup=False, soft_wrap=True)
    return url


def _is_expected_bootstrap_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "http"
        and parsed.hostname == DASHBOARD_HOST
        and port == DASHBOARD_PORT
        and parsed.netloc == f"{DASHBOARD_HOST}:{DASHBOARD_PORT}"
        and parsed.query == ""
        and parsed.fragment == ""
        and _BOOTSTRAP_PATH.fullmatch(parsed.path) is not None
    )
