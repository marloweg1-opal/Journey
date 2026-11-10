"""Interpret visible evidence without assigning canonical meaning from resemblance or text."""

import json
from pathlib import Path
import re

from core.naming import detected_token_ids, extract_date_info, observe_filename
from core.token_registry import resolve_token, validate_token_registry
from journey_planner.catalog import validate_name
from journey_vision.steward import PROPOSE_IDENTITY, STAMP, VERSION_TOKEN, _identity, _purpose, contextual_filename, pixel_distance


PROFILE = Path(__file__).resolve().parents[1] / "examples" / "carebloom" / "project_tokens.json"
ASSET_TYPES = {
    "CareRail UI / Design": r"\bcare[\W_]*rail\b",
    "Touchstone": r"\btouch[\W_]*stones?\b",
    "Crystal": r"\bcrystals?\b",
    "Emblem": r"\bemblems?\b|\bmedallions?\b",
    "Character Lineup": r"\b(?:multi[\W_]*character|(?:character|cast|team)[\W_]+line[\W_]*up|line[\W_]*up)\b",
    "Character Reference": r"\bcharacter[\W_]+(?:reference|sheet|design[\W_]+(?:summary[\W_]+)?sheet)\b|\breference[\W_]+sheet\b",
    "Equipment / Design Reference": r"\b(?:armou?ry|arsenal)\b|\b(?:equipment|weapons?|technical|loadout)[\W_]*(?:(?:design|reference|sheet|board|study)\b|$)|\bdesign[\W_]+(?:sheet|board)\b",
    "Concept Board": r"\bconcept[\W_]+(?:board|art)\b|\bconcepts\b",
    "Chibi / Mascot": r"\b(?:chibi|mascots?)\b",
    "Widget": r"\bwidgets?\b",
    "Desk": r"\bdesks?\b",
    "Icons & Badges": r"\b(?:icons?|badges?)\b",
    "Wallpaper": r"\bwallpapers?\b",
    "Screenshot": r"\bscreenshots?\b",
    "Diagram": r"\bdiagrams?\b",
    "Artwork": r"\bartwork\b",
}
MENTION_ONLY = re.compile(r"\b(?:not|versus|vs|compare|comparison|inspired by|resembles|unrelated|example of)\b", re.I)
NAMING_HOLD = ("Filename changes are held: this candidate has no validated project naming profile. "
               "A confirmed subject, a trial format, and batch approval do not validate the convention. "
               "Inspection, virtual collections, and reviewed moves that keep the exact filename remain available.")


def require_preserved_filename(source, destination):
    """Enforce the release hold independently of UI, trial formats and consent."""
    if Path(source).name != Path(destination).name:
        raise ValueError(NAMING_HOLD)


