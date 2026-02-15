import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from storage import Storage
from tg_client import (
    TelegramSendError,
    format_generic,
    format_issue_event,
    format_pr_event,
    format_push_event,
    format_release_event,
    format_workflow_run_event,
    send_message,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["replay"])

EVENT_FORMATTERS: dict[str, Any] = {
    "push": format_push_event,
    "pull_request": format_pr_event,
    "issues": format_issue_event,
    "release": format_release_event,
    "workflow_run": format_workflow_run_event,
}


def _get_storage(request: Request) -> Storage:
    return request.app.state.storage


async def _replay_delivery(record: dict[str, Any], storage: Storage) -> str:
    """Re-send a failed delivery to Telegram. Returns new status."""
    source = record["source"]
    event_type = record["event_type"]
    payload = record["payload"]

    if source == "generic":
        message = format_generic(
            payload.get("title", ""),
            payload.get("body", ""),
            payload.get("url"),
        )
    else:
        formatter = EVENT_FORMATTERS.get(event_type)
        if not formatter:
            raise HTTPException(
                status_code=400,
                detail=f"No formatter for event type: {event_type}",
            )
        message = formatter(payload)

    try:
        await send_message(message)
        await storage.update_failed_delivery_status(record["id"], "delivered")
        return "delivered"
    except TelegramSendError:
        logger.warning("Replay failed for delivery %s", record["id"])
        return "failed"


@router.get("/deliveries")
async def list_deliveries(
    source: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    storage: Storage = Depends(_get_storage),
) -> dict[str, Any]:
    """List failed deliveries from storage."""
    deliveries, total = await storage.list_failed_deliveries(
        source=source, status=status, limit=limit, offset=offset,
    )
    return {"deliveries": deliveries, "total": total}


@router.post("/deliveries/{delivery_id}/replay")
async def replay_delivery(
    delivery_id: str,
    storage: Storage = Depends(_get_storage),
) -> dict[str, str]:
    """Retry a specific failed delivery."""
    record = await storage.get_failed_delivery(delivery_id)
    if not record:
        raise HTTPException(status_code=404, detail="Delivery not found")

    new_status = await _replay_delivery(record, storage)
    return {"status": new_status, "delivery_id": delivery_id}


@router.post("/deliveries/replay-all")
async def replay_all(
    storage: Storage = Depends(_get_storage),
) -> dict[str, int]:
    """Retry all failed deliveries."""
    failed, _ = await storage.list_failed_deliveries(status="failed", limit=1000, offset=0)

    attempted = 0
    succeeded = 0
    failed_count = 0

    for record in failed:
        attempted += 1
        new_status = await _replay_delivery(record, storage)
        if new_status == "delivered":
            succeeded += 1
        else:
            failed_count += 1

    return {"attempted": attempted, "succeeded": succeeded, "failed": failed_count}
