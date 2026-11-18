"""Integrated acceptance for the real authenticated HTTP routes on disposable copies."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from journey_navigator import workbench
from tools.demo_carebloom_collection import make_demo
from tools.demo_conversation_integration import (
    ADVICE_QUERY, ASSET, HISTORY_QUERY, LEGACY_FIND_BASELINE, MODEL_IDS, PANEL_MESSAGE, ApprovalSpy,
    FakeModels, LegacyInterpreterSpy, converse, destination, import_history, inspect, request,
    running_navigator, select, snapshot,
)


COUNCIL_QUERY = "Ask the full Council to review the selected collection."
INTERPRETED_QUERY = "For Moonstone, could you surface the relevant sheet?"
OTHER_ASSET = "ForeignRootSentinel.png"


class ConversationIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="journey-conversation-acceptance-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.fixture = self.base / "Fixture"
        self.collection, self.exports, self.pack = make_demo(self.fixture)
        self.other = self.fixture / "Separate private collection"
        self.other.mkdir()
        copyfile(self.collection / ASSET, self.other / OTHER_ASSET)
        self.store = self.base / "Checkpoint"
        self.models = FakeModels()
        self.approval = ApprovalSpy()
        self.legacy = LegacyInterpreterSpy()

    def navigator(self):
        return running_navigator(self.store, self.models, approver=self.approval, interpreter=self.legacy)

    def prepare(self, server, *, history=False, retain=True):
        job = select(server, self.collection, retain=retain)
        summary, _ = inspect(server, job)
        self.assertEqual(summary["analyzed"], 10)
        if history:
            import_history(server, job, self.exports, self.pack)
        return job

    def test_identity_capabilities_and_permissions_reflect_runtime_without_inference(self):
        with self.navigator() as server:
            build = request(server, "build")
            for prompt in ("Who are you?", "What build is running?"):
                with self.subTest(prompt=prompt):
                    result = converse(server, prompt, use_model=True, share_evidence=True)
                    self.assertEqual((result["intent"], result["state"]), ("identity", "COMPLETE"))
                    self.assertEqual(result["identity"]["name"], "Journey")
                    self.assertEqual(result["identity"]["runtime"],
                                     {field: build[field] for field in (
                                         "application", "version", "commit", "build", "installation", "session")})
                    self.assertEqual(result["metrics"]["calls"], 0)
            result = converse(server, "What can you do?", use_model=True, share_evidence=True)
            self.assertEqual((result["intent"], result["state"]), ("capabilities", "COMPLETE"))
            capabilities = {route["id"]: route for route in result["capabilities"]}
            self.assertEqual(capabilities["find"]["availability"], "requires_active_inspection")
            self.assertIn("readiness_not_verified", capabilities["guided"]["availability"])
            self.assertEqual(result["metrics"]["calls"], 0)
            result = converse(server, "What permissions do you have?", use_model=True, share_evidence=True)
            self.assertEqual((result["intent"], result["state"]), ("permissions", "COMPLETE"))
            self.assertEqual(result["authority"]["inspection"], "not_granted")
            self.assertFalse(result["authority"]["source_mutation_via_conversation"])
            self.assertEqual(result["metrics"]["calls"], 0)
            status = converse(server, "What do you remember?", use_model=True)
            self.assertIsNone(status["summary"])
            self.assertEqual(status["knowledge"]["history_messages"], 0)
            missing = converse(server, "Inspect the selected folder.", use_model=True)
            self.assertEqual(missing["state"], "NEEDS_SCOPE")
            self.assertEqual(self.models.calls, [])
            self.assertEqual(self.legacy.calls, [])

    def test_inspection_uses_bounded_existing_scope_and_find_needs_no_model(self):
        for index in range(workbench.IMAGE_BATCH + 2):
            copyfile(self.collection / ASSET, self.collection / f"Bounded inventory copy {index:03}.png")
        before = snapshot(self.fixture)
        with self.navigator() as server:
            job = select(server, self.collection)
            original = workbench.image_bytes

            def scoped_reader(path, *args, **kwargs):
                self.assertTrue(Path(path).is_relative_to(self.collection), f"Unexpected image read: {path}")
                return original(path, *args, **kwargs)

            with patch.object(workbench, "image_bytes", side_effect=scoped_reader) as opened:
                summary, steps = inspect(server, job)
                self.assertGreater(opened.call_count, 0)
            self.assertEqual(summary["analyzed"], 10 + workbench.IMAGE_BATCH + 2)
            self.assertEqual(steps[0], "IN_PROGRESS")
            self.assertEqual(steps[-1], "COMPLETE")
            self.assertEqual(summary, request(server, "summary", job=job))
            permission = converse(server, "What permissions do you have?", job=job)["authority"]
            self.assertEqual(permission["inspection"], "selected_scope_only")
            recorded = request(server, "permissions", job=job)["scopes"]
            self.assertEqual([row["path"] for row in permission["scopes"]], [row["path"] for row in recorded])
            self.assertTrue(all(row["effective_inspect"] and row["recorded_inspect"] for row in permission["scopes"]))
            self.assertFalse(permission["scopes"][0]["execute"])
            found = converse(server, "Find Moonstone", job=job, use_model=True)
            self.assertEqual(found["metrics"]["calls"], 0)
            asset = next(row for row in found["results"] if row["title"] == ASSET)
            self.assertEqual(asset["summary"], str(self.collection / ASSET))
            self.assertEqual(asset["group"], "INSPECTED FILES")
            self.assertEqual(converse(server, f"Find {OTHER_ASSET}", job=job)["results"], [])
            key = destination(server, job)
            equivalent = request(server, "goal-plan", destination=key, instruction="Find Moonstone",
                                 use_model=True)
            self.assertEqual(equivalent["results"], found["results"])
            self.assertEqual(LEGACY_FIND_BASELINE["interpreter_calls"], 1)
            self.assertEqual(self.legacy.calls, [])
            self.assertEqual(self.models.calls, [])
        self.assertEqual(snapshot(self.fixture), before)

    def test_retained_checkpoint_reopens_with_attributed_deduplicated_history(self):
        before = snapshot(self.fixture)
        with self.navigator() as server:
            job = self.prepare(server)
            self.assertEqual(converse(server, HISTORY_QUERY, job=job)["state"], "HISTORY_NOT_CONFIGURED")
            status = import_history(server, job, self.exports, self.pack)
            self.assertEqual(len(status["files"]), 2)
            self.assertFalse(status["monitor"]["enabled"])
            result = converse(server, HISTORY_QUERY, job=job, use_model=True)
            self.assertEqual(result["state"], "COMPLETE")
            self.assertEqual(result["metrics"]["calls"], 0)
            self.assertEqual(len(result["results"]), 1)
            reference = result["results"][0]
            self.assertEqual((reference["message"], reference["role"]), (PANEL_MESSAGE, "user"))
            self.assertIn("render_17.png", reference["excerpt"])
            self.assertIn(reference["name"], {path.name for path in self.exports.iterdir()})
            authored = datetime.fromisoformat(reference["authored"])
            imported = datetime.fromisoformat(reference["imported"])
            self.assertNotEqual(authored, imported)
            original = converse(server, "What do you remember?", job=job)
            session = request(server, "build")["session"]
        with self.navigator() as reopened:
            saved = {row["id"] for row in request(reopened, "jobs")["items"]}
            self.assertIn(job, saved)
            current = converse(reopened, "What do you remember?", job=job)
            self.assertNotEqual(request(reopened, "build")["session"], session)
            self.assertEqual(original["summary"], current["summary"])
            self.assertEqual(current["knowledge"]["history_messages"], 3)
            self.assertTrue(current["knowledge"]["retained_checkpoint"])
            self.assertEqual(current["knowledge"]["conversation_transcript"], "not_saved")
            self.assertEqual(converse(reopened, HISTORY_QUERY, job=job)["results"], result["results"])
            self.assertEqual(self.models.calls, [])
        self.assertEqual(snapshot(self.fixture), before)

    def test_novel_words_call_interpreter_once_and_fabricated_terms_are_refused(self):
        with self.navigator() as server:
            job = self.prepare(server)
            refused = converse(server, INTERPRETED_QUERY, job=job)
            self.assertEqual(refused["state"], "NEEDS_CLARIFICATION")
            self.assertEqual(self.models.calls, [])
            result = converse(server, INTERPRETED_QUERY, job=job, use_model=True)
            self.assertEqual((result["intent"], result["state"]), ("find", "COMPLETE"))
            self.assertEqual(result["metrics"]["calls"], 1)
            self.assertEqual([call["kind"] for call in self.models.calls], ["interpret"])
            self.assertIn(ASSET, {row["title"] for row in result["results"]})

            self.models.term = ASSET
            refused = converse(server, INTERPRETED_QUERY, job=job, use_model=True)
            self.assertEqual(refused["state"], "NEEDS_CLARIFICATION")
            self.assertNotIn("results", refused)
            self.assertEqual([call["kind"] for call in self.models.calls], ["interpret", "interpret"])

    def test_per_request_consent_and_bounded_evidence_for_attributed_advice(self):
        with self.navigator() as server:
            job = self.prepare(server, history=True)
            denied = converse(server, COUNCIL_QUERY, job=job, share_evidence=True)
            self.assertEqual(denied["state"], "LOCAL_MODEL_CONSENT_REQUIRED")
            self.assertEqual(self.models.calls, [])

            private = converse(server, ADVICE_QUERY, job=job, use_model=True)
            private_context = self.models.calls[-1]["context"]
            encoded = json.dumps(private_context)
            for filename in self.collection.iterdir():
                self.assertNotIn(filename.name, encoded)
            for secret in (str(self.collection), str(self.base), PANEL_MESSAGE, "interface layout",
                           "conversations-001.json", "conversations-002.json"):
                self.assertNotIn(secret, encoded)
            explicit = converse(server, ADVICE_QUERY, job=job, use_model=True, share_evidence=True)
            shared = self.models.calls[-1]["context"]
            evidence = shared["evidence"]
            names = {row["value"]["filename"] for row in evidence if row["kind"] == "inspected_asset"}
            excerpts = [row["value"] for row in evidence if row["kind"] == "imported_history_excerpt"]
            self.assertTrue(names)
            self.assertLessEqual(len(names), 6)
            self.assertTrue(names <= {path.name for path in self.collection.iterdir()})
            self.assertEqual([row["message"] for row in excerpts], [PANEL_MESSAGE])
            self.assertIn("interface layout", excerpts[0]["excerpt"])
            self.assertNotIn(str(self.collection), json.dumps(shared))
            self.assertTrue(explicit["metrics"]["shared_evidence_excerpts"])
            self.assertFalse(private["metrics"]["shared_evidence_excerpts"])

            default = converse(server, "Advise on the selected collection.", job=job, use_model=True)
            council = converse(server, COUNCIL_QUERY, job=job, use_model=True)
            self.assertEqual([call["members"] for call in self.models.calls],
                             [("Phi",), ("Phi",), ("Qwen",), tuple(MODEL_IDS)])
            for result, members in ((private, ["Phi"]), (explicit, ["Phi"]), (default, ["Qwen"]),
                                    (council, list(MODEL_IDS))):
                with self.subTest(members=members):
                    self.assertEqual(result["state"], "REVIEW_REQUIRED")
                    self.assertEqual(result["metrics"]["calls"], len(members))
                    self.assertEqual(result["metrics"]["retries"], 0)
                    self.assertEqual(result["council"]["assessment"]["authority"], False)
                    self.assertTrue(result["council"]["assessment"]["human_review_required"])
                    present = {row["id"] for row in result["evidence"]}
                    self.assertEqual([(row["member"], row["model"]) for row in result["council"]["members"]],
                                     [(name, MODEL_IDS[name]) for name in members])
                    for row in result["council"]["members"]:
                        self.assertTrue(set(row["contribution"]["evidence_ids"]) <= present)
            self.assertEqual(self.approval.calls, [])

    def test_model_discovery_requires_local_consent_and_spends_no_inference(self):
        with self.navigator() as server:
            held = converse(server, "Show local models.")
            self.assertEqual(held["state"], "LOCAL_MODEL_CONSENT_REQUIRED")
            self.assertEqual(self.models.calls, [])
            available = converse(server, "Show local models.", use_model=True)
            self.assertEqual(available["models"]["state"], "AVAILABLE")
            self.assertEqual(available["metrics"]["calls"], 0)
            self.assertEqual(available["metrics"]["tag_calls"], 1)
            self.assertFalse(available["metrics"]["shared_evidence_excerpts"])
            self.assertEqual([call["kind"] for call in self.models.calls], ["status"])
            self.assertEqual([(row["member"], row["model"]) for row in available["models"]["members"]],
                             list(MODEL_IDS.items()))

    def test_revocation_while_inference_is_blocked_is_lock_free_and_discards_result(self):
        before = snapshot(self.fixture)
        with self.navigator() as server:
            job = self.prepare(server)
            other_job = select(server, self.other)
            inspect(server, other_job)
            self.models.blocked = True
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(converse, server, INTERPRETED_QUERY, job=job, use_model=True,
                                      share_evidence=True, timeout=12)
                try:
                    self.assertTrue(self.models.entered.wait(3), "The fixture interpreter never started")
                    grants = request(server, "permissions", job=job, timeout=2)
                    self.assertTrue(grants["scopes"][0]["inspect"])
                    current = request(server, "revoke", job=job, scope=str(self.collection),
                                      permission="inspect", timeout=2)
                    self.assertTrue(current["closed"])
                    revoked = request(server, "permissions", job=job, timeout=2)
                    self.assertFalse(revoked["scopes"][0]["inspect"])
                    self.assertEqual(converse(server, f"Find {OTHER_ASSET}", job=other_job)["state"], "COMPLETE")
                    self.assertFalse(pending.done(), "The model response must still be blocked")
                finally:
                    self.models.release.set()
                result = pending.result(timeout=4)
            self.assertEqual(result["state"], "STALE_CONTEXT")
            self.assertEqual(result["metrics"]["calls"], 1)
            self.assertNotIn("results", result)
            self.assertNotIn(ASSET, json.dumps(result))
            self.assertNotIn(OTHER_ASSET, json.dumps(self.models.calls[0]["context"]))
            denied = converse(server, "Find Moonstone.", job=job, expected=403)
            self.assertNotIn("results", denied)
            self.assertEqual(len(self.models.calls), 1)
            self.assertEqual(self.models.sends, [("interpret", "Qwen")])
            self.assertEqual(self.approval.calls, [])
        self.assertEqual(snapshot(self.fixture), before)

    def test_review_and_history_changes_discard_in_flight_advice(self):
        for change, retain in (("review", True), ("history-forget", True), ("review", False)):
            with self.subTest(change=change, retain=retain), running_navigator(
                self.base / f"{change}-{retain}", self.models
            ) as server:
                job = self.prepare(server, history=retain, retain=retain)
                candidate = next(row for row in request(server, "images", job=job)["items"]
                                 if row["filename"] == ASSET)
                self.models.entered.clear()
                self.models.release.clear()
                self.models.blocked = True
                before = len(self.models.sends)
                ask_council = change == "history-forget"
                prompt = 'Ask the full Council about "CareRail".' if ask_council else ADVICE_QUERY
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pending = pool.submit(converse, server, prompt, job=job, use_model=True,
                                          share_evidence=ask_council, timeout=12)
                    try:
                        self.assertTrue(self.models.entered.wait(3), "The fixture advisor never started")
                        if change == "review":
                            request(server, "review", job=job, asset=candidate["id"], decision="confirm",
                                    label="Moonstone", timeout=2)
                        else:
                            status = request(server, "history-forget", job=job, timeout=2)
                            self.assertEqual(status["unique_messages"], 0)
                        self.assertFalse(pending.done())
                    finally:
                        self.models.release.set()
                    result = pending.result(timeout=4)
                self.assertEqual(result["state"], "STALE_CONTEXT")
                self.assertEqual(result["metrics"]["calls"], 1)
                self.assertNotIn("council", result)
                self.assertNotIn("evidence", result)
                self.assertEqual(self.models.sends[before:], [("review", "Qwen" if ask_council else "Phi")])

    def test_negated_and_hypothetical_requests_create_no_work_or_retirement_plan(self):
        before = snapshot(self.fixture)
        with self.navigator() as server:
            job = select(server, self.collection)
            key = destination(server, job)
            summary = request(server, "summary", job=job)
            for prompt in ("Do not inspect this folder.", "Do not retire Moonstone.",
                           "What if we retire Moonstone?"):
                with self.subTest(prompt=prompt):
                    result = converse(server, prompt, job=job, destination=key, use_model=True)
                    self.assertEqual(result["state"], "NEEDS_CLARIFICATION")
                    self.assertNotIn("binding", result)
                    self.assertEqual(result["metrics"]["calls"], 0)
            self.assertEqual(self.models.sends, [])

            self.models.intent = "retire"
            self.models.family = "Moonstone"
            self.models.term = None
            suggested = converse(server, "What might happen to Moonstone in a future retirement?",
                                  job=job, destination=key, use_model=True)
            self.assertEqual(suggested["state"], "NEEDS_CLARIFICATION")
            self.assertNotIn("binding", suggested)
            self.assertEqual(self.models.sends, [("interpret", "Qwen")])
            self.assertEqual(request(server, "summary", job=job), summary)
            self.assertEqual(request(server, "patrol-status", destination=key)["batches"], [])
            self.assertEqual(self.approval.calls, [])
        self.assertEqual(snapshot(self.fixture), before)

    def test_scope_session_and_mutation_boundaries_do_not_reach_executor(self):
        before = snapshot(self.fixture)
        with self.navigator() as server:
            job = self.prepare(server)
            other_job = select(server, self.other)
            inspect(server, other_job)
            key, other_key = destination(server, job), destination(server, other_job)
            for invalid in ({"session": "wrong-token"}, {"origin": "https://invalid.example"}):
                with self.subTest(invalid=invalid):
                    self.assertIn("error", converse(server, COUNCIL_QUERY, job=job, use_model=True,
                                                    expected=403, **invalid))
            mismatch = converse(server, "Organize the selected folder.", job=job, destination=other_key,
                                use_model=True, expected=403)
            self.assertNotIn("results", mismatch)
            self.assertNotIn(str(self.other), json.dumps(mismatch))
            grants = request(server, "permissions", job=job)
            for prompt in ("Delete Moonstone.", "Rename Moonstone.", "Move Moonstone.",
                           "Approve the batch.", "Grant unattended execution."):
                with self.subTest(prompt=prompt):
                    held = converse(server, prompt, job=job, destination=key, use_model=True,
                                    share_evidence=True)
                    self.assertEqual(held["state"], "REVIEW_REQUIRED")
                    self.assertEqual(held["metrics"]["calls"], 0)
            self.assertEqual(request(server, "permissions", job=job), grants)
            for current in (key, other_key):
                work = request(server, "patrol-status", destination=current)
                self.assertEqual(work["batches"], [])
                self.assertEqual(work["history"], [])
                self.assertEqual(work["metrics"]["physical_verified"], 0)
                self.assertTrue(all(task["attempts"] == 0 for task in work["tasks"]))
            self.assertEqual(self.models.calls, [])
            self.assertEqual(self.approval.calls, [])
        self.assertEqual(snapshot(self.fixture), before)

    def test_ephemeral_selection_runs_read_only_inspection_without_saved_destination(self):
        before = snapshot(self.fixture)
        with self.navigator() as server:
            job = self.prepare(server, retain=False)
            self.assertTrue(job.startswith("session-"))
            self.assertEqual(request(server, "jobs")["items"], [])
            status = converse(server, "What do you remember?", job=job)
            self.assertFalse(status["knowledge"]["retained_checkpoint"])
            kept = converse(server, "Organize the selected folder.", job=job, use_model=True)
            self.assertEqual(kept["state"], "NEEDS_CHECKPOINT")
            found = converse(server, "Find Moonstone", job=job, use_model=True)
            self.assertIn(ASSET, {row["title"] for row in found["results"]})
            self.assertEqual(self.models.calls, [])
        with self.navigator() as reopened:
            self.assertEqual(request(reopened, "jobs")["items"], [])
            self.assertIn("error", converse(reopened, "Find Moonstone", job=job, expected=400))
        self.assertEqual(snapshot(self.fixture), before)


if __name__ == "__main__":
    unittest.main()
