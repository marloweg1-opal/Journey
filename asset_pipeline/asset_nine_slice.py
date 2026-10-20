from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image

from .asset_deconstructor import sha256_file


NINE_SLICE_NAMES = (
    ("top_left", "top", "top_right"),
    ("left", "center", "right"),
    ("bottom_left", "bottom", "bottom_right"),
)


def _safe_job_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "._-" else "_" for char in value).strip("._-")
    return cleaned or "nine_slice"


def _boxes(width: int, height: int, left: int, top: int, right: int, bottom: int) -> list[tuple[str, tuple[int, int, int, int]]]:
    if min(left, top, right, bottom) < 0:
        raise ValueError("Insets must be zero or greater.")
    if left + right >= width or top + bottom >= height:
        raise ValueError("Insets must leave a center region.")
    xs = (0, left, width - right, width)
    ys = (0, top, height - bottom, height)
    cells: list[tuple[str, tuple[int, int, int, int]]] = []
    for row in range(3):
        for column in range(3):
            cells.append((NINE_SLICE_NAMES[row][column], (xs[column], ys[row], xs[column + 1], ys[row + 1])))
    return cells


def _suggest_axis_inset(total: int) -> int:
    if total <= 3:
        return 1
    return min(max(2, round(total * 0.16)), max(1, total // 3 - 1))


def suggest_nine_slice_insets(image_path: Path) -> dict[str, int]:
    """Return conservative 9-slice guide estimates for a frame or panel image."""
    with Image.open(image_path) as source:
        horizontal = _suggest_axis_inset(source.width)
        vertical = _suggest_axis_inset(source.height)
    return {"left": horizontal, "top": vertical, "right": horizontal, "bottom": vertical}


def build_nine_slice(
    image_path: Path,
    pipeline_root: Path,
    *,
    left: int,
    top: int,
    right: int,
    bottom: int,
    job_name: str | None = None,
    inferred: bool = False,
) -> Path:
    source = Image.open(image_path).convert("RGBA")
    job = _safe_job_name(job_name or f"nine_slice__{image_path.stem}")
    job_dir = pipeline_root / "outbox" / job
    slice_dir = job_dir / "nine_slice"
    slice_dir.mkdir(parents=True, exist_ok=True)

    manifest_assets: list[dict[str, Any]] = []
    for name, bbox in _boxes(source.width, source.height, left, top, right, bottom):
        output_path = slice_dir / f"{name}.png"
        cell_image = source.crop(bbox)
        cell_image.save(output_path)
        manifest_assets.append(
            {
                "name": f"{name}.png",
                "role": name,
                "source_bbox": list(bbox),
                "output_path": str(output_path.relative_to(job_dir)),
                "output_dimensions": list(cell_image.size),
                "output_sha256": sha256_file(output_path),
                "operations": ["nine-slice:extract-region"],
            }
        )

    css_token_path = job_dir / "nine-slice.tokens.json"
    css_token_path.write_text(
        json.dumps(
            {
                "source": str(image_path),
                "border_image_slice": [top, right, bottom, left],
                "css": f"border-image-slice: {top} {right} {bottom} {left};",
                "inferred": inferred,
                "notes": "Use the extracted cells for engines that need true 9-part composition. Use the CSS token for web-style border-image experiments.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    manifest = {
        "job": job,
        "stage": "nine_slice",
        "source_path": str(image_path),
        "source_sha256": sha256_file(image_path),
        "source_dimensions": [source.width, source.height],
        "insets": {"left": left, "top": top, "right": right, "bottom": bottom},
        "insets_inferred": inferred,
        "inset_guide": "Insets are protected border distances from each source edge. Corners stay fixed; top/bottom and left/right repeat or stretch; center is the stretchable interior.",
        "assets": manifest_assets,
        "tokens": str(css_token_path.relative_to(job_dir)),
    }
    (job_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return job_dir
