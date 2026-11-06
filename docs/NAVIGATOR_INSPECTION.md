# Journey Navigator inspection candidate

## Open Navigator

Extract the Windows x64 ZIP to a local test folder and open **Journey Navigator.exe**.
Navigator opens in your browser. **Inspect** accepts a folder path or lets you
browse local drives and select an existing folder shortcut, junction, or symbolic
link. **Manage** opens saved inspections and closes the local app.

Navigator shows the selected link and destination separately. For an out-of-scope
destination, choose **Authorize this destination** to read it, or **Keep current
scope**. A second out-of-scope hop gets its own review. **Links and destinations**
shows resolved, duplicate, pending, broken, protected, and cyclic links.

Discovery and image processing run in successive batches. You can pause and
reopen an inspection from **Manage**. **Refresh source** detects new or changed
files and reuses image analysis by content hash. **Images** and **Visual groups**
show thumbnails, overlapping virtual memberships, and grouped questions. Record
a correction on an image to update evidence for nearby examples. Set a naming
convention and use **Save plan** for a reviewable JSON plan with provenance,
coverage, and naming previews.

Journey keeps its checkpoint database, thumbnails, review decisions, and plan
exports in `%LOCALAPPDATA%\Journey\Navigator Inspection`. The selected source is
read-only. Review files can contain paths and private visual evidence. The app
can read the existing Journey source-hold and perception-policy records in read-only
mode when the standard production stores exist. Explicit restrictions still apply.

## Integration and limits

The candidate uses the existing Navigator page and visual shell, RC2 path and
naming checks, and Vision Lab's descriptors and review rules. Its isolated local
service supports inspection, Find over the current inventory, and Manage for
saved inspections. The production ledger search, action catalogue, and mutation
routes belong to the existing production service. RC1, RC2, and Vision Lab data
stay in their own formats. Import of those records is outside this candidate.

The shortcut reader uses filesystem paths stored in Windows shortcut records.
Network, device, shell-only, and tracking-dependent targets are reported as
unsupported. A folder shortcut needs a readable local path. Windows account
permissions, protected folders, and source holds remain in effect. Reopening
checks the saved link chain and physical source before continuing. If a link
changes, select it again and review the new destination. Directory identity is
used to avoid duplicate scans, and cycle checks cover chained links and links
back into the observed folder graph.

Coverage is a live, checkpointed observation. Directory enumeration can repeat
after interruption, with already recorded entries deduplicated. Image reads
have the Vision Lab's per-file 16 MiB and 20-megapixel limits. Pixel-based grouping
compares a bounded set of representatives. Grouping is approximate and visual
similarity alone does not establish identity. Contextual names require confirmed
subject and purpose. File changes remain previews. The workbench uses local
Windows access controls and path revalidation, with no elevated privileges.

The candidate uses standard keyboard-accessible browser controls. Thumbnails
have filename text and classifications have evidence labels. Identifying the
content of an unfamiliar image still relies on vision. Screen-reader usability
and nonvisual descriptions require separate verification.

## Verification

The Windows acceptance workflow builds and extracts the ZIP into a path with
spaces. It opens the bundled Navigator in a browser and selects a Windows-created
shortcut. The fixture includes nested directories, 10,020 other files, more
than 50 images, local shortcut and junction aliases, a cycle, and a destination
outside the initial scope. It pauses and restarts the service, resumes from
persisted counts, authorizes the outside target, applies a correction to a later
look-alike, refreshes cached analyses, exports the plan, and compares source
hashes and modification times. Targeted tests exercise malformed and broken
shortcuts, permissions, retargeting, source holds, and separate local drives
where the runner has them.

The boundaries of this program are not the boundaries of human possibility.
