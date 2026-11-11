"""Exercise the project's normal Navigator browser flow with generated images."""

from argparse import ArgumentParser
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import expect, sync_playwright

from patrol_browser import navigator
from test_navigator_context import fingerprint
from test_navigator_registry import CANONICAL, ORIGINAL, profile, sample_image, write_archive


def run(browser, base):
    source = base / "Studio images"
    source.mkdir()
    sample_image(source / ORIGINAL, "purple")
    sample_image(source / "Other.png", "green")
    archive = base / "Conversation export.json"
    write_archive(archive)
    config = base / "Project profile.json"
    config.write_text(json.dumps(profile()), encoding="utf-8")
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
        expect(page.locator('[data-count="analyzed"]')).to_have_text("2")
        page.get_by_text("Project registry and validated naming", exact=True).click()
        registry = page.locator("#inspect-registry")
        registry.get_by_label("Project profile JSON").set_input_files(config)
        expect(registry.locator("#registry-file-preview")).to_contain_text("06_11")
        registry.get_by_role("button", name="Use this profile in this folder").click()
        expect(registry.locator("#registry-status")).to_contain_text("1 validated naming rules")
        registry.get_by_label("Full local path to a conversation export", exact=False).fill(str(archive))
        registry.get_by_role("button", name="Import selected evidence file").click()
        expect(registry.locator("#registry-status")).to_contain_text("6 evidence records")
        expect(registry.locator("#registry-results")).to_contain_text("referenced not located")
        image = page.locator("article").filter(has=page.get_by_role("heading", name=ORIGINAL, exact=True))
        image.get_by_text("Record a correction", exact=True).click()
        image.get_by_label("Identity", exact=True).fill("Moonstone")
        image.get_by_label("Purpose", exact=True).fill("Character Reference")
        image.get_by_role("button", name="Save correction", exact=True).click()
        expect(image).to_contain_text("human confirmed identity")
        image.get_by_text("Image details · created Unknown", exact=True).click()
        expect(image.get_by_text("00_00 date placeholder", exact=False)).to_be_visible()
        image.get_by_role("button", name="Confirm 2026-11-06 for this image").click()
        expect(image.get_by_text("Image details · created 2026-11-06", exact=True)).to_be_visible()
        image.get_by_text("Evidence and naming preview", exact=True).click()
        expect(image.get_by_text("Destination preview", exact=False)).to_contain_text(CANONICAL)
        page.locator(".journey-tools").get_by_role("button", name="Destination", exact=True).click()
        page.get_by_label("Why this matters", exact=True).fill("Retrieve the correct image by its dated name.")
        page.get_by_role("button", name="Save Destination", exact=True).click()
        page.get_by_role("button", name="Open Review", exact=True).click()
        expect(page.locator("#patrol-names")).to_contain_text(CANONICAL)
        page.locator("#patrol-names").get_by_role("checkbox").check()
        page.get_by_role("button", name="Review selected naming changes", exact=True).click()
        expect(page.locator("#patrol-batch-details")).to_contain_text("review_required")
        expect(page.locator("#patrol-batch-details")).to_contain_text(CANONICAL)
        assert fingerprint(source) == before, "Inspection or exact batch preparation changed a source."
        assert not errors, errors
        page.close()
    print("Registry browser acceptance: profile, native export, date provenance and exact read-only review passed.")


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--browser", help="Optional local Chromium executable")
    args = parser.parse_args()
    with TemporaryDirectory(prefix="journey-registry-browser-") as temporary, sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.browser)
        try:
            run(browser, Path(temporary).resolve())
        finally:
            browser.close()
