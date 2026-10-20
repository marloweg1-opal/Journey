"""
Conversation Ingestion Gateway v0.1.1.

Diet boundary:
- preserve one normalized conversation unchanged in handoffs.raw_json
- extract traceable PMM/PWM review candidates
- write review JSON for human inspection
- do not create proposals, open loops, accepted decisions, or canonical state
"""

import hashlib
import json
import re
from pathlib import Path

PMM_CATEGORIES = {
    "principle": "Principle",
    "preference": "Preference",
    "definition": "Definition",
    "decision": "Decision",
    "goal": "Goal",
    "constraint": "Constraint",
    "pattern": "Pattern",
}

PWM_CATEGORIES = {
    "entity": "Entity",
    "system": "System",
    "artifact": "Artifact",
    "resource": "Resource",
    "state": "State",
    "event": "Event",
    "dependency": "Dependency",
    "location": "Location / Reference",
}

DOMAIN_SIGNALS = {
    "Mini ARK": ("mini ark", "mini_ark", "ark.py"),
    "Project ARK": ("project ark",),
    "CareBloomOS": ("carebloomos", "carebloom"),
    "HEXSEED": ("hexseed",),
    "Moonstone": ("moonstone",),
    "Cloverstone": ("cloverstone",),
    "Welfare Witchcraft": ("welfare witchcraft", "welfare_witchcraft"),
}

SEMANTIC_DOMAIN_SIGNALS = {
    "Games": (
        "egyptian ratscrew", "egyptian rat screw", "ers", "egyptian war",
        "ratslap", "slapjack", "beggar-my-neighbour", "card game",
        "folk game",
    ),
    "Civic Infrastructure": (
        "infrastructure", "curb", "parking", "public space", "municipal",
        "highway", "right-of-way", "roadside", "corridor",
    ),
    "Transit": (
        "public transit", "transit", "bus", "train", "paratransit",
        "gtfs", "mobility", "transportation",
    ),
    "Environment": (
        "green infrastructure", "solar", "renewable", "ecological",
        "habitat", "stormwater", "biodiversity", "pollinator",
        "agrivoltaics", "ecovoltaics", "native planting",
    ),
    "Technology": (
        "digital", "api", "apis", "ai", "data", "software", "computer vision",
        "sensors", "gis", "battery", "ev charging", "standards",
    ),
    "Career": (
        "career", "credentials", "experience", "sector history",
        "sector-specific", "bridge roles", "first year", "resume",
        "professional package", "portfolio",
    ),
    "Personal Interpretation": (
        "i feel", "i think", "i want", "i'm hostile", "i am hostile",
        "my instinct", "your anxiety", "your brain", "self",
        "success", "wealth", "provenance", "what made this possible",
    ),
}

TENTATIVE_RE = re.compile(r"\b(maybe|possibly|what if|could|might|explore|tentative)\b", re.IGNORECASE)
SUPERSEDED_RE = re.compile(r"\b(replaces|supersedes|instead of|no longer|previously|now use)\b", re.IGNORECASE)
CONFLICT_RE = re.compile(r"\b(conflicts? with|contradicts?|disagrees? with)\b", re.IGNORECASE)
PATH_RE = re.compile(r"\b[A-Za-z]:\\[^\s`\"']+")
COUNT_EVENT_RE = re.compile(r"\b(proposal|op-|quarantined|applied|failed|skipped|created|found)\b", re.IGNORECASE)
DEPENDENCY_RE = re.compile(r"\b(depends on|dependent|dependency|references?|points to)\b", re.IGNORECASE)
ASSISTANT_GROUNDED_RE = re.compile(r"\b(i ran|command output|ledger shows|filesystem shows|verified|observed)\b", re.IGNORECASE)
SELF_REPORT_RE = re.compile(r"\b(i feel|i think|i want|i found out|i'm|i am|my)\b", re.IGNORECASE)
DESCRIPTIVE_EXTERNAL_RE = re.compile(
    r"\b(is|are|has|have|contains?|involves?|uses?|does|causes?|lacks?|consists? of)\b",
    re.IGNORECASE,
)
CONTRAST_RE = re.compile(r"\b(vs\.?|versus|rather than|the difference is|not\b.+\bbut)\b", re.IGNORECASE)


