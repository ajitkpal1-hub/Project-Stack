"""Donation rules: who may do what, and how listings move between statuses.

listing:  pending_review --admin--> available | rejected
          available --donor approves a request--> reserved
          reserved  --donor--> completed | available (reservation cancelled)
request:  pending --> approved | declined | withdrawn

Every method checks permission itself (server-side authorization first); row-level
security in the database is the second line of defence.
"""

from __future__ import annotations

import logging
import re
import uuid

from pydantic import BaseModel, Field

from reloop.database.donations import DonationRepo, is_uuid, now_iso
from reloop.database.supabase import SupabaseError
from reloop.models.donations import (
    PUBLIC_STATUSES,
    DonationRequest,
    Listing,
    ListingForm,
    ListingStatus,
    Profile,
    RequestStatus,
    User,
)
from reloop.utils.images import PreparedImage

log = logging.getLogger("reloop.donations")


class DonationError(RuntimeError):
    """A refused or failed action. The message is safe to show users."""


# Words that mean hazardous or medical waste, which can never be listed. Deliberately
# excludes words with innocent meanings ("tablet" the device, "battery" inside a phone).
BLOCKED_TERMS = [
    "medicine", "medicines", "medication", "syringe", "syringes", "needle", "needles", "injection", "insulin",
    "capsule", "capsules", "syrup", "ointment", "expired", "bandage", "bandages", "sanitary pad", "sanitary pads",
    "diaper", "diapers", "used mask", "used masks", "pesticide", "insecticide", "poison", "paint", "thinner",
    "acid", "bleach", "chemical", "chemicals", "kerosene", "petrol", "diesel", "mercury", "tube light",
    "tubelight", "cfl", "asbestos", "gas cylinder",
]
_BLOCKED = re.compile(r"\b(" + "|".join(re.escape(t) for t in sorted(BLOCKED_TERMS, key=len, reverse=True)) + r")\b", re.IGNORECASE)


def find_blocked_term(*texts: str) -> str | None:
    for text in texts:
        m = _BLOCKED.search(text or "")
        if m:
            return m.group(1).lower()
    return None


class RequestView(BaseModel):
    request: DonationRequest
    requester_name: str = ""
    contact_note: str | None = None  # requester's contact, only once the donor approved them


class ListingView(BaseModel):
    listing: Listing
    photo_url: str | None = None
    requests: list[RequestView] = Field(default_factory=list)


class MyRequestView(BaseModel):
    request: DonationRequest
    listing: Listing | None = None
    donor_name: str = ""
    donor_contact: str | None = None  # only when approved


class Dashboard(BaseModel):
    profile: Profile | None
    listings: list[ListingView]
    requests: list[MyRequestView]


