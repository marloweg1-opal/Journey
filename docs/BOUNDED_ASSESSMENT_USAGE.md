# Bounded Metadata Assessment

## User Workflow

In a deployed Navigator, open **Guide -> Filesystem Assessment -> Run** to view
retained evidence. With separately approved scope authority installed, choose
**Start Bounded Assessment**, then **Continue Bounded Assessment** for remaining
work. **Refresh Evidence** retrieves the durable receipt after a disconnect.
Completed assessments do not offer another batch.

The shipped `ASSESSMENT_POLICY` is `None`: new source assessment is disabled.
Browser payloads cannot grant approval or choose scopes, limits or policy stores.
The trusted host integration must bind an exact reviewed scope and an authorizer
that enforces applicable task approval, Gate and pause requirements. The existing
source-hold guard is additionally mandatory; absence of a hold is not authority.
Fixture authorizers must never be used as production approval.

## Evidence and Recovery

The implementation reuses metadata/reparse guards, process locking, the existing
SQLite ledger and placement doctrine matching. No new service, scheduler or
database is created. Assessment tables are initialized only at an authorized start;
status access never initializes configuration or schemas.

Each batch permits 200 entries, five directory attempts, a cooperative two-second
budget and depth 20. Source contents are neither read nor modified. F: and alias
paths are denied before source probing. Source observations and discovered child
work commit together. Completed directories are not rescanned.

After process interruption, an unfinished directory may be retried once if its
identity/mtime signature matches. Observations have unique keys, preventing
duplicate records. A second interruption stops retries. An oversized directory
or a mid-directory time limit retains partial observations and becomes HELD; it
is not retried indefinitely. Other discovered directories can continue.

This is directory-level recovery, not a portable per-entry filesystem cursor.
OS calls can exceed the cooperative time budget. Guards are path based, not
adversarial handle-based race protection. COMPLETE_WITH_GAPS is not full coverage.
Neither COMPLETE nor a stored ACTIVE checkpoint proves current filesystem health
or process liveness. Historical observations are not an atomic snapshot.

Placement reports distinguish path/rule membership from semantic congruence.
Content role, permanence, dependencies and intentional exceptions may remain
unknown. No corrective operation is authorized by these reports.

The legacy content-hash scan remains separate and is labeled with its fixed
300-second timeout. A forced kill can leave partial records and stale running
state; the bounded assessment does not silently repair that historical state.

## Verification

Run the assessment tests with:

```text
python -B -m unittest discover -s tests -p test_bounded_assessment.py -v
```

They exercise source preservation, restart recovery, actual child exit, retry
ceilings, time/count limits, missing/revoked authority, holds, alias rejection,
concurrent locks, schema compatibility and retained receipts.

The rendered disposable demo uses installed Node, Playwright and Brave:

```text
python -B tests/assessment_browser_demo.py NODE_EXE PLAYWRIGHT_MODULE OUTPUT_DIR
```

It starts only a temporary loopback fixture, not Navigator's production main
routine or a Destination worker. It demonstrates Start -> Pending -> Continue ->
Complete -> retained receipt for six synthetic files and seven directories, and
compares fixture source bytes and modification times before/after. Outputs contain
local temporary paths and must remain local, not committed or uploaded.
Brave is launched by executable path; set BRAVE_EXECUTABLE for a nonstandard
installation. No Edge dependency, browser installation or default-browser change
is required. Missing Brave fails explicitly without substituting another browser.

The development working-tree focused suite passed 81 tests. The isolated staged
publication snapshot passed 61 relevant tests (2.537 seconds), inline JavaScript
parsing and the rendered Brave end-to-end demonstration. This smaller publication
suite excludes unrelated unpublished Council/Destination tests. Neither count
claims full-repository verification or live production deployment.

## Deployment and Rollback

Publishing this code is not production deployment or source authorization.
Controlled restart, reliable Council inactivity/worker idle checks, exact source
authority binding and assessment schema deployment require separate approval.
Static HTML can update before a running backend reloads; UI presence does not
establish that the endpoint is deployed.

Rollback only the assessment integration and its tests after review. Preserve
unrelated edits and retained evidence. Do not delete production records as a
rollback step. Local inventories, databases, machine-status logs and generated
screenshots are deliberately excluded from this publication.
