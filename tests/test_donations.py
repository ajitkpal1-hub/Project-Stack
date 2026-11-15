"""Phase 6: accounts and donations. Supabase is replaced by fakes; nothing touches the network."""

from __future__ import annotations

import io
import time
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from reloop.config import get_settings
from reloop.database.donations import SupabaseDonationRepo
from reloop.database.memory import InMemoryDonationRepo
from reloop.database.supabase import AuthError, Session, SupabaseClient, SupabaseError
from reloop.models.donations import (
    DonationCategory,
    ListingCondition,
    ListingForm,
    ListingStatus,
    ProfileForm,
    RequestStatus,
    User,
)
from reloop.routes import deps
from reloop.security import SESSION_COOKIE, decode_session, encode_session
from reloop.services.donations import DonationError, DonationService, find_blocked_term
from reloop.utils.images import prepare_image
from reloop.web import create_app

ADMIN_EMAIL = "admin@reloop.test"


class FakeAuth:
    """Stands in for Supabase Auth."""

    def __init__(self) -> None:
        self.users: dict[str, tuple[str, str]] = {}  # email -> (id, password)
        self.tokens: dict[str, str] = {}  # access token -> user id
        self.refreshes = 0
        self.expire_next = False

    def _session(self, uid: str, email: str) -> Session:
        token = f"tok-{uuid.uuid4()}"
        self.tokens[token] = uid
        expires = int(time.time()) - 10 if self.expire_next else int(time.time()) + 3600
        self.expire_next = False
        return Session(access_token=token, refresh_token=f"ref-{uid}", expires_at=expires, user_id=uid, email=email)

    def sign_up(self, email, password):
        if email in self.users:
            raise AuthError("An account with this email already exists. Please log in instead.")
        uid = str(uuid.uuid4())
        self.users[email] = (uid, password)
        return self._session(uid, email)

    def sign_in(self, email, password):
        uid, pw = self.users.get(email, (None, None))
        if uid is None or pw != password:
            raise AuthError("That email and password don't match. Please try again.")
        return self._session(uid, email)

    def refresh(self, refresh_token):
        self.refreshes += 1
        uid = refresh_token.removeprefix("ref-")
        email = next((e for e, (i, _) in self.users.items() if i == uid), None)
        if email is None:
            raise AuthError("expired")
        return self._session(uid, email)

    def get_user(self, token):
        uid = self.tokens.get(token)
        if uid is None:
            return None
        email = next(e for e, (i, _) in self.users.items() if i == uid)
        return {"id": uid, "email": email}

    def sign_out(self, token):
        self.tokens.pop(token, None)


def form(**over) -> ListingForm:
    base = dict(title="Wooden study table", category=DonationCategory.FURNITURE, condition=ListingCondition.WORKS_CLEAN,
                description="One drawer sticks.", locality="Thakurli East", pin_code="421201")
    base.update(over)
    return ListingForm(**base)


def image_bytes(fmt="JPEG", gps=False) -> bytes:
    img = Image.new("RGB", (80, 60), (120, 80, 40))
    buf = io.BytesIO()
    if gps:
        exif = Image.Exif()
        exif[0x8825] = {1: "N", 2: (19.0, 13.0, 0.0), 3: "E", 4: (73.0, 5.0, 0.0)}  # GPS IFD
        img.save(buf, format=fmt, exif=exif)
    else:
        img.save(buf, format=fmt)
    return buf.getvalue()


# ---------- service: rules and permissions ----------

@pytest.fixture
def svc():
    return DonationService(InMemoryDonationRepo())


DONOR = User(id=str(uuid.uuid4()), email="donor@x.test")
ASKER = User(id=str(uuid.uuid4()), email="asker@x.test")
OTHER = User(id=str(uuid.uuid4()), email="other@x.test")
ADMIN = User(id=str(uuid.uuid4()), email=ADMIN_EMAIL, is_admin=True)


def approved_listing(svc, **over):
    listing = svc.create_listing(DONOR, "t", form(**over), None)
    svc.admin_approve(ADMIN, listing.id)
    return listing


@pytest.mark.parametrize("text", ["expired medicines", "Used SYRINGES box", "half tin of paint", "pesticide spray", "old tube light"])
def test_hazardous_or_medical_words_block_listing(svc, text):
    with pytest.raises(DonationError, match="can never be listed"):
        svc.create_listing(DONOR, "t", form(title=text), None)


