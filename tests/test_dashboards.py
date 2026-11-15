"""Phase 8: saved scans and answers, AI-answer reports, totals and the admin overview. All storage is faked."""

from __future__ import annotations

import html as html_lib
import re
import uuid

import pytest
from fastapi.testclient import TestClient

from reloop.agents.pipeline import WastePipeline
from reloop.config import get_settings
from reloop.database.memory import InMemoryDashboardRepo, InMemoryDonationRepo, InMemoryPartnerRepo
from reloop.models.dashboards import FlagStatus, KnowledgeDoc
from reloop.models.donations import ListingStatus, User
from reloop.rag.answer import KnowledgeAssistant
from reloop.rag.embeddings import HashEmbedder
from reloop.routes import assistant as assistant_route
from reloop.routes import deps
from reloop.routes import scan as scan_route
from reloop.services.classifier import MockClassifier
from reloop.services.dashboards import DashboardError, DashboardService, answer_summary, parse_payload, user_stats
from reloop.services.donations import DonationService
from reloop.utils.images import prepare_image
from reloop.web import create_app
from tests.test_donations import ADMIN_EMAIL, FakeAuth, form, post, signup
from tests.test_rag import SETTINGS, CitingGenerator, loaded_store
from tests.test_scan import make_image, post_photo

USER = User(id=str(uuid.uuid4()), email="u@x.test")
OTHER = User(id=str(uuid.uuid4()), email="o@x.test")
ADMIN = User(id=str(uuid.uuid4()), email=ADMIN_EMAIL, is_admin=True)


def scan_payload(filename="chair.jpg") -> str:
    return WastePipeline(MockClassifier()).run(prepare_image(make_image(), "image/jpeg"), filename=filename).model_dump_json()


def answer_payload() -> str:
    assistant = KnowledgeAssistant(loaded_store(), HashEmbedder(), CitingGenerator(), SETTINGS)
    return assistant.answer("How do I get rid of old batteries?").model_dump_json()


# ---------- summaries ----------

def test_scan_summary_is_compact_text_only():
    kind, title, lane, summary = parse_payload("scan", scan_payload())
    assert kind.value == "scan" and title and lane
    assert set(summary) == {"item", "lane", "certainty", "action", "advice", "steps", "warnings", "options", "demo"}
    assert summary["demo"] is True and len(summary["steps"]) <= 5
    assert "data:image" not in str(summary)


def test_answer_summary_keeps_sources_and_drops_bad_links():
    from reloop.models.knowledge import Answer
    answer = Answer.model_validate_json(answer_payload())
    answer.sources[0].source_url = "javascript:alert(1)"
    _, summary = answer_summary(answer)
    assert summary["question"].startswith("How do I")
    assert summary["sources"] and summary["sources"][0]["url"] is None


@pytest.mark.parametrize("kind,payload", [("scan", "{}"), ("scan", "not json"), ("answer", '{"bad": 1}'), ("photo", "{}")])
def test_tampered_or_unknown_payloads_are_refused(kind, payload):
    with pytest.raises(DashboardError):
        parse_payload(kind, payload)


# ---------- saving ----------

def test_save_list_and_delete_only_own():
    svc = DashboardService(InMemoryDashboardRepo())
    item = svc.save(USER, "t", "scan", scan_payload())
    assert [i.id for i in svc.saved(USER, "t")] == [item.id]
    assert svc.saved(OTHER, "t") == []
    svc.delete(OTHER, "t", item.id)  # someone else's item: nothing happens
    assert len(svc.saved(USER, "t")) == 1
    svc.delete(USER, "t", item.id)
    assert svc.saved(USER, "t") == []


def test_saved_items_are_capped():
    repo = InMemoryDashboardRepo()
    svc = DashboardService(repo)
    payload = answer_payload()
    for _ in range(50):
        svc.save(USER, "t", "answer", payload)
    with pytest.raises(DashboardError, match="50 items"):
        svc.save(USER, "t", "answer", payload)


# ---------- reports ----------

def test_reports_from_anyone_and_validation():
    repo = InMemoryDashboardRepo()
    svc = DashboardService(repo)
    svc.report(None, "scan", "wrong_lane", "This is a CFL, so hazardous", scan_payload("bottle.jpg"))
    svc.report(USER, "answer", "wrong_source", "x" * 900, answer_payload())
    flags = repo.flags("open")
    assert len(flags) == 2 and {f.reporter_id for f in flags} == {None, USER.id}
    assert all(len(f.note) <= 500 for f in flags) and all(f.snapshot.get("title") for f in flags)
    with pytest.raises(DashboardError, match="choose"):
        svc.report(None, "scan", "because", "", scan_payload())


