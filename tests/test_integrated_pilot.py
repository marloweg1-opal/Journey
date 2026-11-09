"""Acceptance of operational history, scope safety and the live regression cases."""

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock, Thread
from time import monotonic, sleep
from urllib.request import Request, urlopen
import unittest

from journey_navigator.__main__ import Navigator
from journey_navigator.conversation import explicit_intent
from journey_navigator.patrol import Patrol
from journey_navigator.registry import PATTERN_FORMAT
from journey_navigator.session import SessionOwner
from journey_navigator.watch import DriftWatch
from journey_navigator.workbench import Workbench
from tools.demo_integrated_pilot import illustration, make_demo, native_record


def digest(path):
    return sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


class IntegratedPilot(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="journey-integrated-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.collection, self.exports, self.pack = make_demo(self.root / "Pilot")
        self.app = Workbench(self.root / "Checkpoint")
        self.addCleanup(self.app.close)
        self.job = self.app.select(self.collection, proposals=True)["job"]
        self.finish_scan()

    def finish_scan(self):
        for _ in range(40):
            progress = self.app.step(self.job)
            if not progress["pending"] and not progress["pending_folders"]:
                return
        self.fail("Inspection did not finish.")

    def panel(self):
        return self.app.images(self.job, 0, query="render_a.png", thumbnails=False)["items"][0]

    def test_history_changes_assessment_and_routes_to_the_same_patrol(self):
        with Navigator(self.app) as navigator:
            worker = Thread(target=navigator.serve_forever)
            worker.start()

            def api(action, **body):
                request = Request(navigator.origin + "/api/inspect/" + action, data=json.dumps(body).encode(), headers={
                    "Content-Type": "application/json", "Origin": navigator.origin, "X-Journey-Session": navigator.token})
                with urlopen(request, timeout=12) as reply:
                    return json.load(reply)

            try:
                job = self.job
                plan = api("pack-preview", job=job, path=str(self.pack))
                api("pack-apply", job=job, project="studio fixture", ticket=plan["ticket"])
                untouched = {path: digest(path) for path in [*self.collection.glob("*.png"), *self.exports.iterdir()]}
                self.assertEqual(api("history-status", job=job)["unique_messages"], 0)
                self.assertEqual(api("images", job=job, query="render_a.png")["items"][0]["purpose"]["state"], "unknown")
                preview = api("history-preview", job=job, path=str(self.exports))
                self.assertEqual(len(preview["files"]), 2)
                self.assertEqual(api("history-status", job=job)["files"], [])
                api("history-enqueue", job=job, ticket=preview["ticket"])
                for _ in range(160):
                    coverage = api("history-status", job=job)
                    if all(file["status"] != "queued" for file in coverage["files"]):
                        break
                    sleep(.025)
                self.assertEqual([file["status"] for file in coverage["files"]], ["complete", "complete"])
                self.assertEqual(coverage["unique_messages"], 3)
                self.assertEqual(coverage["attachment_records"], 1)
                image = api("images", job=job, query="render_a.png")["items"][0]
                self.assertEqual(image["purpose"]["label"], "CareRail UI / Design")
                self.assertTrue(any(item.get("provenance", {}).get("message") == "demo-panel" for item in image["signals"]))
                destination = api("destination-create", job=job, objective="Organize project", why="Evidence", success="Review groups")["id"]
                plan = api("goal-plan", destination=destination, instruction="Organize the selected folder.")
                self.assertEqual(plan["intent"], "organize")
                results = api("goal-plan", destination=destination, instruction="Find render_a.png")
                self.assertIn("LOCAL REFERENCE HISTORY", {item["group"] for item in results["results"]})
                api("patrol-begin", destination=destination)
                for _ in range(180):
                    work = api("patrol-status", destination=destination)
                    if work["state"] not in ("Inspecting", "Assessing", "Working", "Verifying"):
                        break
                    sleep(.025)
                self.assertIn("CareRail UI / Design", {item["name"] for item in work["collections"]})
                self.assertEqual(api("history-status", job=job)["reconciliation"]["archive_bytes_verified"], 0)
                self.assertEqual({path: digest(path) for path in untouched}, untouched)
                self.assertEqual(api("history-forget", job=job)["claims"], 0)
                self.assertEqual(api("images", job=job, query="render_a.png")["items"][0]["purpose"]["state"], "unknown")
                self.assertFalse(any(item["group"] == "LOCAL REFERENCE HISTORY" for item in
                                     api("goal-plan", destination=destination, instruction="Find render_a.png")["results"]))
            finally:
                navigator.shutdown()
                worker.join(6)

    def test_real_case_names_and_relation_boundaries(self):
        filenames = {
            "care_rail_final.png": "CareRail UI / Design", "care_rail_train_test_example.png": "CareRail UI / Design",
            "Cloudstone Weapon Design Sheet.png": "Equipment / Design Reference", "Multi-character Lineup.png": "Character Lineup",
            "Moonstone Character Sheet.png": "Character Reference", "Cloverstone Character Sheet.png": "Character Reference",
            "Heartstone Character Sheet.png": "Character Reference", "Moonstone Purple Touchstone 50%.png": "Touchstone",
            "Cloverstone Green Touchstone 50%.png": "Touchstone", "Heart Touchstone.png": "Touchstone",
            "Clover Corestone Crystal.png": "Crystal", "Heart Corestone Crystal.png": "Crystal",
            "musicstone_care_rail(1).png": "CareRail UI / Design", "Wishstone Wallpaper.png": "Wallpaper",
            "Beat Character Sheet.png": "Character Reference", "Melody Character Sheet.png": "Character Reference",
            "Opalstone Chibi.png": "Chibi / Mascot",
        }
        for index, name in enumerate(filenames):
            illustration(self.collection / name, (960 + index, 520), "#39aafa")
        profile = {"format": PATTERN_FORMAT, "project": "CareBloomOS",
                   "signals": ["CareBloomOS", "Musicstone", "Corestone", "Opalstone"], "rules": []}
        self.app.project_registry.activate(self.job, profile)
        tick = chr(96)
        records = [("music-ref", "user", f"In CareBloomOS, {tick}musicstone_care_rail.png{tick} is a CareRail panel.", []),
                   ("duo", "user", "Musicstone: Beat and Melody each have a reference sheet.", []),
                   ("opal", "user", "Corestone is Opalstone. Opalstone acts as the current Corestone.", [])]
        export = self.root / "conversations-fixture.json"
        export.write_text(json.dumps([native_record("named-assets", records, "CareBloomOS")]), encoding="utf-8")
        plan = self.app.history.preview(self.job, export)
        self.app.history.enqueue(self.job, plan["ticket"])
        while self.app.history.advance():
            pass
        self.app.refresh(self.job)
        self.finish_scan()
        items = {image["filename"]: image for image in self.app.images(self.job, 0, thumbnails=False)["items"]}
        for name, purpose in filenames.items():
            with self.subTest(name=name):
                self.assertEqual(items[name]["purpose"]["label"], purpose)
                self.assertFalse(items[name]["name"]["executable"])
                self.assertEqual(items[name]["metadata"]["original_filename"], name)
        for name, stone in [("Clover Corestone Crystal.png", "Cloverstone"), ("Heart Corestone Crystal.png", "Heartstone")]:
            self.assertEqual(items[name]["identity"]["state"], "unknown")
            self.assertEqual(items[name]["relations"][0]["possible_subject"], stone)
        self.assertEqual(items["Heart Touchstone.png"]["identity"]["label"], "Heartstone")
        for name in ("Beat Character Sheet.png", "Melody Character Sheet.png"):
            self.assertEqual(items[name]["identity"]["label"], "Musicstone")
        self.assertEqual(items["Opalstone Chibi.png"]["identity"]["label"], "Corestone")
        music = items["musicstone_care_rail(1).png"]["metadata"]["local_history"]
        self.assertTrue(any(item["name"] == "musicstone_care_rail.png" and item["match"] == "variant candidate" for item in music))
        self.assertIn("musicstone_care_rail(1).png", {item["title"] for item in self.app.search(self.job, "Musicstone CareRail")
                                                   if item["group"] == "INSPECTED FILES"})
        self.assertEqual(self.app.history.reconcile(self.job)["archive_bytes_verified"], 0)

    def test_changed_export_and_manifest_escape_fail_without_importing(self):
        preview = self.app.packs.preview(self.job, self.pack)
        self.app.packs.apply(self.job, preview["ticket"], "studio fixture")
        plan = self.app.history.preview(self.job, self.exports)
        selected = self.exports / "conversations-001.json"
        selected.write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "changed since preview"):
            self.app.history.enqueue(self.job, plan["ticket"])
        manifest = self.exports / "exports.manifest.json"
        manifest.write_text(json.dumps({"format": "journey-history-manifest-1", "files": ["../private.json"]}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "its own folder"):
            self.app.history.preview(self.job, manifest)
        self.assertEqual(self.app.history.status(self.job)["files"], [])

    def test_malformed_export_does_not_publish_partial_claims(self):
        preview = self.app.packs.preview(self.job, self.pack)
        self.app.packs.apply(self.job, preview["ticket"], "studio fixture")
        text = "Studio Fixture: " + chr(96) + "render_a.png" + chr(96) + " is a CareRail interface."
        record = native_record("bad", [("bad-message", "user", text, [])])
        export = self.root / "conversations-bad.json"
        export.write_text("[" + ",".join(json.dumps(record) for _ in range(8)) + ", broken]", encoding="utf-8")
        self.app.history.enqueue(self.job, self.app.history.preview(self.job, export)["ticket"])
        self.assertTrue(self.app.history.advance())
        self.assertEqual(self.app.history.status(self.job)["claims"], 0)
        self.assertTrue(self.app.history.advance())
        self.assertEqual(self.app.history.status(self.job)["files"][0]["status"], "failed")
        self.assertEqual(self.panel()["purpose"]["state"], "unknown")

    def test_drift_watch_is_session_only_and_detects_without_writing(self):
        watch = DriftWatch(self.app)
        self.assertFalse(watch.status()["enabled"])
        self.assertTrue(watch.enable(self.job)["enabled"])
        source = self.collection / "render_a.png"
        illustration(source, (920, 610), "#e73144")
        current = digest(source)
        watch.tick()
        self.assertIn("render_a.png", watch.status()["changes"])
        self.assertLessEqual(watch.status()["checked"], 25)
        self.assertEqual(digest(source), current)
        self.assertFalse(watch.stop()["enabled"])
        self.assertFalse(DriftWatch(self.app).status()["enabled"])

    def test_parallel_launch_waits_for_the_authenticated_session(self):
        owner = SessionOwner(self.app.data_dir)
        owner.enter()
        self.addCleanup(owner.close)
        with Navigator(self.app, owner=owner) as navigator:
            run = Thread(target=navigator.serve_forever)
            run.start()
            observed = []
            other = SessionOwner(self.app.data_dir)
            opening = Thread(target=lambda: observed.append(other.enter()))
            opening.start()
            try:
                sleep(.25)
                self.assertTrue(opening.is_alive())
                owner.publish(navigator)
                opening.join(10)
                self.assertEqual(observed, [navigator.url])
                self.assertFalse(other.owns)
            finally:
                navigator.shutdown()
                run.join(5)
                opening.join(10)
                other.close()

    def test_abandoned_browser_lease_closes_the_session(self):
        with Navigator(self.app) as navigator:
            runner = Thread(target=navigator.serve_forever)
            runner.start()
            try:
                with navigator.lock:
                    navigator.attached("fixture-window")
                    navigator.clients["fixture-window"] = monotonic() - 200
                    navigator.service_actions()
                    self.assertEqual(navigator.clients, {})
                    navigator.empty_since = monotonic() - 10
                    navigator.service_actions()
                runner.join(5)
                self.assertFalse(runner.is_alive())
            finally:
                navigator.shutdown()
                runner.join(5)

    def test_playful_age_is_retirement_intent_and_negation_stays_out(self):
        self.assertEqual(explicit_intent("Heartfield Desk is 92 Carecycles past its expiration date, I don't need that design anymore."),
                         "Heartfield Desk")
        self.assertIsNone(explicit_intent("Do not retire Heartfield Desk."))


if __name__ == "__main__":
    unittest.main()
