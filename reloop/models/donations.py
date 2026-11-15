"""Accounts and donations (Phase 6). Mirrors supabase/migrations/0002_accounts_donations.sql."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from reloop.models.categories import WasteCategory

PIN_RE = re.compile(r"^[1-9][0-9]{5}$")


class DonationCategory(StrEnum):
    CLOTHES = "clothes"
    BOOKS = "books"
    TOYS = "toys"
    FURNITURE = "furniture"
    ELECTRONICS = "electronics"
    SCHOOL_SUPPLIES = "school_supplies"
    HOUSEHOLD_GOODS = "household_goods"
    OTHER = "other"


CATEGORY_LABELS: dict[DonationCategory, str] = {
    DonationCategory.CLOTHES: "Clothes",
    DonationCategory.BOOKS: "Books",
    DonationCategory.TOYS: "Toys",
    DonationCategory.FURNITURE: "Furniture",
    DonationCategory.ELECTRONICS: "Electronics",
    DonationCategory.SCHOOL_SUPPLIES: "School supplies",
    DonationCategory.HOUSEHOLD_GOODS: "Household goods",
    DonationCategory.OTHER: "Other reusable items",
}

# Pre-fill the donate form from a scan's waste lane. Hazardous and medical have no entry on purpose.
CATEGORY_FROM_LANE: dict[WasteCategory, DonationCategory] = {
    WasteCategory.TEXTILE: DonationCategory.CLOTHES,
    WasteCategory.E_WASTE: DonationCategory.ELECTRONICS,
    WasteCategory.REUSE: DonationCategory.HOUSEHOLD_GOODS,
    WasteCategory.DRY: DonationCategory.HOUSEHOLD_GOODS,
}


class ListingCondition(StrEnum):
    WORKS_CLEAN = "works_clean"
    NEEDS_REPAIR = "needs_repair"


CONDITION_LABELS: dict[ListingCondition, str] = {
    ListingCondition.WORKS_CLEAN: "Works and is clean",
    ListingCondition.NEEDS_REPAIR: "Needs cleaning or a small repair",
}


class ListingStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    AVAILABLE = "available"
    RESERVED = "reserved"
    COMPLETED = "completed"
    REJECTED = "rejected"


STATUS_LABELS: dict[ListingStatus, str] = {
    ListingStatus.PENDING_REVIEW: "Pending review",
    ListingStatus.AVAILABLE: "Available",
    ListingStatus.RESERVED: "Reserved",
    ListingStatus.COMPLETED: "Completed",
    ListingStatus.REJECTED: "Rejected",
}
PUBLIC_STATUSES = {ListingStatus.AVAILABLE, ListingStatus.RESERVED}


class RequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DECLINED = "declined"
    WITHDRAWN = "withdrawn"


REQUEST_LABELS: dict[RequestStatus, str] = {
    RequestStatus.PENDING: "Waiting for the donor",
    RequestStatus.APPROVED: "Approved",
    RequestStatus.DECLINED: "Declined",
    RequestStatus.WITHDRAWN: "Withdrawn",
}


def _clean(v: str) -> str:
    return " ".join(v.split())


class User(BaseModel):
    """The signed-in person, as confirmed by Supabase Auth."""

    id: str
    email: str
    is_admin: bool = False


class Profile(BaseModel):
    id: str
    display_name: str = ""
    locality: str = ""
    pin_code: str = ""
    contact_note: str = ""  # shared only with the other side of an approved request


class ProfileForm(BaseModel):
    display_name: str = Field("", max_length=60)
    locality: str = Field("", max_length=80)
    pin_code: str = ""
    contact_note: str = Field("", max_length=200)

    _strip = field_validator("display_name", "locality", "contact_note", mode="before")(lambda v: _clean(str(v or "")))

    @field_validator("pin_code", mode="before")
    @classmethod
    def _pin(cls, v: object) -> str:
        v = str(v or "").strip()
        if v and not PIN_RE.match(v):
            raise ValueError("PIN code must be 6 digits and can't start with 0.")
        return v


class ListingForm(BaseModel):
    title: str = Field(min_length=3, max_length=80)
    category: DonationCategory
    condition: ListingCondition
    description: str = Field("", max_length=1000)
    locality: str = Field(min_length=2, max_length=80)
    pin_code: str

    @field_validator("title", "locality", mode="before")
    @classmethod
    def _one_line(cls, v: object) -> str:
        return _clean(str(v or ""))

    @field_validator("description", mode="before")
    @classmethod
    def _desc(cls, v: object) -> str:
        return str(v or "").strip()

    @field_validator("pin_code", mode="before")
    @classmethod
    def _pin(cls, v: object) -> str:
        v = str(v or "").strip()
        if not PIN_RE.match(v):
            raise ValueError("PIN code must be 6 digits and can't start with 0.")
        return v


class Listing(BaseModel):
    id: str
    donor_id: str
    title: str
    category: DonationCategory
    condition: ListingCondition
    description: str = ""
    locality: str
    pin_code: str
    photo_path: str | None = None
    status: ListingStatus = ListingStatus.PENDING_REVIEW
    rejection_reason: str | None = None
    created_at: datetime | None = None


class DonationRequest(BaseModel):
    id: str
    listing_id: str
    requester_id: str
    message: str = ""
    status: RequestStatus = RequestStatus.PENDING
    created_at: datetime | None = None
