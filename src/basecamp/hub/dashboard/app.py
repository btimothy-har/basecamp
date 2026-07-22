"""Authenticated, read-only localhost dashboard FastAPI app."""

from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi import Path as FastAPIPath
from fastapi.responses import JSONResponse, RedirectResponse, Response

from .access import DashboardAccess
from .uds import DashboardDataSource, DashboardUdsClient, DashboardUdsError

DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = 47658
DASHBOARD_ORIGIN = f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}"
DASHBOARD_COOKIE = "basecamp_dashboard"
PUBLIC_HANDLE_PATTERN = r"^[A-Za-z0-9_.-]+$"
PublicHandle = Annotated[str, Query(min_length=1, max_length=128, pattern=PUBLIC_HANDLE_PATTERN)]
BootstrapNonce = Annotated[str, FastAPIPath(min_length=32, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]

_SECURITY_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
    "Content-Security-Policy": (
        "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; "
        "script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; "
        "font-src 'none'; object-src 'none'; manifest-src 'none'; worker-src 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": (
        "accelerometer=(), autoplay=(), camera=(), display-capture=(), fullscreen=(), "
        "geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()"
    ),
}


class DashboardAssetError(RuntimeError):
    """Packaged dashboard assets are missing or unreadable."""

    def __init__(self) -> None:
        super().__init__("dashboard index asset is unavailable")


def _asset_bundle(assets_dir: Path) -> tuple[bytes, dict[str, tuple[bytes, str]]]:
    index_path = assets_dir / "index.html"
    try:
        index = index_path.read_bytes()
    except OSError as error:
        raise DashboardAssetError from error

    assets: dict[str, tuple[bytes, str]] = {}
    for path in assets_dir.iterdir():
        if not path.is_file() or path.suffix not in {".css", ".js", ".svg"}:
            continue
        content_type = "text/javascript" if path.suffix == ".js" else mimetypes.guess_type(path.name)[0]
        assets[path.name] = (path.read_bytes(), content_type or "application/octet-stream")
    return index, assets


def create_dashboard_app(
    *,
    access: DashboardAccess,
    uds_path: str,
    data_source: DashboardDataSource | None = None,
    assets_dir: Path | None = None,
    expected_host: str = f"{DASHBOARD_HOST}:{DASHBOARD_PORT}",
    expected_origin: str = DASHBOARD_ORIGIN,
) -> FastAPI:
    """Build the TCP-only dashboard app with no daemon control routes."""

    source = data_source or DashboardUdsClient(uds_path)
    asset_root = assets_dir or Path(__file__).with_name("assets")
    index, assets = _asset_bundle(asset_root)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def protect_request(request: Request, call_next: Any) -> Response:
        host_values = _header_values(request, b"host")
        origin_values = _header_values(request, b"origin")
        fetch_site_values = _header_values(request, b"sec-fetch-site")
        if host_values != [expected_host]:
            response: Response = Response("Bad request", status_code=400, media_type="text/plain")
        elif request.method != "GET":
            response = Response("Method not allowed", status_code=405, media_type="text/plain")
        elif len(origin_values) > 1 or (origin_values and origin_values[0] != expected_origin):
            response = Response("Forbidden", status_code=403, media_type="text/plain")
        elif len(fetch_site_values) != 1 or not _fetch_site_allowed(request.url.path, fetch_site_values[0]):
            response = Response("Forbidden", status_code=403, media_type="text/plain")
        else:
            response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers[name] = value
        return response

    def require_session(request: Request) -> None:
        if not access.validate_session(request.cookies.get(DASHBOARD_COOKIE)):
            raise HTTPException(status_code=401, detail="Dashboard authentication required")

    authenticated = [Depends(require_session)]

    @app.get("/bootstrap/{nonce}")
    async def bootstrap(nonce: BootstrapNonce) -> Response:
        session = access.redeem_bootstrap(nonce)
        if session is None:
            raise HTTPException(status_code=404, detail="Dashboard bootstrap is invalid or expired")
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(
            DASHBOARD_COOKIE,
            session,
            max_age=access.session_max_age,
            path="/",
            secure=False,
            httponly=True,
            samesite="strict",
        )
        return response

    @app.get("/", dependencies=authenticated)
    async def index_page() -> Response:
        return Response(index, media_type="text/html")

    @app.get("/assets/{asset_name}", dependencies=authenticated)
    async def static_asset(asset_name: str) -> Response:
        asset = assets.get(asset_name)
        if asset is None:
            raise HTTPException(status_code=404)
        content, content_type = asset
        return Response(content, media_type=content_type)

    @app.get("/api/snapshot", dependencies=authenticated)
    async def snapshot() -> JSONResponse:
        try:
            payload = await asyncio.to_thread(source.get_snapshot)
        except DashboardUdsError as error:
            raise HTTPException(status_code=503, detail="Dashboard data is temporarily unavailable") from error
        return JSONResponse(payload)

    @app.get("/api/messages", dependencies=authenticated)
    async def messages(root_handle: PublicHandle, agent_handle: PublicHandle) -> JSONResponse:
        try:
            payload = await asyncio.to_thread(
                source.get_messages,
                root_handle=root_handle,
                agent_handle=agent_handle,
            )
        except DashboardUdsError as error:
            raise HTTPException(status_code=503, detail="Dashboard data is temporarily unavailable") from error
        return JSONResponse(payload)

    return app


def _header_values(request: Request, name: bytes) -> list[str]:
    return [value.decode("latin-1") for key, value in request.scope["headers"] if key.lower() == name]


def _fetch_site_allowed(path: str, fetch_site: str | None) -> bool:
    if path == "/" or path.startswith("/bootstrap/"):
        return fetch_site in {"none", "same-origin"}
    return fetch_site == "same-origin"
