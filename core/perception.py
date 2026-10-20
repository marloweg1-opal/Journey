"""Provider-neutral evidence contract. Providers receive no action authority."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class InspectionBudget:
    max_bytes: int = 8_000_000
    max_seconds: float = 5


@dataclass(frozen=True)
class PerceptualEvidence:
    provider: str
    provider_version: str
    source_fingerprint: str
    dimension: str
    value: str
    confidence: float
    explanation: str

    def __post_init__(self):
        if self.dimension not in {"project", "affinity", "role", "lifecycle", "placement"}:
            raise ValueError("Unknown evidence dimension")
        if not 0 <= self.confidence <= 1:
            raise ValueError("Confidence must be between zero and one")


class PerceptionProvider(Protocol):
    media_types: frozenset[str]

    def inspect(self, content: bytes, media_type: str, budget: InspectionBudget) -> tuple[PerceptualEvidence, ...]:
        """Return evidence only. Caller controls reading, timeouts and policy."""
        ...


EVIDENCE_PRECEDENCE = ("explicit_canon", "registered_identity", "provenance", "known_example",
                       "similarity", "perception", "generic_heuristic")


def resolve_dimensions(evidence):
    """Preserve unresolved dimensions; learned confidence cannot overrule canon."""
    result = {}
    for dimension in ("project", "affinity", "role", "lifecycle", "placement"):
        candidates = [e for e in evidence if e["dimension"] == dimension]
        if not candidates:
            result[dimension] = {"status": "unresolved", "candidates": []}
            continue
        priority = min(EVIDENCE_PRECEDENCE.index(e["kind"]) for e in candidates)
        strongest = [e for e in candidates if EVIDENCE_PRECEDENCE.index(e["kind"]) == priority]
        conflict = len({e["value"] for e in strongest}) > 1
        result[dimension] = {"status": "unresolved" if conflict else "candidate", "candidates": strongest}
    return result
