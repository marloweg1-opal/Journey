# Journey Development History

> **How to read this history:** This is a sourced project chronology, **not** a claim that every milestone is represented by a Git commit. The public `main` branch was republished as a portfolio-oriented snapshot in October 2026, initially with two publication commits. Newer documentation commits have been added since then. The working project's development predates the portfolio publication; commit count is not its total development effort.

Journey is the successor public identity for **Mini ARK**, the local Python/SQLite system developed within HEXSEED. **The effort did not begin with Mini ARK:** it grew from earlier Windows and PowerShell automation work aimed at organizing downloads, screenshots, duplicates, and other files without constant manual sorting. The working Windows path and some command names continue to use `mini_ark` for compatibility. **HEXSEED is the user's machine and computing environment; Journey is the coordinating software; Project ARK is the broader architectural family.** See [Naming Architecture](JOURNEY_NAMING_ARCHITECTURE.md) and [Forward Architecture](JOURNEY_FORWARD_ARCHITECTURE.md).

## At a glance

This work has included multiple, interacting engineering disciplines:

- **Product and workflow definition:** begin with concrete Windows housekeeping scripts (including an extension-aware Downloads sorter), then translate the observed limits of standalone automation into context-aware behavior and testable acceptance criteria.
- **Architecture:** a project-neutral local coordinator with separation between observation, interpretation, proposals, scope, authorization, execution, receipts and recovery.
- **Filesystem engineering:** bounded scanning, cataloging, identity and duplicate evidence, dependency-aware placement, collision control, cross-volume considerations, interruption recovery, undo and non-destructive handling of unknowns.
- **Governance and privacy:** holds, contextual permissions, explicit consent boundaries, authenticated-approval aspirations, fail-closed action gates and deliberately disabled legacy mutation paths.
- **AI integration:** replaceable local reasoning, limited context packets with provenance and budgets, multiple independent advisory perspectives, and evaluation that cannot itself grant file-operation authority.
- **Product delivery:** CLI, local browser Navigator/Dashboard, documentation, synthetic/disposable fixtures, Windows launcher work and repeatable regression suites.
- **Reliability and review:** regression investigation, security boundary hardening, independent model-assisted critique, mutation testing, and correction of overstated claims.

These areas did not all arrive in one implementation. Many were designed, revised, rejected, independently challenged, and tested across successive iterations. **The important through-line is the progression from isolated scripts that do things to a coordinator that can decide which supported thing to do, under whose permission, how to verify it, and how to recover if it goes wrong.**

## Chronology and evidence level

