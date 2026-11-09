"""Keyboard-operable naming coverage and read-only retirement review in Navigator."""

from argparse import ArgumentParser
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import expect, sync_playwright

from patrol_browser import navigator
from test_navigator_context import fingerprint
from test_navigator_registry import sample_image
from test_navigator_stewardship import MOON, PROMPT, audit, cbos_profile


def run(browser, base):
    source = base / "Project evidence"
    source.mkdir()
    sample_image(source / MOON, "blue", created="2026-11-06")
    sample_image(source / "Heartfield Desk.png", "pink")
    sample_image(source / "Musicstone Badge.png", "red")
    history = source / "Heartfield Desk history.md"
    history.write_text("An earlier use of Heartfield Desk.png", encoding="utf-8")
    config = base / "Naming profile.json"
    config.write_text(json.dumps(cbos_profile()), encoding="utf-8")
    evidence = base / "Naming audit.json"
    evidence.write_text(json.dumps(audit()), encoding="utf-8")
    before = fingerprint(source)
    errors = []
    with navigator(base / "Review data", None) as server:
        page = browser.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(server.url)
        page.get_by_label("Keep a local checkpoint", exact=False).check()
        page.get_by_label("Suggest names and draft a plan", exact=True).check()
        page.get_by_label("Folder or shortcut path").fill(str(source))
        page.get_by_role("button", name="Inspect selection").click()
        expect(page.locator('[data-count="analyzed"]')).to_have_text("3")
        page.get_by_text("Project registry and validated naming", exact=True).click()
        page.get_by_label("Project profile JSON").set_input_files(config)
        page.get_by_role("button", name="Use this profile in this folder").click()
        expect(page.locator("#registry-status")).to_contain_text("1 validated naming rules")
        summary = page.get_by_text("Naming coverage and proof", exact=True)
        summary.focus()
        summary.press("Enter")
        page.get_by_label("Naming audit JSON").set_input_files(evidence)
        page.get_by_role("button", name="Load naming evidence").click()
        expect(page.locator("#naming-audit-status")).to_contain_text("14 subject and asset-family combinations")
        expect(page.locator("#naming-audit-results")).to_contain_text("Moonstone · Character Reference · verified filename exemplar")
        expect(page.locator("#naming-audit-results")).to_contain_text("Musicstone · Badge · candidate")
        page.locator(".journey-tools").get_by_role("button", name="Destination", exact=True).click()
        page.get_by_label("Why this matters", exact=True).fill("Keep the history of the retired design.")
        page.get_by_role("button", name="Save Destination", exact=True).click()
        page.get_by_role("button", name="Open Review", exact=True).click()
        summary = page.get_by_text("Talk to Journey about retirement", exact=True)
        summary.focus()
        summary.press("Enter")
        page.get_by_label("Stewardship instruction", exact=True).fill(PROMPT)
        page.get_by_label("Read scoped documentation and configuration references").check()
        page.get_by_role("button", name="Inspect instruction").click()
        results = page.locator("#stewardship-results")
        expect(results).to_contain_text("Heartfield Desk history.md")
        expect(results).to_contain_text("documentation")
        expect(results.get_by_role("checkbox")).to_have_count(1)
        results.get_by_role("checkbox").check()
        page.get_by_label("Reason for retirement").fill("Superseded by the current desk system.")
        page.get_by_role("button", name="Record selected retirements").click()
        expect(page.locator("#stewardship-status")).to_contain_text("Recorded 1 selected retirements")
        assert fingerprint(source) == before
        assert history.is_file()
        assert not errors, errors
        page.close()
    print("Stewardship browser acceptance passed: keyboard disclosure, audit proof, natural language and retirement history.")


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--browser")
    args = parser.parse_args()
    with TemporaryDirectory(prefix="journey-stewardship-browser-") as temp, sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.browser)
        try:
            run(browser, Path(temp).resolve())
        finally:
            browser.close()