@pytest.mark.parametrize("text", ["Samsung tablet", "Phone with battery and charger", "Painting book", "Kids' paintbrushes"])
def test_innocent_words_are_allowed(text):
    assert find_blocked_term(text) is None


def test_new_listing_is_pending_and_hidden_from_others(svc):
    listing = svc.create_listing(DONOR, "t", form(), None)
    assert listing.status == ListingStatus.PENDING_REVIEW
    assert svc.browse(None, None) == []
    assert svc.view_listing(listing.id, OTHER) is None
    assert svc.view_listing(listing.id, None) is None
    assert svc.view_listing(listing.id, DONOR) is not None
    assert svc.view_listing(listing.id, ADMIN) is not None


def test_only_admins_review(svc):
    listing = svc.create_listing(DONOR, "t", form(), None)
    with pytest.raises(DonationError, match="Only RELOOP admins"):
        svc.admin_approve(DONOR, listing.id)
    with pytest.raises(DonationError):
        svc.pending_queue(OTHER)
    svc.admin_reject(ADMIN, listing.id, "Please remove the phone number from the description.")
    stored = svc.repo.get_listing(listing.id)
    assert stored.status == ListingStatus.REJECTED and "phone number" in stored.rejection_reason
    with pytest.raises(DonationError):
        svc.admin_approve(ADMIN, listing.id)  # no longer pending


def test_browse_filters_by_category_and_place(svc):
    approved_listing(svc)
    approved_listing(svc, title="School bag", category=DonationCategory.SCHOOL_SUPPLIES, locality="Kalyan West", pin_code="421301")
    assert [v.listing.title for v in svc.browse("school_supplies", None)] == ["School bag"]
    assert [v.listing.title for v in svc.browse(None, "4213")] == ["School bag"]
    assert [v.listing.title for v in svc.browse(None, "thakurli")] == ["Wooden study table"]


def test_request_rules(svc):
    listing = approved_listing(svc)
    with pytest.raises(DonationError, match="your own listing"):
        svc.request_item(DONOR, "t", listing.id, "")
    svc.request_item(ASKER, "t", listing.id, "For my son")
    with pytest.raises(DonationError, match="already asked"):
        svc.request_item(ASKER, "t", listing.id, "again")
    pending = svc.create_listing(DONOR, "t", form(title="Bookshelf"), None)
    with pytest.raises(DonationError, match="isn't available"):
        svc.request_item(ASKER, "t", pending.id, "")
    with pytest.raises(DonationError):
        svc.request_item(ASKER, "t", "not-a-uuid", "")


def test_approve_reserves_and_shares_contact_only_with_matched_pair(svc):
    svc.repo.save_profile(DONOR.id, ProfileForm(display_name="Asha", contact_note="WhatsApp 98xxxxxx10"), "t")
    svc.repo.save_profile(ASKER.id, ProfileForm(display_name="Ravi", contact_note="Call after 6pm"), "t")
    svc.repo.save_profile(OTHER.id, ProfileForm(display_name="Meera", contact_note="other-contact"), "t")
    listing = approved_listing(svc)
    req = svc.request_item(ASKER, "t", listing.id, "Need it for studies")
    svc.request_item(OTHER, "t", listing.id, "Me too")

    before = svc.dashboard(DONOR, "t")
    assert all(rv.contact_note is None for rv in before.listings[0].requests)
    assert svc.dashboard(ASKER, "t").requests[0].donor_contact is None

    with pytest.raises(DonationError):
        svc.approve_request(OTHER, req.id)  # not their listing
    svc.approve_request(DONOR, req.id)
    assert svc.repo.get_listing(listing.id).status == ListingStatus.RESERVED

    donor_view = {rv.requester_name: rv.contact_note for rv in svc.dashboard(DONOR, "t").listings[0].requests}
    assert donor_view == {"Ravi": "Call after 6pm", "Meera": None}
    assert svc.dashboard(ASKER, "t").requests[0].donor_contact == "WhatsApp 98xxxxxx10"
    assert svc.dashboard(OTHER, "t").requests[0].donor_contact is None


