from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

from .asset_deconstructor import sha256_file


def _asset_path(job_dir: Path, asset: dict[str, Any]) -> Path:
    return job_dir / asset["output_path"]


def build_reconstruction_proof(job_dir: Path) -> Path:
    manifest = json.loads((job_dir / "manifest.json").read_text(encoding="utf-8"))
    assets = manifest["assets"]
    if not assets:
        raise ValueError("manifest contains no assets")

    boxes = [asset["source_bbox"] for asset in assets]
    max_right = max(box[2] for box in boxes)
    max_bottom = max(box[3] for box in boxes)
    min_left = min(box[0] for box in boxes)
    min_top = min(box[1] for box in boxes)
    proof = Image.new("RGBA", (max_right - min_left, max_bottom - min_top), (0, 0, 0, 0))

    for asset in assets:
        image = Image.open(_asset_path(job_dir, asset)).convert("RGBA")
        left, top, _, _ = asset["source_bbox"]
        proof.alpha_composite(image, (left - min_left, top - min_top))

    proof_path = job_dir / "reconstruction-proof.png"
    proof.save(proof_path)
    return proof_path


def verify_deconstruct_lossless(job_dir: Path) -> dict[str, Any]:
    manifest_path = job_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = Image.open(manifest["source_path"]).convert("RGBA")
    results = []
    all_pass = True

    for asset in manifest["assets"]:
        output = Image.open(_asset_path(job_dir, asset)).convert("RGBA")
        source_region = source.crop(tuple(asset["source_bbox"]))
        diff = ImageChops.difference(source_region, output)
        exact = diff.getbbox() is None
        if not exact:
            all_pass = False
        asset["output_sha256"] = sha256_file(_asset_path(job_dir, asset))
        results.append({"name": asset["name"], "exact_pixel_match": exact})

    proof_path = build_reconstruction_proof(job_dir)
    manifest["verification"] = {
        "deconstruct_lossless": all_pass,
        "asset_checks": results,
        "reconstruction_proof": str(proof_path.relative_to(job_dir)),
        "proof_sha256": sha256_file(proof_path),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest["verification"]
