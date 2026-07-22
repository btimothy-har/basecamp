"""In-memory dashboard bootstrap and browser-session tests."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from basecamp.hub.dashboard.access import DashboardAccess, DashboardUnavailableError


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_dashboard_access_requires_listener_and_redeems_once() -> None:
    tokens = iter(["nonce-token-000000000000000000000000", "session-token-0000000000000000000000"])
    access = DashboardAccess(token_factory=lambda: next(tokens))

    with pytest.raises(DashboardUnavailableError):
        access.mint_bootstrap_url()

    access.set_available("http://127.0.0.1:47658")
    url = access.mint_bootstrap_url()
    nonce = url.rsplit("/", 1)[-1]
    session = access.redeem_bootstrap(nonce)

    assert url == "http://127.0.0.1:47658/bootstrap/nonce-token-000000000000000000000000"
    assert session == "session-token-0000000000000000000000"
    assert access.validate_session(session) is True
    assert access.redeem_bootstrap(nonce) is None
    access.set_unavailable("stopped")
    assert access.validate_session(session) is False


def test_dashboard_access_enforces_nonce_and_session_expiry() -> None:
    clock = _Clock()
    tokens = iter(
        [
            "nonce-one-0000000000000000000000000",
            "session-one-00000000000000000000000",
            "nonce-two-0000000000000000000000000",
        ]
    )
    access = DashboardAccess(clock=clock, token_factory=lambda: next(tokens))
    access.set_available("http://127.0.0.1:47658")

    first_nonce = access.mint_bootstrap_url().rsplit("/", 1)[-1]
    clock.now = 29.9
    session = access.redeem_bootstrap(first_nonce)
    assert session is not None
    assert access.validate_session(session) is True

    second_nonce = access.mint_bootstrap_url().rsplit("/", 1)[-1]
    clock.now = 60.0
    assert access.redeem_bootstrap(second_nonce) is None
    clock.now = 12 * 60 * 60 + 30.0
    assert access.validate_session(session) is False


def test_dashboard_nonce_redemption_is_atomic_across_threads() -> None:
    counter = 0
    token_lock = threading.Lock()

    def token() -> str:
        nonlocal counter
        with token_lock:
            counter += 1
            return f"token-{counter:04}-0000000000000000000000000000"

    access = DashboardAccess(token_factory=token)
    access.set_available("http://127.0.0.1:47658")
    nonce = access.mint_bootstrap_url().rsplit("/", 1)[-1]

    with ThreadPoolExecutor(max_workers=16) as executor:
        sessions = list(executor.map(access.redeem_bootstrap, [nonce] * 64))

    redeemed = [session for session in sessions if session is not None]
    assert len(redeemed) == 1
    assert access.validate_session(redeemed[0]) is True
