"""Usage limits for AI calls, reports and sign-in attempts.

Each visitor is identified by a keyed hash of their IP address (raw IPs are never
stored). Limits are counted in Supabase so they hold across all server instances; if
the database can't be reached, a per-instance in-memory counter takes over so the site
keeps working. A site-wide daily cap bounds the AI bill even under a distributed attack.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import threading
import time
from dataclasses import dataclass
from typing import Protocol

from fastapi import Request

from reloop.database.supabase import SupabaseClient, SupabaseError

log = logging.getLogger("reloop.ratelimit")


@dataclass(frozen=True)
class Limit:
    hits: int
    window_s: int


# (per visitor limits..., site-wide daily cap or None)
POLICIES: dict[str, tuple[list[Limit], int | None]] = {
    "scan": ([Limit(20, 3600), Limit(60, 86400)], 2000),
    "assistant": ([Limit(30, 3600), Limit(100, 86400)], 3000),
    "report": ([Limit(10, 3600)], 1000),
    "auth": ([Limit(10, 900), Limit(40, 86400)], None),
    # Voice tool calls all arrive from ElevenLabs' servers, so the per-visitor limit is
    # effectively a cap on the whole voice channel. Each call may be a paid AI request.
    "voice": ([Limit(300, 3600)], 1500),
    "internal": ([Limit(20, 3600)], 100),  # reel drafts: each one is a paid AI call
}

MESSAGES = {
    "scan": "You've reached the scan limit for now. Please try again in a little while.",
    "assistant": "You've asked a lot of questions in a short time. Please try again in a little while.",
    "report": "Thanks, we've received several reports from you already. Please try again later.",
    "auth": "Too many sign-in attempts. Please wait 15 minutes and try again.",
    "voice": "The voice helper is very busy right now. Please try again later or use the website.",
    "internal": "Too many internal requests in a short time. Try again in an hour.",
}
SITE_CAP_MESSAGE = "RELOOP is very busy today and has paused new AI requests. Please try again tomorrow."


class Counter(Protocol):
    def hit(self, key: str, limit: int, window_s: int) -> bool: ...


class MemoryCounter:
    def __init__(self) -> None:
        self._hits: dict[tuple[str, int], int] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_s: int) -> bool:
        window = int(time.time() // window_s)
        with self._lock:
            if len(self._hits) > 20000:
                self._hits.clear()
            n = self._hits.get((key, window), 0) + 1
            self._hits[(key, window)] = n
        return n <= limit


class SupabaseCounter:
    def __init__(self, client: SupabaseClient, fallback: MemoryCounter):
        self.c, self.fallback = client, fallback

    def hit(self, key: str, limit: int, window_s: int) -> bool:
        try:
            return bool(self.c.rest("POST", "/rpc/hit_rate_limit", service=True,
                                    json={"p_key": key, "p_limit": limit, "p_window_seconds": window_s}))
        except SupabaseError:
            log.warning("rate limit store unavailable; using in-memory counter")
            return self.fallback.hit(key, limit, window_s)


def client_ip(request: Request) -> str:
    """Vercel puts the real client address in these headers and overwrites spoofed values."""
    for header in ("x-vercel-forwarded-for", "x-real-ip", "x-forwarded-for"):
        value = request.headers.get(header)
        if value:
            return value.split(",")[0].strip()[:64]
    return request.client.host if request.client else "unknown"


def visitor_key(request: Request, pepper: str) -> str:
    return hmac.new(pepper.encode() or b"reloop", client_ip(request).encode(), hashlib.sha256).hexdigest()[:32]


class RateLimiter:
    def __init__(self, counter: Counter, pepper: str):
        self.counter, self.pepper = counter, pepper

    def check(self, request: Request, action: str) -> str | None:
        """None if allowed, otherwise a message safe to show the visitor."""
        limits, site_cap = POLICIES[action]
        who = visitor_key(request, self.pepper)
        for lim in limits:
            if not self.counter.hit(f"{action}:{lim.window_s}:{who}", lim.hits, lim.window_s):
                log.warning("rate limited action=%s window=%s", action, lim.window_s)
                return MESSAGES[action]
        if site_cap is not None and not self.counter.hit(f"{action}:site", site_cap, 86400):
            log.error("site-wide daily cap reached action=%s", action)
            return SITE_CAP_MESSAGE
        return None
