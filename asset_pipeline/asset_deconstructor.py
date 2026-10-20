from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image


@dataclass(frozen=True)
class AssetCell:
    name: str
    group: str
    row: str | None
    column: str | None
    bbox: tuple[int, int, int, int]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_recipe(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        recipe = json.load(handle)
    if not recipe.get("job"):
        raise ValueError("recipe must include a job name")
    if not recipe.get("groups"):
        raise ValueError("recipe must include at least one group")
    return recipe


def _cell_name(pattern: str, row: str | None, column: str | None, index: int) -> str:
    return pattern.format(row=row or "", column=column or "", index=index)


def iter_cells(recipe: dict[str, Any]) -> list[AssetCell]:
    cells: list[AssetCell] = []
    for group_name, group in recipe["groups"].items():
        name_pattern = group.get("filename_pattern", "{column}-{row}.png")
        if "cells" in group:
            for index, cell in enumerate(group["cells"]):
                bbox = tuple(int(v) for v in cell["bbox"])
                if len(bbox) != 4:
                    raise ValueError(f"{group_name} cell {index} bbox must have four values")
                row = cell.get("row")
                column = cell.get("column")
                name = cell.get("filename") or _cell_name(name_pattern, row, column, index)
                cells.append(AssetCell(name, group_name, row, column, bbox))  # type: ignore[arg-type]
            continue

        grid = group.get("grid")
        rows = group.get("rows")
        columns = group.get("columns")
        if not grid or not rows or not columns:
            raise ValueError(f"group {group_name} must define cells or grid+rows+columns")

        x0 = int(grid.get("x", 0))
        y0 = int(grid.get("y", 0))
        cell_w = int(grid["cell_width"])
        cell_h = int(grid["cell_height"])
        gutter_x = int(grid.get("gutter_x", 0))
        gutter_y = int(grid.get("gutter_y", 0))

        for row_index, row in enumerate(rows):
            for col_index, column in enumerate(columns):
                left = x0 + col_index * (cell_w + gutter_x)
                top = y0 + row_index * (cell_h + gutter_y)
                bbox = (left, top, left + cell_w, top + cell_h)
                name = _cell_name(name_pattern, row, column, len(cells))
                cells.append(AssetCell(name, group_name, row, column, bbox))
    return cells


def deconstruct_sheet(sheet_path: Path, recipe_path: Path, pipeline_root: Path, job_name: str | None = None) -> Path:
    recipe = load_recipe(recipe_path)
    job = job_name or recipe["job"]
    job_dir = pipeline_root / "outbox" / job
    assets_dir = job_dir / "deconstructed"
    if job_dir.exists():
        shutil.rmtree(job_dir)
    assets_dir.mkdir(parents=True, exist_ok=True)

    source = Image.open(sheet_path).convert("RGBA")
    source_size = source.size
    manifest_assets: list[dict[str, Any]] = []

    for cell in iter_cells(recipe):
        left, top, right, bottom = cell.bbox
        if left < 0 or top < 0 or right > source_size[0] or bottom > source_size[1]:
            raise ValueError(f"{cell.name} bbox {cell.bbox} falls outside source {source_size}")
        out_path = assets_dir / cell.name
        group_path = job_dir / "groups" / cell.group / cell.name
        out_path.parent.mkdir(parents=True, exist_ok=True)
        source.crop(cell.bbox).save(out_path)
        group_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out_path, group_path)
        manifest_assets.append(
            {
                "name": cell.name,
                "group": cell.group,
                "row": cell.row,
                "column": cell.column,
                "source_bbox": list(cell.bbox),
                "source_dimensions": [right - left, bottom - top],
                "output_path": str(out_path.relative_to(job_dir)),
                "group_output_path": str(group_path.relative_to(job_dir)),
                "output_dimensions": [right - left, bottom - top],
                "output_sha256": sha256_file(out_path),
                "operations": ["deconstruct:lossless-cell-copy"],
            }
        )

    manifest = {
        "job": job,
        "source_path": str(sheet_path),
        "source_sha256": sha256_file(sheet_path),
        "source_dimensions": list(source_size),
        "recipe_path": str(recipe_path),
        "stage": "deconstruct",
        "assets": manifest_assets,
    }
    (job_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return job_dir
