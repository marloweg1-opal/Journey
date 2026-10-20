from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

try:
    from .asset_approver import approve_job, review_job
    from .asset_autodetect import auto_deconstruct_assets
    from .asset_composer import compose_master_sheet
    from .asset_deconstructor import sha256_file
    from .asset_precision import precision_icons
    from .asset_repair import repair_icons
    from .asset_registry import existing_entry, fingerprint, record_entry
except ImportError:
    from asset_approver import approve_job, review_job
    from asset_autodetect import auto_deconstruct_assets
    from asset_composer import compose_master_sheet
    from asset_deconstructor import sha256_file
    from asset_precision import precision_icons
    from asset_repair import repair_icons
    from asset_registry import existing_entry, fingerprint, record_entry


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-").lower()
    return cleaned or "asset_autopilot"


def _approve_allowed(review: dict[str, Any], *, require_no_duplicates: bool) -> tuple[bool, list[str]]:
    quality = review.get("quality", {})
    reasons = []
    if int(quality.get("reject_count") or 0):
        reasons.append("one_or_more_assets_rejected")
    if int(quality.get("review_count") or 0):
        reasons.append("one_or_more_assets_need_review")
    if require_no_duplicates and int(quality.get("duplicate_group_count") or 0):
        reasons.append("likely_visual_duplicates")
    return not reasons, reasons


def _archive_inbox_inputs(source_paths: list[Path], pipeline_root: Path) -> list[str]:
    inbox = (pipeline_root / "inbox").resolve()
    archive = pipeline_root / "inbox" / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    archived = []
    for path in source_paths:
        try:
            if path.resolve().parent != inbox or not path.exists():
                continue
        except OSError:
            continue
        destination = archive / path.name
        if destination.exists():
            stamp = time.strftime("%Y%m%d-%H%M%S")
            destination = archive / f"{path.stem}__{stamp}{path.suffix}"
        shutil.move(str(path), str(destination))
        archived.append(str(destination))
    return archived


def run_asset_intake(
    source_paths: list[Path],
    pipeline_root: Path,
    *,
    job_name: str | None = None,
    family: str | None = None,
    label: str | None = None,
    approve_perfect: bool = True,
    require_no_duplicates: bool = True,
    alpha_threshold: int = 8,
    min_area: int = 5000,
    complete_min_area: int = 300,
    split_alpha_threshold: int = 32,
    precision_padding: int = 8,
    repair_min_component_area: int = 24,
    max_fill_ratio: float = 0.08,
    group_mode: str = "keep_separate",
    archive_inputs: bool = False,
) -> dict[str, Any]:
    sources = [Path(path) for path in source_paths if Path(path).suffix.lower() in IMAGE_SUFFIXES]
    if not sources:
        raise ValueError("At least one image asset sheet is required.")

    source_hashes = [sha256_file(path) for path in sources]
    options = {
        "source_count": len(sources),
        "family": family,
        "label": label,
        "approve_perfect": approve_perfect,
        "require_no_duplicates": require_no_duplicates,
        "alpha_threshold": alpha_threshold,
        "min_area": min_area,
        "complete_min_area": complete_min_area,
        "split_alpha_threshold": split_alpha_threshold,
        "precision_padding": precision_padding,
        "repair_min_component_area": repair_min_component_area,
        "max_fill_ratio": max_fill_ratio,
        "group_mode": group_mode,
    }
    cache_key = fingerprint("asset_intake", sorted(source_hashes), options)
    cached = existing_entry(pipeline_root, cache_key)
    if cached:
        outputs = cached.get("outputs", {})
        return {
            "ok": True,
            "reused": True,
            "fingerprint": cache_key,
            **outputs,
        }

    base_job = _safe_name(job_name or label or Path(sources[0]).stem)
    if len(sources) == 1:
        intake = auto_deconstruct_assets(
            sources[0],
            pipeline_root,
            job_name=f"{base_job}_asset_intake",
            alpha_threshold=alpha_threshold,
            min_area=min_area,
            padding=0,
            group="autopilot_assets",
            name_prefix="asset",
            complete=True,
            complete_min_area=complete_min_area,
            split_alpha_threshold=split_alpha_threshold,
        )
        job = intake["job"]
        job_dir = Path(intake["job_dir"])
        intake_result = intake
    else:
        intake_result = compose_master_sheet(
            sources,
            pipeline_root,
            job_name=f"{base_job}_asset_intake_master",
            alpha_threshold=alpha_threshold,
            min_area=min_area,
            complete=True,
            complete_min_area=complete_min_area,
            split_alpha_threshold=split_alpha_threshold,
            input_padding=0,
            group="autopilot_assets",
            group_mode=group_mode,
            name_prefix="asset",
        )
        job = intake_result["job"]
        job_dir = Path(intake_result["job_dir"])

    repair = repair_icons(
        job_dir,
        alpha_threshold=1,
        min_component_area=repair_min_component_area,
        smooth_alpha=True,
        reshape_candidate=True,
        max_fill_ratio=max_fill_ratio,
    )
    precision = precision_icons(job_dir, padding=precision_padding, alpha_threshold=1)
    review = review_job(pipeline_root, job)
    may_approve, blocked_reasons = _approve_allowed(review, require_no_duplicates=require_no_duplicates)
    approval = None
    if approve_perfect and may_approve:
        approval = approve_job(pipeline_root, job, family=family, label=label or job)

    status = "approved" if approval else "needs_review"
    if not may_approve:
        status = "blocked_from_approval"
    outputs = {
        "status": status,
        "job": job,
        "job_dir": str(job_dir),
        "source_count": len(sources),
        "source_sha256": source_hashes,
        "group_mode": group_mode,
        "intake": intake_result,
        "repair": {
            "asset_count": repair.get("asset_count"),
            "removed_components": repair.get("removed_components"),
            "removed_pixels": repair.get("removed_pixels"),
            "reshape_accepted": repair.get("reshape_accepted"),
            "reshape_rejected": repair.get("reshape_rejected"),
            "contact_sheet": repair.get("contact_sheet"),
        },
        "precision": {
            "asset_count": precision.get("asset_count"),
            "canvas_size": precision.get("canvas_size"),
            "contact_sheet": precision.get("contact_sheet"),
        },
        "review": {
            "asset_count": review.get("asset_count"),
            "source_stage": review.get("source_stage"),
            "quality": review.get("quality"),
        },
        "approval": approval,
        "approval_blocked_reasons": blocked_reasons,
    }
    if archive_inputs:
        outputs["archived_to"] = _archive_inbox_inputs(sources, pipeline_root)
    record_entry(
        pipeline_root,
        cache_key,
        operation="asset_intake",
        source_sha256=sorted(source_hashes),
        options=options,
        job=job,
        job_dir=job_dir,
        outputs=outputs,
    )
    summary_path = job_dir / "asset-intake-summary.json"
    summary_path.write_text(json.dumps({"fingerprint": cache_key, **outputs}, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "reused": False,
        "fingerprint": cache_key,
        "summary_path": str(summary_path),
        **outputs,
    }
