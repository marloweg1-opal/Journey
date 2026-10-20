"""In-memory Journey knowledge contracts. No collection, persistence or authority grants."""
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone


PROVENANCE = frozenset({'USER_DECLARED','USER_CORRECTION','CANONICAL','DOCUMENTED_FACT',
    'SYSTEM_REPORTED','APPLICATION_REPORTED','JOURNEY_OBSERVED','JOURNEY_DERIVED',
    'JOURNEY_INFERENCE','MODEL_INTERPRETATION','HYPOTHESIS','UNKNOWN'})
BLOCKERS = {'capability':'CAPABILITY_GAP', 'environment':'ENVIRONMENT_BLOCKED',
    'resources':'RESOURCE_BLOCKED', 'authority':'PERMISSION_BLOCKED',
    'policy':'POLICY_BLOCKED', 'evidence':'NEEDS_EVIDENCE'}


@dataclass(frozen=True, repr=False)
class Need:
    """Protected requirement payload intended to extend an existing open loop."""
    need_id: str
    condition: str
    why_it_matters: str
    finding_refs: tuple[str, ...] = ()
    proposal_refs: tuple[str, ...] = ()

    def assess(self, checks, *, outcome_verified=False, evidence_refs=()):
        return assess_need(checks, outcome_verified=outcome_verified, evidence_refs=evidence_refs)


def assess_need(checks, *, outcome_verified=False, evidence_refs=()):
    """A feasible proposal is not a satisfied need; preserve every unmet dimension."""
    if set(checks) - BLOCKERS.keys() or any(v is not None and type(v) is not bool for v in checks.values()):
        raise ValueError('Need checks require known independent boolean/unknown dimensions')
    if type(outcome_verified) is not bool:
        raise ValueError('Outcome verification must be explicit')
    blockers = [label if checks.get(key) is False else 'UNKNOWN_' + key.upper()
                for key, label in BLOCKERS.items() if checks.get(key) is not True]
    satisfied = outcome_verified and bool(evidence_refs) and not blockers
    return {'state':'SATISFIED' if satisfied else 'UNRESOLVED', 'blockers':blockers,
            'action_authorized':False, 'proposal_status_does_not_resolve_need':True}


@dataclass(frozen=True, repr=False)
class KnowledgeClaim:
    claim_id: str
    subject: str = field(repr=False)
    scope: str = field(repr=False)
    value: str = field(repr=False)
    provenance: str
    source_ref: str = field(repr=False)
    observed_at: datetime
    expires_at: datetime
    purpose: str = field(repr=False)
    status: str = 'raw'
    supersedes_event_id: str | None = None
    sensitivity: str = field(default='PRIVATE', init=False)
    portability: str = field(default='NONTRANSFERABLE', init=False)

    def __post_init__(self):
        if self.provenance not in PROVENANCE or self.status not in {'raw','accepted','rejected','superseded','stale'}:
            raise ValueError('Unknown provenance or claim status')
        if not all(isinstance(v,str) and v.strip() for v in
                   (self.claim_id,self.subject,self.scope,self.source_ref,self.purpose)):
            raise ValueError('Subject, scope, source, purpose and opaque ID are required')
        if any(v.tzinfo is None for v in (self.observed_at,self.expires_at)) or self.expires_at <= self.observed_at:
            raise ValueError('Bounded timezone-aware retention is required')


def supersede_inference(prior, correction):
    """Explicit scoped correction preserves history without changing unrelated contexts."""
    if (correction.provenance != 'USER_CORRECTION' or correction.status != 'accepted'
        or prior.provenance not in {'JOURNEY_INFERENCE','MODEL_INTERPRETATION','HYPOTHESIS'}
        or (prior.subject, prior.scope) != (correction.subject, correction.scope)
        or prior.claim_id == correction.claim_id or correction.observed_at < prior.observed_at):
        raise ValueError('An accepted same-subject/context correction is required')
    return replace(prior,status='superseded'), replace(correction,supersedes_event_id=prior.claim_id)


def usable_claim(claim, permissions, *, purpose, scope=None, now=None):
    now = now or datetime.now(timezone.utc)
    return (claim.status == 'accepted' and claim.observed_at <= now < claim.expires_at
            and purpose == claim.purpose and scope == claim.scope
            and permissions.get('semantic_retention_permission') is True
            and permissions.get('inference_permission') is True)


def knowledge_capability_status():
    return {'contract_version':1, 'discover_mode':'DISABLED',
            'user_knowledge_storage':'PROTECTION_NOT_READY', 'collection_enabled':False,
            'provider_execution_enabled':False, 'export_enabled':False,
            'replication_enabled':False, 'authority':'NONE',
            'implementation_scope':'in_memory_contracts_only'}
