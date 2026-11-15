"""In-memory DonationRepo for tests and offline development.

Mirrors the row-level security rules in 0002_accounts_donations.sql for the calls
made with a user's token (insert listing, insert request), so tests exercise them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from reloop.database.supabase import SupabaseError
from reloop.models.donations import (
    PUBLIC_STATUSES,
    DonationRequest,
    Listing,
    ListingForm,
    ListingStatus,
    Profile,
    ProfileForm,
    RequestStatus,
)


class InMemoryDonationRepo:
    def __init__(self) -> None:
        self.profiles: dict[str, Profile] = {}
        self.listings: dict[str, Listing] = {}
        self.requests: dict[str, DonationRequest] = {}
        self.photos: dict[str, bytes] = {}
        self._clock = 0

    def _now(self) -> datetime:
        self._clock += 1
        return datetime.fromtimestamp(1_760_000_000 + self._clock, UTC)

    # profiles
    def get_profile(self, user_id: str) -> Profile | None:
        return self.profiles.get(user_id)

    def save_profile(self, user_id: str, form: ProfileForm, token: str) -> Profile:
        p = Profile(id=user_id, **form.model_dump())
        self.profiles[user_id] = p
        return p

    def display_names(self, user_ids: list[str]) -> dict[str, str]:
        return {u: self.profiles[u].display_name for u in user_ids if u in self.profiles}

    # listings
    def insert_listing(self, donor_id: str, form: ListingForm, photo_path: str | None, token: str) -> Listing:
        listing = Listing(id=str(uuid.uuid4()), donor_id=donor_id, photo_path=photo_path,
                          status=ListingStatus.PENDING_REVIEW, created_at=self._now(), **form.model_dump())
        self.listings[listing.id] = listing
        return listing

    def public_listings(self, category: str | None, place: str | None, limit: int = 60) -> list[Listing]:
        rows = [x for x in self.listings.values() if x.status in PUBLIC_STATUSES]
        if category:
            rows = [x for x in rows if x.category.value == category]
        if place:
            rows = [x for x in rows if (x.pin_code.startswith(place) if place.isdigit() else place.lower() in x.locality.lower())]
        return sorted(rows, key=lambda x: x.created_at, reverse=True)[:limit]

    def get_listing(self, listing_id: str) -> Listing | None:
        return self.listings.get(listing_id)

    def listings_by_donor(self, donor_id: str, token: str) -> list[Listing]:
        return sorted((x for x in self.listings.values() if x.donor_id == donor_id), key=lambda x: x.created_at, reverse=True)

    def pending_listings(self) -> list[Listing]:
        return sorted((x for x in self.listings.values() if x.status == ListingStatus.PENDING_REVIEW), key=lambda x: x.created_at)

    def update_listing(self, listing_id: str, **fields: object) -> None:
        self.listings[listing_id] = self.listings[listing_id].model_copy(update=fields)

    def delete_listing(self, listing_id: str) -> None:
        self.listings.pop(listing_id, None)
        for rid in [r.id for r in self.requests.values() if r.listing_id == listing_id]:
            del self.requests[rid]

    # requests
    def insert_request(self, listing_id: str, requester_id: str, message: str, token: str) -> DonationRequest:
        listing = self.listings.get(listing_id)
        if listing is None or listing.status != ListingStatus.AVAILABLE or listing.donor_id == requester_id:
            raise SupabaseError("Something went wrong saving or loading that. Please try again.")  # RLS refusal
        if any(r.listing_id == listing_id and r.requester_id == requester_id for r in self.requests.values()):
            raise SupabaseError("Something went wrong saving or loading that. Please try again.")  # unique constraint
        req = DonationRequest(id=str(uuid.uuid4()), listing_id=listing_id, requester_id=requester_id,
                              message=message, created_at=self._now())
        self.requests[req.id] = req
        return req

    def requests_for_listings(self, listing_ids: list[str]) -> list[DonationRequest]:
        return sorted((r for r in self.requests.values() if r.listing_id in listing_ids), key=lambda r: r.created_at)

    def requests_by_requester(self, requester_id: str, token: str) -> list[DonationRequest]:
        return sorted((r for r in self.requests.values() if r.requester_id == requester_id), key=lambda r: r.created_at, reverse=True)

    def get_request(self, request_id: str) -> DonationRequest | None:
        return self.requests.get(request_id)

    def update_request(self, request_id: str, **fields: object) -> None:
        fields.pop("decided_at", None)
        self.requests[request_id] = self.requests[request_id].model_copy(update=fields)

    def set_requests_for_listing(self, listing_id: str, from_status: RequestStatus, to_status: RequestStatus) -> None:
        for r in list(self.requests.values()):
            if r.listing_id == listing_id and r.status == from_status:
                self.requests[r.id] = r.model_copy(update={"status": to_status})

    # photos
    def upload_photo(self, path: str, data: bytes) -> None:
        self.photos[path] = data

    def photo_url(self, path: str) -> str | None:
        return f"https://storage.example.test/{path}?signed=1" if path in self.photos else None

    def delete_photo(self, path: str) -> None:
        self.photos.pop(path, None)
