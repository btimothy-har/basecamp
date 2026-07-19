"""Raw session-thread ingest: persist a top-level session's thread node by node."""

from __future__ import annotations

import asyncio

from ..frames import ThreadReportFrame
from ..store import Store
from ..store.raw_pi_thread import RawPiThreadNode


async def handle_thread_report(*, frame: ThreadReportFrame, node_id: str, store: Store) -> int:
    """Persist a top-level session's raw thread; return the new head seq.

    The connection's registered ``node_id`` is authoritative; each entry's
    ``entry_json`` is stored verbatim — the daemon never parses the pi shape here.
    Only new nodes are inserted; the head records pi's session id and transcript path.
    The returned seq is the analyzer's freshness cursor (the caller wakes the scheduler).
    """

    nodes = [
        RawPiThreadNode(entry_id=node.id, parent_id=node.parent_id, entry_json=node.entry_json) for node in frame.nodes
    ]
    return await asyncio.to_thread(
        store.record_raw_pi_thread,
        owner_id=node_id,
        session_id=frame.session_id,
        session_file=frame.session_file,
        leaf_id=frame.leaf_id,
        nodes=nodes,
    )
