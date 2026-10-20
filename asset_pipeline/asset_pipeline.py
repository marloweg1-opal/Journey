from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path
import re
import shutil
import time

try:
    from .asset_autodetect import auto_deconstruct_assets
    from .asset_approver import approve_job, review_job
    from .asset_brief import build_recipe_bound_brief
    from .asset_composer import compose_master_sheet
    from .asset_deconstructor import deconstruct_sheet, iter_cells, load_recipe, sha256_file
    from .asset_intake import run_asset_intake
    from .asset_nine_slice import build_nine_slice, suggest_nine_slice_insets
    from .asset_normalizer import normalize_job
    from .asset_precision import precision_icons
    from .asset_registry import existing_entry, fingerprint, record_entry
    from .asset_repair import repair_icons
    from .asset_treatment import treat_asset
    from .asset_verifier import verify_deconstruct_lossless
except ImportError:  # Allows: python asset_pipeline.py ...
    from asset_autodetect import auto_deconstruct_assets
    from asset_approver import approve_job, review_job
    from asset_brief import build_recipe_bound_brief
    from asset_composer import compose_master_sheet
    from asset_deconstructor import deconstruct_sheet, iter_cells, load_recipe, sha256_file
    from asset_intake import run_asset_intake
    from asset_nine_slice import build_nine_slice, suggest_nine_slice_insets
    from asset_normalizer import normalize_job
    from asset_precision import precision_icons
    from asset_registry import existing_entry, fingerprint, record_entry
    from asset_repair import repair_icons
    from asset_treatment import treat_asset
    from asset_verifier import verify_deconstruct_lossless


PIPELINE_ROOT = Path(__file__).resolve().parent


def ensure_dirs(root: Path = PIPELINE_ROOT) -> None:
    for name in ("inbox", "recipes", "work", "outbox", "approved", "rejected", "library", "logs"):
        (root / name).mkdir(parents=True, exist_ok=True)


def inspect_recipe(recipe_path: Path) -> dict:
    recipe = load_recipe(recipe_path)
    cells = iter_cells(recipe)
    return {
        "job": recipe["job"],
        "asset_count": len(cells),
        "assets": [
            {"name": cell.name, "group": cell.group, "row": cell.row, "column": cell.column, "bbox": list(cell.bbox)}
            for cell in cells
        ],
    }


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return cleaned or "asset_sheet"


def _archive_inbox_sheet(sheet: Path, inbox: Path) -> Path:
    archive = inbox / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    destination = archive / sheet.name
    if destination.exists():
        stamp = time.strftime("%Y%m%d-%H%M%S")
        destination = archive / f"{sheet.stem}__{stamp}{sheet.suffix}"
        counter = 2
        while destination.exists():
            destination = archive / f"{sheet.stem}__{stamp}-{counter}{sheet.suffix}"
            counter += 1
    shutil.move(str(sheet), str(destination))
    return destination


def _recipe_matches_sheet(recipe: dict, recipe_path: Path, sheet_path: Path) -> bool:
    match = recipe.get("match", {})
    sheet_name = sheet_path.name.lower()
    sheet_stem = sheet_path.stem.lower()

    if isinstance(match, dict):
        glob_rule = match.get("filename_glob")
        if glob_rule:
            patterns = glob_rule if isinstance(glob_rule, list) else [glob_rule]
            return any(fnmatch.fnmatch(sheet_name, str(pattern).lower()) for pattern in patterns)

        contains_rule = match.get("filename_contains")
        if contains_rule:
            tokens = contains_rule if isinstance(contains_rule, list) else [contains_rule]
            return all(str(token).lower() in sheet_name for token in tokens)

    job_tokens = [token for token in re.split(r"[^A-Za-z0-9]+", recipe["job"].lower()) if token]
    recipe_tokens = [token for token in re.split(r"[^A-Za-z0-9]+", recipe_path.stem.lower()) if token]
    useful_tokens = [token for token in dict.fromkeys(job_tokens + recipe_tokens) if len(token) > 2]
    return bool(useful_tokens) and all(token in sheet_stem for token in useful_tokens[:4])


def _deconstruct_options(recipe_path: Path) -> dict:
    return {"recipe_path": str(recipe_path.resolve()), "stage": "deconstruct"}


def _auto_options(
    *,
    alpha_threshold: int,
    min_area: int,
    padding: int,
    group: str,
    name_prefix: str,
    complete: bool,
    complete_min_area: int,
    split_alpha_threshold: int,
) -> dict:
    return {
        "alpha_threshold": alpha_threshold,
        "min_area": min_area,
        "padding": padding,
        "group": group,
        "name_prefix": name_prefix,
        "complete": complete,
        "complete_min_area": complete_min_area,
        "split_alpha_threshold": split_alpha_threshold,
    }


