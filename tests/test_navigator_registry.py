"""Acceptance for source-linked project records and the exact rename boundary."""

from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock
import unittest

from PIL import Image, PngImagePlugin

from core.project_registry import PROFILE_FORMAT
from journey_navigator.links import ProtectedPath
from journey_navigator.patrol import Patrol
from journey_navigator.workbench import Workbench
from test_navigator_context import fingerprint
from test_operational_patrol import FixtureConsent


PREFIX = "💜 STUDIO Moonstone_Character_Sheet"
ORIGINAL = PREFIX + "_00_00.PNG"
CANONICAL = PREFIX + "_06_11.PNG"


def profile():
    return {"format": PROFILE_FORMAT, "project": "Studio", "signals": ["Moonstone"],
            "rules": [{"subject": "Moonstone", "purpose": "Character Reference", "prefix": PREFIX,
                       "extension": ".png", "date_order": "DD_MM", "source": "Synthetic creator decision",
                       "example": {"date": "2026-11-06", "filename": PREFIX + "_06_11.png"}}]}


def sample_image(path, color, created=None, exif_created=None):
    tags, exif = PngImagePlugin.PngInfo(), Image.Exif()
    if created:
        tags.add_text("Creation Time", created)
    if exif_created:
        exif[36867] = exif_created
    Image.new("RGB", (80, 64), color).save(path, pnginfo=tags, exif=exif)


def write_archive(path):
    def message(identifier, role, text):
        return {"id": identifier, "author": {"role": role}, "create_time": 1793923200,
                "content": {"parts": [text]}}

    def node(*args):
        return {"message": message(*args)}

    data = [
        {"id": "project-conversation", "mapping": {
            "a": node("message-1", "user", f"Studio: `{ORIGINAL}` was created on 2026-11-06."),
            "b": node("message-2", "assistant", f"`{ORIGINAL}` supersedes `Moonstone_old.png`."),
            "c": node("message-3", "user", "Personal unrelated file `private-untouched.png`."),
            "d": node("message-4", "user", "Maybe `Moonstone_old.png` should be discarded?"),
        }},
        {"id": "unretained-chat", "is_do_not_remember": True, "mapping": {
            "a": node("message-5", "user", "`Moonstone_temporary.png`."),
        }},
    ]
    path.write_text(json.dumps(data), encoding="utf-8")


class ProjectRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix="journey-project-registry-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "Studio"
        self.root.mkdir()
        self.data = self.base / "Checkpoint"
        sample_image(self.root / ORIGINAL, "#3a284f", created="2026-11-06")
        sample_image(self.root / "other.PNG", "#345d55")
        sample_image(self.root / "variant_v2.PNG", "#948940", created="2026-11-06")
        self.archive = self.base / "Export.json"
        write_archive(self.archive)
        self.open()
        self.job = self.app.select(self.root, proposals=True)["job"]
        self.scan()

    def open(self):
        self.app = Workbench(self.data)
        self.addCleanup(self.app.close)
        self.registry = self.app.project_registry
        self.patrol = Patrol(self.app, RLock(), approver=FixtureConsent())
        self.addCleanup(self.patrol.close)

    def scan(self):
        for _ in range(20):
            status = self.app.step(self.job)
            if not status["pending"] and not status["pending_folders"]:
                return
        self.fail("Fixture inspection did not finish.")

    def image(self, name=ORIGINAL):
        return next(item for item in self.app.images(self.job, 0)["items"] if item["filename"] == name)

    def confirm(self, name=ORIGINAL):
        self.app.review(self.job, self.image(name)["id"], "confirm", "Moonstone", "Character Reference")
        return self.image(name)

    def prepare(self, target=CANONICAL, source=ORIGINAL):
        return self.patrol.guided.prepare(self.job, [{"kind": "rename", "asset": self.image(source)["id"],
                                                     "destination": str(self.root / target)}])

    def test_profile_requires_an_exact_example_and_only_applies_to_its_own_scope(self):
        invalid = profile()
        invalid["rules"][0]["example"]["filename"] = PREFIX + "_11_06.png"
        with self.assertRaisesRegex(ValueError, "dated example"):
            self.registry.activate(self.job, invalid)
        self.assertIsNone(self.registry.profile(self.job))
        self.registry.activate(self.job, profile())
        outside = self.base / "Another project"
        outside.mkdir()
        other = self.app.select(outside, proposals=True)["job"]
        self.assertIsNone(self.registry.catalog(other, 0)["profile"])
        temporary = Workbench(self.data, temporary=True)
        self.addCleanup(temporary.close)
        with self.assertRaises(ProtectedPath):
            temporary.project_registry.activate(self.job, profile())

    def test_registry_import_is_selective_deduplicated_and_persistent(self):
        before = fingerprint(self.root)
        archived = self.archive.read_bytes()
        self.registry.activate(self.job, profile())
        result = self.registry.import_archive(self.job, self.archive)
        self.assertEqual(result["added"], 6)
        self.assertTrue(self.registry.import_archive(self.job, self.archive)["already_imported"])
        renamed_export = self.base / "Export duplicate.json"
        renamed_export.write_bytes(archived)
        self.assertTrue(self.registry.import_archive(self.job, renamed_export)["already_imported"])
        rows = {item["name"]: item for item in self.registry.catalog(self.job, 0)["items"]}
        self.assertNotIn("private-untouched.png", rows)
        self.assertNotIn("Moonstone_temporary.png", rows)
        self.assertEqual(rows[ORIGINAL]["state"], "filename_candidate")
        self.assertEqual(rows["Moonstone_old.png"]["state"], "referenced_not_located")
        self.assertEqual(rows["other.PNG"]["state"], "observed_in_scope")
        relationship = next(item for item in rows[ORIGINAL]["evidence"] if item["kind"] == "relationship")
        self.assertEqual(rows["Moonstone_old.png"]["lifecycle"], "unestablished")
        self.registry.review(self.job, relationship["id"], "accepted")
        old = next(item for item in self.registry.catalog(self.job, 0)["items"] if item["name"] == "Moonstone_old.png")
        self.assertEqual(old["lifecycle"], "superseded")
        self.assertTrue(all(item["kind"] != "lifecycle" for item in rows["Moonstone_old.png"]["evidence"]))
        created = next(item for item in rows[ORIGINAL]["evidence"] if item["kind"] == "creation_date")
        self.assertEqual(created["source"]["message"], "message-1")
        self.assertEqual(created["decision"], "unreviewed")
        self.registry.record_date(self.job, self.image()["id"], None, None, created["id"])
        self.assertEqual(self.confirm()["metadata"]["date"]["type"], "operator_confirmed_archive")
        self.registry.review(self.job, created["id"], "rejected")
        self.assertEqual(self.image()["name"]["state"], "needs_date")
        self.assertEqual(self.archive.read_bytes(), archived)
        self.assertEqual(fingerprint(self.root), before)
        self.patrol.close()
        self.app.close()
        self.open()
        self.assertEqual(self.registry.catalog(self.job, 0)["claims"], 6)
        self.assertEqual(self.image()["metadata"]["date_state"], "conflicted")
        self.app.revoke(self.job, str(self.root), "retain")
        for table in ("project_profiles", "project_imports", "project_claims", "project_asset_dates"):
            self.assertEqual(self.app.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0], 0)

    def test_preview_uses_full_date_and_preserves_original_bytes_case_and_parent(self):
        before = fingerprint(self.root)
        self.registry.activate(self.job, profile())
        initial = self.image()
        self.assertEqual(initial["metadata"]["filename_date"]["state"], "placeholder")
        self.assertEqual(initial["metadata"]["date"]["date"], "2026-11-06")
        self.assertEqual(initial["name"]["state"], "needs_identification")
        image = self.confirm()
        self.assertEqual(image["name"]["destination"], CANONICAL)
        self.assertEqual(image["metadata"]["original_filename"], ORIGINAL)
        self.assertEqual(self.confirm("other.PNG")["name"]["state"], "needs_date")
        self.assertEqual(self.confirm("variant_v2.PNG")["name"]["state"], "blocked")
        with self.assertRaisesRegex(ValueError, "exact destination"):
            self.prepare(PREFIX + "_11_06.PNG")
        batch = self.prepare()
        self.assertEqual(batch["operations"][0]["naming"]["creation_date"]["date"], "2026-11-06")
        self.assertEqual(fingerprint(self.root), before)
        self.assertFalse((self.root / CANONICAL).exists())
        self.registry.deactivate(self.job)
        with self.assertRaisesRegex(ValueError, "no validated project naming profile"):
            self.patrol.guided.begin_approval(batch["id"])
        self.registry.activate(self.job, profile())
        with self.assertRaisesRegex(ValueError, "changed after review"):
            self.patrol.guided.begin_approval(batch["id"])

    def test_new_date_or_occupant_invalidates_a_prepared_batch(self):
        self.registry.activate(self.job, profile())
        image = self.confirm()
        batch = self.prepare()
        self.registry.record_date(self.job, image["id"], "2026-11-07", "Synthetic creation note")
        with self.assertRaisesRegex(ValueError, "exact destination"):
            self.patrol.guided.begin_approval(batch["id"])
        target = self.root / (PREFIX + "_07_11.PNG")
        self.prepare(target.name)
        target.write_bytes(b"unrelated occupant")
        self.assertEqual(self.image()["name"]["state"], "blocked")
        with self.assertRaisesRegex(ValueError, "occupied"):
            self.prepare(target.name)
        self.assertEqual(target.read_bytes(), b"unrelated occupant")

    def test_conflicting_dates_require_explicit_asset_review(self):
        name = "Moonstone redraft.PNG"
        sample_image(self.root / name, "#ab4355", created="2026-11-06", exif_created="2026:11:07 12:00:00")
        self.app.refresh(self.job)
        self.scan()
        self.registry.activate(self.job, profile())
        image = self.confirm(name)
        self.assertEqual(image["metadata"]["date_state"], "conflicted")
        self.assertEqual(image["name"]["state"], "needs_date")
        with self.assertRaises(ValueError):
            self.registry.record_date(self.job, image["id"], "2026-02-29", "Invalid test")
        self.registry.record_date(self.job, image["id"], "2026-11-07", "Reviewed original source")
        self.assertEqual(self.image(name)["metadata"]["date"]["date"], "2026-11-07")

    def test_creation_index_records_outputs_without_following_paths_or_using_index_time(self):
        self.registry.activate(self.job, profile())
        index = self.base / "asset-index.json"
        record = {"fingerprint": "test-index", "operation": "compose_master_sheet",
                  "job": "Studio sheet", "updated_at": "2025-01-12T15:00:00",
                  "outputs": {"master_sheet": "/unavailable/" + ORIGINAL}}
        index.write_text(json.dumps({"version": 1, "entries": {"test-index": record}}), encoding="utf-8")
        self.assertEqual(self.registry.import_archive(self.job, index)["added"], 1)
        evidence = self.image()["metadata"]["registry_evidence"][0]
        self.assertEqual(evidence["source"]["role"], "creation_record")
        self.assertEqual(evidence["source"]["message"], "test-index")
        self.assertEqual(evidence["kind"], "reference")

    @unittest.skipUnless(os.name == "nt", "Native Windows no-overwrite rename and reversal")
    def test_exact_account_path_executes_renames_and_preserves_history_through_undo(self):
        source = self.root / ORIGINAL
        content = sha256(source.read_bytes()).hexdigest()
        self.registry.activate(self.job, profile())
        self.registry.import_archive(self.job, self.archive)
        self.confirm()
        batch = self.prepare()
        binding, description = self.patrol.guided.begin_approval(batch["id"])
        self.patrol.guided.accept(batch["id"], FixtureConsent().verify(binding, description))
        result = self.patrol.guided.step(batch["id"])
        self.assertEqual(result["status"], "completed", result)
        self.scan()
        target = self.root / CANONICAL
        self.assertEqual(sha256(target.read_bytes()).hexdigest(), content)
        image = self.image(CANONICAL)
        self.assertEqual(image["metadata"]["original_filename"], ORIGINAL)
        self.assertEqual(image["metadata"]["date"]["date"], "2026-11-06")
        rows = {item["name"]: item for item in self.registry.catalog(self.job, 0)["items"]}
        self.assertEqual(rows[ORIGINAL]["state"], "verified_path_history")
        undo = self.patrol.guided.prepare_undo(self.job, result["progress"][0]["receipt"])
        binding, description = self.patrol.guided.begin_approval(undo["id"])
        self.patrol.guided.accept(undo["id"], FixtureConsent().verify(binding, description))
        result = self.patrol.guided.step(undo["id"])
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(sha256(source.read_bytes()).hexdigest(), content)
