"""The read and planning routes shared by Navigator's daily work."""

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import re

from journey_navigator.conversation import QUOTED, _directive, _family, explicit_intent, validate_prompt
from journey_navigator.links import ProtectedPath


FIND = re.compile(r"^(?:please\s+)?(?:find|locate|search for|show me)\s+(.+?)\s*[.!]?$", re.I)
ORGANIZE = re.compile(r"^(?:please\s+)?(?:organize|organise|group|classify|review)\b", re.I)
INSPECT_REQUEST = re.compile(
    r"^(?:(?:please|(?:can|could|would|will)\s+you(?:\s+please)?)\s+)?"
    r"(?:inspect|scan|examine|(?:take|have)\s+a\s+look\s+(?:at|inside)|look\s+(?:at|inside|through))\s+"
    r"(?:(?:the|my)\s+)?(?:selected|current|approved|this)\s+(?:folder|scope|collection)[?.!]*$", re.I)


def inspection_request(text):
    return bool(INSPECT_REQUEST.fullmatch(QUOTED.sub(" ", text).strip()))


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
    "duplicates": Capability("Audit redundant copies without deleting them", "Retained selected inspection", "Existing Duplicate Patrol resource limits", "Bulk review and recoverable-cleanup preview", False),
    "council": Capability("Request local advisory perspectives", "Per-request local-model consent; excerpt sharing is separate", "At most one call per selected member; no automatic retries", "Attributed advice, gaps and measured usage; never approval", False),
}


def conversation_intent(prompt):
    """Recognize bounded requests without spending inference or widening scope."""
    text = validate_prompt(prompt)
    live = QUOTED.sub(" ", text)
    if re.search(r"\b(?:do not|don['’]t|never|must not|cannot|can['’]t)\s+(?:\w+\s+){0,3}(?:inspect|scan|examine|find|search|organize|organise|retire|consult|convene)\b", live, re.I) or re.match(
            r"^(?:suppose|hypothetically|what if|for example|maybe|should we)\b", live, re.I):
        return "non_directive", ""
    if re.search(r"\b(?:who are you|what is journey|identify yourself|what (?:build|version))\b", text, re.I):
        return "identity", ""
    if re.search(r"\b(?:what (?:can|could) you do|capabilities|what is (?:the )?council)\b", text, re.I) or re.fullmatch(r"(?:please\s+)?help[?.!]*", text, re.I):
        return "capabilities", ""
    if re.search(r"\b(?:permissions?|authority|what (?:are you|am i) allowed|may you)\b", text, re.I):
        return "permissions", ""
    if re.fullmatch(r"(?:please\s+)?(?:show\s+)?(?:the\s+)?(?:current\s+)?(?:status|progress|inspection status|what do you (?:know|remember)|what have you (?:done|learned))[?.!]*", text, re.I):
        return "status", ""
    if inspection_request(text):
        return "inspect", ""
    if re.fullmatch(r"(?:show\s+)?duplicate(?:s)?\s+(?:status|progress)[?.!]?", text, re.I):
        return "duplicate_status", ""
    if re.fullmatch(r"(?:please\s+)?(?:find|check|audit|scan|look for)\s+(?:the\s+)?(?:exact\s+)?duplicates(?:\s+in\s+(?:the\s+)?(?:selected|current|approved|this)\s+(?:folder|scope|collection))?[.!]?", text, re.I):
        return "duplicates", ""
    history = re.fullmatch(r"(?:please\s+)?(?:search|find in|look in)\s+(?:the\s+)?(?:conversation\s+)?history\s+for\s+(.+?)[.!]?", text, re.I)
    if history:
        return "history", history[1].strip(' "“”')
    if re.fullmatch(r"(?:show\s+)?(?:local\s+)?(?:history|import)\s+(?:status|coverage)[?.!]?", text, re.I):
        return "history", ""
    if re.fullmatch(r"(?:show|check)\s+(?:local\s+)?models[?.!]?", text, re.I):
        return "models", ""
    if re.match(r"^(?:please\s+)?(?:ask|consult|convene|use|have)\s+(?:the\s+)?(?:full\s+)?council\b|^council\s+review\b", text, re.I):
        return "council", ""
    member = re.match(r"^(?:please\s+)?(?:ask|consult)\s+(Qwen|Phi|Gemma)\b", text, re.I)
    if member:
        return "perspective", member[1].title()
    if re.match(r"^(?:please\s+)?(?:advise|summari[sz]e|suggest|recommend)\b", text, re.I):
        return "advice", "Qwen"
    found = FIND.fullmatch(text)
    if found:
        return "find", found[1].strip(' "“”')
    if explicit_intent(text):
        return "retire", ""
    if ORGANIZE.match(text):
        return "organize", ""
    if re.search(r"\b(?:delete|erase|move|rename|overwrite|execute|install|approve|grant|unattended)\b", text, re.I):
        return "mutation", ""
    return "unknown", ""


