# Journey / Mini ARK

**Journey** is a developing, local-first stewardship system for **HEXSEED**, the maintainer's custom Windows computer environment. **Mini ARK** remains the repository and implementation name; **Project ARK** is the broader architectural family, not a second name for this executable. Journey coordinates and assists rather than independently governing the computer.

**The central distinction: capability is not authority.** Code may be able to inspect, propose, or prepare a change without permission to perform it. Gate A is the current, most restricted operating authority level: bounded observation and proposals are distinct from approval to mutate managed files. The existence of a feature in Git does **not** establish that it is deployed, enabled, or authorized on a live machine.

## Start here (Windows)

The repository targets Windows and uses PowerShell, Python, and local Windows paths. These are **source-level instructions**, not a clean-install certification. The examples below were inspected in the published code; they were **not run on the maintainer's machine for this README update**.

```powershell
cd C:\mini_ark
.\ark.cmd brief
```

`brief` opens an existing ledger read-only and summarizes pending work. It reports a missing ledger rather than creating one. **Its output can include private work descriptions or local operational details. Do not paste raw output into public issues or documentation.**

Additional commands are available, but have different effects:

- `.\ark.cmd doctor` checks ledger health **and may migrate existing database schema**. It is not strictly read-only; review before running.
- `powershell -ExecutionPolicy Bypass -File .\start_mini_ark.ps1` launches the local Navigator server (normally on loopback port 8788, if available). The bypass applies to that PowerShell process, not a permanent machine-wide setting. The server may create local runtime records.
- `.\ark.cmd bootstrap` creates or initializes local configuration and ledger state. Do not use it as a harmless diagnostic.

These commands assume the expected local working tree and dependencies exist. No actual local output is reproduced here. See [the operator handbook](docs/HANDBOOK.md) for fuller operational guidance.

## Current published checkpoint

The September 29 [public checkpoint](docs/JOURNEY_PUBLIC_CHECKPOINT.md) records the earlier custody and verifier milestone. The repository has since published further **code-level** increments, including bounded metadata assessment with resumable receipts and a shared read-only work-policy view with non-authorizing natural-language previews. See [shared work policy](docs/WORK_POLICY.md) for its precise verification and deployment limits.

| State | Scope |
|---|---|
| Published and locally tested | Bounded discovery and inventory, source holds, privacy and recovery contracts, journals, test-bound move verifier, bounded metadata assessment, and shared policy read/preview infrastructure |
| Implemented but held or not established as deployed | Production managed moves, legacy consolidation and migration execution, and newly published Navigator/policy behavior pending separate controlled deployment |
| Not yet active work modes | Enforced Observe, Ask First, Balanced and Focused execution restrictions; previews are not activation |
| Future or separately gated | Broader learning campaigns, reusable stewardship routines, semantic providers, advanced reasoning and Council integration |

**Tests and publication do not confer authority.** The move verifier's fixture issuer is not a production approval mechanism. No live managed move is claimed. Gate changes and execution approval remain separate human-controlled decisions.

## What the code supports versus what Journey is building toward

**Present, at source level:** local CLI and Navigator components, bounded assessment and reporting, provenance-aware records, privacy/source-hold checks, and guarded proposal or verification paths. Each component's runtime availability and permissions must be checked independently.

**Design direction, not a shipping promise:** sustained contextual continuity, recurring-pattern learning, richer retrieval and relationships, reusable routines, and coordinated advisory reasoning. Terms such as *resonance* describe intended connections across evidence and context, not proof that semantic matching is currently enabled.

> **“Meatbags forever, sentient machines/programming that has discarded humanity as inherently necessary for its own continued meaning and existence... never.”**

## Why it exists

AI collaboration can be remarkably capable and remarkably forgetful.

Useful work gets scattered across conversations, files, notes, tools, revisions, and systems. Decisions get rediscovered. Context gets flattened. Important distinctions disappear.

mini_ark is an attempt to build infrastructure around that problem.

The goal is not simply a larger archive. It is an archive capable of preserving **continuity and relationship**.

