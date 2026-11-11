"""Acceptance fixtures for contextual evidence, local text, and independent scope grants."""

from collections import Counter
from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import tempfile
from time import perf_counter
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

from journey_navigator.links import ProtectedPath
from journey_navigator.ocr import LocalOcr, find_local_ocr
from journey_navigator.workbench import Workbench
from navigator_fixtures import make_link


NAMES = ("Moonstone", "Cloverstone", "Heartstone", "Cloudstone", "Wishstone", "Corestone")
ALIASES = ("Moon-Stone", "Clover Stone", "Heart Stone", "Cloud_Stone", "Wish Stone", "Opalstone")
COLORS = ("#553480", "#275343", "#91344a", "#20587a", "#9e651c", "#536566")


def make_board(path, heading="", subtitle="", color="#553480", revision="", note="", variation=0):
    image = Image.new("RGB", (1080, 760), "#faf8ef")
    draw = ImageDraw.Draw(image)
    font = "arialbd.ttf" if os.name == "nt" else "DejaVuSans-Bold.ttf"
    fonts = {size: ImageFont.truetype(font, size) for size in (28, 36, 64)}
    draw.text((55, 30), heading, font=fonts[64], fill="#181927")
    draw.text((55, 120), subtitle, font=fonts[36], fill="#181927")
    draw.text((55, 175), revision, font=fonts[28], fill="#181927")
    draw.rounded_rectangle((55, 245, 630, 693), radius=18, fill=color)
    draw.polygon([(190, 616), (356, 294 + variation), (545, 616)], fill="#f2da93")
    draw.ellipse((326 + variation, 403, 392 + variation, 470), fill="#ebe3f4")
    for number in range(4):
        y = 255 + number * 105
        draw.rounded_rectangle((665, y, 1021, y + 86), radius=14, outline=color, width=5)
        draw.line((700, y + 64, 986, y + 28), fill=color, width=3)
    draw.text((55, 704), note, font=fonts[28], fill="#181927")
    image.save(path)


def reader():
    provided = os.environ.get("JOURNEY_TEST_OCR")
    if provided:
        root = Path(provided)
        return LocalOcr(root / "tesseract.exe", root / "tessdata")
    return find_local_ocr()


