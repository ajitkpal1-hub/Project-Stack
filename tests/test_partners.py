"""Phase 7: recycling directory and OpenStreetMap search. All map and database calls are faked."""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from reloop.agents.donation import DonationMatchingAgent
from reloop.agents.recommendation import RecommendationAgent
from reloop.config import get_settings
from reloop.database.memory import InMemoryDonationRepo, InMemoryPartnerRepo
from reloop.database.partners import SupabasePartnerRepo
from reloop.database.supabase import SupabaseClient, SupabaseError
from reloop.models.categories import WasteCategory
from reloop.models.classification import Condition
from reloop.models.donations import User
from reloop.models.partners import GeoPoint, OsmPlace, PartnerForm, PartnerKind, PartnerStatus
from reloop.routes import deps
from reloop.services.geo import GeoUnavailable, OsmGeo, haversine_km, overpass_query, parse_overpass
from reloop.services.partners import DirectoryPartners, PartnerError, PartnerService
from reloop.web import create_app
from tests.test_agents import scan
from tests.test_donations import ADMIN_EMAIL, FakeAuth, post, signup

DOMBIVLI = GeoPoint(latitude=19.2141, longitude=73.0923, label="421201, Dombivali, Thane, Maharashtra, India")
ADMIN = User(id=str(uuid.uuid4()), email=ADMIN_EMAIL, is_admin=True)
MEMBER = User(id=str(uuid.uuid4()), email="m@x.test")


def pform(**over) -> PartnerForm:
    base = dict(name="Green E-Waste Collectors (fixture)", kind=PartnerKind.EWASTE_COLLECTOR, materials=[WasteCategory.E_WASTE],
                locality="Dombivli East", city="Kalyan", pin_code="421201", source_url="https://example.org/authorised-list",
                latitude=19.2180, longitude=73.0950)
    base.update(over)
    return PartnerForm(**base)


class FakeGeo:
    def __init__(self, places=None, fail_geocode=False, fail_nearby=False, point=DOMBIVLI):
        self.places = places or []
        self.fail_geocode, self.fail_nearby, self.point = fail_geocode, fail_nearby, point
        self.calls = []

    def geocode(self, place):
        self.calls.append(("geocode", place))
        if self.fail_geocode:
            raise GeoUnavailable("We couldn't reach the map service. Showing our own directory only.")
        return self.point

    def nearby(self, point, material):
        self.calls.append(("nearby", material))
        if self.fail_nearby:
            raise GeoUnavailable("The map service is busy. Showing our own directory only.")
        return self.places


OSM_PLACE = OsmPlace(osm_id="node/42", name="Ward Dry Waste Centre (map)", kind_label="Recycling centre", accepts=["paper"],
                     latitude=19.22, longitude=73.09, distance_km=0.7)


# ---------- geo helpers ----------

def test_haversine():
    assert haversine_km(19.2141, 73.0923, 19.2141, 73.0923) == 0.0
    assert 25 < haversine_km(19.2141, 73.0923, 19.0760, 72.8777) < 31  # Dombivli to Mumbai, roughly


def test_overpass_query_targets_material():
    q = overpass_query(19.2, 73.09, WasteCategory.E_WASTE)
    assert "electrical_appliances" in q and "around:15000,19.20000,73.09000" in q
    assert "batteries" in overpass_query(19.2, 73.09, WasteCategory.HAZARDOUS)
    assert '"amenity"="recycling"' in overpass_query(19.2, 73.09, None)


def test_parse_overpass_labels_and_sorts():
    data = {"elements": [
        {"type": "node", "id": 1, "lat": 19.30, "lon": 73.09,
         "tags": {"amenity": "recycling", "recycling_type": "centre", "recycling:paper": "yes", "name": "Far Centre"}},
        {"type": "way", "id": 2, "center": {"lat": 19.215, "lon": 73.093},
         "tags": {"industrial": "scrap_yard", "website": "javascript:alert(1)"}},
        {"type": "node", "id": 3, "tags": {"amenity": "recycling"}},  # no coordinates: skipped
    ]}
    places = parse_overpass(data, DOMBIVLI)
    assert [p.osm_id for p in places] == ["way/2", "node/1"]
    assert places[0].name == "Unnamed scrap yard" and places[0].website == ""
    assert places[1].kind_label == "Recycling centre" and places[1].accepts == ["paper"]


