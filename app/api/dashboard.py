"""Dashboard webUI router — serves the admin SPA at GET /."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["dashboard"])

_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "dashboard"
_templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(request: Request) -> HTMLResponse:
    """Serve the admin dashboard SPA."""
    return _templates.TemplateResponse("index.html", {"request": request})
