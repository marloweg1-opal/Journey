import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from journey_planner.catalog import scan_folder, suggested_name
from journey_planner.plan_file import coverage_notes, export_plan, export_text, open_plan, save_plan


class FolderPlannerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.source = self.base / "Studio source"
        self.source.mkdir()
        self.output = self.base / "Planning"
        self.output.mkdir()

    def file(self, path, data=b"example source data"):
        target = self.source / path
        target.parent.mkdir(exist_ok=True, parents=True)
        target.write_bytes(data)
        return target

    def test_workflow_preserves_source_and_reopens_without_it(self):
        image = self.file("incoming/Café__cover.PNG")
        notes = self.file("reference/Workshop notes.txt")
        snapshot = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (image, notes)}
        with patch.object(Path, "open", side_effect=AssertionError("Scan attempted to read file bytes")):
            plan = scan_folder(self.source)
        self.assertEqual(set(plan.files), {"incoming/Café__cover.PNG", "reference/Workshop notes.txt"})
        self.assertEqual(plan.files["incoming/Café__cover.PNG"].name, "Café cover.PNG")

        plan.add_collection("Workshop assets")
        plan.assign(plan.files, "Workshop assets")
        plan.rename("incoming/Café__cover.PNG", "Café workshop cover.PNG")
        plan.files["incoming/Café__cover.PNG"].decision = "Include"
        plan.files["reference/Workshop notes.txt"].decision = "Keep"
        saved = self.output / "Workshop.journey.json"
        revision = save_plan(plan, saved)

        for path, identity in snapshot.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), identity)
        self.assertEqual({path.name for path in self.source.iterdir()}, {"incoming", "reference"})
        # Simulate removal of a portable source after the user's scan.
        self.source.rename(self.base / "Disconnected")
        reopened, current = open_plan(saved)
        self.assertEqual(current, revision)
        self.assertEqual(reopened, plan)
        self.assertEqual(reopened.proposals()["incoming/Café__cover.PNG"].destination,
                         "Workshop assets/Café workshop cover.PNG")
        report = self.output / "Checklist.txt"
        export_plan(reopened, report)
        text = report.read_text(encoding="utf-8")
        self.assertIn("Included changes (1)", text)
        self.assertIn(r'"Workshop assets\Café workshop cover.PNG"', text)
        self.assertIn("Keep in place (1)", text)
        self.assertFalse(self.source.exists())

    def test_changed_proposal_resets_include_decision(self):
        self.file("title.txt")
        plan = scan_folder(self.source)
        plan.add_collection("Notes")
        plan.files["title.txt"].decision = "Include"
        self.assertTrue(plan.rename("title.txt", "session title.txt"))
        self.assertEqual(plan.files["title.txt"].decision, "Review")
        plan.files["title.txt"].decision = "Include"
        self.assertTrue(plan.assign(["title.txt"], "Notes"))
        self.assertEqual(plan.files["title.txt"].decision, "Review")
        for invalid in ("title.jpg", "..", "a/b.txt", "CON.txt", "COM¹.txt", "test.txt ", "a:b.txt"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                plan.rename("title.txt", invalid)

    def test_naming_preserves_extensions_unicode_and_hidden_files(self):
        for original, expected in (
            ("Café__cover.PNG", "Café cover.PNG"), (".editor_config", ".editor_config"),
            ("clip__download.part", "clip__download.part"), ("Read__This", "Read This"),
            ("image__master.tiff", "image master.tiff"), ("Outils__DEMO.tar.gz", "Outils DEMO.tar.gz"),
        ):
            with self.subTest(original=original):
                self.assertEqual(suggested_name(original), expected)

    def test_conflicts_and_temporary_files_stay_out_of_included_changes(self):
        for path in ("a/Cover.png", "b/cover.png", "a/video.part", "assets/existing.txt", "not a folder"):
            self.file(path)
        plan = scan_folder(self.source)
        plan.add_collection("Assets")
        plan.assign(["a/Cover.png", "b/cover.png", "a/video.part"], "Assets")
        for path in ("a/Cover.png", "b/cover.png", "a/video.part"):
            plan.files[path].decision = "Include"
        self.assertIn("More than one", plan.proposals()["a/Cover.png"].blocker)
        self.assertIn("Temporary", plan.proposals()["a/video.part"].blocker)
        plan.rename("b/cover.png", "other cover.png")
        plan.rename("a/Cover.png", "cover art.png")
        plan.files["a/Cover.png"].decision = "Include"
        self.assertEqual(plan.proposals()["a/Cover.png"].destination, "assets/cover art.png")
        self.assertIn("Included changes (1)", export_text(plan))
        self.assertIn("Included items that need review (1)", export_text(plan))

    def test_occupied_paths_are_blocked(self):
        self.file("raw/notes.txt")
        self.file("Assets/Notes.txt")
        self.file("Taken")
        plan = scan_folder(self.source)
        plan.add_collection("assets")
        plan.add_collection("taken")
        plan.assign(["raw/notes.txt"], "assets")
        self.assertIn("already exists", plan.proposals()["raw/notes.txt"].blocker)
        plan.assign(["raw/notes.txt"], "taken")
        self.assertIn("occupies", plan.proposals()["raw/notes.txt"].blocker)
        plan.assign(["raw/notes.txt"], "")
        plan.rename("raw/notes.txt", "Notes.txt")
        self.assertIn("Case-only", plan.proposals()["raw/notes.txt"].blocker)

    def test_skips_links_and_disallows_output_through_aliases(self):
        self.file("source notes.txt")
        hidden = self.output / "Outside"
        hidden.mkdir()
        (hidden / "out of scope.txt").touch()
        try:
            (self.source / "Link").symlink_to(hidden, target_is_directory=True)
            (self.output / "Alias").symlink_to(self.source, target_is_directory=True)
        except OSError:
            self.skipTest("Test account cannot create symlinks.")
        plan = scan_folder(self.source)
        self.assertEqual(set(plan.files), {"source notes.txt"})
        self.assertIn("Link", plan.gaps)
        plan.add_collection("Link")
        plan.assign(plan.files, "Link")
        self.assertIn("uninspected", plan.proposals()["source notes.txt"].blocker)
        with self.assertRaises(ValueError):
            scan_folder(self.output / "Alias")
        with self.assertRaises(ValueError):
            export_plan(plan, self.output / "Alias" / "danger.txt")
        self.assertFalse((self.source / "danger.txt").exists())

    def test_scan_limits_are_explicit(self):
        self.file("asset__one.txt")
        self.file("asset__two.txt")
        plan = scan_folder(self.source, max_entries=1)
        self.assertTrue(plan.limited)
        self.assertEqual(len(plan.files), 1)
        next(iter(plan.files.values())).decision = "Include"
        self.assertIn("Included changes (0)", export_text(plan))
        self.assertIn("1-entry limit", export_text(plan))
        with patch("journey_planner.catalog.monotonic", side_effect=[0, 0, 20]):
            timed = scan_folder(self.source)
        self.assertTrue(timed.limited)
        self.assertEqual(len(timed.files), 1)
        self.assertIn("20-second time limit", export_text(timed))

    def test_scan_details_distinguish_skipped_folders_from_unvisited_paths(self):
        self.file("private/unseen.txt")
        self.file("visible.txt")
        scandir = os.scandir

        def read_folder(path):
            if Path(path).name == "private":
                raise PermissionError("Fixture for an unreadable folder")
            return scandir(path)

        with patch("journey_planner.catalog.os.scandir", side_effect=read_folder):
            plan = scan_folder(self.source)
        self.assertFalse(plan.limited)
        self.assertEqual(set(plan.files), {"visible.txt"})
        self.assertEqual(plan.gaps, {"private": "Access denied while reading folder."})
        notes = "\n".join(coverage_notes(plan))
        self.assertIn("Skipped paths (1)", notes)
        self.assertIn("1 × Access denied", notes)
        self.assertIn('"private": Access denied', notes)

    def test_focused_plan_preserves_the_outer_read_only_boundary(self):
        self.file("docs/notes.txt")
        self.file("other/sibling.txt")
        broader = scan_folder(self.source)
        with self.assertRaisesRegex(ValueError, "Choose a subfolder"):
            scan_folder(self.output, broader_plan=broader)
        plan = scan_folder(self.source / "docs", broader_plan=broader)
        self.assertEqual(set(plan.files), {"notes.txt"})
        saved = self.output / "Focused.journey.json"
        save_plan(plan, saved)
        reopened, _ = open_plan(saved)
        self.assertEqual(reopened, plan)
        with self.assertRaisesRegex(ValueError, "outside the inspected folder"):
            save_plan(reopened, self.source / "Rejected.journey.json")
        with self.assertRaisesRegex(ValueError, "outside the inspected folder"):
            export_plan(reopened, self.source / "other" / "Rejected.txt")
        self.assertEqual(os.listdir(self.source / "other"), ["sibling.txt"])

    def test_opens_rc1_plan_with_legacy_scan_limit(self):
        self.file("asset.txt")
        saved = self.output / "RC1.journey.json"
        save_plan(scan_folder(self.source), saved)
        old = json.loads(saved.read_text(encoding="utf-8"))
        old["schema"] = 1
        old["plan"]["limited"] = True
        del old["plan"]["scan_limit"], old["plan"]["protected_root"]
        saved.write_text(json.dumps(old), encoding="utf-8")
        reopened, _ = open_plan(saved)
        self.assertEqual(set(reopened.files), {"asset.txt"})
        self.assertTrue(reopened.limited)
        self.assertIn("The earlier plan did not record which", export_text(reopened))

    def test_refuses_source_output_existing_files_and_stale_saves(self):
        self.file("notes.txt")
        plan = scan_folder(self.source)
        with self.assertRaisesRegex(ValueError, "outside the inspected folder"):
            save_plan(plan, self.source / "Rejected.journey.json")
        with self.assertRaisesRegex(ValueError, "outside the inspected folder"):
            export_plan(plan, self.source / "Rejected.txt")
        self.assertEqual(os.listdir(self.source), ["notes.txt"])

        saved = self.output / "Editable.journey.json"
        revision = save_plan(plan, saved)
        with self.assertRaises(FileExistsError):
            save_plan(plan, saved)
        second, _ = open_plan(saved)
        second.add_collection("New decision")
        new_revision = save_plan(second, saved, expected=revision)
        self.assertNotEqual(new_revision, revision)
        with self.assertRaisesRegex(ValueError, "changed on disk"):
            save_plan(plan, saved, expected=revision)
        self.assertEqual(open_plan(saved)[0], second)

        report = self.output / "Existing.txt"
        report.write_text("preserve me", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            export_plan(plan, report)
        self.assertEqual(report.read_text(encoding="utf-8"), "preserve me")
        self.assertEqual(set(os.listdir(self.output)), {saved.name, report.name})

    def test_invalid_plan_cannot_create_proposals_from_traversal_or_unknown_schema(self):
        self.file("notes.txt")
        plan = scan_folder(self.source)
        path = self.output / "Untrusted.journey.json"
        save_plan(plan, path)
        original = json.loads(path.read_text(encoding="utf-8"))
        for field, value in (("schema", 99), ("schema", True), ("format", "other")):
            with self.subTest(field=field, value=value):
                path.write_text(json.dumps({**original, field: value}), encoding="utf-8")
                with self.assertRaises(ValueError):
                    open_plan(path)
        original["plan"]["files"]["../notes.txt"] = original["plan"]["files"].pop("notes.txt")
        path.write_text(json.dumps(original), encoding="utf-8")
        with self.assertRaises(ValueError):
            open_plan(path)
