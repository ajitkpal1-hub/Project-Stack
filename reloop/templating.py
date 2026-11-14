"""Shared Jinja2 environment.

Interface text is wrapped in _() so Hindi and Marathi translations can be added
later with gettext/Babel without touching templates. For now translations are
the identity function (English).
"""

from pathlib import Path

from fastapi.templating import Jinja2Templates

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

templates = Jinja2Templates(directory=TEMPLATE_DIR)
templates.env.add_extension("jinja2.ext.i18n")
templates.env.install_null_translations(newstyle=True)  # type: ignore[attr-defined]
