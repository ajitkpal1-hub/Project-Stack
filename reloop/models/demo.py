"""Demonstration donation listings for the homepage.

These are NOT real items or people. The UI must always label them as demonstration
data. They will be replaced by approved listings from Supabase in Phase 6.
"""

from pydantic import BaseModel


class DemoListing(BaseModel):
    item: str
    category: str
    condition: str
    locality: str
    pickup: str
    status: str  # one of the listing statuses


DEMO_LISTINGS: list[DemoListing] = [
    DemoListing(
        item="Wooden study table",
        category="Furniture",
        condition="Good, one drawer sticks",
        locality="Thakurli East",
        pickup="Recipient collects",
        status="Available",
    ),
    DemoListing(
        item="Class 8 textbooks, state board",
        category="Books",
        condition="Like new",
        locality="Dombivli West",
        pickup="Hand over at society gate",
        status="Available",
    ),
    DemoListing(
        item="Winter jackets, children's sizes",
        category="Clothes",
        condition="Washed, gently used",
        locality="Kalyan West",
        pickup="Recipient collects",
        status="Reserved",
    ),
]
