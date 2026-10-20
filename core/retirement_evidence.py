"""Evaluate retirement claims independently of identity and execution authority."""


def evaluate_retirement(claim, *, fingerprint):
    missing = []
    if not fingerprint or claim.get('fingerprint') != fingerprint:
        missing.append('current_subject_fingerprint')
    if not claim.get('receipt') or claim.get('source') not in {'operator_review', 'verified_inspector'}:
        missing.append('accountable_provenance')
    condition = claim.get('condition')
    requirements = {
        'verified_redundancy': ('retained_copy_receipt', 'content_comparison_receipt', 'role_equivalence_receipt'),
        'explicit_supersession': ('successor_receipt', 'supersession_authority_receipt'),
        'verified_residue': ('producer_receipt', 'completed_lifecycle_receipt'),
        'explicit_retirement': ('owner_decision_receipt',),
    }
    if condition not in requirements:
        missing.append('explicit_retirement_condition')
    else:
        missing.extend(key for key in requirements[condition] if not claim.get(key))
    return {'state': 'SUPPORTED_CLAIM' if not missing else 'REVIEW', 'missing': missing,
            'execution_authorized': False,
            'reason': 'Claim receipts still require trusted verification, dependency review, recovery, and explicit approval.'}
