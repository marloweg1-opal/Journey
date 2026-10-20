from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from .asset_deconstructor import sha256_file
from .asset_normalizer import alpha_bbox


def _asset_path(job_dir: Path, asset: dict[str, Any]) -> Path:
    return job_dir / asset["output_path"]


def _source_manifest(job_dir: Path) -> tuple[Path, dict[str, Any], str]:
    repair_manifest_path = job_dir / "repair-manifest.json"
    if repair_manifest_path.exists():
        return repair_manifest_path, json.loads(repair_manifest_path.read_text(encoding="utf-8")), "repair"
    manifest_path = job_dir / "manifest.json"
    return manifest_path, json.loads(manifest_path.read_text(encoding="utf-8")), "deconstruct"


def _parse_target_size(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    cleaned = value.lower().replace(" ", "")
    if "x" in cleaned:
        left, right = cleaned.split("x", 1)
        width = int(left)
        height = int(right)
    else:
        width = height = int(cleaned)
    if width < 1 or height < 1:
        raise ValueError("target size must be positive")
    return width, height


def _organized_path(root: Path, asset: dict[str, Any]) -> Path:
    group = str(asset.get("group") or "assets")
    row = str(asset.get("row") or "").strip()
    if row:
        return root / group / row / asset["name"]
    return root / group / asset["name"]


def _fit_inside(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    copy = image.copy()
    copy.thumbnail(size, Image.Resampling.LANCZOS)
    return copy


def _contact_sheet(entries: list[dict[str, Any]], out_path: Path) -> None:
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
        with Image.open(out_path.parent / entry["output_path"]) as raw:
            image = raw.convert("RGBA")
        preview = _fit_inside(image, (thumb, thumb))
        col = index % columns
        row = index // columns
        x = gutter + col * (thumb + gutter)
        y = gutter + row * (thumb + label_h + gutter)
        sheet.alpha_composite(preview, (x + (thumb - preview.width) // 2, y + (thumb - preview.height) // 2))
        draw.text((x, y + thumb + 4), entry["name"][:22], fill=(235, 238, 245, 255))
    sheet.save(out_path)


def precision_icons(
    job_dir: Path,
    *,
    padding: int = 8,
    alpha_threshold: int = 1,
    target_size: str | None = None,
    square: bool = True,
) -> dict[str, Any]:
    manifest_path, manifest, source_stage = _source_manifest(job_dir)
    source_assets = manifest["assets"]
    prepared: list[tuple[dict[str, Any], Image.Image, tuple[int, int, int, int] | None]] = []

    max_width = 1
    max_height = 1
    for asset in source_assets:
        image = Image.open(_asset_path(job_dir, asset)).convert("RGBA")
        bbox = alpha_bbox(image, alpha_threshold)
        if bbox is None:
            cropped = image.copy()
        else:
            cropped = image.crop(bbox)
        max_width = max(max_width, cropped.width + padding * 2)
        max_height = max(max_height, cropped.height + padding * 2)
        prepared.append((asset, cropped, bbox))

    parsed_target = _parse_target_size(target_size)
    if parsed_target is None:
        if square:
            side = max(max_width, max_height)
            canvas_size = (side, side)
        else:
            canvas_size = (max_width, max_height)
    else:
        canvas_size = parsed_target

    out_root = job_dir / "precision"
    entries: list[dict[str, Any]] = []
    for asset, cropped, bbox in prepared:
        fitted = _fit_inside(cropped, (max(1, canvas_size[0] - padding * 2), max(1, canvas_size[1] - padding * 2)))
        canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
        offset = ((canvas_size[0] - fitted.width) // 2, (canvas_size[1] - fitted.height) // 2)
        canvas.alpha_composite(fitted, offset)
        out_path = _organized_path(out_root, asset)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(out_path)
        entry = {
            "name": asset["name"],
            "group": asset.get("group"),
            "row": asset.get("row"),
            "column": asset.get("column"),
            "source_output_path": asset["output_path"],
            "source_stage": source_stage,
            "visible_bbox": list(bbox) if bbox else None,
            "output_path": str(out_path.relative_to(job_dir)),
            "output_dimensions": list(canvas.size),
            "output_sha256": sha256_file(out_path),
            "operations": list(asset.get("operations", [])) + ["precision:alpha-trim-center-canvas"],
        }
        entries.append(entry)

    precision_manifest = {
        "job": manifest["job"],
        "stage": "precision",
        "source_manifest": str(manifest_path),
        "source_stage": source_stage,
        "canvas_size": list(canvas_size),
        "padding": padding,
        "alpha_threshold": alpha_threshold,
        "organization": "precision/<group>/<row>/<asset>",
        "asset_count": len(entries),
        "assets": entries,
    }
    precision_manifest_path = job_dir / "precision-manifest.json"
    precision_manifest_path.write_text(json.dumps(precision_manifest, indent=2), encoding="utf-8")
    contact_path = job_dir / "precision-contact-sheet.png"
    _contact_sheet(entries, contact_path)
    precision_manifest["contact_sheet"] = str(contact_path)
    precision_manifest_path.write_text(json.dumps(precision_manifest, indent=2), encoding="utf-8")
    return precision_manifest
