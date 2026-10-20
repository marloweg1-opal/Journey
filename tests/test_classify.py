import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.classify import (  # noqa: E402
    LIFECYCLE_OPERATIONAL,
    LIFECYCLE_PROJECT,
    LIFECYCLE_PROTECTED,
    LIFECYCLE_TRANSIENT,
    LIFECYCLE_UNKNOWN,
    classify_path,
)


class ClassifyPathTests(unittest.TestCase):
    def test_rainmeter_image_is_live_surface_not_generic_image(self):
        result = classify_path(
            r"C:\Users\ExampleUser\Documents\Rainmeter\Skins\CareBloom\Background.png"
        )

        self.assertEqual(result["bucket"], "System_Records/Operational_Manifests")
        self.assertEqual(result["confidence"], "Confirmed")
        self.assertEqual(result["lifecycle_class"], LIFECYCLE_PROTECTED)
        self.assertEqual(result["placement"], "live_rainmeter")
        self.assertEqual(result["owner"], "CareBloomOS")

    def test_plex_audio_keeps_application_library_context(self):
        result = classify_path(
            r"C:\Users\ExampleUser\Music\Plex Media Server\Library\freak.wav"
        )

        self.assertEqual(result["bucket"], "Media/Audio")
        self.assertEqual(result["owner"], "Plex")
        self.assertEqual(result["lifecycle_class"], LIFECYCLE_PROJECT)
        self.assertEqual(result["placement"], "application_library")

    def test_carebloom_project_asset_outranks_extension(self):
        result = classify_path(r"R:\Projects\CareBloomOS\Assets\moonstone_badge.png")

        self.assertEqual(result["bucket"], "RuneScript/Projects/CareBloomOS")
        self.assertEqual(result["confidence"], "Strongly_inferred")
        self.assertEqual(result["lifecycle_class"], LIFECYCLE_PROJECT)
        self.assertEqual(result["subject_type"], "project_asset")

    def test_script_is_operational_infrastructure(self):
        result = classify_path(r"R:\Projects\CareBloomOS\scripts\repair_projection.ps1")

        self.assertEqual(result["bucket"], "RuneScript/Projects/CareBloomOS")
        self.assertEqual(result["lifecycle_class"], LIFECYCLE_OPERATIONAL)
        self.assertEqual(result["subject_type"], "script")

    def test_old_account_folder_is_source_context_only(self):
        result = classify_path(r"C:\Users\OldUser\Desktop\mystery.bin")

        self.assertEqual(result["bucket"], "Intake/From_User_Accounts")
        self.assertEqual(result["confidence"], "Tentative")
        self.assertEqual(result["lifecycle_class"], LIFECYCLE_UNKNOWN)
        self.assertEqual(result["placement"], "source_context_only")

    def test_transient_signal_requires_review(self):
        result = classify_path(r"R:\scratch\render_temp\half_finished_export.tmp")

        self.assertEqual(result["bucket"], "Intake/Needs_Classification")
        self.assertEqual(result["confidence"], "Tentative")
        self.assertEqual(result["lifecycle_class"], LIFECYCLE_TRANSIENT)

    def test_unknown_remains_unknown(self):
        result = classify_path(r"R:\Oddments\thing.withoutsignal")

        self.assertEqual(result["bucket"], "Intake/Needs_Classification")
        self.assertEqual(result["confidence"], "Unknown")
        self.assertEqual(result["lifecycle_class"], LIFECYCLE_UNKNOWN)


if __name__ == "__main__":
    unittest.main()