def fingerprint(source):
    return {str(path.relative_to(source)): (sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in source.rglob("*") if path.is_file() and path.suffix.casefold() == ".png"}


class NavigatorContextTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="navigator-context-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.source = self.base / "CareBloomOS"
        self.source.mkdir()
        self.store = self.base / "Review data"

    def workbench(self, **settings):
        app = Workbench(self.store, **settings)
        self.addCleanup(app.close)
        return app

    def finish(self, app, job):
        for _ in range(100):
            status = app.step(job)
            if not status["pending"] and not status["pending_folders"]:
                return status
        self.fail("Inspection did not finish in its bounded batches.")

    def results(self, app, job):
        rows, offset = {}, 0
        while True:
            page = app.images(job, offset)
            rows.update((row["filename"], row) for row in page["items"])
            if not page["more"]:
                return rows
            offset += 24

    def test_36_labeled_and_misleading_boards_with_real_ocr(self):
        ocr = reader()
        if ocr is None:
            self.skipTest("Requires a local English Tesseract runtime.")
        expected = {}
        for index, (name, alias, color) in enumerate(zip(NAMES, ALIASES, COLORS)):
            filenames = [f"{name}_Character_Reference_2026-10-18_v02.1.PNG", f"untitled-{index}.png",
                         f"{alias} - concept board.png", f"{name} - misleading-{index}.png",
                         f"comparison-{index}.png", f"{name}ish-{index}.png"]
            filename, titled, aliased, conflict, comparison, substring = filenames
            make_board(self.source / filename, "Design study", color=color)
            make_board(self.source / titled, name, "Character reference sheet", color=color,
                       revision="Revision v12.4 2026-10-19", note=f"Scene board {index}")
            make_board(self.source / aliased, "Draft study", color=color)
            wrong = self.source / NAMES[(index + 1) % len(NAMES)]
            wrong.mkdir(exist_ok=True)
            make_board(wrong / conflict, "Reference board", color=color)
            make_board(self.source / comparison, "Design notes", color=color, note=f"Not {name}")
            make_board(self.source / substring, "Palette notes", color=color)
            for item in (filename, titled, aliased):
                expected[item] = ("proposed_identity", name)
            expected[conflict] = ("conflicting_evidence", "")
            expected[comparison] = ("possibly_related", "")
            expected[substring] = ("unknown", "")

        before = fingerprint(self.source)
        app = self.workbench(ocr=ocr)
        job = app.select(self.source, proposals=True)["job"]
        elapsed = perf_counter()
        with patch.object(ocr, "recognize", wraps=ocr.recognize) as invoked:
            stats = self.finish(app, job)
            calls = invoked.call_count
        elapsed = perf_counter() - elapsed
        self.assertEqual(stats["analyzed"], 36)
        self.assertEqual(calls, 36)
        rows = self.results(app, job)
        observed = {name: (row["identity"]["state"], row["identity"]["label"]) for name, row in rows.items()}
        self.assertEqual(observed, expected)
        for index, name in enumerate(NAMES):
            row = rows[f"untitled-{index}.png"]
            self.assertEqual(row["suggestion"]["filename"], f"{name} - Character Reference.png")
            self.assertIsNone(row["name"]["destination"])
            self.assertTrue(any(signal["source"] == "Image text" and name in signal["subjects"]
                                for signal in row["signals"]))
            self.assertTrue(any("v12.4" in [value.casefold() for value in signal["versions"]]
                                and "2026-10-19" in signal["dates"] for signal in row["signals"]), row["signals"])
            filename = f"{name}_Character_Reference_2026-10-18_v02.1.PNG"
            self.assertTrue(rows[filename]["suggestion"]["filename"].endswith("v02.1 - 2026-10-18.PNG"))
        self.assertTrue(any(item["title"] == "untitled-0.png" and "Image text: Moonstone" in item["details"]
                            for item in app.search(job, "Moonstone")))
        self.assertIn("untitled-0.png", {row["filename"] for row in app.images(job, 0, query="Scene board 0")["items"]})

        app.review(job, rows["untitled-0.png"]["id"], "confirm", "Moonstone", "Character Reference")
        app.review(job, rows["comparison-0.png"]["id"], "reject", "Moonstone")
        export = json.loads(Path(app.export(job)["path"]).read_text())
        reviewed = next(row for row in export["images"] if row["filename"] == "untitled-0.png")
        self.assertEqual(reviewed["identity"]["state"], "human_confirmed_identity")
        self.assertEqual(reviewed["name"]["state"], "held_convention")
        self.assertIsNone(reviewed["name"]["destination"])
        self.assertEqual(reviewed["name"]["candidate_destination"], "Moonstone/Moonstone - Character Reference.png")
        self.assertNotIn("lines", reviewed["ocr"])
        self.assertEqual(fingerprint(self.source), before)

        # New bytes and explicit misleading filename. The persisted rejection changes the result.
        later = self.source / "Moonstone - later draft.png"
        make_board(later, "Design notes", color=COLORS[0], note="Not Moonstone", variation=2)
        control = self.base / "Unreviewed sample"
        control.mkdir()
        shutil.copyfile(later, control / later.name)
        with closing(Workbench(self.base / "Fresh comparison", ocr=ocr, temporary=True)) as untrained:
            neutral = untrained.select(control, proposals=True)["job"]
            self.finish(untrained, neutral)
            self.assertEqual(self.results(untrained, neutral)[later.name]["identity"]["state"], "proposed_identity")
        app.close()
        reopened = self.workbench(ocr=ocr)
        self.assertEqual(reopened.jobs()[0]["id"], job)
        reopened.refresh(job)
        with patch.object(ocr, "recognize", wraps=ocr.recognize) as invoked:
            warm = perf_counter()
            refreshed = self.finish(reopened, job)
            warm = perf_counter() - warm
            self.assertEqual(invoked.call_count, 1)
        self.assertEqual(refreshed["reused"], 36)
        reviewed_later = self.results(reopened, job)[later.name]
        self.assertEqual(reviewed_later["identity"]["state"], "explicitly_rejected_identity")
        self.assertIsNone(reviewed_later["suggestion"])
        self.assertEqual(fingerprint(self.source) | before, fingerprint(self.source))
        totals = Counter(state for state, _ in observed.values())
        print(f"Context fixture: {ocr.version}; 36 boards in {elapsed:.3f}s; {dict(totals)}; "
              f"2 operator decisions; 0 automatic confirmations; reopened and refreshed 37 in {warm:.3f}s "
              f"with 36 reused and one new text run.")

    def test_text_and_folder_conflict_does_not_override_exact_confirmation(self):
        ocr = reader()
        if ocr is None:
            self.skipTest("Requires a local English Tesseract runtime.")
        filename = self.source / "Cloverstone character reference.png"
        make_board(filename, "Moonstone", "Character reference sheet")
        app = self.workbench(ocr=ocr)
        job = app.select(self.source, proposals=True)["job"]
        self.finish(app, job)
        image = self.results(app, job)[filename.name]
        self.assertEqual(set(image["identity"]["conflicts"]), {"Moonstone", "Cloverstone"})
        self.assertIsNone(image["suggestion"])
        app.review(job, image["id"], "confirm", "Moonstone", "Character Reference")
        current = self.results(app, job)[filename.name]
        self.assertEqual(current["identity"]["state"], "human_confirmed_identity")
        self.assertIn("Cloverstone", current["identity"]["conflicts"])
        with self.assertRaisesRegex(ValueError, "already has a confirmed identity"):
            app.review(job, image["id"], "confirm", "Cloverstone")

    def test_perception_failures_leave_filename_evidence_usable(self):
        path = self.source / "Moonstone_reference_sheet.png"
        make_board(path)
        app = self.workbench()
        job = app.select(self.source, proposals=True)["job"]
        self.finish(app, job)
        row = self.results(app, job)[path.name]
        self.assertEqual(row["ocr"]["status"], "unavailable")
        self.assertEqual(row["suggestion"]["filename"], "Moonstone - Character Reference.png")

    def test_scope_retention_proposal_and_execution_are_independent(self):
        path = self.source / "Moonstone concept board.png"
        make_board(path)
        app = self.workbench(temporary=True)
        job = app.select(self.source)["job"]
        self.finish(app, job)
        image = self.results(app, job)[path.name]
        self.assertEqual(image["identity"]["state"], "proposed_identity")
        self.assertIsNone(image["suggestion"])
        app.permit_proposals(job, str(self.source), True)
        self.assertIsNotNone(self.results(app, job)[path.name]["suggestion"])
        with self.assertRaises(ProtectedPath):
            app.export(job)
        permissions = app.permissions(job)["scopes"][0]
        self.assertEqual((permissions["inspect"], permissions["retain"], permissions["propose"],
                          permissions["reuse_elsewhere"], permissions["execute"]), (1, False, 1, False, False))
        app.review(job, image["id"], "confirm", "Moonstone")
        app.permit_proposals(job, str(self.source), False)
        self.assertIsNone(self.results(app, job)[path.name]["suggestion"])
        app.revoke(job, str(self.source), "inspect")
        for read in (app.step, app.summary, lambda id: app.images(id, 0), lambda id: app.search(id, "Moonstone"),
                     lambda id: app.groups(id, 0), lambda id: app.links(id, 0), lambda id: app.issues(id, 0)):
            with self.assertRaises(ProtectedPath):
                read(job)
        self.assertFalse(self.store.exists())

    def test_external_link_and_corrections_are_isolated_and_revocable(self):
        source_image = self.source / "source.png"
        make_board(source_image)
        outside = self.base / "Unrelated project"
        outside.mkdir()
        linked_image = outside / "outside.png"
        shutil.copyfile(source_image, linked_image)
        alias = make_link(self.source / "Other scope.lnk", outside)
        app = self.workbench()
        job = app.select(self.source, proposals=True)["job"]
        import journey_navigator.workbench as workbench_module
        original = workbench_module.image_bytes

        def bounded_read(path, *args):
            if not path.is_relative_to(self.source):
                self.fail("Unapproved linked content was opened")
            return original(path, *args)

        with patch.object(workbench_module, "image_bytes", bounded_read):
            summary = self.finish(app, job)
        self.assertEqual(summary["analyzed"], 1)
        image = self.results(app, job)[source_image.name]
        app.review(job, image["id"], "confirm", "Moonstone")
        row = next(row for row in app.links(job, 0)["items"] if row["selected"] == str(alias))
        self.assertEqual(row["status"], "approval_required")
        pending = app.select(None, job_id=job, link_id=row["id"])
        with self.assertRaises(ValueError):
            app.approve("unissued-ticket")
        app.approve(pending["ticket"], proposals=False)
        self.assertEqual(self.finish(app, job)["analyzed"], 2)
        self.assertEqual(self.results(app, job)[linked_image.name]["identity"]["state"], "unknown")
        self.assertNotEqual(self.results(app, job)[linked_image.name]["series"], image["series"])
        app.revoke(job, str(outside), "retain")
        self.assertEqual(app.summary(job)["analyzed"], 1)
        self.assertEqual(app.search(job, linked_image.name), [])
        self.assertEqual(app.groups(job, 0)["items"], [])
        self.assertEqual(app.conn.execute("SELECT count(*) FROM observations WHERE scope=?", (str(outside),)).fetchone()[0], 0)
        app.refresh(job)
        with patch.object(workbench_module, "image_bytes", bounded_read):
            self.assertEqual(self.finish(app, job)["analyzed"], 1)
        self.assertEqual(fingerprint(outside)[linked_image.name][0], fingerprint(self.source)[source_image.name][0])


if __name__ == "__main__":
    unittest.main()