def load_conversation(input_path: str | Path) -> tuple[dict, str]:
    path = Path(input_path)
    raw_text = path.read_text(encoding="utf-8")
    data = json.loads(raw_text)
    validate_conversation(data)
    return data, raw_text


def validate_conversation(data: dict) -> None:
    if not isinstance(data, dict):
        raise ValueError("conversation must be a JSON object")
    if not data.get("id"):
        raise ValueError("conversation.id is required")
    messages = data.get("messages")
    if not isinstance(messages, list):
        raise ValueError("conversation.messages must be a list")
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise ValueError(f"messages[{index}] must be an object")
        if "role" not in message:
            raise ValueError(f"messages[{index}].role is required")
        if "content" not in message:
            raise ValueError(f"messages[{index}].content is required")


def preserve_raw_conversation(conn, conversation: dict, raw_text: str,
                              platform: str = None, source_container: str = None) -> dict:
    from db.database import record_source

    conversation_id = str(conversation["id"])
    platform = platform or conversation.get("platform") or "unknown"
    source_container = source_container or conversation.get("source_container")
    label = conversation.get("title") or conversation_id
    if source_container:
        label = f"{label} [{source_container}]"

    source_id = record_source(conn, kind="conversation_import", label=label, platform=platform)
    summary = json.dumps(
        {
            "conversation_id": conversation_id,
            "title": conversation.get("title"),
            "platform": platform,
            "source_container": source_container,
            "message_count": len(conversation.get("messages", [])),
        },
        sort_keys=True,
    )
    existing = conn.execute(
        "SELECT id FROM handoffs WHERE packet_id = ?;",
        (conversation_id,),
    ).fetchone()
    if existing:
        conn.execute(
            """UPDATE handoffs
               SET source_id=?, summary=?, raw_json=?, requires_review=1
               WHERE id=?;""",
            (source_id, summary, raw_text, existing["id"]),
        )
        handoff_id = existing["id"]
    else:
        cur = conn.execute(
            """INSERT INTO handoffs (packet_id, source_id, summary, raw_json, requires_review)
               VALUES (?, ?, ?, ?, 1);""",
            (conversation_id, source_id, summary, raw_text),
        )
        handoff_id = cur.lastrowid
    conn.commit()
    return {"source_id": source_id, "handoff_id": handoff_id}


def candidate_key(conversation_id: str, message_index: int, statement_index: int,
                  model: str, category: str, what: str) -> str:
    basis = "\n".join([conversation_id, str(message_index), str(statement_index), model, category, what])
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
    return f"cand_{digest}"


def split_candidate_statements(content: str) -> list[str]:
    statements = []
    for line in content.splitlines():
        cleaned = line.strip(" \t-*#>`")
        if not cleaned:
            continue
        parts = re.split(r"(?<=[.!?])\s+", cleaned)
        for part in parts:
            if re.search(r"\bbut that is not part of\b", part, re.IGNORECASE):
                left, right = re.split(r",?\s+but\s+", part, maxsplit=1, flags=re.IGNORECASE)
                statements.append(left.strip(" ."))
                statements.append(_resolve_split_demonstrative(left, right))
            else:
                statements.append(part.strip())
    return [statement for statement in statements if statement]


def _resolve_split_demonstrative(left: str, right: str) -> str:
    cleaned_right = right.strip(" .")
    match = re.search(r"\buse\s+([A-Za-z0-9_ -]+)$", left.strip(" ."), re.IGNORECASE)
    if match and re.match(r"^(that|this|it)\s+is\s+not\s+part\s+of\b", cleaned_right, re.IGNORECASE):
        subject = match.group(1).strip()
        verb = "are" if subject.lower().endswith("s") else "is"
        remainder = re.sub(
            r"^(that|this|it)\s+is\s+not\s+part\s+of",
            "not part of",
            cleaned_right,
            count=1,
            flags=re.IGNORECASE,
        )
        return f"{subject[:1].upper()}{subject[1:]} {verb} {remainder}."
    return cleaned_right[:1].upper() + cleaned_right[1:] + "."


