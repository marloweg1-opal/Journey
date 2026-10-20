"""Project-neutral naming engine seam.

This module previews canonical names. It does not rename files; rename
execution still belongs to proposal -> approval -> apply -> undo.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from core.token_registry import resolve_token


STOP_WORDS = {"a", "an", "and", "for", "of", "the", "to", "with"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
LOSSLESS_UI_ROLES = {"asset", "badge", "button", "care_rail", "icon", "panel", "rail", "sprite", "ui", "widget"}
PHOTO_ROLES = {"background", "reference", "wallpaper"}
SCRIPT_SUFFIXES = {".ps1", ".py", ".js", ".ts", ".bat", ".cmd", ".sh", ".lua"}
DOC_SUFFIXES = {".md", ".txt", ".docx", ".pdf"}
DATA_SUFFIXES = {".json", ".csv", ".tsv", ".xlsx", ".sqlite", ".db"}
MEDIA_SUFFIXES = {".mp3", ".wav", ".flac", ".mp4", ".mov", ".mkv", ".webm"}
TEMP_SUFFIXES = {".tmp", ".temp", ".part", ".crdownload", ".download"}
RESERVED_WINDOWS_NAMES = {
    "con", "prn", "aux", "nul",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
}
MAX_RECOMMENDED_PATH_LENGTH = 220


def date_token(year: str, month: str, day: str) -> str:
    return f"{year}-{month}-{day}"


def slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    parts = [part for part in cleaned.split("_") if part and part not in STOP_WORDS]
    return "_".join(parts)


def detected_token_ids(registry: dict[str, Any], text: str) -> list[str]:
    lowered = text.lower()
    found = []
    for token_id, token in registry.get("tokens", {}).items():
        candidates = [token_id, token.get("display_name", ""), *token.get("aliases", [])]
        if any(str(candidate).lower() in lowered for candidate in candidates if candidate):
            resolved = resolve_token(registry, token_id)
            canonical_id = resolved[0] if resolved else token_id
            if canonical_id not in found:
                found.append(canonical_id)
    return found


def _valid_month(value: int) -> bool:
    return 1 <= value <= 12


def _valid_day(value: int) -> bool:
    return 1 <= value <= 31


def extract_date_info(value: str) -> tuple[str, dict[str, Any]]:
    ymd = re.search(r"(?<!\d)(20\d{2})[-_\. ]?([01]\d)[-_\. ]?([0-3]\d)(?!\d)", value)
    if ymd:
        year, month, day = ymd.groups()
        without = (value[: ymd.start()] + " " + value[ymd.end() :]).strip(" _-.")
        return without, {
            "token": date_token(year, month, day),
            "status": "accepted",
            "source": "filename",
            "format": "YYYY-MM-DD",
            "confidence": "high",
            "note": "Year-first dates are canonical-safe and belong at the end of the name when semantically relevant.",
        }

    delimited = re.search(r"(?<!\d)(\d{1,2})[-_\.\/ ](\d{1,2})[-_\.\/ ](20\d{2})(?!\d)", value)
    if delimited:
        first_raw, second_raw, year = delimited.groups()
        first = int(first_raw)
        second = int(second_raw)
        without = (value[: delimited.start()] + " " + value[delimited.end() :]).strip(" _-.")
        first_s = str(first).zfill(2)
        second_s = str(second).zfill(2)
        if _valid_month(first) and _valid_day(second) and not _valid_month(second):
            return without, {
                "token": date_token(year, first_s, second_s),
                "status": "accepted",
                "source": "filename",
                "format": "MM-DD-YYYY",
                "confidence": "medium",
                "note": "Month/day date is unambiguous because the second number cannot be a month.",
            }
        if _valid_day(first) and _valid_month(second) and not _valid_month(first):
            return without, {
                "token": date_token(year, second_s, first_s),
                "status": "accepted",
                "source": "filename",
                "format": "DD-MM-YYYY",
                "confidence": "medium",
                "note": "Day/month date is unambiguous because the first number cannot be a month.",
            }
        if first == second and _valid_month(first) and _valid_day(second):
            return without, {
                "token": date_token(year, first_s, second_s),
                "status": "accepted",
                "source": "filename",
                "format": "MM-DD-YYYY/DD-MM-YYYY",
                "confidence": "medium",
                "note": "Day and month are identical, so locale ordering does not change the date.",
            }
        return without, {
            "token": None,
            "status": "ambiguous",
            "source": "filename",
            "format": "MM-DD-YYYY/DD-MM-YYYY",
            "confidence": "low",
            "note": "Ambiguous date evidence is recorded but not added to the canonical filename.",
        }
    return value, {
        "token": None,
        "status": "missing",
        "source": None,
        "format": None,
        "confidence": "none",
        "note": "No semantic filename date found; download/import/modified dates belong in provenance metadata.",
    }


def extract_date_token(value: str) -> tuple[str, str | None]:
    without, info = extract_date_info(value)
    return without, info["token"]


def format_recommendation(source_suffix: str, role_slug: str, source_stem: str) -> dict[str, Any] | None:
    role_text = f"{role_slug} {slug(source_stem)}"
    role_parts = set(role_text.split("_"))
    if source_suffix in IMAGE_SUFFIXES and role_parts & LOSSLESS_UI_ROLES:
        preferred = ".png"
        reason = "UI/assets with transparency or crisp edges should stay lossless and alpha-safe."
    elif source_suffix in IMAGE_SUFFIXES and role_parts & PHOTO_ROLES:
        preferred = ".webp" if source_suffix == ".webp" else source_suffix
        reason = "Wallpaper/reference imagery can keep its current efficient display format unless alpha is needed."
    elif source_suffix in IMAGE_SUFFIXES:
        preferred = ".png" if source_suffix in {".bmp", ".tif", ".tiff"} else source_suffix
        reason = "No stronger role signal; preserve format unless it is awkward for normal UI use."
    elif source_suffix in SCRIPT_SUFFIXES:
        preferred = source_suffix
        reason = "Script/programmatic files keep their executable language extension; naming should clarify owner and role."
    elif source_suffix in DOC_SUFFIXES:
        preferred = source_suffix
        reason = "Document files keep their authored format; naming should clarify topic, project, and date."
    elif source_suffix in DATA_SUFFIXES:
        preferred = source_suffix
        reason = "Structured data keeps its machine-readable format; naming should clarify schema/purpose and date."
    elif source_suffix in MEDIA_SUFFIXES:
        preferred = source_suffix
        reason = "Media files keep their production/export format unless a separate transcode is requested."
    else:
        preferred = source_suffix
        reason = "Unknown file type; preserve extension and improve name only."
    return {
        "current": source_suffix,
        "preferred": preferred,
        "needs_resave": source_suffix != preferred,
        "reason": reason,
    }


def protect_reserved_stem(stem: str) -> tuple[str, list[str]]:
    warnings = []
    if stem.lower() in RESERVED_WINDOWS_NAMES:
        warnings.append(f"Reserved Windows filename stem '{stem}' disambiguated.")
        return f"{stem}_file", warnings
    return stem, warnings


def metadata_advice(date_info: dict[str, Any], tokens: list[str], role_slug: str, source_slug: str) -> list[str]:
    advice = []
    if date_info["status"] == "ambiguous":
        advice.append("Ambiguous filename date kept as provenance evidence, not canonical filename text.")
    if "download" in source_slug or "downloaded" in source_slug:
        advice.append("Download/acquisition dates belong in provenance unless they identify the artifact.")
    if len(tokens) > 2:
        advice.append("Extra project/stone associations should become representations or metadata, not filename sprawl.")
    if not role_slug:
        advice.append("No explicit role supplied; available filename/token evidence was used.")
    return advice


def path_warnings(path: Path, suggested_name: str, stem_warnings: list[str], status: str) -> list[str]:
    warnings = list(stem_warnings)
    if path.suffix.lower() in TEMP_SUFFIXES:
        warnings.append("Temporary or partial-download file; defer ordinary naming until the file is complete.")
    projected = str(path.with_name(suggested_name))
    if len(projected) > MAX_RECOMMENDED_PATH_LENGTH:
        warnings.append(f"Projected path length is {len(projected)} characters; consider a shorter name or shallower folder.")
    if status == "defer":
        warnings.append("Preview is informational only; do not propose rename while status is defer.")
    return warnings


def preview_name(path_value: str, registry: dict[str, Any], role: str | None = None, project: str | None = None) -> dict[str, Any]:
    path = Path(path_value)
    source_stem, date_info = extract_date_info(path.stem)
    date_token = date_info["token"]
    source_suffix = path.suffix.lower()
    text = " ".join(part for part in [path_value, role or "", project or ""] if part)
    tokens = detected_token_ids(registry, text)
    if project:
        resolved_project = resolve_token(registry, project)
        if resolved_project:
            project_id = resolved_project[0]
            tokens = [token for token in tokens if token != project_id]
            tokens.insert(0, project_id)

    role_slug = slug(role or "")
    source_slug = slug(source_stem)
    stem_parts = []
    if role_slug:
        stem_parts.append(role_slug)
    if tokens:
        stem_parts.extend(tokens[:2])
    stem_parts.append(source_slug)
    if date_token:
        stem_parts.append(date_token)
    stem = "_".join(part for part in stem_parts if part)
    stem = re.sub(r"_+", "_", stem).strip("_")
    if not stem:
        stem = "unnamed_asset"
    stem, stem_warnings = protect_reserved_stem(stem)
    format_advice = format_recommendation(source_suffix, role_slug, source_stem)
    suggested_suffix = format_advice["preferred"] if format_advice else source_suffix
    suggested_name = f"{stem}{suggested_suffix}"
    status = "defer" if source_suffix in TEMP_SUFFIXES else "preview_only"

    return {
        "source_path": path_value,
        "suggested_name": suggested_name,
        "suggested_stem": stem,
        "extension": source_suffix,
        "date_token": date_token,
        "date": date_info,
        "tokens": tokens,
        "role": role,
        "project": project,
        "format_recommendation": format_advice,
        "metadata_advice": metadata_advice(date_info, tokens, role_slug, source_slug),
        "warnings": path_warnings(path, suggested_name, stem_warnings, status),
        "status": status,
        "mutation": "none",
        "next_step": "Use propose-rename when this naming pattern is approved.",
    }
