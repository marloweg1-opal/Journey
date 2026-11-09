# Journey Navigator integrated pilot

Journey helps a Windows user inspect, understand, organize and resume work in a selected collection. It retains evidence in a local checkpoint when asked. The same assessments appear in Inspect, Find and the scoped Patrol review. A reference archive, a project naming rule and permission to change a file are separate records.

## Three-minute walkthrough

1. From a fresh checkout of this branch, use Python 3.12 or later with Pillow installed. Run the commands below from the repository root. The first creates an invented collection, two conversation exports with a duplicate message, and a project pack.
   
   ~~~powershell
   python -m pip install Pillow==12.2.0
   $demoRoot = Join-Path $env:TEMP ('Journey-Demo-' + [guid]::NewGuid().ToString('N'))
   python -m tools.demo_integrated_pilot $demoRoot
   python -B -m journey_navigator --data-dir (Join-Path $demoRoot 'Checkpoint')
   ~~~

2. In **Inspect**, select **Collection copies** inside the demo and enable **Keep a local checkpoint** and **Suggest names and draft a plan**. The wide `render_a.png` has an open purpose.
3. In **Project registry and validated naming**, paste the full local path to **Studio-fixture-pack.json**, preview and activate it. In **Local reference history**, preview and import **Local exports**. The two exports contain three distinct messages and one attachment pointer. `render_a.png` now has a CareRail design candidate with a source citation. The referenced attachment bytes are unavailable.
4. Save a **Destination** with a reason and a success criterion. In **Review → Talk to Journey about your work**, enter **Find render_a.png** or **Organize the selected folder**. Find shows inventory and reference results separately. Start the proposed organization plan to see evidence-linked groups and the work report.
5. Enter **Retire “Old Drawing Desk” assets**. Enable scoped reference reading to review the historical document and relevant dependencies. Select the image and record your reason. Prepare an archive proposal using the existing **Archive** folder. On Windows, an account-approved exact batch produces a verified operation receipt. Choose **Review safe reversal** on that receipt to prepare and approve undo. Run this demonstration on its disposable copies.

The Windows workflow builds an installable candidate. It uses an automated fixture actor only in execution tests, and exercises the installed application through a real browser. The product uses the actual Windows account approval path. A fixture actor cannot be enabled in the shipped app.

## Daily operation

- Use **Setup Journey.exe** from the extracted Windows package. One managed shortcut opens the compatible running session. A changed build asks before checkpointing and handing off. The running build and commit appear in Navigator. **Manage** lists saved inspections, managed builds and available recovery snapshots.
- The project pack can be one Journey JSON pack or an evidence ZIP with scoped profile and audit documents. Review the proposed change, activate once and reopen the saved inspection to reuse it. Use **Restore prior pack** to revert its activation. The pack carries supplied facts and rules. A separate **Local reference history** grant is what gives Journey a runtime archive index.
- Preview a native conversation JSON, folder containing top-level `conversations*.json`, or a file ending in `.manifest.json` with format `journey-history-manifest-1` and a `files` array of JSON basenames. The default budget is 128 files, 128 MiB per file and 768 MiB total. Each conversation has a 12 MiB limit. Import work checkpoints at conversation boundaries. Re-preview and confirm the same selection to resume. A failed file contributes no published claims.
- **Forget imported archives** removes the inspection’s archive index, source references and dependent cached assessments. Recovery snapshots containing retained inspection data are cleared. The input exports and separate physical action receipts are preserved.
- **Opt-in drift watch** samples up to 24 path metadata checks per minute within the original scope of one finished inspection. It reports drift, misses and the last check. It runs without OCR, a model or file changes. Stop it in Inspect, pause Patrol, revoke scope or close Navigator. After the last browser tab detaches, the service shuts down at a safe checkpoint. The watch starts off on each launch. Current observation is a bounded sample.
- The optional Qwen3 connection accepts one live prompt over loopback. Its response can propose only an intent or a literal search phrase. The local index and approvals remain on Navigator’s side. Plain text commands work when the model is unavailable. The archive parser treats all historical material as source data.

## Participation and release boundaries

The pilot is for users who can identify a local folder and interpret evidence or previewed changes. It offers keyboard controls, readable status and text provenance. Nonvisual recognition of unfamiliar artwork and a complete screen-reader task pass need direct testing. OCR uses English data and can leave stylized or low-quality text unreadable. Permission-bound background maintenance here covers metadata drift observation. Task scheduling across sessions, arbitrary workflow planning, standing physical authority, managed build cleanup and icon foundry remain future work. Contributions that bring a reproducible input, expected behavior and observed result are welcome.

The boundaries of this program are not the boundaries of human possibility.