class Capabilities:
    def __init__(self, patrol, *, app=None):
        self.patrol = patrol
        self.app = app if app is not None else patrol.app

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

    def describe(self, job, info):
        """Runtime facts from the existing owners, never from a model's memory."""
        active, summary, permissions, history = False, None, None, None
        if job:
            self.app.job(job)  # Unknown identifiers are errors, not empty scopes.
            try:
                summary = self.app.summary(job)
                permissions = self.app.permissions(job)
                visible = set(self.app._visible(self.app.job(job)))
                permissions["scopes"] = [dict(scope) | {
                    "recorded_inspect": bool(scope["inspect"]), "recorded_propose": bool(scope["propose"]),
                    "inspect": int(bool(scope["inspect"]) and scope["path"] in visible),
                    "propose": int(bool(scope["propose"]) and scope["path"] in visible),
                    "effective_inspect": bool(scope["inspect"]) and scope["path"] in visible,
                    "effective_propose": bool(scope["propose"]) and scope["path"] in visible,
                } for scope in permissions["scopes"]]
                active = True
            except ProtectedPath:
                permissions = {"scopes": [], "reason": "Inspection permission is inactive or the source changed."}
            if active and self.app.project_registry.profile(job):
                history = self.app.history.read_coverage(job)
        authority = {"inspection": "selected_scope_only" if active else "not_granted",
                     "source_mutation_via_conversation": False,
                     "approval": "Separate exact reviewed batch and fresh Windows-account approval; existing holds still apply.",
                     "background": "Conversation does not enable background work or expand permissions."}
        if permissions is not None:
            authority["scopes"] = permissions["scopes"]
        capabilities = []
        for name, contract in CONTRACTS.items():
            if name == "guided":
                availability = "separate_guarded_workflow; readiness_not_verified"
            elif name == "council":
                availability = "local_provider_registered; model_health_not_checked"
            elif not active:
                availability = "requires_active_inspection"
            elif name in ("history", "reconcile") and not self.app.project_registry.profile(job):
                availability = "requires_project_profile"
            elif name in ("history", "duplicates") and not self.app.retains:
                availability = "requires_retained_checkpoint"
            elif name == "retire":
                availability = "requires_saved_destination_and_review"
            else:
                availability = "available"
            capabilities.append({"id": name, **asdict(contract), "availability": availability})
        knowledge = {"source": "This runtime's selected inspection and explicitly imported local history.",
                     "retained_checkpoint": bool(self.app.retains), "conversation_transcript": "not_saved",
                     "history_state": "indexed" if history and history["unique_messages"] else "no_indexed_history",
                     "history_files": history["indexed_files"] if history else 0,
                     "history_messages": history["unique_messages"] if history else 0,
                     "truncated_history_records": history["text_index"]["truncated_records"] if history else 0,
                     "project_profile": bool(active and self.app.project_registry.profile(job)),
                     "work_archives_are_not_automatically_accessible": True}
        return {"identity": {"name": "Journey", "purpose": "Local, human-governed computer stewardship",
                             "runtime": {k: info.get(k) for k in ("application", "version", "commit", "build", "installation", "session")}},
                "capabilities": capabilities, "authority": authority, "knowledge": knowledge, "summary": summary}

    def model_context(self, job, prompt, info, *, share_evidence=False):
        """Share scope metadata by default; retained content needs separate consent."""
        state = self.describe(job, info)
        if job:
            # This is an observation boundary, including for a metadata consultation.
            self.app._visible(self.app.job(job))
        authority = {k: v for k, v in state["authority"].items() if k != "scopes"}
        evidence = [{"id": "authority", "kind": "runtime_authority", "value": authority},
                    {"id": "knowledge", "kind": "runtime_coverage", "value": state["knowledge"]}]
        if state["summary"]:
            counts = {k: v for k, v in state["summary"].items() if k in (
                "files", "folders", "analyzed", "pending", "pending_folders", "reused", "skipped", "text_count")}
            evidence.append({"id": "inventory", "kind": "inspection_counts", "value": counts})
        if share_evidence and job:
            current = self.app.job(job)
            visible = self.app._visible(current)
            marks = ",".join("?" for _ in visible)
            rows = self.app.conn.execute(f"SELECT id,path,status,digest FROM files WHERE job=? AND epoch=? AND scope IN ({marks}) ORDER BY id LIMIT 6",
                                         (job, current["epoch"], *visible)).fetchall()
            for row in rows:
                try:
                    self.app.policy.check_image(Path(row["path"]), retain=self.app.retains)
                except ProtectedPath:
                    continue
                evidence.append({"id": f"asset-{row['id']}", "kind": "inspected_asset",
                                 "value": {"filename": Path(row["path"]).name, "status": row["status"], "sha256": row["digest"]}})
            intent, term = conversation_intent(prompt)
            query = term if intent in ("history", "find") else ""
            if not query:
                quoted = re.findall(r'["“]([^"”\n]{1,160})["”]', prompt)
                about = re.search(r"\babout\s+(.{1,160}?)[?.!]*$", prompt, re.I)
                query = quoted[0] if len(quoted) == 1 else about[1].strip(' "“”') if about else ""
            if query and state["knowledge"]["project_profile"]:
                for index, row in enumerate(self.app.history.text_search(job, query, limit=3)):
                    evidence.append({"id": f"history-{index}", "kind": "imported_history_excerpt",
                                     "value": {k: row[k] for k in ("conversation", "message", "role", "authored", "imported", "name", "excerpt", "truncated")}})
        return {"identity": state["identity"], "capabilities": state["capabilities"],
                "authority": authority, "knowledge": state["knowledge"], "evidence": evidence}

    def conversation_binding(self, job, prompt, info, *, share_evidence=False):
        context = self.model_context(job, prompt, info, share_evidence=share_evidence)
        revision = (self.patrol.signature(job) if job and self.app is self.patrol.app else
                    [self.app.job(job)["epoch"], self.app.job(job)["rule"]] if job else None)
        value = [context, revision,
                 self.app.permissions(job) if job else None,
                 self.app.conn.execute("SELECT max(id) FROM reviews WHERE job=?", (job,)).fetchone()[0] if job else None]
        return sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest(), context

    @staticmethod
    def _response(intent, message, *, state="COMPLETE", **values):
        return {"state": state, "intent": intent, "message": message, "reason": message,
                "metrics": {"level": 0, "calls": 0, "retries": 0, "prompt_eval_count": None, "eval_count": None}, **values}

    def converse(self, job, prompt, info, *, destination=None, provider=None, read_references=False):
        instruction = validate_prompt(prompt)
        intent, term = conversation_intent(instruction)
        if intent in ("identity", "capabilities", "permissions", "status"):
            described = self.describe(job, info)
            message = {"identity": "I am Journey, your local computer stewardship application. This reply describes the running candidate.",
                       "capabilities": "These are the registered runtime routes and their current prerequisites. Code presence does not establish live Windows readiness.",
                       "permissions": "Observation and physical changes have separate authority. Conversation cannot grant permissions or authorize a batch.",
                       "status": "This is the current saved inspection and imported-history coverage. I do not retain a conversation transcript."}[intent]
            fields = {"identity": ("identity",), "capabilities": ("capabilities", "authority"),
                      "permissions": ("authority",), "status": ("summary", "knowledge", "authority")}[intent]
            return self._response(intent, message, **{key: described[key] for key in fields})
        if intent == "mutation":
            return self._response(intent, "Source-file changes and approvals require the existing exact-batch review and account-verification workflow. This conversation has not changed files or permissions.", state="REVIEW_REQUIRED")
        if intent == "non_directive":
            return self._response(intent, "This instruction is negated or hypothetical. No inspection or plan was started. State an affirmative request when you want work to proceed.", state="NEEDS_CLARIFICATION")
        if intent in ("council", "perspective", "advice", "models"):
            if job:
                self.app._visible(self.app.job(job))
            return self._response(intent, "Allow local AI for this request to consult the configured local provider. Evidence excerpts require their separate sharing choice.",
                                  state="LOCAL_MODEL_CONSENT_REQUIRED", _model=intent,
                                  _members=[term] if intent == "perspective" else (["Qwen"] if intent == "advice" else None))
        if intent == "unknown" and provider is None:
            return self._response(intent, "I could not match this instruction to a bounded capability. Allow local interpretation, or ask for an inspection, Find, history search, duplicate audit or plan.",
                                  state="NEEDS_CLARIFICATION", _model="interpret")
        if intent == "unknown" and provider:
            if provider.get("state") != "INTERPRETED":
                return self._response(intent, provider.get("reason", "Local interpretation was unavailable."), state="LOCAL_MODEL_UNAVAILABLE", provider=provider)
            intent = provider.get("intent")
            if intent not in ("find", "inspect", "status", "history", "capabilities", "permissions", "organize", "retire"):
                return self._response("unknown", "The local model did not establish a supported bounded request.", state="NEEDS_CLARIFICATION", provider=provider)
            term = provider.get("term", "")
            if intent in ("find", "history") and term and (not isinstance(term, str) or term.casefold() not in instruction.casefold()):
                return self._response("unknown", "The proposed search term was absent from your instruction.", state="NEEDS_CLARIFICATION")
            if intent == "inspect" and not inspection_request(instruction):
                return self._response(intent, "Choose and authorize the folder in Inspect first, then ask to inspect the selected folder.", state="NEEDS_SCOPE")
            if intent == "retire" and not (explicit_intent(instruction) or
                                           (_directive(instruction) and _family(instruction, provider.get("family")))):
                return self._response(intent, "An affirmative retirement instruction with a literal family is required before preparing a review.", state="NEEDS_CLARIFICATION")
            if intent in ("status", "capabilities", "permissions"):
                return self._response(intent, "Here are the current runtime facts.", **self.describe(job, info))
        if not job:
            return self._response(intent, "Select and authorize a folder in Inspect first. This request does not grant access to another location.", state="NEEDS_SCOPE")
        summary = self.app.summary(job)  # Revalidates active scope, link identity and holds.
        evidence = [{"id": "inspection", "kind": "scoped_inspection", "value": {"job": job, "root": summary["root"], "files": summary["files"]}}]
        if intent == "inspect":
            result = self.inspect(job)
            pending = bool(result["pending"] or result["pending_folders"])
            return self._response(intent, "Completed one bounded inspection step. More work remains; resume Inspect or Patrol." if pending else "The selected inspection has completed its current inventory and analysis queue.",
                                  state="IN_PROGRESS" if pending else "COMPLETE", summary=result, evidence=evidence)
        if intent == "find":
            results = self.find(job, term)
            return self._response(intent, f"Found {len(results)} matching files or structured references in the selected inspection. This is a checkpoint lookup, not an unbounded live-drive scan.", results=results, evidence=evidence)
        if intent == "history":
            if not self.app.project_registry.profile(job):
                return self._response(intent, "No project profile is active for local historical evidence. Work's access to archives does not import them into Journey.", state="HISTORY_NOT_CONFIGURED", evidence=evidence)
            status = self.app.history.read_coverage(job)
            results = self.app.history.text_search(job, term) if term else []
            return self._response(intent, f"Journey has {status['unique_messages']} readable indexed messages in this project. Conversation dates and import dates are reported separately.", history=status, results=results, evidence=evidence)
        if intent == "duplicates":
            if not self.app.retains:
                return self._response(intent, "Keep a local checkpoint before using Duplicate Patrol.", state="NEEDS_CHECKPOINT")
            result = self.patrol.duplicates.queue(job, read_references)
            self.patrol.wake.set()
            return self._response(intent, "Queued the existing bounded duplicate audit. No cleanup permission was granted and no source file was deleted. Open Duplicate Patrol for its bulk preview.", state="IN_PROGRESS", audit=result, evidence=evidence)
        if intent == "duplicate_status":
            if not self.app.retains:
                return self._response(intent, "Keep a local checkpoint before using Duplicate Patrol.", state="NEEDS_CHECKPOINT")
            return self._response(intent, "This is the current Duplicate Patrol result and any remaining audit work.", audit=self.patrol.duplicates.status(job), evidence=evidence)
        if intent in ("organize", "retire"):
            if self.app is not self.patrol.app:
                return self._response(intent, "Keep a local checkpoint before creating a Destination and reviewable plan.", state="NEEDS_CHECKPOINT")
            if not destination:
                return self._response(intent, "Save or open a Destination for this inspection to prepare its existing reviewable plan.", state="NEEDS_DESTINATION", evidence=evidence)
            row = self.patrol.row(destination)
            if row["job"] != job:
                raise ProtectedPath("The Destination belongs to another inspection. Select its scope explicitly.")
            adapted = None
            if provider:
                adapted = {"state": "CANDIDATE", "intent": intent, "term": term,
                           "family": provider.get("family") if intent == "retire" else None}
            result = self.plan(destination, instruction, provider=adapted, read_references=read_references)
            return result | {"message": result["reason"], "evidence": evidence,
                             "metrics": {"level": 0, "calls": 0, "retries": 0}}
        return self._response("unknown", "No supported action was established. The model cannot add capabilities or authority by proposing them.", state="NEEDS_CLARIFICATION")

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
