import logging
import re

from telegram import Bot
from telegram.constants import ParseMode

from config import settings

logger = logging.getLogger(__name__)

bot = Bot(token=settings.telegram_bot_token)


def escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!\\])", r"\\\1", text)


def md_link(text: str, url: str) -> str:
    return f"[{escape_md(text)}]({escape_md(url)})"


async def send_message(text: str) -> None:
    """Send a MarkdownV2 message to the configured chat."""
    try:
        await bot.send_message(
            chat_id=settings.telegram_chat_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    except Exception:
        logger.exception("Failed to send Telegram message")
        raise


def format_push_event(payload: dict) -> str:
    repo = escape_md(payload.get("repository", {}).get("full_name", "unknown"))
    pusher = escape_md(payload.get("pusher", {}).get("name", "unknown"))
    ref = escape_md(payload.get("ref", "").removeprefix("refs/heads/"))
    commits = payload.get("commits", [])
    compare_url = payload.get("compare", "")

    lines = [f"*Push* to `{repo}` by *{pusher}*", f"Branch: `{ref}`"]

    for c in commits[:5]:
        sha = escape_md(c["id"][:7])
        msg = escape_md(c["message"].split("\n", 1)[0])
        lines.append(f"  `{sha}` {msg}")

    if len(commits) > 5:
        lines.append(escape_md(f"  ...and {len(commits) - 5} more"))

    if compare_url:
        lines.append(md_link("View diff", compare_url))

    return "\n".join(lines)


def format_pr_event(payload: dict) -> str:
    action = escape_md(payload.get("action", "unknown"))
    pr = payload.get("pull_request", {})
    title = escape_md(pr.get("title", ""))
    number = pr.get("number", 0)
    user = escape_md(pr.get("user", {}).get("login", "unknown"))
    repo = escape_md(payload.get("repository", {}).get("full_name", "unknown"))
    url = pr.get("html_url", "")

    lines = [
        f"*Pull Request* {action} in `{repo}`",
        f"\\#{escape_md(str(number))}: *{title}* by *{user}*",
    ]
    if url:
        lines.append(md_link("View PR", url))

    return "\n".join(lines)


def format_issue_event(payload: dict) -> str:
    action = escape_md(payload.get("action", "unknown"))
    issue = payload.get("issue", {})
    title = escape_md(issue.get("title", ""))
    number = issue.get("number", 0)
    user = escape_md(issue.get("user", {}).get("login", "unknown"))
    repo = escape_md(payload.get("repository", {}).get("full_name", "unknown"))
    url = issue.get("html_url", "")

    lines = [
        f"*Issue* {action} in `{repo}`",
        f"\\#{escape_md(str(number))}: *{title}* by *{user}*",
    ]
    if url:
        lines.append(md_link("View issue", url))

    return "\n".join(lines)


def format_generic(title: str, body: str, url: str | None = None) -> str:
    lines = [f"*{escape_md(title)}*", escape_md(body)]
    if url:
        lines.append(md_link("Open", url))
    return "\n".join(lines)
