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
    with page.expect_navigation():  # choosing a photo starts the scan by itself
        page.set_input_files("form.chute input[name=photo]", str(photo))
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
    assert "script-src 'self'" in headers["content-security-policy"] and headers["x-frame-options"] == "DENY"
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    for path in ["/", "/scan", "/donations", "/centres"]:
        page.goto(f"{app.url}{path}")
    assert not [e for e in errors if "Content Security Policy" in e], errors  # the strict policy breaks nothing


def test_phone_shows_camera_and_upload_and_scans_straight_away(app, browser, tmp_path):
    photo = tmp_path / "bottle.jpg"
    photo.write_bytes(make_image())
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    try:
        page = ctx.new_page()
        page.goto(f"{app.url}/scan")
        camera = page.locator("form.chute input[name=camera]")
        assert camera.get_attribute("capture") == "environment" and camera.get_attribute("accept") == "image/*"
        assert page.is_visible("label.chute-pick--camera") and page.is_visible("label.chute-pick--upload")
        assert not page.is_visible("form.chute .chute-submit")  # no extra tap needed
        with page.expect_navigation():
            page.set_input_files("form.chute input[name=camera]", str(photo))
        assert page.is_visible("#result-title")
    finally:
        ctx.close()


def test_computer_shows_upload_only(app, new_page):
    page = new_page(1440)
    page.goto(f"{app.url}/scan")
    assert page.is_visible("label.chute-pick--upload") and not page.is_visible("label.chute-pick--camera")


def test_loading_card_shows_while_scanning_and_assistant_works(app, new_page, tmp_path):
    hold = "document.querySelectorAll('form').forEach(f => f.addEventListener('submit', e => e.preventDefault()))"
    photo = tmp_path / "bottle.jpg"
    photo.write_bytes(make_image())
    page = new_page(390)
    page.goto(f"{app.url}/scan")
    # keep the page here so the in-progress state can be checked (the scan form sends via form.submit())
    page.evaluate("() => { HTMLFormElement.prototype.submit = function () { document.body.dataset.submitted = '1'; }; }")
    page.set_input_files("form.chute input[name=photo]", str(photo))
    page.wait_for_selector(".loading:not([hidden])", timeout=3000)
    assert page.inner_text(".loading-title") == "Scanning your photo"
    assert page.inner_text(".loading-step") == "Uploading your photo…"
    page.wait_for_selector(".loading-step:has-text('Looking at the item')", timeout=5000)  # the message moves on
    assert page.evaluate("document.body.classList.contains('is-loading')")

    page.goto(f"{app.url}/assistant")
    page.evaluate(hold)
    page.fill("input[name=question]", "How do I get rid of paint?")
    page.click("form.ask-form button[type=submit] >> nth=0")
    page.wait_for_selector(".loading:not([hidden])", timeout=3000)
    assert page.inner_text(".loading-title") == "Finding your answer"
    page.click("form.ask-form button[type=submit] >> nth=0", force=True)  # a second tap is ignored
    assert page.locator(".loading").count() == 1

    page.goto(f"{app.url}/scan")  # a fresh page has no loading card showing
    assert not page.is_visible(".loading")



def _big_camera_photo(path):
    import io
    import os

    from PIL import Image
    img = Image.frombytes("RGB", (4000, 3000), os.urandom(4000 * 3000 * 3))  # noise: compresses badly, like a real photo
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    path.write_bytes(buf.getvalue())
    return len(buf.getvalue())


def test_big_phone_photo_is_shrunk_before_upload(app, browser, tmp_path):
    photo = tmp_path / "IMG_20261115_101500.jpg"
    size = _big_camera_photo(photo)
    assert size > 8 * 1024 * 1024  # bigger than the host's upload limit
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    try:
        page = ctx.new_page()
        page.goto(f"{app.url}/scan")
        page.evaluate("""() => { HTMLFormElement.prototype.submit = function () {
            var f = this.querySelector('input[name=camera]').files[0];
            document.body.dataset.sent = f.size + ' ' + f.type; }; }""")
        page.set_input_files("form.chute input[name=camera]", str(photo))
        page.wait_for_selector("body[data-sent]", timeout=15000)
        sent_size, sent_type = page.get_attribute("body", "data-sent").split()
        assert sent_type == "image/jpeg" and int(sent_size) < 1024 * 1024  # under 1 MB, far below the limit
    finally:
        ctx.close()


def test_big_phone_photo_scans_successfully(app, browser, tmp_path):
    photo = tmp_path / "IMG_20261115_101501.jpg"
    _big_camera_photo(photo)
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    try:
        page = ctx.new_page()
        page.goto(f"{app.url}/scan")
        with page.expect_navigation(timeout=30000):
            page.set_input_files("form.chute input[name=camera]", str(photo))
        assert page.is_visible("#result-title") and "larger than 4 MB" not in page.content()
    finally:
        ctx.close()
