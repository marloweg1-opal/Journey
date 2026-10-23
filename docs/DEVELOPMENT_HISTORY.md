# Journey Development History

> **How to read this history:** This is a sourced project chronology, **not** a claim that every milestone is represented by a Git commit. The public `main` branch was republished as a portfolio-oriented snapshot in October 2026. It contains only two visible commits as of 2026-10-23, while the working project's development predates those commits. Do not interpret a two-commit graph as the project's total implementation effort.

Journey is the successor public identity for **Mini ARK**, the local Python/SQLite system developed within HEXSEED. The working Windows path and some command names continue to use `mini_ark` for compatibility. **HEXSEED is the user's machine and computing environment; Journey is the coordinating software; Project ARK is the broader architectural family.** See [Naming Architecture](JOURNEY_NAMING_ARCHITECTURE.md) and [Forward Architecture](JOURNEY_FORWARD_ARCHITECTURE.md).

## At a glance

This work has included multiple, interacting engineering disciplines:

- **Product and workflow definition:** translate a human desire for less computer friction into inspectable behavior and testable acceptance criteria, rather than starting from a file-extension sorter.
- **Architecture:** a project-neutral local coordinator with separation between observation, interpretation, proposals, scope, authorization, execution, receipts and recovery.
- **Filesystem engineering:** bounded scanning, cataloging, identity and duplicate evidence, dependency-aware placement, collision control, cross-volume considerations, interruption recovery, undo and non-destructive handling of unknowns.
- **Governance and privacy:** holds, contextual permissions, explicit consent boundaries, authenticated-approval aspirations, fail-closed action gates and deliberately disabled legacy mutation paths.
- **AI integration:** replaceable local reasoning, limited context packets with provenance and budgets, multiple independent advisory perspectives, and evaluation that cannot itself grant file-operation authority.
- **Product delivery:** CLI, local browser Navigator/Dashboard, documentation, synthetic/disposable fixtures, Windows launcher work and repeatable regression suites.
- **Reliability and review:** regression investigation, security boundary hardening, independent model-assisted critique, mutation testing, and correction of overstated claims.

These areas did not all arrive in one implementation. Many were designed, revised, rejected, independently challenged, and tested across successive iterations.

## Chronology and evidence level