def test_complete_declines_the_rest(svc):
    listing = approved_listing(svc)
    a = svc.request_item(ASKER, "t", listing.id, "")
    b = svc.request_item(OTHER, "t", listing.id, "")
    with pytest.raises(DonationError, match="Approve a request first"):
        svc.complete_listing(DONOR, listing.id)
    svc.approve_request(DONOR, a.id)
    with pytest.raises(DonationError):
        svc.approve_request(DONOR, b.id)  # already reserved
    svc.complete_listing(DONOR, listing.id)
    assert svc.repo.get_listing(listing.id).status == ListingStatus.COMPLETED
    assert svc.repo.get_request(b.id).status == RequestStatus.DECLINED
    assert svc.view_listing(listing.id, OTHER) is None  # completed listings leave Explore


def test_cancel_reservation_and_withdraw_return_item_to_available(svc):
    listing = approved_listing(svc)
    a = svc.request_item(ASKER, "t", listing.id, "")
    svc.approve_request(DONOR, a.id)
    svc.cancel_reservation(DONOR, listing.id)
    assert svc.repo.get_listing(listing.id).status == ListingStatus.AVAILABLE
    assert svc.repo.get_request(a.id).status == RequestStatus.DECLINED

    b = svc.request_item(OTHER, "t", listing.id, "")
    svc.approve_request(DONOR, b.id)
    with pytest.raises(DonationError):
        svc.withdraw_request(ASKER, b.id)  # someone else's request
    svc.withdraw_request(OTHER, b.id)
    assert svc.repo.get_listing(listing.id).status == ListingStatus.AVAILABLE


def test_delete_listing_permissions(svc):
    listing = approved_listing(svc)
    with pytest.raises(DonationError):
        svc.delete_listing(OTHER, listing.id)
    req = svc.request_item(ASKER, "t", listing.id, "")
    svc.approve_request(DONOR, req.id)
    with pytest.raises(DonationError, match="reserved or completed"):
        svc.delete_listing(DONOR, listing.id)
    svc.cancel_reservation(DONOR, listing.id)
    svc.delete_listing(DONOR, listing.id)
    assert svc.repo.get_listing(listing.id) is None


def test_photo_is_stored_under_the_donors_folder_and_removed_on_failure(svc):
    photo = prepare_image(image_bytes(), "image/jpeg")
    listing = svc.create_listing(DONOR, "t", form(), photo)
    assert listing.photo_path.startswith(f"{DONOR.id}/") and listing.photo_path in svc.repo.photos

    def boom(*a, **k):
        raise SupabaseError("db down")

    svc.repo.insert_listing = boom
    with pytest.raises(SupabaseError):
        svc.create_listing(DONOR, "t", form(title="Second table"), photo)
    assert len(svc.repo.photos) == 1  # the failed listing's photo was cleaned up


def test_photo_location_data_is_stripped():
    raw = image_bytes(gps=True)
    assert Image.open(io.BytesIO(raw)).getexif().get_ifd(0x8825)
    cleaned = prepare_image(raw, "image/jpeg").data
    assert not Image.open(io.BytesIO(cleaned)).getexif().get_ifd(0x8825)


def test_listing_form_validation():
    with pytest.raises(ValueError):
        form(pin_code="012345")
    with pytest.raises(ValueError):
        form(title="ab")
    assert form(title="  Big   table  ").title == "Big table"


# ---------- REST repo request shapes ----------

def test_public_listings_use_anon_key_and_safe_filters(monkeypatch):
    seen = {}

    def fake(method, url, json=None, params=None, headers=None, timeout=None):
        seen.update(method=method, url=url, params=params, headers=headers)
        return httpx.Response(200, json=[])

    monkeypatch.setattr(httpx, "request", fake)
    repo = SupabaseDonationRepo(SupabaseClient("https://x.supabase.co", "anon-key", "service-key"))
    repo.public_listings("books", "Kalyan,West)*")
    assert seen["headers"]["apikey"] == "anon-key" and "Authorization" not in seen["headers"]
    assert seen["params"]["status"] == "in.(available,reserved)"
    assert seen["params"]["locality"] == "ilike.*KalyanWest*"


