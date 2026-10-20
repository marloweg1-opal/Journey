import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.conversation_ingest import (  # noqa: E402
    candidate_key,
    extract_candidates,
    ingest_conversation,
    load_conversation,
)
from db.database import initialize_schema  # noqa: E402


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "project_ark_normalized_conversation.json"
TEST_OUTPUT = Path(tempfile.gettempdir()) / "mini_ark_conversation_ingest_test_review.json"


class ConversationIngestTests(unittest.TestCase):
    def make_conn(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        initialize_schema(conn)
        return conn

    def require_private_fixture(self):
        if not FIXTURE.exists():
            self.skipTest("private conversation fixture is not included in the public archive")

    def test_extracts_pmm_pwm_candidates_with_stable_keys(self):
        self.require_private_fixture()
        conversation, _ = load_conversation(FIXTURE)

        first = extract_candidates(conversation)
        second = extract_candidates(conversation)

        self.assertGreaterEqual(len(first), 6)
        self.assertEqual(
            [candidate["candidate_key"] for candidate in first],
            [candidate["candidate_key"] for candidate in second],
        )
        self.assertTrue(any(c["model"] == "PMM" for c in first))
        self.assertTrue(any(c["model"] == "PWM" for c in first))
        self.assertTrue(any(c["confidence"] == "TENTATIVE" for c in first))
        self.assertTrue(any("Project ARK" in c["scope"] for c in first))

    def test_candidate_key_is_deterministic(self):
        a = candidate_key("conv", 1, 2, "PMM", "Constraint", "Do not create open_loops yet.")
        b = candidate_key("conv", 1, 2, "PMM", "Constraint", "Do not create open_loops yet.")
        c = candidate_key("conv", 1, 3, "PMM", "Constraint", "Do not create open_loops yet.")

        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_ingest_preserves_raw_and_stops_at_review_json(self):
        self.require_private_fixture()
        conn = self.make_conn()
        before_events = conn.execute("SELECT COUNT(*) FROM events;").fetchone()[0]
        before_proposals = conn.execute("SELECT COUNT(*) FROM proposals;").fetchone()[0]
        before_open_loops = conn.execute("SELECT COUNT(*) FROM open_loops;").fetchone()[0]
        raw_text = FIXTURE.read_text(encoding="utf-8")

        if TEST_OUTPUT.exists():
            TEST_OUTPUT.unlink()
        try:
            result = ingest_conversation(conn, FIXTURE, output_path=TEST_OUTPUT)
            review = json.loads(TEST_OUTPUT.read_text(encoding="utf-8"))
        finally:
            if TEST_OUTPUT.exists():
                TEST_OUTPUT.unlink()

        self.assertEqual(result["status"], "review_written")
        self.assertGreater(result["candidate_count"], 0)
        self.assertEqual(review["summary"]["canonical_promotion"], False)
        self.assertEqual(review["summary"]["proposals_created"], False)
        self.assertEqual(review["summary"]["open_loops_created"], False)
        self.assertTrue(all("confidence" in c and "state" in c and "status" in c for c in review["candidates"]))

        handoff = conn.execute("SELECT raw_json FROM handoffs WHERE id=?;", (result["handoff_id"],)).fetchone()
        self.assertEqual(handoff["raw_json"], raw_text)

        self.assertEqual(conn.execute("SELECT COUNT(*) FROM events;").fetchone()[0], before_events)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM proposals;").fetchone()[0], before_proposals)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM open_loops;").fetchone()[0], before_open_loops)

    def test_proposed_move_is_not_treated_as_completed_move(self):
        self.require_private_fixture()
        conversation, _ = load_conversation(FIXTURE)
        candidates = extract_candidates(conversation)

        proposed = [c for c in candidates if "proposed move" in c["what"].lower()]
        occurred = [c for c in candidates if "quarantined 29" in c["what"].lower()]

        self.assertTrue(proposed)
        self.assertTrue(occurred)
        self.assertEqual(proposed[0]["model"], "PMM")
        self.assertEqual(proposed[0]["category"], "Principle")
        self.assertEqual(occurred[0]["model"], "PWM")
        self.assertIn("proposed move is not evidence", proposed[0]["what"].lower())
        self.assertIn("quarantined 29", occurred[0]["what"].lower())
        self.assertEqual(occurred[0]["confidence"], "INFERRED")

    def test_assertion_semantics_outrank_concrete_nouns(self):
        self.require_private_fixture()
        conversation, _ = load_conversation(FIXTURE)
        candidates = extract_candidates(conversation)

        by_text = {c["what"]: c for c in candidates}
        self.assertEqual(
            by_text["Preserve raw input in handoffs.raw_json if the current schema allows it cleanly."]["model"],
            "PMM",
        )
        self.assertEqual(
            by_text["Add deterministic candidate_key values now."]["category"],
            "Decision",
        )
        self.assertEqual(by_text["Stop at review JSON."]["model"], "PMM")

    def test_mixed_sentence_splits_epistemic_levels(self):
        self.require_private_fixture()
        conversation, _ = load_conversation(FIXTURE)
        candidates = extract_candidates(conversation)

        future = [c for c in candidates if c["what"] == "Maybe later Project ARK could use embeddings"]
        boundary = [c for c in candidates if c["what"] == "Embeddings are not part of Diet v0.1."]

        self.assertEqual(len(future), 1)
        self.assertEqual(len(boundary), 1)
        self.assertEqual(future[0]["confidence"], "TENTATIVE")
        self.assertEqual(boundary[0]["confidence"], "CONFIRMED")
        self.assertEqual(boundary[0]["category"], "Constraint")

    def test_clause_split_preserves_demonstrative_antecedent(self):
        conversation = {
            "id": "antecedent-fixture",
            "platform": "ChatGPT",
            "source_container": "Project ARK",
            "messages": [
                {
                    "role": "user",
                    "content": "Maybe later Project ARK could use embeddings, but that is not part of Diet v0.1.",
                    "timestamp": None,
                }
            ],
        }

        candidates = extract_candidates(conversation)
        self.assertTrue(any(c["what"] == "Maybe later Project ARK could use embeddings" for c in candidates))
        self.assertTrue(any(c["what"] == "Embeddings are not part of Diet v0.1." for c in candidates))
        self.assertFalse(any(c["what"].lower().startswith("that is not part") for c in candidates))

    def test_speech_act_precedence_outranks_system_vocabulary(self):
        conversation = {
            "id": "precedence-fixture",
            "platform": "ChatGPT",
            "source_container": "Project ARK",
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Do not create new proposals, events, decisions, open loops, or canonical records.\n"
                        "Classify candidates according to what the statement asserts, not according to concrete nouns or system objects mentioned inside the statement.\n"
                        "Atomic candidates may split one sentence when it contains claims with different semantics or epistemic status.\n"
                        "Separate epistemic confidence from lifecycle state."
                    ),
                    "timestamp": None,
                }
            ],
        }

        by_text = {c["what"]: c for c in extract_candidates(conversation)}
        self.assertEqual(
            by_text["Do not create new proposals, events, decisions, open loops, or canonical records."]["model"],
            "PMM",
        )
        self.assertEqual(
            by_text["Do not create new proposals, events, decisions, open loops, or canonical records."]["category"],
            "Constraint",
        )
        self.assertEqual(
            by_text["Classify candidates according to what the statement asserts, not according to concrete nouns or system objects mentioned inside the statement."]["category"],
            "Principle",
        )
        self.assertEqual(
            by_text["Atomic candidates may split one sentence when it contains claims with different semantics or epistemic status."]["category"],
            "Principle",
        )
        self.assertEqual(
            by_text["Separate epistemic confidence from lifecycle state."]["category"],
            "Principle",
        )

    def test_acceptance_and_taxonomy_deferral_are_captured(self):
        conversation = {
            "id": "acceptance-fixture",
            "platform": "ChatGPT",
            "source_container": "Project ARK",
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Diet v0.1 implementation is accepted as structurally successful.\n"
                        "Use the existing generated review output.\n"
                        "Record this as a taxonomy question to revisit only if real-conversation testing demonstrates a recurring need."
                    ),
                    "timestamp": None,
                }
            ],
        }

        by_text = {c["what"]: c for c in extract_candidates(conversation)}
        self.assertEqual(
            by_text["Diet v0.1 implementation is accepted as structurally successful."]["category"],
            "Decision",
        )
        self.assertEqual(
            by_text["Use the existing generated review output."]["category"],
            "Constraint",
        )
        taxonomy = (
            "Whether tentative future possibilities need a category distinct from "
            "Goal remains an intentionally deferred taxonomy question."
        )
        self.assertEqual(by_text[taxonomy]["model"], "PMM")
        self.assertEqual(by_text[taxonomy]["category"], "Decision")
        self.assertEqual(by_text[taxonomy]["confidence"], "CONFIRMED")

    def test_source_container_does_not_auto_route_scope(self):
        conversation = {
            "id": "routing-fixture",
            "platform": "ChatGPT",
            "source_container": "Project ARK",
            "messages": [
                {
                    "role": "assistant",
                    "content": "Egyptian Ratscrew is the standard modern American name for the game.",
                    "timestamp": None,
                }
            ],
        }

        candidates = extract_candidates(conversation)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["semantic_domains"], ["Games"])
        self.assertEqual(candidates[0]["project_associations"], [])
        self.assertEqual(candidates[0]["scope"], ["Games"])
        self.assertEqual(candidates[0]["source"]["source_container"], "Project ARK")

    def test_mixed_topic_domains_are_claim_level(self):
        conversation = {
            "id": "mixed-domain-fixture",
            "platform": "ChatGPT",
            "source_container": "General",
            "messages": [
                {
                    "role": "assistant",
                    "content": (
                        "Egyptian Ratscrew is the standard modern American name for the game.\n"
                        "Digital curb inventories let cities represent curb space digitally through APIs.\n"
                        "A highway corridor could be transportation + energy transmission + generation + ecological connectivity + water management."
                    ),
                    "timestamp": None,
                }
            ],
        }

        candidates = extract_candidates(conversation)
        domains = {domain for candidate in candidates for domain in candidate["semantic_domains"]}
        self.assertIn("Games", domains)
        self.assertIn("Civic Infrastructure", domains)
        self.assertIn("Technology", domains)
        self.assertIn("Transit", domains)
        self.assertIn("Environment", domains)
        self.assertTrue(any(len(c["semantic_domains"]) > 1 for c in candidates))
        self.assertTrue(all(c["project_associations"] == [] for c in candidates))

    def test_assistant_suggestions_are_not_adopted_decisions(self):
        conversation = {
            "id": "assistant-suggestion-fixture",
            "platform": "ChatGPT",
            "source_container": "General",
            "messages": [
                {
                    "role": "assistant",
                    "content": (
                        "Use already-disturbed land first.\n"
                        "Build something like Tacoma Multipurpose Mobility Corridor and make a professional package with a GIS map and two-page decision memo."
                    ),
                    "timestamp": None,
                }
            ],
        }

        by_text = {c["what"]: c for c in extract_candidates(conversation)}
        use_land = by_text["Use already-disturbed land first."]
        build = by_text[
            "Build something like Tacoma Multipurpose Mobility Corridor and make a professional package with a GIS map and two-page decision memo."
        ]
        self.assertEqual(use_land["category"], "Constraint")
        self.assertEqual(use_land["confidence"], "INFERRED")
        self.assertNotEqual(build["category"], "Decision")
        self.assertEqual(build["confidence"], "TENTATIVE")

    def test_user_self_report_is_pmm_not_pwm_event(self):
        conversation = {
            "id": "self-report-fixture",
            "platform": "ChatGPT",
            "source_container": "General",
            "messages": [
                {
                    "role": "user",
                    "content": "I found out that I'm inherently hostile towards people who are symbols of success in terms of quality wealth.",
                    "timestamp": None,
                }
            ],
        }

        candidates = extract_candidates(conversation)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["model"], "PMM")
        self.assertEqual(candidates[0]["category"], "Pattern")
        self.assertEqual(candidates[0]["confidence"], "CONFIRMED")

    def test_descriptive_external_state_does_not_become_pmm_goal(self):
        conversation = {
            "id": "descriptive-external-fixture",
            "platform": "ChatGPT",
            "source_container": "General",
            "messages": [
                {
                    "role": "assistant",
                    "content": (
                        "It is a folk game with no central rules authority.\n"
                        "Solar still involves mining and manufacturing, land, transmission infrastructure, and eventual panel disposal."
                    ),
                    "timestamp": None,
                }
            ],
        }

        by_text = {c["what"]: c for c in extract_candidates(conversation)}
        folk_game = by_text["It is a folk game with no central rules authority."]
        solar = by_text[
            "Solar still involves mining and manufacturing, land, transmission infrastructure, and eventual panel disposal."
        ]
        self.assertEqual(folk_game["model"], "PWM")
        self.assertEqual(folk_game["category"], "State")
        self.assertEqual(folk_game["semantic_domains"], ["Games"])
        self.assertEqual(solar["model"], "PWM")
        self.assertEqual(solar["category"], "State")
        self.assertIn("Environment", solar["semantic_domains"])

    def test_contrastive_framing_is_pmm_principle(self):
        conversation = {
            "id": "contrast-fixture",
            "platform": "ChatGPT",
            "source_container": "General",
            "messages": [
                {
                    "role": "assistant",
                    "content": "The same infrastructure can produce two radically different cities: public utility intelligence vs everything becomes a toll booth.",
                    "timestamp": None,
                }
            ],
        }

        candidates = extract_candidates(conversation)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(
            candidates[0]["what"],
            "Public infrastructure should function as shared public intelligence rather than turning every interaction into an extraction or toll mechanism.",
        )
        self.assertEqual(candidates[0]["model"], "PMM")
        self.assertEqual(candidates[0]["category"], "Principle")
        self.assertEqual(candidates[0]["confidence"], "INFERRED")


if __name__ == "__main__":
    unittest.main()
