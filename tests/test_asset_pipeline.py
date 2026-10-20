import json
import sys
import unittest
import shutil
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from asset_pipeline.asset_autodetect import auto_deconstruct_assets  # noqa: E402
from asset_pipeline.asset_approver import approve_job, review_job  # noqa: E402
from asset_pipeline.asset_brief import build_recipe_bound_brief  # noqa: E402
from asset_pipeline.asset_composer import compose_master_sheet  # noqa: E402
from asset_pipeline.asset_deconstructor import deconstruct_sheet  # noqa: E402
from asset_pipeline.asset_intake import run_asset_intake  # noqa: E402
from asset_pipeline.asset_nine_slice import build_nine_slice, suggest_nine_slice_insets  # noqa: E402
from asset_pipeline.asset_normalizer import normalize_job  # noqa: E402
from asset_pipeline.asset_pipeline import run_inbox  # noqa: E402
from asset_pipeline.asset_precision import precision_icons  # noqa: E402
from asset_pipeline.asset_repair import repair_icons  # noqa: E402
from asset_pipeline.asset_treatment import treat_asset  # noqa: E402
from asset_pipeline.asset_verifier import verify_deconstruct_lossless  # noqa: E402


CONTROLS = ["previous", "play", "pause", "stop", "next", "slower", "faster"]
STATES = ["normal", "hover", "pressed"]


