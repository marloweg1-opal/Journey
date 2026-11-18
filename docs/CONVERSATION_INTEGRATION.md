# Talk to Journey in the isolated candidate

Talk now connects to the same scope, inspection, search, history and planning controls as the rest of Navigator. It is part of Navigator, not another application. Source files cannot be changed or approved through this conversation route.

## Try the portable demonstration

1. Extract the complete Windows package into a new folder. Leave the existing Journey installation alone. Do not run Setup Journey for this trial.
2. Open **Start isolated conversation demo.cmd**. It uses a separate **Conversation checkpoint** beside the extracted package. It does not replace services or change Windows configuration.
3. Open **Talk** and ask **Who are you?** Then ask **What can you do?** The response identifies this running candidate and separates registered capabilities, current prerequisites and permission. A model is not needed.
4. In **Inspect**, select the package's **Conversation demonstration / Collection copies**. Keep a local checkpoint. Inspect this disposable collection.
5. Return to **Talk**. Ask **Inspect the selected folder.** One bounded step runs. If it reports remaining work, resume Inspect or Patrol. Ask **Find Moonstone** to see actual matches from this inspection.
6. In Inspect's project controls, activate **Conversation demonstration / CareBloom-fixture-pack.json**. Preview and import **Conversation demonstration / Local exports** using the existing history controls. The two overlapping exports are invented examples, not project canon.
7. Ask **Search history for CareRail**. The response now contains imported source references, conversation timestamps and separate import timestamps. Work's access to archives does not load them into Journey; this step demonstrates Journey's own import.
8. Optionally allow local AI and ask **Show local models**. This checks the existing local Ollama service without downloading or loading a model. Missing models are reported. No cloud provider is configured by this workflow.
9. To test local advice, ask **Ask the Council to review this inspection.** Enable **Allow local AI when needed**. The configured Qwen, Phi and Gemma are consulted independently, sequentially, at most once each. Missing, failed, abstaining and unconsulted members stay distinguishable. Advice cannot authorize operations.
10. Enable **Include scoped evidence excerpts** when you want to share retained filenames and relevant indexed excerpts on that request. With excerpts off, the provider receives your message and the current capability and coverage information. The consent boxes clear when you send. Ollama manages its own logging settings.
11. Close through **Manage / Close Navigator**. Reopening this same demonstration reuses its checkpoint. Conversation transcripts are not saved; retained inspection and imported evidence provide the supported continuity.

Success means the displayed build matches the package, deterministic requests return actual scope results without model calls, imported history appears only after import, source files remain unchanged, and local advice clearly reports each member's real status. Real Council inference requires the existing local service and the configured model tags. Hosted fixtures do not establish model quality or successful HEXSEED deployment.

## What is connected

| Request | Existing owner | Boundary |
| --- | --- | --- |
| Identity, capability, permissions, status | Navigator build and Capabilities contracts | Runtime facts, no model needed |
| Inspect selected folder | Workbench.step | Existing bounded read guard and queues |
| Find a term | Workbench.search | Current inspection checkpoint and structured references |
| Search history for a term | ArchiveHistory.text_search | Imported active-project evidence only |
| Find duplicates / duplicate status | Duplicate Patrol | Audit only, no cleanup authorization |
| Organize or retire a named design | Existing Destination and stewardship planner | Reviewable plan; separate Begin/review/approval controls |
| Local interpretation or advice | Existing loopback provider module | Explicit opt-in, structured validated output, no model tools |

Physical-change readiness is reported as unverified. Existing holds, approval, receipts, recovery and kill-switch controls remain with their existing owners. Conversation cannot mint approvals, accept paths from model output, turn agreement into truth or enable unattended execution.

The earlier private Council implementation was reported in historical conversations but was not present in the published code reviewed for this increment. This candidate adds a bounded advisory route in the existing provider module. It does not claim that the unpublished local implementation was restored or that it is running on the operator's computer.

## Maximum Coherence per Token

Routine inventory, search and status use existing software even when local interpretation is allowed. An unrecognized request can use one Qwen interpretation. **Ask Qwen**, **Ask Phi** or **Ask Gemma** selects one member. **Ask the Council** requests one independent contribution from each available member.

**Suggest** starts with Qwen. A finding or abstention ends the consultation. If evidence is missing, Journey identifies what can be checked in the selected inspection or imported history. Journey can ask Phi for one independent view when Qwen raises an objection and the host can match its quote to a shared history excerpt or its fingerprint to a shared, analyzed asset. Matching a citation establishes which source was used. You still judge whether the conclusion follows. Authority decisions stay with the existing human review. The Council assessment shows the reason Journey continued or stopped. Every generation rechecks the selected context, shares the same permitted input and counts against the request budget.

Qwen is configured as `qwen3:4b`, Phi as `phi4-mini` (including its explicit `:latest` tag), and Gemma as `gemma3:4b`. These are checked against the current local inventory and generation response. They are not assertions of installed availability. Members have no permanent invented personas. Each sees the same grounded request, rather than another member's conclusion.

Responses expose actual generation-call counts, model identities and returned Ollama usage when available. Missing token measurements remain null. Lower call counts in fixtures demonstrate routing overhead only; they are not measured live token or cost savings. Broad adaptive routing beyond the bounded supported tasks, quality calibration and comparison with the unpublished local Council remain future validation work.

## Read-only local diagnostic

After opening the isolated candidate, run **Verify Journey conversation.ps1** from Windows PowerShell if a diagnostic report is needed. It checks the package's selected source hashes, authenticated running build/identity/capability routes and local model inventory. It performs no collection scan, model generation, install, restart or permission change. It prints labeled progress and a final status and copies a redacted report to the clipboard. Session/control tokens are never included.

`FINISHED SUCCESS` means the diagnostic completed its limited checks. Full acceptance through the intended HEXSEED interface, including real local model inference, remains `LOCAL_RUNTIME_ACCEPTANCE_PENDING` until demonstrated.

## Reproduce development acceptance

```text
python -B -m unittest discover -s tests -p test_conversation_providers.py -v
python -B -m unittest discover -s tests -p test_conversation_integration.py -v
python -B -m unittest discover -s tests -p test_conversation_boundaries.py -v
python -B -m tools.demo_conversation_integration
```

Use the repository's supported Pillow dependency. The provider tests use an explicit disposable Ollama-compatible HTTP fixture, not real model inference. The integrated test runs the authenticated Navigator handler, real local inspection/history components and disposable source files. Existing scope, provenance, native approval and recovery regressions must also pass. Hosted Windows package checks remain separate from the operator's actual computer.
