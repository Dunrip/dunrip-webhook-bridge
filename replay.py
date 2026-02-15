"""Admin endpoints for listing and replaying failed webhook deliveries."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from exceptions import ValidationError
from formatters import get_formatter
from security import verify_admin_api_key
from storage import Storage
from tg_client import TelegramSendError, format_generic, send_message

logger = logging.getLogger(__name__)

router = APIRouter(tags=["replay"])


def _get_storage(request: Request) -> Storage:
    """Resolve storage backend from application state."""
    return request.app.state.storage


async def _replay_delivery(record: dict[str, Any], storage: Storage) -> str:
    """Replay a single failed delivery.

    Args:
        record: Failed-delivery record from storage.
        storage: Storage backend used to update delivery status.

    Returns:
        New delivery status, either ``delivered`` or ``failed``.
    """
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
        formatter = get_formatter(event_type)
        if not formatter:
            logger.warning("No formatter registered for event type %s", event_type)
            return "failed"
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
    _auth: str = Depends(verify_admin_api_key),
    storage: Storage = Depends(_get_storage),
) -> dict[str, Any]:
    """List failed deliveries from storage.

    Args:
        source: Optional source filter (e.g., ``github`` or ``generic``).
        status: Optional status filter.
        limit: Maximum number of records to return.
        offset: Pagination offset.
        _auth: Admin auth dependency marker.
        storage: Resolved storage backend.

    Returns:
        JSON object with delivery list and total matching count.
    """
    deliveries, total = await storage.list_failed_deliveries(
        source=source, status=status, limit=limit, offset=offset,
    )
    return {"deliveries": deliveries, "total": total}


@router.post("/deliveries/{delivery_id}/replay")
async def replay_delivery(
    delivery_id: str,
    _auth: str = Depends(verify_admin_api_key),
    storage: Storage = Depends(_get_storage),
) -> dict[str, str]:
    """Replay one failed delivery by ID.

    Args:
        delivery_id: Failed-delivery identifier.
        _auth: Admin auth dependency marker.
        storage: Resolved storage backend.

    Returns:
        JSON object with updated replay status and delivery ID.

    Raises:
        ValidationError: Delivery ID is unknown.
    """
    record = await storage.get_failed_delivery(delivery_id)
    if not record:
        raise ValidationError(
            "Delivery not found",
            error_code="delivery_not_found",
            status_code=404,
        )

    new_status = await _replay_delivery(record, storage)
    return {"status": new_status, "delivery_id": delivery_id}


@router.post("/deliveries/replay-all")
async def replay_all(
    _auth: str = Depends(verify_admin_api_key),
    storage: Storage = Depends(_get_storage),
) -> dict[str, int]:
    """Replay all currently failed deliveries.

    Args:
        _auth: Admin auth dependency marker.
        storage: Resolved storage backend.

    Returns:
        Replay summary containing attempted/succeeded/failed counts.
    """
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
