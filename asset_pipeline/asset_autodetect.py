from __future__ import annotations

import json
import math
import re
from collections import deque
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

try:
    from .asset_deconstructor import deconstruct_sheet, sha256_file
    from .asset_verifier import verify_deconstruct_lossless
except ImportError:  # Allows direct local script use during repair/testing.
    from asset_deconstructor import deconstruct_sheet, sha256_file
    from asset_verifier import verify_deconstruct_lossless


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-").lower()
    return cleaned or "asset_sheet"


def _component_boxes(image: Image.Image, alpha_threshold: int, min_area: int) -> list[dict[str, Any]]:
    alpha = image.getchannel("A")
    width, height = image.size
    pixels = alpha.load()
    seen: set[tuple[int, int]] = set()
    boxes: list[dict[str, Any]] = []

    for y in range(height):
        for x in range(width):
            if pixels[x, y] < alpha_threshold or (x, y) in seen:
                continue
            queue: deque[tuple[int, int]] = deque([(x, y)])
            seen.add((x, y))
            count = 0
            left = right = x
            top = bottom = y
            while queue:
                cx, cy = queue.popleft()
                count += 1
                left = min(left, cx)
                right = max(right, cx)
                top = min(top, cy)
                bottom = max(bottom, cy)
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < width and 0 <= ny < height and pixels[nx, ny] >= alpha_threshold and (nx, ny) not in seen:
                        seen.add((nx, ny))
                        queue.append((nx, ny))
            if count >= min_area:
                boxes.append({"bbox": [left, top, right + 1, bottom + 1], "area": count})
    return boxes


def _box_size(box: list[int]) -> tuple[int, int]:
    return box[2] - box[0], box[3] - box[1]


def _box_center(box: list[int]) -> tuple[float, float]:
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def _center_inside(inner: list[int], outer: list[int]) -> bool:
    x, y = _box_center(inner)
    return outer[0] <= x <= outer[2] and outer[1] <= y <= outer[3]


def _is_likely_text_or_noise(box: list[int], area: int, min_area: int) -> tuple[bool, str | None]:
    width, height = _box_size(box)
    if width <= 0 or height <= 0:
        return True, "empty_bbox"
    if area < min_area:
        return True, "below_min_area"
    density = area / max(1, width * height)
    if min(width, height) <= 6 and area < 120:
        return True, "hairline_noise"
    if height <= 14 and width >= 25:
        return True, "likely_text_label"
    if width <= 14 and height >= 25:
        return True, "likely_vertical_label"
    if height <= 18 and width >= height * 3 and density < 0.7:
        return True, "likely_text_label"
    if width <= 18 and height >= width * 3 and density < 0.7:
        return True, "likely_vertical_label"
    return False, None


