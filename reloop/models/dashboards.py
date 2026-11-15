"""Saved items and AI-answer reports (Phase 8). Mirrors supabase/migrations/0004_dashboards.sql."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class SavedKind(StrEnum):
    SCAN = "scan"
    ANSWER = "answer"


class SavedItem(BaseModel):
    id: str
    user_id: str
    kind: SavedKind
    title: str
    lane: str | None = None
    summary: dict = Field(default_factory=dict)
    created_at: datetime | None = None


class FlagReason(StrEnum):
    WRONG_LANE = "wrong_lane"
    UNSAFE = "unsafe"
    WRONG_SOURCE = "wrong_source"
    OTHER = "other"


FLAG_REASON_LABELS: dict[FlagReason, str] = {
    FlagReason.WRONG_LANE: "Wrong bin or wrong item",
    FlagReason.UNSAFE: "Unsafe or risky advice",
    FlagReason.WRONG_SOURCE: "The source doesn't say this",
    FlagReason.OTHER: "Something else",
}


class FlagStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class AiFlag(BaseModel):
    id: str
    kind: SavedKind
    reason: FlagReason
    note: str = ""
    snapshot: dict = Field(default_factory=dict)
    reporter_id: str | None = None
    status: FlagStatus = FlagStatus.OPEN
    admin_note: str = ""
    created_at: datetime | None = None


class KnowledgeDoc(BaseModel):
    id: str
    title: str
    file_name: str = ""
    publisher: str | None = None
    source_url: str | None = None
    published_on: str | None = None
    chunk_count: int = 0
    status: str = "active"
    created_at: datetime | None = None


class UserStats(BaseModel):
    given_away: int = 0  # your listings marked handed over
    listed_now: int = 0  # available or reserved
    waiting_review: int = 0
    received: int = 0  # items you asked for, approved and handed over


class AdminOverview(BaseModel):
    listings_pending: int = 0
    listings_public: int = 0
    listings_completed: int = 0
    suggestions_pending: int = 0
    directory_verified: int = 0
    flags_open: int = 0
    documents_active: int = 0
    members: int | None = None  # None when the count isn't available