| Period | Work and checkpoint | Evidence / qualification |
| --- | --- | --- |
| **August 17–31, 2026** | Mini ARK established as a local implementation distinct from the conversational assistant and the broader Project ARK concept. Early Python/SQLite work combined filesystem inventory, classification, provenance, proposals, approval, journaling and undo. | **Historical archive / conversations**. Earlier local scans and their large item counts are historical observations, not current inventories or Git milestones. |
| **September 2026, first half** | Stabilized machine/project placement concepts; clarified that `R:\` is the RuneScript drive root, while `C:\mini_ark` is the implementation directory. Architectural direction shifted toward **Journey** as the system's user-facing identity. Began formalizing stewardship contracts and separating the identity of a file from authority to act upon it. | See [R-drive doctrine](R_DRIVE_DOCTRINE.md), [Placement Doctrine](CANONICAL_PLACEMENT_DOCTRINE.md), [Naming Architecture](JOURNEY_NAMING_ARCHITECTURE.md). |
| **September 16, 2026** | Gate A development checkpoint: local fixture tests for dependency evidence, read/privacy controls, journaling-before-mutation, undo protections, Recovery & Repair contracts and Navigator management. | **Published source checkpoint:** [Gate A checkpoint](GATE_A_CHECKPOINT.md) documents 139 tests in one local run, with 134 passes and five intentional private-fixture skips in the isolated publication snapshot. The suite size and environment matter. |
| **September 17–29, 2026** | Hardened asset assessment, bounded metadata/content access, durable process handling and fail-closed guards; documented limitations around coverage, fixture issuers, production action authority and incomplete retirement evidence. | **Published source checkpoint:** [September 29 public checkpoint](JOURNEY_PUBLIC_CHECKPOINT.md) reports 288 passing tests on Windows/Python 3.14 before publication. It explicitly says no production file move had been demonstrated at that point. |
| **Late September–mid-October 2026** | Extended recovery, foreground confirmation, interruption/journal states, protected app references, cross-volume and restart scenarios, and Council/goal coordination. The Navigator and desktop-launch paths received repeated integration work. | **Historical local reports/conversations**, not entirely reconstructed from public `main`. Earlier checkpoint test totals are not comparable to later totals without matching test selection, environment and branch. |
| **October 19, 2026 (Pacific)** | Public portfolio release of the Journey repository, followed by desktop shortcut support. | **GitHub commit history:** `4a8a0ba` and `4eef5df`; GitHub dates are October 20 UTC. These are publication commits, **not** Journey's origin dates. |
| **October 21–23, 2026** | Local development reported replaceable primary-model conversation, an advisory Council, fixed-fixture capability proposal/evaluation, hardened local HTTP boundaries, a Dashboard image planner and recoverable image-action receipts. Security was independently challenged with 25 hostile/legitimate socket cases on a reproduced implementation. | **Reported local, not yet reconciled to public `main`**. Fixture success demonstrates a governed pipeline, not autonomous creation of arbitrary tools or production capability. |
| **October 23, 2026** | Codex reported **25 real images moved** into `R:\Pictures\CareBloomOS`, receipts `OP-000033`–`OP-000057`, SHA-256 checks, five unrecognized files left in place, and zero deletions. A selected 180-test suite and Brave receipt verification were also reported. | **Local execution report, not independently replayed in this public checkout.** Review the on-machine operational report/receipts before publishing a stronger claim. Codex reported recording explicit chat approval while the independent terminal approval usability problem remained unresolved. This is **not** evidence of general unattended authority. |

## What the test history means

Test counts are useful evidence of effort, but **they are not a score or a cumulative tally**. Different historical runs used different source snapshots, selected test sets, platforms, dependencies and fixtures. A test count cannot certify an unrelated feature.

The October 2026 public base also reportedly produced **39 unsuccessful full-suite tests** on Windows, matching its unmodified baseline. Therefore the entire published suite should **not** be described as passing. The later **180 passing tests** are from a **selected local regression suite**, not a green full-repository run.

Some tests deliberately exercise and reject unsafe or invalid operations; a refusal is sometimes correct runtime behavior. A test itself still needs to assert that refusal correctly rather than error unexpectedly.

## What was built versus what is planned

**Published in this repository:** the scope represented by the source, tests, contracts and dated checkpoints at the current commit. Its README and [Project Walkthrough](PROJECT_WALKTHROUGH.md) describe the public snapshot.

**Reported locally, awaiting public reconciliation:** October Dashboard reasoning and Council integration, strengthened HTTP guard, real-image pilot code and receipts. Preserve those implementations on their source branch and audit/scrub them before publication. Publishing this history document **does not** publish or authenticate the underlying unpublished code.

**Still open:** frictionless independent terminal approval, evaluator hardening, full-suite baseline investigation, clean installation/reconciliation, broad drive-scale organization, and any general self-expanding tool capability. `UNKNOWN` and `HELD` are meaningful outcomes, not invisible successes.

The October image pilot is an important **bounded operational milestone**. It is not proof that Journey can freely reorganize every resource, repair any dependency, or run without supervision.

## Human leadership and AI collaboration

The project's creator established the problem, intent, architecture constraints, requirements, scope, approval boundaries, acceptance criteria and decisions about what should count as evidence. Coding, test generation, architectural critique, documentation and debugging were carried out through sustained AI-assisted collaboration including ChatGPT, Codex and Claude.

This is a claim of **human-centered product/system design and AI-assisted development**, not a claim that the creator manually typed, audited or memorized every source line. The iterative evaluation and refusal to inflate completion claims are parts of the work itself. See [Project Walkthrough](PROJECT_WALKTHROUGH.md) for the existing portfolio attribution statement.

## Git history is not development history

The public repository's two visible commits resulted from a later publication/rewrite of project history. **Do not backdate commits, fake an activity graph, or invent earlier SHAs.** Keep genuine future code history intact, cite known historical checkpoints, and use this chronology to explain the imported snapshot.

### Publication / privacy boundary

Do not add raw personal files, inventories, prompt logs, private ledgers, authentication artifacts, quarantine contents or machine-specific receipts to the public repository merely to prove the milestone. Publish *sanitized evidence summaries* and, when ready, actual reviewed code and synthetic tests. A local report path is not a public artifact.

---

*Status: chronology assembled from published repo files and user-supplied local milestone reports as of October 23, 2026. It must be revised when independently verified implementation, commits and sanitized reports are reconciled.*
