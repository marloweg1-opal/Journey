# Journey / Mini ARK

Journey is the evolving identity of Mini ARK: a local HEXSEED companion for
continuity, stewardship, coordination and reducing friction between Junior and
the computer. Project ARK is the broader PMM/PWM and domain-ARK umbrella; Journey
is its intended coordinator/gopher, not its entirety.

## Current status

| State | Scope |
|---|---|
| Implemented and verified locally | Bounded discovery/reference evidence, privacy policy, source holds, inventory, journal and recovery protections |
| Implemented but held | Operation-bound move verifier with test-only issuer; default production moves and legacy consolidation executors remain denied |
| Active milestone | Generic project custody: ownership, provenance, contextual classification and reviewable placement |
| Near-term | Exact eligible custody candidate and legitimate production evidence/approval source |
| Future, not shipped | Broader observation depths, advanced judgment, capability expansion and reasoning council |

Read [public checkpoint](docs/JOURNEY_PUBLIC_CHECKPOINT.md) and
[forward architecture](docs/JOURNEY_FORWARD_ARCHITECTURE.md) before older operating
guides. Historical descriptions below preserve development context, not current
authority. No live managed move is claimed from the verifier integration.

**mini_ark** is a local-first **Archival Resonance Kernel** for continuity, canon, project memory, contextual retrieval, and human-centered AI collaboration.

Built to help people and their tools remember what matters, connect what resonates, and keep moving without flattening the human at the center.

> **“Meatbags forever, sentient machines/programming that has discarded humanity as inherently necessary for its own continued meaning and existence... never.”**

## What mini_ark does

mini_ark is being developed as a persistent local intelligence layer that can:

- ingest and organize conversational and project context
- preserve decisions, principles, canon, and changing project state
- retrieve relevant context when it becomes useful again
- recognize recurring ideas, relationships, contradictions, and resonance
- support continuity across people, AI collaborators, tools, and projects
- provide shared infrastructure for multiple projects and expression profiles
- remain inspectable, attributable, and locally controlled

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

## Project status

mini_ark is currently under active development.

Current work focuses on HEXSEED operational congruence through project-neutral custody and stewardship contracts. Discover collectors, semantic providers and new persistent user-knowledge storage remain disabled.

### Gate A stewardship checkpoint

Gate A remains open; tests do not confer managed-file authority or Journey graduation.
Recovery & Repair now has a derivative-only provider contract and structural media
validation. Perception Policy supports inherited SEALED, LIMITED, and OPEN scopes
with separate inspection, semantic-retention, and learning permissions. Semantic
providers remain disabled. Personal-media inventories and recovery evidence are
local-only under ignored `private/` storage and are not part of this repository.

See [Recovery and privacy contracts](docs/RECOVERY_AND_PERCEPTION_POLICY.md).

Expect architecture changes, experiments, aggressively specific naming, and the occasional highly plausible piece of nonsense requiring verification.

## Current MVP controls

The current local MVP includes:

- a Python CLI with a Windows wrapper: `ark.py` and `ark.cmd`
- a compact Navigator control surface: `index.html`
- a Rainmeter Tender Console widget under `rainmeter/`
- an operator handbook, user guide, and handoff docs under `docs/`
- read-only inventory, diagnosis, reporting, and classification commands
- approval-gated proposal/apply/undo workflows
- project-neutral asset intake under `asset_pipeline/`, with source-copy intake, reviewable outbox jobs, approved exports, and reusable library sets
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

The asset-pipeline doctrine lives in [`docs/ASSET_PIPELINE_DOCTRINE.md`](docs/ASSET_PIPELINE_DOCTRINE.md) and [`config/asset_pipeline_doctrine.json`](config/asset_pipeline_doctrine.json). Its source rule is simple: external source files are copied into intake and are not moved unless an explicit operator-approved export/apply step says so.

## Integration profiles

Journey's architecture is project-neutral. Domain-specific terminology, artwork,
handoffs and cleanup scripts belong to the projects that own them. CareBloomOS was
the first mature integration profile and remains a documented example of how a
project can translate Journey's stable functional kernels without becoming the
base ontology or taking over this repository.

## License

mini_ark is licensed under the **Mozilla Public License 2.0 (MPL-2.0)**.

See [`LICENSE`](LICENSE) for the complete license terms.

## Maintainer

Created and maintained by **Junior Gilmore**

Developed with material collaboration from **OpenAI / ChatGPT**, with AI assistance credited openly rather than absorbed into anonymous authorship.

---

**mini_ark is the tender. Project ARK is the ship.**
