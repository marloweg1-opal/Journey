from __future__ import annotations

import json
import math
import re
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

try:
    from .asset_autodetect import auto_deconstruct_assets
    from .asset_deconstructor import sha256_file
    from .asset_registry import existing_entry, fingerprint, record_entry
except ImportError:  # Allows direct local script use during repair/testing.
    from asset_autodetect import auto_deconstruct_assets
    from asset_deconstructor import sha256_file
    from asset_registry import existing_entry, fingerprint, record_entry


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-").lower()
    return cleaned or "asset_master"


def _asset_source_dir(job_dir: Path, group: str) -> Path:
    grouped = job_dir / "groups" / group
    if grouped.exists():
        return grouped
    return job_dir / "deconstructed"


def _iter_asset_files(job_dir: Path, group: str) -> list[Path]:
    source_dir = _asset_source_dir(job_dir, group)
    return sorted(path for path in source_dir.glob("*.png") if path.is_file())


def _copy_asset(image_path: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(image_path, destination)


def _move_internal_job(child_job_dir: Path, parent_job_dir: Path) -> Path:
    internal_root = parent_job_dir / "_intake_jobs"
    internal_root.mkdir(parents=True, exist_ok=True)
    destination = internal_root / child_job_dir.name
    if destination.exists():
        shutil.rmtree(destination)
    shutil.move(str(child_job_dir), str(destination))
    return destination


def _cell_dimensions(asset_paths: list[Path], requested_cell: int | None, padding: int) -> tuple[int, int]:
    if requested_cell:
        return requested_cell, requested_cell
    max_width = 1
    max_height = 1
    for path in asset_paths:
        with Image.open(path) as image:
            max_width = max(max_width, image.width)
            max_height = max(max_height, image.height)
    side = max(max_width, max_height) + padding * 2
    return side, side


def _write_preview(master: Image.Image, cells: list[dict[str, Any]], preview_path: Path) -> None:
    preview = master.convert("RGBA")
    overlay = Image.new("RGBA", preview.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for index, cell in enumerate(cells, start=1):
        left, top, right, bottom = cell["bbox"]
        color = (127, 217, 210, 220) if index % 2 else (229, 198, 96, 220)
        draw.rectangle((left, top, right, bottom), outline=color, width=2)
        draw.rectangle((left + 3, top + 3, left + 65, top + 22), fill=(10, 12, 18, 210))
        draw.text((left + 7, top + 6), f"{index:02d}", fill=color)
    preview.alpha_composite(overlay)
    preview.save(preview_path)


def compose_master_sheet(
    source_paths: list[Path],
    pipeline_root: Path,
    *,
    job_name: str | None = None,
    alpha_threshold: int = 8,
    min_area: int = 5000,
    complete: bool = True,
    complete_min_area: int = 300,
    split_alpha_threshold: int = 32,
    input_padding: int = 0,
    cell_size: int | None = None,
    gutter: int = 48,
    margin: int = 96,
    columns: int | None = None,
    group: str = "master_assets",
    group_mode: str = "keep_separate",
    name_prefix: str = "asset",
) -> dict[str, Any]:
    sheets = [Path(path) for path in source_paths if Path(path).suffix.lower() in IMAGE_SUFFIXES]
    if not sheets:
        raise ValueError("At least one image sheet is required.")

    deduped_sheets: list[Path] = []
    seen_source_hashes: set[str] = set()
    source_hashes: list[dict[str, str]] = []
    duplicate_sources: list[dict[str, str]] = []
    for path in sheets:
        digest = sha256_file(path)
        if digest in seen_source_hashes:
            duplicate_sources.append({"path": str(path), "sha256": digest})
            continue
        seen_source_hashes.add(digest)
        deduped_sheets.append(path)
        source_hashes.append({"path": str(path), "sha256": digest})
    sheets = deduped_sheets
    source_hashes = sorted(source_hashes, key=lambda item: (item["sha256"], item["path"]))
    options = {
        "alpha_threshold": alpha_threshold,
        "min_area": min_area,
        "complete": complete,
        "complete_min_area": complete_min_area,
        "split_alpha_threshold": split_alpha_threshold,
        "input_padding": input_padding,
        "cell_size": cell_size,
        "gutter": gutter,
        "margin": margin,
        "columns": columns,
        "group": group,
        "group_mode": group_mode,
        "name_prefix": name_prefix,
    }
    cache_key = fingerprint("compose_master_sheet", [item["sha256"] for item in source_hashes], options)
    cached = existing_entry(pipeline_root, cache_key)
    if cached:
        outputs = cached.get("outputs", {})
        return {
            "job": cached["job"],
            "job_dir": cached["job_dir"],
            "source_count": len(sheets),
            "asset_count": outputs.get("asset_count"),
            "master_sheet": outputs.get("master_sheet"),
            "master_preview": outputs.get("master_preview"),
            "master_recipe": outputs.get("master_recipe"),
            "master_manifest": outputs.get("master_manifest"),
            "canvas": outputs.get("canvas"),
            "grid": outputs.get("grid"),
            "intake_jobs": outputs.get("intake_jobs", []),
            "reused": True,
            "fingerprint": cache_key,
            "duplicate_sources": duplicate_sources,
        }

    job = _safe_name(job_name or f"master_sheet_{len(sheets)}_sources")
    job_dir = pipeline_root / "outbox" / job
    if job_dir.exists():
        shutil.rmtree(job_dir)
    job_dir.mkdir(parents=True)
    parts_dir = job_dir / "parts"
    parts_dir.mkdir()
    source_assets_dir = job_dir / "_source_assets"
    source_assets_dir.mkdir()

    intake_results: list[dict[str, Any]] = []
    asset_paths: list[tuple[Path, dict[str, Any]]] = []
    internal_jobs: list[dict[str, str]] = []
    for index, sheet in enumerate(sheets, start=1):
        intake_job = f"{job}__source_{index:02d}_{_safe_name(sheet.stem)}"
        source_group = group if group_mode != "keep_separate" else _safe_name(sheet.stem)
        result = auto_deconstruct_assets(
            sheet,
            pipeline_root,
            job_name=intake_job,
            alpha_threshold=alpha_threshold,
            min_area=min_area,
            padding=input_padding,
            group=source_group,
            name_prefix=f"source_{index:02d}",
            complete=complete,
            complete_min_area=complete_min_area,
            split_alpha_threshold=split_alpha_threshold,
        )
        intake_results.append(result)
        child_job_dir = Path(result["job_dir"])
        source_dir = _asset_source_dir(child_job_dir, source_group)
        for asset in result["assets"]:
            asset_path = source_dir / asset["name"]
            if asset_path.exists():
                stable_source = source_assets_dir / intake_job / asset["name"]
                _copy_asset(asset_path, stable_source)
                asset_paths.append((stable_source, {"source_index": index, "source_sheet": str(sheet), "group": source_group, **asset}))
        moved_child_dir = _move_internal_job(child_job_dir, job_dir)
        result["job_dir"] = str(moved_child_dir)
        if result.get("recipe_path"):
            result["recipe_path"] = str(moved_child_dir / "recipe.json") if (moved_child_dir / "recipe.json").exists() else result["recipe_path"]
        internal_jobs.append({"job": intake_job, "path": str(moved_child_dir)})

    if not asset_paths:
        raise ValueError("No assets were extracted from the supplied sheets.")

    cell_width, cell_height = _cell_dimensions([path for path, _ in asset_paths], cell_size, padding=0)
    col_count = columns or math.ceil(math.sqrt(len(asset_paths)))
    row_count = math.ceil(len(asset_paths) / col_count)
    width = margin * 2 + col_count * cell_width + max(0, col_count - 1) * gutter
    height = margin * 2 + row_count * cell_height + max(0, row_count - 1) * gutter
    master = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    cells: list[dict[str, Any]] = []
    for index, (asset_path, meta) in enumerate(asset_paths, start=1):
        row = (index - 1) // col_count
        col = (index - 1) % col_count
        left = margin + col * (cell_width + gutter)
        top = margin + row * (cell_height + gutter)
        right = left + cell_width
        bottom = top + cell_height
        with Image.open(asset_path) as asset_image:
            asset = asset_image.convert("RGBA")
            paste_x = left + (cell_width - asset.width) // 2
            paste_y = top + (cell_height - asset.height) // 2
            master.alpha_composite(asset, (paste_x, paste_y))
        output_name = f"{name_prefix}_{index:03d}.png"
        copied_path = parts_dir / output_name
        _copy_asset(asset_path, copied_path)
        cells.append(
            {
                "filename": output_name,
                "group": meta.get("group") or group,
                "row": f"row_{row + 1:02d}",
                "column": f"col_{col + 1:02d}",
                "bbox": [left, top, right, bottom],
                "asset_bbox_in_cell": [paste_x - left, paste_y - top, paste_x - left + asset.width, paste_y - top + asset.height],
                "source_file": str(asset_path),
                "source_sheet": meta["source_sheet"],
                "source_index": meta["source_index"],
                "source_asset": meta["name"],
            }
        )

    master_path = job_dir / "master-sheet.png"
    master.save(master_path)
    preview_path = job_dir / "master-preview.png"
    _write_preview(master, cells, preview_path)
    recipe_groups: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for cell in cells:
        recipe_groups.setdefault(cell["group"], {"cells": []})["cells"].append(
            {"filename": cell["filename"], "row": cell["row"], "column": cell["column"], "bbox": cell["bbox"]}
        )
    recipe = {
        "job": job,
        "match": {"filename_glob": [master_path.name]},
        "canvas": {"width": width, "height": height},
        "groups": recipe_groups,
    }
    recipe_path = job_dir / "master-recipe.json"
    recipe_path.write_text(json.dumps(recipe, indent=2), encoding="utf-8")

    manifest = {
        "job": job,
        "stage": "compose_master_sheet",
        "fingerprint": cache_key,
        "source_count": len(sheets),
        "asset_count": len(cells),
        "master_sheet": str(master_path),
        "master_preview": str(preview_path),
        "master_recipe": str(recipe_path),
        "source_sheets": [str(path) for path in sheets],
        "source_sha256": source_hashes,
        "duplicate_sources": duplicate_sources,
        "group_mode": group_mode,
        "canvas": {"width": width, "height": height},
        "grid": {"columns": col_count, "rows": row_count, "cell_width": cell_width, "cell_height": cell_height, "gutter": gutter, "margin": margin},
        "intake_results": intake_results,
        "internal_jobs": internal_jobs,
        "assets": cells,
    }
    manifest_path = job_dir / "master-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    part_manifest = {
        "job": job,
        "source_path": str(master_path),
        "source_sha256": sha256_file(master_path),
        "source_dimensions": [width, height],
        "recipe_path": str(recipe_path),
        "stage": "compose_parts",
        "assets": [
            {
                "name": cell["filename"],
                "group": cell["group"],
                "row": cell["row"],
                "column": cell["column"],
                "source_bbox": cell["bbox"],
                "source_dimensions": [cell["bbox"][2] - cell["bbox"][0], cell["bbox"][3] - cell["bbox"][1]],
                "output_path": str((parts_dir / cell["filename"]).relative_to(job_dir)),
                "group_output_path": str((parts_dir / cell["filename"]).relative_to(job_dir)),
                "output_dimensions": [cell["bbox"][2] - cell["bbox"][0], cell["bbox"][3] - cell["bbox"][1]],
                "output_sha256": sha256_file(parts_dir / cell["filename"]),
                "operations": ["compose:part-copy"],
            }
            for cell in cells
        ],
    }
    (job_dir / "manifest.json").write_text(json.dumps(part_manifest, indent=2), encoding="utf-8")

    outputs = {
        "asset_count": len(cells),
        "master_sheet": str(master_path),
        "master_preview": str(preview_path),
        "master_recipe": str(recipe_path),
        "master_manifest": str(manifest_path),
        "canvas": manifest["canvas"],
        "grid": manifest["grid"],
        "group_mode": group_mode,
        "intake_jobs": internal_jobs,
    }
    record_entry(
        pipeline_root,
        cache_key,
        operation="compose_master_sheet",
        source_sha256=[item["sha256"] for item in source_hashes],
        options=options,
        job=job,
        job_dir=job_dir,
        outputs=outputs,
    )

    return {
        "job": job,
        "job_dir": str(job_dir),
        "source_count": len(sheets),
        **outputs,
        "reused": False,
        "fingerprint": cache_key,
        "duplicate_sources": duplicate_sources,
    }
