"""FastAPI application factory. Vercel loads `app` via the root app.py entrypoint."""

import os
import platform
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from reloop import __version__
from reloop.config import get_settings

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

templates = Jinja2Templates(directory=BASE_DIR / "templates")


def create_app() -> FastAPI:
    app = FastAPI(title="RELOOP AI", version=__version__, docs_url=None, redoc_url=None)

    # On Vercel, files in public/ are served by the CDN. Vercel's docs say not to
    # mount public/ ourselves there, so we only mount it for local development.
    if not os.environ.get("VERCEL"):
        from fastapi.staticfiles import StaticFiles

        app.mount("/css", StaticFiles(directory=PROJECT_ROOT / "public" / "css"), name="css")

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "home.html",
            {"integrations": get_settings().integration_status()},
        )

    @app.get("/api/health")
    def health() -> dict:
        settings = get_settings()
        return {
            "status": "ok",
            "version": __version__,
            "python": platform.python_version(),
            "environment": settings.app_env,
            "on_vercel": bool(os.environ.get("VERCEL")),
            "integrations": settings.integration_status(),
        }

    return app


app = create_app()
