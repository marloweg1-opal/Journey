import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.placement import (  # noqa: E402
    DEPLOY,
    LEGACY_PATH,
    MIGRATE,
    MISPLACED_HIGH_CONFIDENCE,
    MISPLACED_NEEDS_REVIEW,
    PROTECTED_OPERATIONAL,
    doctrine_summary,
    evaluate_placement,
)


ROOT = Path(__file__).resolve().parents[1]


class PlacementDoctrineTests(unittest.TestCase):
    def test_doctrine_entries_have_machine_readable_fields(self):
        summary = doctrine_summary(ROOT)
        required = {
            "canonical_name",
            "path",
            "domain",
            "owner",
            "purpose",
            "allowed_content",
            "disallowed_content",
            "lifecycle",
            "canonicality",
            "protection_level",
            "routing_hints",
            "aliases",
            "legacy_aliases",
            "related_destinations",
            "related_locations",
            "reasoning_notes",
        }

        self.assertGreater(summary["location_count"], 0)
        for location in summary["locations"]:
            self.assertTrue(required.issubset(location))

    def test_downloads2_routes_to_en_route_without_moving(self):
        result = evaluate_placement(r"R:\Downloads2\new_asset_sheet.png", ROOT)

        self.assertEqual(result["state"], LEGACY_PATH)
        self.assertEqual(result["likely_canonical_placement"]["id"], "r_en_route")
        self.assertEqual(result["recommended_action"], "review_legacy_mapping")
        self.assertEqual(result["resolution_strategy"], MIGRATE)
        self.assertTrue(result["read_only"])
        self.assertTrue(result["approval_required_for_changes"])

    def test_live_rainmeter_asset_is_protected_operational(self):
        result = evaluate_placement(
            r"C:\Users\ExampleUser\Documents\Rainmeter\Skins\CareBloom\Images\moonstone.png",
            ROOT,
        )

        self.assertEqual(result["state"], PROTECTED_OPERATIONAL)
        self.assertEqual(result["recommended_action"], "leave_protected")
        self.assertEqual(result["resolution_strategy"], DEPLOY)
        self.assertEqual(result["likely_canonical_placement"]["id"], "active_rainmeter")

    def test_carebloom_asset_outside_project_routes_to_durable_source(self):
        result = evaluate_placement(r"C:\Temp\carebloom_moonstone_badge.png", ROOT)

        self.assertEqual(result["state"], MISPLACED_NEEDS_REVIEW)
        self.assertEqual(result["resolution_strategy"], "REVIEW")
        self.assertEqual(result["likely_canonical_placement"]["id"], "carebloomos_durable_project")
        self.assertEqual(result["likely_canonical_placement"]["path"], r"R:\Projects\CareBloomOS")

    def test_runescript_wrapper_is_legacy_not_canonical_root(self):
        summary = doctrine_summary(ROOT)
        legacy = next(location for location in summary["locations"] if location["id"] == "r_runescript_legacy_wrapper")
        projects = next(location for location in summary["locations"] if location["id"] == "r_projects")

        self.assertEqual(legacy["canonicality"], "legacy")
        self.assertEqual(projects["path"], r"R:\Projects")
        self.assertIn(r"R:\RuneScript\Projects", projects["legacy_aliases"])


if __name__ == "__main__":
    unittest.main()
