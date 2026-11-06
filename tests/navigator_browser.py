"""Drive the packaged Navigator through a large, disposable project review."""

import argparse
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from playwright.sync_api import expect, sync_playwright

from journey_vision.demo import _icon, _portrait
from navigator_fixtures import make_link


ROOT = Path(__file__).resolve().parents[1]
FIRST = "01-Aster_20261018_142351_v02.png"
WRONG = "02-Lookalike.png"
LATER = "03-Later.png"


@contextmanager
def running_navigator(runtime, data, cwd):
    env = os.environ | {"PYTHONPATH": str(ROOT)}
    process = subprocess.Popen([str(runtime), "-B", "-m", "journey_navigator", "--no-browser", "--data-dir", str(data)],
                               cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        url = process.stdout.readline().strip()
        if not url.startswith("http://127.0.0.1:"):
            raise RuntimeError(f"Navigator failed to start: {process.stderr.read()}")
        yield url
    finally:
        if process.poll() is None:
            process.terminate()
        process.communicate(timeout=15)


def fingerprint(paths):
    return {path: (sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns) for path in paths}


def count(page, key):
    return int(page.locator(f'[data-count="{key}"]').inner_text().replace(",", ""))


def completed(page, files, images):
    expect(page.locator('[data-count="files"]')).to_have_text(f"{files:,}", timeout=90_000)
    expect(page.locator('[data-count="analyzed"]')).to_have_text(f"{images:,}", timeout=90_000)
    expect(page.locator("#inspect-progress")).to_contain_text("Finished inspecting", timeout=90_000)
    assert count(page, "files") == files, count(page, "files")
    assert count(page, "analyzed") == images, count(page, "analyzed")
    assert count(page, "pending") == count(page, "pending_folders") == 0


def select_link(page, folder, link):
    page.get_by_label("Folder or shortcut path").fill(str(folder))
    page.get_by_role("button", name="Browse folders", exact=True).click()
    page.get_by_role("button", name=f"Review {link.name}", exact=True).click()
    expect(page.locator("#inspect-approval")).to_contain_text(str(link))


def corrections(page, filename, decision, label, purpose=""):
    card = page.locator("[data-image]").filter(has=page.get_by_role("heading", name=filename, exact=True))
    card.get_by_text("Record a correction", exact=True).click()
    card.get_by_label("Decision").select_option(decision)
    card.get_by_label("Identity", exact=True).fill(label)
    if purpose:
        card.get_by_label("Purpose", exact=True).fill(purpose)
    card.get_by_role("button", name="Save correction").click()
    expect(page.locator("#inspect-notice")).to_contain_text("Correction saved")


def run(browser, runtime, base):
    fixture = base / "Fixture"
    fixture.mkdir()
    source = fixture / "Project Library"
    source.mkdir()
    artwork = source / "Nested Project" / "Design" / "Icons"
    artwork.mkdir(parents=True)
    bulk = source / "Workspace Notes"
    bulk.mkdir()
    initial = [source / FIRST, source / WRONG]
    _portrait(0).save(initial[0])
    _portrait(0, True).save(initial[1])
    for index in range(72):
        path = artwork / f"symbol-{index:03}.png"
        _icon(index % 5, bool(index % 2)).save(path)
        initial.append(path)
    for index in range(10_020):
        path = bulk / f"note-{index:05}.txt"
        path.write_bytes(b"Disposable acceptance fixture\n")
        initial.append(path)
    outside = fixture / "Outside the original project"
    outside.mkdir()
    external = outside / "outside.png"
    _icon(3, False).save(external)
    initial.append(external)
    launch_folder = fixture / "Existing shortcuts"
    launch_folder.mkdir()
    shortcut = make_link(launch_folder / "Project shortcut.lnk", source)
    make_link(source / "Nested alias.lnk", artwork)
    make_link(source / "Nested junction", artwork, "junction")
    make_link(artwork / "Back to project", source, "junction")
    outside_link = make_link(source / "Outside folder.lnk", outside)
    before = fingerprint(initial)
    data = base / "Navigator Review Storage"
    errors = []

    def open_page(url):
        page = browser.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url)
        expect(page.get_by_role("heading", name="mini_ark Navigator")).to_be_visible()
        return page

    with running_navigator(runtime, data, base) as url:
        page = open_page(url)
        select_link(page, launch_folder, shortcut)
        expect(page.locator("#inspect-approval")).to_contain_text(str(source))
        expect(page.locator("#inspect-review")).to_be_hidden()
        page.get_by_role("button", name="Authorize this destination").click()
        expect(page.locator('[data-count="files"]')).not_to_have_text("0", timeout=15_000)
        expect(page.get_by_role("button", name="Pause", exact=True)).to_be_enabled(timeout=15_000)
        page.get_by_role("button", name="Pause", exact=True).click()
        expect(page.locator("#inspect-progress")).to_contain_text("paused")
        paused = count(page, "files")
        assert 0 < paused < 10_094, paused
        page.locator('.quick [data-select="manage"]').click()
        page.get_by_role("button", name="Close Navigator").click()
        expect(page.get_by_text("Navigator is closed. Your review is saved.")).to_be_visible()
        page.close()

    with running_navigator(runtime, data, base) as url:
        page = open_page(url)
        page.locator('.quick [data-select="manage"]').click()
        page.get_by_role("button", name="Open saved inspection").click()
        assert count(page, "files") == paused
        page.get_by_role("button", name="Resume scan").click()
        completed(page, 10_094, 74)
        assert count(page, "unsupported") == 10_020
        assert count(page, "skipped") == 0
        page.get_by_role("button", name="Links and destinations").click()
        expect(page.locator("#inspect-results")).to_contain_text(str(shortcut))
        expect(page.locator("#inspect-results")).to_contain_text(str(source))
        expect(page.locator("#inspect-results")).to_contain_text("cycle")
        expect(page.locator("#inspect-results")).to_contain_text("already covered")
        pending = page.locator("[data-link-row]").filter(has_text=str(outside_link))
        expect(pending).to_contain_text("approval required")
        pending.get_by_role("button", name="Review destination").click()
        expect(page.locator("#inspect-approval")).to_contain_text(str(outside))
        page.get_by_role("button", name="Authorize this destination").click()
        completed(page, 10_095, 75)

        page.get_by_role("button", name="Images", exact=True).click()
        corrections(page, FIRST, "confirm", "Aster", "Character Artwork")
        wrong = page.locator("[data-image]").filter(has=page.get_by_role("heading", name=WRONG, exact=True))
        expect(wrong).to_contain_text("Aster · proposed identity")
        corrections(page, WRONG, "reject", "Aster")
        _portrait(4, True).save(source / LATER)
        before |= fingerprint([source / LATER])
        page.get_by_role("button", name="Refresh source").click()
        completed(page, 10_096, 76)
        assert count(page, "reused") == 75, count(page, "reused")
        page.get_by_label("Filter image names or paths").fill(LATER)
        page.get_by_role("button", name="Filter images").click()
        later = page.locator("[data-image]").filter(has=page.get_by_role("heading", name=LATER, exact=True))
        expect(later).to_contain_text("Identity open · unknown")
        later.get_by_text("Evidence and naming preview", exact=True).click()
        expect(later).to_contain_text("Rejected association · Aster")
        page.get_by_label("Filter image names or paths").fill("")
        page.get_by_role("button", name="Filter images").click()
        original = page.locator("[data-image]").filter(has=page.get_by_role("heading", name=FIRST, exact=True))
        expect(original).to_contain_text("Character Artwork")
        original.get_by_text("Evidence and naming preview", exact=True).click()
        expect(original).to_contain_text("v02 - 20261018_142351.png")
        page.get_by_role("button", name="Visual groups").click()
        expect(page.get_by_role("button", name="Browse series").first).to_be_visible()
        page.get_by_role("button", name="Save plan").click()
        expect(page.locator("#inspect-notice")).to_contain_text("Plan saved to")
        plan = json.loads(next(data.glob("Inspection-*.json")).read_text(encoding="utf-8"))
        assert len(plan["images"]) == 76
        named = next(image for image in plan["images"] if image["filename"] == FIRST)
        assert len(named["memberships"]) >= 3
        assert named["name"]["destination"].endswith("v02 - 20261018_142351.png")
        denied = page.evaluate("""async () => {
          const headers = {"Content-Type": "application/json", "X-Journey-Session": sessionStorage.getItem("journey-inspection-session")};
          return (await fetch('/api/proposals/1/apply', {method:'POST', headers, body:'{}'})).status;
        }""")
        assert denied == 404, denied
        page.locator("#command").fill("note-10019")
        expect(page.get_by_role("heading", name="note-10019.txt")).to_be_visible()
        page.close()
    assert not errors, errors
    assert fingerprint(before) == before
    print(f"Navigator verified: paused at {paused} files, resumed, inspected 10,096 files and 76 images, reused 75 analyses.")
    print("Verified shortcut authorization, separate provenance, alias deduplication, cycle detection, later correction, saved plan, and source integrity.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, default=Path(sys.executable))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="navigator-browser-") as temporary, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            run(browser, args.runtime.resolve(), Path(temporary).resolve())
        finally:
            browser.close()


if __name__ == "__main__":
    main()
