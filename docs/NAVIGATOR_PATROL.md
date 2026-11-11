# Journey Navigator 0.6 Project Stewardship

Navigator can reconcile source-linked project references with a selected
inventory. A reviewed profile supplies a convention for a specific subject,
asset type and extension. A Guided rename requires the exact current preview,
including its creation-date evidence. Original Unicode spelling, extension case
and verified path history are retained in the image details and plan export.

| Capability | 0.5 | 0.6 candidate |
| --- | --- | --- |
| Scoped inspection, local image text, checkpoint, and Guided receipts | Operational | Same workflow with separate unreliable and timed-out text states |
| Project naming profiles | Explicit image rules using day and month | Explicit dated or undated patterns with project-specific field order |
| Naming evidence across subjects and asset families | Imported candidate records | Scoped naming audit with provenance, conflicts, open fields, and observed file examples |
| Conversational retirement | Structured controls only | Bounded retirement planning in Review, with an optional local interpreter |
| Dependency checking for retirement | Account review and registered protections | Adds scoped reference evidence and rechecks it before an archive move |
| Production deployment, broad conversational execution, or deletion | Unavailable | Unavailable |

## Open and upgrade

Extract the complete Windows x64 package. Open **Setup Journey.exe** to install
for the current Windows account. Setup verifies the packaged files, stages the
version under the user's local Programs folder, and creates the **Journey
Navigator Candidate** shortcut on the desktop and Start menu. Existing candidate
versions remain available in the managed install folder. **Journey Navigator.exe**
can also run from the extracted folder.

The header identifies the actual version, commit, content build, installation
location and service identity. A compatible second launch reopens the existing
service. A changed build offers an authenticated handoff and waits for the
previous service to close at its checkpoint. An earlier release with no verified
handoff protocol needs **Manage → Close Navigator**, followed by reopening the
update. The application never removes a live lock or terminates another program.

Saved work stays under `%LOCALAPPDATA%\Journey\Navigator Inspection`, separately
from application files. The production installation has its own lifecycle and
source holds. Setup does not replace its files or services.

## Work toward a Destination

1. In **Inspect**, choose the existing collection or a local folder shortcut.
   Choose retention to save the objective, analysis and corrections. Proposal
   permission is separate. External link targets require a destination review.
2. Open **Destination**, enter the intended outcome, why it matters, success
   criteria and foreground cycle budgets, then choose **Save Destination**.
3. In **Patrol**, begin the work. The worker inventories supported content,
   reads local image text, interprets evidence and builds virtual memberships.
   The state, scope, active authority, progress and remaining work stay visible.
4. In **Review**, browse collections and grouped uncertainties. Select the
   images a correction applies to. Record one identity or purpose decision for
   that selection. New assessment uses the scoped correction without repeating
   unchanged OCR work. A preliminary name and a physical operation remain
   distinct records.
5. Prepare a folder creation, a within-scope move that keeps the exact
   filename, or select eligible naming proposals for an exact rename review.
   The batch lists original and destination paths, operation types and its
   binding before any source change.
6. Choose **Authorize exact batch with my Windows account**. The native
   review includes the dependency disposition you are confirming for these
   exact sources. Windows verifies the current account using its sign-in
   password. The backend receives the account identifier and batch binding.
   Credential material remains in the native Windows component and is cleared
   after verification. Cancel when a dependency or intended change is unclear.
7. Patrol revalidates each operation, uses the existing executor and journal,
   verifies the resulting identity, and records the receipt. It then refreshes
   its inventory and continues eligible work. An approved batch runs before
   remaining unrelated indexing, within the foreground time limit. Original paths and confirmed
   context remain traceable after a move. Approved batches expire after ten
   minutes and require review again after a restart.
8. **Review** shows operation history and offers an exact, account-approved
   reversal for verified file moves. A new occupant or changed file blocks a
   reversal. A newly created folder is retained when folder removal would need
   separate review.

The saved purpose and success criterion remain available in **Patrol**. After
reviewing the result, **This meets my success criterion** records your outcome
assessment for that result. Later corrections, source refreshes or operation
receipts invalidate that assessment. This control grants no physical authority.

Pause stops at the next bounded checkpoint. Closing the Navigator window ends
its foreground work through the local session lifecycle. **Manage → Close
Navigator** explicitly closes the service. A reopened service restores saved
objectives and tasks in a paused state. Ready physical approvals require fresh
review after restart.

## Build a project registry

1. In **Inspect**, select the project's folder and turn on **Keep a local
   checkpoint**. Turn on **Suggest names and draft a plan** to preview names.
2. Open **Project registry and validated naming**, select the project profile
   JSON, review the displayed examples, and choose **Use this profile in this
   folder**. The profile is attached to that inspection's original scope.
3. To add evidence, give Navigator the full local path to a selected ChatGPT
   conversation export, normalized conversation, or Asset Pipeline
   `asset-index.json`. Choose **Import selected evidence file**. Imports
   retain matching structured references with message or creation-record IDs.
   Historical statements enter as review candidates. The original JSON is
   read in place and its paths are never followed. Importing the same file
   again is safe.
4. Review candidate matches, dates, and relationships. A name match alone is
   a candidate. Named references can remain open even when the archive
   supplies no literal filename. A reviewed supersession is separate from whether the
   old artwork was located in this scope. **Image details** shows the full
   creation date and its source, any competing evidence, the filesystem
   modification time, and any verified rename or move history.
