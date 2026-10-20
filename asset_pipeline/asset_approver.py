from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

try:
    from .asset_deconstructor import sha256_file
    from .asset_quality import score_assets
except ImportError:
    from asset_deconstructor import sha256_file
    from asset_quality import score_assets


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-").lower()
    return cleaned or "asset_set"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _best_asset_source(job_dir: Path) -> tuple[str, Path]:
    if (job_dir / "precision-manifest.json").exists() and (job_dir / "precision").exists():
        return "precision", job_dir / "precision"
    if (job_dir / "repair-manifest.json").exists() and (job_dir / "repaired").exists():
        return "repair", job_dir / "repaired"
    if (job_dir / "nine_slice").exists():
        return "nine_slice", job_dir / "nine_slice"
    if (job_dir / "parts").exists():
        return "parts", job_dir / "parts"
    groups = job_dir / "groups"
    if groups.exists():
        return "groups", groups
    return "deconstructed", job_dir / "deconstructed"


def _iter_pngs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*.png") if path.is_file())


def _copy_tree_pngs(source_root: Path, destination_root: Path) -> list[dict[str, Any]]:
    copied = []
    for source in _iter_pngs(source_root):
        relative = source.relative_to(source_root)
        destination = destination_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append(
            {
                "source": str(source),
                "output": str(destination),
                "sha256": sha256_file(destination),
            }
        )
    return copied


def approve_job(
    pipeline_root: Path,
    job: str,
    *,
    family: str | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    job_name = _safe_name(job)
    job_dir = pipeline_root / "outbox" / job_name
    if not job_dir.exists() or not job_dir.is_dir():
        raise ValueError(f"Asset job does not exist: {job}")

    source_stage, source_root = _best_asset_source(job_dir)
    source_assets = _iter_pngs(source_root)
    if not source_assets:
        raise ValueError(f"Asset job has no PNG assets to approve: {job}")

    quality = score_assets(source_assets)
    approved_root = pipeline_root / "approved" / job_name
    if approved_root.exists():
        stamp = time.strftime("%Y%m%d-%H%M%S")
        approved_root = pipeline_root / "approved" / f"{job_name}__{stamp}"
    assets_root = approved_root / "assets"
    copied = _copy_tree_pngs(source_root, assets_root)

    library_root = None
    library_copied = []
    if family:
        library_root = pipeline_root / "library" / _safe_name(family) / _safe_name(label or job_name)
        library_copied = _copy_tree_pngs(source_root, library_root)

    manifest_sources = {
        "deconstruct": str(job_dir / "manifest.json") if (job_dir / "manifest.json").exists() else None,
        "repair": str(job_dir / "repair-manifest.json") if (job_dir / "repair-manifest.json").exists() else None,
        "precision": str(job_dir / "precision-manifest.json") if (job_dir / "precision-manifest.json").exists() else None,
        "master": str(job_dir / "master-manifest.json") if (job_dir / "master-manifest.json").exists() else None,
    }
    approval = {
        "job": job_name,
        "approved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source_stage": source_stage,
        "source_root": str(source_root),
        "approved_root": str(approved_root),
        "assets_root": str(assets_root),
        "library_root": str(library_root) if library_root else None,
        "asset_count": len(copied),
        "quality": quality,
        "source_manifests": manifest_sources,
        "assets": copied,
        "library_assets": library_copied,
    }
    approved_root.mkdir(parents=True, exist_ok=True)
    (approved_root / "approval-manifest.json").write_text(json.dumps(approval, indent=2), encoding="utf-8")
    return approval


def review_job(pipeline_root: Path, job: str) -> dict[str, Any]:
    job_name = _safe_name(job)
    job_dir = pipeline_root / "outbox" / job_name
    if not job_dir.exists() or not job_dir.is_dir():
        raise ValueError(f"Asset job does not exist: {job}")
    source_stage, source_root = _best_asset_source(job_dir)
    source_assets = _iter_pngs(source_root)
    quality = score_assets(source_assets)
    return {
        "job": job_name,
        "job_dir": str(job_dir),
        "source_stage": source_stage,
        "source_root": str(source_root),
        "asset_count": len(source_assets),
        "quality": quality,
        "manifests": {
            "deconstruct": _read_json(job_dir / "manifest.json"),
            "repair": _read_json(job_dir / "repair-manifest.json"),
            "precision": _read_json(job_dir / "precision-manifest.json"),
            "master": _read_json(job_dir / "master-manifest.json"),
        },
    }
