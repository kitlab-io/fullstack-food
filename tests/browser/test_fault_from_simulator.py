"""Browser test: break a sensor from the simulator page, see it on the overview, follow the
link to the guide, then fix it. Same setup as test_mushroom_grow.py; this file runs first
because the other one ends the planting.
"""

import os

import pytest

URL = os.environ.get("FSF_BROWSER_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set FSF_BROWSER_URL to a running mock stack (mushrooms site)")


def test_a_fault_from_the_simulator_page_shows_up_and_leads_to_its_guide():
    sync_api = pytest.importorskip("playwright.sync_api")
    expect = sync_api.expect
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.environ.get("FSF_BROWSER_CHANNEL") or None)
        page = browser.new_page()
        page.set_default_timeout(20000)
        page.goto(URL)
        if page.get_by_role("heading", name="Log in").is_visible():
            page.get_by_label("Your name").fill("tester")
            page.get_by_label("Password").fill(os.environ.get("FSF_BROWSER_PASSWORD", "browser-test"))
            page.get_by_role("button", name="Log in").click()

        page.get_by_role("link", name="Simulator").click()
        expect(page.get_by_text("This site is simulated")).to_be_visible()
        page.get_by_role("button", name="10 min per second").click()
        row = page.locator("li", has_text="inc-air")
        row.get_by_role("button", name="Stop reporting").click()
        expect(page.get_by_role("status").filter(has_text="inc-air stopped reporting.")).to_be_visible()
        expect(page.get_by_text("1 active")).to_be_visible()

        # ten simulated minutes later the hub gives up on the reading
        page.get_by_role("link", name="Zones").click()
        card = page.locator("article", has_text="incubation-chamber")
        expect(card).to_contain_text("Sensor not reporting", timeout=30000)
        card.get_by_role("link", name="What to check").first.click()
        expect(page.get_by_role("heading", name="What the hub is doing")).to_be_visible()
        expect(page.get_by_text("Switching off every loop that depends on the missing reading")).to_be_visible()

        # the documented fix: the sensor reports again and the status clears
        page.get_by_role("link", name="Simulator").click()
        page.get_by_role("button", name="Remove all faults").click()
        expect(page.get_by_text("0 active")).to_be_visible()
        page.get_by_role("link", name="Zones").click()
        expect(page.locator("article", has_text="incubation-chamber")).not_to_contain_text("Sensor not reporting", timeout=30000)
        browser.close()
