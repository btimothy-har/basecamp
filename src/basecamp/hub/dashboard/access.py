"""In-memory bootstrap and browser-session authority for the dashboard."""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote

BOOTSTRAP_TTL_SECONDS = 30.0
SESSION_TTL_SECONDS = 12 * 60 * 60
MAX_BOOTSTRAP_NONCES = 64
MAX_BROWSER_SESSIONS = 64


class DashboardUnavailableError(RuntimeError):
    """Dashboard listener is not available for browser bootstrap."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)


@dataclass(frozen=True)
class DashboardAvailability:
    """Current dashboard listener state."""

    available: bool
    base_url: str | None
    reason: str | None


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def _digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


class DashboardAccess:
    """Thread-safe, process-lifetime dashboard authentication state."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        token_factory: Callable[[], str] = _new_token,
    ) -> None:
        self._clock = clock
        self._token_factory = token_factory
        self._lock = threading.Lock()
        self._base_url: str | None = None
        self._reason: str | None = "dashboard listener has not started"
        self._nonces: dict[bytes, float] = {}
        self._sessions: dict[bytes, float] = {}

    @property
    def session_max_age(self) -> int:
        return int(SESSION_TTL_SECONDS)

    def availability(self) -> DashboardAvailability:
        with self._lock:
            return DashboardAvailability(
                available=self._base_url is not None,
                base_url=self._base_url,
                reason=self._reason,
            )

    def set_available(self, base_url: str) -> None:
        with self._lock:
            self._base_url = base_url.rstrip("/")
            self._reason = None

    def set_unavailable(self, reason: str) -> None:
        with self._lock:
            self._base_url = None
            self._reason = reason
            self._nonces.clear()
            self._sessions.clear()

    def mint_bootstrap_url(self) -> str:
        with self._lock:
            now = self._clock()
            self._prune(now)
            if self._base_url is None:
                raise DashboardUnavailableError(self._reason or "dashboard listener is unavailable")
            nonce = self._token_factory()
            self._store_bounded(
                self._nonces,
                _digest(nonce),
                now + BOOTSTRAP_TTL_SECONDS,
                MAX_BOOTSTRAP_NONCES,
            )
            return f"{self._base_url}/bootstrap/{quote(nonce, safe='')}"

    def redeem_bootstrap(self, nonce: str) -> str | None:
        nonce_digest = _digest(nonce)
        with self._lock:
            now = self._clock()
            self._prune(now)
            matched: bytes | None = None
            for stored in self._nonces:
                if secrets.compare_digest(stored, nonce_digest):
                    matched = stored
            expiry = self._nonces.pop(matched, None) if matched is not None else None
            if expiry is None or expiry <= now or self._base_url is None:
                return None
            session = self._token_factory()
            self._store_bounded(
                self._sessions,
                _digest(session),
                now + SESSION_TTL_SECONDS,
                MAX_BROWSER_SESSIONS,
            )
            return session

    def validate_session(self, session: str | None) -> bool:
        if not session:
            return False
        candidate = _digest(session)
        with self._lock:
            now = self._clock()
            self._prune(now)
            return any(
                expiry > now and secrets.compare_digest(stored, candidate) for stored, expiry in self._sessions.items()
            )

    def _prune(self, now: float) -> None:
        self._nonces = {token: expiry for token, expiry in self._nonces.items() if expiry > now}
        self._sessions = {token: expiry for token, expiry in self._sessions.items() if expiry > now}

    @staticmethod
    def _store_bounded(store: dict[bytes, float], token: bytes, expiry: float, limit: int) -> None:
        if len(store) >= limit:
            oldest = min(store.items(), key=lambda item: item[1])[0]
            del store[oldest]
        store[token] = expiry