| Period | Work and checkpoint | Evidence / qualification |
| --- | --- | --- |
| **March 19, 2026** | Workstation identity **HEXSEED-VER1** was in use in the early automation effort. Organizing the Windows machine itself, not building a general AI system, was the immediate problem. | **Prior conversation record.** This is an early documented point, not a claim that the idea first arose on this date. |
| **March 21–22, 2026** | Initial PowerShell work bootstrapped organized R: drive directories (including Downloads, Staging, Projects, Grimoire and Lab), then built/tested a Downloads sorter. The sorter classified incoming files, moved them into categorized destinations, compared size and SHA-256 for duplicate detection, and staged suspected duplicates under `R:\Staging\Duplicates` rather than deleting originals. A successful test was recorded March 22. | **Earlier conversation/implementation record; not reconstructed from the later Git history.** This was practical standalone automation, not Journey's later governed orchestration or a verified present-day deployment. |
| **April 2026** | The user sought increasingly automatic file organization and housekeeping across the everyday Windows environment using PowerShell, Task Scheduler and existing utilities. This included reducing routine manual cleanup and developing user-account-friendly workflows that elevate only when truly needed. Screenshot and temporary-file cleanup were among the desired tasks, but their complete implementation is **not independently established** here. | **Earlier discussion / requirements.** Distinguish proposed automation from executed tests. |
| **July 2026** | The growing automation toolkit included media-health and recovery work using FFmpeg/FFprobe, CSV reports, and quarantine-style duplicate handling. This widened the task from sorting by extension to assessing whether files were useful, healthy, duplicated, recoverable and safe to change. | **Earlier conversation record;** specific reported runs need their own machine evidence for current reproduction. |
| **August 17–31, 2026** | Mini ARK established as a local implementation distinct from the conversational assistant and the broader Project ARK concept. Early Python/SQLite work combined filesystem inventory, classification, provenance, proposals, approval, journaling and undo. | **Historical archive / conversations**. Earlier local scans and their large item counts are historical observations, not current inventories or Git milestones. |
| **September 2026, first half** | Stabilized machine/project placement concepts; clarified that `R:\` is the RuneScript drive root, while `C:\mini_ark` is the implementation directory. Architectural direction shifted toward **Journey** as the system's user-facing identity. Began formalizing stewardship contracts and separating the identity of a file from authority to act upon it. | See [R-drive doctrine](R_DRIVE_DOCTRINE.md), [Placement Doctrine](CANONICAL_PLACEMENT_DOCTRINE.md), [Naming Architecture](JOURNEY_NAMING_ARCHITECTURE.md). |
| **September 16, 2026** | Gate A development checkpoint: local fixture tests for dependency evidence, read/privacy controls, journaling-before-mutation, undo protections, Recovery & Repair contracts and Navigator management. | **Published source checkpoint:** [Gate A checkpoint](GATE_A_CHECKPOINT.md) documents 139 tests in one local run, with 134 passes and five intentional private-fixture skips in the isolated publication snapshot. The suite size and environment matter. |
| **September 17–29, 2026** | Hardened asset assessment, bounded metadata/content access, durable process handling and fail-closed guards; documented limitations around coverage, fixture issuers, production action authority and incomplete retirement evidence. | **Published source checkpoint:** [September 29 public checkpoint](JOURNEY_PUBLIC_CHECKPOINT.md) reports 288 passing tests on Windows/Python 3.14 before publication. It explicitly says no production file move had been demonstrated at that point. |
| **Late September–mid-October 2026** | Extended recovery, foreground confirmation, interruption/journal states, protected app references, cross-volume and restart scenarios, and Council/goal coordination. The Navigator and desktop-launch paths received repeated integration work. | **Historical local reports/conversations**, not entirely reconstructed from public `main`. Earlier checkpoint test totals are not comparable to later totals without matching test selection, environment and branch. |
| **October 19, 2026 (Pacific)** | Public portfolio release of the Journey repository, followed by desktop shortcut support. | **GitHub commit history:** `4a8a0ba` and `4eef5df`; GitHub dates are October 20 UTC. These are publication commits, **not** Journey's origin dates. |
| **October 21–23, 2026** | Local development reported replaceable primary-model conversation, an advisory Council, fixed-fixture capability proposal/evaluation, hardened local HTTP boundaries, a Dashboard image planner and recoverable image-action receipts. Security was independently challenged with 25 hostile/legitimate socket cases on a reproduced implementation. | **Reported local, not yet reconciled to public `main`**. Fixture success demonstrates a governed pipeline, not autonomous creation of arbitrary tools or production capability. |
| **October 23, 2026** | Codex reported **25 real images moved** into `R:\Pictures\CareBloomOS`, receipts `OP-000033`–`OP-000057`, SHA-256 checks, five unrecognized files left in place, and zero deletions. A selected 180-test suite and Brave receipt verification were also reported. | **Local execution report, not independently replayed in this public checkout.** Review the on-machine operational report/receipts before publishing a stronger claim. Codex reported recording explicit chat approval while the independent terminal approval usability problem remained unresolved. This is **not** evidence of general unattended authority. |
| **October 26, 2026 (Pacific)** | **Milestone 001: first grounded local-model proposal.** A local `qwen3:4b` reasoning attempt for `EXACT-0015` produced a validated, non-executing recommendation about a two-file, same-directory historical exact-byte duplicate group under the `ID_ONLY_V2` contract. The proposal was saved; no optional preference was recorded and no managed files were moved. | **User-supplied live terminal screenshots and local review notes, n=1 successful demonstration.** Earlier live attempts were rejected under the original row-echo contract and `ID_ONLY_V1`. This is proof of the bounded local pipeline on that occasion, not measured general reliability or evidence of autonomous organization. The implementing local changes and private records are **not** part of this public repository snapshot. |

## Milestone 001: what the first live proposal established

On October 26, 2026 (Pacific), the local development build completed one bounded, real-model reasoning demonstration against a previously pinned historical duplicate group. Journey selected the evidence, supplied it to the local model, validated the returned IDs and permitted interpretation/action, rechecked the pinned evidence, and retained a review-only proposal. The transcript ended with an explicit completion status, no recorded preference, and **no managed-file operation**. The model's contribution was deliberately narrow; Python supplied the facts and rendered the recommendation.

**Limits:** The sample was a two-file group already in the same directory, so the suggested shared-home review was not independently shown to save user effort. File roles, dependency clearance, backups, current contents, and deletion eligibility were **not** established. The history contains two earlier rejected live proposals under stricter/duplicative output contracts and only one successful `ID_ONLY_V2` live case. This observation does not estimate accuracy, utility, or safety for other data. Local implementation changes and real reasoning records are not published here. The one-time retention confirmation accepted unresolved synchronization uncertainty, not standing authority or authenticated task approval.

## Milestone 002: deterministic census review (local, pending usefulness grades)

In the local development worktree, Codex reported implementing a bounded, terminal-only `census-review` capability to classify historical exact-duplicate groups into four transparent buckets: **Worth reviewing**, **Needs additional evidence**, **Already congruent or low-value**, and **Protected or blocked**. Every eligible two- or three-file group is accounted for once, while unsupported or unjoined groups are counted as exclusions. Reasons are fixed rule codes, with filename and timestamp clues labeled as weak hints. The feature does not claim current file equality, file roles or execution authority.

**Reported verification, not replicated on this published code:** The initial selected fixture suite yielded 152 passes and five explicit skips. A later focused, synthetic policy-integration run reportedly yielded **112 passes, zero failures, errors or skips**. It exercised actual CLI policy-store selection against fixture and decoy hold databases, confirmed denial when the active policy was unavailable or malformed, and checked nonzero malformed-input exits and cancellation. The runs used different test selections and their counts must not be added or treated as a full-repository pass. Codex reported no code changes from the final integration check.

**Real-use observation:** A separate user-supplied terminal screenshot showed the historical review command completing in approximately 42.6 seconds, displaying findings without an intentional file operation. The synthetic integration verification neither inspected the real policy database nor retroactively establishes the correct production store selection for that earlier run. The queue's ranking quality has **not** been established: owner usefulness grades for the first ten findings remain pending. No real paths, prompts, private records or local review output are published here.

The feature's current local source and tests are **not yet reconciled to this public repository**, and documentation of its reported behavior is not publication or validation of that source. No standing file-operation authority was granted.

## CareBloomOS: a separate family passion project with shared HEXSEED roots

[**🌈 CareBloomOS**](https://github.com/marloweg1-opal/CareBloomOS) deserves its own identity in this history. It is a fever-dream, nostalgia-fueled family passion project and love letter to childhood wonder, Saturday-morning cartoons, magic, fantasy, friendship and caring, brought to life as a character-driven computer UI experience. Its Carestone Bearers, original lore, living fantasy worlds, themed utilities and expressive interfaces aim to bring a sincere **“awwwww!!!!!!”** back into everyday computing. Its worldbuilding, visual canon, authored experience and production assets belong to **CareBloomOS**, not to Journey. These are creative ambitions with different levels of implementation maturity, not a claim that a complete operating system has shipped.

**Relationship:** CareBloomOS and Journey are **separate projects in the same creative and technical family**, with overlapping HEXSEED roots. Their boundary was clarified through the lived complexity of organizing and expressing the Windows environment. CareBloom's first mature Journey integration profile is a documented translation of generic kernels into CareBloom vocabulary, not proof that all proposed integrations are operational. Journey's project-neutral governance never makes it owner of CareBloom canon; CareBloom's immersive presentation never grants Journey operational authority. See [CareBloomOS's own description](https://github.com/marloweg1-opal/CareBloomOS) and [Project Boundaries](PROJECT_BOUNDARIES.md).

## CareBloomOS and Journey: a shared early problem, then different responsibilities

**Origin interpretation (creator recollection, not a precisely dated technical split):** The early Windows automation, screen-capture housekeeping, file placement, and desktop-experience work were not conceived as a neatly separated "Journey product" from day one. They formed part of the wider effort to make HEXSEED usable, coherent, and personally expressive, alongside work that became CareBloomOS. The growing complexity and sprawl of the HEXSEED environment helped make a **dedicated operational coordinator** desirable. The boundary between CareBloomOS and Mini ARK/Journey emerged through practical work; it should not be retroactively portrayed as a fixed distinction from March 2026.

The creator recalls that screenshot cleanup may have become part of CareBloomOS rather than a distinct Journey automation. **That ownership remains a recollection and should not be asserted as confirmed implementation or as a specific migration event without code or dated evidence.**

In the later, clearer architecture:

- **HEXSEED** is the computer and the broader working environment, not a synonym for either application.
- **CareBloomOS** concerns expression and experience: visual language, interfaces, themed assets, and how the computer's workflows feel to the user.
- **Mini ARK / Journey** concerns the operational machinery and its evidence: inspection, context, permissions, filesystem stewardship, bounded execution, receipts, recovery, and project-neutral coordination.
- **Project ARK** is the wider software/intelligence family, not another name for CareBloomOS or Journey.

Those responsibilities can overlap in interfaces and experience. CareBloomOS can provide the expression of a workflow; Journey can provide governed underlying operations. A recurring challenge was to keep project-specific art and language from accidentally becoming Journey's generic core behavior. The present architectural split reflects **lessons learned**, not a claim that the project's early exploratory work was always organized that way.

See [Project Boundaries](PROJECT_BOUNDARIES.md), [Naming Architecture](JOURNEY_NAMING_ARCHITECTURE.md), and [Forward Architecture](JOURNEY_FORWARD_ARCHITECTURE.md).

## Why the pre–Mini ARK history matters

The original goal was not to make an AI agent for its own sake. It was to stop doing the same filesystem housekeeping by hand: downloads should go where they belong; transient screenshots should not pile up forever; duplicates should be handled deliberately; useful files should remain usable. These concerns developed amid the overlapping HEXSEED and CareBloomOS work before the later Journey distinction became clear. PowerShell and Windows scheduling were practical starting points. The later challenges of context, dependencies, permission, confidence, review and recovery are why a coordinating program became desirable.

March's working file sorter and October's reported 25-image pilot are separated by months of design and engineering, but share the same practical end goal. Neither event should be overstated: early scripts did not have all the later governance, and the current pilot does not demonstrate general unsupervised capability.

## What the test history means

Test counts are useful evidence of effort, but **they are not a score or a cumulative tally**. Different historical runs used different source snapshots, selected test sets, platforms, dependencies and fixtures. A test count cannot certify an unrelated feature.

The October 2026 public base also reportedly produced **39 unsuccessful full-suite tests** on Windows, matching its unmodified baseline. Therefore the entire published suite should **not** be described as passing. The later **180 passing tests** are from a **selected local regression suite**, not a green full-repository run.

Some tests deliberately exercise and reject unsafe or invalid operations; a refusal is sometimes correct runtime behavior. A test itself still needs to assert that refusal correctly rather than error unexpectedly.

## What was built versus what is planned

**Published in this repository:** the scope represented by the source, tests, contracts and dated checkpoints at the current commit. Its README and [Project Walkthrough](PROJECT_WALKTHROUGH.md) describe the public snapshot.

**Reported locally, awaiting public reconciliation:** October Dashboard reasoning and Council integration, strengthened HTTP guard, real-image pilot code and receipts, the October 26 bounded grounded-model demonstration, and the subsequent deterministic census-review queue with synthetic policy-integration verification. Preserve those implementations on their source branch and audit/scrub them before publication. Publishing this history document **does not** publish or authenticate the underlying unpublished code.

**Still open:** frictionless independent terminal approval, evaluator hardening, full-suite baseline investigation, clean installation/reconciliation, broad drive-scale organization, and any general self-expanding tool capability. `UNKNOWN` and `HELD` are meaningful outcomes, not invisible successes.

The October image pilot is an important **bounded operational milestone**. It is not proof that Journey can freely reorganize every resource, repair any dependency, or run without supervision.

## Human leadership and AI collaboration

The project's creator established the problem, intent, architecture constraints, requirements, scope, approval boundaries, acceptance criteria and decisions about what should count as evidence. Coding, test generation, architectural critique, documentation and debugging were carried out through sustained AI-assisted collaboration including ChatGPT, Codex and Claude.

This is a claim of **human-centered product/system design and AI-assisted development**, not a claim that the creator manually typed, audited or memorized every source line. The iterative evaluation and refusal to inflate completion claims are parts of the work itself. See [Project Walkthrough](PROJECT_WALKTHROUGH.md) for the existing portfolio attribution statement.

## Git history is not development history

The public repository's first two publication commits represented a later snapshot of a longer development history. Subsequent documentation commits do not reconstruct the earlier working history. **Do not backdate commits, fake an activity graph, or invent earlier SHAs.** Keep genuine future code history intact, cite known historical checkpoints, and use this chronology to explain the imported snapshot.

### Publication / privacy boundary

Do not add raw personal files, inventories, prompt logs, private ledgers, authentication artifacts, quarantine contents or machine-specific receipts to the public repository merely to prove the milestone. Publish *sanitized evidence summaries* and, when ready, actual reviewed code and synthetic tests. A local report path is not a public artifact.

---

*Status: chronology assembled from published repo files, earlier conversation records, and user-supplied local milestone reports through October 28, 2026. It must be revised when independently verified implementation, commits and sanitized reports are reconciled.*
