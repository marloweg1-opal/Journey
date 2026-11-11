"""Exercise the installed Navigator against a private-data-free project."""

from pathlib import Path
import os

from playwright.sync_api import expect, sync_playwright

from tools.demo_integrated_pilot import make_demo


def exercise(url, base):
    collection, exports, pack = make_demo(base)
    with sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True, executable_path=os.environ.get("JOURNEY_TEST_BROWSER"))
        page = browser.new_page(viewport={"width": 960, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url)
        page.get_by_label("Keep a local checkpoint", exact=False).check()
        page.get_by_label("Suggest names and draft a plan", exact=True).check()
        page.get_by_label("Folder or shortcut path").fill(str(collection))
        page.get_by_role("button", name="Inspect selection", exact=True).click()
        expect(page.locator('[data-count="analyzed"]')).to_have_text("3", timeout=30000)
        panel = page.locator("[data-image]").filter(has=page.get_by_role("heading", name="render_a.png", exact=True))
        expect(panel).to_contain_text("Purpose open")
        page.get_by_text("Project registry and validated naming", exact=True).click()
        page.get_by_label("Local project pack or evidence ZIP path").fill(str(pack))
        page.get_by_role("button", name="Preview project pack", exact=True).click()
        page.get_by_role("button", name="Activate Studio Fixture for this scope", exact=True).click()
        page.get_by_text("Local reference history", exact=True).click()
        expect(page.locator("#history-status")).to_contain_text("No local conversation archive")
        page.get_by_label("Local conversation export or folder path").fill(str(exports))
        page.get_by_role("button", name="Preview archive selection", exact=True).click()
        page.get_by_role("button", name="Import these reviewed exports", exact=True).click()
        expect(page.locator("#history-status")).to_contain_text("2 exports indexed · 3 distinct messages", timeout=30000)
        expect(panel).to_contain_text("CareRail UI / Design", timeout=30000)
        expect(page.locator("#history-files")).to_contain_text("overlapping assertions reused")
        page.get_by_text("Archive coverage and gaps", exact=True).click()
        page.get_by_role("button", name="Monitor this reviewed export folder", exact=True).click()
        expect(page.locator("#history-files")).to_contain_text("Export monitoring · watching")
        page.get_by_role("button", name="Stop export monitoring", exact=True).click()
        expect(page.locator("#history-files")).to_contain_text("Export monitoring · stopped")
        page.get_by_role("button", name="Compact list", exact=True).click()
        expect(page.locator("#inspect-results")).to_have_class("compact-layout")
        page.get_by_text("Opt-in drift watch", exact=True).click()
        page.get_by_role("button", name="Enable for this session", exact=True).click()
        expect(page.locator("#watch-status")).to_contain_text("watching")
        page.get_by_role("button", name="Stop drift watch", exact=True).click()
        expect(page.locator("#watch-status")).to_contain_text("off")
        page.locator(".journey-tools").get_by_role("button", name="Destination", exact=True).click()
        page.get_by_label("Why this matters", exact=True).fill("Reopen and understand the collection without sorting by hand.")
        page.get_by_role("button", name="Save Destination", exact=True).click()
        page.get_by_role("button", name="Open Review", exact=True).click()
        page.get_by_text("Talk to Journey about your work", exact=True).click()
        goal = page.get_by_label("Stewardship instruction")
        goal.fill("Find render_a.png")
        page.get_by_role("button", name="Inspect instruction", exact=True).click()
        expect(page.locator("#stewardship-results")).to_contain_text("LOCAL REFERENCE HISTORY")
        goal.fill("Organize the selected folder.")
        page.get_by_role("button", name="Inspect instruction", exact=True).click()
        page.get_by_role("button", name="Start this scoped plan", exact=True).click()
        expect(page.locator("#patrol-collections")).to_contain_text("CareRail UI / Design", timeout=30000)
        expect(page.locator("#patrol-work")).to_contain_text("reference name matches", timeout=30000)
        if screenshot := os.environ.get("JOURNEY_INTEGRATED_SCREENSHOT"):
            page.screenshot(path=Path(screenshot))
        assert not errors, errors
        browser.close()
    print("Installed-browser flow passed: pack, explicit archive grant, dedupe, changed assessment, Find, Patrol and opt-in watch.")
