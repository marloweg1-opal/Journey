import unittest

from core.stewardship_contract import assess_resource_feasibility


class ResourceFeasibilityTests(unittest.TestCase):
    def test_full_image_is_blocked_not_failed(self):
        result = assess_resource_feasibility(
            {"storage": 2306867200000}, {"storage": 561004331008})
        self.assertEqual(result["state"], "RESOURCE_BLOCKED")
        self.assertFalse(result["execution_authorized"])

    def test_unknown_capacity_not_assumed_available(self):
        self.assertEqual(assess_resource_feasibility(
            {"storage": 100}, {})["state"], "RESOURCE_UNKNOWN")

    def test_feasible_does_not_mean_safe_or_authorized(self):
        result = assess_resource_feasibility({"storage": 100}, {"storage": 100})
        self.assertEqual(result["state"], "RESOURCE_FEASIBLE")
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["safety_assessed"])

    def test_other_resources_and_mixed_unknown(self):
        result = assess_resource_feasibility(
            {"hardware": 1, "physical_access": 1}, {"hardware": 0})
        self.assertEqual(result["state"], "RESOURCE_BLOCKED")
        self.assertEqual(result["unknown"], ["physical_access"])

    def test_invalid_quantities_fail_closed(self):
        for value in (-1, True, 1.5, "100"):
            with self.assertRaises(ValueError):
                assess_resource_feasibility({"storage": value}, {})
            with self.assertRaises(ValueError):
                assess_resource_feasibility({"storage": 1}, {"storage": value})

    def test_zero_requirement_needs_no_resource(self):
        self.assertEqual(assess_resource_feasibility(
            {"money": 0}, {})["state"], "RESOURCE_FEASIBLE")
