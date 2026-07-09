"""Exceptions raised by the daemon SQLite store."""

from __future__ import annotations


class ActiveRunExistsError(Exception):
    """Raised when an agent already has an active primary run."""

    def __init__(self, agent_id: str) -> None:
        super().__init__(f"agent {agent_id} already has an active primary run")


class DuplicateAgentHandleError(Exception):
    """Raised when an agent handle is already assigned to another agent."""

    def __init__(self, agent_handle: str) -> None:
        super().__init__(f"agent handle {agent_handle!r} is already in use")


class DuplicateWorkstreamSlugError(Exception):
    """Raised when a workstream slug is already in use."""

    def __init__(self, slug: str) -> None:
        super().__init__(f"workstream slug {slug!r} is already in use")


class WorkstreamNotFoundError(Exception):
    """Raised when a referenced workstream does not exist."""

    def __init__(self, identifier: str) -> None:
        super().__init__(f"workstream {identifier!r} not found")
