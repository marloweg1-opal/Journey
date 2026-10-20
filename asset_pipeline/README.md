# Mini ARK Asset ARK

Local-first intake, deconstruction, 9-slice extraction, and treatment for master asset sheets, sprite sheets, UI atlases, CareRail assets, VLC control sheets, menus, frames, and interface parts.

The central rule is:

```text
Deconstruction is lossless. Normalization is optional.
```

The project-routing rule is:

```text
External source files are copied into intake. They are not moved unless an operator-approved export/apply step explicitly says so.
```

Deconstruction copies the exact RGBA pixels inside recipe-defined cells. It does not tight-crop, resize, redraw, regenerate, or discard faint alpha pixels.

Treatments are nondestructive. They write new treated outputs with manifests instead of overwriting the source art.

Recipes should drive generation. Image generation should not force reverse-engineering unless the source sheet already exists.

Each successful job writes:

- `deconstructed/` flat individual files.
- `groups/<group>/` grouped copies based on the recipe group names.
- `repaired/` cleaned alpha-mask outputs when running an asset repair pass.
- `nine_slice/` extracted frame regions when running a 9-slice job.
- `treated/` adjusted assets when running a treatment job.
- `manifest.json` with source, recipe, dimensions, output paths, and checksums.
- `reconstruction-proof.png` showing the deconstructed cells can rebuild the source regions.

## Folders

- `inbox/` receives source-sheet copies and staged sheets.
- `inbox/archive/` receives processed staging copies.
- `recipes/` stores reusable JSON deconstruction recipes.
- `work/` is scratch space for future staged operations.
- `outbox/` receives generated individual files, grouped folders, manifests, and proofs pending approval.
- `approved/` receives reviewed/exported job assets.
- `rejected/` is reserved for rejected sets.
- `library/` receives approved, reusable asset sets by family and label.
- `logs/` is reserved for pipeline run logs.

## Commands

```powershell
python -m asset_pipeline inspect --recipe asset_pipeline\recipes\media_controls.example.json
python -m asset_pipeline run path\to\sheet.png --recipe asset_pipeline\recipes\media_controls.example.json
python -m asset_pipeline run-inbox
python -m asset_pipeline brief --job navigation_panel_parts --slots "top_rail,bottom_rail,left_cap,right_cap,center_crest,tab_home,tab_tools,tab_review,tab_manage" --columns 3 --cell-width 512 --cell-height 512 --gutter-x 48 --gutter-y 48 --margin-x 96 --margin-y 96 --style "Dark navy navigation interface assets. No text."
python -m asset_pipeline nine-slice path\to\frame.png --left 48 --top 44 --right 48 --bottom 44 --job navigation_panel_frame
python -m asset_pipeline treat path\to\asset.png --trim --padding 4 --tint "#c8ddff" --tint-strength 0.2 --shadow-blur 6 --shadow-offset-y 3 --job navigation_treated_asset
python -m asset_pipeline repair-icons project_orbit_icon_sheet_4x7__project_orbit_icon_sheet_4x7 --min-component-area 24
python -m asset_pipeline repair-icons damaged_icon_job --reshape-candidate --max-fill-ratio 0.08
python -m asset_pipeline normalize media_controls
python -m asset_pipeline verify media_controls
python -m asset_pipeline review-job media_controls
python -m asset_pipeline approve-job media_controls --family navigation --label media_controls
```

