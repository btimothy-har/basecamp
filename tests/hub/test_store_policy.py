"""Tests for daemon store reachability, messaging, and cancellation policy."""

from __future__ import annotations

from pathlib import Path

from basecamp.hub.store import Store


def test_can_ask_allows_ancestors_descendants_and_siblings_only(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="agent-a",
        parent_id="root",
        sibling_group="root",
        depth=1,
        role="agent",
        session_name="agent-a",
        cwd="/tmp/a",
    )
    store.upsert_agent(
        agent_id="agent-b",
        parent_id="root",
        sibling_group="root",
        depth=1,
        role="agent",
        session_name="agent-b",
        cwd="/tmp/b",
    )
    store.upsert_agent(
        agent_id="grandchild",
        parent_id="agent-a",
        sibling_group="agent-a",
        depth=2,
        role="agent",
        session_name="grandchild",
        cwd="/tmp/grandchild",
    )
    store.upsert_agent(
        agent_id="outside-root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="outside-root",
        cwd="/tmp/outside-root",
    )
    store.upsert_agent(
        agent_id="outside-agent",
        parent_id="outside-root",
        sibling_group="outside-root",
        depth=1,
        role="agent",
        session_name="outside-agent",
        cwd="/tmp/outside-agent",
    )

    assert store.can_ask("grandchild", "agent-a") is True
    assert store.can_ask("agent-a", "grandchild") is True
    assert store.can_ask("agent-a", "agent-b") is True
    assert store.can_ask("agent-a", "agent-a") is True
    assert store.can_ask("agent-a", "outside-agent") is False
    assert store.can_ask("root", "outside-root") is False
    assert store.can_ask("agent-a", "missing") is False
    assert store.can_ask("missing", "agent-a") is False


def test_can_message_allows_visible_sessions_agents_and_siblings_only(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="agent-a",
        parent_id="root",
        sibling_group="root",
        depth=1,
        role="agent",
        session_name="agent-a",
        cwd="/tmp/a",
    )
    store.upsert_agent(
        agent_id="agent-b",
        parent_id="root",
        sibling_group="root",
        depth=1,
        role="agent",
        session_name="agent-b",
        cwd="/tmp/b",
    )
    store.upsert_agent(
        agent_id="grandchild",
        parent_id="agent-a",
        sibling_group="agent-a",
        depth=2,
        role="agent",
        session_name="grandchild",
        cwd="/tmp/grandchild",
    )
    store.upsert_agent(
        agent_id="outside-root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="outside-root",
        cwd="/tmp/outside-root",
    )
    store.upsert_agent(
        agent_id="outside-agent",
        parent_id="outside-root",
        sibling_group="outside-root",
        depth=1,
        role="agent",
        session_name="outside-agent",
        cwd="/tmp/outside-agent",
    )

    assert store.can_message("grandchild", "root") is True
    assert store.can_message("root", "grandchild") is True
    assert store.can_message("agent-a", "agent-b") is True
    assert store.can_message("agent-a", "agent-a") is True
    assert store.can_message("agent-a", "outside-agent") is False
    assert store.can_message("root", "outside-root") is False
    assert store.can_message("agent-a", "missing") is False
    assert store.can_message("missing", "agent-a") is False

    assert store.agent_relation("agent-a", "agent-a") == "self"
    assert store.agent_relation("grandchild", "agent-a") == "parent"
    assert store.agent_relation("grandchild", "root") == "ancestor"
    assert store.agent_relation("root", "agent-a") == "child"
    assert store.agent_relation("root", "grandchild") == "descendant"
    assert store.agent_relation("agent-a", "agent-b") == "peer"
    assert store.agent_relation("agent-a", "outside-agent") == "unknown"
    assert store.agent_relation("agent-a", "missing") == "unknown"


def test_can_cancel_allows_dispatcher_ancestors_only_and_rejects_public_handle_authority(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="root",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="parent",
        parent_id="root",
        sibling_group="root",
        depth=1,
        role="agent",
        session_name="parent",
        cwd="/tmp/parent",
    )
    store.upsert_agent(
        agent_id="grandchild",
        agent_handle="grandchild-public",
        parent_id="parent",
        sibling_group="parent",
        depth=2,
        role="agent",
        session_name="grandchild",
        cwd="/tmp/grandchild",
    )
    store.create_run(
        run_id="run-grandchild",
        agent_id="grandchild",
        dispatcher_id="parent",
        spec={"task": "work"},
        report_token_hash="hash",
    )
    store.upsert_agent(
        agent_id="unrelated",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="unrelated",
        cwd="/tmp/unrelated",
    )
    store.upsert_agent(
        agent_id="retasked",
        agent_handle="retasked-public",
        parent_id="unrelated",
        sibling_group="unrelated",
        depth=1,
        role="agent",
        session_name="retasked",
        cwd="/tmp/retasked",
    )
    store.create_run(
        run_id="run-retasked",
        agent_id="retasked",
        dispatcher_id="root",
        spec={"task": "retasked work"},
        report_token_hash="hash",
    )

    assert store.can_cancel("parent", "grandchild") is True
    assert store.can_cancel("root", "grandchild") is True
    assert store.can_cancel("root", "retasked") is True
    assert store.can_cancel("unrelated", "grandchild") is False
    assert store.can_cancel("grandchild", "grandchild") is False
    assert store.can_cancel("grandchild", "root") is False


def test_known_public_handle_contact_is_allowed_across_unrelated_roots(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="outside-root",
        parent_id=None,
        sibling_group="outside-root",
        depth=0,
        role="session",
        session_name="outside-root",
        cwd="/tmp/outside-root",
    )
    store.upsert_agent(
        agent_id="outside-agent",
        agent_handle="outside-handle",
        parent_id="outside-root",
        sibling_group="outside-root",
        depth=1,
        role="agent",
        session_name="outside-agent",
        cwd="/tmp/outside-agent",
    )
    store.upsert_agent(
        agent_id="private-agent-id",
        parent_id="outside-root",
        sibling_group="outside-root",
        depth=1,
        role="agent",
        session_name="private-agent",
        cwd="/tmp/private-agent",
    )

    # Without known-handle addressing, an unrelated target stays denied.
    assert store.can_message("root", "outside-agent") is False
    assert store.can_ask("root", "outside-agent") is False

    # A known public handle is a routable contact address across unrelated roots.
    assert store.can_message("root", "outside-agent", addressed_by_public_handle=True) is True
    assert store.can_ask("root", "outside-agent", addressed_by_public_handle=True) is True

    # An agent whose handle falls back to its private id exposes no public handle,
    # so known-handle addressing does not relax private-id routing.
    assert store.can_message("root", "private-agent-id", addressed_by_public_handle=True) is False
    assert store.can_ask("root", "private-agent-id", addressed_by_public_handle=True) is False

    # A missing requester or target is never reachable, even by known handle.
    assert store.can_message("missing", "outside-agent", addressed_by_public_handle=True) is False
    assert store.can_message("root", "missing", addressed_by_public_handle=True) is False
