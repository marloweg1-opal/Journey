# Journey

**A human-governed local AI system that learns how you work while keeping every meaningful action visible, reviewable, and under your control.**

Journey is being built to help a person and their computer maintain continuity across files, projects, conversations, tools, and time. It remembers where work came from, preserves decisions and relationships, and proposes useful next steps without quietly taking authority for itself.

![Journey — human-governed local AI](docs/images/journey-repository-preview.svg)

> Journey is the public product identity. **Mini ARK** is its former name and remains in a few legacy filenames, commands, and the current Windows installation path while migration is completed safely.

## Start here

| If you want to… | Go here |
|---|---|
| Review Journey as a portfolio project | [Five-minute project walkthrough](docs/PROJECT_WALKTHROUGH.md) |
| Understand the work behind the public snapshot | [Development history and evidence](docs/DEVELOPMENT_HISTORY.md) |
| Meet a sibling family passion project | [CareBloomOS: a little magic for the machine](https://github.com/marloweg1-opal/CareBloomOS) |
| Run a safe, non-mutating example | [Try the public demo](#try-the-public-demo) |
| Understand Journey in plain language | [What Journey is](#what-journey-is) |
| See what currently works | [Current state](#current-state) |
| Operate the local installation | [Operator handbook](docs/HANDBOOK.md) |
| Understand where the project is going | [Forward architecture](docs/JOURNEY_FORWARD_ARCHITECTURE.md) |
| Review its safety and authority boundaries | [Project boundaries](docs/PROJECT_BOUNDARIES.md) |
| Inspect the technical implementation | [Developer map](#developer-map) |
| Ask a question or suggest a use case | [Open a question](https://github.com/marloweg1-opal/Journey/issues/new?template=question.yml) |

## What Journey is

Ordinary computer work becomes scattered. A decision may live in a chat, its source image in a downloads folder, its final version in a project directory, and the reason behind it only in someone's memory.

Journey is a local coordination layer for that problem. It is designed to:

- preserve the origin, context, and history of work;
- recognize which project or person something belongs to before classifying its file type;
- reconnect useful information when it becomes relevant again;
- propose organization and recovery actions for human review;
- keep consequential actions attributable and reversible; and
- support several projects without allowing one project's language to become the whole system.

It is not a general autonomous agent and it is not a replacement for human judgment. Its operating principle is **orientation, not domination**.

## What makes it different

### Local first

Private inventories, recovery evidence, and personal-media analysis remain on the local machine and are excluded from this repository.

### Human governed

Journey separates observation, recommendation, approval, and execution. A successful test does not grant the system new authority.

### Context before file type

A PNG may be a family photograph, product artwork, evidence, or temporary output. Journey asks what it belongs to and why it matters before deciding where it goes.

### Provenance is structural

Sources, decisions, receipts, and changes are meant to remain inspectable. Attribution is part of the architecture, not cleanup performed afterward.

## Current state

Journey is an active prototype—not a finished consumer application.

| Status | Capability |
|---|---|
| Working locally | Bounded inventory, reference evidence, privacy rules, classification, journaling, recovery protection, and a Navigator control surface |
| Approval gated | Proposed file operations, asset intake, exports, and undo workflows |
| Deliberately held | Default production moves, semantic providers, broad background observation, and new persistent personal-knowledge storage |
| Active milestone | Project-neutral custody: ownership, provenance, contextual classification, and reviewable placement |

Gate A remains open. Journey has not been granted broad managed-file authority.

For the evidence behind these statements, read the [public checkpoint](docs/JOURNEY_PUBLIC_CHECKPOINT.md).

## Try the public demo

This read-only walkthrough loads Journey's checked-in stewardship contract and
prints the safety states it expects an operation to pass through. It does not
scan your computer, create a ledger, or move files.

```bash
git clone https://github.com/marloweg1-opal/Journey.git
cd Journey
python -m pip install -r requirements.txt
python ark.py stewardship-contract
```

To inspect the same contract as structured data:

```bash
python ark.py stewardship-contract --json
```

The command is still named `ark` for compatibility with the working local
prototype. The product and repository are Journey.

## Using the current prototype

The current prototype retains the legacy command wrapper `ark.cmd`. Run it from
your own Journey checkout:

```powershell
cd C:\path\to\Journey
.\ark.cmd doctor
.\ark.cmd brief
powershell -ExecutionPolicy Bypass -File .\start_mini_ark.ps1
```

These technical names will migrate incrementally so that renaming the product does not break a working local system.

### Add Journey to your Windows desktop

Open the Journey folder and double-click `install_journey_shortcut.cmd`. It
creates a desktop shortcut named **Journey** using the crystal crest icon.
Double-clicking that shortcut starts the local Navigator and opens it in your
browser.

The shortcut points back to this Journey folder, so keep the folder where it
is after installation. To remove only the shortcut, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_journey_shortcut.ps1 -Remove
```

## Developer map

You do **not** need to read every file in this repository. These are the useful entry points:

| Path | Purpose |
|---|---|
| `README.md` | Public front door—the page you are reading |
| `index.html` | Journey's compact Navigator interface |
| `ark.py` | Command-line entry point |
| `core/` | Classification, stewardship, receipts, policy, and recovery logic |
| `config/` | Machine-readable policy and framework settings |
| `asset_pipeline/` | Copy-first intake and reviewable asset processing |
| `docs/` | Operator guidance, architecture, decisions, and boundaries |
| `tests/` | Automated checks for implemented behavior and safety contracts |
| `examples/` | External project profiles that use Journey without defining its core |

## Journey, Project ARK, and external projects

Journey is the local coordinator within the broader Project ARK vision. Project ARK may eventually contain higher-level mapping, memory, and domain systems; Journey is the component responsible for helping the computer remain oriented to the person, their work, and the authority it has actually been given.

**[🌈 CareBloomOS](https://github.com/marloweg1-opal/CareBloomOS)** is an independent **family passion project**, not a Journey module, fork, or subordinate brand. It is a fever-dream, nostalgia-fueled love letter to childhood wonder, Saturday-morning cartoons, magic, fantasy, friendship and caring, imagined as a character-driven desktop UI experience. Its Carestone Bearers, original lore, living worlds, themed utilities and visual language are designed for the kind of delight that makes someone go **“awwwww!!!!!!”** It is cute on purpose, and its conviction is that **care is infrastructure**.

Journey and CareBloomOS have **overlapping roots in the early HEXSEED effort** to make a growing, increasingly complicated Windows environment more organized, expressive and humane. The separation between CareBloom's authored world and Journey's project-neutral coordination emerged through that work, rather than existing as a fixed boundary from day one. CareBloomOS was Journey's first mature *integration profile*; the small [mapping example](examples/carebloom/README.md) demonstrates how an external project's terminology can express Journey functions **without transferring ownership of CareBloom's world, lore, assets, or experience to Journey**. The example is a documented mapping, not proof of a released full CareBloom-Journey runtime integration.

**CareBloomOS makes room for wonder. Journey helps the underlying work stay oriented, authorized, and recoverable.** Neither project owns the other's identity. Their separate public repositories and the [development history](docs/DEVELOPMENT_HISTORY.md) document the relationship.

## Naming transition

| Name | Meaning now |
|---|---|
| **Journey** | Product and public repository identity |
| **Mini ARK** / `mini_ark` | Former name retained only where immediate renaming could break local paths or integrations |
| **Project ARK** | The broader future family of systems; not synonymous with Journey |

See the [naming architecture](docs/JOURNEY_NAMING_ARCHITECTURE.md) for migration rules.

## How this was built

Junior Gilmore originated Journey's problem definition, product model,
operating principles, authority boundaries, workflow requirements and acceptance
criteria. AI systems have been used as implementation partners for code
generation, documentation, critique, testing and refactoring.

That collaboration is intentional and disclosed. Junior does not claim to have
hand-written every line; he is accountable for the system's direction, the
decisions accepted into the repository and whether its behavior matches the
human-governed design. See the [project walkthrough](docs/PROJECT_WALKTHROUGH.md)
for the working method, current limitations and common questions.

## Questions and participation

Journey is an active prototype, and thoughtful questions are welcome. You can
[open a question or feedback issue](https://github.com/marloweg1-opal/Journey/issues/new?template=question.yml),
report a reproducibility problem or propose a bounded use case. Please do not
attach private inventories, credentials, personal media or machine-specific
logs. See [CONTRIBUTING.md](CONTRIBUTING.md) for the engagement boundary.

## License and authorship

Journey is licensed under the [Mozilla Public License 2.0](LICENSE).

Created and maintained by **Junior Gilmore**. Developed with material collaboration from **OpenAI / ChatGPT**, with AI assistance credited openly rather than absorbed into anonymous authorship.

---

**Journey helps the system remain in relation without pretending that relation grants authority.**