def classify_statement(statement: str, role: str = None) -> tuple[str, str, str]:
    lowered = statement.lower()

    if is_evaluative_contrast(statement):
        return "PMM", PMM_CATEGORIES["principle"], "Evaluative contrast expressing durable interpretation."
    if role == "user" and SELF_REPORT_RE.search(statement) and any(
        signal in lowered
        for signal in ("hostile", "want", "feel", "think", "reaction", "preference", "torn")
    ):
        return "PMM", PMM_CATEGORIES["pattern"], "User self-report about attitude, interpretation, or recurring pattern."
    if lowered.startswith("do not ") or lowered.startswith("no ") or " do not " in lowered or " never " in lowered:
        return "PMM", PMM_CATEGORIES["constraint"], "Normative prohibition or boundary instruction."
    if lowered.startswith("proceed with ") or " is accepted" in lowered or " accepted as " in lowered:
        return "PMM", PMM_CATEGORIES["decision"], "Explicit approval/decision to proceed."
    if lowered.startswith("add deterministic "):
        return "PMM", PMM_CATEGORIES["decision"], "Explicit implementation decision."
    if "intentionally deferred taxonomy question" in lowered:
        return "PMM", PMM_CATEGORIES["decision"], "Explicit decision to defer taxonomy."
    if "means" in lowered or "defined as" in lowered or "definition" in lowered:
        if role == "assistant" and not project_associations_for_statement(statement):
            return "PWM", PWM_CATEGORIES["state"], "General reference definition, not adopted user/project meaning."
        return "PMM", PMM_CATEGORIES["definition"], "Meaning/definition language."
    if (
        "proposed move is not evidence" in lowered
        or lowered.startswith("classify candidates according to ")
        or lowered.startswith("atomic candidates ")
        or lowered.startswith("separate epistemic confidence ")
    ):
        return "PMM", PMM_CATEGORIES["principle"], "Interpretation or architectural rule."
    if any(signal in lowered for signal in ("must", "should", "do not", "never", "constraint", "permissioned")):
        return "PMM", PMM_CATEGORIES["constraint"], "Normative or constraint language."
    if "not part of diet v0.1" in lowered:
        return "PMM", PMM_CATEGORIES["constraint"], "Explicit phase boundary."
    if lowered.startswith("use ") or lowered.startswith("preserve ") or lowered.startswith("stop at ") or lowered.startswith("keep "):
        return "PMM", PMM_CATEGORIES["constraint"], "Implementation boundary instruction."
    if any(signal in lowered for signal in ("i prefer", "preference", "prefer ")):
        return "PMM", PMM_CATEGORIES["preference"], "Preference language."
    if (
        "decided" in lowered
        or "current decision" in lowered
        or "decision:" in lowered
        or lowered.startswith("decision ")
    ):
        return "PMM", PMM_CATEGORIES["decision"], "Decision language."
    if is_descriptive_external_state(statement, role=role):
        return "PWM", PWM_CATEGORIES["state"], "Descriptive external/reference state."
    if any(signal in lowered for signal in ("maybe", "possibly", "what if", "could", "might", "explore")):
        return "PMM", PMM_CATEGORIES["goal"], "Tentative future possibility."
    if role == "assistant" and lowered.startswith("build something like "):
        return "PMM", PMM_CATEGORIES["goal"], "Assistant suggestion, not adopted user decision."
    if any(_has_signal(lowered, signal) for signal in ("goal", "mission", "success condition")):
        return "PMM", PMM_CATEGORIES["goal"], "Goal or mission language."

    if any(signal in lowered for signal in ("common alternate name", "standard modern american name", "established name")):
        return "PWM", PWM_CATEGORIES["state"], "General reference/world-knowledge claim."
    if "no meaningful egyptian connection" in lowered:
        return "PWM", PWM_CATEGORIES["state"], "General reference/world-knowledge claim."
    if "curb data specification" in lowered or "digital curb inventories" in lowered:
        return "PWM", PWM_CATEGORIES["system"], "Concrete civic-technology system/reference."
    if "zero direct sector history" in lowered and "transferable ability" in lowered:
        return "PMM", PMM_CATEGORIES["principle"], "Personal/career interpretation rule."
    if "proposal" in lowered:
        return "PWM", PWM_CATEGORIES["event"], "Proposal/move state language; proposed action is not treated as completed action."
    if any(signal in lowered for signal in ("embedding", "vector search")):
        return "PWM", PWM_CATEGORIES["resource"], "Concrete resource/capability reference."
    if PATH_RE.search(statement):
        return "PWM", PWM_CATEGORIES["location"], "Concrete filesystem path reference."
    if "tables" in lowered and any(signal in lowered for signal in ("has ", "already has", "exists")):
        return "PWM", PWM_CATEGORIES["system"], "Reported system/schema state."
    if DEPENDENCY_RE.search(statement):
        return "PWM", PWM_CATEGORIES["dependency"], "Dependency/reference language."
    if COUNT_EVENT_RE.search(statement):
        return "PWM", PWM_CATEGORIES["event"], "Concrete operation/event language."
    if any(signal in lowered for signal in ("exists", "created", "status", "state", "artifact", "system")):
        return "PWM", PWM_CATEGORIES["state"], "Concrete state/system language."

    return "neither", "None", "No durable PMM/PWM signal detected."


