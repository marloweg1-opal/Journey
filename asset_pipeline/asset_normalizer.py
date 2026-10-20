from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image

from .asset_deconstructor import sha256_file


def alpha_bbox(image: Image.Image, threshold: int = 1) -> tuple[int, int, int, int] | None:
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    mask = alpha.point(lambda value: 255 if value >= threshold else 0)
    return mask.getbbox()


def padded_bbox(
    bbox: tuple[int, int, int, int],
    size: tuple[int, int],
    padding: int,
) -> tuple[int, int, int, int]:
    left, top, right, bottom = bbox
    width, height = size
    return (
        max(0, left - padding),
        max(0, top - padding),
        min(width, right + padding),
        min(height, bottom + padding),
    )


def union_bbox(bounds: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int] | None:
    if not bounds:
        return None
    return (
        min(b[0] for b in bounds),
        min(b[1] for b in bounds),
        max(b[2] for b in bounds),
        max(b[3] for b in bounds),
    )


def smart_crop_glow_asset(
    image: Image.Image,
    alpha_threshold: int = 1,
    padding: int = 2,
) -> tuple[Image.Image, tuple[int, int, int, int] | None]:
    bbox = alpha_bbox(image, alpha_threshold)
    if bbox is None:
        return image.copy(), None
    crop_box = padded_bbox(bbox, image.size, padding)
    return image.crop(crop_box), crop_box


def normalize_job(
    job_dir: Path,
    alpha_threshold: int = 1,
    padding: int = 2,
    state_group_key: str = "column",
) -> Path:
    manifest_path = job_dir / "manifest.json"
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_assets = manifest["assets"]
    in_dir = job_dir / "deconstructed"
    out_dir = job_dir / "normalized"
    out_dir.mkdir(parents=True, exist_ok=True)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for asset in source_assets:
        key = str(asset.get(state_group_key) or asset["name"])
        grouped.setdefault(key, []).append(asset)

    normalized_assets: list[dict[str, Any]] = []
    for _, assets in grouped.items():
        images = [(asset, Image.open(job_dir / asset["output_path"]).convert("RGBA")) for asset in assets]
        bounds = [bbox for _, image in images if (bbox := alpha_bbox(image, alpha_threshold))]
        common = union_bbox(bounds)
        if common is not None:
            common = padded_bbox(common, images[0][1].size, padding)

        for asset, image in images:
            if common is None:
                normalized = image.copy()
                crop_box = None
            else:
                normalized = image.crop(common)
                crop_box = list(common)
            out_path = out_dir / asset["name"]
            normalized.save(out_path)
            entry = dict(asset)
            entry["output_path"] = str(out_path.relative_to(job_dir))
            entry["output_dimensions"] = list(normalized.size)
            entry["output_sha256"] = sha256_file(out_path)
            entry["normalization"] = {
                "operation": "state-group-union-alpha-crop",
                "state_group_key": state_group_key,
                "alpha_threshold": alpha_threshold,
                "padding": padding,
                "crop_box": crop_box,
                "source_alpha_preserved": True,
            }
            entry["operations"] = asset["operations"] + ["normalize:state-group-union-alpha-crop"]
            normalized_assets.append(entry)

    manifest["stage"] = "normalize"
    manifest["assets"] = normalized_assets
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return out_dir
