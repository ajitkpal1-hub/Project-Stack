"""End-to-end journeys through the real pages, as a person would click them."""

from __future__ import annotations

from reloop.models.donations import ListingCondition, ListingForm, ProfileForm, User
from reloop.models.partners import OsmPlace, PartnerForm
from reloop.services.donations import DonationService
from tests.test_scan import make_image

PW = "correct-horse-1"


def login(page, base, email):
    page.goto(f"{base}/account/login")
    page.fill("input[name=email]", email)
    page.fill("input[name=password]", PW)
    page.click("form.form-stack button[type=submit]")
    page.wait_for_load_state("networkidle")


def no_sideways_scroll(page) -> bool:
    return not page.evaluate("document.documentElement.scrollWidth > window.innerWidth")


def test_scan_condition_then_sign_up_and_list_donation(app, new_page, tmp_path):
    photo = tmp_path / "chair.jpg"
    photo.write_bytes(make_image())
    page = new_page(390)
    page.goto(f"{app.url}/scan")
    page.set_input_files("form.chute input[type=file]", str(photo))
    page.click("form.chute button[type=submit]")
    page.wait_for_load_state("networkidle")
    assert "Demo mode" in page.content() and "what condition is it in" in page.content()
    page.click("details.trace summary")
    assert page.is_visible("text=Safety review")

    page.check("input[value=works_clean]")
    page.click("form.condition button[type=submit]")
    page.wait_for_load_state("networkidle")
    assert page.is_visible("text=It can be donated")
    with page.expect_navigation():
        page.click("a.btn:has-text('List it for donation')")
    assert page.is_visible("text=Log in to list an item")

    with page.expect_navigation():
        page.click(".action-row >> text=Create an account")
    page.fill("input[name=email]", "new.donor@example.com")
    page.fill("input[name=password]", PW)
    page.click("form.form-stack button[type=submit]")
    page.wait_for_load_state("networkidle")
    assert "/donate" in page.url  # back where they were, with the scan's details
    assert page.input_value("input[name=title]") and page.locator("select[name=category]").input_value()
    page.fill("input[name=locality]", "Thakurli East")
    page.fill("input[name=pin_code]", "421201")
    page.click("form.form-stack button[type=submit]")
    page.wait_for_load_state("networkidle")
    assert "/dashboard" in page.url and page.is_visible("text=Pending review")
    assert no_sideways_scroll(page)
    assert len(app.donations.listings) == 1


def test_admin_approves_member_requests_donor_approves(app, new_page):
    for email in ("donor@example.com", "asker@example.com", "admin@example.com"):
        app.auth.sign_up(email, PW)
    donor_id = app.auth.users["donor@example.com"][0]
    asker_id = app.auth.users["asker@example.com"][0]
    app.donations.save_profile(donor_id, ProfileForm(display_name="Asha", locality="Thakurli", pin_code="421201",
                                                     contact_note="WhatsApp 98xxxxxx10"), "t")
    app.donations.save_profile(asker_id, ProfileForm(display_name="Ravi", locality="Kalyan", pin_code="421301",
                                                     contact_note="Call after 6pm"), "t")
    DonationService(app.donations).create_listing(
        User(id=donor_id, email="donor@example.com"), "t",
        ListingForm(title="Children's story books", category="books", condition=ListingCondition.WORKS_CLEAN,
                    locality="Thakurli East", pin_code="421201"), None)

    admin = new_page(1440)
    login(admin, app.url, "admin@example.com")
    admin.goto(f"{app.url}/admin")
    assert admin.is_visible("text=Needs your attention")
    with admin.expect_navigation():
        admin.click(".admin-nav >> text=Listings")
    with admin.expect_navigation():
        admin.click("button:has-text('Approve')")
    assert admin.is_visible("text=Listing approved")

    asker = new_page(390)
    login(asker, app.url, "asker@example.com")
    asker.goto(f"{app.url}/donations")
    with asker.expect_navigation():
        asker.click("a:has-text(\"Children's story books\")")
    assert "WhatsApp" not in asker.content()
    asker.fill("textarea[name=message]", "For my daughter")
    with asker.expect_navigation():
        asker.click("button:has-text('Request this item')")
    assert asker.is_visible("text=Request sent")

    donor = new_page(1000)
    login(donor, app.url, "donor@example.com")
    donor.goto(f"{app.url}/dashboard")
    assert donor.is_visible("text=For my daughter") and "Call after 6pm" not in donor.content()
    with donor.expect_navigation():
        donor.click("form[action*='/approve'] button")
    assert donor.is_visible("text=Call after 6pm")

    asker.goto(f"{app.url}/dashboard")
    assert asker.is_visible("text=WhatsApp 98xxxxxx10")