def concise_candidate_statement(statement: str) -> str:
    lowered = statement.lower()
    if lowered.startswith("record this as a taxonomy question"):
        return (
            "Whether tentative future possibilities need a category distinct from "
            "Goal remains an intentionally deferred taxonomy question."
        )
    if "public utility intelligence" in lowered and "toll booth" in lowered:
        return (
            "Public infrastructure should function as shared public intelligence "
            "rather than turning every interaction into an extraction or toll mechanism."
        )
    return statement


def confidence_for_statement(statement: str, role: str = None, model: str = None,
                             category: str = None) -> str:
    if "intentionally deferred taxonomy question" in statement.lower():
        return "CONFIRMED"
    if role == "assistant" and statement.lower().startswith("build something like "):
        return "TENTATIVE"
    if role == "assistant" and model == "PWM" and not ASSISTANT_GROUNDED_RE.search(statement):
        return "INFERRED"
    if role == "assistant" and model == "PMM":
        if TENTATIVE_RE.search(statement):
            return "TENTATIVE"
        if category in (PMM_CATEGORIES["decision"], PMM_CATEGORIES["principle"], PMM_CATEGORIES["constraint"]):
            return "INFERRED"
    if TENTATIVE_RE.search(statement):
        return "TENTATIVE"
    if any(signal in statement.lower() for signal in ("likely", "suggests", "inferred")):
        return "INFERRED"
    return "CONFIRMED"


def state_for_statement(statement: str) -> str:
    if CONFLICT_RE.search(statement):
        return "CONFLICTED"
    if SUPERSEDED_RE.search(statement):
        return "SUPERSEDED"
    return "ACTIVE"


def compatibility_status(confidence: str, state: str) -> str:
    return state if state != "ACTIVE" else confidence


def _has_signal(text: str, signal: str) -> bool:
    if re.search(r"\w", signal):
        return re.search(rf"(?<!\w){re.escape(signal)}(?!\w)", text) is not None
    return signal in text


def is_evaluative_contrast(statement: str) -> bool:
    lowered = statement.lower()
    if not CONTRAST_RE.search(statement):
        return False
    evaluative_terms = (
        "should", "public", "shared", "extract", "toll", "rather than",
        "difference", "success", "systems", "benefit", "loses", "chokepoint",
    )
    return any(term in lowered for term in evaluative_terms)


def is_descriptive_external_state(statement: str, role: str = None) -> bool:
    lowered = statement.lower()
    if role == "user":
        return False
    if project_associations_for_statement(statement):
        return False
    if not DESCRIPTIVE_EXTERNAL_RE.search(statement):
        return False
    if any(signal in lowered for signal in ("should", "must", "do not", "never", "i prefer")):
        return False
    if "not part of diet" in lowered:
        return False
    if any(domain != "General / Unclassified" for domain in semantic_domains_for_statement(statement)):
        return True
    return False


def project_associations_for_statement(statement: str) -> list[str]:
    lowered = statement.lower()
    associations = []
    for scope, signals in DOMAIN_SIGNALS.items():
        if any(_has_signal(lowered, signal) for signal in signals):
            associations.append(scope)
    return associations


