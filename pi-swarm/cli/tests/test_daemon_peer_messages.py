"""Tests for daemon peer-message service metadata."""

from __future__ import annotations

import asyncio
from pathlib import Path

from pi_swarm.frames import PROTOCOL_VERSION, PeerMessageFrame
from pi_swarm.service import AcceptedPeerMessage, accept_peer_message
from pi_swarm.store import Store


def test_accept_peer_message_includes_stored_sender_product_role_for_unknown_relation(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    store.upsert_agent(
        agent_id="sender-session",
        parent_id=None,
        sibling_group="sender-root",
        depth=0,
        role="session",
        session_name="Sender",
        cwd=str(tmp_path),
        agent_handle="clear-falcon-80cda5",
        product_role="copilot",
    )
    store.upsert_agent(
        agent_id="target-session",
        parent_id=None,
        sibling_group="target-root",
        depth=0,
        role="session",
        session_name="Target",
        cwd=str(tmp_path),
        agent_handle="quiet-badger-3dc450",
    )

    accepted = asyncio.run(
        accept_peer_message(
            frame=_peer_message(target_handle="quiet-badger-3dc450"),
            requester_node_id="sender-session",
            store=store,
        )
    )

    assert isinstance(accepted, AcceptedPeerMessage)
    assert accepted.delivery.from_relation == "unknown"
    assert accepted.delivery.from_product_role == "copilot"


def test_accept_peer_message_agent_sender_falls_back_to_agent_type_or_subagent(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="root",
        depth=0,
        role="session",
        session_name="Root",
        cwd=str(tmp_path),
        agent_handle="root-handle",
    )
    store.upsert_agent(
        agent_id="sender-agent",
        parent_id="root",
        sibling_group="root",
        depth=1,
        role="agent",
        session_name="Sender Agent",
        cwd=str(tmp_path),
        agent_handle="sender-agent-handle",
        agent_type="testing-specialist",
        product_role="copilot",
    )
    store.upsert_agent(
        agent_id="sender-agent-no-type",
        parent_id="root",
        sibling_group="root",
        depth=1,
        role="agent",
        session_name="Sender Agent No Type",
        cwd=str(tmp_path),
        agent_handle="sender-agent-no-type-handle",
    )
    store.upsert_agent(
        agent_id="target-agent",
        parent_id="root",
        sibling_group="root",
        depth=1,
        role="agent",
        session_name="Target Agent",
        cwd=str(tmp_path),
        agent_handle="target-agent-handle",
    )

    with_type = asyncio.run(
        accept_peer_message(
            frame=_peer_message(request_id="request-type", target_handle="target-agent-handle"),
            requester_node_id="sender-agent",
            store=store,
        )
    )
    without_type = asyncio.run(
        accept_peer_message(
            frame=_peer_message(request_id="request-subagent", target_handle="target-agent-handle"),
            requester_node_id="sender-agent-no-type",
            store=store,
        )
    )

    assert isinstance(with_type, AcceptedPeerMessage)
    assert with_type.delivery.from_product_role == "testing-specialist"
    assert isinstance(without_type, AcceptedPeerMessage)
    assert without_type.delivery.from_product_role == "subagent"


def _peer_message(*, target_handle: str, request_id: str = "request-1") -> PeerMessageFrame:
    return PeerMessageFrame(
        type="peer_message",
        v=PROTOCOL_VERSION,
        request_id=request_id,
        target_handle=target_handle,
        message="hello",
        interrupt=False,
    )
