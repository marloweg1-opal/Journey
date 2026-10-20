"""Action confidence is separate from identity and from operator approval."""
from core.retirement_evidence import evaluate_retirement

REQUIREMENTS = {
    "MIGRATE": {"destination_authority", "source_role", "dependency_clearance", "destination_compatibility"},
    "CANONICALIZE": {"version_relationship", "canonical_authority", "dependency_clearance", "retirement_condition"},
    "QUARANTINE": {"retirement_condition", "dependency_clearance", "recovery_plan"},
    "REFERENCE": {"reference_need", "dependency_clearance"},
    "DEPLOY": {"deployment_contract", "dependency_clearance", "destination_compatibility"},
}
RETIREMENT_KINDS = {"verified_redundancy", "explicit_supersession", "verified_residue", "explicit_retirement"}


def assess_action(action, facts=(), *, current_fingerprint=None, receipt_verifier=None):
    """Evaluate verified, provenance-bearing facts; never sum identity scores.

    Facts are supplied by reviewed evidence adapters, not perception models.
    This result is not approval or permission to execute an operation.
    """
    required = REQUIREMENTS.get(action)
    if required is None:
        return {"action": action, "confidence": "UNKNOWN", "eligible": False,
                "missing": ["action_contract"], "used_evidence": []}
    accepted, rejected, conflicts = {}, [], set()
    for fact in facts:
        if not isinstance(fact, dict):
            rejected.append('malformed')
            continue
        key = fact.get("kind")
        valid = (key in required and fact.get("verified") is True
                 and fact.get("receipt") and current_fingerprint
                 and fact.get("fingerprint") == current_fingerprint
                 and fact.get("source") in {"operator_review", "verified_inspector"})
        if key == "retirement_condition":
            valid = valid and fact.get("condition") in RETIREMENT_KINDS
            valid = valid and evaluate_retirement(fact, fingerprint=current_fingerprint)['state'] == 'SUPPORTED_CLAIM'
        if key == "dependency_clearance":
            valid = valid and fact.get("coverage_complete") is True and fact.get("unresolved") == 0
        # Self-labelled "verified" claims are not authenticated evidence. Only
        # a trusted adapter may verify the complete subject-bound fact and receipts.
        if valid:
            try:
                valid = callable(receipt_verifier) and receipt_verifier(dict(fact), current_fingerprint) is True
            except Exception:
                valid = False
        if fact.get("supports_action") is False and key in required:
            conflicts.add(key)
            valid = False
        if valid:
            accepted[key] = fact["receipt"]
        else:
            rejected.append(key or "untyped")
    for key in conflicts:
        accepted.pop(key, None)
    missing = sorted(required - accepted.keys())
    return {"action": action, "confidence": "HIGH" if not missing else "REVIEW",
            "eligible": not missing, "missing": missing,
            "used_evidence": accepted, "rejected_evidence": rejected,
            "approval_required": True,
            "receipt_verifier_available": callable(receipt_verifier)}


def quarantine_hold():
    # No production adapter currently supplies verified retirement/coverage receipts.
    return "Quarantine held: affirmative retirement, complete dependency review, and recovery evidence are required. Approval or an empty-folder observation alone is insufficient."