def test_osm_geo_handles_errors_and_caches(monkeypatch):
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(headers["User-Agent"])
        return httpx.Response(200, json=[{"lat": "19.2141", "lon": "73.0923", "display_name": "421201, Dombivali"}])

    monkeypatch.setattr(httpx, "get", fake_get)
    geo = OsmGeo("RELOOP-AI/0.1")
    assert geo.geocode("421201").latitude == 19.2141
    assert geo.geocode("421201") is not None and len(calls) == 1  # cached
    assert calls == ["RELOOP-AI/0.1"]

    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(429))
    with pytest.raises(GeoUnavailable):
        geo.nearby(DOMBIVLI, WasteCategory.DRY)
    assert geo.nearby(DOMBIVLI, WasteCategory.MEDICAL) == []  # never map pins for medical waste

    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "get", boom)
    with pytest.raises(GeoUnavailable):
        OsmGeo().geocode("Kalyan West")


# ---------- search ----------

def test_overpass_tries_mirror_on_refusal_and_remembers_outages(monkeypatch):
    urls = []

    def refuse_then_ok(url, data=None, headers=None, timeout=None):
        urls.append(url)
        if len(urls) == 1:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json={"elements": []})

    monkeypatch.setattr(httpx, "post", refuse_then_ok)
    assert OsmGeo().nearby(DOMBIVLI, None) == [] and len(urls) == 2

    calls = []

    def slow(url, data=None, headers=None, timeout=None):
        calls.append(timeout)
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(httpx, "post", slow)
    geo = OsmGeo()
    with pytest.raises(GeoUnavailable, match="slow"):
        geo.nearby(DOMBIVLI, WasteCategory.DRY)
    assert calls == [8.0]  # one short attempt, no second wait
    with pytest.raises(GeoUnavailable):
        geo.nearby(GeoPoint(latitude=19.0, longitude=73.0, label="x"), None)
    assert len(calls) == 1  # outage remembered: no new request


def test_search_puts_verified_first_and_labels_map_results():
    repo = InMemoryPartnerRepo()
    repo.insert_verified(pform())
    repo.insert_verified(pform(name="Pune Recycler (fixture)", pin_code="411001", locality="Camp", city="Pune", latitude=18.52, longitude=73.87))
    r = PartnerService(repo, FakeGeo([OSM_PLACE])).search("421201", WasteCategory.E_WASTE)
    assert [e.name for e in r.verified] == ["Green E-Waste Collectors (fixture)"]
    assert r.verified[0].distance_km is not None and r.verified[0].distance_km < 2
    assert [p.name for p in r.unverified] == ["Ward Dry Waste Centre (map)"]


def test_search_matches_locality_text_without_coordinates():
    repo = InMemoryPartnerRepo()
    repo.insert_verified(pform(latitude=None, longitude=None))
    r = PartnerService(repo, FakeGeo(point=None)).search("dombivli east", None)
    assert len(r.verified) == 1 and r.unverified == []
    assert any("couldn't find that place" in n for n in r.notices)


def test_search_survives_map_outage():
    repo = InMemoryPartnerRepo()
    repo.insert_verified(pform())
    r = PartnerService(repo, FakeGeo(fail_geocode=True)).search("421201", None)
    assert len(r.verified) == 1 and r.unverified == [] and any("directory only" in n for n in r.notices)
    r = PartnerService(repo, FakeGeo(fail_nearby=True)).search("421201", None)
    assert len(r.verified) == 1 and any("busy" in n for n in r.notices)


def test_search_survives_database_outage():
    class Down(InMemoryPartnerRepo):
        def verified(self, *a, **k):
            raise SupabaseError("We couldn't reach the database. Please try again shortly.")

    r = PartnerService(Down(), FakeGeo([OSM_PLACE])).search("421201", None)
    assert r.verified == [] and r.unverified and any("database" in n for n in r.notices)


def test_medical_search_warns():
    r = PartnerService(InMemoryPartnerRepo(), FakeGeo()).search("421201", WasteCategory.MEDICAL)
    assert any("biomedical" in n for n in r.notices)


