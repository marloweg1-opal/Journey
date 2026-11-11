# Incremental historical reconciliation

The Integrated Pilot now records evidence changes separately from the physical asset inventory. Adding conversation history does not refresh the inspection epoch, rehash images, repeat OCR, replace accepted corrections, or authorize a file operation.

## Use it

1. Open a retained inspection and activate its project pack.
2. Under **Local reference history**, preview and import the next JSON export or reviewed export folder. Existing imports remain available. Exports may overlap.
3. Open **Archive coverage and gaps** to see new assertions, changed assertions, overlapping assertions reused, affected-asset counts, and conversation/message citations. Claims from failed or incomplete imports stay unpublished.
4. Resume the saved Destination. Journey updates only affected saved assessments when the inventory, project rules, accepted corrections and other nonhistorical inputs are unchanged. The Patrol report states how many assessments were reused and reassessed.
5. Optionally choose **Monitor this reviewed export folder** after importing a folder in the current session. This grants automatic reading of future top-level `conversations*.json` files in that exact folder, for this inspection and project. New matching files and changed exports go through the same guarded importer. Nested folders, other filename patterns and manifests are outside this monitoring grant.

Monitoring is off by default and after restart. Stop it in the history controls, pause import or Patrol, forget history, revoke the scope, or close Navigator. A project or folder-identity change stops the monitor. Budget/access failures stop it for review. No grant expands to another project or directory.

## What is retained and reused

- Stable file IDs, content fingerprints, inspection epoch and saved pixel/OCR observations remain unchanged during a knowledge-only update.
- Message identity deduplicates overlapping branches. A semantic comparison of kind, filename, value, family and author role distinguishes repeated assertions from new evidence. Source associations remain retained for provenance, so duplicate exports still consume the explicit retention budget.
- A claim with a different value or asset family for the same kind/name is reported as changed evidence. Earlier assertions remain attributed. Conflicting evidence remains a question rather than silently replacing an accepted answer.
- Asset impact includes normalized filename candidates, both endpoints of new relationships, and supported entity aliases such as Beat/Melody to Musicstone. Only the profile-owning root is affected. Linked scopes retain independent interpretations.
- Patrol keeps a persistent evidence cursor and affected-asset queue. Unaffected assessment records and virtual memberships are reused. Full review remains appropriate after inventory, accepted corrections, project rules or other nonhistorical inputs change.
- Existing completed Pilot checkpoints gain a baseline without reprocessing saved assets when their previous evidence signature still matches. An incomplete or stale checkpoint requires ordinary review.
- Forgetting archive knowledge clears dependent saved virtual interpretations and queued evidence work. Source exports and image files remain intact.

## Resource and authority bounds

The monitor examines at most 24 directory entries each minute, with a soft 150 ms scan budget and a 4,000-entry folder ceiling. Imports retain the Pilot limits of 128 files, 128 MiB per file, 768 MiB total, 12 MiB per conversation and one checkpoint slice per worker iteration. A single conversation can exceed the usual 1 MiB slice, within its 12 MiB ceiling. Finalizing an export compares its structured claims against the bounded retained index.

When monitoring is explicitly enabled, background reconciliation updates at most one 24-asset page per minute across eligible saved Destinations. Paused Destinations and changed nonhistorical inputs require normal foreground review. Background updates use their own virtual-assessment route and cannot execute Guided batches. Full inventory-to-archive coverage counts can be refreshed with **Reconcile with inspected files** or by resuming Patrol. Background completion leaves the outcome open for review.

A historical update may invalidate an old exact-operation evidence binding. It never supplies new operation authority. Windows-account approval, production holds, protected collections, provenance and reversal requirements remain in force.

## Reproducible acceptance

Run from the repository root with Pillow installed.

```powershell
python -B -m unittest discover -s tests -p test_incremental_history.py -v
```

The tests use invented conversation exports and disposable image copies through the actual Workbench, importer and Patrol. They demonstrate:

- An already inspected Beat sheet, an overlapping second export, and new Beat/Melody relationship evidence. Two affected assessments change, one unrelated saved assessment is reused byte-for-byte, and an accepted correction survives.
- An overlap-only export produces zero reassessments and reuses all three saved assessments.
- Changed claims retain both old and new provenance and expose competing purposes.
- A directly accepted identity survives contradictory new evidence while retaining the challenge.
- A 30-asset update resumes after a partial 24-asset checkpoint and Patrol restart. A project-profile change requires full reassessment.
- Authorized folder monitoring imports only matching top-level files, stops on pause, and starts off in a newly constructed runtime.
- Background virtual updates never invoke the Guided executor. Input SHA-256 hashes and modification timestamps stay unchanged, no operation batch is created, and no new pixel analysis occurs.
- Forgetting history removes dependent interpretations before fresh review.

The Windows workflow also exercises the installed application's monitoring controls in a browser. Hosted Windows acceptance is distinct from live verification on HEXSEED. No live HEXSEED verification is implied by these fixtures.
