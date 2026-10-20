import unittest

from core.photo_taxonomy import taxonomy_summary


class PhotoTaxonomyTests(unittest.TestCase):
    def test_taxonomy_has_top_level_themes_and_dance_drilldown(self):
        summary = taxonomy_summary()
        categories = {item["id"]: item for item in summary["categories"]}

        self.assertEqual(summary["status"], "ready")
        self.assertIn("family_friends", categories)
        self.assertIn("dance", categories)
        self.assertIn("selfies", categories)
        self.assertIn("vacation", categories)
        self.assertIn("dance_team", categories["dance"]["children"])
        self.assertIn("recitals", categories["dance"]["children"])
        self.assertIn("teachers", categories["dance"]["children"])


if __name__ == "__main__":
    unittest.main()
