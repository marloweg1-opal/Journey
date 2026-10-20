# Journey / Mini ARK Handbook

## Purpose

Journey reduces friction between a person and a changing digital environment.
It preserves context, explains recommendations and separates capability from
authority.

## Operating principles

- People remain the decision-makers.
- Capability is not permission.
- Observation scope is explicit.
- Unknown stays unknown.
- Ownership and context outrank file extension.
- Consequential work moves through proposal, approval, preview, receipt and undo.
- Destructive or ambiguous actions fail closed.
- Project-specific identities extend Journey; they do not replace its ontology.

## System layers

| Layer | Responsibility |
|---|---|
| Observation | Gather authorized structural evidence |
| Classification | Describe ownership, context and confidence |
| Placement | Compare current and likely canonical locations |
| Proposal | Express a bounded, reviewable change |
| Approval | Capture human authorization for that proposal |
| Execution | Apply only the authorized operation |
| Receipt | Preserve evidence, result and rollback information |
| Project profile | Translate generic capabilities for an external domain |

## Boundaries

The repository contains Journey's generic mechanisms, safety contracts,
Navigator and tests. An integrating project owns its terminology, artwork,
canon, handoffs and project-only scripts.

CareBloomOS was the first mature integration profile. Its history informed the
generic contracts, but its implementation is not Journey's base architecture.

See [Project Boundaries](PROJECT_BOUNDARIES.md) and
[Forward Architecture](JOURNEY_FORWARD_ARCHITECTURE.md).

## Safety

Generated ledgers, private inventories, personal media evidence, caches and live
runtime state do not belong in the public repository. Never infer authority from
a passing test, an old approval or a file's age.
