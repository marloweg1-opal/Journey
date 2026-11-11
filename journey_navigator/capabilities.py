"""The read and planning routes shared by Navigator's daily work."""

from dataclasses import dataclass
from pathlib import Path
import re

from journey_navigator.conversation import explicit_intent, validate_prompt


FIND = re.compile(r"^(?:please\s+)?(?:find|locate|search for|show me)\s+(.+?)\s*[.!]?$", re.I)
ORGANIZE = re.compile(r"^(?:please\s+)?(?:organize|organise|group|classify|review)\b", re.I)


@dataclass(frozen=True)
class Capability:
    purpose: str
    authority: str
    budget: str
    result: str
    patrol: bool


CONTRACTS = {
    "inventory": Capability("Inventory and observe selected assets", "Selected inspection scope", "Existing per-cycle and file limits", "Inventory, local OCR and fingerprints", True),
    "history": Capability("Index a reviewed local archive selection", "Reference selection and local retention", "One bounded conversation slice", "Attributed evidence and coverage", True),
    "reconcile": Capability("Match local evidence and source observations", "Retained inspection and project namespace", "Current root inventory", "Candidate matches, gaps and conflicts", True),
    "find": Capability("Look up files and historical references", "Visible inspection scope", "50 local paths and 18 history records", "Scoped source references", False),
    "retire": Capability("Review a design family and its dependencies", "Inspection and optional scoped reference reading", "Bounded family and reference scan", "Grouped retirement proposal", False),
    "guided": Capability("Execute and verify an exact reviewed batch", "Fresh Windows-account batch approval", "One existing journaled operation per step", "Verified result and reversal receipt", False),
}


class Capabilities:
    def __init__(self, patrol):
        self.patrol = patrol
        self.app = patrol.app

    def inspect(self, job):
        return self.app.step(job)

    def history_step(self):
        return self.app.history.advance()

    def reconcile(self, job):
        return self.app.history.reconcile(job)

    def find(self, job, query):
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Enter a search term for this inspection.")
        return self.app.search(job, query.strip()[:200])

    def plan(self, destination, prompt, *, provider=None, read_references=False):
        row = self.patrol.row(destination)
        instruction = validate_prompt(prompt)
        provider_state = provider["state"] if provider else "DISABLED"
        family = explicit_intent(instruction)
        if family or (provider and provider.get("family")):
            return self.patrol.stewardship.plan(destination, instruction, provider=provider, read_references=read_references) | {"intent": "retire"}
        found = FIND.fullmatch(instruction)
        if found or (provider and provider.get("intent") == "find"):
            term = found[1].strip(' "“”') if found else provider["term"]
            return {"state": "COMPLETE", "intent": "find", "provider": provider_state,
                    "reason": "Searched the current inspection and its indexed local references.",
                    "results": self.find(row["job"], term)}
        if ORGANIZE.match(instruction) or (provider and provider.get("intent") == "organize"):
            root = Path(self.app.job(row["job"])["root"])
            return {"state": "AWAITING_REVIEW", "intent": "organize", "provider": provider_state,
                    "reason": "Review the plan and start Patrol when ready.", "scope": str(root),
                    "steps": [CONTRACTS[name].purpose for name in ("inventory", "reconcile")]}
        return {"state": "NEEDS_HUMAN_DECISION", "intent": "unknown", "provider": provider_state,
                "reason": "Choose a supported goal. Ask Journey to organize the selected folder, find a term, or retire one named design."}