### Archival
What happened? What was decided? Where did it come from?

### Resonance
What keeps recurring? What connects to this? What becomes relevant again here?

### Kernel
What operational core can turn those relationships into useful behavior?

## Human-centered by design

**People are the center. First and always.**

AI assistance should increase human capacity without flattening authorship, specificity, history, ambiguity, or the people whose work made the system possible.

Attribution and provenance are part of the architecture, not cleanup work performed afterward.

mini_ark's guardrails are intentionally architected by the maintainer: human review, visible reports, dry runs, approval gates, quarantine before deletion, and local control are not afterthoughts.

## Project status and historical context

mini_ark is under active development. Sections below include earlier milestones and should be read alongside the current published checkpoint above; they do not independently establish current deployment or permission.

Current work focuses on HEXSEED operational congruence, starting with CareBloom custody. Discover collectors, semantic providers and new persistent user-knowledge storage remain disabled.

### Gate A stewardship checkpoint

Gate A remains open; tests do not confer managed-file authority or Journey graduation.
Recovery & Repair now has a derivative-only provider contract and structural media
validation. Perception Policy supports inherited SEALED, LIMITED, and OPEN scopes
with separate inspection, semantic-retention, and learning permissions. Semantic
providers remain disabled. Personal-media inventories and recovery evidence are
local-only under ignored `private/` storage and are not part of this repository.

See [Recovery and privacy contracts](docs/RECOVERY_AND_PERCEPTION_POLICY.md).

Expect architecture changes, experiments, aggressively specific naming, and the occasional highly plausible piece of nonsense requiring verification.

## Implementation surfaces and historical MVP controls

The current local MVP includes:

- a Python CLI with a Windows wrapper: `ark.py` and `ark.cmd`
- a compact Navigator control surface: `index.html`
- a Rainmeter Tender Console widget under `rainmeter/`
- an operator handbook, user guide, and handoff docs under `docs/`
- read-only inventory, diagnosis, reporting, and classification commands
- approval-gated proposal/apply/undo workflows
- Wishstone asset intake under `asset_pipeline/`, with source-copy intake, reviewable outbox jobs, approved exports, and reusable library sets
- legacy CareBloomOS consolidation/archive planning (execution held)
- user-profile migration planning and hierarchy reports (execution held)

Typical local launch:

```powershell
cd C:\mini_ark
.\ark.cmd doctor
.\ark.cmd brief
powershell -ExecutionPolicy Bypass -File .\start_mini_ark.ps1
```

Safety posture: generated local ledgers, logs, maps, cache files, and handoff review packets are excluded from the GitHub archive unless explicitly reviewed for release.

Start with [`docs/HANDBOOK.md`](docs/HANDBOOK.md) if you want to operate mini_ark directly.

Naming posture: `Mini ARK` remains the implementation name and `C:\mini_ark` remains the canonical working tree. `Journey` is the emerging product/system identity, not a parallel codebase or active rename. See [`docs/JOURNEY_NAMING_ARCHITECTURE.md`](docs/JOURNEY_NAMING_ARCHITECTURE.md) and [`config/naming_status.json`](config/naming_status.json).

Wishstone's asset-pipeline doctrine lives in [`docs/WISHSTONE_ASSET_PIPELINE_DOCTRINE.md`](docs/WISHSTONE_ASSET_PIPELINE_DOCTRINE.md) and [`config/wishstone_asset_doctrine.json`](config/wishstone_asset_doctrine.json). Its source rule is simple: external source files are copied into intake and are not moved unless an explicit operator-approved export/apply step says so.

## License

mini_ark is licensed under the **Mozilla Public License 2.0 (MPL-2.0)**.

See [`LICENSE`](LICENSE) for the complete license terms.

## Maintainer

Created and maintained by **Junior Gilmore**

Developed with material collaboration from **OpenAI / ChatGPT**, with AI assistance credited openly rather than absorbed into anonymous authorship.

---

**mini_ark is the tender. Project ARK is the ship.**