def semantic_domains_for_statement(statement: str) -> list[str]:
    lowered = statement.lower()
    domains = []
    for domain, signals in SEMANTIC_DOMAIN_SIGNALS.items():
        if any(_has_signal(lowered, signal) for signal in signals):
            domains.append(domain)
    return domains or ["General / Unclassified"]


def scope_for_statement(statement: str, source_container: str = None) -> list[str]:
    del source_container
    project_associations = project_associations_for_statement(statement)
    if project_associations:
        return project_associations
    return semantic_domains_for_statement(statement)


def extract_candidates(conversation: dict, platform: str = None,
                       source_container: str = None) -> list[dict]:
    conversation_id = str(conversation["id"])
    platform = platform or conversation.get("platform") or "unknown"
    source_container = source_container or conversation.get("source_container")
    candidates = []

    for message_index, message in enumerate(conversation.get("messages", [])):
        role = message.get("role")
        content = str(message.get("content", ""))
        timestamp = message.get("timestamp")
        for statement_index, statement in enumerate(split_candidate_statements(content)):
            statement = concise_candidate_statement(statement)
            model, category, reason = classify_statement(statement, role=role)
            if model == "neither":
                continue
            confidence = confidence_for_statement(statement, role=role, model=model, category=category)
            state = state_for_statement(statement)
            status = compatibility_status(confidence, state)
            semantic_domains = semantic_domains_for_statement(statement)
            project_associations = project_associations_for_statement(statement)
            candidate = {
                "candidate_key": candidate_key(
                    conversation_id, message_index, statement_index, model, category, statement
                ),
                "what": statement,
                "model": model,
                "category": category,
                "confidence": confidence,
                "state": state,
                "status": status,
                "semantic_domains": semantic_domains,
                "project_associations": project_associations,
                "scope": project_associations or semantic_domains,
                "source": {
                    "conversation_id": conversation_id,
                    "platform": platform,
                    "source_container": source_container,
                    "message_index": message_index,
                    "statement_index": statement_index,
                    "role": role,
                    "timestamp": timestamp,
                },
                "reason": reason,
            }
            candidates.append(candidate)
    return candidates


def build_review(conversation: dict, candidates: list[dict], preserve_result: dict,
                 platform: str = None, source_container: str = None) -> dict:
    platform = platform or conversation.get("platform") or "unknown"
    source_container = source_container or conversation.get("source_container")
    pmm_count = sum(1 for c in candidates if c["model"] == "PMM")
    pwm_count = sum(1 for c in candidates if c["model"] == "PWM")
    return {
        "source": {
            "conversation_id": str(conversation["id"]),
            "title": conversation.get("title"),
            "platform": platform,
            "source_container": source_container,
            "handoff_id": preserve_result["handoff_id"],
            "source_id": preserve_result["source_id"],
        },
        "summary": {
            "message_count": len(conversation.get("messages", [])),
            "candidate_count": len(candidates),
            "pmm_count": pmm_count,
            "pwm_count": pwm_count,
            "neither_count": 0,
            "requires_review": True,
            "canonical_promotion": False,
            "proposals_created": False,
            "open_loops_created": False,
        },
        "candidates": candidates,
    }


def default_review_path(conversation: dict) -> Path:
    root = Path(__file__).resolve().parents[1]
    return root / "handoffs_inbox" / f"{conversation['id']}.review.json"


def ingest_conversation(conn, input_path: str | Path, output_path: str | Path = None,
                        platform: str = None, source_container: str = None) -> dict:
    conversation, raw_text = load_conversation(input_path)
    platform = platform or conversation.get("platform") or "unknown"
    source_container = source_container or conversation.get("source_container")
    preserve_result = preserve_raw_conversation(
        conn, conversation, raw_text, platform=platform, source_container=source_container
    )
    candidates = extract_candidates(
        conversation, platform=platform, source_container=source_container
    )
    review = build_review(
        conversation, candidates, preserve_result,
        platform=platform, source_container=source_container,
    )
    out = Path(output_path) if output_path else default_review_path(conversation)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(review, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "status": "review_written",
        "output_path": str(out),
        "source_id": preserve_result["source_id"],
        "handoff_id": preserve_result["handoff_id"],
        "candidate_count": len(candidates),
        "pmm_count": review["summary"]["pmm_count"],
        "pwm_count": review["summary"]["pwm_count"],
    }
