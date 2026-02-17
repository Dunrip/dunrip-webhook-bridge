import asyncio
import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import NetworkError, RetryAfter, TimedOut

from app.infra.circuit_breaker import telegram_circuit
from app.core.config import settings
from app.observability.observability import get_request_id

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


def _verbosity() -> str:
    value = str(getattr(settings, "message_verbosity", "compact") or "compact").strip().lower()
    return value if value in {"compact", "detailed"} else "compact"


def _clean_text(value: Any, *, fallback: str = "unknown", max_len: int = 80) -> str:
    text = str(value or "").replace("\n", " ").replace("\r", " ")
    text = " ".join(text.split()).strip()
    if not text:
        text = fallback
    if len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text


def _safe_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    url = value.strip()
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return None
    return url


def _build_message(
    *,
    header_emoji: str,
    event_label: str,
    repo: str,
    facts: list[str],
    action_label: str,
    action_url: str | None,
    extra_facts: list[str] | None = None,
) -> str:
    mode = _verbosity()
    fact_cap = 4 if mode == "compact" else 5

    lines = [f"{header_emoji} *{escape_md(event_label)}* • `{escape_md(repo)}`"]

    combined = facts[:]
    if mode == "detailed" and extra_facts:
        combined.extend(extra_facts)

    for fact in combined[:fact_cap]:
        lines.append(escape_md(fact))

    if action_url:
        lines.append(f"🔗 {md_link(action_label, action_url)}")

    return "\n".join(lines)


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
    repo = _clean_text(repository.get("full_name"))
    pusher = _clean_text(pusher_info.get("name"))
    ref = str(payload.get("ref", "")).removeprefix("refs/heads/")
    branch = _clean_text(ref)
    commits_raw = payload.get("commits")
    commits = commits_raw if isinstance(commits_raw, list) else []
    compare_url = _safe_url(payload.get("compare"))

    facts = [
        f"By: @{pusher}",
        f"Branch: {branch}",
        f"Commits: {len(commits)}",
    ]

    extra_facts: list[str] = []
    for c in commits[:2]:
        commit = _as_dict(c)
        sha = _clean_text(str(commit.get("id", "unknown"))[:7], max_len=7)
        title = _clean_text(str(commit.get("message", "(no message)")).split("\n", 1)[0], max_len=64)
        extra_facts.append(f"• {sha} {title}")

    return _build_message(
        header_emoji="🚀",
        event_label="Push",
        repo=repo,
        facts=facts,
        extra_facts=extra_facts,
        action_label="View diff",
        action_url=compare_url,
    )


def format_pr_event(payload: Mapping[str, Any]) -> str:
    action = _clean_text(payload.get("action"), max_len=24)
    pr = _as_dict(payload.get("pull_request"))
    pr_user = _as_dict(pr.get("user"))
    repository = _as_dict(payload.get("repository"))
    title = _clean_text(pr.get("title"), fallback="(no title)", max_len=72)
    number = _clean_text(pr.get("number"), fallback="0", max_len=12)
    user = _clean_text(pr_user.get("login"), max_len=32)
    repo = _clean_text(repository.get("full_name"))
    url = _safe_url(pr.get("html_url"))

    facts = [
        f"Action: {action}",
        f"PR #{number} by @{user}",
        f"Title: {title}",
    ]

    return _build_message(
        header_emoji="🔀",
        event_label="Pull Request",
        repo=repo,
        facts=facts,
        action_label="View PR",
        action_url=url,
    )


def format_issue_event(payload: Mapping[str, Any]) -> str:
    action = _clean_text(payload.get("action"), max_len=24)
    issue = _as_dict(payload.get("issue"))
    issue_user = _as_dict(issue.get("user"))
    repository = _as_dict(payload.get("repository"))
    title = _clean_text(issue.get("title"), fallback="(no title)", max_len=72)
    number = _clean_text(issue.get("number"), fallback="0", max_len=12)
    user = _clean_text(issue_user.get("login"), max_len=32)
    repo = _clean_text(repository.get("full_name"))
    url = _safe_url(issue.get("html_url"))

    emoji = "✅" if action == "closed" else "🐞"
    facts = [
        f"Action: {action}",
        f"Issue #{number} by @{user}",
        f"Title: {title}",
    ]

    return _build_message(
        header_emoji=emoji,
        event_label="Issue",
        repo=repo,
        facts=facts,
        action_label="View issue",
        action_url=url,
    )


def format_release_event(payload: Mapping[str, Any]) -> str:
    """Format a GitHub release event."""
    action = _clean_text(payload.get("action", "published"), max_len=24)
    release = _as_dict(payload.get("release"))
    repository = _as_dict(payload.get("repository"))

    tag = _clean_text(release.get("tag_name"), max_len=40)
    name = _clean_text(release.get("name") or tag, max_len=72)
    repo = _clean_text(repository.get("full_name"))
    url = _safe_url(release.get("html_url"))
    prerelease = bool(release.get("prerelease", False))
    draft = bool(release.get("draft", False))

    status = "draft" if draft else "prerelease" if prerelease else "stable"
    emoji = "⚠️" if draft or prerelease else "✅"
    facts = [
        f"Action: {action}",
        f"Name: {name}",
        f"Tag: {tag}",
        f"Status: {status}",
    ]

    return _build_message(
        header_emoji=emoji,
        event_label="Release",
        repo=repo,
        facts=facts,
        action_label="View release",
        action_url=url,
    )


def format_workflow_run_event(payload: Mapping[str, Any]) -> str:
    """Format a GitHub workflow run event."""
    action = _clean_text(payload.get("action", "completed"), max_len=24)
    wf_run = _as_dict(payload.get("workflow_run"))
    workflow = _as_dict(payload.get("workflow"))
    repository = _as_dict(payload.get("repository"))

    repo = _clean_text(repository.get("full_name"))
    wf_name = _clean_text(workflow.get("name", "Workflow"), max_len=72)
    conclusion = _clean_text(str(wf_run.get("conclusion", "unknown")).lower(), max_len=24)
    status = _clean_text(wf_run.get("status", "unknown"), max_len=24)
    branch = _clean_text(wf_run.get("head_branch"), max_len=40)
    url = _safe_url(wf_run.get("html_url"))

    emoji_map = {
        "success": "✅",
        "neutral": "✅",
        "failure": "❌",
        "cancelled": "⚠️",
        "skipped": "⚠️",
        "timed_out": "🔥",
        "action_required": "🔥",
    }
    emoji = emoji_map.get(conclusion, "⚠️")

    facts = [
        f"Action: {action}",
        f"Workflow: {wf_name}",
        f"Branch: {branch}",
        f"Result: {conclusion if conclusion != 'unknown' else status}",
    ]

    return _build_message(
        header_emoji=emoji,
        event_label="Workflow",
        repo=repo,
        facts=facts,
        action_label="View run",
        action_url=url,
    )


def format_generic(title: str, body: str, url: str | None = None) -> str:
    title_clean = _clean_text(title, fallback="Notification", max_len=72)
    body_clean = _clean_text(body, fallback="(no details)", max_len=160)
    lines = [f"*{escape_md(title_clean)}*", escape_md(body_clean)]
    safe_url = _safe_url(url)
    if safe_url:
        lines.append(f"🔗 {md_link('Open', safe_url)}")
    return "\n".join(lines)
