from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._-")
    return cleaned or "asset_sheet"


def parse_slots(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        raw_slots = value
    else:
        raw_slots = re.split(r"[\n,]+", value)
    slots = []
    for raw in raw_slots:
        slot = safe_name(str(raw))
        if slot and slot not in slots:
            slots.append(slot)
    if not slots:
        raise ValueError("At least one asset slot is required.")
    return slots


def build_recipe_bound_brief(
    pipeline_root: Path,
    *,
    job: str,
    slots: str | list[str],
    columns: int,
    cell_width: int,
    cell_height: int,
    gutter_x: int = 32,
    gutter_y: int = 32,
    margin_x: int = 64,
    margin_y: int = 64,
    safe_zone_width: int | None = None,
    safe_zone_height: int | None = None,
    style: str = "",
    background: str = "transparent",
    group: str = "generated_assets",
) -> dict[str, Any]:
    if columns < 1:
        raise ValueError("columns must be at least 1.")
    if cell_width < 1 or cell_height < 1:
        raise ValueError("cell dimensions must be positive.")
    if min(gutter_x, gutter_y, margin_x, margin_y) < 0:
        raise ValueError("gutters and margins must be zero or greater.")

    slot_names = parse_slots(slots)
    rows = (len(slot_names) + columns - 1) // columns
    canvas_width = margin_x * 2 + columns * cell_width + (columns - 1) * gutter_x
    canvas_height = margin_y * 2 + rows * cell_height + (rows - 1) * gutter_y
    safe_w = safe_zone_width or max(1, cell_width - 24)
    safe_h = safe_zone_height or max(1, cell_height - 24)
    if safe_w > cell_width or safe_h > cell_height:
        raise ValueError("safe zone must fit inside each cell.")

    job_name = safe_name(job)
    cells = []
    slot_lines = []
    for index, slot in enumerate(slot_names):
        row = index // columns
        column = index % columns
        left = margin_x + column * (cell_width + gutter_x)
        top = margin_y + row * (cell_height + gutter_y)
        cells.append(
            {
                "filename": f"{slot}.png",
                "row": f"row_{row + 1}",
                "column": slot,
                "bbox": [left, top, left + cell_width, top + cell_height],
            }
        )
        slot_lines.append(f"- Cell row {row + 1}, column {column + 1}: `{slot}`")

    recipe = {
        "job": job_name,
        "match": {"filename_contains": [token for token in job_name.lower().split("_") if token]},
        "canvas": {
            "width": canvas_width,
            "height": canvas_height,
            "columns": columns,
            "rows": rows,
            "cell_width": cell_width,
            "cell_height": cell_height,
            "gutter_x": gutter_x,
            "gutter_y": gutter_y,
            "margin_x": margin_x,
            "margin_y": margin_y,
            "safe_zone_width": safe_w,
            "safe_zone_height": safe_h,
        },
        "groups": {
            group: {
                "cells": cells,
            }
        },
    }

    prompt = f"""Create a PNG asset sheet for `{job_name}` using this exact layout.

Canvas: {canvas_width} x {canvas_height} px.
Background: {background}.
Grid: {columns} columns x {rows} rows.
Cell size: {cell_width} x {cell_height} px.
Outer margin: {margin_x} px horizontal, {margin_y} px vertical.
Gutter: {gutter_x} px horizontal, {gutter_y} px vertical.
Visual safe zone inside each cell: {safe_w} x {safe_h} px.

Style:
{style or "Clean, interface-ready assets with consistent lighting and no text."}

Rules:
- Keep each asset centered in its assigned cell.
- Keep all glow, shadow, ornament, and edge detail inside that cell.
- Leave gutters and margins empty/transparent unless the requested background says otherwise.
- Do not add labels, captions, watermarks, sample UI, panels, mock screens, or explanatory text.
- Do not merge cells or allow assets to overlap neighboring cells.
- Create isolated reusable interface parts, not a finished dashboard mockup.

Required slots:
{chr(10).join(slot_lines)}

After generating the image, preserve this companion extraction recipe as the deconstruction recipe for the sheet.
"""

    recipes_dir = pipeline_root / "recipes"
    out_dir = pipeline_root / "outbox" / f"{job_name}__imagegen_brief"
    recipes_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    recipe_path = recipes_dir / f"{job_name}.json"
    brief_path = out_dir / "imagegen-brief.md"
    job_recipe_path = out_dir / f"{job_name}.recipe.json"
    recipe_text = json.dumps(recipe, indent=2)
    recipe_path.write_text(recipe_text, encoding="utf-8")
    job_recipe_path.write_text(recipe_text, encoding="utf-8")
    brief_path.write_text(prompt, encoding="utf-8")

    return {
        "job": job_name,
        "canvas": recipe["canvas"],
        "slot_count": len(slot_names),
        "recipe_path": str(recipe_path),
        "brief_path": str(brief_path),
        "job_dir": str(out_dir),
        "prompt": prompt,
    }