def _compound_references(registry, text, ids):
    # A registered word within a compound asset reference is not necessarily
    # the depicted subject. Preserve the phrase rather than register an alias.
    result = []
    normalized = " ".join(re.findall(r"[^\W_]+", text.casefold()))
    stems = {token["display_name"][:-5].casefold(): token["display_name"] for token in registry["tokens"].values()
             if token["display_name"].casefold().endswith("stone")}
    for key in ids:
        token = registry["tokens"][key]
        aliases = [key, token["display_name"], *token.get("aliases", [])]
        phrases = {" ".join(re.findall(r"[^\W_]+", alias.casefold())) for alias in aliases}
        matches, compounds = [], []
        for phrase in phrases:
            matches.extend(match.span() for match in re.finditer(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", normalized))
            for stem in stems:
                compound = stem + " " + phrase
                if compound in phrases:
                    continue  # Respect a deliberately registered full alias.
                for match in re.finditer(r"(?<!\w)" + re.escape(compound) + r"(?!\w)", normalized):
                    compounds.append((match.start(), match.end(), compound, stem))
        if compounds and all(any(start < first and last <= end for start, end, _, _ in compounds) for first, last in matches):
            result.extend({"token": key, "phrase": phrase, "possible_subject": stems[stem],
                           "related_to": token["display_name"],
                           "reason": "A compound asset reference does not establish the image's subject."}
                          for phrase, stem in sorted({(phrase, stem) for _, _, phrase, stem in compounds}))
    return result


def profile_registry():
    registry = json.loads(PROFILE.read_text(encoding="utf-8"))
    validate_token_registry(registry)
    return registry


def _token_key(registry, value):
    resolved = resolve_token(registry, value)
    return resolved[0] if resolved else value.casefold()


def asset_families(text):
    text = text.replace("_", " ")
    labels = [label for label, pattern in ASSET_TYPES.items() if re.search(pattern, text, re.I)]
    # Specific role words describe the artifact even if the text also names
    # a generic medium. Conflicting specific roles remain visible.
    if "CareRail UI / Design" in labels:
        labels = [label for label in labels if label not in ("Artwork", "Screenshot", "Diagram")]
    if "Character Lineup" in labels:
        labels = [label for label in labels if label != "Character Reference"]
    if "Equipment / Design Reference" in labels and "Character Reference" in labels and not re.search(r"\bcharacter\b", text, re.I):
        labels.remove("Character Reference")
    return labels


def _evidence(registry, source, text, *, confidence=None, top=None):
    ids = detected_token_ids(registry, text, whole_tokens=True)
    compounds = _compound_references(registry, text, ids)
    ambiguous = {item["token"] for item in compounds}
    ids = [key for key in ids if key not in ambiguous]
    purposes = asset_families(text)
    versions = VERSION_TOKEN.findall(text)
    dates = STAMP.findall(text)
    if not dates:
        _, date_info = extract_date_info(text)
        if date_info["token"]:
            dates = [date_info["token"]]
    if not (ids or purposes or versions or dates or compounds):
        return None
    strength = "mention" if MENTION_ONLY.search(text.replace("_", " ")) else "direct"
    if source == "Image text":
        strength = "title" if confidence >= 75 and top <= 0.33 and len(text.split()) <= 8 and strength == "direct" else "mention"
    return {"source": source, "text": text, "subjects": [registry["tokens"][key]["display_name"] for key in ids],
            "purposes": purposes, "versions": versions, "dates": dates, "strength": strength, "confidence": confidence,
            "ambiguous_references": compounds}


def _context_identity(registry, asset, reviews, examples, signals):
    visual = _identity(asset, reviews, examples)
    direct, mentions = {}, {}
    for signal in signals:
        for label in signal["subjects"]:
            key = _token_key(registry, label)
            if signal["strength"] == "mention":
                mentions[key] = label
            else:
                direct[key] = label
    if visual["state"] == "proposed_identity":
        direct.setdefault(_token_key(registry, visual["label"]), visual["label"])
    elif visual["state"] == "unknown":
        close = {}
        for digest, decisions in reviews.items():
            if digest not in examples or pixel_distance(asset["features"], examples[digest]["features"]) > PROPOSE_IDENTITY:
                continue
            for event in decisions.values():
                if event["action"] == "confirm":
                    close[_token_key(registry, event["label"])] = event["label"]
        if len(close) > 1:
            direct.update(close)
    rejections = {_token_key(registry, item["label"]): item["evidence"] for item in visual.get("suppressed", [])}
    for digest, decisions in reviews.items():
        if digest not in examples or pixel_distance(asset["features"], examples[digest]["features"]) > PROPOSE_IDENTITY:
            continue
        for event in decisions.values():
            if event["action"] == "reject":
                key = _token_key(registry, event["label"])
                if key in direct or key in mentions or digest == asset["digest"]:
                    rejections[key] = event

    if visual["state"] == "human_confirmed_identity":
        confirmed = _token_key(registry, visual["label"])
        conflicts = [label for key, label in direct.items() if key != confirmed]
        if conflicts:
            visual["reason"] += " Other evidence disagrees with the saved confirmation."
        return visual | {"conflicts": conflicts, "visual": None}

    rejected = list(rejections.values())
    for key in rejections:
        direct.pop(key, None)
        mentions.pop(key, None)
    conflicts = list(direct.values())
    common = {"label": "", "rejections": rejected, "conflicts": [],
              "visual": visual if visual["state"] == "proposed_identity" else None}
    if len(direct) > 1:
        return common | {"state": "conflicting_evidence", "conflicts": conflicts,
                         "reason": "Different evidence points to different identities. The subject needs review."}
    if direct:
        key, label = next(iter(direct.items()))
        return common | {"state": "proposed_identity", "label": label,
                         "reason": "The evidence suggests this subject. A human has yet to confirm this image.",
                         "mentions": [value for other, value in mentions.items() if other != key]}
    if rejected:
        return common | {"state": "explicitly_rejected_identity",
                         "reason": "A saved correction ruled out the listed association for this image or a closely related example."}
    if mentions:
        return common | {"state": "possibly_related", "mentions": list(mentions.values()),
                         "reason": "The image text mentions these subjects. A mention alone does not identify the image."}
    ambiguous = [item for signal in signals for item in signal.get("ambiguous_references", [])]
    reason = "The available evidence leaves the subject open."
    if ambiguous:
        reason += " A compound asset reference needs context before it can identify a subject."
    return common | {"state": "unknown", "reason": reason}


def _context_purpose(path, asset, reviews, examples, signals):
    visual = _purpose(path.as_posix(), asset, reviews, examples)
    if visual["state"] == "human_confirmed":
        return visual
    tiers = (("Filename", "Image text", "Verified file exemplar"), ("Local history",), ("Folder",))
    for sources in tiers:
        explicit = {purpose for signal in signals if signal["source"] in sources and signal["strength"] != "mention"
                    for purpose in signal["purposes"]}
        if len(explicit) == 1:
            reason = ("An attributed local archive reference suggests this purpose for the matched name."
                      if sources == ("Local history",) else "The filename, a readable title, or a scoped example indicates this purpose.")
            return {"state": "inferred", "label": explicit.pop(), "reason": reason}
        if explicit:
            return {"state": "conflicting_evidence", "label": "", "reason": "The available labels describe more than one asset purpose.",
                    "conflicts": sorted(explicit)}
    if visual["label"] == "Wallpaper candidates":
        return {"state": "unknown", "label": "", "reason": "A widescreen canvas suggests a presentation format. The asset purpose is open."}
    return visual


def assess(registry, path, scope, asset, reviews, examples, ocr, historical=(), exemplars=(), entity_links=()):
    identities, purposes = reviews
    signals = [_evidence(registry, "Filename", path.stem)]
    if registry.get("profile_active") and signals[0] and not signals[0]["subjects"] and "Touchstone" in signals[0]["purposes"]:
        short = re.match(r"([^\W_]+)[\W_]+touch[\W_]*stone\b", path.stem, re.I)
        if short:
            signal = _evidence(registry, "Filename", short[1] + "stone")
            if signal and len(signal["subjects"]) == 1:
                signals[0]["subjects"] = signal["subjects"]
                signals[0]["text"] += " (project Touchstone shorthand)"
    for parent in (Path(scope).name, *path.relative_to(scope).parts[:-1]):
        signals.append(_evidence(registry, "Folder", parent))
    for line in ocr.get("lines", []) if ocr.get("status") != "unreliable" else ():
        signals.append(_evidence(registry, "Image text", line["text"], confidence=line["confidence"], top=line["top"]))
    for claim in historical:
        if claim.get("family") and claim["match"] in ("filename candidate", "variant candidate"):
            source = claim["source"]
            signals.append({"source": "Local history", "text": claim["name"], "subjects": [], "purposes": [claim["family"]],
                            "strength": "candidate", "provenance": source})
    for item in exemplars:
        exemplar_purposes = asset_families(Path(item["filename"]).stem)
        known = {"CareRail Panel": "CareRail UI / Design", "Icon": "Icons & Badges", "Badge": "Icons & Badges"}
        family = known.get(item["family"], item["family"])
        if not exemplar_purposes and family in ASSET_TYPES:
            exemplar_purposes = [family]
        signals.append({"source": "Verified file exemplar", "text": item["filename"], "subjects": [item["subject"]],
                        "purposes": exemplar_purposes, "strength": "candidate", "provenance": item["source"]})
    for item in entity_links:
        signals.append({"source": "Local history", "text": item["name"], "subjects": [item["value"]["entity"]],
                        "purposes": [], "strength": "candidate", "provenance": item["source"]})
    signals = [signal for signal in signals if signal]
    identity = _context_identity(registry, asset, identities, examples, signals)
    purpose = _context_purpose(path, asset, purposes, examples, signals)
    if registry.get("profile_active") and purpose["state"] in ("unknown", "inferred") and identity["label"] and not any(
            signal["purposes"] and signal["strength"] != "mention" for signal in signals):
        features = asset["features"]
        subject_only = _token_key(registry, path.stem) == _token_key(registry, identity["label"])
        if subject_only and 0.72 <= features["width"] / features["height"] <= 1.38 and features["transparency"] >= 0.08:
            purpose = {"state": "inferred", "label": "Emblem", "reason": "The subject-only name and isolated artwork suggest a project emblem."}
    return {"identity": identity, "purpose": purpose, "signals": signals,
            "relations": [item for signal in signals for item in signal.get("ambiguous_references", [])]}


def preliminary_name(path, record, rule):
    subject, purpose = record["identity"]["label"], record["purpose"]["label"]
    if not subject or record["identity"]["state"] not in ("proposed_identity", "human_confirmed_identity"):
        return None
    if record["purpose"]["state"] == "conflicting_evidence":
        return None
    if record["identity"]["state"] == "human_confirmed_identity" and record["purpose"]["state"] == "human_confirmed":
        return None
    observed = observe_filename(path.name)
    if observed["unicode_sequences"] or re.search(r"(?:_[0-9]+){2,}$", path.stem):
        return {"state": "preliminary", "filename": path.name, "executable": False,
                "convention_state": "unvalidated",
                "reason": "Keeps the exact Unicode spelling and structured fields while their naming meanings remain unresolved. " + NAMING_HOLD}
    versions = VERSION_TOKEN.findall(path.stem)
    stamps = STAMP.findall(path.stem)
    values = {"project": rule["project"], "subject": subject, "purpose": purpose,
              "variation": " - ".join(versions), "stamp": " - ".join(stamps)}
    try:
        name = contextual_filename(path, rule["filename"], values, versions, stamps)
        reason = "Uses the selected naming convention and the available subject and purpose evidence."
    except ValueError:
        filename_subjects = {value for signal in record["signals"] if signal["source"] == "Filename" for value in signal["subjects"]}
        try:
            name = path.name if subject in filename_subjects else validate_name(path.name, f"{subject} - {path.name}")
        except ValueError:
            return None
        reason = "Keeps the original filename information while the remaining naming fields are open."
    return {"state": "preliminary", "filename": name, "executable": False,
            "convention_state": "unvalidated", "reason": reason + " This is a trial format, not a validated project convention."}
