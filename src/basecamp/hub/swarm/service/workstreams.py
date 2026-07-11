"""Workstream lifecycle: create, attach agents, and update status."""

from __future__ import annotations

import asyncio

from ...frames import (
    PROTOCOL_VERSION,
    AttachWorkstreamAgentAckFrame,
    AttachWorkstreamAgentFrame,
    CreateWorkstreamAckFrame,
    CreateWorkstreamFrame,
    UpdateWorkstreamAckFrame,
    UpdateWorkstreamFrame,
)
from ...store import DuplicateWorkstreamSlugError, Store, WorkstreamNotFoundError


async def create_workstream(
    *,
    frame: CreateWorkstreamFrame,
    store: Store,
) -> CreateWorkstreamAckFrame:
    """Create a workstream, returning a slug-conflict ack on duplicate slug."""

    try:
        await asyncio.to_thread(
            store.create_workstream,
            workstream_id=frame.workstream_id,
            slug=frame.slug,
            label=frame.label,
            brief=frame.brief,
            source_dossier_path=frame.source_dossier_path,
            constraints=frame.constraints,
            source_repo_page_path=frame.source_repo_page_path,
        )
    except DuplicateWorkstreamSlugError:
        return CreateWorkstreamAckFrame(
            type="create_workstream_ack",
            v=PROTOCOL_VERSION,
            request_id=frame.request_id,
            status="slug_conflict",
            error=None,
        )
    except Exception as exc:  # noqa: BLE001
        return CreateWorkstreamAckFrame(
            type="create_workstream_ack",
            v=PROTOCOL_VERSION,
            request_id=frame.request_id,
            status="error",
            error=str(exc),
        )
    return CreateWorkstreamAckFrame(
        type="create_workstream_ack",
        v=PROTOCOL_VERSION,
        request_id=frame.request_id,
        status="created",
        workstream_id=frame.workstream_id,
        slug=frame.slug,
        error=None,
    )


async def attach_workstream_agent(
    *,
    frame: AttachWorkstreamAgentFrame,
    requester_node_id: str,
    store: Store,
) -> AttachWorkstreamAgentAckFrame:
    """Attach the requester's own node to a workstream by id or slug."""

    workstream = await asyncio.to_thread(store.get_workstream, frame.workstream)
    if workstream is None:
        return AttachWorkstreamAgentAckFrame(
            type="attach_workstream_agent_ack",
            v=PROTOCOL_VERSION,
            request_id=frame.request_id,
            status="not_found",
            error=None,
        )
    try:
        await asyncio.to_thread(
            store.attach_workstream_agent,
            workstream_id=workstream["id"],
            agent_id=requester_node_id,
            repo=frame.repo,
            worktree_label=frame.worktree_label,
            status=frame.status,
            error=frame.error,
        )
    except WorkstreamNotFoundError:
        return AttachWorkstreamAgentAckFrame(
            type="attach_workstream_agent_ack",
            v=PROTOCOL_VERSION,
            request_id=frame.request_id,
            status="not_found",
            error=None,
        )
    except Exception as exc:  # noqa: BLE001
        return AttachWorkstreamAgentAckFrame(
            type="attach_workstream_agent_ack",
            v=PROTOCOL_VERSION,
            request_id=frame.request_id,
            status="error",
            error=str(exc),
        )
    return AttachWorkstreamAgentAckFrame(
        type="attach_workstream_agent_ack",
        v=PROTOCOL_VERSION,
        request_id=frame.request_id,
        status="attached",
        error=None,
    )


async def update_workstream(
    *,
    frame: UpdateWorkstreamFrame,
    store: Store,
) -> UpdateWorkstreamAckFrame:
    """Update a workstream's status by id or slug."""

    workstream = await asyncio.to_thread(store.get_workstream, frame.workstream)
    if workstream is None:
        return UpdateWorkstreamAckFrame(
            type="update_workstream_ack",
            v=PROTOCOL_VERSION,
            request_id=frame.request_id,
            status="not_found",
            error=None,
        )
    try:
        rowcount = await asyncio.to_thread(
            store.set_workstream_status,
            workstream_id=workstream["id"],
            status=frame.status,
        )
    except ValueError:
        return UpdateWorkstreamAckFrame(
            type="update_workstream_ack",
            v=PROTOCOL_VERSION,
            request_id=frame.request_id,
            status="invalid_status",
            error=None,
        )
    except Exception as exc:  # noqa: BLE001
        return UpdateWorkstreamAckFrame(
            type="update_workstream_ack",
            v=PROTOCOL_VERSION,
            request_id=frame.request_id,
            status="error",
            error=str(exc),
        )
    if not rowcount:
        return UpdateWorkstreamAckFrame(
            type="update_workstream_ack",
            v=PROTOCOL_VERSION,
            request_id=frame.request_id,
            status="not_found",
            error=None,
        )
    return UpdateWorkstreamAckFrame(
        type="update_workstream_ack",
        v=PROTOCOL_VERSION,
        request_id=frame.request_id,
        status="updated",
        error=None,
    )