def test_only_admins_review_reports_and_documents():
    repo = InMemoryDashboardRepo()
    svc = DashboardService(repo)
    svc.report(None, "scan", "unsafe", "", scan_payload())
    for action in (lambda: svc.open_flags(USER), lambda: svc.overview(USER), lambda: svc.documents(USER)):
        with pytest.raises(DashboardError, match="Only RELOOP admins"):
            action()
    flag = svc.open_flags(ADMIN)[0]
    svc.resolve(ADMIN, flag.id, "Adjusted the prompt for CFL bulbs")
    assert repo.get_flag(flag.id).status == FlagStatus.RESOLVED
    with pytest.raises(DashboardError, match="already closed"):
        svc.resolve(ADMIN, flag.id, "again")


def test_archive_and_restore_documents():
    repo = InMemoryDashboardRepo()
    repo.docs["d1"] = KnowledgeDoc(id="d1", title="E-Waste Rules (fixture)", chunk_count=58)
    svc = DashboardService(repo)
    svc.set_document(ADMIN, "d1", active=False)
    assert repo.docs["d1"].status == "archived"
    svc.set_document(ADMIN, "d1", active=True)
    assert repo.docs["d1"].status == "active"
    with pytest.raises(DashboardError):
        svc.set_document(ADMIN, "missing", active=False)


# ---------- totals ----------

def test_user_totals_are_plain_counts():
    drepo = InMemoryDonationRepo()
    dsvc = DonationService(drepo)
    donor, asker = User(id=str(uuid.uuid4()), email="d@x.test"), User(id=str(uuid.uuid4()), email="a@x.test")
    a = dsvc.create_listing(donor, "t", form(title="Table"), None)
    b = dsvc.create_listing(donor, "t", form(title="Chair"), None)
    dsvc.create_listing(donor, "t", form(title="Lamp"), None)  # stays pending
    for x in (a, b):
        dsvc.admin_approve(ADMIN, x.id)
    req = dsvc.request_item(asker, "t", a.id, "")
    dsvc.approve_request(donor, req.id)
    dsvc.complete_listing(donor, a.id)
    assert user_stats(dsvc.dashboard(donor, "t")).model_dump() == {"given_away": 1, "listed_now": 1, "waiting_review": 1, "received": 0}
    assert user_stats(dsvc.dashboard(asker, "t")).received == 1


def test_admin_overview_counts():
    drepo, prepo = InMemoryDonationRepo(), InMemoryPartnerRepo()
    repo = InMemoryDashboardRepo(drepo, prepo)
    repo.members = 7
    dsvc = DonationService(drepo)
    donor = User(id=str(uuid.uuid4()), email="d@x.test")
    dsvc.create_listing(donor, "t", form(), None)
    approved = dsvc.create_listing(donor, "t", form(title="Bookshelf"), None)
    dsvc.admin_approve(ADMIN, approved.id)
    repo.docs["d1"] = KnowledgeDoc(id="d1", title="Rules")
    stats = DashboardService(repo).overview(ADMIN)
    assert (stats.listings_pending, stats.listings_public, stats.documents_active, stats.members) == (1, 1, 1, 7)


# ---------- pages ----------

@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", ADMIN_EMAIL)
    get_settings.cache_clear()
    auth, drepo, prepo = FakeAuth(), InMemoryDonationRepo(), InMemoryPartnerRepo()
    dash = InMemoryDashboardRepo(drepo, prepo)
    deps._auth_override, deps._repo_override, deps._partner_repo_override, deps._dash_repo_override = auth, drepo, prepo, dash
    scan_route._classifier_override = MockClassifier()
    deps._VERIFIED.clear()
    yield dash, drepo
    deps._auth_override = deps._repo_override = deps._partner_repo_override = deps._dash_repo_override = None
    scan_route._classifier_override = None
    assistant_route._assistant_override = None
    deps._VERIFIED.clear()


def hidden(page: str, name: str) -> str:
    return html_lib.unescape(re.search(rf'name="{name}" value="([^"]*)"', page).group(1))


