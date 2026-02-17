import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.services.formatters import get_formatter
from app.models.models import GenericWebhookPayload
from app.services.tg_client import format_generic

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sandbox"])


def _payload_summary(payload: dict[str, Any], event_type: str) -> dict[str, Any]:
    """Extract key fields from a payload for the summary."""
    summary: dict[str, Any] = {"event_type": event_type}

    repo = payload.get("repository", {})
    if isinstance(repo, dict) and repo.get("full_name"):
        summary["repository"] = repo["full_name"]

    if event_type == "push":
        commits = payload.get("commits", [])
        summary["commit_count"] = len(commits) if isinstance(commits, list) else 0
        ref = str(payload.get("ref", ""))
        if ref.startswith("refs/heads/"):
            summary["branch"] = ref.removeprefix("refs/heads/")
    elif event_type == "pull_request":
        pr = payload.get("pull_request", {})
        if isinstance(pr, dict):
            summary["action"] = payload.get("action")
            summary["number"] = pr.get("number")
            summary["title"] = pr.get("title")
    elif event_type == "issues":
        issue = payload.get("issue", {})
        if isinstance(issue, dict):
            summary["action"] = payload.get("action")
            summary["number"] = issue.get("number")
            summary["title"] = issue.get("title")
    elif event_type == "release":
        release = payload.get("release", {})
        if isinstance(release, dict):
            summary["action"] = payload.get("action")
            summary["tag_name"] = release.get("tag_name")
            summary["name"] = release.get("name")
    elif event_type == "workflow_run":
        wf_run = payload.get("workflow_run", {})
        workflow = payload.get("workflow", {})
        if isinstance(wf_run, dict):
            summary["conclusion"] = wf_run.get("conclusion")
        if isinstance(workflow, dict):
            summary["workflow_name"] = workflow.get("name")

    return summary


@router.post("/webhook/github/sandbox")
async def github_sandbox(
    request: Request,
) -> JSONResponse:
    """Preview a GitHub webhook message without sending to Telegram."""
    x_github_event = request.headers.get("x-github-event", "ping")

    # Read raw body (no signature verification for sandbox)
    body = await request.body()
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        request_id = getattr(request.state, "request_id", "-")
        return JSONResponse(
            status_code=400,
            content={"error": "VALIDATION_ERROR", "message": "Malformed JSON payload", "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )

    if not isinstance(payload, dict):
        request_id = getattr(request.state, "request_id", "-")
        return JSONResponse(
            status_code=400,
            content={"error": "VALIDATION_ERROR", "message": "Payload must be a JSON object", "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )

    formatter = get_formatter(x_github_event)
    if not formatter:
        return JSONResponse(
            status_code=200,
            content={
                "preview": None,
                "payload_summary": {"event_type": x_github_event, "note": "unsupported event type"},
            },
        )

    message = formatter(payload)
    summary = _payload_summary(payload, x_github_event)

    return JSONResponse(
        status_code=200,
        content={"preview": message, "payload_summary": summary},
    )


@router.post("/webhook/generic/sandbox")
async def generic_sandbox(
    payload: GenericWebhookPayload,
) -> JSONResponse:
    """Preview a generic webhook message without sending to Telegram."""
    message = format_generic(payload.title, payload.body, payload.url)

    summary: dict[str, Any] = {
        "event_type": "generic",
        "title": payload.title,
        "body_length": len(payload.body),
    }
    if payload.url:
        summary["url"] = payload.url

    return JSONResponse(
        status_code=200,
        content={"preview": message, "payload_summary": summary},
    )
