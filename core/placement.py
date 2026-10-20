"""Canonical placement doctrine and read-only placement evaluation."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path, PureWindowsPath
from typing import Any

from core.classify import classify_path
from core.action_evidence import assess_action
from core.token_registry import ensure_token_registry, resolve_token


DOCTRINE_RELATIVE_PATH = Path("config") / "canonical_placement.json"

CONGRUENT = "CONGRUENT"
LIKELY_CONGRUENT = "LIKELY_CONGRUENT"
MISPLACED_HIGH_CONFIDENCE = "MISPLACED_HIGH_CONFIDENCE"
MISPLACED_NEEDS_REVIEW = "MISPLACED_NEEDS_REVIEW"
TRANSIENT_ACCEPTABLE = "TRANSIENT_ACCEPTABLE"
LEGACY_PATH = "LEGACY_PATH"
PROTECTED_OPERATIONAL = "PROTECTED_OPERATIONAL"
UNKNOWN = "UNKNOWN"

LEAVE = "LEAVE"
REFERENCE = "REFERENCE"
MIGRATE = "MIGRATE"
CANONICALIZE = "CANONICALIZE"
DEPLOY = "DEPLOY"
QUARANTINE = "QUARANTINE"
REVIEW = "REVIEW"


def doctrine_path(root: Path) -> Path:
    return root / DOCTRINE_RELATIVE_PATH


def load_placement_doctrine(root: Path) -> dict[str, Any]:
    path = doctrine_path(root)
    with path.open("r", encoding="utf-8") as handle:
        doctrine = json.load(handle)
    validate_placement_doctrine(doctrine)
    return doctrine


def validate_placement_doctrine(doctrine: dict[str, Any]) -> None:
    if not isinstance(doctrine, dict):
        raise ValueError("Placement doctrine must be a JSON object.")
    if doctrine.get("schema_version") != 1:
        raise ValueError("Placement doctrine schema_version must be 1.")
    locations = doctrine.get("locations")
    if not isinstance(locations, list) or not locations:
        raise ValueError("Placement doctrine must contain locations.")
    required = {
        "id",
        "canonical_name",
        "path",
        "domain",
        "owner",
        "purpose",
        "allowed_content",
        "disallowed_content",
        "lifecycle",
        "canonicality",
        "protection_level",
        "routing_hints",
        "aliases",
        "legacy_aliases",
        "related_destinations",
        "related_locations",
        "reasoning_notes",
    }
    for location in locations:
        if not isinstance(location, dict):
            raise ValueError("Each placement location must be an object.")
        missing = required - set(location)
        if missing:
            raise ValueError(f"Placement location {location.get('id', '(unknown)')!r} is missing {sorted(missing)}.")


def _norm(path: str) -> str:
    value = str(PureWindowsPath(path)).rstrip("\\/")
    return value.lower()


def _is_under(path: str, root: str) -> bool:
    norm_path = _norm(path)
    norm_root = _norm(root)
    return norm_path == norm_root or norm_path.startswith(norm_root + "\\")


def _location_paths(location: dict[str, Any]) -> list[str]:
    return [location["path"], *location.get("aliases", []), *location.get("legacy_aliases", [])]


def _matching_location(doctrine: dict[str, Any], path: str) -> dict[str, Any] | None:
    matches = []
    for location in doctrine["locations"]:
        for candidate in _location_paths(location):
            if _is_under(path, candidate):
                matches.append((len(_norm(candidate)), location, candidate))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0], reverse=True)
    location = deepcopy(matches[0][1])
    location["matched_path"] = matches[0][2]
    return location


def _location_by_id(doctrine: dict[str, Any], location_id: str) -> dict[str, Any]:
    for location in doctrine["locations"]:
        if location["id"] == location_id:
            return deepcopy(location)
    raise KeyError(location_id)


def _path_tokens(path: str) -> set[str]:
    normalized = _norm(path).replace("/", "\\")
    pieces = []
    for part in normalized.split("\\"):
        pieces.extend(piece for piece in part.replace("-", "_").split("_") if piece)
    return set(pieces)


def _target_for_classification(root: Path, doctrine: dict[str, Any], path: str, classification: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    if classification.get("placement") in {"live_rainmeter", "wallpaper_engine", "application_library", "operational_context"}:
        return None, "operational context requires dependency and deployment review before a target is inferred"
    token_registry = ensure_token_registry(root)
    owner = classification.get("owner", "")
    resolved = resolve_token(token_registry, owner)
    if resolved:
        token_id, token = resolved
        if token_id == "carebloomos":
            return _location_by_id(doctrine, "carebloomos_durable_project"), "known project owner routes to durable project source"

    bucket = classification.get("bucket", "")
    lifecycle = classification.get("lifecycle_class", "")
    placement = classification.get("placement", "")
    lowered_path = _norm(path)
    tokens = _path_tokens(path)

    if placement in {"live_rainmeter", "wallpaper_engine", "application_library"}:
        return None, "application-owned placement is protected"
    if "downloads2" in tokens or lowered_path.endswith("\\downloads") or "\\downloads\\" in lowered_path:
        location = _location_by_id(doctrine, "r_en_route")
        return location, "downloads-style intake belongs in En_Route until classified"
    if lifecycle == "transient_residue":
        location = _location_by_id(doctrine, "r_en_route")
        return location, "transient material belongs in En_Route while awaiting routing"
    if bucket.startswith("RuneScript/Projects/CareBloomOS"):
        return _location_by_id(doctrine, "carebloomos_durable_project"), "CareBloomOS project signal routes to durable CareBloomOS source"
    if bucket.startswith("RuneScript/Projects/"):
        return _location_by_id(doctrine, "r_projects"), "known project material routes to canonical project source"
    if bucket.startswith("Media/"):
        media_type = bucket.split("/", 1)[1]
        location = _location_by_id(doctrine, "r_media")
        location["path"] = str(PureWindowsPath(location["path"]) / media_type)
        return location, "unowned media routes to durable media by physical type"
    if bucket.startswith("Library/"):
        library_type = bucket.split("/", 1)[1]
        location = _location_by_id(doctrine, "r_library")
        location["path"] = str(PureWindowsPath(location["path"]) / library_type)
        return location, "reference material routes to Library by physical type"
    if bucket.startswith("System_Records/"):
        return _location_by_id(doctrine, "r_system_records"), "system records and operational manifests route to durable records"
    if bucket.startswith("Intake/"):
        return _location_by_id(doctrine, "r_en_route"), "unknown or source-context-only material belongs in En_Route first"
    return None, "no canonical target could be inferred"


def _recommended_action(state: str) -> str:
    return {
        CONGRUENT: "leave",
        LIKELY_CONGRUENT: "leave_or_review",
        MISPLACED_HIGH_CONFIDENCE: "propose_route",
        MISPLACED_NEEDS_REVIEW: "review_before_route",
        TRANSIENT_ACCEPTABLE: "observe_then_route",
        LEGACY_PATH: "review_legacy_mapping",
        PROTECTED_OPERATIONAL: "leave_protected",
        UNKNOWN: "classify_or_ask",
    }[state]


def _resolution_strategy(state: str, current: dict[str, Any] | None, target: dict[str, Any] | None) -> str:
    """Pick the placement resolution family without mutating the filesystem.

    References are intentionally not the default. They are for operational,
    compatibility, or presentation cases where the object should stay put.
    """
    if state in {CONGRUENT, LIKELY_CONGRUENT, TRANSIENT_ACCEPTABLE}:
        return LEAVE
    if state == PROTECTED_OPERATIONAL:
        return DEPLOY
    if state == UNKNOWN:
        return REVIEW
    if state == LEGACY_PATH:
        if current and target and current.get("id") == target.get("id"):
            return MIGRATE
        return REVIEW
    if state == MISPLACED_HIGH_CONFIDENCE:
        return MIGRATE
    if state == MISPLACED_NEEDS_REVIEW:
        return REVIEW
    return REVIEW


def _resolution_reason(strategy: str, state: str) -> str:
    return {
        LEAVE: "Current placement is already congruent or acceptable; no filesystem convergence is proposed.",
        REFERENCE: "Use only when the object must remain physically in place but needs discovery, compatibility, or portal exposure.",
        MIGRATE: "Current placement appears noncanonical and a likely canonical home exists; migration should be approval-gated, reversible, and verified.",
        CANONICALIZE: "Multiple copies or versions need an authority decision before one becomes the canonical source.",
        DEPLOY: "The object is in an operational/application-owned location; treat it as a deployed instance linked to a canonical source when one exists.",
        QUARANTINE: "The object appears redundant or retired; reversible quarantine is the safe retirement path.",
        REVIEW: "Evidence is insufficient or conflicting; review the family before choosing migration, reference, deploy, or quarantine.",
    }.get(strategy, f"Review required for placement state {state}.")


def evaluate_placement(path: str, root: Path | None = None) -> dict[str, Any]:
    root = root or Path(__file__).resolve().parents[1]
    doctrine = load_placement_doctrine(root)
    classification = classify_path(path)
    current = _matching_location(doctrine, path)

    if current and current.get("protection_level") == "protected_operational":
        state = PROTECTED_OPERATIONAL
        target = {
            "id": current["id"],
            "path": current["path"],
            "owner": current["owner"],
            "domain": current["domain"],
        }
        reason = f"{current['purpose']} This location is protected operational state."
        confidence = "Confirmed"
    else:
        target, target_reason = _target_for_classification(root, doctrine, path, classification)
        if target is None:
            state = UNKNOWN
            reason = target_reason
            confidence = "Unknown"
        elif current and current.get("matched_path") != current.get("path") and target and target.get("id") == current.get("id"):
            state = LEGACY_PATH
            reason = f"Current path matches a known alias or legacy path. {target_reason}."
            confidence = "Strongly_inferred"
        elif current and _is_under(path, target["path"]):
            state = CONGRUENT
            reason = f"Current path is already under likely canonical placement. {target_reason}."
            confidence = "Confirmed"
        elif current and current.get("canonicality") == "working_canonical" and target.get("id") == "carebloomos_durable_project":
            state = LIKELY_CONGRUENT
            reason = "Active CareBloomOS source can be correct; durable reusable material should be mirrored/routed after review."
            confidence = "Strongly_inferred"
        elif target.get("id") == "r_en_route" and current and current.get("id") in {"r_in_transit", "r_en_route"}:
            state = TRANSIENT_ACCEPTABLE
            reason = f"Current transient/intake placement is acceptable. {target_reason}."
            confidence = "Strongly_inferred"
        elif any(_is_under(path, alias) for location in doctrine["locations"] for alias in location.get("aliases", [])):
            state = LEGACY_PATH
            reason = f"Current path matches a known alias or legacy path. {target_reason}."
            confidence = "Strongly_inferred"
        elif classification["confidence"] in {"Confirmed", "Strongly_inferred"}:
            state = MISPLACED_NEEDS_REVIEW
            reason = target_reason + "; project/type confidence does not establish placement or dependency safety"
            confidence = "Tentative"
        else:
            state = MISPLACED_NEEDS_REVIEW
            reason = target_reason
            confidence = classification["confidence"]

    resolution_strategy = _resolution_strategy(state, current, target)
    operational = current if state == PROTECTED_OPERATIONAL else None
    return {
        "path": path,
        "state": state,
        "placement_congruence": state,
        "resolution_strategy": resolution_strategy,
        "action_assessment": assess_action(resolution_strategy),
        "resolution_reason": _resolution_reason(resolution_strategy, state),
        "confidence": confidence,
        "confidence_scope": "placement_description_only; see action_assessment for action confidence",
        "current_placement": current,
        "canonical_location": None if operational else target,
        "operational_location": operational,
        "presentation_location": None,
        "confidence_dimensions": {
            "project": {"value": classification.get("owner"), "confidence": classification.get("confidence"), "basis": "path_heuristic"},
            "affinity": {"value": None, "confidence": None, "basis": "not_inspected"},
            "role": {"value": classification.get("subject_type"), "confidence": None, "basis": "path_heuristic"},
            "lifecycle": {"value": classification.get("lifecycle_class"), "confidence": None, "basis": "path_heuristic"},
            "placement": {"value": state, "confidence": confidence, "basis": "placement_policy"},
        },
        "likely_canonical_placement": target,
        "classification": classification,
        "reason": reason,
        "dependencies_references": "not_checked",
        "recommended_action": _recommended_action(state),
        "approval_required_for_changes": True,
        "read_only": True,
    }


def doctrine_summary(root: Path | None = None) -> dict[str, Any]:
    root = root or Path(__file__).resolve().parents[1]
    doctrine = load_placement_doctrine(root)
    return {
        "schema_version": doctrine["schema_version"],
        "architecture_schema": doctrine.get("architecture_schema"),
        "placement_policy": doctrine.get("placement_policy"),
        "classification_schema": doctrine.get("classification_schema"),
        "capability_registry": doctrine.get("capability_registry"),
        "doctrine": doctrine.get("doctrine", {}),
        "location_count": len(doctrine["locations"]),
        "locations": doctrine["locations"],
    }