def test_pending_entries_never_show_in_search():
    repo = InMemoryPartnerRepo()
    svc = PartnerService(repo, FakeGeo())
    svc.suggest(MEMBER, "t", pform(name="Suggested Place"))
    assert svc.search("421201", None).verified == []


# ---------- moderation ----------

def test_admin_add_requires_source_and_admin():
    svc = PartnerService(InMemoryPartnerRepo(), None)
    with pytest.raises(PartnerError, match="Only RELOOP admins"):
        svc.admin_add(MEMBER, pform())
    with pytest.raises(PartnerError, match="source link"):
        svc.admin_add(ADMIN, pform(source_url=""))
    assert svc.admin_add(ADMIN, pform()).status == PartnerStatus.VERIFIED


def test_suggestion_review_flow():
    repo = InMemoryPartnerRepo()
    svc = PartnerService(repo, None)
    good = svc.suggest(MEMBER, "t", pform(name="With Source"))
    bare = svc.suggest(MEMBER, "t", pform(name="No Source", source_url=""))
    assert {e.status for e in svc.my_suggestions(MEMBER, "t")} == {PartnerStatus.PENDING}
    with pytest.raises(PartnerError):
        svc.verify(MEMBER, good.id)
    svc.verify(ADMIN, good.id)
    with pytest.raises(PartnerError, match="no source link"):
        svc.verify(ADMIN, bare.id)
    svc.reject(ADMIN, bare.id)
    assert repo.get(good.id).status == PartnerStatus.VERIFIED and repo.get(bare.id).status == PartnerStatus.REJECTED
    with pytest.raises(PartnerError):
        svc.verify(ADMIN, bare.id)  # no longer pending
    svc.remove(ADMIN, good.id)
    assert repo.get(good.id) is None


def test_partner_form_validation():
    with pytest.raises(ValueError):
        pform(website="javascript:alert(1)")
    with pytest.raises(ValueError):
        pform(pin_code="12345")
    with pytest.raises(ValueError):
        pform(latitude=200)
    assert pform(latitude="", longitude="").latitude is None


# ---------- donation matching uses verified NGOs only ----------

def test_scan_donation_matching_names_only_verified_ngos():
    repo = InMemoryPartnerRepo()
    repo.insert_verified(pform(name="Clothes Bank (fixture)", kind=PartnerKind.NGO, materials=[WasteCategory.TEXTILE],
                               donation_categories=["clothes"]))
    PartnerService(repo, None).suggest(MEMBER, "t", pform(name="Unverified NGO", kind=PartnerKind.NGO, donation_categories=["clothes"]))
    s, _, _ = RecommendationAgent().run(scan(primary_category=WasteCategory.TEXTILE), Condition.WORKS_CLEAN)
    match, _ = DonationMatchingAgent(DirectoryPartners(repo)).run(s)
    assert [p.name for p in match.partners] == ["Clothes Bank (fixture)"]


def test_directory_outage_does_not_break_donation_matching():
    class Down(InMemoryPartnerRepo):
        def verified_ngos(self, *a, **k):
            raise SupabaseError("down")

    assert DirectoryPartners(Down()).find(WasteCategory.TEXTILE) == []
    assert DirectoryPartners(InMemoryPartnerRepo()).find(WasteCategory.MEDICAL) == []


# ---------- REST shapes ----------

def test_verified_query_uses_public_key_and_contains_filter(monkeypatch):
    seen = {}

    def fake(method, url, json=None, params=None, headers=None, timeout=None):
        seen.update(params=params, headers=headers)
        return httpx.Response(200, json=[])

    monkeypatch.setattr(httpx, "request", fake)
    SupabasePartnerRepo(SupabaseClient("https://x.supabase.co", "sb_publishable_k", "sb_secret_k")).verified("e-waste")
    assert seen["params"]["status"] == "eq.verified" and seen["params"]["materials"] == "cs.{e-waste}"
    assert "Authorization" not in seen["headers"]


# ---------- pages ----------

@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", ADMIN_EMAIL)
    get_settings.cache_clear()
    auth, prepo, geo = FakeAuth(), InMemoryPartnerRepo(), FakeGeo([OSM_PLACE])
    deps._auth_override, deps._repo_override = auth, InMemoryDonationRepo()
    deps._partner_repo_override, deps._geo_override = prepo, geo
    deps._VERIFIED.clear()
    yield auth, prepo, geo
    deps._auth_override = deps._repo_override = deps._partner_repo_override = deps._geo_override = None
    deps._VERIFIED.clear()


