# Journey 1.0 RC2 Folder Planner

The Folder Planner helps a person decide where a selected collection of files
belongs. It records their collections, naming choices, and decisions in a local
plan they can reopen. The selected folder is read-only to the planner.

## Audit of the public starting point

The audit used [public main at f77256f](https://github.com/marloweg1-opal/Journey/tree/f77256f0eea9b9b968a48c375c4f91c2b898b254).

| Capability | What the public source showed | What RC1 delivers |
|---|---|---|
| First use | The [public demo](../README.md#try-the-public-demo) prints a checked-in stewardship contract. The [prototype launcher](../start_mini_ark.ps1) locates a separate Python installation and starts Navigator's local server. | An extracted Windows x64 folder containing a desktop launcher and its runtime. |
| Inspection | [Media inventory](../core/media_inventory.py) has bounded metadata enumeration and reparse checks, with a private hold-store dependency. The [general scanner](../scanner/scanner.py) hashes files and writes to the prototype ledger. | One explicitly chosen folder, scanned for file names, sizes, and timestamps. The planner reuses the metadata checks and reports skipped paths and limits. |
| Collections | The [classifier](../core/classify.py) includes project and machine conventions. Its buckets do not persist a person's collection choices in a standalone document. | User-named collections with bulk assignment. A file can belong to one collection per plan. |
| Preview and decision | The [naming engine](../core/naming.py) previews contextual names and format advice. The [prototype server](../mini_ark_server.py) also exposes apply, asset, and undo paths. | Editable naming and placement previews with extension preservation, collision checks, and explicit Include, Keep, and Review decisions. |
| Persistence and handoff | The [checkpoint](JOURNEY_PUBLIC_CHECKPOINT.md) documents prototype policy and recovery state. The public demo has no standalone save, reopen, and export workflow. | Versioned local plan snapshots and a plain-text checklist separating included, blocked, kept, and undecided items. |

The planner shares file metadata checks and naming safeguards with the
prototype. The release ZIP contains only the planner, those shared helpers,
the launcher, and the runtime. Navigator, the ledger, execution and recovery
handlers, and model integrations are outside this package. The longer-term
Journey mission and prototype remain described in the repository.

## First use

1. Extract the whole Windows ZIP and double-click **Journey.exe**.
2. Select **Choose folder** and pick a local folder. **Scan details** shows the
   stopping reason, skip counts by reason, and the path for each skipped entry.
   **Scan subfolder** starts its picker in the current folder and opens a focused
   plan in another window. The broader plan stays open with its own decisions.
3. Select related files, using Ctrl or Shift for several. Type a name in **New
   collection** and choose **Create & assign**. Use **Assign selected** to add
   files to an existing collection.
4. Select a single file to read or copy the full original and proposed paths.
   Edit **Proposed name** if needed, then choose **Set name** and **Include in
   checklist** or **Keep in place**. Files start in Review.
5. Use **Save plan** and select a location outside the original inspected folder.
   Close Journey, reopen it, and use **Open plan** to check the restored decisions.
6. Choose **Export checklist** and save the text outside the original inspected folder.
   Verify its included source and destination, then compare the original folder.
   A focused plan shows destinations relative to its subfolder and still protects
   the broader folder from plan and checklist writes.

The checklist is a historical record. Before making a manual change, verify
the current paths and any dependencies. The preview never authorizes an operation.

## Acceptance and limits

- The desktop acceptance test copies the repository's `docs` folder into an
  isolated workspace. It reaches a deliberately reduced entry limit, narrows the
  scan in the app, checks full paths, creates the Getting started collection,
  records Include and Keep decisions, then saves, closes, reopens, and exports.
  It compares source file paths, bytes, and modification times.
- A scan examines at most 10,000 entries or 20 seconds of enumeration. Links,
  junctions, inaccessible paths, and incompatible names are reported as gaps.
  The entry limit includes directories and skipped entries. Unvisited paths
  beyond a limit are outside the skipped-path count. Changed proposals in an
  incomplete scan caused by a limit require a smaller scan to verify them.
  Network and device paths are outside this candidate's scope.
- Plans and checklists contain names and paths. They are plain local files saved
  where the user chooses. An opened plan is a snapshot and needs no access to
  the original folder. Existing exports are preserved, and a stale plan save is
  rejected. RC2 opens RC1 plans. Saving uses the RC2 format, which persists the
  precise limit reason and the broader read-only boundary of a focused plan.
- This version uses a mouse-and-keyboard desktop interface and a text export.
  Keyboard navigation and platform-native dialogs are available. Screen reader
  compatibility, voice-only use, and high-contrast rendering still need direct
  testing. A person who relies on any of those modes may need assistance to
  complete the workflow.
- Semantic inspection, thumbnail rendering, automatic grouping, and managed
  file changes are outside RC2. The prototype's experimental paths are described
  in the public checkpoint. The boundaries of this program are not the boundaries
  of human possibility.

## Reproduce the build and tests

Run the source workflow from the repository with Python 3.12 or later and
Tcl/Tk installed for the desktop UI.

```text
python -B -m journey_planner
python -B -m unittest discover -s tests -p "test_folder_planner*.py" -v
```

Use a desktop session for the GUI test. Set `JOURNEY_REQUIRE_DESKTOP=1` to
require it. For the Windows bundle install Zig 0.15.2, or use
`python -m pip install ziglang==0.15.2` in an isolated build environment.
A Linux builder also needs `msiextract`. The packager checks both CPython
download digests and bundles only the standalone application files.

```text
python -B tools/build_windows_planner.py dist --cache runtime-downloads
```

Run the same planner tests against the extracted runtime for Windows acceptance.
On a clean Windows machine, check opening `Journey.exe`, the native folder
picker, save and export dialogs, and exit. The launcher is unsigned.

The legacy repository suite also covers machine-specific prototype behavior.
Its [checkpoint](JOURNEY_PUBLIC_CHECKPOINT.md#validation-and-reproducibility-limits)
records private policy dependencies. The standalone suite uses disposable data.
