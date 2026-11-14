"""FastAPI application factory. Vercel loads `app` via the root app.py entrypoint."""

import os
import platform
from pathlib import Path

from fastapi import FastAPI

from reloop import __version__
from reloop.config import get_settings
from reloop.models.categories import LANES
from reloop.routes import pages
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
    )
    app.include_router(pages.router)

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
