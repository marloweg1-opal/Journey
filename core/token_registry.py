"""Project-neutral identity and capability token registry for Journey."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


REGISTRY_RELATIVE_PATH = Path("config") / "project_tokens.json"

DEFAULT_REGISTRY: dict[str, Any] = {
    "schema_version": 1,
    "doctrine": {
        "summary": "Journey tokens describe identity, capability ownership, routing, safety and optional surface customization.",
        "canonical_system_token": "journey",
        "identity_resolution": {"mini_ark": "journey", "mini ark": "journey"},
        "identity_note": "Journey is the orchestration system. Domain profiles may rename or decorate capabilities without replacing Journey's identity.",
        "empty_folder_policy": "Never delete a folder solely because it is empty.",
        "routing_policy": "Files live in their natural canonical home first; specificity is added through representations such as shortcuts, manifests, tags and project views.",
        "token_reception_policy": "Every incoming item carries an existing token or receives a provisional token at reception. Routing follows verified identity evidence.",
        "ambient_congruence_policy": "Always observe within granted scope; auto-apply only safe, reversible, high-confidence and low-cost maintenance; ask for ambiguity, judgment, destructive action, unclear ownership or expensive work.",
        "resource_doctrine": "Foreground responsiveness wins; heavy compute makes stewardship throttle or pause; idle periods permit deeper maintenance.",
        "mutation_policy": "Detect and propose first; execute only through approved, reversible operations.",
        "prompt_policy": "Prompts are for real judgment, not routine housekeeping.",
        "auto_apply_policy": ["index and manifest updates", "verified routing with unambiguous destinations", "non-destructive organizational maintenance", "report generation", "safe metadata normalization"],
        "do_not_auto_apply_policy": ["deletion", "folder deletion", "ambiguous rename", "semantic merges", "system or app-managed path changes", "destructive dedupe", "changes with unclear ownership or destination"],
    },
    "visual_identity": {
        "selected_mini_ark_icon": "C:\\HEXSEED\\10_ASSETS\\HEXSEED_ICONS\\ICO\\mini_ark.ico",
        "future_journey_icon": "C:\\HEXSEED\\10_ASSETS\\HEXSEED_ICONS\\ICO\\journey.ico",
        "policy": "Expression profiles may provide presentation assets; those assets remain owned by their source projects.",
    },
    "tokens": {
        "journey": {
            "display_name": "Journey",
            "type": "configuration_engine",
            "aliases": ["mini_ark", "mini ark", "miniark", "adaptive local orchestration layer"],
            "owns": ["configuration_engine", "functional_kernel_translation", "navigator_surface", "continuity", "stewardship", "audit", "rollback"],
            "routes": {"home": "C:\\mini_ark", "docs": "C:\\mini_ark\\docs", "ledger": "C:\\mini_ark\\ark.sqlite"},
            "representations": {"implementation": "Mini ARK", "canonical_working_tree": "C:\\mini_ark", "role": "human_centered_local_orchestration"},
            "customization": {"surface_label": "Journey", "accent": "#7fd9d2"},
        },
        "asset_pipeline": {
            "display_name": "Asset Pipeline",
            "type": "capability",
            "aliases": ["asset intake", "asset routing"],
            "owns": ["asset_intake", "asset_routing", "provenance", "reviewable_exports"],
            "routes": {
                "inbox": "C:\\mini_ark\\asset_pipeline\\inbox",
                "outbox": "C:\\mini_ark\\asset_pipeline\\outbox",
                "approved": "C:\\mini_ark\\asset_pipeline\\approved",
                "library": "C:\\mini_ark\\asset_pipeline\\library",
            },
            "representations": {"canonical": "C:\\mini_ark\\asset_pipeline", "surface": "Tools > Asset Intake", "role": "asset_acquisition_and_routing"},
            "customization": {"surface_label": "Asset Intake", "accent": "#f4c95d"},
        },
        "project_profile": {
            "display_name": "Project Profile",
            "type": "extension_contract",
            "aliases": ["integration profile", "expression profile"],
            "owns": ["project_routes", "project_tokens", "presentation_translation"],
            "routes": {},
            "representations": {"role": "external_project_owned_extension", "boundary": "Project-specific doctrine and assets remain in the owning project."},
            "customization": {"surface_label": "Project Profile", "accent": "#9fc4ff"},
        },
    },
    "reserved_roots": [
        "C:\\mini_ark\\asset_pipeline\\inbox",
        "C:\\mini_ark\\asset_pipeline\\inbox\\archive",
        "C:\\mini_ark\\asset_pipeline\\outbox",
        "C:\\mini_ark\\asset_pipeline\\approved",
        "C:\\mini_ark\\asset_pipeline\\library",
        "C:\\mini_ark\\asset_pipeline\\recipes",
        "C:\\mini_ark\\asset_pipeline\\logs",
        "R:\\HEXSEED",
        "R:\\ark_quarantine",
        "R:\\.System_Records",
    ],
}


def registry_path(root: Path) -> Path:
    return root / REGISTRY_RELATIVE_PATH


def ensure_token_registry(root: Path) -> dict[str, Any]:
    path = registry_path(root)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        write_token_registry(root, DEFAULT_REGISTRY)
    registry = load_token_registry(root)
    validate_token_registry(registry)
    return registry


def load_token_registry(root: Path) -> dict[str, Any]:
    path = registry_path(root)
    with path.open("r", encoding="utf-8") as handle:
        registry = json.load(handle)
    validate_token_registry(registry)
    return registry


def write_token_registry(root: Path, registry: dict[str, Any]) -> None:
    validate_token_registry(registry)
    path = registry_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(registry, handle, indent=2)
        handle.write("\n")


def validate_token_registry(registry: dict[str, Any]) -> None:
    if not isinstance(registry, dict):
        raise ValueError("Token registry must be a JSON object.")
    if registry.get("schema_version") != 1:
        raise ValueError("Token registry schema_version must be 1.")
    tokens = registry.get("tokens")
    if not isinstance(tokens, dict) or not tokens:
        raise ValueError("Token registry must contain a non-empty tokens object.")
    for token_id, token in tokens.items():
        if not isinstance(token_id, str) or not token_id.strip():
            raise ValueError("Token ids must be non-empty strings.")
        if not isinstance(token, dict):
            raise ValueError(f"Token {token_id!r} must be an object.")
        for field in ("display_name", "type", "aliases", "owns", "routes", "customization"):
            if field not in token:
                raise ValueError(f"Token {token_id!r} is missing {field!r}.")
        if not isinstance(token["aliases"], list):
            raise ValueError(f"Token {token_id!r} aliases must be a list.")
        if not isinstance(token["owns"], list):
            raise ValueError(f"Token {token_id!r} owns must be a list.")


def resolve_token(registry: dict[str, Any], value: str) -> tuple[str, dict[str, Any]] | None:
    needle = value.strip().lower()
    if not needle:
        return None
    for token_id, token in registry["tokens"].items():
        candidates = [token_id, token["display_name"], *token.get("aliases", [])]
        if needle in {str(candidate).strip().lower() for candidate in candidates}:
            return token_id, deepcopy(token)
    return None


def token_summary(registry: dict[str, Any]) -> dict[str, Any]:
    validate_token_registry(registry)
    tokens = registry["tokens"]
    return {
        "schema_version": registry["schema_version"],
        "token_count": len(tokens),
        "tokens": [{
            "id": token_id,
            "display_name": token["display_name"],
            "type": token["type"],
            "aliases": token.get("aliases", []),
            "owns": token.get("owns", []),
            "routes": token.get("routes", {}),
            "representations": token.get("representations", {}),
            "customization": token.get("customization", {}),
        } for token_id, token in sorted(tokens.items())],
        "reserved_roots": registry.get("reserved_roots", []),
        "policies": registry.get("doctrine", {}),
    }


def route_summary(registry: dict[str, Any]) -> dict[str, Any]:
    validate_token_registry(registry)
    routed_tokens = []
    for token_id, token in sorted(registry["tokens"].items()):
        routes = token.get("routes", {})
        representations = token.get("representations", {})
        if routes or representations:
            routed_tokens.append({"id": token_id, "display_name": token["display_name"], "type": token["type"], "routes": routes, "representations": representations})
    return {
        "schema_version": registry["schema_version"],
        "routed_token_count": len(routed_tokens),
        "tokens": routed_tokens,
        "rule": "Canonical roots are the source of truth; representations are useful views, shortcuts, manifests or surfaces.",
        "routing_policy": registry.get("doctrine", {}).get("routing_policy", ""),
    }