def test_save_scan_from_result_page_then_delete(env):
    dash, _ = env
    c = TestClient(create_app())
    signup(c, "u@x.test")
    page = post_photo(c, "old-charger.jpg").text
    assert "Save to my dashboard" in page and "Report a problem" in page
    r = c.post("/saved", data={"kind": "scan", "payload": hidden(page, "payload"), "csrf_token": c.cookies.get("rl_csrf")},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/dashboard#saved"
    board = c.get("/dashboard").text
    assert "Saved scans and answers" in board and "Mobile phone charger" in board and "demo sample" in board
    item = next(iter(dash.saved.values()))
    post(c, f"/saved/{item.id}/delete")
    assert dash.saved == {}


def test_signed_out_visitors_see_login_to_save_but_can_report(env):
    dash, _ = env
    c = TestClient(create_app())
    page = post_photo(c, "bottle.jpg").text
    assert "Log in to save answers" in page and 'action="/saved"' not in page
    r = c.post("/report", data={"kind": "scan", "reason": "wrong_lane", "note": "It is glass", "payload": hidden(page, "payload"),
                                "csrf_token": c.cookies.get("rl_csrf")}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/scan"
    assert len(dash.flags("open")) == 1 and "Thank you" in c.get("/scan").text


def test_report_needs_csrf_and_valid_payload(env):
    dash, _ = env
    c = TestClient(create_app())
    c.get("/")
    assert c.post("/report", data={"kind": "scan", "reason": "unsafe", "payload": "{}"}).status_code == 403
    r = c.post("/report", data={"kind": "scan", "reason": "unsafe", "payload": "{}", "csrf_token": c.cookies.get("rl_csrf")})
    assert dash.flags("open") == [] and "Something went wrong" in r.text


def test_save_answer_from_assistant(env):
    dash, _ = env
    assistant_route._assistant_override = KnowledgeAssistant(loaded_store(), HashEmbedder(), CitingGenerator(), SETTINGS)
    c = TestClient(create_app())
    signup(c, "u@x.test")
    page = c.post("/assistant", data={"question": "How do I get rid of old batteries?"}).text
    r = c.post("/saved", data={"kind": "answer", "payload": hidden(page, "payload"), "csrf_token": c.cookies.get("rl_csrf")},
               follow_redirects=False)
    assert r.status_code == 303
    assert "How do I get rid of old batteries?" in c.get("/dashboard").text


def test_dashboard_shows_totals(env):
    _, drepo = env
    c = TestClient(create_app())
    signup(c, "u@x.test")
    uid = next(iter(deps._auth_override.users.values()))[0]
    DonationService(drepo).create_listing(User(id=uid, email="u@x.test"), "t", form(), None)
    board = c.get("/dashboard").text
    assert "Waiting for review" in board and "Items you gave away" in board
    assert "carbon" not in board.lower() and "CO2" not in board


def test_admin_overview_flags_and_knowledge_pages(env):
    dash, drepo = env
    dash.docs["d1"] = KnowledgeDoc(id="d1", title="Solid Waste Management Rules, 2026 (fixture)", chunk_count=208, source_url="https://example.org")
    dash.add_flag(*parse_payload("scan", scan_payload())[:1], "unsafe", "Wrong advice", {"title": "Plastic bottle", "lane": "dry",
                  "certainty": "clear", "advice": "Recycle it"}, None)
    member, admin = TestClient(create_app()), TestClient(create_app())
    signup(member, "m@x.test")
    for path in ["/admin", "/admin/flags", "/admin/knowledge", "/admin/listings"]:
        assert "only for RELOOP admins" in member.get(path).text, path
    post(member, "/admin/knowledge/d1/archive")
    assert dash.docs["d1"].status == "active"

    signup(admin, ADMIN_EMAIL)
    overview = admin.get("/admin").text
    assert "Needs your attention" in overview and "Reported AI answers" in overview and "no carbon" in overview
    flags = admin.get("/admin/flags").text
    assert "Plastic bottle" in flags and "Unsafe or risky advice" in flags
    flag_id = next(iter(dash.flag_rows))
    post(admin, f"/admin/flags/{flag_id}/resolve", admin_note="Checked, advice corrected")
    assert dash.flag_rows[flag_id].status == FlagStatus.RESOLVED
    assert "Solid Waste Management Rules" in admin.get("/admin/knowledge").text
    post(admin, "/admin/knowledge/d1/archive")
    assert dash.docs["d1"].status == "archived"
    r = post(admin, "/admin/knowledge/d1/delete")
    assert r.status_code == 303 and "d1" in dash.docs  # unknown action ignored


def test_admin_nav_and_listing_queue_moved(env):
    _, drepo = env
    admin = TestClient(create_app())
    signup(admin, ADMIN_EMAIL)
    listing = DonationService(drepo).create_listing(User(id=str(uuid.uuid4()), email="d@x.test"), "t", form(title="Old cycle"), None)
    page = admin.get("/admin/listings").text
    assert "Old cycle" in page and 'href="/admin/flags"' in page
    post(admin, f"/admin/listings/{listing.id}/approve")
    assert drepo.listings[listing.id].status == ListingStatus.AVAILABLE


def test_saved_text_is_escaped(env):
    dash, _ = env
    c = TestClient(create_app())
    signup(c, "u@x.test")
    uid = next(iter(deps._auth_override.users.values()))[0]
    dash.save_item(uid, parse_payload("scan", scan_payload())[0], "<script>alert(1)</script>", "dry",
                   {"advice": "<img src=x onerror=alert(1)>", "steps": [], "warnings": []}, "t")
    board = c.get("/dashboard").text
    assert "<script>alert(1)</script>" not in board and "<img src=x" not in board
