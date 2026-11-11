# A guided collection workflow

This development candidate provides one path through the existing Navigator: collection selection, inspection, project and historical context, interpretation review, virtual organization, and a saved reviewable preview. It does not install itself on HEXSEED or grant production authority.

## Disposable demonstration

From this development checkout, with the existing Pillow dependency available:

```powershell
$demo = Join-Path $env:TEMP ('Journey-CareBloom-' + [guid]::NewGuid().ToString('N'))
python -B -m tools.demo_carebloom_collection $demo
python -B -m journey_navigator --data-dir (Join-Path $demo 'Review checkpoint')
```

The demonstration generates ten schematic image copies, a project pack and two overlapping exports. The images and conversations are invented test material, not original artwork or new project canon. The fixture profile intentionally has no approved filename rules.

1. Select **Collection copies** in Inspect. Enable **Keep a local checkpoint** and **Suggest names and draft a plan** before selecting it. The permission choices remain explicit.
2. Follow **Collection workflow → Add project context**. Preview **CareBloom-fixture-pack.json** and activate CareBloomOS for this scope.
3. Follow **Add historical context**. Preview **Local exports** and choose **Import these reviewed exports**. Activating the pack alone leaves Journey's archive index empty. The two exports produce three distinct messages. Monitoring remains off.
4. Follow **Review interpretations**. Beat and Melody gain Musicstone relationship evidence; `render_17.png` gains a CareRail purpose with a cited message. The compound Heart/Corestone crystal keeps an open identity. Touchstone and armory purposes remain distinct. No filename grammar is fabricated. Record a correction only when warranted.
5. Follow **Preview organization**. Describe why the collection matters, save the Destination and choose **Begin or resume Patrol**. Review the virtual groups, unresolved assets, coverage and work report. A completed activity report leaves the user's success judgment open.
6. Choose **Save organization preview**. The existing review exporter saves source-linked interpretations and proposed memberships in Journey's review checkpoint. The interface reports its exact path. This writes the review artifact, not the collection. Physical moves, renames and their approval workflow remain separate.
7. Close Navigator through Manage, reopen it against the same checkpoint and open the saved inspection. Project context, imported history and saved decisions remain available. Review the work against the original success criterion.

Historical context is optional. **Continue with current evidence** lets the operator review what is already known without granting another import. This choice does not imply that the project has been fully understood.

## Acceptance and limits

`tests/test_carebloom_workflow.py` exercises authenticated application requests through the same importer and Patrol. `tests/carebloom_workflow_browser.py` drives the actual visible sequence against the packaged Windows runtime. Both check source SHA-256 hashes and modification times, unresolved identity, source attribution, naming holds and a saved ten-image preview. The browser additionally checks saved inspection reopening. No physical batch is necessary.

The large inspection browser regression separately exercises more than 10,000 files, pause, closure, reopening, cached observations, authorization boundaries and corrections. Progress and checkpoint diagnostics distinguish a slow or stopped run from a successful complete scan. A failing run remains a release blocker until characterized.

The [component status matrix](COMPONENT_STATUS.md) describes the current local-model adapter and future agent scope. The [accessibility disclosure](ACCESSIBILITY_AND_PARTICIPATION.md) retains task-based verification requirements; keyboard-accessible controls alone do not prove full assistive-technology usability.

This demonstration is not live acceptance on HEXSEED. Real collection access, installation, configuration changes, primary-branch merges and physical operations require separate authorization.
