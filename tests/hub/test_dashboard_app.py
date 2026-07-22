"""Security and allowlist tests for the TCP dashboard FastAPI app."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from basecamp.hub.dashboard.access import DashboardAccess
from basecamp.hub.dashboard.app import DASHBOARD_ORIGIN, create_dashboard_app
from basecamp.hub.dashboard.uds import DashboardUdsError

_NAVIGATION_HEADERS = {"Sec-Fetch-Site": "none"}
_SAME_ORIGIN_HEADERS = {"Sec-Fetch-Site": "same-origin"}


class _Source:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.fail = False
        self.busy = False

    def get_snapshot(
        self,
        *,
        recent_root_limit: int = 5,
        selected_root_handle: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(("snapshot", (recent_root_limit, selected_root_handle)))
        if self.busy:
            raise DashboardUdsError("busy", status=429)
        if self.fail:
            raise DashboardUdsError.unavailable()
        return {"roots": [{"root_handle": "root-handle"}]}

    def get_messages(self, *, root_handle: str, agent_handle: str) -> dict[str, Any]:
        self.calls.append(("messages", (root_handle, agent_handle)))
        return {"root_handle": root_handle, "agent_handle": agent_handle, "messages": []}


def _assets(tmp_path: Path) -> Path:
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "index.html").write_text("<!doctype html><title>Dashboard</title>", encoding="utf-8")
    (assets / "app.js").write_text('document.title = "Dashboard";', encoding="utf-8")
    (assets / "styles.css").write_text("body { color: black; }", encoding="utf-8")
    (assets / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    (assets / "ignored.txt").write_text("not served", encoding="utf-8")
    return assets


def _authenticated_app(tmp_path: Path) -> tuple[Any, DashboardAccess, _Source, str]:
    tokens = iter(["n" * 43, "s" * 43])
    access = DashboardAccess(token_factory=lambda: next(tokens))
    access.set_available(DASHBOARD_ORIGIN)
    source = _Source()
    app = create_dashboard_app(
        access=access,
        uds_path="/tmp/unused.sock",
        data_source=source,
        assets_dir=_assets(tmp_path),
    )
    nonce = access.mint_bootstrap_url().rsplit("/", 1)[-1]
    return app, access, source, nonce


def _authenticate(client: TestClient, nonce: str):
    return client.get(f"/bootstrap/{nonce}", headers=_NAVIGATION_HEADERS, follow_redirects=False)


def test_bootstrap_sets_host_only_cookie_and_serves_authenticated_assets(tmp_path: Path) -> None:
    app, _access, _source, nonce = _authenticated_app(tmp_path)

    with TestClient(app, base_url=DASHBOARD_ORIGIN) as client:
        bootstrap = _authenticate(client, nonce)
        page = client.get("/", headers=_NAVIGATION_HEADERS)
        script = client.get("/assets/app.js", headers=_SAME_ORIGIN_HEADERS)
        icon = client.get("/assets/favicon.svg", headers=_SAME_ORIGIN_HEADERS)
        ignored = client.get("/assets/ignored.txt", headers=_SAME_ORIGIN_HEADERS)
        replay = _authenticate(client, nonce)

    assert bootstrap.status_code == 303
    assert bootstrap.headers["location"] == "/"
    cookie = bootstrap.headers["set-cookie"]
    assert "basecamp_dashboard=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/" in cookie
    assert "Max-Age=" in cookie
    assert "Secure" not in cookie
    assert "Domain=" not in cookie
    assert page.status_code == 200
    assert page.text == "<!doctype html><title>Dashboard</title>"
    assert script.status_code == 200
    assert script.headers["content-type"].startswith("text/javascript")
    assert icon.status_code == 200
    assert icon.headers["content-type"].startswith("image/svg+xml")
    assert ignored.status_code == 404
    assert replay.status_code == 404


def test_security_gate_rejects_wrong_provenance_before_proxy(tmp_path: Path) -> None:
    app, _access, source, nonce = _authenticated_app(tmp_path)

    with TestClient(app, base_url=DASHBOARD_ORIGIN) as client:
        _authenticate(client, nonce)
        wrong_host = client.get(
            "/api/snapshot",
            headers={"Host": "127.0.0.1:80", "Sec-Fetch-Site": "same-origin"},
        )
        wrong_origin = client.get(
            "/api/snapshot",
            headers={"Origin": "http://127.0.0.1:9000", "Sec-Fetch-Site": "same-origin"},
        )
        same_site = client.get("/api/snapshot", headers={"Sec-Fetch-Site": "same-site"})
        missing_fetch_metadata = client.get("/api/snapshot")
        duplicate_host = client.get(
            "/api/snapshot",
            headers=[
                ("Host", "127.0.0.1:47658"),
                ("Host", "evil.test"),
                ("Sec-Fetch-Site", "same-origin"),
            ],
        )
        duplicate_origin = client.get(
            "/api/snapshot",
            headers=[
                ("Origin", DASHBOARD_ORIGIN),
                ("Origin", "http://evil.test"),
                ("Sec-Fetch-Site", "same-origin"),
            ],
        )
        duplicate_fetch_site = client.get(
            "/api/snapshot",
            headers=[
                ("Sec-Fetch-Site", "same-origin"),
                ("Sec-Fetch-Site", "cross-site"),
            ],
        )

    assert wrong_host.status_code == 400
    assert wrong_origin.status_code == 403
    assert same_site.status_code == 403
    assert missing_fetch_metadata.status_code == 403
    assert duplicate_host.status_code == 400
    assert duplicate_origin.status_code == 403
    assert duplicate_fetch_site.status_code == 403
    assert source.calls == []


def test_authenticated_api_proxies_only_fixed_reads(tmp_path: Path) -> None:
    app, _access, source, nonce = _authenticated_app(tmp_path)

    with TestClient(app, base_url=DASHBOARD_ORIGIN) as client:
        unauthenticated = client.get("/api/snapshot", headers=_SAME_ORIGIN_HEADERS)
        unauthenticated_post = client.post("/api/snapshot", headers=_SAME_ORIGIN_HEADERS)
        _authenticate(client, nonce)
        snapshot = client.get(
            "/api/snapshot",
            params={"recent_root_limit": 10, "selected_root_handle": "root-handle"},
            headers=_SAME_ORIGIN_HEADERS,
        )
        messages = client.get(
            "/api/messages",
            params={"root_handle": "root-handle", "agent_handle": "agent-handle"},
            headers=_SAME_ORIGIN_HEADERS,
        )
        invalid_handle = client.get(
            "/api/messages",
            params={"root_handle": "root/invalid", "agent_handle": "agent-handle"},
            headers=_SAME_ORIGIN_HEADERS,
        )
        invalid_snapshot_handle = client.get(
            "/api/snapshot",
            params={"selected_root_handle": "root/invalid"},
            headers=_SAME_ORIGIN_HEADERS,
        )
        invalid_snapshot_limit = client.get(
            "/api/snapshot",
            params={"recent_root_limit": 51},
            headers=_SAME_ORIGIN_HEADERS,
        )
        post = client.post("/api/snapshot", headers=_SAME_ORIGIN_HEADERS)
        missing = [
            client.get(path, headers=_SAME_ORIGIN_HEADERS)
            for path in ("/ws", "/runs/summary", "/workstreams", "/dashboard/snapshot", "/openapi.json")
        ]

    assert unauthenticated.status_code == 401
    assert unauthenticated_post.status_code == 405
    assert snapshot.status_code == 200
    assert snapshot.json() == {"roots": [{"root_handle": "root-handle"}]}
    assert messages.status_code == 200
    assert invalid_handle.status_code == 422
    assert invalid_snapshot_handle.status_code == 422
    assert invalid_snapshot_limit.status_code == 422
    assert post.status_code == 405
    assert all(response.status_code == 404 for response in missing)
    assert source.calls == [
        ("snapshot", (10, "root-handle")),
        ("messages", ("root-handle", "agent-handle")),
    ]


def test_snapshot_busy_remains_distinct_from_hub_unavailable(tmp_path: Path) -> None:
    app, _access, source, nonce = _authenticated_app(tmp_path)

    with TestClient(app, base_url=DASHBOARD_ORIGIN) as client:
        _authenticate(client, nonce)
        source.busy = True
        busy = client.get("/api/snapshot", headers=_SAME_ORIGIN_HEADERS)
        source.busy = False
        source.fail = True
        unavailable = client.get("/api/snapshot", headers=_SAME_ORIGIN_HEADERS)

    assert busy.status_code == 429
    assert busy.headers["retry-after"] == "1"
    assert busy.json()["detail"] == "Dashboard snapshot refresh is already in progress"
    assert unavailable.status_code == 503


def test_security_headers_cover_success_and_error_responses(tmp_path: Path) -> None:
    app, _access, source, nonce = _authenticated_app(tmp_path)

    with TestClient(app, base_url=DASHBOARD_ORIGIN) as client:
        _authenticate(client, nonce)
        success = client.get("/api/snapshot", headers=_SAME_ORIGIN_HEADERS)
        source.fail = True
        unavailable = client.get("/api/snapshot", headers=_SAME_ORIGIN_HEADERS)
        forbidden = client.get("/api/snapshot", headers={"Sec-Fetch-Site": "cross-site"})

    for response in (success, unavailable, forbidden):
        assert response.headers["cache-control"] == "no-store, max-age=0"
        assert response.headers["pragma"] == "no-cache"
        assert response.headers["content-security-policy"].startswith("default-src 'none'")
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["cross-origin-opener-policy"] == "same-origin"
        assert response.headers["cross-origin-resource-policy"] == "same-origin"
        assert "access-control-allow-origin" not in response.headers
    assert unavailable.status_code == 503
    assert forbidden.status_code == 403
