from __future__ import annotations

from pathlib import Path


def test_makefile_has_first_run_and_ops_targets() -> None:
    makefile = Path(__file__).resolve().parents[1] / "Makefile"
    text = makefile.read_text(encoding="utf-8")

    assert "first-run: wizard up smoke" in text
    assert "test-github:" in text
    assert "\n\t./scripts/test-github.sh\n" in text
    assert "post-release-verify:" in text
    assert "\n\t./scripts/post-release-verify.sh\n" in text


def test_setup_wizard_prints_copy_paste_github_values() -> None:
    wizard_script = Path(__file__).resolve().parents[1] / "scripts" / "setup-wizard.py"
    text = wizard_script.read_text(encoding="utf-8")

    assert "Payload URL template" in text
    assert "Content type: application/json" in text
    assert "Secret source: value of GITHUB_WEBHOOK_SECRET in your .env file" in text
    assert "Recommended events" in text


def test_readme_links_operator_troubleshooting_and_kpi_scorecard() -> None:
    readme = Path(__file__).resolve().parents[1] / "README.md"
    text = readme.read_text(encoding="utf-8")

    assert "docs/ops/troubleshooting-decision-tree.md" in text
    assert "docs/ops/kpi-scorecard-template.md" in text