def run_inbox(root: Path = PIPELINE_ROOT) -> dict:
    ensure_dirs(root)
    inbox = root / "inbox"
    recipes_dir = root / "recipes"
    recipes = []
    for recipe_path in sorted(recipes_dir.glob("*.json")):
        recipe = load_recipe(recipe_path)
        recipes.append((recipe_path, recipe))

    summary = {
        "inbox": str(inbox),
        "archive": str(inbox / "archive"),
        "recipes": str(recipes_dir),
        "processed": [],
        "skipped": [],
        "errors": [],
    }

    sheets = sorted(path for path in inbox.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES)
    for sheet in sheets:
        matches = [(path, recipe) for path, recipe in recipes if _recipe_matches_sheet(recipe, path, sheet)]
        if not matches:
            summary["skipped"].append({"sheet": str(sheet), "reason": "no matching recipe"})
            continue
        if len(matches) > 1:
            summary["skipped"].append(
                {"sheet": str(sheet), "reason": "multiple matching recipes", "recipes": [str(path) for path, _ in matches]}
            )
            continue

        recipe_path, recipe = matches[0]
        job_name = _safe_name(f"{recipe['job']}__{sheet.stem}")
        try:
            source_sha = sha256_file(sheet)
            options = _deconstruct_options(recipe_path)
            cache_key = fingerprint("deconstruct", source_sha, options)
            cached = existing_entry(root, cache_key)
            if cached:
                record = {
                    "sheet": str(sheet),
                    "recipe": str(recipe_path),
                    "job": cached["job"],
                    "job_dir": cached["job_dir"],
                    "deconstruct_lossless": True,
                    "asset_count": cached.get("outputs", {}).get("asset_count"),
                    "reused": True,
                    "fingerprint": cache_key,
                }
                record["archived_to"] = str(_archive_inbox_sheet(sheet, inbox))
                summary["processed"].append(record)
                continue
            job_dir = deconstruct_sheet(sheet, recipe_path, root, job_name=job_name)
            verification = verify_deconstruct_lossless(job_dir)
            record = {
                "sheet": str(sheet),
                "recipe": str(recipe_path),
                "job": job_name,
                "job_dir": str(job_dir),
                "deconstruct_lossless": bool(verification["deconstruct_lossless"]),
                "asset_count": len(verification.get("asset_checks", [])),
                "reused": False,
                "fingerprint": cache_key,
            }
            record_entry(
                root,
                cache_key,
                operation="deconstruct",
                source_sha256=source_sha,
                options=options,
                job=job_name,
                job_dir=job_dir,
                outputs={"asset_count": record["asset_count"], "manifest": str(job_dir / "manifest.json")},
            )
            record["archived_to"] = str(_archive_inbox_sheet(sheet, inbox))
            summary["processed"].append(record)
            if not verification["deconstruct_lossless"]:
                summary["errors"].append({"sheet": str(sheet), "job": job_name, "reason": "verification failed"})
        except Exception as exc:  # noqa: BLE001 - batch mode should report all sheets it can.
            summary["errors"].append({"sheet": str(sheet), "recipe": str(recipe_path), "reason": str(exc)})

    log_path = root / "logs" / f"run-inbox-{time.strftime('%Y%m%d-%H%M%S')}.json"
    log_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    summary["log_path"] = str(log_path)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mini ARK asset-sheet intake pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect", help="Inspect a recipe without writing assets")
    inspect.add_argument("--recipe", required=True, type=Path)

    decon = sub.add_parser("deconstruct", help="Losslessly cut a sheet into recipe cells")
    decon.add_argument("sheet", type=Path)
    decon.add_argument("--recipe", required=True, type=Path)

    auto = sub.add_parser("auto-deconstruct", help="Detect major alpha components, write a recipe, and deconstruct assets")
    auto.add_argument("sheet", type=Path)
    auto.add_argument("--job", type=str)
    auto.add_argument("--alpha-threshold", type=int, default=8)
    auto.add_argument("--min-area", type=int, default=5000)
    auto.add_argument("--padding", type=int, default=0)
    auto.add_argument("--group", default="detected_assets")
    auto.add_argument("--name-prefix", default="asset")
    auto.add_argument("--complete", action="store_true", help="Use small-asset intake and conservative merged-blob splitting")
    auto.add_argument("--complete-min-area", type=int, default=300)
    auto.add_argument("--split-alpha-threshold", type=int, default=32)

    compose = sub.add_parser("compose-master", help="Auto-deconstruct multiple sheets and pack their assets into one master sheet")
    compose.add_argument("sheets", nargs="+", type=Path)
    compose.add_argument("--job", type=str)
    compose.add_argument("--alpha-threshold", type=int, default=8)
    compose.add_argument("--min-area", type=int, default=5000)
    compose.add_argument("--complete", action="store_true")
    compose.add_argument("--complete-min-area", type=int, default=300)
    compose.add_argument("--split-alpha-threshold", type=int, default=32)
    compose.add_argument("--input-padding", type=int, default=0)
    compose.add_argument("--cell-size", type=int)
    compose.add_argument("--gutter", type=int, default=48)
    compose.add_argument("--margin", type=int, default=96)
    compose.add_argument("--columns", type=int)
    compose.add_argument("--group", default="master_assets")
    compose.add_argument("--group-mode", choices=("one_group", "keep_separate"), default="keep_separate")
    compose.add_argument("--name-prefix", default="asset")

    intake = sub.add_parser("asset-intake", help="Run the standard Asset ARK pipeline for one or more asset sheets")
    intake.add_argument("sheets", nargs="+", type=Path)
    intake.add_argument("--job", type=str)
    intake.add_argument("--family", type=str)
    intake.add_argument("--label", type=str)
    intake.add_argument("--no-auto-approve", action="store_true", help="Run through review but do not approve even if quality passes")
    intake.add_argument("--allow-duplicates", action="store_true", help="Allow likely visual duplicates to pass approval gate")
    intake.add_argument("--alpha-threshold", type=int, default=8)
    intake.add_argument("--min-area", type=int, default=5000)
    intake.add_argument("--complete-min-area", type=int, default=300)
    intake.add_argument("--split-alpha-threshold", type=int, default=32)
    intake.add_argument("--precision-padding", type=int, default=8)
    intake.add_argument("--repair-min-component-area", type=int, default=24)
    intake.add_argument("--max-fill-ratio", type=float, default=0.08)
    intake.add_argument("--group-mode", choices=("one_group", "keep_separate"), default="keep_separate")
    intake.add_argument("--archive-inputs", action="store_true")

    norm = sub.add_parser("normalize", help="Optionally normalize an existing job")
    norm.add_argument("job", type=str)
    norm.add_argument("--alpha-threshold", type=int, default=1)
    norm.add_argument("--padding", type=int, default=2)
    norm.add_argument("--state-group-key", default="column")

    verify = sub.add_parser("verify", help="Verify a deconstructed job")
    verify.add_argument("job", type=str)

    nine = sub.add_parser("nine-slice", help="Extract a frame image into 9-slice cells")
    nine.add_argument("image", type=Path)
    nine.add_argument("--left", type=int)
    nine.add_argument("--top", type=int)
    nine.add_argument("--right", type=int)
    nine.add_argument("--bottom", type=int)
    nine.add_argument("--auto", action="store_true", help="Estimate any missing 9-slice insets from the image size")
    nine.add_argument("--job", type=str)

    treat = sub.add_parser("treat", help="Create a nondestructive treated asset output")
    treat.add_argument("image", type=Path)
    treat.add_argument("--job", type=str)
    treat.add_argument("--trim", action="store_true")
    treat.add_argument("--padding", type=int, default=0)
    treat.add_argument("--max-width", type=int)
    treat.add_argument("--max-height", type=int)
    treat.add_argument("--tint")
    treat.add_argument("--tint-strength", type=float, default=0.0)
    treat.add_argument("--shadow-blur", type=int, default=0)
    treat.add_argument("--shadow-offset-x", type=int, default=0)
    treat.add_argument("--shadow-offset-y", type=int, default=0)
    treat.add_argument("--shadow-opacity", type=int, default=128)

    precision = sub.add_parser("precision-icons", help="Trim, pad, center, and organize icon-like deconstructed assets")
    precision.add_argument("job", type=str)
    precision.add_argument("--padding", type=int, default=8)
    precision.add_argument("--alpha-threshold", type=int, default=1)
    precision.add_argument("--target-size", help="Canvas size as N or WxH. Defaults to auto square.")
    precision.add_argument("--not-square", action="store_true")

    repair = sub.add_parser("repair-icons", help="Clean alpha noise and loose fragments from icon-like deconstructed assets")
    repair.add_argument("job", type=str)
    repair.add_argument("--alpha-threshold", type=int, default=1)
    repair.add_argument("--min-component-area", type=int, default=24)
    repair.add_argument("--keep-largest-component", action="store_true")
    repair.add_argument("--no-smooth-alpha", action="store_true")
    repair.add_argument("--reshape-candidate", action="store_true")
    repair.add_argument("--max-reshape-growth-ratio", type=float, default=0.08)
    repair.add_argument("--max-fill-ratio", type=float, help="Reject reshape candidates that need to fill more than this fraction")

    review_asset = sub.add_parser("review-job", help="Score an asset job for quality and likely visual duplicates")
    review_asset.add_argument("job", type=str)

    approve_asset = sub.add_parser("approve-job", help="Copy the best available asset stage into approved assets and optional library")
    approve_asset.add_argument("job", type=str)
    approve_asset.add_argument("--family", help="Optional asset library family, such as cloverstone or vlc")
    approve_asset.add_argument("--label", help="Optional asset library set label")

    brief = sub.add_parser("brief", help="Generate a recipe-bound ImageGen asset sheet brief")
    brief.add_argument("--job", required=True)
    brief.add_argument("--slots", required=True, help="Comma-separated or newline-separated asset slot names")
    brief.add_argument("--columns", type=int, required=True)
    brief.add_argument("--cell-width", type=int, required=True)
    brief.add_argument("--cell-height", type=int, required=True)
    brief.add_argument("--gutter-x", type=int, default=32)
    brief.add_argument("--gutter-y", type=int, default=32)
    brief.add_argument("--margin-x", type=int, default=64)
    brief.add_argument("--margin-y", type=int, default=64)
    brief.add_argument("--safe-zone-width", type=int)
    brief.add_argument("--safe-zone-height", type=int)
    brief.add_argument("--style", default="")
    brief.add_argument("--background", default="transparent")
    brief.add_argument("--group", default="generated_assets")

    run = sub.add_parser("run", help="Deconstruct and verify a sheet")
    run.add_argument("sheet", type=Path)
    run.add_argument("--recipe", required=True, type=Path)
    run.add_argument("--normalize", action="store_true")

    sub.add_parser("run-inbox", help="Deconstruct every inbox sheet that matches exactly one recipe")

    args = parser.parse_args(argv)
    ensure_dirs()

    if args.command == "inspect":
        print(json.dumps(inspect_recipe(args.recipe), indent=2))
        return 0

    if args.command == "deconstruct":
        job_dir = deconstruct_sheet(args.sheet, args.recipe, PIPELINE_ROOT)
        print(job_dir)
        return 0

    if args.command == "auto-deconstruct":
        source_sha = sha256_file(args.sheet)
        options = _auto_options(
            alpha_threshold=args.alpha_threshold,
            min_area=args.min_area,
            padding=args.padding,
            group=args.group,
            name_prefix=args.name_prefix,
            complete=args.complete,
            complete_min_area=args.complete_min_area,
            split_alpha_threshold=args.split_alpha_threshold,
        )
        cache_key = fingerprint("auto_deconstruct", source_sha, options)
        cached = existing_entry(PIPELINE_ROOT, cache_key)
        if cached:
            outputs = cached.get("outputs", {})
            result = {
                "job": cached["job"],
                "job_dir": cached["job_dir"],
                "asset_count": outputs.get("asset_count"),
                "deconstruct_lossless": True,
                "recipe_path": outputs.get("recipe_path"),
                "preview_path": outputs.get("preview_path"),
                "review_path": outputs.get("review_path"),
                "assets": outputs.get("assets", []),
                "reused": True,
                "fingerprint": cache_key,
            }
        else:
            result = auto_deconstruct_assets(
                args.sheet,
                PIPELINE_ROOT,
                job_name=args.job,
                alpha_threshold=args.alpha_threshold,
                min_area=args.min_area,
                padding=args.padding,
                group=args.group,
                name_prefix=args.name_prefix,
                complete=args.complete,
                complete_min_area=args.complete_min_area,
                split_alpha_threshold=args.split_alpha_threshold,
            )
            result["reused"] = False
            result["fingerprint"] = cache_key
            record_entry(
                PIPELINE_ROOT,
                cache_key,
                operation="auto_deconstruct",
                source_sha256=source_sha,
                options=options,
                job=result["job"],
                job_dir=Path(result["job_dir"]),
                outputs={
                    "asset_count": result.get("asset_count"),
                    "recipe_path": result.get("recipe_path"),
                    "preview_path": result.get("preview_path"),
                    "review_path": result.get("review_path"),
                    "assets": result.get("assets", []),
                },
            )
        print(json.dumps(result, indent=2))
        return 0 if result["deconstruct_lossless"] else 2

    if args.command == "compose-master":
        result = compose_master_sheet(
            args.sheets,
            PIPELINE_ROOT,
            job_name=args.job,
            alpha_threshold=args.alpha_threshold,
            min_area=args.min_area,
            complete=args.complete,
            complete_min_area=args.complete_min_area,
            split_alpha_threshold=args.split_alpha_threshold,
            input_padding=args.input_padding,
            cell_size=args.cell_size,
            gutter=args.gutter,
            margin=args.margin,
            columns=args.columns,
            group=args.group,
            group_mode=args.group_mode,
            name_prefix=args.name_prefix,
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "asset-intake":
        result = run_asset_intake(
            args.sheets,
            PIPELINE_ROOT,
            job_name=args.job,
            family=args.family,
            label=args.label,
            approve_perfect=not args.no_auto_approve,
            require_no_duplicates=not args.allow_duplicates,
            alpha_threshold=args.alpha_threshold,
            min_area=args.min_area,
            complete_min_area=args.complete_min_area,
            split_alpha_threshold=args.split_alpha_threshold,
            precision_padding=args.precision_padding,
            repair_min_component_area=args.repair_min_component_area,
            max_fill_ratio=args.max_fill_ratio,
            group_mode=args.group_mode,
            archive_inputs=args.archive_inputs,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 2

    if args.command == "normalize":
        out_dir = normalize_job(
            PIPELINE_ROOT / "outbox" / args.job,
            alpha_threshold=args.alpha_threshold,
            padding=args.padding,
            state_group_key=args.state_group_key,
        )
        print(out_dir)
        return 0

    if args.command == "verify":
        result = verify_deconstruct_lossless(PIPELINE_ROOT / "outbox" / args.job)
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "nine-slice":
        suggested = suggest_nine_slice_insets(args.image)
        inferred = bool(args.auto or any(value is None for value in (args.left, args.top, args.right, args.bottom)))
        job_dir = build_nine_slice(
            args.image,
            PIPELINE_ROOT,
            left=args.left if args.left is not None else suggested["left"],
            top=args.top if args.top is not None else suggested["top"],
            right=args.right if args.right is not None else suggested["right"],
            bottom=args.bottom if args.bottom is not None else suggested["bottom"],
            job_name=args.job,
            inferred=inferred,
        )
        print(job_dir)
        return 0

    if args.command == "treat":
        job_dir = treat_asset(
            args.image,
            PIPELINE_ROOT,
            job_name=args.job,
            trim=args.trim,
            padding=args.padding,
            max_width=args.max_width,
            max_height=args.max_height,
            tint=args.tint,
            tint_strength=args.tint_strength,
            shadow_blur=args.shadow_blur,
            shadow_offset_x=args.shadow_offset_x,
            shadow_offset_y=args.shadow_offset_y,
            shadow_opacity=args.shadow_opacity,
        )
        print(job_dir)
        return 0

    if args.command == "precision-icons":
        result = precision_icons(
            PIPELINE_ROOT / "outbox" / args.job,
            padding=args.padding,
            alpha_threshold=args.alpha_threshold,
            target_size=args.target_size,
            square=not args.not_square,
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "repair-icons":
        result = repair_icons(
            PIPELINE_ROOT / "outbox" / args.job,
            alpha_threshold=args.alpha_threshold,
            min_component_area=args.min_component_area,
            keep_largest_component=args.keep_largest_component,
            smooth_alpha=not args.no_smooth_alpha,
            reshape_candidate=args.reshape_candidate,
            max_reshape_growth_ratio=args.max_reshape_growth_ratio,
            max_fill_ratio=args.max_fill_ratio,
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "review-job":
        result = review_job(PIPELINE_ROOT, args.job)
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "approve-job":
        result = approve_job(PIPELINE_ROOT, args.job, family=args.family, label=args.label)
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "brief":
        result = build_recipe_bound_brief(
            PIPELINE_ROOT,
            job=args.job,
            slots=args.slots,
            columns=args.columns,
            cell_width=args.cell_width,
            cell_height=args.cell_height,
            gutter_x=args.gutter_x,
            gutter_y=args.gutter_y,
            margin_x=args.margin_x,
            margin_y=args.margin_y,
            safe_zone_width=args.safe_zone_width,
            safe_zone_height=args.safe_zone_height,
            style=args.style,
            background=args.background,
            group=args.group,
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "run":
        job_dir = deconstruct_sheet(args.sheet, args.recipe, PIPELINE_ROOT)
        if args.normalize:
            normalize_job(job_dir)
        result = verify_deconstruct_lossless(job_dir)
        print(json.dumps(result, indent=2))
        return 0 if result["deconstruct_lossless"] else 2

    if args.command == "run-inbox":
        result = run_inbox(PIPELINE_ROOT)
        print(json.dumps(result, indent=2))
        return 0 if not result["errors"] else 2

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