5. An eligible preview uses a confirmed subject and purpose and a full date
   from explicit embedded metadata or operator-confirmed evidence. Open
   **Review** in a saved Destination to prepare the exact batch. The name
   uses `DD_MM`; the registry retains `YYYY-MM-DD`. If the date is missing,
   confirm it for that image from its source. An unresolved date, unsupported
   asset class, version token that would be lost, or occupied destination
   holds the rename.

Profiles use the `journey-project-naming-1` format with a project label,
search signals, and rules. Each rule specifies `subject`, `purpose`,
`prefix`, `extension`, `date_order`, an attributed `source`, and an
`example` containing a full `date` and exact `filename`. The example must
round-trip through the rule. Trial formats and historical evidence cannot
activate a profile. Deactivate a profile in Inspect to withdraw its naming
rules. Forget the retained inspection to clear its registry evidence.

### Audit the naming grammar

In **Inspect → Naming coverage and proof**, load a scoped naming audit JSON.
The audit groups evidence by subject and asset family. Open a row to see the
sources for its marker, tag, field order, date, extension, variation and version.
An active rule, an archive filename reference, a direct-file sample and a
verified current filename are distinct. A filename date is observed text.
The asset's original creation date requires independent evidence.

The audited project must match the active profile. An audit can also be loaded
without an active naming profile. **Naming coverage and proof** never installs
a naming rule. A new profile may use the `journey-project-naming-2` format with
a literal stem pattern and an optional `{date}` field. The allowed date layouts
are day and month, full year-first date, and undated. Every executable rule
still needs its own scope, source, extension, and exact example. An evidence-only
profile may carry zero rules. A source version or variation with no preservation
rule blocks a proposed rename.

### Review a retirement

1. Inspect the project and open a saved **Destination → Review**. Open
   **Talk to Journey about retirement** and enter one instruction naming the
   design family. A quoted family makes the intended scope clear.
2. **Interpret this instruction with local Qwen3** sends only that live prompt
   to the existing Ollama service at loopback. It returns a candidate family
   phrase. Navigator keeps the source inventory, history, paths, and execution
   authority on its side of the interface. Explicit retirement instructions
   also work with the built-in parser. Draft instructions stay in the session.
3. Optionally enable **Read scoped documentation and configuration references**.
   Review candidate files, exact copies at other paths, historical records,
   existing protections, and dependency evidence. A limited or empty search
   leaves external dependencies open.
4. Select the assets, enter the reason and any known replacement, and choose
   **Record selected retirements**. The scoped registry records the decision,
   original path, fingerprint, and references. Existing historical documents
   and unselected copies remain individually traceable.
5. To move selected retired assets, choose an existing archive folder in
   the same authorized scope and prepare an exact batch. Windows account
   approval, fresh dependency checks, journal and receipt-based reversal
   use the existing Guided workflow. Incomplete dependency coverage, a
   current configuration reference, or a changed file holds the move.

The retirement planner routes questions through current scope inventory,
registry provenance, registered protections and optional reference reading,
then hands an exact reviewed proposal to Guided. Each stage reports its
own outcome. Its task set is limited to retirement review.

## Scope, authority and recovery

Inspection is read-only. Internal indexes, corrections and collections use the
scope's retention permission. Physical source work uses a separately reviewed
batch with native account attribution. A known dependency, protected path,
source hold, revoked scope, occupied destination, changed source or kill switch
blocks the affected operation. An empty reference search supplies no dependency
clearance. The current Guided pathway supports folder creation, same-volume
moves that preserve filenames, and validated same-folder renames inside the
original approved scope. External linked scopes support inspection. Delegated
execution and source deletion are excluded.

The worker stops when there is no eligible work, a cycle budget is exhausted,
or a safe pause is requested. Coverage gaps, unresolved meaning and queued
approvals remain visible separately from successful operations. Failed actions
retain their journal state and require review. A blocked action does not become
permission to alter its target or expand the scope.

Before an additive inspection migration, Journey saves and checks an inspection
snapshot. **Manage** can restore that snapshot while preserving the current
action history. Restoration restarts the application and makes scope access
inactive until reselection. Forgetting retained observations clears matching
Patrol derivatives and old inspection recovery snapshots. Exported plans are
separate copies. Minimal action receipts remain available for safe recovery.

## Acceptance evidence and participation

The Windows workflow builds the package and tests the normal EXE launch,
compatible reopening, authenticated shutdown, lock release, local OCR and
source boundaries. The operational browser test uses generated artwork and a
clearly declared automated approval actor to exercise the real filesystem
executor, journal, verification and reversal. That actor is defined only in the
tests and is excluded from the shipped package. The package exposes no HTTP
flag, environment option or command-line switch that supplies human approval.
Native credential confirmation by the owner's Windows account is a distinct
real-world acceptance step.

The interface keeps text labels, keyboard controls and status announcements.
Screen-reader task completion and nonvisual understanding of unfamiliar,
unlabeled artwork require direct usability evaluation. OCR uses English data
and can miss stylized, rotated, tiny or densely arranged text. Inspection
continues with filename and pixel evidence when text reading is unavailable.
The boundaries of this program are not the boundaries of human possibility.