def test_centres_page_without_search_shows_prompt(env):
    r = TestClient(create_app()).get("/centres")
    assert r.status_code == 200 and "Search near you" in r.text and "Arrives in Phase" not in r.text


def test_centres_search_page_separates_verified_and_unverified(env):
    _, prepo, _ = env
    prepo.insert_verified(pform())
    html = TestClient(create_app()).get("/centres?place=421201&material=e-waste").text
    assert "Verified by RELOOP" in html and "Green E-Waste Collectors (fixture)" in html
    assert "From OpenStreetMap: not verified" in html and "Ward Dry Waste Centre (map)" in html
    assert "OpenStreetMap contributors" in html  # attribution
    assert "https://www.google.com/maps/search/?api=1&amp;query=19.218%2C73.095" in html


def test_member_suggests_and_admin_verifies_through_pages(env):
    _, prepo, _ = env
    member, admin = TestClient(create_app()), TestClient(create_app())
    signup(member, "m@x.test")
    r = member.post("/centres/suggest", data={"name": "Ganesh Kabadiwala", "kind": "scrap_dealer", "materials": ["dry", "e-waste"],
                                              "locality": "Thakurli", "pin_code": "421201", "source_url": "https://example.org/ganesh",
                                              "csrf_token": member.cookies.get("rl_csrf")}, follow_redirects=False)
    assert r.status_code == 303
    entry = next(iter(prepo.rows.values()))
    assert entry.status == PartnerStatus.PENDING and {m.value for m in entry.materials} == {"dry", "e-waste"}
    assert "Ganesh Kabadiwala" not in member.get("/centres?place=421201").text  # hidden until verified

    assert "only for RELOOP admins" in member.get("/admin/partners").text
    post(member, f"/admin/partners/{entry.id}/verify")
    assert prepo.rows[entry.id].status == PartnerStatus.PENDING

    signup(admin, ADMIN_EMAIL)
    assert "Ganesh Kabadiwala" in admin.get("/admin/partners").text
    post(admin, f"/admin/partners/{entry.id}/verify")
    assert "Ganesh Kabadiwala" in member.get("/centres?place=421201").text


def test_admin_add_form_validation_and_success(env):
    _, prepo, _ = env
    admin = TestClient(create_app())
    signup(admin, ADMIN_EMAIL)
    base = {"name": "Ward 12 Dry Waste Centre", "kind": "collection_point", "materials": ["dry"], "locality": "Dombivli West",
            "pin_code": "421202", "csrf_token": admin.cookies.get("rl_csrf")}
    r = admin.post("/admin/partners", data=base)
    assert r.status_code == 422 and "source link" in r.text
    r = admin.post("/admin/partners", data={**base, "source_url": "ftp://bad"})
    assert r.status_code == 422
    r = admin.post("/admin/partners", data={**base, "source_url": "https://example.org/kdmc-list"}, follow_redirects=False)
    assert r.status_code == 303 and len(prepo.verified()) == 1


def test_suggest_requires_login(env):
    c = TestClient(create_app())
    assert "Log in to suggest a place" in c.get("/centres/suggest").text
    c.get("/")
    r = post(c, "/centres/suggest", name="X place", kind="other", locality="Kalyan", pin_code="421301")
    assert r.status_code == 303 and r.headers["location"].startswith("/account/login")


def test_directory_text_is_escaped(env):
    _, prepo, _ = env
    prepo.insert_verified(pform(name="<script>alert(1)</script> Recycler", address="<img src=x onerror=alert(1)>"))
    html = TestClient(create_app()).get("/centres?place=421201").text
    assert "<script>alert(1)</script>" not in html and "<img src=x" not in html


def test_scan_links_to_centres_with_material(env):
    from reloop.routes import scan as scan_route
    from reloop.services.classifier import MockClassifier
    from tests.test_scan import post_photo
    scan_route._classifier_override = MockClassifier()
    try:
        html = post_photo(TestClient(create_app()), "old-charger.jpg").text
        assert 'href="/centres?material=e-waste"' in html
    finally:
        scan_route._classifier_override = None
