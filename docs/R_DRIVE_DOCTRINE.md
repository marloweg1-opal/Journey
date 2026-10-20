# HEXSEED C: and R: Drive Operating Doctrine

This document defines how Mini ARK should understand, organize, and interact with the C: and R: drives.

Its purpose is to prevent Mini ARK from treating the computer as one undifferentiated pile of files or inventing new organizational rules whenever it encounters uncertainty.

## 1. The Core Split

### C: is the operating environment

C: holds the machinery that performs work.

This includes:

* Windows and installed applications
* Mini ARK itself
* HEXSEED Control Plane
* Python and Python environments
* scripts, modules, and executable tools
* active configuration files
* databases or indexes Mini ARK needs to operate
* logs, caches, thumbnails, and temporary files
* staging areas used during scans, repairs, imports, and migrations
* local working copies that can be regenerated
* application-specific files that must remain on C: to function properly

Mini ARK's primary installation location is:

`C:\CathedralRoot\mini_ark`

Other HEXSEED operating components may live beneath:

`C:\CathedralRoot\`

C: is not the default destination for personal archives, completed creative work, recovered media, project assets, or irreplaceable user files.

### R: is the durable user repository

R: holds the user's actual body of work and personal digital materials.

This includes:

* documents and records
* creative assets
* photographs, video, audio, and other media
* project materials
* reference libraries
* agreements and administrative records
* exports and completed deliverables
* recovered files
* archives
* reusable templates
* personal and household files
* resources intended to remain accessible independently of Mini ARK

R: should remain intelligible to a human browsing it without Mini ARK.

Mini ARK can enrich R: with indexes, manifests, reports, metadata, and shortcuts, but the files must not become dependent on Mini ARK simply to be found or understood.

## 2. The Relationship Between the Drives

The relationship is:

**C: performs. R: preserves.**

Mini ARK operates from C:, reads and tends R:, and returns durable results to R:.

A normal workflow should look like this:

1. Mini ARK runs from C:.
2. It scans or receives files from R:, user-account folders, removable drives, downloads, or recovery sources.
3. Temporary processing happens on C: when appropriate.
4. Mini ARK identifies the likely file type, purpose, ownership, project relationship, duplicates, and destination.
5. It presents or records its proposed action.
6. Approved durable files are placed into the appropriate location on R:.
7. Temporary files, caches, and regenerable processing artifacts remain on C: or are safely cleared.
8. Mini ARK updates its indexes, logs, manifests, and shortcuts.

Mini ARK must not move Windows-controlled application data or functioning program files to R: merely for organizational neatness.

Mini ARK must not keep the only copy of an important user file inside a cache, temporary folder, Python environment, application-data folder, or Mini ARK installation directory.

## 3. Mini ARK's Required Behavioral Model

Mini ARK is a curator, migration assistant, and systems steward. It is not an autonomous rearrangement engine.

It should:

* inventory before reorganizing
* classify before moving
* preserve before renaming
* distinguish confirmed facts from inferred classifications
* use confidence levels when classification is uncertain
* keep a record of every move, rename, deduplication, and replacement
* support rollback wherever reasonably possible
* quarantine uncertain or conflicting files rather than guessing
* use shortcuts to create project views without duplicating source files
* recognize that storage category and project membership are separate dimensions
* produce visible progress, current activity, totals, and estimated completion time for long operations
* pause safely and resume after interruption or restart
* never silently overwrite a different file with the same name
* never delete the final known copy of a user file
* never treat "duplicate-looking" as proof that two files are disposable duplicates

For any operation expected to take longer than approximately five minutes, Mini ARK must show:

* the operation being performed
* current file or folder
* items completed
* total items, when known
* percentage completed
* elapsed time
* estimated time remaining
* errors or items requiring review
* a clear indication that Mini ARK is still active

## 4. R: Drive Architectural Principle

R: should not be organized only by project.

A single file can be:

* an image by file type
* a Welfare Witchcraft asset by project
* a published deliverable by lifecycle state
* a reusable texture by future usefulness

Putting a copy into every applicable project folder would create duplication and version confusion.

Therefore:

**Canonical files are stored according to what they are. Projects gather what they use through shortcuts, indexes, manifests, or explicit project-owned working folders.**

A project folder is not automatically the permanent home of every file associated with that project.

Projects should contain:

* project-specific planning
* active working files
* project-owned source material
* exports and deliverables
* documentation
* manifests
* shortcuts to canonical assets stored elsewhere

They should not accumulate unnecessary duplicate copies of shared fonts, textures, references, media, templates, or administrative records.

## 5. Proposed R: Drive Map

The following is the intended architectural map. Existing material should be inventoried and migrated into it carefully rather than forcing the entire structure into existence at once.

```text
R:\
├── RuneScript\
│   ├── Bureaucracy_Mancer\
│   │   ├── User_Terms_Agreements\
│   │   │   ├── Inbox\
│   │   │   ├── Active\
│   │   │   ├── Superseded\
│   │   │   └── Reviews\
│   │   ├── Identity_Records\
│   │   ├── Financial_Records\
│   │   ├── Employment_Career\
│   │   ├── Insurance_Benefits\
│   │   ├── Transportation_Gig_Work\
│   │   ├── Household_Admin\
│   │   └── Templates\
│   │
│   ├── Projects\
│   │   ├── CareBloomOS\
│   │   ├── Welfare_Witchcraft\
│   │   ├── HEXSEED\
│   │   ├── Mini_ARK\
│   │   ├── Gig_Work_Accessibility\
│   │   └── Future_Projects\
│   │
│   ├── Knowledge\
│   │   ├── Research\
│   │   ├── References\
│   │   ├── Notes\
│   │   ├── Learning\
│   │   └── Manuals\
│   │
│   ├── Creative\
│   │   ├── Writing\
│   │   ├── Design\
│   │   ├── Illustration\
│   │   ├── Audio_Projects\
│   │   ├── Video_Projects\
│   │   └── Templates\
│   │
│   └── Personal\
│       ├── Documents\
│       ├── Correspondence\
│       ├── Household\
│       ├── Travel\
│       └── Personal_Archive\
│
├── Media\
│   ├── Images\
│   │   ├── Photos\
│   │   ├── Screenshots\
│   │   ├── Artwork\
│   │   ├── Generated_Images\
│   │   ├── Textures_Patterns\
│   │   └── Reference_Images\
│   │
│   ├── Video\
│   │   ├── Personal\
│   │   ├── Project_Source\
│   │   ├── Exports\
│   │   ├── Recovered\
│   │   └── Needs_Repair\
│   │
│   ├── Audio\
│   │   ├── Music\
│   │   ├── Recordings\
│   │   ├── Project_Source\
│   │   └── Exports\
│   │
│   ├── Fonts\
│   ├── Icons\
│   └── Shared_Assets\
│
├── Library\
│   ├── Books\
│   ├── Articles\
│   ├── PDFs\
│   ├── Manuals\
│   ├── Courses\
│   └── Reference_Collections\
│
├── Archive\
│   ├── Completed_Projects\
│   ├── Superseded\
│   ├── Legacy_User_Accounts\
│   ├── Historical_Exports\
│   └── Unsorted_Legacy\
│
├── Intake\
│   ├── New\
│   ├── From_User_Accounts\
│   ├── From_Old_R_Drive\
│   ├── From_Removable_Media\
│   ├── Recovered\
│   ├── Needs_Classification\
│   └── Possible_Duplicates\
│
└── System_Records\
    ├── Mini_ARK_Manifests\
    ├── Migration_Logs\
    ├── Rename_Logs\
    ├── Duplicate_Reports\
    ├── Repair_Reports\
    ├── Folder_Maps\
    └── Checksums\
