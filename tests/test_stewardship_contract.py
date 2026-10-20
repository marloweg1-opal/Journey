import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.stewardship_contract import contract_summary, load_contract  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]


class StewardshipContractTests(unittest.TestCase):
    def test_contract_preserves_paths_are_not_identity(self):
        summary = contract_summary(ROOT)

        self.assertIn("current_path", summary["identity_layers"])
        self.assertIn("logical_asset_id", summary["identity_layers"])
        self.assertLess(
            summary["identity_layers"].index("current_path"),
            summary["identity_layers"].index("logical_asset_id"),
        )

    def test_contract_separates_records_and_operation_states(self):
        summary = contract_summary(ROOT)

        self.assertEqual(set(summary["record_kinds"]), {"finding", "proposal", "operation", "event"})
        self.assertIn("PARTIALLY_COMPLETED", summary["operation_states"])
        self.assertIn("MANUAL_RECOVERY_REQUIRED", summary["operation_states"])
        self.assertIn("DESTINATION_VERIFIED", summary["commit_phases"])

    def test_contract_requires_shadow_mode_before_journey(self):
        contract = load_contract(ROOT)

        self.assertFalse(contract["scanner_rules"]["follow_reparse_points_by_default"])
        self.assertTrue(contract["shadow_mode"]["required"])
        self.assertEqual(contract["shadow_mode"]["mutates_reality"], False)
        self.assertEqual(contract["graduation_gates"][0], "Gate A: Shadow")


if __name__ == "__main__":
    unittest.main()