Outputs stay in `asset_pipeline\outbox\<job>\` until Mini ARK routing proposes a destination and a human approves it.

## Navigator Button

Mini ARK Navigator exposes these as **Tools > Asset Tools**.

Use **Recipe-Bound ImageGen Brief** before generating new sheets. It writes:

- A copyable ImageGen prompt.
- A matching recipe in `asset_pipeline\recipes`.
- A job folder in `asset_pipeline\outbox` with the prompt and recipe copy.

Use **Asset Sheet Deconstructor** when you have a generated or existing sheet. Open the tool to use one of the intake paths:

- Drag and drop an image sheet into the drop zone.
- Choose an image sheet from disk.
- Paste a full local path and run that sheet.
- Run the current contents of `asset_pipeline\inbox`.

Uploads and path-based intake copy the sheet into `asset_pipeline\inbox` first, then run the inbox pass. A sheet runs only when it matches exactly one recipe in `asset_pipeline\recipes`; unmatched or ambiguous sheets are skipped and logged instead of guessed.

## Filename Tokens

Asset ARK chooses recipes from the sheet filename. Use this naming shape:

```text
<family>_<asset_set>_<layout>_sheet.png
```

Examples:

- `project_orbit_icon_sheet_4x7.png`
- `navigation_panel_parts_sheet.png`
- `media_player_controls_sheet.png`

Recipes should declare a matching glob or token set. For the orb icons, the active trigger is:

```text
project_orbit_icon_sheet*.png
```

That means Mini ARK can infer the recipe from the name alone when the sheet lands in `asset_pipeline\inbox`.

## Organization

Asset ARK organizes extracted assets from recipe metadata:

- `group` becomes the first folder.
- `row` becomes the second folder when present.
- `filename` becomes the final asset name.

For icon-like assets, run **Icon Precision Pass** after deconstruction. It writes:

```text
asset_pipeline\outbox\<job>\precision\<group>\<row>\<filename>.png
asset_pipeline\outbox\<job>\precision-manifest.json
asset_pipeline\outbox\<job>\precision-contact-sheet.png
```

The pass alpha-trims visible pixels, adds consistent transparent padding, centers the result on a shared canvas, and keeps the original deconstructed assets untouched.

Run **Asset Repair Pass** before precision when a background-removed image has floating lines, isolated specks, leftover mask fragments, or rough transparent edges. It writes:

```text
asset_pipeline\outbox\<job>\repaired\<group>\<row>\<filename>.png
asset_pipeline\outbox\<job>\repair-manifest.json
asset_pipeline\outbox\<job>\repair-contact-sheet.png
```

Repair is conservative by default. It removes small disconnected alpha components and can lightly smooth alpha edges.

When **Try reshape candidate** is enabled, repair may create a bolder mask candidate that closes tiny gaps and rough cutouts. Mini ARK estimates the percentage of missing fill required by comparing newly visible candidate pixels against the current visible asset. The candidate is accepted only when it scores better than the cleaned version and stays inside the configured max-fill ratio. Rejected candidates are recorded in the manifest instead of silently replacing the asset.

This still does not make a bad recipe correct. If the input contains merged assets or the crop cuts off part of the intended object, fix the recipe/source sheet first, then repair. Full artistic inpainting should be treated as a separate AI-assisted candidate stage with human review.

When `repair-manifest.json` exists, **Icon Precision Pass** uses repaired assets as its source and records `source_stage: repair` in the precision manifest. That gives the pipeline a clear quality gate:

```text
deconstruct -> repair -> precision -> review/approve
```

## Duplicate and Quality Gates

Asset ARK records repeat work in `asset-index.json`. It fingerprints source file hashes, operation type, and meaningful settings. Repeating the same image with the same settings reuses the existing job instead of creating another numbered copy. Batch compose also collapses duplicate sheets inside the same run and treats the same selected files in a different order as the same work.

Use **Asset Job Review** before approval. It scores the best available job stage, currently preferring `precision/`, then `repaired/`, then `parts/`, then grouped/deconstructed assets. The review reports empty assets, visible pixels touching canvas edges, weak transparent padding, and likely visual duplicates using perceptual hashes.

Use **Approve Asset Job** when the set is usable. It copies the best available stage into:

```text
asset_pipeline\approved\<job>\assets
asset_pipeline\library\<family>\<label>
```

It also writes `approval-manifest.json` with hashes, source manifests, quality warnings, duplicate notes, and the exact files exported. Approval is therefore a routed asset-library step, not just copying files somewhere and hoping future-you remembers why.

## CareRail Use

CareRails should be built from extracted interface assets rather than stretched full-frame mockups. The practical sequence is:

1. Deconstruct source sheets into individual and grouped parts.
2. Use `nine-slice` for frames, rails, panels, and ornamental borders that need to resize.
3. Use `treat` for crop/padding/tint/shadow variants.
4. Build Rainmeter or web UI against the resulting assets and manifests.

## Existing Sheets

If a sheet already exists, drop it into chat and ask for a recipe. The visual pass can identify likely grids, gutters, margins, and irregular cells, then write a matching recipe for Asset ARK.