def _dedupe_boxes(boxes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[tuple[int, int, int, int]] = set()
    for box in boxes:
        key = tuple(box["bbox"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(box)
    return unique


def _contains_box(outer: list[int], inner: list[int], inset: int = 0) -> bool:
    return (
        outer[0] - inset <= inner[0]
        and outer[1] - inset <= inner[1]
        and outer[2] + inset >= inner[2]
        and outer[3] + inset >= inner[3]
    )


def _remove_nested_duplicates(boxes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    keep: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    by_area = sorted(boxes, key=lambda item: int(item["area"]), reverse=True)
    for box in by_area:
        bbox = box["bbox"]
        width, height = _box_size(bbox)
        nested_in = None
        for parent in keep:
            parent_box = parent["bbox"]
            parent_width, parent_height = _box_size(parent_box)
            if not _contains_box(parent_box, bbox, inset=2):
                continue
            if int(parent["area"]) < int(box["area"]) * 1.2:
                continue
            if parent_width < width * 1.25 or parent_height < height * 1.25:
                continue
            nested_in = parent_box
            break
        if nested_in:
            skipped.append({"bbox": bbox, "area": box["area"], "reason": "nested_inside_larger_asset", "parent_bbox": nested_in})
            continue
        keep.append(box)
    return _dedupe_boxes(keep), skipped


def _maybe_split_merged_box(
    box: dict[str, Any],
    high_threshold_boxes: list[dict[str, Any]],
    min_area: int,
) -> list[dict[str, Any]]:
    parent = box["bbox"]
    parent_width, parent_height = _box_size(parent)
    children = []
    for candidate in high_threshold_boxes:
        child = candidate["bbox"]
        if child == parent or not _center_inside(child, parent):
            continue
        child_width, child_height = _box_size(child)
        likely_bad, _ = _is_likely_text_or_noise(child, int(candidate["area"]), min_area)
        if likely_bad:
            continue
        horizontal_whole_asset = parent_width >= parent_height * 1.35 and child_width >= parent_width * 0.20 and child_height >= parent_height * 0.42
        vertical_whole_asset = parent_height >= parent_width * 1.35 and child_height >= parent_height * 0.20 and child_width >= parent_width * 0.42
        if horizontal_whole_asset or vertical_whole_asset:
            child_record = dict(candidate)
            child_record["split_from"] = parent
            children.append(child_record)

    if len(children) < 2:
        return [box]
    children = _dedupe_boxes(sorted(children, key=lambda item: (item["bbox"][1], item["bbox"][0])))
    if len(children) < 2:
        return [box]
    return children


def _prepare_boxes(
    image: Image.Image,
    alpha_threshold: int,
    min_area: int,
    complete: bool,
    complete_min_area: int,
    split_alpha_threshold: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    active_min_area = min(min_area, complete_min_area) if complete else min_area
    raw_boxes = _component_boxes(image, alpha_threshold, active_min_area)
    high_boxes = _component_boxes(image, max(alpha_threshold, split_alpha_threshold), active_min_area) if complete else []
    accepted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    split_count = 0

    for raw in raw_boxes:
        likely_bad, reason = _is_likely_text_or_noise(raw["bbox"], int(raw["area"]), active_min_area)
        if likely_bad:
            skipped.append({"bbox": raw["bbox"], "area": raw["area"], "reason": reason})
            continue
        pieces = _maybe_split_merged_box(raw, high_boxes, active_min_area) if complete else [raw]
        if len(pieces) > 1:
            split_count += 1
        for piece in pieces:
            likely_bad, reason = _is_likely_text_or_noise(piece["bbox"], int(piece["area"]), active_min_area)
            if likely_bad:
                skipped.append({"bbox": piece["bbox"], "area": piece["area"], "reason": reason})
                continue
            accepted.append(piece)

    accepted = _dedupe_boxes(accepted)
    accepted, nested_skipped = _remove_nested_duplicates(accepted)
    skipped.extend(nested_skipped)
    review = {
        "mode": "complete" if complete else "major",
        "raw_component_count": len(raw_boxes),
        "accepted_count": len(accepted),
        "skipped_count": len(skipped),
        "split_merged_count": split_count,
        "skipped": skipped,
        "warnings": [],
    }
    if split_count:
        review["warnings"].append("split_merged_components")
    if skipped:
        review["warnings"].append("skipped_text_or_noise_candidates")
    return accepted, skipped, review


def _pad_box(box: list[int], padding: int, width: int, height: int) -> list[int]:
    left, top, right, bottom = box
    return [
        max(0, left - padding),
        max(0, top - padding),
        min(width, right + padding),
        min(height, bottom + padding),
    ]


def _sort_spatial(boxes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not boxes:
        return []
    heights = sorted(box["bbox"][3] - box["bbox"][1] for box in boxes)
    median_height = heights[len(heights) // 2]
    row_tolerance = max(12, int(median_height * 0.35))
    rows: list[list[dict[str, Any]]] = []
    for box in sorted(boxes, key=lambda item: item["bbox"][1]):
        y_mid = (box["bbox"][1] + box["bbox"][3]) / 2
        for row in rows:
            row_mid = sum((item["bbox"][1] + item["bbox"][3]) / 2 for item in row) / len(row)
            if abs(y_mid - row_mid) <= row_tolerance:
                row.append(box)
                break
        else:
            rows.append([box])
    sorted_boxes: list[dict[str, Any]] = []
    for row_index, row in enumerate(rows, start=1):
        for column_index, box in enumerate(sorted(row, key=lambda item: item["bbox"][0]), start=1):
            box["row"] = f"row_{row_index:02d}"
            box["column"] = f"col_{column_index:02d}"
            sorted_boxes.append(box)
    return sorted_boxes


def _write_detection_preview(image: Image.Image, boxes: list[dict[str, Any]], out_path: Path) -> None:
    preview = image.convert("RGBA")
    overlay = Image.new("RGBA", preview.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    colors = [
        (127, 217, 210, 210),
        (229, 198, 96, 210),
        (151, 213, 122, 210),
        (221, 143, 159, 210),
        (145, 184, 238, 210),
        (220, 180, 255, 210),
    ]
    for index, box in enumerate(boxes, start=1):
        color = colors[(index - 1) % len(colors)]
        draw.rectangle(box["bbox"], outline=color, width=4)
        draw.rectangle((box["bbox"][0] + 4, box["bbox"][1] + 4, box["bbox"][0] + 78, box["bbox"][1] + 30), fill=(10, 12, 18, 210))
        draw.text((box["bbox"][0] + 10, box["bbox"][1] + 9), f"asset_{index:02d}", fill=color)
    preview.alpha_composite(overlay)
    preview.save(out_path)


def auto_deconstruct_assets(
    sheet_path: Path,
    pipeline_root: Path,
    *,
    job_name: str | None = None,
    alpha_threshold: int = 8,
    min_area: int = 5000,
    padding: int = 0,
    group: str = "detected_assets",
    name_prefix: str = "asset",
    complete: bool = False,
    complete_min_area: int = 300,
    split_alpha_threshold: int = 32,
) -> dict[str, Any]:
    source = Image.open(sheet_path).convert("RGBA")
    width, height = source.size
    raw_boxes, skipped, review = _prepare_boxes(
        source,
        alpha_threshold=alpha_threshold,
        min_area=min_area,
        complete=complete,
        complete_min_area=complete_min_area,
        split_alpha_threshold=split_alpha_threshold,
    )
    boxes = _sort_spatial(raw_boxes)
    for box in boxes:
        box["bbox"] = _pad_box(box["bbox"], padding, width, height)

    job = _safe_name(job_name or f"{sheet_path.stem}_auto_assets")
    recipe = {
        "job": job,
        "match": {"filename_glob": [sheet_path.name]},
        "autodetect": {
            "source_path": str(sheet_path),
            "alpha_threshold": alpha_threshold,
            "min_area": min_area,
            "padding": padding,
            "complete": complete,
            "complete_min_area": complete_min_area,
            "split_alpha_threshold": split_alpha_threshold,
            "component_count": len(boxes),
            "review": review,
        },
        "groups": {
            group: {
                "cells": [
                    {
                        "filename": f"{name_prefix}_{index:02d}.png",
                        "row": box["row"],
                        "column": box["column"],
                        "bbox": box["bbox"],
                    }
                    for index, box in enumerate(boxes, start=1)
                ]
            }
        },
    }
    recipes_dir = pipeline_root / "recipes"
    recipes_dir.mkdir(parents=True, exist_ok=True)
    recipe_path = recipes_dir / f"{job}.json"
    recipe_path.write_text(json.dumps(recipe, indent=2), encoding="utf-8")

    job_dir = deconstruct_sheet(sheet_path, recipe_path, pipeline_root, job_name=job)
    verification = verify_deconstruct_lossless(job_dir)
    preview_path = job_dir / "autodetect-preview.png"
    _write_detection_preview(source, boxes, preview_path)

    manifest_path = job_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["autodetect"] = {
        "alpha_threshold": alpha_threshold,
        "min_area": min_area,
        "padding": padding,
        "complete": complete,
        "complete_min_area": complete_min_area,
        "split_alpha_threshold": split_alpha_threshold,
        "component_count": len(boxes),
        "preview_path": str(preview_path),
        "review": review,
    }
    review_path = job_dir / "autodetect-review.json"
    review_path.write_text(json.dumps(review, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return {
        "job": job,
        "job_dir": str(job_dir),
        "recipe_path": str(recipe_path),
        "source_path": str(sheet_path),
        "source_sha256": sha256_file(sheet_path),
        "source_dimensions": [width, height],
        "asset_count": len(boxes),
        "alpha_threshold": alpha_threshold,
        "min_area": min_area,
        "padding": padding,
        "complete": complete,
        "complete_min_area": complete_min_area,
        "split_alpha_threshold": split_alpha_threshold,
        "preview_path": str(preview_path),
        "review_path": str(review_path),
        "review": review,
        "deconstruct_lossless": bool(verification["deconstruct_lossless"]),
        "assets": [
            {
                "name": f"{name_prefix}_{index:02d}.png",
                "row": box["row"],
                "column": box["column"],
                "bbox": box["bbox"],
                "area": box["area"],
                "split_from": box.get("split_from"),
            }
            for index, box in enumerate(boxes, start=1)
        ],
    }
