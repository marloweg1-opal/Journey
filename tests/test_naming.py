import unittest

from core.naming import extract_date_info, preview_name, slug
from core.token_registry import DEFAULT_REGISTRY


class NamingTests(unittest.TestCase):
    def test_slug_normalizes_noise_and_stop_words(self):
        self.assertEqual(slug("The Cloverstone Care Rail!!"), "cloverstone_care_rail")

    def test_preview_name_uses_project_role_and_detected_tokens(self):
        result = preview_name(
            r"R:\Projects\CareBloomOS\Assets\Moonstone Rail Final 2026-09-09.PNG",
            DEFAULT_REGISTRY,
            role="Care Rail",
            project="CareBloom",
        )

        self.assertEqual(result["status"], "preview_only")
        self.assertEqual(result["mutation"], "none")
        self.assertIn("carebloomos", result["tokens"])
        self.assertIn("moonstone", result["tokens"])
        self.assertEqual(result["date_token"], "2026-09-09")
        self.assertEqual(result["suggested_name"], "care_rail_carebloomos_moonstone_moonstone_rail_final_2026-09-09.png")
        self.assertFalse(result["format_recommendation"]["needs_resave"])

    def test_preview_name_recommends_file_format_without_image_bias(self):
        script = preview_name(
            r"R:\Projects\CareBloomOS\scripts\Repair Projection 2026-09-09.ps1",
            DEFAULT_REGISTRY,
            role="Repair Script",
            project="CareBloom",
        )
        bitmap = preview_name(
            r"R:\Projects\CareBloomOS\Assets\Button Sheet.bmp",
            DEFAULT_REGISTRY,
            role="UI Button",
            project="CareBloom",
        )

        self.assertEqual(script["suggested_name"], "repair_script_carebloomos_repair_projection_2026-09-09.ps1")
        self.assertEqual(script["format_recommendation"]["preferred"], ".ps1")
        self.assertFalse(script["format_recommendation"]["needs_resave"])
        self.assertEqual(bitmap["format_recommendation"]["preferred"], ".png")
        self.assertTrue(bitmap["format_recommendation"]["needs_resave"])

    def test_ambiguous_day_month_date_is_metadata_not_filename_token(self):
        without, info = extract_date_info("ruby_on_rails_download_09_10_2026")

        self.assertEqual(without, "ruby_on_rails_download")
        self.assertIsNone(info["token"])
        self.assertEqual(info["status"], "ambiguous")
        self.assertIn("not added", info["note"])
        result = preview_name(
            r"R:\Downloads\ruby_on_rails_download_09_10_2026.zip",
            DEFAULT_REGISTRY,
            role="Framework Package",
            project="Corestone",
        )
        self.assertEqual(result["suggested_name"], "framework_package_corestone_ruby_on_rails_download.zip")
        self.assertIn("provenance", " ".join(result["metadata_advice"]))

    def test_unambiguous_day_month_date_can_be_normalized(self):
        _, info = extract_date_info("dance_recital_13_09_2026")

        self.assertEqual(info["token"], "2026-09-13")
        self.assertEqual(info["format"], "DD-MM-YYYY")

    def test_temporary_files_defer_and_reserved_names_are_disambiguated(self):
        temp = preview_name(r"R:\Downloads\installer.crdownload", DEFAULT_REGISTRY)
        reserved = preview_name(r"R:\Exports\CON.txt", DEFAULT_REGISTRY)

        self.assertEqual(temp["status"], "defer")
        self.assertIn("Temporary", " ".join(temp["warnings"]))
        self.assertEqual(reserved["suggested_name"], "con_file.txt")
        self.assertIn("Reserved Windows", " ".join(reserved["warnings"]))


if __name__ == "__main__":
    unittest.main()
