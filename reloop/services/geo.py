"""OpenStreetMap lookups: Nominatim (place -> coordinates) and Overpass (nearby recycling places).

Follows the public services' usage policies: an identifying User-Agent (generic app
name, configurable), at most about one request per second, and results cached. Every
place returned here is UNVERIFIED and is labelled that way on the page. Data
(c) OpenStreetMap contributors, ODbL.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Protocol

import httpx

from reloop.models.categories import WasteCategory
from reloop.models.partners import GeoPoint, OsmPlace

log = logging.getLogger("reloop.geo")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_MIRRORS = [OVERPASS_URL, "https://overpass.kumi.systems/api/interpreter"]
OVERPASS_TIMEOUT_S = 8.0  # the page must not hang on a slow public server
OUTAGE_TTL_S = 300  # after a failure, skip the map for a few minutes instead of making every visitor wait
DEFAULT_USER_AGENT = "RELOOP-AI/0.1"
SEARCH_RADIUS_M = 15000
CACHE_TTL_S = 3600


class GeoUnavailable(RuntimeError):
    """The maps service failed. Message is safe to show users."""


class Geo(Protocol):
    def geocode(self, place: str) -> GeoPoint | None: ...
    def nearby(self, point: GeoPoint, material: WasteCategory | None) -> list[OsmPlace]: ...


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)), 1)


RECYCLING_KEYS: dict[WasteCategory, list[str]] = {
    WasteCategory.E_WASTE: ["electrical_appliances", "small_appliances", "mobile_phones", "computers", "electrical_items"],
    WasteCategory.HAZARDOUS: ["batteries", "car_batteries", "low_energy_bulbs", "fluorescent_tubes", "paint", "engine_oil"],
    WasteCategory.TEXTILE: ["clothes", "shoes", "textiles"],
    WasteCategory.DRY: ["paper", "cardboard", "glass", "glass_bottles", "plastic", "plastic_bottles", "cans", "scrap_metal"],
    WasteCategory.WET: ["organic", "green_waste"],
}
ACCEPT_LABELS = {
    "electrical_appliances": "electrical appliances", "small_appliances": "small appliances", "mobile_phones": "mobile phones",
    "computers": "computers", "electrical_items": "electrical items", "batteries": "batteries", "car_batteries": "car batteries",
    "low_energy_bulbs": "CFL bulbs", "fluorescent_tubes": "tube lights", "paint": "paint", "engine_oil": "engine oil",
    "clothes": "clothes", "shoes": "shoes", "textiles": "textiles", "paper": "paper", "cardboard": "cardboard",
    "glass": "glass", "glass_bottles": "glass bottles", "plastic": "plastic", "plastic_bottles": "plastic bottles",
    "cans": "cans", "scrap_metal": "scrap metal", "organic": "food waste", "green_waste": "garden waste",
}


def overpass_query(lat: float, lon: float, material: WasteCategory | None, radius_m: int = SEARCH_RADIUS_M) -> str:
    around = f"(around:{radius_m},{lat:.5f},{lon:.5f})"
    parts: list[str] = []
    if material in RECYCLING_KEYS:
        keys = "|".join(RECYCLING_KEYS[material])
        parts.append(f'nwr[~"^recycling:({keys})$"~"^yes$"]{around};')
    if material in {None, WasteCategory.UNSURE, WasteCategory.DRY}:
        parts.append(f'nwr["amenity"="recycling"]{around};')
        parts.append(f'nwr["industrial"="scrap_yard"]{around};')
        parts.append(f'nwr["amenity"="waste_transfer_station"]{around};')
    if material in {None, WasteCategory.UNSURE, WasteCategory.TEXTILE, WasteCategory.REUSE}:
        parts.append(f'nwr["shop"~"^(second_hand|charity)$"]{around};')
    if material in {None, WasteCategory.UNSURE, WasteCategory.REUSE, WasteCategory.E_WASTE}:
        parts.append(f'nwr["craft"="electronics_repair"]{around};')
        parts.append(f'nwr["repair_cafe"="yes"]{around};')
    return f"[out:json][timeout:8];({''.join(parts)});out center tags 60;"


def _kind_label(tags: dict[str, str]) -> str:
    if tags.get("amenity") == "recycling":
        return "Recycling centre" if tags.get("recycling_type") == "centre" else "Recycling point"
    return {
        ("industrial", "scrap_yard"): "Scrap yard",
        ("amenity", "waste_transfer_station"): "Waste transfer station",
        ("shop", "second_hand"): "Second-hand shop",
        ("shop", "charity"): "Charity shop",
        ("craft", "electronics_repair"): "Electronics repair",
        ("repair_cafe", "yes"): "Repair cafe",
    }.get(next(((k, tags[k]) for k in ("industrial", "amenity", "shop", "craft", "repair_cafe") if k in tags), ("", "")),
          "Recycling place")


def parse_overpass(data: dict, origin: GeoPoint) -> list[OsmPlace]:
    places: dict[str, OsmPlace] = {}
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue
        kind = _kind_label(tags)
        accepts = [ACCEPT_LABELS[k.split(":", 1)[1]] for k, v in tags.items()
                   if k.startswith("recycling:") and v == "yes" and k.split(":", 1)[1] in ACCEPT_LABELS]
        address = ", ".join(x for x in [tags.get("addr:housenumber"), tags.get("addr:street"), tags.get("addr:suburb"),
                                        tags.get("addr:city"), tags.get("addr:postcode")] if x)
        website = tags.get("website") or tags.get("contact:website") or ""
        osm_id = f"{el.get('type', 'node')}/{el.get('id')}"
        places[osm_id] = OsmPlace(
            osm_id=osm_id, name=(tags.get("name") or tags.get("operator") or f"Unnamed {kind.lower()}")[:120],
            kind_label=kind, accepts=sorted(set(accepts)), address=address[:300], latitude=float(lat), longitude=float(lon),
            distance_km=haversine_km(origin.latitude, origin.longitude, float(lat), float(lon)),
            website=website if website.lower().startswith(("https://", "http://")) else "")
    return sorted(places.values(), key=lambda p: p.distance_km or 0)[:30]


class OsmGeo:
    def __init__(self, user_agent: str = DEFAULT_USER_AGENT, timeout_s: float = 20.0):
        self._headers = {"User-Agent": user_agent or DEFAULT_USER_AGENT}
        self._timeout = timeout_s
        self._cache: dict[tuple, tuple[float, object]] = {}
        self._lock = threading.Lock()
        self._last_nominatim = 0.0
        self._overpass_down_until = 0.0

    def _cached(self, key: tuple):
        hit = self._cache.get(key)
        return hit[1] if hit and hit[0] > time.monotonic() else None

    def _store(self, key: tuple, value: object) -> None:
        if len(self._cache) > 500:
            self._cache.clear()
        self._cache[key] = (time.monotonic() + CACHE_TTL_S, value)

    def geocode(self, place: str) -> GeoPoint | None:
        place = " ".join(place.split())[:80]
        key = ("geo", place.lower())
        cached = self._cached(key)
        if cached is not None:
            return cached or None
        params = {"countrycodes": "in", "format": "jsonv2", "limit": "1"}
        if place.isdigit() and len(place) == 6:
            params["postalcode"] = place
        else:
            params["q"] = place
        with self._lock:  # Nominatim policy: at most one request per second
            wait = 1.05 - (time.monotonic() - self._last_nominatim)
            if wait > 0:
                time.sleep(wait)
            try:
                r = httpx.get(NOMINATIM_URL, params=params, headers=self._headers, timeout=self._timeout)
            except httpx.HTTPError:
                log.error("nominatim connection error")
                raise GeoUnavailable("We couldn't reach the map service. Showing our own directory only.") from None
            finally:
                self._last_nominatim = time.monotonic()
        if r.status_code != 200:
            log.error("nominatim error status=%s", r.status_code)
            raise GeoUnavailable("The map service is busy. Showing our own directory only.")
        rows = r.json()
        point = GeoPoint(latitude=float(rows[0]["lat"]), longitude=float(rows[0]["lon"]),
                         label=str(rows[0].get("display_name", place))[:160]) if rows else None
        self._store(key, point or False)
        return point

    def nearby(self, point: GeoPoint, material: WasteCategory | None) -> list[OsmPlace]:
        if material == WasteCategory.MEDICAL:
            return []  # medical waste goes to the municipal/biomedical route, never a random map pin
        key = ("near", round(point.latitude, 3), round(point.longitude, 3), material)
        cached = self._cached(key)
        if cached is not None:
            return cached
        if time.monotonic() < self._overpass_down_until:
            raise GeoUnavailable("The map service is slow right now. Showing our own directory only.")
        query = overpass_query(point.latitude, point.longitude, material)
        data = None
        for url in OVERPASS_MIRRORS:
            try:
                r = httpx.post(url, data={"data": query}, headers=self._headers, timeout=OVERPASS_TIMEOUT_S)
            except httpx.TimeoutException:
                log.error("overpass timeout")
                break  # a slow server: don't make the visitor wait for a second one
            except httpx.HTTPError:
                log.error("overpass connection error")
                continue  # refused straight away: try the next mirror
            if r.status_code == 200:
                data = r.json()
                break
            log.error("overpass error status=%s", r.status_code)
        if data is None:
            self._overpass_down_until = time.monotonic() + OUTAGE_TTL_S
            raise GeoUnavailable("The map service is slow right now. Showing our own directory only.")
        places = parse_overpass(data, point)
        self._store(key, places)
        return places


_default_geo: OsmGeo | None = None


def get_geo(user_agent: str) -> OsmGeo:
    """One shared client per server instance, so the cache and rate limit are shared."""
    global _default_geo
    if _default_geo is None:
        _default_geo = OsmGeo(user_agent)
    return _default_geo
