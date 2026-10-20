# Recovery, repair, and perception privacy

Gate A remains open. Recovery is a separate stewardship domain, not a shortcut to
filesystem mutation authority, retirement, deletion, or Journey graduation.

## Recovery contract

Effort levels: OBSERVE, VALIDATE, DIAGNOSE, SAFE_RECONSTRUCTION, DEEP_RECOVERY,
MAXIMUM_SAFE_RECOVERY. A bounded task authority specifies source and derivative
workspace scopes, maximum effort, and an authority receipt. Internal escalation
does not ask the user to approve each algorithm. Missing authority, exhausted
resources, unproved results, or changed evidence stop the operation.

The current provider architecture is exercised with disposable fixtures. No
production reconstruction/remux provider is installed. Trusted fixture providers
receive immutable source bytes, not a source pathname. Attempt intent and output
paths are journaled before derivative writes. Output is exclusive-created and
verified; originals are not repair destinations. Interrupted attempts retain
RUNNING or WRITING_DERIVATIVE evidence and require review; automatic resume is not
yet implemented. This is a contract boundary, not an OS-level sandbox.

Video validation checks container, streams, plausible duration, and three bounded
decode windows with positive decoded frame counts. SAMPLE_DECODABLE is not a
full-file usability certificate. Photo validation records structural metadata and
first-frame decode only; unsupported formats and budget limits remain explicit.
No images are rendered to a model. No semantic tags, embeddings, training examples,
or persistent semantic observations are generated.

Exact duplicate relationships require full SHA-256 and byte-length agreement.
Every occurrence remains in provenance. Alternate encodings, probable duplicates,
partial recoveries, and derivatives cannot be collapsed using name similarity.
No relationship authorizes retirement. Metadata is the default organization;
physical subgroup eligibility requires group_count >= 5 and parent remainder >= 15.

## Privacy registry

Registry events, not badges, are authoritative. Policies inherit to descendants
using case-insensitive, boundary-aware absolute paths. Explicit child policies
override parents. Each event retains reason, version, and optional source identity.
Resolution reads policy only, never file content.

- SEALED: structural stewardship only; semantic retention and learning denied.
- LIMITED: semantic inspection only for listed purposes in the registered scope.
- OPEN: semantic inspection permitted by policy, but not automatically enabled.

Inspection, semantic retention, and learning are separate permissions. Retention
and learning default to false even for OPEN. Unknown scopes default to SEALED.
The semantic gateway rejects before reading bytes when the policy denies access
or providers are disabled. No semantic provider is enabled by this release.

Navigator Manage exposes Recovery & Repair status and a Perception Policy form.
Policy changes need an explicit confirmation; inspection does not. These controls
operate through the local bridge, not documentation links. Private evidence and
SQLite files are blocked from static serving, and `private/` is Git-ignored.
The bridge is localhost-only; these policy checks are not a replacement for
operating-system access controls or a future authenticated multi-user service.

## Explorer integration design

Future entry point: right-click folder > Journey > Perception > Seal / Limited /
Open. The shell extension passes an absolute path to the same registry action;
it does not inspect content or maintain its own permission database. The dialog
shows inherited policy, the governing scope/version, purpose restrictions and
separate retention/learning controls. A Grey Lock reflects SEALED policy. Child
overrides remain visible and are not silently cleared by a parent change.
No shell extension, registry installation, or icon changes are performed now.

## Remaining limitations

Gate A dependency completeness, authenticated retirement receipts, robust
cross-volume rollback/resume, power-loss proof, remaining workflow enforcement,
and durable Patrol scheduling remain blockers. Recovery authority records are
contracts for trusted local code, not yet a cryptographically authenticated
delegation system. No production repair endpoint is exposed. Personal-media
work currently stops at read-only inventory, validation, hashing, relationships
and planning. Provider codecs, handle-based race protection, complete provenance
alias handling and scalable resumable corpus hashing require further work.
