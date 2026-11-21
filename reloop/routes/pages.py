"""Page routes. Pages not yet built show an honest "coming in Phase N" shell."""

from dataclasses import dataclass, field

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from reloop.models.categories import LANES
from reloop.models.demo import DEMO_LISTINGS
from reloop.templating import templates

router = APIRouter()


@dataclass(frozen=True)
class Page:
    slug: str
    path: str
    nav_label: str
    title: str
    purpose: str
    phase: int
    lane: str  # which lane colour the page header uses
    will_do: list[str] = field(default_factory=list)


PAGES: list[Page] = [
    Page(
        "scan", "/scan", "Scan", "AI waste scanner",
        "Show us a photo of an item and we'll tell you which lane it belongs in, and how to handle it safely.",
        3, "dry",
        [
            "Accept JPG, PNG or WEBP photos and check their size and type",
            "Name the item and suggest a waste lane, marked Clear, Likely or Unsure (never a made-up percentage)",
            "Ask about the item's condition instead of guessing from the photo",
            "Flag anything that might be hazardous before giving any advice",
        ],
    ),
    Page(
        "assistant", "/assistant", "Ask", "Smart disposal assistant",
        "Ask how to dispose of something. Answers come only from documents we've actually loaded, with the source named.",
        4, "wet",
        [
            "Search a knowledge base of Indian and local waste guidance",
            "Show the document each answer came from",
            "Say plainly when no reliable source is loaded",
        ],
    ),
    Page(
        "donate", "/donate", "Donate", "Donate an item",
        "List something usable so a neighbour or NGO can give it a second life.",
        6, "reuse",
        [
            "Create a listing with photos, condition, locality and PIN code",
            "Get an AI category suggestion that you confirm",
            "Keep your phone, email and address private",
            "Block hazardous or medical items from being listed",
        ],
    ),
    Page(
        "donations", "/donations", "Explore", "Explore donations",
        "Browse items neighbours are giving away and request the ones you need.",
        6, "textile",
        [
            "Browse approved listings by category and locality",
            "Request an item. The donor approves or declines.",
            "See each listing's status: Available, Reserved, Completed",
        ],
    ),
    Page(
        "centres", "/centres", "Recycling", "Find recycling centres",
        "Find collection points, recyclers and NGOs near you by locality, PIN code or material.",
        7, "e-waste",
        [
            "Search by city, locality, PIN code and material",
            "Mark admin-verified organisations clearly. Map results stay unverified.",
            "Fall back to the local directory if the maps service is down",
        ],
    ),
    Page(
        "talk", "/talk", "Talk", "Talk to our voice helper",
        "Ask out loud which bin something goes in, whether it can be donated, and where to drop it.",
        10, "reuse",
        [],
    ),
    Page(
        "dashboard", "/dashboard", "My dashboard", "My dashboard",
        "Your listings, requests, scans and saved guidance in one place.",
        8, "unsure",
        [
            "Track your listings and the requests on them",
            "Revisit past scans and saved guidance",
            "Count what you've donated, with no made-up carbon figures",
        ],
    ),
    Page(
        "admin", "/admin", "Admin", "Admin dashboard",
        "Moderation and verification for the RELOOP AI team.",
        8, "hazardous",
        [
            "Approve or reject donation listings",
            "Verify NGO and recycling partners",
            "Manage knowledge documents and review flagged AI answers",
        ],
    ),
]

PAGES_BY_SLUG = {p.slug: p for p in PAGES}
PRIMARY_NAV = [p for p in PAGES if p.slug not in {"dashboard", "admin"}]


@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "home.html", {"lanes": LANES, "listings": DEMO_LISTINGS, "active": "home"}
    )


def _feature(request: Request, page: Page, **extra) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "feature.html", {"page": page, "active": page.slug, "lanes": LANES, **extra}
    )


SELF_RENDERED = {"scan", "assistant", "donate", "donations", "centres", "talk", "dashboard", "admin"}  # pages with their own route module


def _register(page: Page) -> None:
    def view(request: Request) -> HTMLResponse:
        return _feature(request, page)

    router.add_api_route(page.path, view, methods=["GET"], response_class=HTMLResponse, name=page.slug)


for _page in PAGES:
    if _page.slug not in SELF_RENDERED:
        _register(_page)
