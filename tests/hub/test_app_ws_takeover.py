"""Duplicate-register takeover: liveness gating and generation-guarded cleanup."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest import mock

import pytest
from app_helpers import _answer_liveness_probe, _build_app, _build_app_with_store, _register_ws
from fastapi.testclient import TestClient

import basecamp.hub.app as app_module
import basecamp.hub.handlers as handlers_module
from basecamp.hub.frames import PROTOCOL_VERSION
from basecamp.hub.registry import Registry


def test_ws_duplicate_register_live_incumbent_rejected(tmp_path: Path) -> None:
    # A live incumbent keeps its session: the duplicate register probes it, the
    # write succeeds, and the newcomer gets the same rejection as before.
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as first:
            _register_ws(first, node_id="node-1", role="agent", parent_id=None, sibling_group="sg-main")
            # The incumbent receives the liveness probe (a ping frame) while its
            # duplicate is being classified; drain it so the read below is the error.
            with client.websocket_connect("/ws") as second:
                second.send_json(
                    {
                        "type": "register",
                        "v": PROTOCOL_VERSION,
                        "role": "agent",
                        "node_id": "node-1",
                        "parent_id": None,
                        "sibling_group": "sg-main",
                        "depth": 0,
                        "session_name": "resume-session",
                        "cwd": "/tmp/project",
                    }
                )
                # Answering the probe is what proves the incumbent live; a nonce
                # is generated per probe, so the answer must echo it.
                nonce = _answer_liveness_probe(first)
                assert nonce
                reply = second.receive_json()
                assert reply["type"] == "error"
                assert reply["code"] == "duplicate_node_connection"
            # The incumbent is still usable afterwards.
            first.send_json(
                {
                    "type": "list_agents",
                    "v": PROTOCOL_VERSION,
                    "request_id": "req-after-dup",
                    "awaitable": False,
                }
            )
            assert first.receive_json()["type"] == "list_agents_result"


def test_ws_duplicate_register_unresponsive_incumbent_is_taken_over(tmp_path: Path) -> None:
    # The case the write-only probe could never detect: the incumbent's socket
    # still accepts writes (so a send-success check reads it as live) but the
    # peer never answers. Liveness now requires the pong, so the probe times out
    # and the node id is released. A short timeout keeps the test quick.
    monkey_timeout = 0.3
    app = _build_app(tmp_path)

    with mock.patch("basecamp.hub.app._INCUMBENT_PROBE_TIMEOUT_S", monkey_timeout):
        with TestClient(app) as client:
            with client.websocket_connect("/ws") as first:
                _register_ws(first, node_id="node-1", role="agent", parent_id=None, sibling_group="sg-main")
                with client.websocket_connect("/ws") as second:
                    second.send_json(
                        {
                            "type": "register",
                            "v": PROTOCOL_VERSION,
                            "role": "agent",
                            "node_id": "node-1",
                            "parent_id": None,
                            "sibling_group": "sg-main",
                            "depth": 0,
                            "session_name": "resume-session",
                            "cwd": "/tmp/project",
                        }
                    )
                    # `first` deliberately never answers the probe.
                    assert second.receive_json()["type"] == "registered"


def test_ws_reregister_after_clean_disconnect_needs_no_probe(tmp_path: Path) -> None:
    # A cleanly closed incumbent is already out of the registry by the time the
    # replacement registers, so the probe is never consulted. Asserted rather
    # than assumed, because a probe call here would mean the takeover path is
    # being entered for a node id nobody holds.
    probes: list[str] = []
    app = _build_app(tmp_path)
    real_probe = app_module._incumbent_is_live

    async def counting_probe(incumbent, node_id, registry):  # type: ignore[no-untyped-def]
        probes.append(node_id)
        return await real_probe(incumbent, node_id, registry)

    with mock.patch.object(app_module, "_incumbent_is_live", counting_probe):
        with TestClient(app) as client:
            with client.websocket_connect("/ws") as first:
                _register_ws(first, node_id="node-1", role="agent", parent_id=None, sibling_group="sg-main")
                first.close()
                with client.websocket_connect("/ws") as second:
                    _register_ws(second, node_id="node-1", role="agent", parent_id=None, sibling_group="sg-main")
                    second.send_json(
                        {
                            "type": "list_agents",
                            "v": PROTOCOL_VERSION,
                            "request_id": "req-after-reregister",
                            "awaitable": False,
                        }
                    )
                    assert second.receive_json()["type"] == "list_agents_result"

    assert probes == []


def test_ws_takeover_stale_cleanup_does_not_reap_new_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The genuine stale-handler race, reachable now that an unanswered probe
    # yields the node id: the incumbent is still connected (its handler has not
    # unwound) when the replacement claims gen2. When that stale handler finally
    # runs its cleanup it must remove nothing and reap nothing — only the
    # replacement's own disconnect may schedule a reaper. A missing generation
    # guard would drop the live gen2 entry and add a reaper for a connected node.
    reaped: list[str] = []
    monkeypatch.setattr(
        "basecamp.hub.app.schedule_disconnect_reaper",
        lambda **kwargs: reaped.append(str(kwargs["node_id"])),
    )
    app = _build_app(tmp_path)

    with mock.patch.object(app_module, "_INCUMBENT_PROBE_TIMEOUT_S", 0.3):
        with TestClient(app) as client:
            with client.websocket_connect("/ws") as first:
                _register_ws(first, node_id="node-1", role="agent", parent_id=None, sibling_group="sg-main")
                with client.websocket_connect("/ws") as second:
                    second.send_json(
                        {
                            "type": "register",
                            "v": PROTOCOL_VERSION,
                            "role": "agent",
                            "node_id": "node-1",
                            "parent_id": None,
                            "sibling_group": "sg-main",
                            "depth": 0,
                            "session_name": "resume-session",
                            "cwd": "/tmp/project",
                        }
                    )
                    # `first` never answers: it is displaced while still connected.
                    assert second.receive_json()["type"] == "registered"
                    # The replacement owns the node id and is routable.
                    second.send_json(
                        {
                            "type": "list_agents",
                            "v": PROTOCOL_VERSION,
                            "request_id": "req-after-takeover",
                            "awaitable": False,
                        }
                    )
                    assert second.receive_json()["type"] == "list_agents_result"
                    # The displaced handler has unwound by now; its cleanup was a no-op.
                    assert reaped == []

    assert reaped == ["node-1"]


def test_ws_ping_answered_with_pong_and_pong_ignored(tmp_path: Path) -> None:
    # Keepalive contract: ping gets a pong with the same nonce; an unsolicited
    # pong is inert (the connection simply continues).
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            _register_ws(ws, node_id="node-1", role="agent", parent_id=None, sibling_group="sg-main")
            ws.send_json({"type": "pong", "v": PROTOCOL_VERSION, "nonce": "unsolicited"})
            ws.send_json({"type": "ping", "v": PROTOCOL_VERSION, "nonce": "nonce-42"})
            reply = ws.receive_json()
            assert reply == {"type": "pong", "v": PROTOCOL_VERSION, "nonce": "nonce-42"}
            ws.send_json(
                {
                    "type": "list_agents",
                    "v": PROTOCOL_VERSION,
                    "request_id": "req-after-ping",
                    "awaitable": False,
                }
            )
            assert ws.receive_json()["type"] == "list_agents_result"


def _seed_blocking_run(store, *, dispatcher_id: str, agent_handle: str) -> None:
    """Register an agent with a live non-terminal run owned by dispatcher_id.

    A wait on this handle blocks on the waiter future for its full timeout,
    which is what makes the read-loop and cancellation assertions meaningful.
    """
    store.upsert_agent(
        agent_id="agent-blocking",
        agent_handle=agent_handle,
        parent_id=dispatcher_id,
        sibling_group=dispatcher_id,
        depth=1,
        role="worker",
        session_name=agent_handle,
        cwd="/tmp/agent-blocking",
    )
    store.create_run(
        run_id="run-blocking",
        agent_id="agent-blocking",
        dispatcher_id=dispatcher_id,
        spec={"task": "blocking"},
        report_token_hash="hash",
    )


def test_ws_wait_does_not_block_connection_read_loop(tmp_path: Path) -> None:
    # v28: the wait runs as a daemon-side task, so the socket keeps serving
    # other frames while it is outstanding. The wait here genuinely parks — a
    # real non-terminal run, so wait_for_agents reaches asyncio.wait_for and
    # stays there for the full timeout. Frame ORDER is the discriminator: with
    # a task the pong overtakes the wait_result; awaited inline the read loop
    # could not reach the ping until the wait had already answered.
    app, store = _build_app_with_store(tmp_path)
    _seed_blocking_run(store, dispatcher_id="node-1", agent_handle="amber-fox-a1b2c3")

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            _register_ws(ws, node_id="node-1", role="agent", parent_id=None, sibling_group="sg-main")
            ws.send_json(
                {
                    "type": "wait",
                    "v": PROTOCOL_VERSION,
                    "request_id": "wait-block-1",
                    "agent_handles": ["amber-fox-a1b2c3"],
                    "mode": "all",
                    "timeout_s": 1.0,
                }
            )
            ws.send_json({"type": "ping", "v": PROTOCOL_VERSION, "nonce": "during-wait"})

            first_frame = ws.receive_json()
            assert first_frame["type"] == "pong"
            assert first_frame["nonce"] == "during-wait"

            second_frame = ws.receive_json()
            assert second_frame["type"] == "wait_result"
            assert second_frame["request_id"] == "wait-block-1"
            # Still non-terminal when the wait timed out, so it reports running.
            assert [item["status"] for item in second_frame["results"]] == ["running"]


def test_ws_disconnect_mid_wait_cancels_the_pending_reply_task(tmp_path: Path) -> None:
    # A client that disconnects while a wait is genuinely outstanding must not
    # leave the reply task alive to resolve later and write to a dead socket.
    # The wait is parked on a real non-terminal run for 30s, so the task is
    # unambiguously pending at disconnect. The assertion runs after the socket
    # closes but BEFORE app teardown — otherwise loop shutdown cancels the task
    # anyway and the check cannot tell who did it.
    app, store = _build_app_with_store(tmp_path)
    _seed_blocking_run(store, dispatcher_id="node-1", agent_handle="amber-fox-a1b2c3")
    tasks: list[asyncio.Task[None]] = []
    real_create_task = asyncio.create_task

    def capture(coro, *args, **kwargs):  # type: ignore[no-untyped-def]
        task = real_create_task(coro, *args, **kwargs)
        tasks.append(task)
        return task

    with mock.patch.object(app_module.asyncio, "create_task", capture):
        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
                _register_ws(ws, node_id="node-1", role="agent", parent_id=None, sibling_group="sg-main")
                ws.send_json(
                    {
                        "type": "wait",
                        "v": PROTOCOL_VERSION,
                        "request_id": "wait-abandoned",
                        "agent_handles": ["amber-fox-a1b2c3"],
                        "mode": "all",
                        "timeout_s": 30,
                    }
                )
                # Round-trip a ping to prove the wait task exists and is parked.
                ws.send_json({"type": "ping", "v": PROTOCOL_VERSION, "nonce": "n"})
                assert ws.receive_json()["type"] == "pong"
                assert tasks, "the wait should have been spawned as a task"
                assert not tasks[0].done()

            # Socket closed, handler unwound, app still running.
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not tasks[0].done():
                time.sleep(0.02)
            assert tasks[0].done(), "reply task outlived its connection"
            assert tasks[0].cancelled()


def test_ws_wait_store_failure_still_answers_the_requester(tmp_path: Path) -> None:
    # A reply task runs detached, so a store failure inside it used to reach
    # nobody: no wait_result, no error, socket open, and a client whose
    # waitForFrame has no deadline waits forever. The requester must always get
    # a correlated reply; "unknown" is the honest answer when the daemon could
    # not determine the state.
    app = _build_app(tmp_path)

    class StoreFailureError(RuntimeError):
        pass

    def boom(**_kwargs: object) -> None:
        raise StoreFailureError

    with mock.patch.object(handlers_module, "wait_for_agents", boom):
        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
                _register_ws(ws, node_id="node-1", role="agent", parent_id=None, sibling_group="sg-main")
                ws.send_json(
                    {
                        "type": "wait",
                        "v": PROTOCOL_VERSION,
                        "request_id": "wait-failing",
                        "agent_handles": ["amber-fox-a1b2c3"],
                        "mode": "all",
                        "timeout_s": 30,
                    }
                )
                reply = ws.receive_json()

    assert reply["type"] == "wait_result"
    assert reply["request_id"] == "wait-failing"
    assert [item["status"] for item in reply["results"]] == ["unknown"]


@pytest.mark.asyncio
async def test_registry_probes_are_isolated_by_nonce() -> None:
    # Two registrations can probe one node id concurrently. Keyed by node alone,
    # the second probe cancelled the first's future, which _incumbent_is_live
    # reads as "dead" — evicting a LIVE incumbent purely because someone else
    # probed at the same time. Each probe must own its own future, and a pong
    # must only answer the ping that carries its nonce.
    registry = Registry()

    first = registry.open_probe("node-1", "nonce-a")
    second = registry.open_probe("node-1", "nonce-b")

    # Arming the second must not disturb the first.
    assert not first.cancelled()
    assert not first.done()

    # A pong resolves only its own probe.
    registry.resolve_probe("node-1", "nonce-b")
    assert second.done()
    assert not first.done()

    # An unrelated nonce answers nothing.
    registry.resolve_probe("node-1", "nonce-unknown")
    assert not first.done()

    # Closing one probe leaves the other intact.
    registry.close_probe("node-1", "nonce-b")
    assert not first.done()

    registry.resolve_probe("node-1", "nonce-a")
    assert first.done()
    registry.close_probe("node-1", "nonce-a")


def test_registry_claim_connection_is_compare_and_set() -> None:
    # Probing suspends, so two registrations can reach the claim for one node id.
    # The claim must be conditional on the entry the caller observed before it
    # awaited, or the loser silently keeps serving frames while unroutable.
    registry = Registry()

    # Unheld id, claimed against "nothing was there": succeeds.
    first_gen = registry.claim_connection("node-1", object(), replacing=None)
    assert first_gen is not None

    # A second claimant that also observed "nothing was there" loses, because
    # the id is now held — this is the concurrent-register race.
    assert registry.claim_connection("node-1", object(), replacing=None) is None
    assert registry.get_connection_generation("node-1") == first_gen

    # A claimant that observed the current holder (the takeover path) wins.
    second_gen = registry.claim_connection("node-1", object(), replacing=first_gen)
    assert second_gen is not None
    assert second_gen > first_gen

    # A claimant still holding a stale observation loses.
    assert registry.claim_connection("node-1", object(), replacing=first_gen) is None
    assert registry.get_connection_generation("node-1") == second_gen


def test_registry_remove_connection_generation_guard() -> None:
    registry = Registry()
    first_gen = registry.set_connection("node-1", object())
    second_gen = registry.set_connection("node-1", object())
    assert second_gen > first_gen

    assert registry.remove_connection("node-1", generation=first_gen) is False
    assert registry.get_connection_generation("node-1") == second_gen

    assert registry.remove_connection("node-1", generation=second_gen) is True
    assert registry.get_connection("node-1") is None
    assert registry.remove_connection("node-1", generation=second_gen) is False
