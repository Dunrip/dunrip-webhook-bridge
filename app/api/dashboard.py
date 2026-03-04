"""Dashboard webUI router — serves the admin SPA at GET /."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.api._dashboard_html import DASHBOARD_HTML

router = APIRouter(tags=["dashboard"])


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard() -> HTMLResponse:
    """Serve the admin dashboard SPA."""
    return HTMLResponse(content=DASHBOARD_HTML)