def test_status_updates_use_service_role(monkeypatch):
    seen = {}

    def fake(method, url, json=None, params=None, headers=None, timeout=None):
        seen.update(method=method, url=url, json=json, headers=headers)
        return httpx.Response(204)

    monkeypatch.setattr(httpx, "request", fake)
    repo = SupabaseDonationRepo(SupabaseClient("https://x.supabase.co", "anon-key", "service-key"))
    lid = str(uuid.uuid4())
    repo.update_listing(lid, status=ListingStatus.AVAILABLE)
    assert seen["method"] == "PATCH" and seen["headers"]["Authorization"] == "Bearer service-key"
    assert seen["json"] == {"status": "available"}


def test_auth_errors_become_friendly_messages(monkeypatch):
    monkeypatch.setattr(httpx, "request", lambda *a, **k: httpx.Response(400, json={"error_code": "invalid_credentials"}))
    client = SupabaseClient("https://x.supabase.co", "anon", "service")
    with pytest.raises(AuthError, match="don't match"):
        client.sign_in("a@b.co", "wrongpass")


def test_duplicate_signup_is_reported(monkeypatch):
    monkeypatch.setattr(httpx, "request", lambda *a, **k: httpx.Response(200, json={"id": "x", "identities": []}))
    with pytest.raises(AuthError, match="already exists"):
        SupabaseClient("https://x.supabase.co", "anon", "service").sign_up("a@b.co", "longenough")


def test_session_cookie_round_trip_and_garbage():
    s = Session(access_token="a", refresh_token="r", expires_at=1, user_id="u", email="e@x.co")
    assert decode_session(encode_session(s)) == s
    assert decode_session("not-base64!!") is None
    assert decode_session(None) is None


# ---------- pages ----------

@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", ADMIN_EMAIL)
    get_settings.cache_clear()
    auth, repo = FakeAuth(), InMemoryDonationRepo()
    deps._auth_override, deps._repo_override = auth, repo
    deps._VERIFIED.clear()
    yield auth, repo
    deps._auth_override = deps._repo_override = None
    deps._VERIFIED.clear()


def new_client() -> TestClient:
    return TestClient(create_app())


def csrf(client: TestClient) -> str:
    client.get("/account/login")
    return client.cookies.get("rl_csrf")


def signup(client: TestClient, email: str, password: str = "correct-horse") -> None:
    r = client.post("/account/signup", data={"email": email, "password": password, "csrf_token": csrf(client)}, follow_redirects=False)
    assert r.status_code == 303, r.text


def post(client: TestClient, url: str, **data):
    return client.post(url, data={**data, "csrf_token": client.cookies.get("rl_csrf")}, follow_redirects=False)


def test_forms_without_csrf_token_are_refused(env):
    c = new_client()
    c.get("/")
    r = c.post("/account/login", data={"email": "a@b.co", "password": "x" * 10})
    assert r.status_code == 403 and "form expired" in r.text


def test_signup_login_logout(env):
    auth, _ = env
    c = new_client()
    signup(c, "Priya@Example.com")
    assert c.cookies.get(SESSION_COOKIE)
    assert "priya@example.com" in auth.users
    page = c.get("/dashboard")
    assert page.status_code == 200 and "My listings" in page.text
    assert post(c, "/account/logout").status_code == 303
    assert c.get("/dashboard", follow_redirects=False).status_code == 303

    r = c.post("/account/login", data={"email": "priya@example.com", "password": "wrong-password", "csrf_token": csrf(c)})
    assert r.status_code == 400 and "don&#39;t match" in r.text


def test_signup_validation(env):
    c = new_client()
    r = c.post("/account/signup", data={"email": "not-an-email", "password": "longenough", "csrf_token": csrf(c)})
    assert r.status_code == 422 and "valid email" in r.text
    r = c.post("/account/signup", data={"email": "a@b.co", "password": "short", "csrf_token": csrf(c)})
    assert r.status_code == 422 and "at least 8" in r.text


@pytest.mark.parametrize("nxt,expected", [("/donate", "/donate"), ("//evil.example", "/dashboard"),
                                          ("https://evil.example", "/dashboard"), ("/\\evil", "/dashboard")])
def test_login_redirect_stays_on_site(env, nxt, expected):
    c = new_client()
    signup(c, "a@b.co")
    post(c, "/account/logout")
    r = c.post("/account/login", data={"email": "a@b.co", "password": "correct-horse", "next": nxt, "csrf_token": csrf(c)},
               follow_redirects=False)
    assert r.headers["location"] == expected


