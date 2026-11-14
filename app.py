"""Vercel entrypoint. Vercel detects a FastAPI instance named `app` in app.py."""

from reloop.web import app

__all__ = ["app"]
