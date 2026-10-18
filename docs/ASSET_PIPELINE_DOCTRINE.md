# Asset Pipeline Doctrine

The asset pipeline is mini_ark's local asset intake and routing capability.

It uses `C:\mini_ark` as both the capability reference and the project home. Outputs should therefore land in mini_ark's natural asset folders unless a later approved export targets another project.

## Operating Rule

Source policy:

Do not move or rewrite source files outside `C:\mini_ark` unless an explicit operator-approved apply/export step says so.

Token policy:

Every incoming item either arrives with a token or receives a provisional token at reception.

The source document name is primary token evidence. If an asset sheet or document names a known project or capability, the pipeline treats that as intentional identity evidence.

Tokens may also come from manifests, folder context, metadata, known project routes, user-provided family/label values, or prior registry knowledge.

If no confident token exists, the pipeline assigns a reviewable provisional token instead of pretending the item is anonymous.

Routing and placement decisions should follow token identity. Destination logic is downstream of token recognition, not a replacement for it.

Navigator path-based intake copies external source sheets into:

```text
C:\mini_ark\asset_pipeline\inbox
```

After processing, that inbox copy may be archived under:

```text
C:\mini_ark\asset_pipeline\inbox\archive
```

That archive behavior applies to staging copies, not the original outside source file.

## Natural Folders

```text
C:\mini_ark\asset_pipeline\inbox      intake copies and staged sheets
C:\mini_ark\asset_pipeline\recipes    reusable deconstruction recipes
C:\mini_ark\asset_pipeline\work       scratch and staged intermediate work
C:\mini_ark\asset_pipeline\outbox     generated jobs pending review
C:\mini_ark\asset_pipeline\approved   reviewed/approved job exports
C:\mini_ark\asset_pipeline\library    reusable asset sets by family/label
C:\mini_ark\asset_pipeline\rejected   rejected sets, when used
C:\mini_ark\asset_pipeline\logs       run logs
```

## Standard Flow

```text
source sheet
  -> copy to inbox
  -> read source document name for project/capability token evidence
  -> detect existing token or assign provisional token
  -> deconstruct / auto-detect
  -> repair when needed
  -> precision pass for icon-like assets
  -> review job
  -> approve/export
```

Deconstruction is lossless. Repair, precision, treatment, review, and approval are explicit stages with manifests. Approval copies the best reviewed stage into `approved\` and optionally into `library\<family>\<label>`.

The family/label pair is a token expression. It should clarify identity, capability ownership, or destination context without forcing a premature move.

Examples:

```text
project_orbit_icon_sheet_4x7.png      -> project_orbit + icons token evidence
media_player_controls_sheet.png       -> media_player + controls token evidence
```

The document name should not be discarded as mere source trivia. It is often the operator's first routing instruction.

## Navigator Surface

Use `Tools > Asset Intake` for the normal path. It accepts dropped files, selected files, or pasted local paths and returns the job result in Navigator.

Use `Tools > Asset Intake History` to inspect outbox jobs and find job names for review, repair, precision, or approval.

The advanced asset tools exist for narrower operations:

- Smart Asset Intake
- Batch Master Composer
- Asset Sheet Deconstructor
- Recipe-Bound ImageGen Brief
- 9-Slice Builder
- Asset Treatment Bench
- Asset Job Review
- Approve Asset Job
- Asset Repair Pass
- Icon Precision Pass

## Non-Automatic Actions

The asset pipeline does not automatically perform:

- deletion
- destructive dedupe
- external source relocation
- live app reference rewrites
- project-file moves outside mini_ark
- semantic merges of assets

Those remain proposal, preview, approval, and receipt territory.
