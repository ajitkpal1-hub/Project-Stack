"""Management dashboard: anonymous usage counts and the reporting migration. No network."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reloop.database.supabase import SupabaseError
from reloop.models.categories import WasteCategory
from reloop.routes import deps
from reloop.routes import scan as scan_route
from reloop.routes import voice as voice_route
from reloop.services.usage import MemoryUsage, SupabaseUsage, clean_area
from reloop.web import create_app
from tests.test_scan import _ai, make_image

MIGRATION = (Path(__file__).resolve().parent.parent / "supabase" / "migrations" / "0006_reporting.sql").read_text(encoding="utf-8")


class RealClassifier:
    """Like Claude: not demo, so its scans count as real usage."""

    is_demo = False

    def classify(self, image, note=None, filename=None):
        return _ai()

    def describe(self, description):
        return _ai()


@pytest.fixture
def usage():
    recorder = MemoryUsage()
    deps._usage_override = recorder
    yield recorder
    deps._usage_override = None
    scan_route._classifier_override = None
    voice_route._classifier_override = None


def scan(client, area=""):
    return client.post("/scan", files={"photo": ("item.jpg", make_image(), "image/jpeg")}, data={"note": "", "area": area})


# ---------- recording ----------

def test_scan_records_lane_and_area(usage):
    scan_route._classifier_override = RealClassifier()
    assert scan(TestClient(create_app()), area="thakurli").status_code == 200
    assert usage.events == [("web_scan", _ai().primary_category.value, "thakurli")]


@pytest.mark.parametrize("given", ["", "mumbai", "<script>", "DOMBIVLI "])
def test_area_is_cleaned(usage, given):
    scan_route._classifier_override = RealClassifier()
    scan(TestClient(create_app()), area=given)
    assert usage.events[0][2] == ("dombivli" if given.strip().lower() == "dombivli" else "not_given")


def test_demo_scans_are_not_counted(usage):
    from reloop.services.classifier import MockClassifier

    scan_route._classifier_override = MockClassifier()
    scan(TestClient(create_app()), area="kalyan")
    assert usage.events == []


def test_condition_replan_is_not_a_new_classification(usage):
    from reloop.agents.pipeline import WastePipeline

    scan_route._classifier_override = RealClassifier()
    previous = WastePipeline(RealClassifier()).run_description("chair")
    TestClient(create_app()).post("/scan/condition", data={"pipeline_json": previous.model_dump_json(), "condition": "works_clean"})
    assert usage.events == []


def test_voice_classify_is_counted(usage, monkeypatch):
    secret = "test-voice-secret-0123456789abcdefghij"
    monkeypatch.setenv("VOICE_TOOL_SECRET", secret)
    from reloop.config import get_settings

    get_settings.cache_clear()
    voice_route._classifier_override = RealClassifier()
    r = TestClient(create_app()).post("/api/voice/classify", json={"description": "old chair"},
                                      headers={"X-Reloop-Voice-Key": secret})
    assert r.status_code == 200
    assert usage.events == [("voice", _ai().primary_category.value, "not_given")]


def test_recording_failure_never_breaks_anything():
    class Broken:
        def rest(self, *a, **k):
            raise SupabaseError("down")

    SupabaseUsage(Broken()).record("web_scan", WasteCategory.DRY, "kalyan")  # no exception
    SupabaseUsage(Broken()).record("web_scan", "not-a-lane", "kalyan")  # bad lane: ignored


def test_recorder_sends_only_counts():
    sent = {}

    class Fake:
        def rest(self, method, path, **kw):
            sent.update(kw["json"], path=path)

    SupabaseUsage(Fake()).record("web_scan", WasteCategory.HAZARDOUS, "dombivli")
    assert sent == {"channel": "web_scan", "lane": "hazardous", "area": "dombivli", "path": "/usage_events"}


def test_clean_area():
    assert clean_area("Kalyan") == "kalyan" and clean_area(None) == "not_given" and clean_area("pune") == "not_given"


# ---------- pages ----------

def test_scan_page_asks_area_optionally():
    html = TestClient(create_app()).get("/scan").text
    assert '<select name="area">' in html and "Prefer not to say" in html
    for label in ("Dombivli", "Thakurli", "Kalyan", "Somewhere else"):
        assert label in html


def test_homepage_does_not_ask_area():
    assert 'name="area"' not in TestClient(create_app()).get("/").text


# ---------- the migration ----------

def test_migration_never_contains_a_password():
    assert not re.search(r"password\s+'", MIGRATION, re.IGNORECASE)
    assert "create role reloop_reporting nologin" in MIGRATION


def test_usage_table_is_server_only_and_holds_no_personal_data():
    table = MIGRATION.split("create table if not exists public.usage_events (")[1].split(");")[0]
    columns = {line.strip().split()[0] for line in table.strip().splitlines() if line.strip()}
    assert columns == {"id", "created_at", "channel", "lane", "area"}
    assert "alter table public.usage_events enable row level security" in MIGRATION
    assert "create policy" not in MIGRATION  # nobody but the service role can read or write it


def test_reporting_role_reads_only_the_weekly_views():
    grants = [line for line in MIGRATION.splitlines() if line.startswith("grant ") and "reloop_reporting" in line]
    assert any("weekly_donations, reporting.weekly_classifications, reporting.weekly_summary" in g for g in grants)
    assert not any("public." in g for g in grants)  # never the raw tables
    assert "revoke all on reporting.area_pins from reloop_reporting" in MIGRATION


def test_views_expose_counts_not_personal_details():
    views = MIGRATION.split("create or replace view")[1:]
    for view in views:
        body = view.split(";")[0].lower()
        for private in ("donor_id", "description", "phone", "email", "title", "photo", "contact"):
            assert private not in body, private


def test_area_function_is_safe_security_definer():
    fn = MIGRATION.split("create or replace function reporting.area_of")[1].split("$$;")[0]
    assert "security definer" in fn and "set search_path = reporting, pg_temp" in fn
    assert fn.index("thakurli") < fn.index("dombivli")  # "Thakurli, Dombivli East" counts as Thakurli
