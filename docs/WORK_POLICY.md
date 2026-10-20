# Shared Work Policy: Read-Only First Increment

## Implemented

Navigator **Manage -> Work Policy -> Run** and its natural-language request form
use one backend view of `patrol_control_events`. They do not maintain a second
settings store. The exact-language preview endpoint is also reusable by the
existing conversational interface; model advice is never a policy grant.

Supported draft phrases include `pause journey`, `resume journey`, `observe only`,
`ask before every job`, `use balanced mode`, and `only help with duplicate detection
and ask before every job` (optional comma before `and`). Other wording is reported
as unrecognized, not guessed. This is deliberately not a general language parser.

A combined Focused/Ask First request preserves both requested restrictions in its
draft but is labeled UNSUPPORTED and not applied. Even pause/resume drafts remain
REVIEW_REQUIRED: previewing is not confirming, saving or executing. A review digest
binds the intention and current posture/version; it is not an approval token.

The read-only view reports Paused, Legacy Gate A posture, or Unknown. It never
relabels the legacy posture as Ask First or Balanced. Unknown/malformed policy
fails closed. Snapshot reads do not initialize schemas, configuration or defaults.
The existing runtime initializer remains explicit in the worker-facing reader.
The UI and worker-facing reader share the same strict posture validator, including
rejection of unsupported extra fields.

## Existing Enforcement and Gaps

- Existing Destination checks pause before discovery and immediately before task
  dispatch. This is boundary enforcement, not cancellation of in-flight work.
- Discovery approval guards check exact legacy posture, exact enabled scope and
  source holds. Approval binding/revocation/expiry is rechecked before consumption
  and execution, including the child execution path.
- Scope-specific authority events and per-task approval records remain separate
  from operator posture. A work mode must not replace these checks.
- Focus restrictions, Ask First for every job, Balanced routine selection and
  Observe as a distinct work mode are not implemented. No active setting is saved
  for any of them. An unsupported requested restriction must not be mistaken for
  a restriction already applied to existing work.
- Existing versioned pause updates are reused unchanged; no new confirmation or
  browser-based approval mechanism is introduced. UI/conversation previews do not
  call the update function. A foreground, exact-confirmation workflow and shared
  execution-time restriction checks are prerequisites for new modes.

## Verification and Deployment

`tests/test_work_policy.py` covers missing/malformed policy, shared read-only view,
restart persistence, stale version rejection, combined drafts, changing digest,
unrecognized permission claims and no writes during previews. Existing worker,
approval and intake tests cover pause and revocation at execution boundaries.
The disposable Brave demo also checks an unsupported combined draft leaves policy
unchanged, then a separately applied fixture pause appears on refresh.

Verification for this increment: 121 working-tree integration/regression tests
passed in 18.829 seconds; 71 tests passed in 1.953 seconds against an isolated
publication snapshot; Brave rendered assessment and policy flows both passed.
The two counts cover different suites, not 192 unique tests. Broader unpublished
Council/Destination development remains outside the publication. Its local Council
submit path also previews recognized policy requests through this same endpoint;
publishing that full Council interface requires separate scoped reconciliation.

No production migrations, records, scopes or services are changed. Deployment of
the new reader/routes/UI and strict validator requires separate controlled restart
approval. Unknown extra posture fields now stop work rather than being ignored;
review existing persisted state before deployment. The new read-only endpoints
require no schema migration. Future active work modes require a separate reviewed
implementation and any resulting data migration must be explicitly approved.

Rollback only these work-policy hunks and tests after review, preserving unrelated
development and event history. This increment does not deploy policy changes.
