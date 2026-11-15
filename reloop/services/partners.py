"""Directory search and moderation.

Search shows two clearly separated groups:
  1. Verified by RELOOP: entries an admin checked against a source.
  2. From OpenStreetMap, not verified: nearby places from the open map, shown for convenience.
If the map service is down, the verified directory still works.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from reloop.database.partners import PartnerRepo
from reloop.database.supabase import SupabaseError
from reloop.models.categories import WasteCategory
from reloop.models.donations import CATEGORY_FROM_LANE, User
from reloop.models.partners import DirectoryEntry, GeoPoint, OsmPlace, PartnerForm, PartnerStatus
from reloop.models.pipeline import Partner
from reloop.services.geo import Geo, GeoUnavailable, haversine_km

log = logging.getLogger("reloop.partners")
NEARBY_KM = 25.0


class PartnerError(RuntimeError):
    """A refused action. Message is safe to show users."""


class SearchResult(BaseModel):
    place: str = ""
    material: WasteCategory | None = None
    located: GeoPoint | None = None
    verified: list[DirectoryEntry] = Field(default_factory=list)
    unverified: list[OsmPlace] = Field(default_factory=list)
    notices: list[str] = Field(default_factory=list)


def _matches_place(entry: DirectoryEntry, place: str) -> bool:
    if place.isdigit():
        return entry.pin_code.startswith(place[:3])  # same postal district (e.g. 421 = Kalyan-Dombivli area)
    words = place.lower()
    return words in entry.locality.lower() or words in entry.city.lower() or entry.locality.lower() in words


class PartnerService:
    def __init__(self, repo: PartnerRepo | None, geo: Geo | None):
        self.repo, self.geo = repo, geo

    def search(self, place: str, material: WasteCategory | None) -> SearchResult:
        place = " ".join(place.split())[:80]
        result = SearchResult(place=place, material=material)
        if material == WasteCategory.MEDICAL:
            result.notices.append("Medical and biomedical waste should go to your municipal collector or a biomedical "
                                  "facility, never a general recycler. We only show verified options for it.")

        entries: list[DirectoryEntry] = []
        if self.repo is not None:
            try:
                entries = self.repo.verified(material.value if material and material != WasteCategory.UNSURE else None)
            except SupabaseError as e:
                result.notices.append(str(e))

        if place and self.geo is not None:
            try:
                result.located = self.geo.geocode(place)
                if result.located is None:
                    result.notices.append("We couldn't find that place on the map. Try a 6-digit PIN code or a locality name.")
            except GeoUnavailable as e:
                result.notices.append(str(e))

        if place:
            near = []
            for e in entries:
                if result.located and e.latitude is not None and e.longitude is not None:
                    e.distance_km = haversine_km(result.located.latitude, result.located.longitude, e.latitude, e.longitude)
                if _matches_place(e, place) or (e.distance_km is not None and e.distance_km <= NEARBY_KM):
                    near.append(e)
            entries = sorted(near, key=lambda e: (e.distance_km is None, e.distance_km or 0, e.pin_code != place, e.name))
        result.verified = entries

        if result.located and self.geo is not None:
            try:
                known = {e.name.lower() for e in entries}
                result.unverified = [p for p in self.geo.nearby(result.located, material) if p.name.lower() not in known]
            except GeoUnavailable as e:
                result.notices.append(str(e))
        return result

    # ---------- suggestions and moderation ----------
    def suggest(self, user: User, token: str, form: PartnerForm) -> DirectoryEntry:
        if self.repo is None:
            raise PartnerError("The directory isn't switched on yet.")
        return self.repo.insert_suggestion(user.id, form, token)

    def my_suggestions(self, user: User, token: str) -> list[DirectoryEntry]:
        return self.repo.by_submitter(user.id, token) if self.repo else []

    def _admin(self, user: User) -> None:
        if not user.is_admin:
            raise PartnerError("Only RELOOP admins can do that.")
        if self.repo is None:
            raise PartnerError("The directory isn't switched on yet.")

    def admin_add(self, admin: User, form: PartnerForm) -> DirectoryEntry:
        self._admin(admin)
        if not form.source_url:
            raise PartnerError("Add the source link you checked (an official list or the organisation's own page).")
        return self.repo.insert_verified(form)

    def pending(self, admin: User) -> list[DirectoryEntry]:
        self._admin(admin)
        return self.repo.pending()

    def verify(self, admin: User, entry_id: str) -> None:
        self._admin(admin)
        entry = self.repo.get(entry_id)
        if entry is None or entry.status != PartnerStatus.PENDING:
            raise PartnerError("That suggestion isn't waiting for review.")
        if not entry.source_url:
            raise PartnerError("This suggestion has no source link. Check the place yourself, then add it with a source link and reject this copy.")
        self.repo.set_status(entry.id, PartnerStatus.VERIFIED)

    def reject(self, admin: User, entry_id: str) -> None:
        self._admin(admin)
        entry = self.repo.get(entry_id)
        if entry is None or entry.status != PartnerStatus.PENDING:
            raise PartnerError("That suggestion isn't waiting for review.")
        self.repo.set_status(entry.id, PartnerStatus.REJECTED)

    def remove(self, admin: User, entry_id: str) -> None:
        self._admin(admin)
        if self.repo.get(entry_id) is None:
            raise PartnerError("We couldn't find that entry.")
        self.repo.delete(entry_id)


class DirectoryPartners:
    """Feeds verified NGOs into the scan's Donation Matching agent (reloop/agents/donation.py)."""

    def __init__(self, repo: PartnerRepo):
        self.repo = repo

    def find(self, category: WasteCategory) -> list[Partner]:
        donation_category = CATEGORY_FROM_LANE.get(category)
        if donation_category is None:
            return []
        try:
            entries = self.repo.verified_ngos([donation_category.value])
        except SupabaseError:
            log.warning("partner directory unavailable for donation matching")
            return []
        return [Partner(name=e.name, locality=e.locality, accepts=[c.value for c in e.donation_categories]) for e in entries]
