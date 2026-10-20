"""Expression slot registry for manifestation-safe UI theming."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REGISTRY_RELATIVE_PATH = Path("config") / "expression_slot_registry.json"
REQUIRED_TOP_LEVEL = {"shell", "system_states", "review", "architecture", "operations", "personas"}
REQUIRED_STABLE_STATES = {
    "ready",
    "needs_review",
    "safe_care_available",
    "waiting_approval",
    "work_in_progress",
    "completed",
    "failed",
    "recovery_required",
}


def registry_path(root: Path) -> Path:
    return root / REGISTRY_RELATIVE_PATH


def load_expression_slots(root: Path) -> dict[str, Any]:
    path = registry_path(root)
    with path.open("r", encoding="utf-8") as handle:
        registry = json.load(handle)
    validate_expression_slots(registry)
    return registry


def validate_expression_slots(registry: dict[str, Any]) -> None:
    if not isinstance(registry, dict):
        raise ValueError("Expression slot registry must be a JSON object.")
    if registry.get("schema_version") != 1:
        raise ValueError("Expression slot registry schema_version must be 1.")
    missing = REQUIRED_TOP_LEVEL - set(registry)
    if missing:
        raise ValueError(f"Expression slot registry missing sections: {sorted(missing)}")
    missing_states = REQUIRED_STABLE_STATES - set(registry.get("system_states", {}))
    if missing_states:
        raise ValueError(f"Expression slot registry missing system states: {sorted(missing_states)}")
    law = registry.get("doctrine", {}).get("law", "")
    if "Semantic stability" not in law:
        raise ValueError("Expression slot registry must preserve semantic stability.")


def slot_summary(root: Path) -> dict[str, Any]:
    registry = load_expression_slots(root)
    return {
        "schema_version": registry["schema_version"],
        "profile_id": registry["profile_id"],
        "profile_version": registry["profile_version"],
        "law": registry["doctrine"]["law"],
        "sections": {
            section: sorted(registry[section].keys())
            for section in sorted(REQUIRED_TOP_LEVEL)
        },
    }
