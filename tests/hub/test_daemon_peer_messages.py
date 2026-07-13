"""Tests for daemon peer-message service metadata."""

from __future__ import annotations

import asyncio
from pathlib import Path

from basecamp.hub.frames import PROTOCOL_VERSION, PeerMessageFrame
from basecamp.hub.store import Store
from basecamp.hub.swarm.service import AcceptedPeerMessage, accept_peer_message


def test_accept_peer_message_includes_stored_sender_product_role_for_unknown_relation(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    store.upsert_agent(
        agent_id="sender-session",
        parent_id=None,
        sibling_group="sender-root",
        depth=0,
        role="agent",
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
        role="agent",
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


def test_accept_peer_message_sanitizes_sender_product_role_and_agent_type(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    dirty_role = f"\x1b[31m{'x' * 70}\x1b[0m"
    expected_role = f"{'x' * 63}…"
    store.upsert_agent(
        agent_id="sender-session",
        parent_id=None,
        sibling_group="root",
        depth=0,
        role="agent",
        session_name="Sender Session",
        cwd=str(tmp_path),
        agent_handle="sender-session-handle",
        product_role=dirty_role,
    )
    store.upsert_agent(
        agent_id="sender-agent",
        parent_id="sender-session",
        sibling_group="root",
        depth=1,
        role="worker",
        session_name="Sender Agent",
        cwd=str(tmp_path),
        agent_handle="sender-agent-handle",
        agent_type=dirty_role,
    )
    store.upsert_agent(
        agent_id="target-agent",
        parent_id="sender-session",
        sibling_group="root",
        depth=1,
        role="worker",
        session_name="Target Agent",
        cwd=str(tmp_path),
        agent_handle="target-agent-handle",
    )

    session_sender = asyncio.run(
        accept_peer_message(
            frame=_peer_message(request_id="request-session", target_handle="target-agent-handle"),
            requester_node_id="sender-session",
            store=store,
        )
    )
    agent_sender = asyncio.run(
        accept_peer_message(
            frame=_peer_message(request_id="request-agent", target_handle="target-agent-handle"),
            requester_node_id="sender-agent",
            store=store,
        )
    )

    assert isinstance(session_sender, AcceptedPeerMessage)
    assert session_sender.delivery.from_product_role == expected_role
    assert isinstance(agent_sender, AcceptedPeerMessage)
    assert agent_sender.delivery.from_product_role == expected_role


def test_accept_peer_message_agent_sender_falls_back_to_agent_type_or_subagent(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="root",
        depth=0,
        role="agent",
        session_name="Root",
        cwd=str(tmp_path),
        agent_handle="root-handle",
    )
    store.upsert_agent(
        agent_id="sender-agent",
        parent_id="root",
        sibling_group="root",
        depth=1,
        role="worker",
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
        role="worker",
        session_name="Sender Agent No Type",
        cwd=str(tmp_path),
        agent_handle="sender-agent-no-type-handle",
    )
    store.upsert_agent(
        agent_id="target-agent",
        parent_id="root",
        sibling_group="root",
        depth=1,
        role="worker",
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
