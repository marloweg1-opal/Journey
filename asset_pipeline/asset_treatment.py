from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageOps

from .asset_deconstructor import sha256_file
from .asset_normalizer import smart_crop_glow_asset


def _safe_job_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "._-" else "_" for char in value).strip("._-")
    return cleaned or "treated_asset"


def _parse_hex_color(value: str) -> tuple[int, int, int]:
    cleaned = value.strip().lstrip("#")
    if len(cleaned) != 6:
        raise ValueError("Tint color must be a 6-digit hex value.")
    return tuple(int(cleaned[index:index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def _apply_tint(image: Image.Image, color: str, strength: float) -> Image.Image:
    strength = max(0.0, min(1.0, strength))
    if strength == 0:
        return image
    rgba = image.convert("RGBA")
    tint = Image.new("RGBA", rgba.size, (*_parse_hex_color(color), 255))
    blended_rgb = Image.blend(rgba.convert("RGB"), tint.convert("RGB"), strength)
    blended = blended_rgb.convert("RGBA")
    blended.putalpha(rgba.getchannel("A"))
    return blended


def _add_shadow(image: Image.Image, blur: int, offset: tuple[int, int], opacity: int) -> Image.Image:
    blur = max(0, blur)
    opacity = max(0, min(255, opacity))
    rgba = image.convert("RGBA")
    shadow_alpha = rgba.getchannel("A").filter(ImageFilter.GaussianBlur(blur))
    shadow = Image.new("RGBA", rgba.size, (0, 0, 0, opacity))
    shadow.putalpha(shadow_alpha.point(lambda value: int(value * (opacity / 255))))

    ox, oy = offset
    pad_left = max(blur - ox, blur, 0)
    pad_top = max(blur - oy, blur, 0)
    pad_right = max(blur + ox, blur, 0)
    pad_bottom = max(blur + oy, blur, 0)
    canvas = Image.new("RGBA", (rgba.width + pad_left + pad_right, rgba.height + pad_top + pad_bottom), (0, 0, 0, 0))
    canvas.alpha_composite(shadow, (pad_left + ox, pad_top + oy))
    canvas.alpha_composite(rgba, (pad_left, pad_top))
    return canvas


def treat_asset(
    image_path: Path,
    pipeline_root: Path,
    *,
    job_name: str | None = None,
    trim: bool = False,
    padding: int = 0,
    max_width: int | None = None,
    max_height: int | None = None,
    tint: str | None = None,
    tint_strength: float = 0.0,
    shadow_blur: int = 0,
    shadow_offset_x: int = 0,
    shadow_offset_y: int = 0,
    shadow_opacity: int = 128,
) -> Path:
    source = Image.open(image_path).convert("RGBA")
    image = source
    operations: list[str] = []
    treatment: dict[str, Any] = {}

    if trim:
        image, crop_box = smart_crop_glow_asset(image, alpha_threshold=1, padding=max(0, padding))
        treatment["trim"] = {"padding": max(0, padding), "crop_box": list(crop_box) if crop_box else None}
        operations.append("treat:alpha-trim")
    elif padding > 0:
        image = ImageOps.expand(image, border=padding, fill=(0, 0, 0, 0))
        treatment["padding"] = padding
        operations.append("treat:transparent-padding")

    if max_width or max_height:
        max_w = max_width or image.width
        max_h = max_height or image.height
        image.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
        treatment["fit"] = {"max_width": max_w, "max_height": max_h}
        operations.append("treat:fit-lanczos")

    if tint:
        image = _apply_tint(image, tint, tint_strength)
        treatment["tint"] = {"color": tint, "strength": max(0.0, min(1.0, tint_strength))}
        operations.append("treat:preserve-alpha-tint")

    if shadow_blur > 0 or shadow_offset_x or shadow_offset_y:
        image = _add_shadow(image, shadow_blur, (shadow_offset_x, shadow_offset_y), shadow_opacity)
        treatment["shadow"] = {
            "blur": shadow_blur,
            "offset": [shadow_offset_x, shadow_offset_y],
            "opacity": max(0, min(255, shadow_opacity)),
        }
        operations.append("treat:drop-shadow")

    job = _safe_job_name(job_name or f"treated__{image_path.stem}")
    job_dir = pipeline_root / "outbox" / job
    out_dir = job_dir / "treated"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{image_path.stem}.png"
    image.save(out_path)

    manifest = {
        "job": job,
        "stage": "treat",
        "source_path": str(image_path),
        "source_sha256": sha256_file(image_path),
        "source_dimensions": list(source.size),
        "assets": [
            {
                "name": out_path.name,
                "output_path": str(out_path.relative_to(job_dir)),
                "output_dimensions": list(image.size),
                "output_sha256": sha256_file(out_path),
                "operations": operations or ["treat:copy-rgba"],
                "treatment": treatment,
            }
        ],
    }
    (job_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return job_dir
