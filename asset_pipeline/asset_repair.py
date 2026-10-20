from __future__ import annotations

import json
import math
from collections import deque
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter

from .asset_deconstructor import sha256_file


def _asset_path(job_dir: Path, asset: dict[str, Any]) -> Path:
    return job_dir / asset["output_path"]


def _organized_path(root: Path, asset: dict[str, Any]) -> Path:
    group = str(asset.get("group") or "assets")
    row = str(asset.get("row") or "").strip()
    if row:
        return root / group / row / asset["name"]
    return root / group / asset["name"]


def _component_mask(alpha: Image.Image, threshold: int, min_area: int, keep_largest: bool) -> tuple[Image.Image, dict[str, Any]]:
    alpha = alpha.convert("L")
    width, height = alpha.size
    pixels = alpha.load()
    seen: set[tuple[int, int]] = set()
    components: list[list[tuple[int, int]]] = []

    for y in range(height):
        for x in range(width):
            if pixels[x, y] < threshold or (x, y) in seen:
                continue
            queue: deque[tuple[int, int]] = deque([(x, y)])
            seen.add((x, y))
            component: list[tuple[int, int]] = []
            while queue:
                cx, cy = queue.popleft()
                component.append((cx, cy))
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < width and 0 <= ny < height and pixels[nx, ny] >= threshold and (nx, ny) not in seen:
                        seen.add((nx, ny))
                        queue.append((nx, ny))
            components.append(component)

    if not components:
        return Image.new("L", alpha.size, 0), {"components": 0, "removed_components": 0, "removed_pixels": 0}

    largest = max(components, key=len)
    kept: list[list[tuple[int, int]]] = []
    removed_pixels = 0
    for component in components:
        if keep_largest:
            keep = component is largest
        else:
            keep = len(component) >= min_area
        if keep:
            kept.append(component)
        else:
            removed_pixels += len(component)

    mask = Image.new("L", alpha.size, 0)
    mask_pixels = mask.load()
    for component in kept:
        for x, y in component:
            mask_pixels[x, y] = 255
    return mask, {
        "components": len(components),
        "removed_components": len(components) - len(kept),
        "removed_pixels": removed_pixels,
        "kept_components": len(kept),
    }


def _mask_area(mask: Image.Image) -> int:
    histogram = mask.convert("L").histogram()
    return sum(histogram[1:])


def _edge_transition_count(mask: Image.Image) -> int:
    alpha = mask.convert("L")
    width, height = alpha.size
    pixels = alpha.load()
    transitions = 0
    for y in range(height):
        for x in range(width):
            value = pixels[x, y] > 0
            if x + 1 < width and value != (pixels[x + 1, y] > 0):
                transitions += 1
            if y + 1 < height and value != (pixels[x, y + 1] > 0):
                transitions += 1
    return transitions


def _alpha_quality_score(mask: Image.Image, min_area: int) -> dict[str, int]:
    _, stats = _component_mask(mask, 1, min_area, False)
    transitions = _edge_transition_count(mask)
    small_penalty = int(stats["removed_components"]) * max(1, min_area) * 8
    return {
        "score": transitions + small_penalty,
        "edge_transitions": transitions,
        "small_components": int(stats["removed_components"]),
        "visible_pixels": _mask_area(mask),
    }


def _reshape_candidate(mask: Image.Image) -> Image.Image:
    binary = mask.convert("L").point(lambda value: 255 if value > 0 else 0)
    closed = binary.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    return closed.filter(ImageFilter.MedianFilter(3))


def _apply_alpha_with_edge_fill(image: Image.Image, alpha: Image.Image) -> Image.Image:
    image = image.convert("RGBA")
    old_alpha = image.getchannel("A")
    new_alpha = alpha.convert("L")
    blurred = image.filter(ImageFilter.GaussianBlur(1.2)).convert("RGBA")
    output = Image.new("RGBA", image.size, (0, 0, 0, 0))
    old_pixels = image.load()
    blur_pixels = blurred.load()
    out_pixels = output.load()
    old_alpha_pixels = old_alpha.load()
    new_alpha_pixels = new_alpha.load()
    width, height = image.size
    for y in range(height):
        for x in range(width):
            new_a = new_alpha_pixels[x, y]
            if new_a <= 0:
                continue
            source = old_pixels[x, y] if old_alpha_pixels[x, y] > 0 else blur_pixels[x, y]
            out_pixels[x, y] = (source[0], source[1], source[2], new_a)
    return output


