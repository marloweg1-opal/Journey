"""Scoped naming evidence. Audit records never create executable naming rules."""

from datetime import datetime
import re

from core.project_registry import asset_name, text_field


FORMAT = "journey-naming-audit-1"
FIELDS = ("project_tag", "marker", "marker_meaning", "field_order", "date", "extension", "variation", "version")
TIERS = "ABCDEFGH"
ROLES = {"user", "accepted_spec", "asset_record", "current_file", "assistant", "derived"}


def words(value):
    return " ".join(re.findall(r"[^\W_]+", value.casefold()))


def contains_words(value, phrase):
    phrase = words(phrase)
    return bool(phrase) and f" {phrase} " in f" {words(value)} "


def _bounded_list(value, minimum, maximum, label):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f"Expected {minimum}–{maximum} {label}.")
    return value


def _source(source):
    role = source["role"]
    if role not in ROLES:
        raise ValueError("Naming evidence needs an attributed source.")
    result = {"role": role, "locator": text_field(source["locator"], 400)}
    if source.get("authored"):
        stamp = datetime.fromisoformat(text_field(source["authored"], 50))
        if stamp.tzinfo is None:
            raise ValueError("Authored dates need a timezone.")
        result["authored"] = stamp.isoformat()
    return result


def validate_audit(document):
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise ValueError("Choose a Journey naming audit document.")
    project = text_field(document["project"], 80)
    subjects = [text_field(item, 80) for item in _bounded_list(document["subjects"], 1, 24, "subjects")]
    families = []
    for row in _bounded_list(document["families"], 1, 20, "asset families"):
        families.append({"name": text_field(row["name"], 80),
                         "terms": [text_field(term, 60) for term in _bounded_list(row["terms"], 1, 8, "family terms")]})
    family_names = {row["name"] for row in families}
    if len({item.casefold() for item in subjects}) != len(subjects) or len(family_names) != len(families):
        raise ValueError("Subjects and asset families must be distinct.")
    aliases = document.get("aliases", {})
    if not isinstance(aliases, dict) or set(aliases) - set(subjects):
        raise ValueError("Subject aliases must belong to a declared project subject.")
    aliases = {subject: [text_field(alias, 80) for alias in _bounded_list(values, 0, 8, "subject aliases")]
               for subject, values in aliases.items()}
    claims = {}
    for row in _bounded_list(document["claims"], 0, 200, "evidence records"):
        claim = {key: text_field(row[key], 240 if key == "value" else 100)
                 for key in ("id", "subject", "family", "dimension", "value", "tier")}
        if (claim["id"] in claims or claim["subject"] not in ("*", *subjects)
                or claim["family"] not in ("*", *family_names) or claim["dimension"] not in FIELDS
                or claim["tier"] not in tuple(TIERS)):
            raise ValueError("Invalid, duplicate, or out-of-scope naming evidence.")
        source = _source(row["source"])
        role = source["role"]
        if role not in ROLES or (claim["tier"] in ("A", "C") and role != "user") or (claim["tier"] == "B" and role != "accepted_spec"):
            raise ValueError("The evidence source does not support that authority tier.")
        claim["source"] = source
        if row.get("supersedes"):
            claim["supersedes"] = text_field(row["supersedes"], 100)
        claims[claim["id"]] = claim
    for claim in claims.values():
        if "supersedes" not in claim:
            continue
        prior = claims.get(claim["supersedes"])
        fields = ("subject", "family", "dimension")
        if (claim["tier"] != "A" or prior is None or prior == claim
                or any(prior[key] != claim[key] for key in fields)
                or not claim["source"].get("authored") or not prior["source"].get("authored")
                or datetime.fromisoformat(claim["source"]["authored"]) <= datetime.fromisoformat(prior["source"]["authored"])):
            raise ValueError("A later explicit user correction can supersede only the same dimension and scope.")
    examples = []
    for row in _bounded_list(document.get("examples", []), 0, 100, "filename examples"):
        name, subject, family = row["filename"], row["subject"], row["family"]
        if not name or name != asset_name(name) or subject not in subjects or family not in family_names:
            raise ValueError("An example must be a named asset in the audited project scope.")
        source = _source(row["source"])
        sample = {"filename": name, "subject": subject, "family": family, "source": source}
        if row.get("sha256"):
            digest = row["sha256"]
            if source["role"] not in ("asset_record", "current_file") or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("A file fingerprint must have attributable direct-file provenance.")
            sample["sha256"] = digest
        examples.append(sample)
    return {"format": FORMAT, "project": project, "subjects": subjects, "aliases": aliases,
            "families": families, "claims": list(claims.values()), "examples": examples}


def resolve_field(claims, subject, family, dimension):
    applicable = [claim for claim in claims if claim["dimension"] == dimension
                  and claim["subject"] in ("*", subject) and claim["family"] in ("*", family)]
    superseded = {claim.get("supersedes") for claim in applicable}
    active = [claim for claim in applicable if claim["id"] not in superseded]
    proof = [claim | {"superseded": claim["id"] in superseded} for claim in applicable]
    if not active:
        return {"state": "UNKNOWN", "value": None, "proof": proof}
    def rank(claim):
        return TIERS.index(claim["tier"]), -(int(claim["subject"] == subject) + int(claim["family"] == family))
    strongest = min(active, key=rank)
    strongest_scope = [claim for claim in active if rank(claim) == rank(strongest)]
    # Verified item-specific evidence can surface drift against accepted naming,
    # but an exemplar does not authorize a new project-wide convention.
    verified = [claim for claim in active if claim["tier"] in ("D", "E") and claim["source"]["role"] in ("asset_record", "current_file")
                and claim["subject"] == subject and claim["family"] == family]
    if strongest["tier"] in ("A", "B"):
        strongest_scope += verified
    values = {claim["value"] for claim in strongest_scope}
    if len(values) > 1:
        return {"state": "CONFLICTED", "value": None, "proof": proof}
    return {"state": "CONFIRMED" if strongest["tier"] in ("A", "B") else "CANDIDATE",
            "value": strongest["value"], "proof": proof}
