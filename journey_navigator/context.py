"""Interpret visible evidence without assigning canonical meaning from resemblance or text."""

import json
from pathlib import Path
import re

from core.naming import detected_token_ids, extract_date_info
from core.token_registry import resolve_token, validate_token_registry
from journey_planner.catalog import validate_name
from journey_vision.steward import PROPOSE_IDENTITY, STAMP, VERSION_TOKEN, _identity, _purpose, contextual_filename, pixel_distance


PROFILE = Path(__file__).resolve().parents[1] / "examples" / "carebloom" / "project_tokens.json"
ASSET_TYPES = {
    "Character Reference": r"\bcharacter[\W_]+(?:reference|sheet)\b|\breference[\W_]+sheet\b",
    "Concept Board": r"\bconcept[\W_]+(?:board|art)\b|\bconcepts\b",
    "Icons & Badges": r"\b(?:icons?|badges?)\b",
    "Wallpaper": r"\bwallpapers?\b",
    "Screenshot": r"\bscreenshots?\b",
    "Diagram": r"\bdiagrams?\b",
    "Artwork": r"\bartwork\b",
}
MENTION_ONLY = re.compile(r"\b(?:not|versus|vs|compare|comparison|inspired by|resembles|unrelated|example of)\b", re.I)


def profile_registry():
    registry = json.loads(PROFILE.read_text(encoding="utf-8"))
    validate_token_registry(registry)
    return registry


def _token_key(registry, value):
    resolved = resolve_token(registry, value)
    return resolved[0] if resolved else value.casefold()


def _evidence(registry, source, text, *, confidence=None, top=None):
    ids = detected_token_ids(registry, text, whole_tokens=True)
    purposes = [label for label, pattern in ASSET_TYPES.items() if re.search(pattern, text.replace("_", " "), re.I)]
    versions = VERSION_TOKEN.findall(text)
    dates = STAMP.findall(text)
    if not dates:
        _, date_info = extract_date_info(text)
        if date_info["token"]:
            dates = [date_info["token"]]
    if not (ids or purposes or versions or dates):
        return None
    strength = "mention" if MENTION_ONLY.search(text.replace("_", " ")) else "direct"
    if source == "Image text":
        strength = "title" if confidence >= 75 and top <= 0.33 and len(text.split()) <= 8 and strength == "direct" else "mention"
    return {"source": source, "text": text, "subjects": [registry["tokens"][key]["display_name"] for key in ids],
            "purposes": purposes, "versions": versions, "dates": dates, "strength": strength, "confidence": confidence}


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
    return common | {"state": "unknown", "reason": "The available evidence leaves the subject open."}


def _context_purpose(path, asset, reviews, examples, signals):
    visual = _purpose(path.as_posix(), asset, reviews, examples)
    if visual["state"] == "human_confirmed":
        return visual
    explicit = {purpose for signal in signals if signal["strength"] != "mention" for purpose in signal["purposes"]}
    if len(explicit) == 1:
        return {"state": "inferred", "label": explicit.pop(), "reason": "A name, folder label, or image title indicates this asset type."}
    if explicit:
        return {"state": "conflicting_evidence", "label": "", "reason": "The available labels describe more than one asset purpose."}
    return visual


def assess(registry, path, scope, asset, reviews, examples, ocr):
    identities, purposes = reviews
    signals = [_evidence(registry, "Filename", path.stem)]
    for parent in (Path(scope).name, *path.relative_to(scope).parts[:-1]):
        signals.append(_evidence(registry, "Folder", parent))
    for line in ocr.get("lines", []):
        signals.append(_evidence(registry, "Image text", line["text"], confidence=line["confidence"], top=line["top"]))
    signals = [signal for signal in signals if signal]
    return {"identity": _context_identity(registry, asset, identities, examples, signals),
            "purpose": _context_purpose(path, asset, purposes, examples, signals), "signals": signals}


def preliminary_name(path, record, rule):
    subject, purpose = record["identity"]["label"], record["purpose"]["label"]
    if not subject or record["identity"]["state"] not in ("proposed_identity", "human_confirmed_identity"):
        return None
    if record["purpose"]["state"] == "conflicting_evidence":
        return None
    if record["identity"]["state"] == "human_confirmed_identity" and record["purpose"]["state"] == "human_confirmed":
        return None
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
    return {"state": "preliminary", "filename": name, "reason": reason}
