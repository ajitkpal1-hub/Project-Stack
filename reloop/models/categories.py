"""Waste categories ("lanes") shared by the UI and, later, the AI agents.

Guidance here is general household practice, not a citation of any rule. Verified,
source-backed guidance comes from the RAG knowledge base (Phase 4).
"""

from enum import StrEnum

from pydantic import BaseModel


class WasteCategory(StrEnum):
    WET = "wet"
    DRY = "dry"
    REUSE = "reuse"
    TEXTILE = "textile"
    E_WASTE = "e-waste"
    HAZARDOUS = "hazardous"
    MEDICAL = "medical"
    UNSURE = "unsure"


class Lane(BaseModel):
    category: WasteCategory
    stencil: str  # short uppercase label painted on the bin
    name: str  # full category name
    gist: str  # one-line description
    examples: list[str]
    where: str  # general guidance on where it goes
    hazard: bool = False


LANES: list[Lane] = [
    Lane(
        category=WasteCategory.WET,
        stencil="WET",
        name="Wet waste",
        gist="Food and garden waste",
        examples=["Vegetable and fruit peels", "Leftover food", "Tea leaves and coffee grounds", "Flowers and leaves"],
        where="Green bin or home compost. Keep plastic out of it.",
    ),
    Lane(
        category=WasteCategory.DRY,
        stencil="DRY",
        name="Dry recyclable waste",
        gist="Clean paper, plastic, metal, glass",
        examples=["Newspaper and cardboard", "Plastic bottles and containers", "Metal cans", "Glass bottles and jars"],
        where="Blue bin. Rinse and dry it first, because dirty dry waste is hard to recycle.",
    ),
    Lane(
        category=WasteCategory.REUSE,
        stencil="REUSE",
        name="Reusable and donatable items",
        gist="Still useful to someone",
        examples=["Working furniture", "Books and school supplies", "Toys in good condition", "Kitchen and household goods"],
        where="Donate, repair or pass it on. Check it works and is clean before you list it.",
    ),
    Lane(
        category=WasteCategory.TEXTILE,
        stencil="TEXTILE",
        name="Textile waste",
        gist="Clothes and fabric",
        examples=["Clothes", "Bedsheets and towels", "Curtains", "Bags and shoes"],
        where="Donate it if it's wearable and clean. Otherwise use a textile collection point.",
    ),
    Lane(
        category=WasteCategory.E_WASTE,
        stencil="E-WASTE",
        name="E-waste",
        gist="Anything with a plug or circuit",
        examples=["Old phones and chargers", "Cables and earphones", "Small appliances", "Remote controls and keyboards"],
        where="An authorised e-waste collector. Never the regular bin.",
        hazard=True,
    ),
    Lane(
        category=WasteCategory.HAZARDOUS,
        stencil="HAZARD",
        name="Household hazardous waste",
        gist="Chemicals, batteries, bulbs",
        examples=["Batteries", "Paint and thinner", "Pesticides and cleaning chemicals", "Tube lights and CFL bulbs"],
        where="Keep it sealed and separate. Hand it over at a hazardous-waste collection.",
        hazard=True,
    ),
    Lane(
        category=WasteCategory.MEDICAL,
        stencil="MEDICAL",
        name="Medical and biomedical waste",
        gist="Medicines, sharps, sanitary waste",
        examples=["Expired medicines", "Used syringes and needles", "Sanitary pads and diapers", "Used masks and bandages"],
        where="Wrap and mark it separately. Never donate it, and never put sharps in a bin bag.",
        hazard=True,
    ),
    Lane(
        category=WasteCategory.UNSURE,
        stencil="UNSURE",
        name="Other or uncertain",
        gist="Mixed or unfamiliar items",
        examples=["Items made of mixed materials", "Things you can't identify", "Broken items with batteries inside"],
        where="Scan a photo or ask the assistant. Keep it aside until you know.",
    ),
]

LANES_BY_CATEGORY: dict[WasteCategory, Lane] = {lane.category: lane for lane in LANES}