def test_expired_session_is_refreshed(env):
    auth, _ = env
    c = new_client()
    auth.expire_next = True
    signup(c, "a@b.co")
    old = c.cookies.get(SESSION_COOKIE)
    assert c.get("/dashboard").status_code == 200
    assert auth.refreshes == 1 and c.cookies.get(SESSION_COOKIE) != old


def test_revoked_session_signs_out(env):
    auth, _ = env
    c = new_client()
    signup(c, "a@b.co")
    auth.tokens.clear()
    auth.users.clear()  # refresh fails too
    deps._VERIFIED.clear()
    assert c.get("/dashboard", follow_redirects=False).status_code == 303


def test_profile_save_and_pin_validation(env):
    _, repo = env
    c = new_client()
    signup(c, "a@b.co")
    r = post(c, "/account", display_name="Asha", locality="Dombivli East", pin_code="021201", contact_note="")
    assert r.status_code == 422 and "6 digits" in r.text
    assert post(c, "/account", display_name="Asha", locality="Dombivli East", pin_code="421201", contact_note="WA 98").status_code == 303
    assert next(iter(repo.profiles.values())).locality == "Dombivli East"


def test_full_donation_journey_keeps_contacts_private(env):
    _, repo = env
    donor, asker, admin, stranger = new_client(), new_client(), new_client(), new_client()
    signup(donor, "donor@x.test")
    post(donor, "/account", display_name="Asha", locality="Thakurli East", pin_code="421201", contact_note="WhatsApp 98xxxxxx10")
    r = donor.post("/donate", data={"title": "Children's story books", "category": "books", "condition": "works_clean",
                                    "description": "Set of 12", "locality": "Thakurli East", "pin_code": "421201",
                                    "csrf_token": donor.cookies.get("rl_csrf")},
                   files={"photo": ("books.jpg", image_bytes(), "image/jpeg")}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/dashboard"
    listing = next(iter(repo.listings.values()))
    assert listing.status == ListingStatus.PENDING_REVIEW and listing.photo_path

    assert "Children&#39;s story books" not in stranger.get("/donations").text  # not public yet

    signup(admin, ADMIN_EMAIL)
    queue = admin.get("/admin/listings")
    assert queue.status_code == 200 and "story books" in queue.text
    assert post(admin, f"/admin/listings/{listing.id}/approve").status_code == 303

    explore = stranger.get("/donations")
    assert "story books" in explore.text and "WhatsApp" not in explore.text and "donor@x.test" not in explore.text
    detail = stranger.get(f"/donations/{listing.id}")
    assert "Log in to request" in detail.text and "WhatsApp" not in detail.text

    signup(asker, "asker@x.test")
    post(asker, "/account", display_name="Ravi", locality="Kalyan", pin_code="421301", contact_note="Call after 6pm")
    assert post(asker, f"/donations/{listing.id}/request", message="For my daughter").status_code == 303
    board = donor.get("/dashboard").text
    assert "Ravi" in board and "For my daughter" in board and "Call after 6pm" not in board

    req = next(iter(repo.requests.values()))
    assert post(donor, f"/dashboard/requests/{req.id}/approve").status_code == 303
    assert "Call after 6pm" in donor.get("/dashboard").text
    assert "WhatsApp 98xxxxxx10" in asker.get("/dashboard").text
    assert "WhatsApp" not in stranger.get(f"/donations/{listing.id}").text

    assert post(donor, f"/dashboard/listings/{listing.id}/complete").status_code == 303
    assert repo.listings[listing.id].status == ListingStatus.COMPLETED


def test_non_admin_cannot_use_admin_queue(env):
    _, repo = env
    c = new_client()
    signup(c, "someone@x.test")
    assert "only for RELOOP admins" in c.get("/admin").text
    listing = DonationService(repo).create_listing(User(id=str(uuid.uuid4()), email="d@x.test"), "t", form(), None)
    r = post(c, f"/admin/listings/{listing.id}/approve")
    assert r.status_code == 303 and repo.listings[listing.id].status == ListingStatus.PENDING_REVIEW


def test_cannot_act_on_someone_elses_request(env):
    _, repo = env
    owner, intruder = new_client(), new_client()
    signup(owner, "owner@x.test")
    signup(intruder, "intruder@x.test")
    svc = DonationService(repo)
    owner_id = next(i for e, (i, _) in env[0].users.items() if e == "owner@x.test")
    listing = svc.create_listing(User(id=owner_id, email="owner@x.test"), "t", form(), None)
    svc.admin_approve(ADMIN, listing.id)
    asker = User(id=str(uuid.uuid4()), email="z@x.test")
    req = svc.request_item(asker, "t", listing.id, "")
    post(intruder, f"/dashboard/requests/{req.id}/approve")
    post(intruder, f"/dashboard/listings/{listing.id}/delete")
    assert repo.requests[req.id].status == RequestStatus.PENDING
    assert listing.id in repo.listings


def test_donate_page_prefills_from_scan_and_blocks_hazard_lanes(env):
    c = new_client()
    signup(c, "a@b.co")
    page = c.get("/donate?title=Old%20cotton%20shirt&lane=textile&condition=works_clean").text
    assert 'value="Old cotton shirt"' in page and 'value="clothes" selected' in page
    r = c.get("/donate?title=Syringes&lane=medical")
    assert r.status_code == 422 and "can never be listed" in r.text


def test_donate_rejects_hazardous_text_and_bad_photo(env):
    _, repo = env
    c = new_client()
    signup(c, "a@b.co")
    base = {"category": "other", "condition": "works_clean", "locality": "Kalyan", "pin_code": "421301",
            "csrf_token": c.cookies.get("rl_csrf")}
    r = c.post("/donate", data={**base, "title": "Leftover paint tins"})
    assert r.status_code == 422 and "can never be listed" in r.text
    r = c.post("/donate", data={**base, "title": "Lamp"}, files={"photo": ("x.jpg", b"not an image", "image/jpeg")})
    assert r.status_code == 422
    assert repo.listings == {}


def test_signed_out_donate_and_request_need_login(env):
    c = new_client()
    assert "Log in to list an item" in c.get("/donate").text
    c.get("/")
    r = post(c, "/donate", title="Lamp", category="other", condition="works_clean", locality="Kalyan", pin_code="421301")
    assert r.status_code == 303 and r.headers["location"].startswith("/account/login")


def test_user_text_is_escaped_everywhere(env):
    _, repo = env
    svc = DonationService(repo)
    listing = svc.create_listing(DONOR, "t", form(title="<script>alert(1)</script> table",
                                                  description="<img src=x onerror=alert(1)>"), None)
    svc.admin_approve(ADMIN, listing.id)
    c = new_client()
    for path in ["/donations", f"/donations/{listing.id}"]:
        html = c.get(path).text
        assert "<script>alert(1)</script>" not in html and "<img src=x" not in html


def test_unknown_listing_and_page_show_friendly_404(env):
    c = new_client()
    assert c.get(f"/donations/{uuid.uuid4()}").status_code == 404
    r = c.get("/no-such-page")
    assert r.status_code == 404 and "couldn&#39;t find that page" in r.text


def test_accounts_off_shows_honest_notice():
    c = new_client()  # no overrides, no Supabase settings
    assert "switched on yet" in c.get("/account/login").text
    assert "switched on yet" in c.get("/donations").text


def test_signed_in_pages_are_not_cached(env):
    c = new_client()
    signup(c, "a@b.co")
    assert c.get("/dashboard").headers.get("cache-control") == "private, no-store"


def test_listing_ids_are_validated_before_queries(env):
    c = new_client()
    signup(c, "a@b.co")
    r = post(c, "/dashboard/requests/1;drop table x/approve")
    assert r.status_code in (303, 404)


@pytest.mark.parametrize("anon,service", [("sb_secret_abc", "sb_secret_other"), ("same-key", "same-key")])
def test_secret_key_in_public_slot_keeps_accounts_off(anon, service):
    from reloop.config import Settings
    s = Settings(supabase_url="https://x.supabase.co", supabase_anon_key=anon, supabase_service_role_key=service)
    assert s.accounts_ready is False and s.integration_status()["anon_key_misconfigured"] is True
    ok = Settings(supabase_url="https://x.supabase.co", supabase_anon_key="sb_publishable_abc", supabase_service_role_key="sb_secret_x")
    assert ok.accounts_ready is True and ok.integration_status()["anon_key_misconfigured"] is False
