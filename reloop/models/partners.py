"""Recycling and donation directory (Phase 7). Mirrors supabase/migrations/0003_partners.sql."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from reloop.models.categories import WasteCategory
from reloop.models.donations import PIN_RE, DonationCategory


class PartnerKind(StrEnum):
    RECYCLER = "recycler"
    EWASTE_COLLECTOR = "ewaste_collector"
    SCRAP_DEALER = "scrap_dealer"
    NGO = "ngo"
    HAZARDOUS_COLLECTION = "hazardous_collection"
    BIOMEDICAL = "biomedical"
    COLLECTION_POINT = "collection_point"
    REPAIR = "repair"
    OTHER = "other"


KIND_LABELS: dict[PartnerKind, str] = {
    PartnerKind.RECYCLER: "Recycler",
    PartnerKind.EWASTE_COLLECTOR: "E-waste collector",
    PartnerKind.SCRAP_DEALER: "Scrap dealer (kabadiwala)",
    PartnerKind.NGO: "NGO or donation centre",
    PartnerKind.HAZARDOUS_COLLECTION: "Hazardous waste collection",
    PartnerKind.BIOMEDICAL: "Biomedical waste facility",
    PartnerKind.COLLECTION_POINT: "Municipal collection point",
    PartnerKind.REPAIR: "Repair shop",
    PartnerKind.OTHER: "Other",
}


class PartnerStatus(StrEnum):
    VERIFIED = "verified"
    PENDING = "pending"
    REJECTED = "rejected"


def _url(v: object) -> str:
    v = str(v or "").strip()
    if v and not v.lower().startswith(("https://", "http://")):
        raise ValueError("Links must start with http:// or https://")
    return v


class PartnerForm(BaseModel):
    """What an admin adds or a member suggests."""

    name: str = Field(min_length=2, max_length=120)
    kind: PartnerKind
    materials: list[WasteCategory] = Field(default_factory=list)
    donation_categories: list[DonationCategory] = Field(default_factory=list)
    address: str = Field("", max_length=300)
    locality: str = Field(min_length=2, max_length=80)
    city: str = Field("", max_length=80)
    pin_code: str
    phone: str = Field("", max_length=40)
    website: str = ""
    source_url: str = ""
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)

    @field_validator("name", "address", "locality", "city", "phone", mode="before")
    @classmethod
    def _one_line(cls, v: object) -> str:
        return " ".join(str(v or "").split())

    @field_validator("pin_code", mode="before")
    @classmethod
    def _pin(cls, v: object) -> str:
        v = str(v or "").strip()
        if not PIN_RE.match(v):
            raise ValueError("PIN code must be 6 digits and can't start with 0.")
        return v

    @field_validator("website", "source_url", mode="before")
    @classmethod
    def _links(cls, v: object) -> str:
        return _url(v)

    @field_validator("latitude", "longitude", mode="before")
    @classmethod
    def _blank_coord(cls, v: object) -> object:
        return None if v in ("", None) else v


class DirectoryEntry(PartnerForm):
    id: str
    status: PartnerStatus = PartnerStatus.PENDING
    submitted_by: str | None = None
    verified_at: datetime | None = None
    created_at: datetime | None = None
    distance_km: float | None = None  # filled in by search when both points are known


class GeoPoint(BaseModel):
    latitude: float
    longitude: float
    label: str


class OsmPlace(BaseModel):
    """A place from OpenStreetMap. Always shown as unverified."""

    osm_id: str  # e.g. "node/123"
    name: str
    kind_label: str
    accepts: list[str] = Field(default_factory=list)
    address: str = ""
    latitude: float
    longitude: float
    distance_km: float | None = None
    website: str = ""
