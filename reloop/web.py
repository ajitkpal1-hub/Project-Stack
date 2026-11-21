"""FastAPI application factory. Vercel loads `app` via the root app.py entrypoint."""

import os
import platform
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.exceptions import HTTPException

from reloop import __version__
from reloop.config import get_settings
from reloop.models.categories import LANES
from reloop.models.dashboards import FLAG_REASON_LABELS
from reloop.routes import account, assistant, centres, dashboards, donations, internal, pages, scan, talk, voice
from reloop.routes.deps import LoginRequired, login_url, viewer
from reloop.security import SessionMiddleware, csrf_field, take_flash
from reloop.services.usage import AREAS
from reloop.templating import templates

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DIR = PROJECT_ROOT / "public"


def create_app() -> FastAPI:
    app = FastAPI(title="RELOOP AI", version=__version__, docs_url=None, redoc_url=None)

    templates.env.globals.update(
        primary_nav=pages.PRIMARY_NAV,
        pages_by_slug=pages.PAGES_BY_SLUG,
        app_version=__version__,
        lane_stencils={lane.category.value: lane.stencil for lane in LANES},
        csrf_field=csrf_field,
        current_viewer=viewer,
        take_flash=take_flash,
        flag_reason_labels=FLAG_REASON_LABELS,
        area_choices=AREAS,
    )
    app.add_middleware(SessionMiddleware)
    app.include_router(account.router)
    app.include_router(donations.router)
    app.include_router(centres.router)
    app.include_router(dashboards.router)
    app.include_router(pages.router)
    app.include_router(scan.router)
    app.include_router(assistant.router)
    app.include_router(voice.router)
    app.include_router(talk.router)
    app.include_router(internal.router)

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, exc: LoginRequired) -> RedirectResponse:
        return RedirectResponse(login_url(exc.next_path), status_code=303)

    @app.exception_handler(Exception)
    async def _server_error(request: Request, exc: Exception) -> HTMLResponse:
        import logging

        logging.getLogger("reloop.web").exception("unhandled error on %s", request.url.path)
        return templates.TemplateResponse(request, "error.html", {"active": "", "code": 500,
                                          "message": "Something went wrong on our side. Please try again in a minute."},
                                          status_code=500)

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException) -> HTMLResponse:
        messages = {403: "Your form expired. Please go back, refresh the page and try again.",
                    404: "We couldn't find that page.", 405: "That page can't be opened this way."}
        message = messages.get(exc.status_code, "Something went wrong. Please try again.")
        return templates.TemplateResponse(request, "error.html", {"active": "", "code": exc.status_code, "message": message},
                                          status_code=exc.status_code)

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
            "llm": settings.llm_diagnostics(),
        }

    # On Vercel, public/ is served by the CDN at the site root and must not be
    # mounted here. Locally we mount each public/ subfolder at the same path.
    if not os.environ.get("VERCEL"):
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles

        for sub in sorted(p for p in PUBLIC_DIR.iterdir() if p.is_dir()):
            app.mount(f"/{sub.name}", StaticFiles(directory=sub), name=f"public-{sub.name}")

        @app.get("/favicon.svg", include_in_schema=False)
        def favicon() -> FileResponse:
            return FileResponse(PUBLIC_DIR / "favicon.svg", media_type="image/svg+xml")

    return app


app = create_app()
