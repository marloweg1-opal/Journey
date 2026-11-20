"""Regression: large image-heavy scopes must not fail reference clearance by count alone."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase

from journey_navigator.links import Boundaries
from journey_navigator.stewardship import scan_references


class LargeScopeReferenceTests(TestCase):
    def test_image_heavy_collection_can_complete_a_bounded_reference_check(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            for index in range(1850):
                (root / f"art-{index:05}.png").write_bytes(b"not inspected as image")
            target = root / "art-00001.png"
            (root / "index.txt").write_text("No files referenced here.", encoding="utf-8")
            app = SimpleNamespace(policy=Boundaries())
            result = scan_references(app, root, [str(target)])
            self.assertEqual(result["state"], "CHECKED_WITHIN_SCOPE", result)
            self.assertEqual(result["gaps"], 0)
            self.assertEqual(result["references"], [])

    def test_explicit_reference_is_still_held(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "important.png"
            target.write_bytes(b"fixture")
            (root / "usage.txt").write_text(f"Uses {target.name}", encoding="utf-8")
            app = SimpleNamespace(policy=Boundaries())
            result = scan_references(app, root, [str(target)])
            self.assertEqual(result["state"], "CHECKED_WITHIN_SCOPE", result)
            self.assertTrue(result["references"], result)
