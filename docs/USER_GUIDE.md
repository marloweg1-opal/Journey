# Journey / Mini ARK User Guide

Journey is a local-first stewardship system. It helps inspect, classify and
organize digital environments while keeping consequential actions visible,
reviewable and reversible.

## Start

```powershell
cd C:\mini_ark
.\ark.cmd doctor
.\ark.cmd brief
powershell -ExecutionPolicy Bypass -File .\start_mini_ark.ps1
```

Open the localhost address printed by the launcher to use Navigator.

## Normal workflow

1. Observe an explicitly allowed scope.
2. Review classification and placement evidence.
3. Generate a proposal.
4. Approve only the intended items.
5. Preview the exact operation.
6. Apply with explicit confirmation.
7. Keep the receipt and undo path.

Tests, scans and reports do not grant action authority.

## Useful commands

```powershell
.\ark.cmd doctor
.\ark.cmd brief
.\ark.cmd tokens
.\ark.cmd routes
.\ark.cmd expression-slots
.\ark.cmd placement "C:\path\to\item"
.\ark.cmd name-preview "C:\path\to\item"
.\ark.cmd receipts
```

Run `.\ark.cmd --help` for the complete command list.

## Asset intake

The project-neutral asset pipeline copies external sources into controlled
intake, produces reviewable outputs and exports only approved results. Original
source files are not moved automatically.

See [Asset Pipeline Doctrine](ASSET_PIPELINE_DOCTRINE.md).

## Project profiles

Projects may translate Journey's functional kernels into their own language,
routes and presentation. Project-specific artwork, doctrine and operational
scripts stay with the owning project.

See [Project Boundaries](PROJECT_BOUNDARIES.md).
