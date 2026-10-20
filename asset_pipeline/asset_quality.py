from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

try:
    from .asset_deconstructor import sha256_file
except ImportError:
    from asset_deconstructor import sha256_file


def visible_bbox(image: Image.Image, alpha_threshold: int = 1) -> list[int] | None:
    alpha = image.convert("RGBA").getchannel("A")
    mask = alpha.point(lambda value: 255 if value >= alpha_threshold else 0)
    bbox = mask.getbbox()
    return list(bbox) if bbox else None


def average_hash(image_path: Path, size: int = 16) -> str:
    with Image.open(image_path) as image:
        rgba = image.convert("RGBA")
        bbox = visible_bbox(rgba)
        if bbox:
            rgba = rgba.crop(tuple(bbox))
        background = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
        background.alpha_composite(rgba)
        gray = background.convert("L").resize((size, size), Image.Resampling.LANCZOS)
    pixels = list(gray.getdata())
    average = sum(pixels) / len(pixels)
    bits = "".join("1" if pixel >= average else "0" for pixel in pixels)
    return f"{int(bits, 2):0{size * size // 4}x}"


def hamming_distance(left: str, right: str) -> int:
    return bin(int(left, 16) ^ int(right, 16)).count("1")


def score_asset(image_path: Path, *, alpha_threshold: int = 1) -> dict[str, Any]:
    with Image.open(image_path) as image:
        rgba = image.convert("RGBA")
        bbox = visible_bbox(rgba, alpha_threshold=alpha_threshold)
        width, height = rgba.size
        if bbox is None:
            return {
                "path": str(image_path),
                "width": width,
                "height": height,
                "visible_bbox": None,
                "visible_ratio": 0.0,
                "edge_contact": True,
                "quality_state": "reject",
                "warnings": ["empty_or_fully_transparent"],
                "average_hash": average_hash(image_path),
                "sha256": sha256_file(image_path),
            }

        left, top, right, bottom = bbox
        visible_width = right - left
        visible_height = bottom - top
        visible_ratio = (visible_width * visible_height) / max(1, width * height)
        edge_contact = left <= 0 or top <= 0 or right >= width or bottom >= height
        warnings: list[str] = []
        if edge_contact:
            warnings.append("visible_pixels_touch_canvas_edge")
        if visible_ratio < 0.05:
            warnings.append("very_small_visible_footprint")
        if visible_ratio > 0.96:
            warnings.append("little_or_no_transparent_padding")

        quality_state = "pass"
        if edge_contact or visible_ratio < 0.02:
            quality_state = "review"
        if visible_ratio <= 0:
            quality_state = "reject"

        return {
            "path": str(image_path),
            "width": width,
            "height": height,
            "visible_bbox": bbox,
            "visible_ratio": round(visible_ratio, 4),
            "edge_contact": edge_contact,
            "quality_state": quality_state,
            "warnings": warnings,
            "average_hash": average_hash(image_path),
            "sha256": sha256_file(image_path),
        }


def _duplicate_groups(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups_by_hash: dict[str, list[dict[str, Any]]] = {}
    for asset in assets:
        groups_by_hash.setdefault(asset["sha256"], []).append(asset)
    return [
        {
            "state": "exact_file_duplicate",
            "sha256": digest,
            "count": len(items),
            "assets": [item["path"] for item in items],
        }
        for digest, items in sorted(groups_by_hash.items())
        if len(items) > 1
    ]


def score_assets(asset_paths: list[Path], *, duplicate_distance: int = 0) -> dict[str, Any]:
    assets = []
    duplicate_pairs = []
    for path in asset_paths:
        quality = score_asset(path)
        quality["name"] = path.name
        assets.append(quality)

    for left_index, left in enumerate(assets):
        for right in assets[left_index + 1:]:
            same_file = left["sha256"] == right["sha256"]
            same_size = left["width"] == right["width"] and left["height"] == right["height"]
            distance = hamming_distance(left["average_hash"], right["average_hash"])
            if same_file or (same_size and distance <= duplicate_distance):
                duplicate_pairs.append(
                    {
                        "left": left["path"],
                        "right": right["path"],
                        "distance": distance,
                        "state": "exact_file_duplicate" if same_file else "exact_visual_hash_duplicate",
                    }
                )

    states = [asset["quality_state"] for asset in assets]
    duplicate_groups = _duplicate_groups(assets)
    return {
        "asset_count": len(assets),
        "pass_count": states.count("pass"),
        "review_count": states.count("review"),
        "reject_count": states.count("reject"),
        "duplicate_group_count": len(duplicate_groups),
        "duplicate_pair_count": len(duplicate_pairs),
        "duplicate_asset_count": len({path for group in duplicate_groups for path in group["assets"]}),
        "duplicate_groups": duplicate_groups,
        "duplicate_pairs": duplicate_pairs,
        "assets": assets,
    }
