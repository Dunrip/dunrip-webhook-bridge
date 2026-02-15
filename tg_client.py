import asyncio
import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import NetworkError, RetryAfter, TimedOut

from config import settings

logger = logging.getLogger(__name__)

bot = Bot(token=settings.telegram_bot_token)


class TelegramSendError(RuntimeError):
    """Raised when message delivery to Telegram fails after retries."""


def escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!\\])", r"\\\1", text)


def md_link(text: str, url: str) -> str:
    return f"[{escape_md(text)}]({escape_md(url)})"


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


async def send_message(
    text: str,
    *,
    retries: int = 2,
    sleep_func: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Send a MarkdownV2 message to the configured chat with bounded retries."""
    for attempt in range(retries + 1):
        try:
            await bot.send_message(
                chat_id=settings.telegram_chat_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return
        except RetryAfter as exc:
            wait_seconds = float(exc.retry_after)
            if attempt == retries:
                logger.exception("Telegram rate limited after retries")
                raise TelegramSendError("Rate limited by Telegram") from exc
            logger.warning("Telegram rate limited; retrying in %.2fs", wait_seconds)
            await sleep_func(wait_seconds)
        except (TimedOut, NetworkError) as exc:
            if attempt == retries:
                logger.exception("Telegram transient error after retries")
                raise TelegramSendError("Telegram network error") from exc
            backoff = float(attempt + 1)
            logger.warning("Telegram transient error; retrying in %.2fs", backoff)
            await sleep_func(backoff)
        except Exception as exc:
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


def format_generic(title: str, body: str, url: str | None = None) -> str:
    lines = [f"*{escape_md(title)}*", escape_md(body)]
    if url:
        lines.append(md_link("Open", url))
    return "\n".join(lines)