def _contact_sheet(entries: list[dict[str, Any]], job_dir: Path, out_path: Path) -> None:
    if not entries:
        return
    thumb = 112
    label_h = 28
    gutter = 16
    columns = min(6, max(1, math.ceil(math.sqrt(len(entries)))))
    rows = math.ceil(len(entries) / columns)
    sheet = Image.new("RGBA", (columns * (thumb + gutter) + gutter, rows * (thumb + label_h + gutter) + gutter), (16, 18, 24, 255))
    draw = ImageDraw.Draw(sheet)
    for index, entry in enumerate(entries):
        with Image.open(job_dir / entry["output_path"]) as raw:
            image = raw.convert("RGBA")
        image.thumbnail((thumb, thumb), Image.Resampling.LANCZOS)
        col = index % columns
        row = index // columns
        x = gutter + col * (thumb + gutter)
        y = gutter + row * (thumb + label_h + gutter)
        sheet.alpha_composite(image, (x + (thumb - image.width) // 2, y + (thumb - image.height) // 2))
        draw.text((x, y + thumb + 4), entry["name"][:22], fill=(235, 238, 245, 255))
    sheet.save(out_path)


def repair_icons(
    job_dir: Path,
    *,
    alpha_threshold: int = 1,
    min_component_area: int = 24,
    keep_largest_component: bool = False,
    smooth_alpha: bool = True,
    reshape_candidate: bool = False,
    max_reshape_growth_ratio: float = 0.08,
    max_fill_ratio: float | None = None,
) -> dict[str, Any]:
    manifest_path = job_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    out_root = job_dir / "repaired"
    entries: list[dict[str, Any]] = []
    total_removed_components = 0
    total_removed_pixels = 0
    fill_ratio_limit = max_reshape_growth_ratio if max_fill_ratio is None else max_fill_ratio
    reshape_accepted_count = 0
    reshape_rejected_count = 0

    for asset in manifest["assets"]:
        source_path = _asset_path(job_dir, asset)
        with Image.open(source_path) as raw:
            image = raw.convert("RGBA")
        alpha = image.getchannel("A")
        mask, stats = _component_mask(alpha, alpha_threshold, min_component_area, keep_largest_component)
        if smooth_alpha:
            mask = mask.filter(ImageFilter.MedianFilter(3))
        original_alpha = image.getchannel("A")
        cleaned_alpha = Image.composite(original_alpha, Image.new("L", image.size, 0), mask)
        repaired = image.copy()
        repaired.putalpha(cleaned_alpha)
        reshape = {
            "attempted": reshape_candidate,
            "accepted": False,
            "reason": "not requested",
        }
        if reshape_candidate:
            candidate_alpha = _reshape_candidate(cleaned_alpha)
            base_score = _alpha_quality_score(cleaned_alpha, min_component_area)
            candidate_score = _alpha_quality_score(candidate_alpha, min_component_area)
            growth = candidate_score["visible_pixels"] - base_score["visible_pixels"]
            missing_fill_ratio = max(0, growth) / max(1, base_score["visible_pixels"])
            growth_limit = max(16, int(max(1, base_score["visible_pixels"]) * fill_ratio_limit))
            improves = candidate_score["score"] < base_score["score"]
            within_fill_budget = missing_fill_ratio <= fill_ratio_limit and growth <= growth_limit
            if improves and within_fill_budget:
                repaired = _apply_alpha_with_edge_fill(image, candidate_alpha)
                reshape = {
                    "attempted": True,
                    "accepted": True,
                    "reason": "candidate scored better within fill budget",
                    "growth_pixels": growth,
                    "growth_limit": growth_limit,
                    "missing_fill_ratio": missing_fill_ratio,
                    "max_fill_ratio": fill_ratio_limit,
                    "before": base_score,
                    "after": candidate_score,
                }
            else:
                reason_parts = []
                if not improves:
                    reason_parts.append("candidate did not improve quality score")
                if not within_fill_budget:
                    reason_parts.append("candidate needed too much fill")
                reshape = {
                    "attempted": True,
                    "accepted": False,
                    "reason": "; ".join(reason_parts) or "candidate rejected",
                    "growth_pixels": growth,
                    "growth_limit": growth_limit,
                    "missing_fill_ratio": missing_fill_ratio,
                    "max_fill_ratio": fill_ratio_limit,
                    "before": base_score,
                    "after": candidate_score,
                }
            if reshape["accepted"]:
                reshape_accepted_count += 1
            else:
                reshape_rejected_count += 1

        out_path = _organized_path(out_root, asset)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        repaired.save(out_path)
        total_removed_components += int(stats["removed_components"])
        total_removed_pixels += int(stats["removed_pixels"])
        entries.append(
            {
                "name": asset["name"],
                "group": asset.get("group"),
                "row": asset.get("row"),
                "column": asset.get("column"),
                "source_output_path": asset["output_path"],
                "output_path": str(out_path.relative_to(job_dir)),
                "output_dimensions": list(repaired.size),
                "output_sha256": sha256_file(out_path),
                "operations": list(asset.get("operations", [])) + ["repair:alpha-component-cleanup"],
                "repair": stats | {
                    "alpha_threshold": alpha_threshold,
                    "min_component_area": min_component_area,
                    "keep_largest_component": keep_largest_component,
                    "smooth_alpha": smooth_alpha,
                    "reshape": reshape,
                },
            }
        )

    repair_manifest = {
        "job": manifest["job"],
        "stage": "repair",
        "source_manifest": str(manifest_path),
        "organization": "repaired/<group>/<row>/<asset>",
        "asset_count": len(entries),
        "removed_components": total_removed_components,
        "removed_pixels": total_removed_pixels,
        "reshape_candidate": reshape_candidate,
        "reshape_accepted": reshape_accepted_count,
        "reshape_rejected": reshape_rejected_count,
        "max_fill_ratio": fill_ratio_limit,
        "assets": entries,
    }
    repair_manifest_path = job_dir / "repair-manifest.json"
    repair_manifest_path.write_text(json.dumps(repair_manifest, indent=2), encoding="utf-8")
    contact_path = job_dir / "repair-contact-sheet.png"
    _contact_sheet(entries, job_dir, contact_path)
    repair_manifest["contact_sheet"] = str(contact_path)
    repair_manifest_path.write_text(json.dumps(repair_manifest, indent=2), encoding="utf-8")
    return repair_manifest
