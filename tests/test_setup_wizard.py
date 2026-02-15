from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_wizard_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "setup-wizard.py"
    spec = importlib.util.spec_from_file_location("setup_wizard", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upsert_env_text_updates_and_appends() -> None:
    wizard = _load_wizard_module()

    original = "# comment\nTELEGRAM_BOT_TOKEN=old\nLOG_LEVEL=INFO\n"
    updates = {
        "TELEGRAM_BOT_TOKEN": "new-token",
        "ADMIN_API_KEY": "new-admin",
    }

    merged = wizard.upsert_env_text(original, updates)

    assert "TELEGRAM_BOT_TOKEN=new-token" in merged
    assert "LOG_LEVEL=INFO" in merged
    assert "ADMIN_API_KEY=new-admin" in merged


def test_generate_secret_not_empty() -> None:
    wizard = _load_wizard_module()
    secret = wizard.generate_secret()

    assert isinstance(secret, str)
    assert len(secret) >= 32
