"""Dashboards: saved scans and answers, AI-answer reports, totals, and the admin overview.

Saved items and reports keep a compact text summary only: never a photo, never a
contact detail. Totals are plain counts; we make no carbon or impact claims.
"""

from __future__ import annotations

import logging

from pydantic import ValidationError

from reloop.database.dashboards import DashboardRepo
from reloop.database.supabase import SupabaseError
from reloop.models.dashboards import AdminOverview, AiFlag, FlagReason, KnowledgeDoc, SavedItem, SavedKind, UserStats
from reloop.models.donations import ListingStatus, RequestStatus, User
from reloop.models.knowledge import Answer
from reloop.models.pipeline import PipelineResult
from reloop.services.donations import Dashboard

log = logging.getLogger("reloop.dashboards")


class DashboardError(RuntimeError):
    """A refused or failed action. Message is safe to show users."""


def _clip(text: str, n: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def scan_summary(result: PipelineResult) -> tuple[str, str, dict]:
    s = result.scan
    summary = {
        "item": _clip(s.identified_item, 120),
        "lane": s.primary_category.value,
        "certainty": s.certainty.value,
        "action": s.recommended_action.value,
        "advice": _clip(s.action_summary, 400),
        "steps": [_clip(x, 200) for x in s.disposal_steps[:5]],
        "warnings": [_clip(x, 200) for x in s.safety_warnings[:5]],
        "options": [_clip(o.title, 80) for o in result.options[:3]],
        "demo": s.demo,
    }
    return _clip(s.identified_item, 120) or "Scanned item", s.primary_category.value, summary


def answer_summary(answer: Answer) -> tuple[str, dict]:
    text = " ".join(seg.text for seg in answer.segments) if answer.segments else (answer.message or "")
    summary = {
        "question": _clip(answer.question, 300),
        "mode": answer.mode.value,
        "answer": _clip(text, 1500),
        "sources": [{"title": _clip(src.title, 160), "page": src.page_from,
                     "url": src.source_url if (src.source_url or "").lower().startswith(("https://", "http://")) else None}
                    for src in answer.sources[:6]],
    }
    return _clip(answer.question, 120) or "Saved answer", summary


def parse_payload(kind: str, payload: str) -> tuple[SavedKind, str, str | None, dict]:
    """Validate a result sent back from the page. Returns (kind, title, lane, summary)."""
    try:
        k = SavedKind(kind)
        if k == SavedKind.SCAN:
            title, lane, summary = scan_summary(PipelineResult.model_validate_json(payload))
            return k, title, lane, summary
        title, summary = answer_summary(Answer.model_validate_json(payload))
        return k, title, None, summary
    except (ValueError, ValidationError):
        raise DashboardError("Something went wrong with that page. Please try again.") from None


def user_stats(board: Dashboard) -> UserStats:
    mine = [lv.listing.status for lv in board.listings]
    return UserStats(
        given_away=sum(1 for s in mine if s == ListingStatus.COMPLETED),
        listed_now=sum(1 for s in mine if s in {ListingStatus.AVAILABLE, ListingStatus.RESERVED}),
        waiting_review=sum(1 for s in mine if s == ListingStatus.PENDING_REVIEW),
        received=sum(1 for r in board.requests
                     if r.request.status == RequestStatus.APPROVED and r.listing and r.listing.status == ListingStatus.COMPLETED),
    )


class DashboardService:
    def __init__(self, repo: DashboardRepo):
        self.repo = repo

    # ---------- members ----------
    def save(self, user: User, token: str, kind: str, payload: str) -> SavedItem:
        k, title, lane, summary = parse_payload(kind, payload)
        if len(self.repo.saved_items(user.id, token)) >= 50:
            raise DashboardError("You've saved 50 items, the most we keep. Delete some old ones first.")
        return self.repo.save_item(user.id, k, title, lane, summary, token)

    def saved(self, user: User, token: str) -> list[SavedItem]:
        return self.repo.saved_items(user.id, token)

    def delete(self, user: User, token: str, item_id: str) -> None:
        self.repo.delete_saved(user.id, item_id, token)

    def report(self, reporter: User | None, kind: str, reason: str, note: str, payload: str) -> None:
        try:
            why = FlagReason(reason)
        except ValueError:
            raise DashboardError("Please choose what's wrong with the answer.") from None
        k, title, _lane, summary = parse_payload(kind, payload)
        self.repo.add_flag(k, why.value, _clip(note, 500), {"title": title, **summary}, reporter.id if reporter else None)
        log.info("ai answer reported kind=%s reason=%s", k.value, why.value)

    # ---------- admins ----------
    def _admin(self, user: User) -> None:
        if not user.is_admin:
            raise DashboardError("Only RELOOP admins can do that.")

    def overview(self, admin: User) -> AdminOverview:
        self._admin(admin)
        c = self.repo.count
        out = AdminOverview(
            listings_pending=c("donation_listings", status="pending_review"),
            listings_public=c("donation_listings", status="available") + c("donation_listings", status="reserved"),
            listings_completed=c("donation_listings", status="completed"),
            suggestions_pending=c("partners", status="pending"),
            directory_verified=c("partners", status="verified"),
            flags_open=c("ai_flags", status="open"),
            documents_active=c("knowledge_documents", status="active"),
        )
        try:
            out.members = self.repo.member_count()
        except SupabaseError:
            out.members = None
        return out

    def open_flags(self, admin: User) -> list[AiFlag]:
        self._admin(admin)
        return self.repo.flags("open")

    def resolve(self, admin: User, flag_id: str, admin_note: str) -> None:
        self._admin(admin)
        flag = self.repo.get_flag(flag_id)
        if flag is None or flag.status.value != "open":
            raise DashboardError("That report is already closed.")
        self.repo.resolve_flag(flag.id, _clip(admin_note, 300))

    def documents(self, admin: User) -> list[KnowledgeDoc]:
        self._admin(admin)
        return self.repo.documents()

    def set_document(self, admin: User, doc_id: str, active: bool) -> None:
        self._admin(admin)
        doc = next((d for d in self.repo.documents() if d.id == doc_id), None)
        if doc is None:
            raise DashboardError("We couldn't find that document.")
        self.repo.set_document_status(doc.id, "active" if active else "archived")