class AssetPipelineTests(unittest.TestCase):
    def setUp(self):
        base_tmp = Path.cwd() / "work" / "test_tmp"
        base_tmp.mkdir(parents=True, exist_ok=True)
        self.fixture = tempfile.TemporaryDirectory(prefix='asset-', dir=base_tmp)
        self.root = Path(self.fixture.name)
        self.pipeline = self.root / "asset_pipeline"
        (self.pipeline / "outbox").mkdir(parents=True)

    def tearDown(self):
        self.fixture.cleanup()

    def write_recipe(self, recipe):
        path = self.root / "recipe.json"
        path.write_text(json.dumps(recipe), encoding="utf-8")
        return path

    def grid_recipe(self, job="test_grid", cell=16, gutter=0):
        return {
            "job": job,
            "groups": {
                "primary_controls": {
                    "filename_pattern": "{column}-{row}.png",
                    "rows": STATES,
                    "columns": CONTROLS,
                    "grid": {
                        "x": 0,
                        "y": 0,
                        "cell_width": cell,
                        "cell_height": cell,
                        "gutter_x": gutter,
                        "gutter_y": gutter,
                    },
                }
            },
        }

    def make_grid_sheet(self, cell=16, gutter=0, mode="RGBA"):
        width = len(CONTROLS) * cell + (len(CONTROLS) - 1) * gutter
        height = len(STATES) * cell + (len(STATES) - 1) * gutter
        image = Image.new(mode, (width, height), (0, 0, 0, 0) if mode == "RGBA" else (0, 0, 0))
        for row_index, state in enumerate(STATES):
            for col_index, control in enumerate(CONTROLS):
                left = col_index * (cell + gutter)
                top = row_index * (cell + gutter)
                color = (20 + col_index * 20, 30 + row_index * 40, 180, 255)
                if mode == "RGB":
                    color = color[:3]
                for y in range(top + 3, top + cell - 2):
                    for x in range(left + 3, left + cell - 3):
                        image.putpixel((x, y), color)
                if mode == "RGBA" and control == "play" and state == "normal":
                    for y in range(top + cell - 2, top + cell):
                        for x in range(left + 5, left + cell - 5):
                            image.putpixel((x, y), (255, 255, 255, 7))
        path = self.root / "sheet.png"
        image.save(path)
        return path, image.convert("RGBA")

    def test_cloverstone_vlc_recipe_produces_21_lossless_pngs(self):
        sheet, source = self.make_grid_sheet()
        job_dir = deconstruct_sheet(sheet, self.write_recipe(self.grid_recipe("cloverstone_vlc_primary_controls")), self.pipeline)
        verification = verify_deconstruct_lossless(job_dir)

        self.assertTrue(verification["deconstruct_lossless"])
        self.assertEqual(len(list((job_dir / "deconstructed").glob("*.png"))), 21)
        self.assertEqual(len(list((job_dir / "groups" / "primary_controls").glob("*.png"))), 21)
        self.assertTrue((job_dir / "reconstruction-proof.png").exists())
        exported = Image.open(job_dir / "deconstructed" / "play-normal.png").convert("RGBA")
        grouped = Image.open(job_dir / "groups" / "primary_controls" / "play-normal.png").convert("RGBA")
        expected = source.crop((16, 0, 32, 16))
        self.assertEqual(list(exported.getdata()), list(expected.getdata()))
        self.assertEqual(list(grouped.getdata()), list(expected.getdata()))

    def test_faint_final_rows_survive_deconstruction(self):
        sheet, _ = self.make_grid_sheet()
        job_dir = deconstruct_sheet(sheet, self.write_recipe(self.grid_recipe("faint_rows")), self.pipeline)
        exported = Image.open(job_dir / "deconstructed" / "play-normal.png").convert("RGBA")

        faint_pixels = [exported.getpixel((x, 15))[3] for x in range(5, 11)]
        self.assertEqual(faint_pixels, [7, 7, 7, 7, 7, 7])
        self.assertTrue(verify_deconstruct_lossless(job_dir)["deconstruct_lossless"])

    def test_state_group_normalization_uses_union_bbox(self):
        sheet, _ = self.make_grid_sheet()
        job_dir = deconstruct_sheet(sheet, self.write_recipe(self.grid_recipe("normalize_states")), self.pipeline)
        normalize_job(job_dir, alpha_threshold=1, padding=1, state_group_key="column")
        manifest = json.loads((job_dir / "manifest.json").read_text(encoding="utf-8"))

        play_entries = [a for a in manifest["assets"] if a["column"] == "play"]
        crop_boxes = {tuple(a["normalization"]["crop_box"]) for a in play_entries}
        sizes = {tuple(a["output_dimensions"]) for a in play_entries}
        self.assertEqual(len(crop_boxes), 1)
        self.assertEqual(len(sizes), 1)
        self.assertTrue((job_dir / "normalized" / "play-normal.png").exists())

    def test_irregular_explicit_cells_verify_lossless(self):
        sheet = self.root / "irregular.png"
        image = Image.new("RGBA", (40, 24), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((2, 2, 11, 10), fill=(255, 0, 0, 255))
        draw.rectangle((20, 5, 37, 22), fill=(0, 255, 0, 128))
        image.save(sheet)
        recipe = {
            "job": "irregular",
            "groups": {
                "pieces": {
                    "cells": [
                        {"filename": "small.png", "bbox": [0, 0, 14, 12]},
                        {"filename": "large.png", "bbox": [18, 3, 40, 24]},
                    ]
                }
            },
        }
        job_dir = deconstruct_sheet(sheet, self.write_recipe(recipe), self.pipeline)
        self.assertTrue(verify_deconstruct_lossless(job_dir)["deconstruct_lossless"])

    def test_nine_slice_explicit_recipe(self):
        sheet = self.root / "nine.png"
        Image.new("RGBA", (30, 30), (10, 20, 30, 255)).save(sheet)
        cells = []
        for row in range(3):
            for col in range(3):
                cells.append({"filename": f"{row}-{col}.png", "bbox": [col * 10, row * 10, col * 10 + 10, row * 10 + 10]})
        recipe = {"job": "nine_slice", "groups": {"nine_slice": {"cells": cells}}}
        job_dir = deconstruct_sheet(sheet, self.write_recipe(recipe), self.pipeline)
        self.assertEqual(len(list((job_dir / "deconstructed").glob("*.png"))), 9)
        self.assertTrue(verify_deconstruct_lossless(job_dir)["deconstruct_lossless"])

    def test_nine_slice_builder_outputs_cells_and_tokens(self):
        sheet = self.root / "frame.png"
        image = Image.new("RGBA", (30, 24), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 29, 23), outline=(255, 210, 80, 255), width=4)
        draw.rectangle((6, 5, 23, 18), fill=(30, 20, 60, 180))
        image.save(sheet)

        job_dir = build_nine_slice(sheet, self.pipeline, left=6, top=5, right=6, bottom=5, job_name="frame_parts")
        manifest = json.loads((job_dir / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["stage"], "nine_slice")
        self.assertEqual(len(list((job_dir / "nine_slice").glob("*.png"))), 9)
        self.assertTrue((job_dir / "nine_slice" / "center.png").exists())
        self.assertEqual(manifest["insets"], {"left": 6, "top": 5, "right": 6, "bottom": 5})
        tokens = json.loads((job_dir / "nine-slice.tokens.json").read_text(encoding="utf-8"))
        self.assertEqual(tokens["border_image_slice"], [5, 6, 5, 6])

    def test_nine_slice_builder_can_suggest_safe_first_pass_insets(self):
        sheet = self.root / "wide_frame.png"
        image = Image.new("RGBA", (100, 60), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((0, 0, 99, 59), outline=(255, 210, 80, 255), width=12)
        image.save(sheet)

        suggested = suggest_nine_slice_insets(sheet)
        self.assertEqual(suggested, {"left": 16, "top": 10, "right": 16, "bottom": 10})

        job_dir = build_nine_slice(sheet, self.pipeline, **suggested, job_name="auto_frame_parts", inferred=True)
        manifest = json.loads((job_dir / "manifest.json").read_text(encoding="utf-8"))

        self.assertTrue(manifest["insets_inferred"])
        self.assertIn("protected border distances", manifest["inset_guide"])
        self.assertEqual(manifest["insets"], suggested)

    def test_treat_asset_trims_pads_tints_and_shadows_without_overwriting_source(self):
        source = self.root / "glow.png"
        image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((10, 11, 20, 21), fill=(80, 120, 240, 180))
        image.save(source)
        original_hash = source.read_bytes()

        job_dir = treat_asset(
            source,
            self.pipeline,
            job_name="treated_glow",
            trim=True,
            padding=2,
            tint="#ffd36a",
            tint_strength=0.35,
            shadow_blur=2,
            shadow_offset_x=1,
            shadow_offset_y=2,
        )
        manifest = json.loads((job_dir / "manifest.json").read_text(encoding="utf-8"))
        output = Image.open(job_dir / manifest["assets"][0]["output_path"]).convert("RGBA")

        self.assertEqual(source.read_bytes(), original_hash)
        self.assertEqual(manifest["stage"], "treat")
        self.assertIn("treat:alpha-trim", manifest["assets"][0]["operations"])
        self.assertIn("treat:preserve-alpha-tint", manifest["assets"][0]["operations"])
        self.assertIn("treat:drop-shadow", manifest["assets"][0]["operations"])
        self.assertGreater(output.width, 0)
        self.assertGreater(output.height, 0)

    def test_recipe_bound_brief_writes_prompt_and_matching_recipe(self):
        result = build_recipe_bound_brief(
            self.pipeline,
            job="moonstone_care_rail_parts",
            slots=["top_rail", "bottom_rail", "center_crest", "tab_home"],
            columns=2,
            cell_width=200,
            cell_height=160,
            gutter_x=24,
            gutter_y=30,
            margin_x=40,
            margin_y=50,
            safe_zone_width=170,
            safe_zone_height=130,
            style="Moonstone lunar crystal interface parts. No text.",
        )
        recipe_path = Path(result["recipe_path"])
        brief_path = Path(result["brief_path"])
        recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
        prompt = brief_path.read_text(encoding="utf-8")

        self.assertTrue(recipe_path.exists())
        self.assertTrue(brief_path.exists())
        self.assertEqual(result["canvas"]["width"], 504)
        self.assertEqual(result["canvas"]["height"], 450)
        self.assertEqual(result["slot_count"], 4)
        self.assertEqual(recipe["groups"]["generated_assets"]["cells"][0]["bbox"], [40, 50, 240, 210])
        self.assertEqual(recipe["groups"]["generated_assets"]["cells"][3]["filename"], "tab_home.png")
        self.assertIn("Canvas: 504 x 450 px.", prompt)
        self.assertIn("Do not add labels", prompt)

    def test_auto_deconstruct_assets_detects_major_transparent_components(self):
        sheet = self.root / "rail_sheet.png"
        image = Image.new("RGBA", (240, 180), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        boxes = [
            (10, 10, 95, 45),
            (130, 10, 225, 45),
            (10, 70, 95, 105),
            (130, 70, 225, 105),
            (10, 130, 95, 165),
            (130, 130, 225, 165),
        ]
        for index, box in enumerate(boxes):
            draw.rounded_rectangle(box, radius=4, fill=(20 + index * 20, 120, 180, 255))
        draw.point((118, 88), fill=(255, 255, 255, 4))
        image.save(sheet)

        result = auto_deconstruct_assets(sheet, self.pipeline, alpha_threshold=8, min_area=1000, job_name="auto_rails")
        job_dir = Path(result["job_dir"])

        self.assertEqual(result["asset_count"], 6)
        self.assertTrue(result["deconstruct_lossless"])
        self.assertTrue(Path(result["recipe_path"]).exists())
        self.assertTrue(Path(result["preview_path"]).exists())
        self.assertEqual(len(list((job_dir / "deconstructed").glob("*.png"))), 6)
        self.assertEqual(result["assets"][0]["bbox"], [10, 10, 96, 46])
        self.assertEqual(result["assets"][5]["row"], "row_03")
        self.assertEqual(result["assets"][5]["column"], "col_02")

    def test_complete_auto_deconstruct_splits_faintly_connected_assets(self):
        sheet = self.root / "connected_badges.png"
        image = Image.new("RGBA", (140, 70), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((10, 10, 55, 55), fill=(20, 150, 70, 255))
        draw.ellipse((75, 10, 120, 55), fill=(20, 150, 70, 255))
        draw.rectangle((55, 31, 75, 34), fill=(255, 255, 255, 12))
        image.save(sheet)

        result = auto_deconstruct_assets(
            sheet,
            self.pipeline,
            alpha_threshold=8,
            min_area=500,
            job_name="complete_connected_badges",
            complete=True,
            complete_min_area=300,
            split_alpha_threshold=32,
        )

        self.assertEqual(result["asset_count"], 2)
        self.assertTrue(result["deconstruct_lossless"])
        self.assertEqual(result["review"]["split_merged_count"], 1)
        self.assertIn("split_merged_components", result["review"]["warnings"])
        self.assertTrue(result["assets"][0]["split_from"])
        self.assertTrue(Path(result["review_path"]).exists())

    def test_complete_auto_deconstruct_skips_labels_and_nested_duplicates(self):
        sheet = self.root / "labels_and_nested.png"
        image = Image.new("RGBA", (120, 80), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((8, 8, 80, 17), fill=(255, 255, 255, 255))
        draw.rounded_rectangle((20, 30, 90, 72), radius=6, outline=(20, 150, 70, 255), width=8)
        draw.ellipse((47, 43, 63, 59), fill=(20, 150, 70, 255))
        image.save(sheet)

        result = auto_deconstruct_assets(
            sheet,
            self.pipeline,
            alpha_threshold=8,
            min_area=500,
            job_name="complete_labels_nested",
            complete=True,
            complete_min_area=40,
            split_alpha_threshold=32,
        )

        self.assertEqual(result["asset_count"], 1)
        skipped_reasons = {entry["reason"] for entry in result["review"]["skipped"]}
        self.assertIn("likely_text_label", skipped_reasons)
        self.assertIn("nested_inside_larger_asset", skipped_reasons)

    def test_compose_master_sheet_combines_multiple_source_sheets(self):
        sheets = []
        for sheet_index in range(2):
            sheet = self.root / f"split_{sheet_index + 1}.png"
            image = Image.new("RGBA", (120, 60), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.ellipse((10, 10, 45, 45), fill=(20 + sheet_index * 40, 150, 70, 255))
            draw.rounded_rectangle((70, 12, 110, 48), radius=4, fill=(40, 170 + sheet_index * 20, 90, 255))
            image.save(sheet)
            sheets.append(sheet)

        result = compose_master_sheet(
            sheets,
            self.pipeline,
            job_name="combined_vlc_parts",
            complete=True,
            complete_min_area=100,
            min_area=1000,
            cell_size=64,
            columns=2,
            gutter=12,
            margin=16,
            group_mode="one_group",
        )
        job_dir = Path(result["job_dir"])
        recipe = json.loads(Path(result["master_recipe"]).read_text(encoding="utf-8"))

        self.assertEqual(result["source_count"], 2)
        self.assertEqual(result["asset_count"], 4)
        self.assertTrue(Path(result["master_sheet"]).exists())
        self.assertTrue(Path(result["master_preview"]).exists())
        self.assertTrue(Path(result["master_manifest"]).exists())
        self.assertEqual(len(recipe["groups"]["master_assets"]["cells"]), 4)
        self.assertEqual(len(list((job_dir / "parts").glob("*.png"))), 4)

    def test_compose_master_sheet_can_keep_source_sheets_separate(self):
        sheets = []
        for name, color in (("sheet_alpha", (20, 150, 70, 255)), ("sheet_beta", (80, 90, 180, 255))):
            sheet = self.root / f"{name}.png"
            image = Image.new("RGBA", (96, 48), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.ellipse((8, 8, 32, 32), fill=color)
            draw.rectangle((56, 10, 82, 36), fill=color)
            image.save(sheet)
            sheets.append(sheet)

        result = compose_master_sheet(
            sheets,
            self.pipeline,
            job_name="separate_source_groups",
            complete=True,
            complete_min_area=50,
            min_area=300,
            cell_size=48,
            columns=2,
            gutter=8,
            margin=12,
            group_mode="keep_separate",
        )
        recipe = json.loads(Path(result["master_recipe"]).read_text(encoding="utf-8"))
        manifest = json.loads(Path(result["master_manifest"]).read_text(encoding="utf-8"))

        self.assertEqual(result["group_mode"], "keep_separate")
        self.assertEqual(set(recipe["groups"]), {"sheet_alpha", "sheet_beta"})
        self.assertEqual(len(recipe["groups"]["sheet_alpha"]["cells"]), 2)
        self.assertEqual(len(recipe["groups"]["sheet_beta"]["cells"]), 2)
        self.assertEqual({asset["group"] for asset in manifest["assets"]}, {"sheet_alpha", "sheet_beta"})

    def test_compose_master_sheet_defaults_to_keep_source_sheets_separate(self):
        sheets = []
        for name, color in (("default_alpha", (20, 150, 70, 255)), ("default_beta", (80, 90, 180, 255))):
            sheet = self.root / f"{name}.png"
            image = Image.new("RGBA", (96, 48), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.ellipse((8, 8, 32, 32), fill=color)
            draw.rectangle((56, 10, 82, 36), fill=color)
            image.save(sheet)
            sheets.append(sheet)

        result = compose_master_sheet(
            sheets,
            self.pipeline,
            job_name="default_separate_source_groups",
            complete=True,
            complete_min_area=50,
            min_area=300,
            cell_size=48,
            columns=2,
            gutter=8,
            margin=12,
        )
        recipe = json.loads(Path(result["master_recipe"]).read_text(encoding="utf-8"))

        self.assertEqual(result["group_mode"], "keep_separate")
        self.assertEqual(set(recipe["groups"]), {"default_alpha", "default_beta"})

    def test_compose_master_sheet_reuses_same_sources_and_options(self):
        sheets = []
        for sheet_index in range(2):
            sheet = self.root / f"repeat_split_{sheet_index + 1}.png"
            image = Image.new("RGBA", (80, 48), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.ellipse((8, 8, 32, 32), fill=(20, 150, 70, 255))
            draw.rectangle((48, 10, 72, 34), fill=(40, 170, 90, 255))
            image.save(sheet)
            sheets.append(sheet)

        first = compose_master_sheet(
            sheets,
            self.pipeline,
            job_name="first_batch",
            complete=True,
            complete_min_area=50,
            min_area=300,
            cell_size=48,
            columns=2,
            gutter=8,
            margin=12,
        )
        second = compose_master_sheet(
            list(reversed(sheets)),
            self.pipeline,
            job_name="second_batch_should_not_exist",
            complete=True,
            complete_min_area=50,
            min_area=300,
            cell_size=48,
            columns=2,
            gutter=8,
            margin=12,
        )

        self.assertFalse(first["reused"])
        self.assertTrue(second["reused"])
        self.assertEqual(second["job"], first["job"])
        self.assertEqual(second["job_dir"], first["job_dir"])
        self.assertFalse((self.pipeline / "outbox" / "second_batch_should_not_exist").exists())

    def test_run_inbox_reuses_same_sheet_and_recipe(self):
        sheet, _ = self.make_grid_sheet()
        inbox = self.pipeline / "inbox"
        recipes = self.pipeline / "recipes"
        inbox.mkdir(parents=True)
        recipes.mkdir(parents=True)
        recipe = self.grid_recipe("cloverstone_vlc_primary_controls")
        recipe["match"] = {"filename_contains": ["cloverstone", "vlc", "primary", "controls"]}
        (recipes / "cloverstone_vlc_primary_controls.json").write_text(json.dumps(recipe), encoding="utf-8")

        first_sheet = inbox / "cloverstone_vlc_primary_controls_sheet.png"
        shutil.copy2(sheet, first_sheet)
        first = run_inbox(self.pipeline)
        duplicate_sheet = inbox / "renamed_cloverstone_vlc_primary_controls_sheet.png"
        shutil.copy2(sheet, duplicate_sheet)
        second = run_inbox(self.pipeline)

        self.assertFalse(first["processed"][0]["reused"])
        self.assertTrue(second["processed"][0]["reused"])
        self.assertEqual(second["processed"][0]["job_dir"], first["processed"][0]["job_dir"])
        self.assertTrue(Path(second["processed"][0]["archived_to"]).exists())
        self.assertFalse(duplicate_sheet.exists())

    def test_review_job_reports_quality_and_likely_visual_duplicates(self):
        job_dir = self.pipeline / "outbox" / "review_quality_job"
        assets = job_dir / "deconstructed"
        assets.mkdir(parents=True)
        image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((4, 4, 27, 27), fill=(20, 150, 70, 255))
        image.save(assets / "badge_a.png")
        image.save(assets / "badge_b.png")
        clipped = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        ImageDraw.Draw(clipped).rectangle((0, 4, 20, 26), fill=(20, 150, 70, 255))
        clipped.save(assets / "clipped.png")

        result = review_job(self.pipeline, "review_quality_job")

        self.assertEqual(result["asset_count"], 3)
        self.assertEqual(result["quality"]["review_count"], 1)
        self.assertEqual(result["quality"]["duplicate_group_count"], 1)
        self.assertEqual(result["quality"]["duplicate_asset_count"], 2)
        self.assertEqual(len(result["quality"]["duplicate_pairs"]), 1)

    def test_approve_job_exports_best_stage_to_approved_and_library(self):
        job_dir = self.pipeline / "outbox" / "approval_job"
        precision = job_dir / "precision" / "icons" / "system"
        precision.mkdir(parents=True)
        image = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((4, 4, 19, 19), fill=(20, 150, 70, 255))
        image.save(precision / "system_tools.png")
        (job_dir / "precision-manifest.json").write_text(json.dumps({"asset_count": 1}), encoding="utf-8")

        result = approve_job(self.pipeline, "approval_job", family="cloverstone", label="tool_icons")

        self.assertEqual(result["source_stage"], "precision")
        self.assertEqual(result["asset_count"], 1)
        self.assertTrue(Path(result["approved_root"], "approval-manifest.json").exists())
        self.assertTrue(Path(result["assets_root"], "icons", "system", "system_tools.png").exists())
        self.assertTrue(Path(result["library_root"], "icons", "system", "system_tools.png").exists())

    def test_approve_job_exports_nine_slice_stage(self):
        job_dir = self.pipeline / "outbox" / "nine_slice_approval_job"
        slices = job_dir / "nine_slice"
        slices.mkdir(parents=True)
        image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((1, 1, 6, 6), fill=(20, 150, 70, 255))
        image.save(slices / "top_left.png")
        (job_dir / "manifest.json").write_text(json.dumps({"stage": "nine_slice"}), encoding="utf-8")

        result = approve_job(self.pipeline, "nine_slice_approval_job", family="carebloomos", label="frame_parts")

        self.assertEqual(result["source_stage"], "nine_slice")
        self.assertEqual(result["asset_count"], 1)
        self.assertTrue(Path(result["assets_root"], "top_left.png").exists())
        self.assertTrue(Path(result["library_root"], "top_left.png").exists())

    def test_asset_intake_runs_standard_pipeline_and_holds_imperfect_assets(self):
        sheet = self.root / "edge_touching_buttons.png"
        image = Image.new("RGBA", (90, 45), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((5, 5, 35, 35), fill=(20, 150, 70, 255))
        draw.ellipse((52, 5, 82, 35), fill=(20, 150, 70, 255))
        image.save(sheet)

        result = run_asset_intake(
            [sheet],
            self.pipeline,
            job_name="intake_buttons",
            family="cloverstone",
            label="buttons",
            min_area=200,
            complete_min_area=50,
        )

        self.assertEqual(result["status"], "blocked_from_approval")
        self.assertTrue(Path(result["job_dir"], "repair-manifest.json").exists())
        self.assertTrue(Path(result["job_dir"], "precision-manifest.json").exists())
        self.assertTrue(Path(result["summary_path"]).exists())
        self.assertIn("likely_visual_duplicates", result["approval_blocked_reasons"])
        self.assertEqual(result["review"]["quality"]["duplicate_group_count"], 1)
        self.assertEqual(result["review"]["quality"]["duplicate_asset_count"], 2)
        self.assertIsNone(result["approval"])

    def test_precision_icons_trim_center_and_organize_by_recipe_metadata(self):
        sheet = self.root / "icons.png"
        image = Image.new("RGBA", (64, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((8, 7, 22, 21), fill=(255, 0, 0, 255))
        draw.rectangle((43, 5, 56, 18), fill=(0, 255, 0, 180))
        image.save(sheet)
        recipe = {
            "job": "precision_source",
            "groups": {
                "icons": {
                    "cells": [
                        {"filename": "heart.png", "row": "heart", "column": "gem", "bbox": [0, 0, 32, 32]},
                        {"filename": "system.png", "row": "system", "column": "tool", "bbox": [32, 0, 64, 32]},
                    ]
                }
            },
        }
        job_dir = deconstruct_sheet(sheet, self.write_recipe(recipe), self.pipeline)

        result = precision_icons(job_dir, padding=3, target_size="24")

        heart_path = job_dir / "precision" / "icons" / "heart" / "heart.png"
        system_path = job_dir / "precision" / "icons" / "system" / "system.png"
        self.assertTrue(heart_path.exists())
        self.assertTrue(system_path.exists())
        self.assertTrue((job_dir / "precision-contact-sheet.png").exists())
        self.assertEqual(result["asset_count"], 2)
        self.assertEqual(result["canvas_size"], [24, 24])
        with Image.open(heart_path) as heart:
            self.assertEqual(heart.size, (24, 24))
        with Image.open(system_path) as system:
            self.assertEqual(system.size, (24, 24))
        self.assertEqual(result["assets"][0]["visible_bbox"], [8, 7, 23, 22])

    def test_repair_icons_removes_small_alpha_fragments_before_precision(self):
        sheet = self.root / "noisy_icon.png"
        image = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((12, 12, 25, 25), fill=(255, 0, 0, 255))
        draw.line((2, 2, 8, 2), fill=(255, 255, 255, 255))
        draw.point((35, 35), fill=(255, 255, 255, 255))
        image.save(sheet)
        recipe = {
            "job": "repair_source",
            "groups": {
                "icons": {
                    "cells": [
                        {"filename": "noisy.png", "row": "system", "column": "noise", "bbox": [0, 0, 40, 40]},
                    ]
                }
            },
        }
        job_dir = deconstruct_sheet(sheet, self.write_recipe(recipe), self.pipeline)

        repair = repair_icons(job_dir, min_component_area=20, smooth_alpha=False)
        precision = precision_icons(job_dir, padding=2, target_size="32")
        repaired_path = job_dir / repair["assets"][0]["output_path"]

        self.assertEqual(repair["removed_components"], 2)
        self.assertEqual(repair["removed_pixels"], 8)
        with Image.open(repaired_path) as repaired:
            self.assertEqual(repaired.convert("RGBA").getpixel((2, 2))[3], 0)
            self.assertEqual(repaired.convert("RGBA").getpixel((14, 14))[3], 255)
        self.assertEqual(precision["source_stage"], "repair")
        self.assertEqual(precision["assets"][0]["source_stage"], "repair")

    def test_repair_icons_accepts_reshape_candidate_when_it_scores_better(self):
        sheet = self.root / "damaged_icon.png"
        image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((8, 8, 23, 23), fill=(80, 160, 255, 255))
        draw.rectangle((14, 14, 15, 15), fill=(0, 0, 0, 0))
        image.save(sheet)
        recipe = {
            "job": "reshape_source",
            "groups": {
                "icons": {
                    "cells": [
                        {"filename": "damaged.png", "row": "core", "column": "reshape", "bbox": [0, 0, 32, 32]},
                    ]
                }
            },
        }
        job_dir = deconstruct_sheet(sheet, self.write_recipe(recipe), self.pipeline)

        repair = repair_icons(job_dir, min_component_area=4, smooth_alpha=False, reshape_candidate=True)
        repaired_path = job_dir / repair["assets"][0]["output_path"]
        reshape = repair["assets"][0]["repair"]["reshape"]

        self.assertTrue(reshape["attempted"])
        self.assertTrue(reshape["accepted"])
        self.assertLess(reshape["after"]["score"], reshape["before"]["score"])
        self.assertLessEqual(reshape["missing_fill_ratio"], reshape["max_fill_ratio"])
        with Image.open(repaired_path) as repaired:
            self.assertGreater(repaired.convert("RGBA").getpixel((14, 14))[3], 0)

    def test_repair_icons_rejects_reshape_candidate_when_fill_ratio_is_too_high(self):
        sheet = self.root / "fill_budget_icon.png"
        image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((8, 8, 15, 23), fill=(80, 160, 255, 255))
        draw.rectangle((17, 8, 24, 23), fill=(80, 160, 255, 255))
        image.save(sheet)
        recipe = {
            "job": "fill_budget_source",
            "groups": {
                "icons": {
                    "cells": [
                        {"filename": "budget.png", "row": "core", "column": "budget", "bbox": [0, 0, 32, 32]},
                    ]
                }
            },
        }
        job_dir = deconstruct_sheet(sheet, self.write_recipe(recipe), self.pipeline)

        repair = repair_icons(
            job_dir,
            min_component_area=4,
            smooth_alpha=False,
            reshape_candidate=True,
            max_fill_ratio=0.001,
        )
        repaired_path = job_dir / repair["assets"][0]["output_path"]
        reshape = repair["assets"][0]["repair"]["reshape"]

        self.assertTrue(reshape["attempted"])
        self.assertFalse(reshape["accepted"])
        self.assertIn("too much fill", reshape["reason"])
        self.assertGreater(reshape["missing_fill_ratio"], reshape["max_fill_ratio"])
        with Image.open(repaired_path) as repaired:
            self.assertEqual(repaired.convert("RGBA").getpixel((16, 14))[3], 0)

    def test_rgb_sheet_is_deconstructed_as_rgba_without_pixel_loss_after_conversion(self):
        sheet, source = self.make_grid_sheet(mode="RGB")
        job_dir = deconstruct_sheet(sheet, self.write_recipe(self.grid_recipe("rgb_sheet")), self.pipeline)
        exported = Image.open(job_dir / "deconstructed" / "previous-normal.png").convert("RGBA")
        expected = source.crop((0, 0, 16, 16))
        self.assertEqual(list(exported.getdata()), list(expected.getdata()))
        self.assertTrue(verify_deconstruct_lossless(job_dir)["deconstruct_lossless"])

    def test_run_inbox_deconstructs_exact_recipe_matches_and_logs_summary(self):
        sheet, _ = self.make_grid_sheet()
        inbox = self.pipeline / "inbox"
        recipes = self.pipeline / "recipes"
        inbox.mkdir(parents=True)
        recipes.mkdir(parents=True)
        target_sheet = inbox / "cloverstone_vlc_primary_controls_sheet.png"
        shutil.copy2(sheet, target_sheet)
        recipe = self.grid_recipe("cloverstone_vlc_primary_controls")
        recipe["match"] = {"filename_contains": ["cloverstone", "vlc", "primary", "controls"]}
        (recipes / "cloverstone_vlc_primary_controls.json").write_text(json.dumps(recipe), encoding="utf-8")

        result = run_inbox(self.pipeline)

        self.assertEqual(len(result["processed"]), 1)
        self.assertEqual(result["processed"][0]["asset_count"], 21)
        self.assertTrue(result["processed"][0]["deconstruct_lossless"])
        self.assertTrue(Path(result["processed"][0]["job_dir"]).exists())
        self.assertTrue((Path(result["processed"][0]["job_dir"]) / "groups" / "primary_controls").exists())
        self.assertTrue(Path(result["log_path"]).exists())
        archived = Path(result["processed"][0]["archived_to"])
        self.assertFalse(target_sheet.exists())
        self.assertTrue(archived.exists())
        self.assertEqual(archived.parent, inbox / "archive")

    def test_run_inbox_skips_unmatched_sheets(self):
        sheet, _ = self.make_grid_sheet()
        inbox = self.pipeline / "inbox"
        recipes = self.pipeline / "recipes"
        inbox.mkdir(parents=True)
        recipes.mkdir(parents=True)
        shutil.copy2(sheet, inbox / "mystery_sheet.png")
        recipe = self.grid_recipe("cloverstone_vlc_primary_controls")
        recipe["match"] = {"filename_contains": ["cloverstone", "vlc"]}
        (recipes / "cloverstone_vlc_primary_controls.json").write_text(json.dumps(recipe), encoding="utf-8")

        result = run_inbox(self.pipeline)

        self.assertEqual(result["processed"], [])
        self.assertEqual(len(result["skipped"]), 1)
        self.assertEqual(result["skipped"][0]["reason"], "no matching recipe")


if __name__ == "__main__":
    unittest.main()
