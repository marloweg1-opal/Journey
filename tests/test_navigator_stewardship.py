"""Scoped evidence, explicit retirement, and the existing Windows action boundary."""

from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock, Thread
import unittest

from PIL import Image
from core.naming_audit import FORMAT, resolve_field, validate_audit
from core.project_registry import PATTERN_FORMAT
from journey_navigator.context import assess, profile_registry
from journey_navigator.conversation import LocalQwen, explicit_intent
from journey_navigator.ocr import LocalOcr
from journey_navigator.patrol import Patrol
from journey_navigator.registry import validate_profile
from journey_navigator.workbench import Workbench
from journey_vision.observe import describe
from test_navigator_context import fingerprint
from test_navigator_registry import sample_image
from test_operational_patrol import FixtureConsent


PROMPT = ('Anything containing “Heartfield Desk” is approximately 92 Carecycles past its expiration date. '
          'Retire it from active use and dispose of the obsolete assets.')
MOON = "💜 CBOS Moonstone_Character_Sheet_06_11.png"


def audit():
    return {"format": FORMAT, "project": "CareBloomOS",
            "subjects": ["Moonstone", "Cloverstone", "Heartstone", "Cloudstone", "Wishstone", "Musicstone", "Corestone"],
            "aliases": {"Corestone": ["Opalstone"]}, "families": [
                {"name": "Character Reference", "terms": ["Character Sheet"]},
                {"name": "Badge", "terms": ["Badge"]}],
            "claims": [], "examples": []}


def cbos_profile():
    return {"format": "journey-project-naming-1", "project": "CareBloomOS",
            "signals": ["CBOS", "Heartfield Desk"], "rules": [
                {"subject": "Moonstone", "purpose": "Character Reference", "prefix": "💜 CBOS Moonstone_Character_Sheet",
                 "extension": ".png", "date_order": "DD_MM", "source": "Explicit Moonstone filename example",
                 "example": {"date": "2026-11-06", "filename": MOON}}],
            "evidence": [{"name": "Heartfield Desk.png", "kind": "reference", "value": "",
                          "source": {"archive": "Authorized evidence fixture", "conversation": "conversation", "message": "message", "role": "user"}}]}