class DonationService:
    def __init__(self, repo: DonationRepo):
        self.repo = repo

    # ---------- helpers ----------
    def _photo(self, listing: Listing) -> str | None:
        if not listing.photo_path:
            return None
        try:
            return self.repo.photo_url(listing.photo_path)
        except SupabaseError:
            return None  # the listing still shows, just without its photo

    def _own_listing(self, user: User, listing_id: str) -> Listing:
        listing = self.repo.get_listing(listing_id) if is_uuid(listing_id) else None
        if listing is None or listing.donor_id != user.id:
            raise DonationError("We couldn't find that listing in your account.")
        return listing

    def _request_on_own_listing(self, user: User, request_id: str) -> tuple[DonationRequest, Listing]:
        req = self.repo.get_request(request_id) if is_uuid(request_id) else None
        listing = self.repo.get_listing(req.listing_id) if req else None
        if req is None or listing is None or listing.donor_id != user.id:
            raise DonationError("We couldn't find that request on your listings.")
        return req, listing

    # ---------- listings ----------
    def create_listing(self, user: User, token: str, form: ListingForm, photo: PreparedImage | None) -> Listing:
        term = find_blocked_term(form.title, form.description)
        if term:
            raise DonationError(
                f'This looks like hazardous or medical waste (it mentions "{term}"). These can never be listed as '
                "donations. Scan it to see how to dispose of it safely.")
        photo_path = None
        if photo is not None:
            photo_path = f"{user.id}/{uuid.uuid4()}.jpg"
            self.repo.upload_photo(photo_path, photo.data)
        try:
            listing = self.repo.insert_listing(user.id, form, photo_path, token)
        except SupabaseError:
            if photo_path:
                try:
                    self.repo.delete_photo(photo_path)
                except SupabaseError:
                    log.warning("orphaned listing photo could not be removed")
            raise
        log.info("listing created id=%s category=%s photo=%s", listing.id, listing.category, bool(photo_path))
        return listing

    def browse(self, category: str | None, place: str | None) -> list[ListingView]:
        return [ListingView(listing=x, photo_url=self._photo(x)) for x in self.repo.public_listings(category, place)]

    def view_listing(self, listing_id: str, viewer: User | None) -> ListingView | None:
        """A listing as this viewer may see it: public ones for everyone, others only for the donor or an admin."""
        listing = self.repo.get_listing(listing_id) if is_uuid(listing_id) else None
        if listing is None:
            return None
        allowed = listing.status in PUBLIC_STATUSES or (viewer and (viewer.id == listing.donor_id or viewer.is_admin))
        if not allowed:
            return None
        return ListingView(listing=listing, photo_url=self._photo(listing))

    def existing_request(self, user: User, token: str, listing_id: str) -> DonationRequest | None:
        return next((r for r in self.repo.requests_by_requester(user.id, token) if r.listing_id == listing_id), None)

    def delete_listing(self, user: User, listing_id: str) -> None:
        listing = self._own_listing(user, listing_id)
        if listing.status in {ListingStatus.RESERVED, ListingStatus.COMPLETED}:
            raise DonationError("This listing is reserved or completed, so it can't be removed now.")
        self.repo.delete_listing(listing.id)
        if listing.photo_path:
            try:
                self.repo.delete_photo(listing.photo_path)
            except SupabaseError:
                log.warning("listing photo could not be removed")

    # ---------- requests ----------
    def request_item(self, user: User, token: str, listing_id: str, message: str) -> DonationRequest:
        listing = self.repo.get_listing(listing_id) if is_uuid(listing_id) else None
        if listing is None or listing.status not in PUBLIC_STATUSES:
            raise DonationError("That listing isn't available any more.")
        if listing.donor_id == user.id:
            raise DonationError("This is your own listing.")
        if listing.status != ListingStatus.AVAILABLE:
            raise DonationError("This item is already reserved for someone else.")
        if self.existing_request(user, token, listing.id):
            raise DonationError("You've already asked for this item. Check its status in your dashboard.")
        message = " ".join(message.split())[:500]
        return self.repo.insert_request(listing.id, user.id, message, token)

    def withdraw_request(self, user: User, request_id: str) -> None:
        req = self.repo.get_request(request_id) if is_uuid(request_id) else None
        if req is None or req.requester_id != user.id:
            raise DonationError("We couldn't find that request in your account.")
        if req.status not in {RequestStatus.PENDING, RequestStatus.APPROVED}:
            raise DonationError("This request is already closed.")
        self.repo.update_request(req.id, status=RequestStatus.WITHDRAWN, decided_at=now_iso())
        if req.status == RequestStatus.APPROVED:
            listing = self.repo.get_listing(req.listing_id)
            if listing and listing.status == ListingStatus.RESERVED:
                self.repo.update_listing(listing.id, status=ListingStatus.AVAILABLE)

    def approve_request(self, user: User, request_id: str) -> None:
        req, listing = self._request_on_own_listing(user, request_id)
        if req.status != RequestStatus.PENDING:
            raise DonationError("This request is already closed.")
        if listing.status != ListingStatus.AVAILABLE:
            raise DonationError("This item is already reserved. Cancel that reservation first.")
        self.repo.update_request(req.id, status=RequestStatus.APPROVED, decided_at=now_iso())
        self.repo.update_listing(listing.id, status=ListingStatus.RESERVED)

    def decline_request(self, user: User, request_id: str) -> None:
        req, _ = self._request_on_own_listing(user, request_id)
        if req.status != RequestStatus.PENDING:
            raise DonationError("This request is already closed.")
        self.repo.update_request(req.id, status=RequestStatus.DECLINED, decided_at=now_iso())

    def cancel_reservation(self, user: User, listing_id: str) -> None:
        listing = self._own_listing(user, listing_id)
        if listing.status != ListingStatus.RESERVED:
            raise DonationError("This listing isn't reserved.")
        self.repo.set_requests_for_listing(listing.id, RequestStatus.APPROVED, RequestStatus.DECLINED)
        self.repo.update_listing(listing.id, status=ListingStatus.AVAILABLE)

    def complete_listing(self, user: User, listing_id: str) -> None:
        listing = self._own_listing(user, listing_id)
        if listing.status != ListingStatus.RESERVED:
            raise DonationError("Approve a request first, then mark the item as handed over.")
        self.repo.set_requests_for_listing(listing.id, RequestStatus.PENDING, RequestStatus.DECLINED)
        self.repo.update_listing(listing.id, status=ListingStatus.COMPLETED)

    # ---------- admin ----------
    def _require_admin(self, user: User) -> None:
        if not user.is_admin:
            raise DonationError("Only RELOOP admins can do that.")

    def pending_queue(self, admin: User) -> list[ListingView]:
        self._require_admin(admin)
        return [ListingView(listing=x, photo_url=self._photo(x)) for x in self.repo.pending_listings()]

    def admin_approve(self, admin: User, listing_id: str) -> None:
        self._require_admin(admin)
        listing = self.repo.get_listing(listing_id) if is_uuid(listing_id) else None
        if listing is None or listing.status != ListingStatus.PENDING_REVIEW:
            raise DonationError("That listing isn't waiting for review.")
        self.repo.update_listing(listing.id, status=ListingStatus.AVAILABLE, reviewed_at=now_iso())

    def admin_reject(self, admin: User, listing_id: str, reason: str) -> None:
        self._require_admin(admin)
        listing = self.repo.get_listing(listing_id) if is_uuid(listing_id) else None
        if listing is None or listing.status != ListingStatus.PENDING_REVIEW:
            raise DonationError("That listing isn't waiting for review.")
        reason = " ".join(reason.split())[:300] or "It doesn't meet our listing rules."
        self.repo.update_listing(listing.id, status=ListingStatus.REJECTED, rejection_reason=reason, reviewed_at=now_iso())

    # ---------- dashboard ----------
    def dashboard(self, user: User, token: str) -> Dashboard:
        profile = self.repo.get_profile(user.id)
        mine = self.repo.listings_by_donor(user.id, token)
        reqs = self.repo.requests_for_listings([x.id for x in mine])
        my_reqs = self.repo.requests_by_requester(user.id, token)

        related = {r.requester_id for r in reqs}
        listings_requested = {r.listing_id: self.repo.get_listing(r.listing_id) for r in my_reqs}
        related |= {x.donor_id for x in listings_requested.values() if x}
        names = self.repo.display_names(sorted(related))

        def contact(user_id: str) -> str:
            p = self.repo.get_profile(user_id)
            return p.contact_note if p and p.contact_note else ""

        listing_views = []
        for x in mine:
            views = [RequestView(request=r, requester_name=names.get(r.requester_id) or "A RELOOP member",
                                 contact_note=contact(r.requester_id) if r.status == RequestStatus.APPROVED else None)
                     for r in reqs if r.listing_id == x.id]
            listing_views.append(ListingView(listing=x, photo_url=self._photo(x), requests=views))

        request_views = []
        for r in my_reqs:
            listing = listings_requested.get(r.listing_id)
            approved = r.status == RequestStatus.APPROVED and listing is not None
            request_views.append(MyRequestView(
                request=r, listing=listing,
                donor_name=(names.get(listing.donor_id) if listing else None) or "The donor",
                donor_contact=contact(listing.donor_id) if approved else None))
        return Dashboard(profile=profile, listings=listing_views, requests=request_views)
