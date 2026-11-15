"""Repository functions for profiles, listings, requests and listing photos.

Reads and writes made on a person's behalf use their own token, so row-level security
applies. Status changes and cross-user lookups use the service role, and are only
called by reloop/services/donations.py after it has checked permission.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import quote

from reloop.database.supabase import SupabaseClient
from reloop.models.donations import (
    DonationRequest,
    Listing,
    ListingForm,
    ListingStatus,
    Profile,
    ProfileForm,
    RequestStatus,
)

BUCKET = "listing-photos"
_UUID = re.compile(r"^[0-9a-fA-F-]{36}$")


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def is_uuid(value: str) -> bool:
    return bool(_UUID.match(value or ""))


class DonationRepo(Protocol):
    def get_profile(self, user_id: str) -> Profile | None: ...
    def save_profile(self, user_id: str, form: ProfileForm, token: str) -> Profile: ...
    def display_names(self, user_ids: list[str]) -> dict[str, str]: ...

    def insert_listing(self, donor_id: str, form: ListingForm, photo_path: str | None, token: str) -> Listing: ...
    def public_listings(self, category: str | None, place: str | None, limit: int = 60) -> list[Listing]: ...
    def get_listing(self, listing_id: str) -> Listing | None: ...
    def listings_by_donor(self, donor_id: str, token: str) -> list[Listing]: ...
    def pending_listings(self) -> list[Listing]: ...
    def update_listing(self, listing_id: str, **fields: object) -> None: ...
    def delete_listing(self, listing_id: str) -> None: ...

    def insert_request(self, listing_id: str, requester_id: str, message: str, token: str) -> DonationRequest: ...
    def requests_for_listings(self, listing_ids: list[str]) -> list[DonationRequest]: ...
    def requests_by_requester(self, requester_id: str, token: str) -> list[DonationRequest]: ...
    def get_request(self, request_id: str) -> DonationRequest | None: ...
    def update_request(self, request_id: str, **fields: object) -> None: ...
    def set_requests_for_listing(self, listing_id: str, from_status: RequestStatus, to_status: RequestStatus) -> None: ...

    def upload_photo(self, path: str, data: bytes) -> None: ...
    def photo_url(self, path: str) -> str | None: ...
    def delete_photo(self, path: str) -> None: ...


def _in(ids: list[str]) -> str:
    return "in.(" + ",".join(i for i in ids if is_uuid(i)) + ")"


def _ilike(text: str) -> str:
    # PostgREST pattern: strip characters that have meaning in filters.
    safe = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip()
    return f"*{safe}*"


class SupabaseDonationRepo:
    def __init__(self, client: SupabaseClient):
        self.c = client

    # ---------- profiles ----------
    def get_profile(self, user_id: str) -> Profile | None:
        rows = self.c.rest("GET", "/profiles", service=True, params={"id": f"eq.{user_id}", "select": "*"})
        return Profile(**rows[0]) if rows else None

    def save_profile(self, user_id: str, form: ProfileForm, token: str) -> Profile:
        rows = self.c.rest("POST", "/profiles?on_conflict=id", token=token, json={"id": user_id, **form.model_dump()},
                           prefer="resolution=merge-duplicates,return=representation")
        return Profile(**rows[0])

    def display_names(self, user_ids: list[str]) -> dict[str, str]:
        if not user_ids:
            return {}
        rows = self.c.rest("GET", "/profiles", service=True, params={"id": _in(user_ids), "select": "id,display_name"})
        return {r["id"]: r["display_name"] for r in rows or []}

    # ---------- listings ----------
    def insert_listing(self, donor_id: str, form: ListingForm, photo_path: str | None, token: str) -> Listing:
        body = {"donor_id": donor_id, **form.model_dump(mode="json"), "photo_path": photo_path}
        rows = self.c.rest("POST", "/donation_listings", token=token, json=body, prefer="return=representation")
        return Listing(**rows[0])

    def public_listings(self, category: str | None, place: str | None, limit: int = 60) -> list[Listing]:
        params = {"select": "*", "status": "in.(available,reserved)", "order": "created_at.desc", "limit": str(limit)}
        if category:
            params["category"] = f"eq.{category}"
        if place:
            if place.isdigit():
                params["pin_code"] = f"like.{place}*"
            else:
                params["locality"] = f"ilike.{_ilike(place)}"
        rows = self.c.rest("GET", "/donation_listings", params=params)  # anon key: RLS shows public rows only
        return [Listing(**r) for r in rows or []]

    def get_listing(self, listing_id: str) -> Listing | None:
        if not is_uuid(listing_id):
            return None
        rows = self.c.rest("GET", "/donation_listings", service=True, params={"id": f"eq.{listing_id}", "select": "*"})
        return Listing(**rows[0]) if rows else None

    def listings_by_donor(self, donor_id: str, token: str) -> list[Listing]:
        rows = self.c.rest("GET", "/donation_listings", token=token,
                           params={"donor_id": f"eq.{donor_id}", "select": "*", "order": "created_at.desc"})
        return [Listing(**r) for r in rows or []]

    def pending_listings(self) -> list[Listing]:
        rows = self.c.rest("GET", "/donation_listings", service=True,
                           params={"status": "eq.pending_review", "select": "*", "order": "created_at.asc"})
        return [Listing(**r) for r in rows or []]

    def update_listing(self, listing_id: str, **fields: object) -> None:
        body = {k: (v.value if isinstance(v, ListingStatus) else v) for k, v in fields.items()}
        self.c.rest("PATCH", f"/donation_listings?id=eq.{quote(listing_id)}", service=True, json=body, prefer="return=minimal")

    def delete_listing(self, listing_id: str) -> None:
        self.c.rest("DELETE", f"/donation_listings?id=eq.{quote(listing_id)}", service=True, prefer="return=minimal")

    # ---------- requests ----------
    def insert_request(self, listing_id: str, requester_id: str, message: str, token: str) -> DonationRequest:
        rows = self.c.rest("POST", "/donation_requests", token=token,
                           json={"listing_id": listing_id, "requester_id": requester_id, "message": message},
                           prefer="return=representation")
        return DonationRequest(**rows[0])

    def requests_for_listings(self, listing_ids: list[str]) -> list[DonationRequest]:
        if not listing_ids:
            return []
        rows = self.c.rest("GET", "/donation_requests", service=True,
                           params={"listing_id": _in(listing_ids), "select": "*", "order": "created_at.asc"})
        return [DonationRequest(**r) for r in rows or []]

    def requests_by_requester(self, requester_id: str, token: str) -> list[DonationRequest]:
        rows = self.c.rest("GET", "/donation_requests", token=token,
                           params={"requester_id": f"eq.{requester_id}", "select": "*", "order": "created_at.desc"})
        return [DonationRequest(**r) for r in rows or []]

    def get_request(self, request_id: str) -> DonationRequest | None:
        if not is_uuid(request_id):
            return None
        rows = self.c.rest("GET", "/donation_requests", service=True, params={"id": f"eq.{request_id}", "select": "*"})
        return DonationRequest(**rows[0]) if rows else None

    def update_request(self, request_id: str, **fields: object) -> None:
        body = {k: (v.value if isinstance(v, RequestStatus) else v) for k, v in fields.items()}
        self.c.rest("PATCH", f"/donation_requests?id=eq.{quote(request_id)}", service=True, json=body, prefer="return=minimal")

    def set_requests_for_listing(self, listing_id: str, from_status: RequestStatus, to_status: RequestStatus) -> None:
        self.c.rest("PATCH", f"/donation_requests?listing_id=eq.{quote(listing_id)}&status=eq.{from_status.value}",
                    service=True, json={"status": to_status.value, "decided_at": now_iso()}, prefer="return=minimal")

    # ---------- photos ----------
    def upload_photo(self, path: str, data: bytes) -> None:
        self.c.upload(BUCKET, path, data, "image/jpeg")

    def photo_url(self, path: str) -> str | None:
        return self.c.signed_url(BUCKET, path, expires_in=3600)

    def delete_photo(self, path: str) -> None:
        self.c.remove(BUCKET, [path])
