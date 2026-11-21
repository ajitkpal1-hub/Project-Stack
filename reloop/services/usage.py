"""Anonymous usage counts for the management dashboard (migration 0006, docs/DASHBOARD.md).

One row per classification: date (set by the database), channel, bin lane and area. Never a photo,
text, IP address or account. Recording runs after the response is sent and never breaks a scan.
"""

from __future__ import annotations

import logging
from typing import Protocol

from reloop.database.supabase import SupabaseClient, SupabaseError
from reloop.models.categories import WasteCategory

log = logging.getLogger("reloop.usage")

AREAS: dict[str, str] = {"dombivli": "Dombivli", "thakurli": "Thakurli", "kalyan": "Kalyan", "other": "Somewhere else"}
CHANNELS = {"web_scan", "voice"}


def clean_area(value: str | None) -> str:
    v = (value or "").strip().lower()
    return v if v in AREAS else "not_given"


class UsageRecorder(Protocol):
    def record(self, channel: str, lane: WasteCategory, area: str = "not_given") -> None: ...


class SupabaseUsage:
    def __init__(self, client: SupabaseClient):
        self.c = client

    def record(self, channel: str, lane: WasteCategory, area: str = "not_given") -> None:
        if channel not in CHANNELS:
            return
        try:
            self.c.rest("POST", "/usage_events", service=True, prefer="return=minimal",
                        json={"channel": channel, "lane": WasteCategory(lane).value, "area": clean_area(area)})
        except (SupabaseError, ValueError):
            log.warning("usage event not recorded (channel=%s)", channel)


class MemoryUsage:
    """For tests."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, str]] = []

    def record(self, channel: str, lane: WasteCategory, area: str = "not_given") -> None:
        if channel in CHANNELS:
            self.events.append((channel, WasteCategory(lane).value, clean_area(area)))
