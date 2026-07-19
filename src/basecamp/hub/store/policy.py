"""Agent reachability and cancellation policy mixin."""

from __future__ import annotations

from typing import Any, Literal

AgentRelation = Literal["self", "parent", "ancestor", "child", "descendant", "peer", "unknown"]


class PolicyMixin:
    """Reachability, contact, and cancellation policy checks."""

    def can_ask(
        self,
        requester_node_id: str,
        target_agent_id: str,
        *,
        addressed_by_public_handle: bool = False,
    ) -> bool:
        """Return whether requester may fork-ask the target agent.

        Relationship reachability (self/ancestor/descendant/sibling) always
        authorizes. When the caller addressed the target by its known public
        handle, contact is also allowed without a live relationship: the handle
        is a routable contact address, not authorization for introspection.
        """

        if self._can_reach_agent(requester_node_id, target_agent_id):
            return True
        if addressed_by_public_handle:
            return self._can_contact_by_public_handle(requester_node_id, target_agent_id)
        return False

    def can_message(
        self,
        requester_node_id: str,
        target_agent_id: str,
        *,
        addressed_by_public_handle: bool = False,
    ) -> bool:
        """Return whether requester may send a live peer message to the target.

        See :meth:`can_ask` for how known-public-handle contact relates to
        relationship reachability.
        """

        if self._can_reach_agent(requester_node_id, target_agent_id):
            return True
        if addressed_by_public_handle:
            return self._can_contact_by_public_handle(requester_node_id, target_agent_id)
        return False

    def can_cancel(self, requester_node_id: str, target_agent_id: str) -> bool:
        """Return whether requester may cancel target's current run.

        Cancellation uses subtree authority only: the requester must have
        dispatched the target directly or transitively. A known public handle is
        a routable contact address only and does NOT authorize cancellation.
        """

        if requester_node_id == target_agent_id:
            return False
        if self._parent_chain_contains(target_agent_id, requester_node_id):
            return True

        target = self.get_agent(target_agent_id)
        if target is None:
            return False
        run_id = target.get("current_run_id")
        if not isinstance(run_id, str):
            return False
        run = self.get_run(run_id)
        return run is not None and run.get("dispatcher_id") == requester_node_id

    def agent_relation(self, viewer_agent_id: str, other_agent_id: str) -> AgentRelation:
        """Return how the other agent relates to the viewer."""

        viewer = self.get_agent(viewer_agent_id)
        other = self.get_agent(other_agent_id)
        if viewer is None or other is None:
            return "unknown"
        if viewer_agent_id == other_agent_id:
            return "self"
        if viewer.get("parent_id") == other_agent_id:
            return "parent"
        if other.get("parent_id") == viewer_agent_id:
            return "child"
        if self._parent_chain_contains(viewer_agent_id, other_agent_id):
            return "ancestor"
        if self._parent_chain_contains(other_agent_id, viewer_agent_id):
            return "descendant"

        viewer_sibling_group = viewer.get("sibling_group")
        if viewer_sibling_group is not None and viewer_sibling_group == other.get("sibling_group"):
            return "peer"
        return "unknown"

    def _can_reach_agent(self, requester_node_id: str, target_agent_id: str) -> bool:
        requester = self.get_agent(requester_node_id)
        target = self.get_agent(target_agent_id)
        if requester is None or target is None:
            return False
        if requester_node_id == target_agent_id:
            return True

        if self._parent_chain_contains(requester_node_id, target_agent_id):
            return True
        if self._parent_chain_contains(target_agent_id, requester_node_id):
            return True

        requester_sibling_group = requester.get("sibling_group")
        return requester_sibling_group is not None and requester_sibling_group == target.get("sibling_group")

    def _can_contact_by_public_handle(self, requester_node_id: str, target_agent_id: str) -> bool:
        """Allow contact when the requester is a registered node and the target
        exposes a public handle. This is a routable contact path only; it never
        grants directory listing, transcript access, or wait-result ownership."""

        requester = self.get_agent(requester_node_id)
        target = self.get_agent(target_agent_id)
        if requester is None or target is None:
            return False
        if requester_node_id == target_agent_id:
            return True
        return self._agent_has_public_handle(target)

    @staticmethod
    def _agent_has_public_handle(agent: dict[str, Any]) -> bool:
        if agent.get("role") not in {"agent", "worker"}:
            return False
        handle = agent.get("agent_handle")
        agent_id = agent.get("id")
        return isinstance(handle, str) and bool(handle) and handle != agent_id

    def _parent_chain_contains(self, agent_id: str, target_agent_id: str) -> bool:
        visited: set[str] = set()
        current = agent_id

        while isinstance(current, str) and current not in visited:
            visited.add(current)
            row = self.get_agent(current)
            if row is None:
                return False

            parent_id = row.get("parent_id")
            if not isinstance(parent_id, str) or not parent_id.strip():
                return False
            if parent_id == target_agent_id:
                return True
            current = parent_id

        return False
