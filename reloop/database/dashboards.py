"""Repository functions for saved items, AI-answer reports, knowledge documents and admin counts."""

from __future__ import annotations

from typing import Protocol
from urllib.parse import quote

from reloop.database.donations import is_uuid, now_iso
from reloop.database.supabase import SupabaseClient
from reloop.models.dashboards import AiFlag, KnowledgeDoc, SavedItem, SavedKind


class DashboardRepo(Protocol):
    def save_item(self, user_id: str, kind: SavedKind, title: str, lane: str | None, summary: dict, token: str) -> SavedItem: ...
    def saved_items(self, user_id: str, token: str) -> list[SavedItem]: ...
    def delete_saved(self, user_id: str, item_id: str, token: str) -> None: ...
    def add_flag(self, kind: SavedKind, reason: str, note: str, snapshot: dict, reporter_id: str | None) -> None: ...
    def flags(self, status: str) -> list[AiFlag]: ...
    def get_flag(self, flag_id: str) -> AiFlag | None: ...
    def resolve_flag(self, flag_id: str, admin_note: str) -> None: ...
    def documents(self) -> list[KnowledgeDoc]: ...
    def set_document_status(self, doc_id: str, status: str) -> None: ...
    def count(self, table: str, **filters: str) -> int: ...
    def member_count(self) -> int | None: ...


class SupabaseDashboardRepo:
    def __init__(self, client: SupabaseClient):
        self.c = client

    def save_item(self, user_id, kind, title, lane, summary, token):
        rows = self.c.rest("POST", "/saved_items", token=token, prefer="return=representation",
                           json={"user_id": user_id, "kind": kind.value, "title": title, "lane": lane, "summary": summary})
        return SavedItem(**rows[0])

    def saved_items(self, user_id, token):
        rows = self.c.rest("GET", "/saved_items", token=token,
                           params={"user_id": f"eq.{user_id}", "select": "*", "order": "created_at.desc", "limit": "50"})
        return [SavedItem(**r) for r in rows or []]

    def delete_saved(self, user_id, item_id, token):
        if is_uuid(item_id):  # the user's own token: RLS only lets them delete their own rows
            self.c.rest("DELETE", f"/saved_items?id=eq.{quote(item_id)}&user_id=eq.{quote(user_id)}", token=token, prefer="return=minimal")

    def add_flag(self, kind, reason, note, snapshot, reporter_id):
        self.c.rest("POST", "/ai_flags", service=True, prefer="return=minimal",
                    json={"kind": kind.value, "reason": reason, "note": note, "snapshot": snapshot, "reporter_id": reporter_id})

    def flags(self, status):
        rows = self.c.rest("GET", "/ai_flags", service=True,
                           params={"status": f"eq.{status}", "select": "*", "order": "created_at.asc", "limit": "100"})
        return [AiFlag(**r) for r in rows or []]

    def get_flag(self, flag_id):
        if not is_uuid(flag_id):
            return None
        rows = self.c.rest("GET", "/ai_flags", service=True, params={"id": f"eq.{flag_id}", "select": "*"})
        return AiFlag(**rows[0]) if rows else None

    def resolve_flag(self, flag_id, admin_note):
        self.c.rest("PATCH", f"/ai_flags?id=eq.{quote(flag_id)}", service=True, prefer="return=minimal",
                    json={"status": "resolved", "admin_note": admin_note, "resolved_at": now_iso()})

    def documents(self):
        rows = self.c.rest("GET", "/knowledge_documents", service=True,
                           params={"select": "id,title,file_name,publisher,source_url,published_on,chunk_count,status,created_at",
                                   "order": "title.asc"})
        return [KnowledgeDoc(**r) for r in rows or []]

    def set_document_status(self, doc_id, status):
        self.c.rest("PATCH", f"/knowledge_documents?id=eq.{quote(doc_id)}", service=True, json={"status": status}, prefer="return=minimal")

    def count(self, table, **filters):
        return self.c.count(f"/{table}", {k: f"eq.{v}" for k, v in filters.items()})

    def member_count(self):
        return self.c.count_users()
