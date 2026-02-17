import asyncio
import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import NetworkError, RetryAfter, TimedOut

from circuit_breaker import telegram_circuit
from config import settings
from observability import get_request_id

logger = logging.getLogger(__name__)

bot = Bot(token=settings.telegram_bot_token)


class TelegramSendError(RuntimeError):
    """Raised when message delivery to Telegram fails after retries."""


def escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    return re.sub(r"([_\*\[\]()~`>#+\-=|{}.!\\])", r"\\\1", text)


def md_link(text: str, url: str) -> str:
    return f"[{escape_md(text)}]({escape_md(url)})"


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


async def send_message(
    text: str,
    *,
    retries: int | None = None,
    sleep_func: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Send a MarkdownV2 message to the configured chat with bounded retries."""
    if retries is None:
        retries = settings.telegram_retries

    request_id = get_request_id()
    if request_id != "-" and "request_id:" not in text:
        text = f"{text}\n\n`request_id: {request_id}`"

    # Check circuit breaker first
    if not telegram_circuit.can_execute():
        raise TelegramSendError(
            f"Circuit breaker is OPEN - Telegram service appears down "
            f"(will retry in {telegram_circuit.timeout}s)"
        )

    for attempt in range(retries + 1):
        try:
            await bot.send_message(
                chat_id=settings.telegram_chat_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            telegram_circuit.record_success()
            return
        except RetryAfter as exc:
            wait_seconds = float(exc.retry_after)
            if attempt == retries:
                telegram_circuit.record_failure()
                logger.exception("Telegram rate limited after retries")
                raise TelegramSendError("Rate limited by Telegram") from exc
            logger.warning("Telegram rate limited; retrying in %.2fs", wait_seconds)
            await sleep_func(wait_seconds)
        except (TimedOut, NetworkError) as exc:
            if attempt == retries:
                telegram_circuit.record_failure()
                logger.exception("Telegram transient error after retries")
                raise TelegramSendError("Telegram network error") from exc
            backoff = float(attempt + 1)
            logger.warning("Telegram transient error; retrying in %.2fs", backoff)
            await sleep_func(backoff)
        except Exception as exc:
            telegram_circuit.record_failure()
            logger.exception("Failed to send Telegram message")
            raise TelegramSendError("Telegram delivery failed") from exc


def format_push_event(payload: Mapping[str, Any]) -> str:
    repository = _as_dict(payload.get("repository"))
    pusher_info = _as_dict(payload.get("pusher"))
    repo = escape_md(str(repository.get("full_name", "unknown")))
    pusher = escape_md(str(pusher_info.get("name", "unknown")))
    ref = str(payload.get("ref", "")).removeprefix("refs/heads/")
    ref_display = escape_md(ref or "unknown")
    commits_raw = payload.get("commits")
    commits = commits_raw if isinstance(commits_raw, list) else []
    compare_url = payload.get("compare", "")

    lines = [f"*Push* to `{repo}` by *{pusher}*", f"Branch: `{ref_display}`"]

    for c in commits[:5]:
        commit = _as_dict(c)
        sha = escape_md(str(commit.get("id", "unknown"))[:7] or "unknown")
        raw_msg = str(commit.get("message", "(no message)"))
        msg = escape_md(raw_msg.split("\n", 1)[0] or "(no message)")
        lines.append(f"  `{sha}` {msg}")

    if len(commits) > 5:
        lines.append(escape_md(f"  ...and {len(commits) - 5} more"))

    if isinstance(compare_url, str) and compare_url:
        lines.append(md_link("View diff", compare_url))

    return "\n".join(lines)


def format_pr_event(payload: Mapping[str, Any]) -> str:
    action = escape_md(str(payload.get("action", "unknown")))
    pr = _as_dict(payload.get("pull_request"))
    pr_user = _as_dict(pr.get("user"))
    repository = _as_dict(payload.get("repository"))
    title = escape_md(str(pr.get("title", "")))
    number = pr.get("number", 0)
    user = escape_md(str(pr_user.get("login", "unknown")))
    repo = escape_md(str(repository.get("full_name", "unknown")))
    url = pr.get("html_url", "")

    lines = [
        f"*Pull Request* {action} in `{repo}`",
        f"\\#{escape_md(str(number))}: *{title}* by *{user}*",
    ]
    if isinstance(url, str) and url:
        lines.append(md_link("View PR", url))

    return "\n".join(lines)


def format_issue_event(payload: Mapping[str, Any]) -> str:
    action = escape_md(str(payload.get("action", "unknown")))
    issue = _as_dict(payload.get("issue"))
    issue_user = _as_dict(issue.get("user"))
    repository = _as_dict(payload.get("repository"))
    title = escape_md(str(issue.get("title", "")))
    number = issue.get("number", 0)
    user = escape_md(str(issue_user.get("login", "unknown")))
    repo = escape_md(str(repository.get("full_name", "unknown")))
    url = issue.get("html_url", "")

    lines = [
        f"*Issue* {action} in `{repo}`",
        f"\\#{escape_md(str(number))}: *{title}* by *{user}*",
    ]
    if isinstance(url, str) and url:
        lines.append(md_link("View issue", url))

    return "\n".join(lines)


def format_release_event(payload: Mapping[str, Any]) -> str:
    """Format a GitHub release event."""
    action = escape_md(str(payload.get("action", "published")))
    release = _as_dict(payload.get("release"))
    repository = _as_dict(payload.get("repository"))

    tag = escape_md(str(release.get("tag_name", "unknown")))
    name = escape_md(str(release.get("name", tag)))
    repo = escape_md(str(repository.get("full_name", "unknown")))
    url = release.get("html_url", "")
    prerelease = release.get("prerelease", False)
    draft = release.get("draft", False)

    badge = ""
    if draft:
        badge = " ~*DRAFT*~"
    elif prerelease:
        badge = " ~*PRE*~"

    lines = [
        f"*Release* {action}{badge} in `{repo}`",
        f"*{name}* (`{tag}`)",
    ]

    if isinstance(url, str) and url:
        lines.append(md_link("View release", url))

    return "\n".join(lines)


def format_workflow_run_event(payload: Mapping[str, Any]) -> str:
    """Format a GitHub workflow run event."""
    action = escape_md(str(payload.get("action", "completed")))
    wf_run = _as_dict(payload.get("workflow_run"))
    workflow = _as_dict(payload.get("workflow"))
    repository = _as_dict(payload.get("repository"))

    repo = escape_md(str(repository.get("full_name", "unknown")))
    wf_name = escape_md(str(workflow.get("name", "Workflow")))
    conclusion = str(wf_run.get("conclusion", "unknown")).lower()
    status = str(wf_run.get("status", "unknown"))
    branch = escape_md(str(wf_run.get("head_branch", "unknown")))
    url = wf_run.get("html_url", "")

    # Status emoji mapping
    emoji_map = {
        "success": "✅",
        "failure": "❌",
        "cancelled": "🚫",
        "skipped": "⏭️",
    }
    emoji = emoji_map.get(conclusion, "⚠️")

    lines = [
        f"{emoji} *Workflow* {action} in `{repo}`",
        f"*{wf_name}* on `{branch}`",
    ]

    if conclusion != "unknown":
        lines.append(f"Result: *{escape_md(conclusion)}*")
    elif status != "unknown":
        lines.append(f"Status: {escape_md(status)}")

    if isinstance(url, str) and url:
        lines.append(md_link("View run", url))

    return "\n".join(lines)


def format_generic(title: str, body: str, url: str | None = None) -> str:
    lines = [f"*{escape_md(title)}*", escape_md(body)]
    if url:
        lines.append(md_link("Open", url))
    return "\n".join(lines)