class EvidenceTests(unittest.TestCase):
    def test_unreliable_ocr_never_provides_identity_evidence(self):
        reader = object.__new__(LocalOcr)
        reader.data_args = ()
        reader.version = "synthetic-reader"
        reader.model = "fixture"
        reader._run = lambda *args: "text\tconf\tblock_num\tpar_num\tline_num\ttop\nMoonstone\t48\t1\t1\t1\t0\n"
        output = reader.recognize(Image.new("RGBA", (64, 32), "white"))
        self.assertEqual(output["status"], "unreliable")
        root = Path.cwd()
        record = assess(profile_registry(), root / "untitled.png", root,
                        {"digest": "fixture", "features": describe(Image.new("RGBA", (64, 32), "white"))}, ({}, {}), {}, output)
        self.assertEqual(record["identity"]["state"], "unknown")

    def test_explicit_scope_supersession_preserves_both_sources_and_conflicts(self):
        def evidence(identifier, tier, value, role, day, **extra):
            return {"id": identifier, "tier": tier, "subject": "Heartstone", "family": "Badge",
                    "dimension": "marker", "value": value,
                    "source": {"role": role, "locator": identifier, "authored": f"2026-11-{day:02}T12:00:00+00:00"}, **extra}

        draft = evidence("assistant", "H", "💖", "assistant", 4)
        correction = evidence("owner", "A", "🩷", "user", 5, supersedes="assistant")
        doc = audit() | {"claims": [draft, correction]}
        claims = validate_audit(doc)["claims"]
        result = resolve_field(claims, "Heartstone", "Badge", "marker")
        self.assertEqual(result["value"], "🩷")
        self.assertTrue(result["proof"][0]["superseded"])
        self.assertEqual(resolve_field(claims, "Heartstone", "Character Reference", "marker")["state"], "UNKNOWN")
        doc["claims"].append(evidence("file", "E", "💗", "current_file", 6))
        self.assertEqual(resolve_field(validate_audit(doc)["claims"], "Heartstone", "Badge", "marker")["state"], "CONFLICTED")
        invalid = correction | {"family": "Character Reference"}
        with self.assertRaisesRegex(ValueError, "same dimension and scope"):
            validate_audit(audit() | {"claims": [draft, invalid]})

    def test_other_projects_can_use_different_patterns_without_widening_legacy_rules(self):
        profile = {"format": PATTERN_FORMAT, "project": "Fixture project", "signals": ["FICT"], "rules": [
            {"subject": "Blue", "purpose": "Badge", "pattern": "Blue_Badge_FICT",
             "extension": ".png", "date_order": "NONE", "source": "Synthetic owner review",
             "example": {"filename": "Blue_Badge_FICT.png"}},
            {"subject": "Green", "purpose": "Badge", "pattern": "Green_{date}_FICT",
             "extension": ".png", "date_order": "YYYY-MM-DD", "source": "Synthetic owner review",
             "example": {"date": "2026-11-06", "filename": "Green_2026-11-06_FICT.png"}}]}
        result = validate_profile(profile)
        self.assertEqual(result["rules"][0]["date_order"], "NONE")
        self.assertIsNone(result["rules"][0]["example"]["date"])
        self.assertEqual(validate_profile(cbos_profile())["rules"][0]["example"]["filename"], MOON)
        profile["rules"][1]["pattern"] = "{date.__class__}"
        with self.assertRaisesRegex(ValueError, "one date field"):
            validate_profile(profile)

    def test_qwen_receives_only_the_live_instruction_and_returns_no_tools(self):
        requests = []
        proposed = {"action": "retire_family", "family": "Heartfield Desk"}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                requests.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                body = json.dumps({"message": {"content": json.dumps(proposed)}}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = Thread(target=server.serve_forever)
            thread.start()
            try:
                interpreter = LocalQwen(port=server.server_port)
                self.assertEqual(interpreter.interpret(PROMPT), {"state": "CANDIDATE", "family": "Heartfield Desk"})
                proposed["family"] = "Another Project"
                self.assertEqual(interpreter.interpret(PROMPT)["state"], "NEEDS_HUMAN_DECISION")
                self.assertEqual(interpreter.interpret("Don't retire Heartfield Desk.")["state"], "NEEDS_HUMAN_DECISION")
            finally:
                server.shutdown()
                thread.join()
        route, request = requests[0]
        self.assertEqual(route, "/api/chat")
        self.assertEqual(request["model"], "qwen3:4b")
        self.assertEqual(request["messages"][-1], {"role": "user", "content": PROMPT})
        self.assertNotIn("tools", request)
        self.assertEqual(explicit_intent(PROMPT), "Heartfield Desk")
        self.assertIsNone(explicit_intent('Suppose we retire “Heartfield Desk”.'))


class StewardshipTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="journey-stewardship-")
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.source = self.base / "Selected project"
        self.source.mkdir()
        self.archive = self.source / "Archive"
        self.archive.mkdir()
        self.history = self.source / "Heartfield Desk decision history.md"
        self.history.write_text("Historical note concerning Heartfield Desk.png", encoding="utf-8")
        self.image = self.source / "Heartfield Desk.png"
        sample_image(self.image, "purple")
        self.copy = self.source / "Heartfield Desk alternate copy.png"
        self.copy.write_bytes(self.image.read_bytes())
        sample_image(self.source / "Carefield Desk.png", "green")
        sample_image(self.source / MOON, "blue", created="2026-11-06")
        sample_image(self.source / "Musicstone Badge.png", "red")
        self.app = Workbench(self.base / "Local checkpoint")
        self.addCleanup(self.app.close)
        self.job = self.app.select(self.source, proposals=True)["job"]
        self.app.project_registry.activate(self.job, cbos_profile())
        self.scan()
        self.patrol = Patrol(self.app, RLock(), approver=FixtureConsent())
        self.addCleanup(self.patrol.close)
        self.destination = self.patrol.create(self.job, "Review obsolete designs", "Project continuity",
                                              "The retired design and its history are traceable")["id"]
        self.service = self.patrol.stewardship

    def scan(self):
        for _ in range(30):
            summary = self.app.step(self.job)
            if not summary["pending"] and not summary["pending_folders"]:
                return
        self.fail("Fixture inventory did not finish.")

    def review(self):
        result = self.service.plan(self.destination, PROMPT, read_references=True)
        self.assertEqual(result["state"], "AWAITING_REVIEW")
        return result

    def choose(self, review, path):
        return next(item["id"] for item in review["entries"] if item["path"] == str(path))

    def confirm(self, review, chosen):
        return self.service.confirm(self.destination, review["binding"], [chosen],
                                    "Superseded by the current desk system", "Current desk system")

    def test_carebloom_filename_proof_and_project_separation(self):
        self.app.project_audit.activate(self.job, audit())
        result = self.app.project_audit.view(self.job)
        self.assertEqual(len(result["items"]), 14)
        rows = {(item["subject"], item["family"]): item for item in result["items"]}
        self.assertEqual(rows["Moonstone", "Character Reference"]["state"], "VERIFIED_FILENAME_EXEMPLAR")
        self.assertEqual(rows["Musicstone", "Badge"]["state"], "CANDIDATE")
        self.assertEqual(rows["Wishstone", "Badge"]["state"], "UNKNOWN")
        music = next(row for row in self.app.images(self.job, 0)["items"] if row["filename"] == "Musicstone Badge.png")
        self.assertEqual(music["identity"]["label"], "Musicstone")
        with self.assertRaisesRegex(ValueError, "another project"):
            self.app.project_audit.activate(self.job, audit() | {"project": "Welfare Witchcraft"})
        other = self.base / "Separate project"
        other.mkdir()
        sample_image(other / "Musicstone Badge.png", "red")
        job = self.app.select(other, proposals=True)["job"]
        self.app.project_registry.activate(job, {"format": PATTERN_FORMAT, "project": "Welfare Witchcraft",
                                                "signals": ["Welfare Witchcraft"], "rules": []})
        self.app.step(job)
        self.assertEqual(self.app.images(job, 0)["items"][0]["identity"]["state"], "unknown")

    def test_new_audit_correction_holds_an_already_prepared_rename(self):
        source = self.source / "Moonstone Character Sheet import.png"
        sample_image(source, "yellow", created="2026-11-07")
        self.app.refresh(self.job)
        self.scan()
        image = next(item for item in self.app.images(self.job, 0)["items"] if item["path"] == str(source))
        self.app.review(self.job, image["id"], "confirm", "Moonstone", "Character Reference")
        target = self.source / MOON.replace("06_11", "07_11")
        batch = self.patrol.guided.prepare(self.job, [{"kind": "rename", "asset": image["id"], "destination": str(target)}])
        late = {"id": "date-correction", "tier": "A", "subject": "Moonstone", "family": "Character Reference",
                "dimension": "date", "value": "YYYY-MM-DD", "source": {"role": "user", "locator": "Synthetic scoped correction"}}
        self.app.project_audit.activate(self.job, audit() | {"claims": [late]})
        with self.assertRaisesRegex(ValueError, "disagrees with accepted audit evidence"):
            self.patrol.guided.begin_approval(batch["id"])
        self.assertTrue(source.exists())
        self.assertFalse(target.exists())

    def test_grouped_retirement_preserves_history_and_copy_identity(self):
        config = self.source / "current-desk.ini"
        config.write_text("[main]\nimage=Heartfield Desk.png", encoding="utf-8")
        before = fingerprint(self.source)
        result = self.review()
        entries = {item["path"]: item for item in result["entries"]}
        self.assertEqual(entries[str(self.history)]["group"], "historical_reference")
        self.assertNotIn(str(self.source / "Carefield Desk.png"), entries)
        self.assertTrue(entries[str(self.image)]["physical_blocker"])
        self.assertIn(str(self.copy), entries[str(self.image)]["copy_paths"])
        self.assertTrue(result["archive_evidence"])
        with self.assertRaisesRegex(ValueError, "Historical references"):
            self.confirm(result, self.choose(result, self.history))
        selected = self.choose(result, self.image)
        decision = self.confirm(result, selected)
        self.assertEqual(self.confirm(result, selected)["decision"], decision["decision"])
        self.assertEqual(self.app.conn.execute("SELECT count(*) FROM stewardship_retirements").fetchone()[0], 1)
        images = {item["path"]: item for item in self.app.images(self.job, 0)["items"]}
        self.assertEqual(images[str(self.image)]["metadata"]["lifecycle"], "retired")
        self.assertEqual(images[str(self.copy)]["metadata"]["retirements"], [])
        with self.assertRaisesRegex(PermissionError, "current configuration"):
            self.service.archive(self.destination, result["binding"], [selected], decision["decision"], self.archive)
        self.assertEqual(fingerprint(self.source), before)
        self.assertIn("Historical note", self.history.read_text())

    def test_new_reference_blocks_an_already_reviewed_batch(self):
        result = self.review()
        selected = self.choose(result, self.image)
        decision = self.confirm(result, selected)
        batch = self.service.archive(self.destination, result["binding"], [selected], decision["decision"], self.archive)
        binding, description = self.patrol.guided.begin_approval(batch["id"])
        self.patrol.guided.accept(batch["id"], FixtureConsent().verify(binding, description))
        (self.source / "new-dependent.ini").write_text("[current]\nsource=Heartfield Desk.png", encoding="utf-8")
        result = self.patrol.guided.step(batch["id"])
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(self.image.exists())
        self.assertFalse((self.archive / self.image.name).exists())

    def test_forgotten_scope_invalidates_drafts_and_removes_derived_evidence(self):
        result = self.review()
        selected = self.choose(result, self.image)
        self.confirm(result, selected)
        self.app.project_audit.activate(self.job, audit())
        self.app.revoke(self.job, str(self.source), "retain")
        with self.assertRaises(ValueError):
            self.confirm(result, selected)
        for table in ("stewardship_retirements", "project_naming_audits"):
            self.assertEqual(self.app.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0], 0)
        self.assertTrue(self.image.exists())

    @unittest.skipUnless(os.name == "nt", "Native no-overwrite archive and reversal")
    def test_account_reviewed_archive_and_reversal_preserve_the_registry(self):
        before = sha256(self.image.read_bytes()).hexdigest()
        review = self.review()
        selected = self.choose(review, self.image)
        decision = self.confirm(review, selected)
        batch = self.service.archive(self.destination, review["binding"], [selected], decision["decision"], self.archive)
        self.assertTrue(self.image.exists())
        binding, description = self.patrol.guided.begin_approval(batch["id"])
        self.patrol.guided.accept(batch["id"], FixtureConsent().verify(binding, description))
        result = self.patrol.guided.step(batch["id"])
        self.assertEqual(result["status"], "completed", result)
        archived = self.archive / self.image.name
        self.assertEqual(sha256(archived.read_bytes()).hexdigest(), before)
        self.scan()
        image = next(item for item in self.app.images(self.job, 0)["items"] if item["path"] == str(archived))
        self.assertEqual(image["metadata"]["retirements"][0]["replacement"], "Current desk system")
        undo = self.patrol.guided.prepare_undo(self.job, result["progress"][0]["receipt"])
        binding, description = self.patrol.guided.begin_approval(undo["id"])
        self.patrol.guided.accept(undo["id"], FixtureConsent().verify(binding, description))
        result = self.patrol.guided.step(undo["id"])
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(sha256(self.image.read_bytes()).hexdigest(), before)
        self.assertTrue(self.history.exists())