```

This map is a controlled framework, not permission to manufacture empty complexity. Mini ARK should create folders when they have an identified purpose or incoming contents.

## 6. Meaning of the Major R: Areas

### RuneScript

RuneScript contains structured human work: projects, writing, planning, knowledge, administration, and records.

It is the primary realm for materials whose meaning matters more than their file format.

A PDF contract belongs with the relevant administrative records, not automatically in a generic PDF folder.

A CareBloomOS planning document belongs with CareBloomOS, even though it is technically a document.

### Media

Media contains canonical visual, audio, and video assets.

It should be used when the file is primarily an asset, recording, source file, photograph, reusable visual, or media export.

Projects may link to these files instead of storing duplicate copies.

### Library

Library contains material primarily kept for reading, learning, research, or reference.

It is distinct from project research that is being actively annotated or transformed. Mini ARK may connect Library materials to relevant projects through shortcuts or manifests.

### Archive

Archive contains material that is no longer active but must be preserved.

Archive is not a dumping ground for files Mini ARK does not understand. Uncertain files belong in Intake.

### Intake

Intake is a transitional area.

Files should not remain in Intake permanently without a reason. Mini ARK should periodically report:

* what is waiting
* how long it has been waiting
* what classification is proposed
* what information is missing
* which decisions require the user

### System_Records

System_Records contains the human-readable history of Mini ARK's stewardship of R:.

It may include manifests and reports, but Mini ARK's executable code and working databases remain on C: unless a durable export or backup is deliberately placed here.

## 7. Folder and File Naming Conventions

Folder names should be:

* readable without special software
* stable over time
* specific enough to distinguish their purpose
* consistent within the same branch
* free from ornamental renaming that obscures meaning

Use underscore-separated names for formal system folders:

`User_Terms_Agreements`

`Employment_Career`

`Possible_Duplicates`

Use established project names exactly:

`CareBloomOS`

`Welfare_Witchcraft`

`HEXSEED`

`Mini_ARK`

Do not casually normalize, respell, abbreviate, or "correct" named-project terminology.

For ordinary files, preserve meaningful original names when possible.

Rename files when:

* the existing name is meaningless
* a camera or scanner name provides no useful identity
* multiple files would otherwise be indistinguishable
* a consistent series clearly benefits from structured names
* the user approves a proposed convention

A useful general convention is:

`YYYY-MM-DD_Subject_Description_Status.ext`

Examples:

`2026-08-24_R-Drive_Architecture_Draft.md`

`2026-08-20_Uber_Toll-Policy_Feedback_Final.docx`

Dates should only be added when the date is known and genuinely useful. Mini ARK must not invent dates based solely on an unreliable modified timestamp.

Avoid names such as:

* `final_final2`
* `new folder`
* `misc`
* `stuff`
* `document1`
* unexplained acronyms
* names derived from an unsupported guess about the contents

## 8. Shortcut and Project-Collection Rules

Shortcuts are appropriate when a canonical file belongs elsewhere but is useful inside a project view.

Example:

A reusable opal texture may live at:

`R:\Media\Images\Textures_Patterns\Opal\`

CareBloomOS may contain a shortcut or manifest reference to it rather than a second physical copy.

Mini ARK should:

* verify the canonical target exists before creating a shortcut
* use clearly marked shortcut collections
* detect and report broken shortcuts
* update known shortcuts when Mini ARK itself moves the target
* never mistake a shortcut for an independent backup
* avoid chains of shortcuts pointing to other shortcuts

A project may keep its own copy when the file is intentionally forked, edited independently, packaged for delivery, or frozen as part of a release. Such a copy should be labeled by purpose or version.

## 9. Migration From User Accounts and the Old R: Drive

Mini ARK should not immediately empty user folders or reorganize the old R: drive in place.

The migration sequence should be:

1. Inventory the source.
2. Record paths, sizes, timestamps, file types, and checksums where practical.
3. Identify exact duplicates, likely duplicates, and unique files.
4. Copy unique files into a migration intake area.
5. Verify the copied files.
6. Classify them against the R: architecture.
7. Propose renames or destinations where confidence is limited.
8. Move verified files from Intake into their canonical destinations.
9. Create project shortcuts where useful.
10. Produce a migration report.
11. Retain the original source until the migration has been verified and the user authorizes cleanup.

Files from Desktop, Documents, Downloads, Pictures, Videos, and old user accounts should be classified by purpose. Their former Windows location is source information, not necessarily their final R: destination.

## 10. Duplicates, Versions, and Conflicts

Mini ARK must distinguish:

* exact duplicates
* resized or recompressed variants
* edited versions
* exports
* thumbnails
* backups
* independently useful alternate formats
* files that merely share a name

Hashes can establish identical file contents. Matching filenames cannot.

When multiple nonidentical files have the same name, Mini ARK should preserve both and create a conflict report.

When one file appears to supersede another, Mini ARK should not delete the older version automatically. It may move a confirmed older version to a `Superseded` or version-history location.

## 11. Future Holds

The architecture must preserve room for future capabilities without prematurely implementing all of them.

Future Mini ARK functions may include:

* content-aware classification
* semantic search
* image and media tagging
* automatic project manifests
* duplicate reconciliation
* version relationship detection
* broken-shortcut repair
* drive-health reporting
* scheduled archive reviews
* asset-use tracking
* document retention rules
* media repair pipelines
* naming suggestions
* user-account migration assistants
* Moonstone diagnostic reports inside CareBloomOS
* review queues presented through the HEXSEED Control Plane
* backup and redundancy verification
* automated but reversible housekeeping

Future-facing folders should only be created when the corresponding function or material exists.

Do not use "future possibility" as justification for adding dozens of empty folders or moving files into speculative categories.

## 12. Canon Protection and Uncertainty

If the existing drive contains a structure, project name, category, or convention not covered here, Mini ARK must not silently replace it.

Mini ARK should classify its knowledge as:

* **Confirmed:** explicitly defined by the user or verified by content
* **Strongly inferred:** supported by several clear signals
* **Tentative:** plausible but requires review
* **Unknown:** insufficient information

Only confirmed, low-risk actions should become fully automatic.

Strongly inferred actions may be batched for approval.

Tentative and unknown items should remain in a review queue or Intake.

Absence of instruction is not permission for Mini ARK to fill the space with a new system.

## 13. The Desired End State

The final system should allow the user to:

* reinstall or replace Mini ARK without losing their organized work
* browse R: manually and understand where things are
* locate materials by project without duplicating everything
* see what Mini ARK is doing during long operations
* reverse or audit organizational changes
* migrate old user-account files safely
* distinguish active work, canonical assets, reference material, Intake, and Archive
* expand the system without repeatedly rebuilding the folder architecture

The governing summary is:

**C: contains the intelligence and machinery.**

**R: contains the durable memory, materials, and body of work.**

**Mini ARK lives on C:, tends R:, and must leave R: more intelligible, recoverable, and human-readable than it found it.**

## 14. Future Hold: Manifestation Model (not an active build task)

A later architectural refinement, noted here so it isn't lost, but explicitly **not** something to build now:

HEXSEED environments are not a theme applied on top of one fixed machine. They are **manifestations**: complete identity states (icons, wallpapers, Rainmeter configs, scripts, lighting profiles, UI behavior, organizational language, supporting code) that can be archived, retrieved, and deployed as a unit.

This implies a third category alongside R: (source identity) and C: (active manifestation): **permanent machinery** -- infrastructure that operates *on* manifestations and therefore cannot live *inside* one. Mini ARK belongs to this category. It must not depend on any single HEXSEED identity being active, since its job is to move between them.

Intended eventual layout:

```text
C:\
└── CathedralRoot
    ├── mini_ark              (permanent machinery -- not part of any manifestation)
    ├── HEXSEED\ActiveManifestation
    └── System

R:\
└── RuneScript
    ├── HEXSEED
    ├── CareBloomOS
    ├── Projects
    ├── Archives
    └── Assets
```

Icon placement follows directly from this: a tool's own icon (e.g. Mini ARK's) is permanent-machinery and stays with the tool; an identity's icon (e.g. CareBloomOS's) is manifestation content and lives in R: under that identity, deployed to C: only while that manifestation is active.

**Current reality, as of this writing:** Mini ARK's actual install path is `C:\mini_ark`, not `C:\CathedralRoot\mini_ark`. This is a known, deliberate divergence from the intended layout above -- not an error to silently fix. Do not build environment-switching, manifestation deployment, or the CathedralRoot move until CareBloomOS MVP, a functional UI, one polished realm, and a stable Mini ARK foundation exist first.
