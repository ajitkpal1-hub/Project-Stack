"""Talk to us: the ElevenLabs voice helper on a page of its own.

The widget is third-party code, so it loads only here, with a security policy widened just
for this page (see `security_headers(voice_widget=True)`). Every other page keeps the strict
policy and has no microphone access.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from reloop.config import get_settings
from reloop.security import VOICE_WIDGET_SRC, VOICE_WIDGET_SRI, _secure, security_headers
from reloop.templating import templates

router = APIRouter()


@router.get("/talk", response_class=HTMLResponse)
def talk(request: Request) -> HTMLResponse:
    agent_id = get_settings().voice_widget_agent
    response = templates.TemplateResponse(request, "talk.html", {
        "active": "talk", "agent_id": agent_id, "widget_src": VOICE_WIDGET_SRC, "widget_sri": VOICE_WIDGET_SRI,
    })
    if agent_id:
        response.headers.update(security_headers(_secure(request), voice_widget=True))
    return response
