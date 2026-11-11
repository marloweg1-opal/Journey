"""Acceptance and safety checks for the isolated visual experiment."""

import json
import os
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from journey_vision.demo import ASTER, HOLDOUT, run_demo
from journey_vision.lab import Lab


class VisionLabTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="journey-vision-test-")
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.root, self.workspace = self.base / "Source images", self.base / "Visual review"
        self.root.mkdir()
        self.workspace.mkdir()

    def test_complete_visual_acceptance_on_forty_images(self):
        report, plan_path, evidence, metrics = run_demo(self.base)
        self.assertTrue(metrics["source_preserved"])
        self.assertEqual(metrics["images"], 40)
        self.assertEqual(metrics["warm_reopen"]["cache_hits"], 40)
        self.assertEqual(metrics["warm_reopen"]["decoded"], 0)
        self.assertGreater(metrics["quality_after_confirmation"]["false_proposed_identity"], 0)
        self.assertEqual(metrics["quality_after_review"]["false_proposed_identity"], 0)
        self.assertEqual(metrics["quality_after_review"]["false_confirmed_identity"], 0)
        self.assertGreater(metrics["quality_after_review"]["correct_automatic_purpose"], 30)
        for path in HOLDOUT[2:]:
            comparison = metrics["holdout_comparison"][path]
            self.assertEqual(comparison["without_rejection"], "Aster")
            self.assertEqual(comparison["with_rejection_state"], "unknown")
        self.assertEqual(json.loads(evidence.read_text(encoding="utf-8")), metrics)
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        item = plan["assets"][ASTER]
        self.assertGreaterEqual(len(item["collections"]), 3)
        self.assertTrue(plan["questions"])
        self.assertTrue(item["name"]["destination"].endswith("v02 - 2026-10-18T14-23-51.png"))
        self.assertTrue(any(a["name"]["state"] == "needs_identification" for a in plan["assets"].values()))
        text = report.read_text(encoding="utf-8")
        self.assertIn("data:image/webp;base64,", text)
        self.assertIn("Generated acceptance sample", text)

    def test_canon_is_scope_bound_and_reversible(self):
        filename = "mislabeled.bmp"
        asset = self.root / filename
        Image.new("RGB", (44, 40), "purple").save(asset)
        lab = Lab(self.root, self.workspace)
        lab.scan()
        lab.review(filename, "confirm", label="Subject A", purpose="Character artwork")
        lab = Lab(self.root, self.workspace)
        with self.assertRaisesRegex(ValueError, "confirmed as Subject A"):
            lab.review(filename, "confirm", label="Subject B")
        lab.review(filename, "reject", label="Subject A")
        self.assertEqual(lab.scan()["assets"][filename]["identity"]["state"], "explicitly_rejected_identity")
        lab.undo()
        self.assertEqual(lab.scan()["assets"][filename]["identity"]["label"], "Subject A")
        alternate = self.base / "Another scope"
        alternate.mkdir()
        with self.assertRaisesRegex(ValueError, "different source"):
            Lab(alternate, self.workspace)
        before = asset.stat()
        Image.new("RGB", (44, 40), "green").save(asset)
        os.utime(asset, ns=(before.st_atime_ns, before.st_mtime_ns))
        with self.assertRaisesRegex(ValueError, "has changed"):
            lab.review(filename, "confirm", label="Subject A")
        result = lab.scan()
        self.assertEqual(result["counts"]["decoded"], 1)
        self.assertEqual(result["assets"][filename]["identity"]["state"], "unknown")

    def test_outputs_and_invalid_images_are_safely_bounded(self):
        (self.root / "corrupt.png").write_bytes(b"this is plain text")
        Image.new("RGB", (12, 12), "red").save(self.root / "wrong.jpg", format="PNG")
        Image.new("RGBA", (96, 96)).save(self.root / "valid.png")
        with self.assertRaisesRegex(ValueError, "outside the inspected folder"):
            Lab(self.root, self.root)
        lab = Lab(self.root, self.workspace)
        with self.assertRaises(ValueError):
            lab.set_rule(project="", filename="{subject}", folder="../Escape")
        plan = lab.scan()
        self.assertEqual(set(plan["assets"]), {"valid.png"})
        self.assertEqual(set(plan["skipped"]), {"corrupt.png", "wrong.jpg"})
        self.assertIn("different extension", plan["skipped"]["wrong.jpg"])
        lab.export(plan)
        self.assertEqual({p.name for p in self.root.iterdir()}, {"corrupt.png", "wrong.jpg", "valid.png"})

    def test_encoder_failure_falls_back_to_pixel_evidence(self):
        class Unavailable:
            identifier = "unavailable test encoder"

            def embed(self, _image):
                raise RuntimeError("Test failure")

        Image.new("RGBA", (96, 96)).save(self.root / "transparent.png")
        plan = Lab(self.root, self.workspace).scan(Unavailable())
        self.assertEqual(plan["counts"]["analyzed"], 1)
        self.assertIsNone(plan["encoder"])
        self.assertIn("Pixel analysis continues", " ".join(plan["notes"]))
