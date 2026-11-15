"""Repository functions for the recycling and donation directory (table: partners)."""

from __future__ import annotations

from typing import Protocol
from urllib.parse import quote

from reloop.database.donations import is_uuid, now_iso
from reloop.database.supabase import SupabaseClient
from reloop.models.partners import DirectoryEntry, PartnerForm, PartnerKind, PartnerStatus


class PartnerRepo(Protocol):
    def verified(self, material: str | None = None, limit: int = 500) -> list[DirectoryEntry]: ...
    def verified_ngos(self, donation_categories: list[str], limit: int = 5) -> list[DirectoryEntry]: ...
    def insert_suggestion(self, user_id: str, form: PartnerForm, token: str) -> DirectoryEntry: ...
    def insert_verified(self, form: PartnerForm) -> DirectoryEntry: ...
    def pending(self) -> list[DirectoryEntry]: ...
    def by_submitter(self, user_id: str, token: str) -> list[DirectoryEntry]: ...
    def get(self, entry_id: str) -> DirectoryEntry | None: ...
    def set_status(self, entry_id: str, status: PartnerStatus) -> None: ...
    def delete(self, entry_id: str) -> None: ...


def _row(form: PartnerForm) -> dict:
    return form.model_dump(mode="json")


class SupabasePartnerRepo:
    def __init__(self, client: SupabaseClient):
        self.c = client

    def verified(self, material: str | None = None, limit: int = 500) -> list[DirectoryEntry]:
        params = {"select": "*", "status": "eq.verified", "order": "name.asc", "limit": str(limit)}
        if material:
            params["materials"] = f"cs.{{{material}}}"
        rows = self.c.rest("GET", "/partners", params=params)  # public key: RLS shows verified rows only
        return [DirectoryEntry(**r) for r in rows or []]

    def verified_ngos(self, donation_categories: list[str], limit: int = 5) -> list[DirectoryEntry]:
        if not donation_categories:
            return []
        params = {"select": "*", "status": "eq.verified", "kind": f"eq.{PartnerKind.NGO.value}",
                  "donation_categories": "ov.{" + ",".join(donation_categories) + "}", "order": "name.asc", "limit": str(limit)}
        rows = self.c.rest("GET", "/partners", params=params)
        return [DirectoryEntry(**r) for r in rows or []]

    def insert_suggestion(self, user_id: str, form: PartnerForm, token: str) -> DirectoryEntry:
        rows = self.c.rest("POST", "/partners", token=token, json={**_row(form), "submitted_by": user_id, "status": "pending"},
                           prefer="return=representation")
        return DirectoryEntry(**rows[0])

    def insert_verified(self, form: PartnerForm) -> DirectoryEntry:
        rows = self.c.rest("POST", "/partners", service=True, json={**_row(form), "status": "verified", "verified_at": now_iso()},
                           prefer="return=representation")
        return DirectoryEntry(**rows[0])

    def pending(self) -> list[DirectoryEntry]:
        rows = self.c.rest("GET", "/partners", service=True, params={"select": "*", "status": "eq.pending", "order": "created_at.asc"})
        return [DirectoryEntry(**r) for r in rows or []]

    def by_submitter(self, user_id: str, token: str) -> list[DirectoryEntry]:
        rows = self.c.rest("GET", "/partners", token=token,
                           params={"select": "*", "submitted_by": f"eq.{user_id}", "order": "created_at.desc"})
        return [DirectoryEntry(**r) for r in rows or []]

    def get(self, entry_id: str) -> DirectoryEntry | None:
        if not is_uuid(entry_id):
            return None
        rows = self.c.rest("GET", "/partners", service=True, params={"select": "*", "id": f"eq.{entry_id}"})
        return DirectoryEntry(**rows[0]) if rows else None

    def set_status(self, entry_id: str, status: PartnerStatus) -> None:
        body: dict = {"status": status.value}
        if status == PartnerStatus.VERIFIED:
            body["verified_at"] = now_iso()
        self.c.rest("PATCH", f"/partners?id=eq.{quote(entry_id)}", service=True, json=body, prefer="return=minimal")

    def delete(self, entry_id: str) -> None:
        self.c.rest("DELETE", f"/partners?id=eq.{quote(entry_id)}", service=True, prefer="return=minimal")
