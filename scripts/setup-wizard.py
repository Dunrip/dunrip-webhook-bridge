#!/usr/bin/env python3
"""Interactive setup wizard for generating/updating .env."""

from __future__ import annotations

import secrets
from pathlib import Path

ENV_PATH = Path('.env')
EXAMPLE_PATH = Path('.env.example')

REQUIRED_FIELDS = [
    ("TELEGRAM_BOT_TOKEN", "Telegram bot token (from @BotFather)", False),
    ("TELEGRAM_CHAT_ID", "Telegram chat ID (target user/group/channel)", False),
    ("GITHUB_WEBHOOK_SECRET", "GitHub webhook secret", True),
    ("GENERIC_WEBHOOK_TOKEN", "Generic webhook token", True),
    ("ADMIN_API_KEY", "Admin API key", True),
]


def parse_env(content: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        values[key.strip()] = value.strip()
    return values


def upsert_env_text(original: str, updates: dict[str, str]) -> str:
    lines = original.splitlines()
    seen: set[str] = set()
    out_lines: list[str] = []

    for line in lines:
        if not line.strip() or line.lstrip().startswith('#') or '=' not in line:
            out_lines.append(line)
            continue

        key, _value = line.split('=', 1)
        key = key.strip()
        if key in updates:
            out_lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out_lines.append(line)

    if out_lines and out_lines[-1].strip():
        out_lines.append('')

    for key, value in updates.items():
        if key not in seen:
            out_lines.append(f"{key}={value}")

    return '\n'.join(out_lines).rstrip() + '\n'


def generate_secret() -> str:
    return secrets.token_urlsafe(32)


def prompt_value(key: str, label: str, existing: str, can_generate: bool) -> str:
    default_note = f" [current: {existing}]" if existing else ''
    while True:
        answer = input(f"{label}{default_note}: ").strip()

        if answer:
            return answer

        if existing:
            return existing

        if can_generate:
            generated = generate_secret()
            print(f"  ↳ generated secure {key}")
            return generated

        print(f"  {key} is required and cannot be empty.")


def main() -> int:
    source_text = ''
    if ENV_PATH.exists():
        source_text = ENV_PATH.read_text(encoding='utf-8')
    elif EXAMPLE_PATH.exists():
        source_text = EXAMPLE_PATH.read_text(encoding='utf-8')

    existing = parse_env(source_text)
    updates: dict[str, str] = {}

    print('Webhook Bridge Setup Wizard')
    print('Press Enter to keep current values or auto-generate secrets where allowed.\n')

    for key, label, can_generate in REQUIRED_FIELDS:
        updates[key] = prompt_value(key, label, existing.get(key, ''), can_generate)

    merged = upsert_env_text(source_text, updates)
    ENV_PATH.write_text(merged, encoding='utf-8')

    print('\n✅ .env updated successfully.')
    print('\nGitHub webhook settings:')
    print('  URL: https://<your-domain>/webhook/github')
    print('  Content type: application/json')
    print(f"  Secret: {updates['GITHUB_WEBHOOK_SECRET']}")
    print('  Events: Pushes, Pull requests, Issues, Releases, Workflow runs')
    print('\nNext steps: make up && make smoke')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
