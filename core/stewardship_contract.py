"""Mini ARK stewardship reliability contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CONTRACT_RELATIVE_PATH = Path("config") / "stewardship_contract.json"

REQUIRED_OPERATION_STATES = {
    "PROPOSED",
    "REVIEWED",
    "APPROVED",
    "PREVIEWED",
    "QUEUED",
    "RUNNING",
    "VERIFYING",
    "COMPLETED",
    "FAILED",
    "PARTIALLY_COMPLETED",
    "ROLLING_BACK",
    "ROLLED_BACK",
    "MANUAL_RECOVERY_REQUIRED",
}

REQUIRED_RECORD_KINDS = {"finding", "proposal", "operation", "event"}


def contract_path(root: Path) -> Path:
    return root / CONTRACT_RELATIVE_PATH


def load_contract(root: Path) -> dict[str, Any]:
    path = contract_path(root)
    with path.open("r", encoding="utf-8") as handle:
        contract = json.load(handle)
    validate_contract(contract)
    return contract


def validate_contract(contract: dict[str, Any]) -> None:
    if not isinstance(contract, dict):
        raise ValueError("Stewardship contract must be a JSON object.")
    if contract.get("schema_version") != 1:
        raise ValueError("Stewardship contract schema_version must be 1.")
    layers = contract.get("identity_model", {}).get("layers", [])
    if "current_path" not in layers or "logical_asset_id" not in layers:
        raise ValueError("Identity model must distinguish path from logical asset identity.")
    operation_states = set(contract.get("operation_states", []))
    missing_states = REQUIRED_OPERATION_STATES - operation_states
    if missing_states:
        raise ValueError(f"Stewardship contract missing operation states: {sorted(missing_states)}")
    record_kinds = set(contract.get("record_kinds", {}))
    missing_records = REQUIRED_RECORD_KINDS - record_kinds
    if missing_records:
        raise ValueError(f"Stewardship contract missing record kinds: {sorted(missing_records)}")
    if contract.get("scanner_rules", {}).get("follow_reparse_points_by_default") is not False:
        raise ValueError("Scanner contract must default to not following reparse points.")
    if not contract.get("shadow_mode", {}).get("required"):
        raise ValueError("Shadow Mode must be required before broad stewardship.")


def contract_summary(root: Path) -> dict[str, Any]:
    contract = load_contract(root)
    return {
        "schema_version": contract["schema_version"],
        "identity_layers": contract["identity_model"]["layers"],
        "record_kinds": contract["record_kinds"],
        "operation_states": contract["operation_states"],
        "commit_phases": contract["commit_phases"],
        "canonicalization_relationships": contract["canonicalization_relationships"],
        "policy_precedence": contract["policy_precedence"],
        "protected_default": contract["protected_territory"]["default_posture"],
        "graduation_gates": contract["graduation_gates"],
        "shadow_mode": contract["shadow_mode"],
        "resource_feasibility": contract.get("resource_feasibility", {}),
    }


def assess_resource_feasibility(requirements: dict[str, int],
                                available: dict[str, int | None]) -> dict[str, Any]:
    """Compare same-unit resource quantities; feasibility never grants execution authority."""
    blocked, unknown = [], []
    for resource, required in requirements.items():
        actual = available.get(resource)
        if type(required) is not int or required < 0:
            raise ValueError("Required resources must be nonnegative integer quantities.")
        if actual is not None and (type(actual) is not int or actual < 0):
            raise ValueError("Available resources must be nonnegative integers or unknown.")
        if required == 0:
            continue
        if actual is None:
            unknown.append(resource)
        elif actual < required:
            blocked.append({"resource": resource, "required": required,
                            "available": actual, "shortfall": required - actual})
    return {
        "state": "RESOURCE_BLOCKED" if blocked else (
            "RESOURCE_UNKNOWN" if unknown else "RESOURCE_FEASIBLE"),
        "blocked": blocked, "unknown": unknown,
        "execution_authorized": False,
        "safety_assessed": False,
    }
