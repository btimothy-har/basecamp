"""FastAPI application for the basecamp daemon skeleton."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from basecamp.daemon.frames import (
    PROTOCOL_VERSION,
    ErrorFrame,
    RegisteredFrame,
    RegisterFrame,
    parse_frame,
    serialize_frame,
)
from basecamp.daemon.registry import Registry
from basecamp.daemon.store import Store


def create_app(store: Store) -> FastAPI:
    """Create and configure the daemon FastAPI app."""

    app = FastAPI()
    registry = Registry()

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "protocol": PROTOCOL_VERSION}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()

        try:
            first_payload = await websocket.receive_json()
            if not isinstance(first_payload, dict):
                await _send_error_and_close(
                    websocket,
                    code="invalid_frame",
                    message="Expected a JSON object frame.",
                )
                return

            version = first_payload.get("v")
            if version != PROTOCOL_VERSION:
                await _send_error_and_close(
                    websocket,
                    code="protocol_version",
                    message=(f"Unsupported protocol version {version!r}; expected {PROTOCOL_VERSION}."),
                )
                return

            parsed = parse_frame(first_payload)
            if not isinstance(parsed, RegisterFrame):
                await _send_error_and_close(
                    websocket,
                    code="invalid_register",
                    message="First frame must be a register frame.",
                )
                return

            store.upsert_agent(
                agent_id=parsed.node_id,
                parent_id=parsed.parent_id,
                sibling_group=parsed.sibling_group,
                depth=parsed.depth,
                role=parsed.role,
                session_name=parsed.session_name,
                cwd=parsed.cwd,
            )
            registry.set_connection(parsed.node_id, websocket)

            registered = RegisteredFrame(
                type="registered",
                v=PROTOCOL_VERSION,
                node_id=parsed.node_id,
                protocol=PROTOCOL_VERSION,
            )
            await websocket.send_json(serialize_frame(registered))

            while True:
                await websocket.receive_json()

        except WebSocketDisconnect:
            return
        except Exception as exc:  # noqa: BLE001
            await _send_error_and_close(
                websocket,
                code="invalid_frame",
                message=f"Failed to parse frame: {exc}",
            )
        finally:
            node_id = None
            if isinstance(locals().get("parsed"), RegisterFrame):
                node_id = parsed.node_id
            if node_id is not None:
                registry.remove_connection(node_id)

    return app


async def _send_error_and_close(websocket: WebSocket, *, code: str, message: str) -> None:
    error = ErrorFrame(type="error", v=PROTOCOL_VERSION, code=code, message=message)
    await websocket.send_json(serialize_frame(error))
    await websocket.close(code=1002)
