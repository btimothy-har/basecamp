"""Run-report authorization: telemetry and result-report handling."""

from __future__ import annotations

import asyncio
import hmac
from typing import Any

from ...frames import ResultReportFrame, TelemetryFrame
from ...registry import Registry
from ...store import Store
from .dispatch import _hash_report_token
from .waiting import notify_run_finalized


def _is_report_frame_authorized(*, frame: TelemetryFrame | ResultReportFrame, run: dict[str, Any] | None) -> bool:
    if not run:
        return False
    if frame.agent_id != run.get("agent_id"):
        return False
    report_token_hash = run.get("report_token_hash")
    if not isinstance(report_token_hash, str):
        return False
    return hmac.compare_digest(_hash_report_token(frame.report_token), report_token_hash)


async def handle_telemetry(*, frame: TelemetryFrame, store: Store) -> None:
    run = await asyncio.to_thread(store.get_run, frame.run_id)
    if not _is_report_frame_authorized(frame=frame, run=run):
        return
    await asyncio.to_thread(
        store.append_run_event,
        run_id=frame.run_id,
        kind=frame.kind,
        payload=frame.payload,
    )


async def handle_result_report(
    *,
    frame: ResultReportFrame,
    store: Store,
    registry: Registry,
) -> None:
    run = await asyncio.to_thread(store.get_run, frame.run_id)
    if not _is_report_frame_authorized(frame=frame, run=run):
        return
    run_status = "completed" if frame.status == "ok" else "failed"
    finalized = await asyncio.to_thread(
        store.set_run_result_if_unset,
        run_id=frame.run_id,
        status=run_status,
        result=frame.result,
        error=frame.error,
    )
    if finalized:
        await notify_run_finalized(frame.run_id, registry=registry, store=store)
