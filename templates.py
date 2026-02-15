import logging
import os
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, TemplateNotFound

from config import settings

logger = logging.getLogger(__name__)

# Default templates directory (built-in)
_DEFAULT_TEMPLATE_DIR = Path(__file__).parent / "templates" / "default"

# Custom template directory from env var
_CUSTOM_TEMPLATE_DIR = os.environ.get("TEMPLATE_DIR", "")


def _create_environment() -> Environment | None:
    """Create Jinja2 environment with template directories."""
    search_paths: list[str] = []

    if _CUSTOM_TEMPLATE_DIR and Path(_CUSTOM_TEMPLATE_DIR).is_dir():
        search_paths.append(_CUSTOM_TEMPLATE_DIR)

    if _DEFAULT_TEMPLATE_DIR.is_dir():
        search_paths.append(str(_DEFAULT_TEMPLATE_DIR))

    if not search_paths:
        return None

    return Environment(
        loader=FileSystemLoader(search_paths),
        autoescape=False,
        keep_trailing_newline=False,
    )


_env = _create_environment()


def render_template(event_type: str, context: dict[str, Any]) -> str | None:
    """Render a Jinja2 template for the given event type.

    Returns the rendered string, or None if no template is found
    (caller should fall back to the built-in formatter).
    """
    if _env is None:
        return None

    template_name = f"{event_type}.j2"
    try:
        template = _env.get_template(template_name)
        return template.render(**context)
    except TemplateNotFound:
        return None
    except Exception:
        logger.exception("Failed to render template %s", template_name)
        return None


def reload_templates() -> None:
    """Reload the template environment (useful after config change)."""
    global _env
    _env = _create_environment()