def test_assistant_answer_report_and_admin_closes_it(app, new_page):
    from reloop.rag.answer import KnowledgeAssistant
    from reloop.rag.embeddings import HashEmbedder
    from reloop.routes import assistant as assistant_route
    from tests.test_rag import SETTINGS, CitingGenerator, loaded_store

    assistant_route._assistant_override = KnowledgeAssistant(loaded_store(), HashEmbedder(), CitingGenerator(), SETTINGS)
    app.auth.sign_up("admin@example.com", PW)
    page = new_page(390)
    page.goto(f"{app.url}/assistant")
    page.fill("input[name=question]", "How do I get rid of old batteries?")
    page.click("form.ask-form button[type=submit] >> nth=0")
    page.wait_for_load_state("networkidle")
    assert page.is_visible("text=Answered from")
    page.click("details.report summary")
    page.check("input[value=wrong_source]")
    page.fill("textarea[name=note]", "The rules page doesn't say this")
    page.click("text=Send report")
    page.wait_for_load_state("networkidle")
    assert page.is_visible("text=Our team will review that answer")

    admin = new_page(1000)
    login(admin, app.url, "admin@example.com")
    admin.goto(f"{app.url}/admin/flags")
    assert admin.is_visible("text=The rules page doesn't say this")
    admin.fill("input[name=admin_note]", "Checked the source")
    admin.click("text=Close report")
    admin.wait_for_load_state("networkidle")
    assert admin.is_visible("text=No open reports")


def test_centres_search_shows_verified_before_map_results(app, new_page):
    app.partners.insert_verified(PartnerForm(name="Ward Dry Waste Centre (test)", kind="collection_point", materials=["dry"],
                                             locality="Dombivli East", pin_code="421201", source_url="https://example.org/list",
                                             latitude=19.218, longitude=73.095))
    app.geo.places = [OsmPlace(osm_id="node/1", name="Map Recycling Point (test)", kind_label="Recycling point",
                               latitude=19.22, longitude=73.09, distance_km=0.8)]
    page = new_page(390)
    page.goto(f"{app.url}/centres")
    page.fill("input[name=place]", "421201")
    page.click("form.filter-bar button[type=submit]")
    page.wait_for_load_state("networkidle")
    html = page.content()
    assert html.index("Ward Dry Waste Centre (test)") < html.index("Map Recycling Point (test)")
    assert page.is_visible("text=Not verified") and page.is_visible("text=OpenStreetMap contributors")
    assert no_sideways_scroll(page)


def test_basic_accessibility_on_every_main_page(app, new_page):
    page = new_page(390)
    for path in ["/", "/scan", "/assistant", "/donate", "/donations", "/centres", "/account/login", "/account/signup"]:
        page.goto(f"{app.url}{path}")
        assert page.evaluate("document.documentElement.lang") == "en-IN", path
        assert page.locator("h1").count() == 1, path
        missing_alt = page.evaluate("[...document.images].filter(i => !i.hasAttribute('alt')).length")
        assert missing_alt == 0, path
        unlabelled = page.evaluate("""[...document.querySelectorAll('input:not([type=hidden]), select, textarea')]
            .filter(el => !(el.labels && el.labels.length) && !el.getAttribute('aria-label')).length""")
        assert unlabelled == 0, path
        assert no_sideways_scroll(page), path
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.className") == "skip", path  # skip link comes first


def test_security_headers_reach_the_browser(app, new_page):
    page = new_page()
    response = page.goto(f"{app.url}/")
    headers = response.headers
    assert "script-src 'none'" in headers["content-security-policy"] and headers["x-frame-options"] == "DENY"
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    for path in ["/", "/scan", "/donations", "/centres"]:
        page.goto(f"{app.url}{path}")
    assert not [e for e in errors if "Content Security Policy" in e], errors  # the strict policy breaks nothing
