import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.expression_slots import load_expression_slots, slot_summary  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]


class ExpressionSlotTests(unittest.TestCase):
    def test_expression_slot_registry_preserves_semantic_states(self):
        registry = load_expression_slots(ROOT)

        self.assertEqual(registry["profile_id"], "journey_default")
        self.assertIn("Semantic stability", registry["doctrine"]["law"])
        self.assertIn("needs_review", registry["system_states"])
        self.assertIn("waiting_approval", registry["system_states"])
        self.assertIn("recovery_required", registry["system_states"])

    def test_expression_slot_summary_groups_slots_by_semantic_section(self):
        summary = slot_summary(ROOT)

        self.assertIn("shell", summary["sections"])
        self.assertIn("review", summary["sections"])
        self.assertIn("operations", summary["sections"])
        self.assertIn("undo_available", summary["sections"]["operations"])
        self.assertIn("legacy_path", summary["sections"]["architecture"])


if __name__ == "__main__":
    unittest.main()
