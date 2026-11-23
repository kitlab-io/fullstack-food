"""Browser test: drive a whole mushroom grow through the dashboard, as a person would.

Needs the mock stack running the mushrooms site with the login switched on, and Playwright:

    pip install playwright            # plus `playwright install chromium`, or use an installed browser:
    export FSF_BROWSER_CHANNEL=msedge
    export FSF_WEB_NO_LOGIN=0 FSF_WEB_PASSWORD_HASH=$(python -c "from fsf_web.auth import hash_password; print(hash_password('browser-test'))")
    FSF_SITE=mushrooms FSF_SPEED=600 docker compose -f deploy/compose/base.yaml -f deploy/compose/mock.yaml up -d --build
    FSF_BROWSER_URL=http://localhost:8080 FSF_BROWSER_PASSWORD=browser-test pytest tests/browser

Skipped when FSF_BROWSER_URL is not set. Start from a fresh stack: the test advances the
planting to its end.
"""

import os
import re

import pytest

URL = os.environ.get("FSF_BROWSER_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set FSF_BROWSER_URL to a running mock stack (mushrooms site)")


@pytest.fixture
def page():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.environ.get("FSF_BROWSER_CHANNEL") or None)
        page = browser.new_page()
        page.set_default_timeout(15000)
        yield page
        browser.close()


def confirm(page, button: str, expect_in_dialog: str | None = None):
    dialog = page.locator("dialog[open]")
    dialog.wait_for()
    if expect_in_dialog:
        assert expect_in_dialog in " ".join(dialog.inner_text().split())
    dialog.get_by_role("button", name=button, exact=True).click()


def test_a_mushroom_grow_from_incubation_to_harvest(page):
    from playwright.sync_api import expect

    page.goto(URL)
    # -- the login guards everything
    expect(page.get_by_role("heading", name="Log in")).to_be_visible()
    page.get_by_label("Your name").fill("tester")
    page.get_by_label("Password").fill("definitely wrong")
    page.get_by_role("button", name="Log in").click()
    expect(page.get_by_role("alert")).to_have_text("wrong password")
    page.get_by_label("Password").fill(os.environ.get("FSF_BROWSER_PASSWORD", "browser-test"))
    page.get_by_role("button", name="Log in").click()

    # -- overview: both chambers, the planting in incubation
    incubation = page.locator("article", has_text="incubation-chamber")
    expect(incubation).to_contain_text("Blue oyster mushroom")
    expect(incubation).to_contain_text("Incubation")
    expect(page.locator("article", has_text="fruiting-chamber")).to_contain_text("Nothing planted here")

    # -- incubation -> fruiting: the confirmation names the zone it moves to
    incubation.get_by_role("link", name="incubation-chamber").click()
    page.get_by_role("button", name="Advance to fruiting").click()
    confirm(page, "Advance", expect_in_dialog="moves to fruiting-chamber")
    expect(page.get_by_role("status").filter(has_text="Moved to stage fruiting")).to_be_visible()
    expect(page.get_by_text("Nothing planted here")).to_be_visible()

    page.goto(f"{URL}/#/zones/fruiting-chamber")
    expect(page.locator("li[aria-current='step']")).to_have_text("Fruiting")
    expect(page.locator("figure", has_text="Humidity").first).to_be_visible()      # the fruiting stage's charts

    # -- pause and resume
    page.get_by_role("button", name="Pause zone").click()
    confirm(page, "Pause", expect_in_dialog="switched off and stays off")
    expect(page.get_by_text("Paused until someone resumes it.")).to_be_visible()
    expect(page.get_by_role("button", name="Resume zone")).to_be_visible()
    page.get_by_role("button", name="Resume zone").click()
    expect(page.get_by_role("status").filter(has_text="Resumed.")).to_be_visible()

    # -- a temporary target override, then back to the recipe
    page.get_by_role("button", name="Override a target").click()
    page.locator("dialog[open]").get_by_label("Quantity").select_option("air_temperature")
    page.locator("dialog[open]").get_by_label("Target").fill("17")
    confirm(page, "Override")
    expect(page.get_by_role("status").filter(has_text="Air temperature overridden for 4h.")).to_be_visible()
    expect(page.get_by_text("overridden").first).to_be_visible()
    page.get_by_role("button", name="Clear overrides").click()
    expect(page.get_by_role("status").filter(has_text="Overrides cleared")).to_be_visible()

    # -- a refusal from the hub is shown as it is
    page.get_by_role("button", name="Override a target").click()
    page.locator("dialog[open]").get_by_label("Quantity").select_option("air_temperature")
    page.locator("dialog[open]").get_by_label("Target").fill("99")
    confirm(page, "Override")
    expect(page.get_by_role("status").filter(has_text=re.compile("The hub refused: .*inconsistent band"))).to_be_visible()

    # -- a test pulse from the devices page
    page.get_by_role("link", name="Devices").click()
    page.locator(".tr", has_text="fr-fan").get_by_role("button", name="Test pulse").click()
    confirm(page, "Switch on for 2 s", expect_in_dialog="fr-fan")
    expect(page.get_by_text("Pulsed for 2 s.")).to_be_visible()

    # -- fruiting -> harvest -> finished
    page.goto(f"{URL}/#/zones/fruiting-chamber")
    page.get_by_role("button", name="Advance to harvest").click()
    confirm(page, "Advance")
    expect(page.locator("li[aria-current='step']")).to_have_text("Harvest")
    page.get_by_role("button", name="Finish planting").click()
    confirm(page, "Finish", expect_in_dialog="fruiting-chamber is freed")
    expect(page.get_by_role("status").filter(has_text="Planting finished; the zone is free.")).to_be_visible()
    expect(page.get_by_text("Nothing planted here")).to_be_visible()

    # -- everything that was done is in the log with who did it
    page.get_by_role("link", name="Log", exact=True).click()
    page.get_by_label("Kind").select_option("command")
    log = page.get_by_role("list", name="Log entries")
    expect(log).to_contain_text("advance_stage accepted from dashboard:tester")
    expect(log).to_contain_text("set_override rejected")
    expect(log).to_contain_text("test pulse on fr-fan for 2 s")

    # -- and logging out closes the door again
    page.get_by_role("button", name="Log out").click()
    expect(page.get_by_role("heading", name="Log in")).to_be_visible()
