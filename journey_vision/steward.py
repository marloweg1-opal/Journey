"""Interpret pixel evidence and draft virtual collections and naming plans."""

from collections import defaultdict
from dataclasses import replace
from itertools import combinations
from pathlib import PurePosixPath
import re
from string import Formatter

from journey_planner.catalog import component, validate_name


SIMILAR = 0.115
RELATED = 0.17
PROPOSE_IDENTITY = 0.075
CONFLICT_MARGIN = 0.012
DEFAULT_RULE = {"project": "", "filename": "{subject} - {purpose}", "folder": "{subject}"}
FIELDS = ("project", "subject", "purpose", "variation", "stamp")
STAMP = re.compile(r"(?<!\d)20\d{2}-?\d{2}-?\d{2}(?:[T_ ]\d{2}-?\d{2}-?\d{2})?(?!\d)")
VERSION_TOKEN = re.compile(r"(?<![a-zA-Z0-9])v\d{1,4}(?![a-zA-Z0-9])", re.I)


def pixel_distance(left, right):
    pixels = sum(abs(a - b) for a, b in zip(left["pixels"], right["pixels"])) / (255 * len(left["pixels"]))
    palette = sum(abs(a - b) for a, b in zip(left["palette"], right["palette"])) / 2
    mask = sum(abs(a - b) for a, b in zip(left["mask"], right["mask"])) / (255 * len(left["mask"]))
    alpha = abs(left["transparency"] - right["transparency"])
    a, b = left["width"] / left["height"], right["width"] / right["height"]
    aspect = 1 - min(a, b) / max(a, b)
    return 0.65 * pixels + 0.16 * palette + 0.09 * mask + 0.05 * alpha + 0.05 * aspect


def group_assets(assets):
    ordered = sorted(assets, key=lambda path: (assets[path]["digest"], path))
    pairs = sorted((pixel_distance(assets[a]["features"], assets[b]["features"]), a, b)
                   for a, b in combinations(ordered, 2))
    distances = {frozenset((a, b)): distance for distance, a, b in pairs}
    groups = {path: {path} for path in ordered}
    for distance, a, b in pairs:
        if distance > SIMILAR:
            break
        left, right = groups[a], groups[b]
        if left is right or any(distances[frozenset((x, y))] > SIMILAR for x in left for y in right):
            continue
        joined = left | right
        for path in joined:
            groups[path] = joined
    unique = {tuple(sorted(group)) for group in groups.values() if len(group) > 1}
    return sorted(unique, key=lambda group: (-len(group), group)), distances


def active_reviews(events):
    undone = {event["target"] for event in events if event["action"] == "undo"}
    return [event for event in events if event["action"] != "undo" and event["id"] not in undone]


def review_index(events):
    identities, purposes = defaultdict(dict), {}
    for event in active_reviews(events):
        key = event["digest"]
        if event["action"] in ("confirm", "reject"):
            identities[key][event["label"].casefold()] = event
        if event.get("purpose"):
            purposes[(event["path"], key)] = event
    return identities, purposes


def _identity(asset, identities, cache):
    exact = identities.get(asset["digest"], {})
    confirmed = next((event for event in exact.values() if event["action"] == "confirm"), None)
    rejected = [event for event in exact.values() if event["action"] == "reject"]
    if confirmed:
        return {"state": "human_confirmed_identity", "label": confirmed["label"], "evidence": confirmed,
                "reason": "The operator confirmed this exact image content within this source scope.", "rejections": rejected}
    if rejected:
        return {"state": "explicitly_rejected_identity", "label": "", "rejections": rejected,
                "reason": "The operator rejected the listed identities for this exact image content."}

    nearby, negatives = {}, defaultdict(list)
    for digest, records in identities.items():
        if digest not in cache:
            continue
        distance = pixel_distance(asset["features"], cache[digest]["features"])
        for label, event in records.items():
            if event["action"] == "reject":
                negatives[label].append((distance, event))
            elif distance <= PROPOSE_IDENTITY and (label not in nearby or distance < nearby[label][0]):
                nearby[label] = (distance, event)

    candidates, suppressed = [], []
    for label, (distance, event) in nearby.items():
        contrary = [item for item in negatives[label]
                    if item[0] <= PROPOSE_IDENTITY and item[0] <= distance + CONFLICT_MARGIN]
        if contrary:
            closest, correction = min(contrary, key=lambda item: item[0])
            suppressed.append({"label": event["label"], "evidence": correction, "distance": round(closest, 4)})
        else:
            candidates.append((distance, event))
    candidates.sort(key=lambda item: item[0])
    if candidates and (len(candidates) == 1 or candidates[1][0] - candidates[0][0] > CONFLICT_MARGIN):
        distance, event = candidates[0]
        return {"state": "proposed_identity", "label": event["label"], "evidence": event,
                "reason": "The composition is close to a human-confirmed example. Identity awaits direct confirmation.",
                "distance": round(distance, 4), "suppressed": suppressed}
    return {"state": "unknown", "label": "", "suppressed": suppressed,
            "reason": ("A retained rejection prevents the similar positive example from supplying this identity."
                       if suppressed else "Human-confirmed examples are absent or too close to competing identities.")}


def _purpose(path, asset, purposes, cache):
    exact = purposes.get((path, asset["digest"]))
    if exact:
        return {"state": "human_confirmed", "label": exact["purpose"], "evidence": exact,
                "reason": "The operator recorded the purpose for this asset."}
    features = asset["features"]
    ratio = features["width"] / features["height"]
    if 0.7 <= ratio <= 1.45 and 0.23 <= features["transparency"] <= 0.96:
        return {"state": "inferred", "label": "Icons & Badges", "reason": "A compact canvas with isolated transparent artwork."}
    if ratio >= 1.6 and features["width"] >= 800 and features["height"] >= 420 and features["transparency"] < 0.03:
        return {"state": "inferred", "label": "Wallpaper candidates", "reason": "A large, opaque widescreen canvas suggests wallpaper format."}
    parent = PurePosixPath(path).parent
    matches, directory_examples = [], []
    for (example, digest), event in purposes.items():
        if digest not in cache:
            continue
        distance = pixel_distance(features, cache[digest]["features"])
        if distance <= PROPOSE_IDENTITY:
            matches.append(event)
        if distance <= SIMILAR and parent.parts and PurePosixPath(example).parent == parent:
            directory_examples.append(event)
    labels = {event["purpose"].casefold() for event in matches}
    if len(labels) == 1:
        event = matches[0]
        return {"state": "inferred", "label": event["purpose"], "evidence": event,
                "reason": "A similar composition has a human-confirmed purpose."}
    if not labels and len({event["digest"] for event in directory_examples}) >= 2:
        if len({event["purpose"].casefold() for event in directory_examples}) == 1:
            return {"state": "inferred", "label": directory_examples[0]["purpose"], "evidence": directory_examples,
                    "reason": "Two or more visually related examples in this folder share a confirmed purpose."}
    return {"state": "unknown", "label": "", "reason": "Visual evidence leaves the purpose open."}


def interpret(assets, cache, events):
    identities, purposes = review_index(events)
    groups, distances = group_assets(assets)
    records, collections, questions = {}, {}, []
    series = {}
    for number, group in enumerate(groups, 1):
        label = f"Visual series {number}"
        collections[label] = {"kind": "visual_series", "members": list(group)}
        series.update((path, label) for path in group)
    for path, asset in assets.items():
        identity = _identity(asset, identities, cache)
        purpose = _purpose(path, asset, purposes, cache)
        memberships = [series[path]] if path in series else []
        if purpose["label"]:
            key = f"Purpose · {purpose['label']}"
            collections.setdefault(key, {"kind": "purpose", "members": []})["members"].append(path)
            memberships.append(key)
        if identity["label"]:
            confirmed = identity["state"] == "human_confirmed_identity"
            key = f"{'Confirmed' if confirmed else 'Proposed'} identity · {identity['label']}"
            collections.setdefault(key, {"kind": "identity", "members": []})["members"].append(path)
            memberships.append(key)

        relations = []
        for other, neighbor in assets.items():
            if other == path:
                continue
            distance = distances[frozenset((path, other))]
            model_similarity = None
            if asset["embedding"] is not None and neighbor["embedding"] is not None:
                model_similarity = sum(a * b for a, b in zip(asset["embedding"], neighbor["embedding"]))
            if distance <= RELATED or (model_similarity is not None and model_similarity >= 0.84):
                relations.append({"path": other, "state": "visually_similar" if distance <= SIMILAR else "possibly_related",
                                  "pixel_distance": round(distance, 4),
                                  "encoder_similarity": round(model_similarity, 4) if model_similarity is not None else None,
                                  "same_content": asset["digest"] == neighbor["digest"],
                                  "possible_variation": distance <= 0.035 and asset["digest"] != neighbor["digest"]})
        relations.sort(key=lambda item: (item["state"] != "visually_similar", item["pixel_distance"]))
        features = asset["features"]
        records[path] = {"digest": asset["digest"], "mtime_ns": asset["mtime_ns"], "width": features["width"],
                         "height": features["height"], "identity": identity, "purpose": purpose,
                         "collections": memberships, "relationships": relations[:3]}

    review_groups = defaultdict(list)
    for path, record in records.items():
        identity = record["identity"]
        if identity["state"] == "proposed_identity":
            review_groups[(series.get(path, path), identity["label"])].append(path)
    for (_, label), members in sorted(review_groups.items(), key=lambda item: (-len(item[1]), item[0])):
        questions.append({"kind": "identity", "label": label, "members": members,
                          "prompt": f"These images resemble the confirmed {label} example. Which, if any, depict {label}?"})
    for group in groups:
        unknown = [path for path in group if records[path]["purpose"]["state"] == "unknown"]
        if len(unknown) >= 2:
            questions.append({"kind": "purpose", "members": unknown,
                              "prompt": "These images share a composition. What purpose would you give this group?"})
    return records, collections, questions[:8]


def _fields(template):
    names = set()
    for _, name, spec, conversion in Formatter().parse(template):
        if name is None:
            continue
        if name not in FIELDS or spec or conversion:
            raise ValueError(f"Use only these naming fields: {', '.join(FIELDS)}.")
        names.add(name)
    return names


def validate_rule(project, filename, folder):
    if project:
        component(project)
    sample = {name: "Example" for name in FIELDS}
    for template in (filename, folder):
        if template:
            if len(template) > 200:
                raise ValueError("A naming template can contain up to 200 characters.")
            _fields(template)
            component(template.format_map(sample).strip())
    if not filename:
        raise ValueError("A filename template is required.")
    return {"project": project, "filename": filename, "folder": folder}


def draft_names(inventory, records, rule):
    draft = replace(inventory, collections=[], files={path: replace(file, name=PurePosixPath(path).name)
                                                       for path, file in inventory.files.items()})
    candidates = []
    for path, record in records.items():
        original = PurePosixPath(path)
        stamps = STAMP.findall(original.stem)
        versions = VERSION_TOKEN.findall(original.stem)
        identity, purpose = record["identity"], record["purpose"]
        info = {"state": "needs_identification", "destination": None, "filename_tokens": stamps + versions,
                "reason": "A confirmed identity and purpose are needed to draft a contextual name."}
        record["name"] = info
        if identity["state"] != "human_confirmed_identity" or purpose["state"] != "human_confirmed":
            continue
        review = identity["evidence"]
        values = {"project": rule["project"], "subject": identity["label"], "purpose": purpose["label"],
                  "variation": review.get("variation") or " - ".join(versions), "stamp": " - ".join(stamps)}
        try:
            required = _fields(rule["filename"]) | _fields(rule["folder"])
            if any(not values[field] for field in required):
                raise ValueError("The naming rule calls for a field with insufficient evidence.")
            stem = rule["filename"].format_map(values).strip()
            for token in dict.fromkeys([values["variation"], *versions, *stamps]):
                if token and token not in stem:
                    stem += f" - {token}"
            name = validate_name(original.name, stem + original.suffix)
            folder = rule["folder"].format_map(values).strip()
            if folder:
                existing = next((known for known in draft.collections if known.casefold() == folder.casefold()), None)
                draft.assign([path], existing or draft.add_collection(folder))
            draft.rename(path, name)
        except ValueError as error:
            info["reason"] = str(error)
            continue
        draft.files[path].decision = "Include"  # Reuse RC2 collision checks for the complete draft set.
        candidates.append(path)
        info["reason"] = "Uses the operator-confirmed subject and purpose with the saved naming rule. Keeps the original extension and observed filename tokens."

    previews = draft.proposals()
    for path in candidates:
        preview = previews[path]
        info = records[path]["name"]
        info["state"] = "blocked" if preview.blocker else ("matches_rule" if preview.change == "No change" else "proposed")
        info["destination"] = preview.destination
        info["blocker"] = preview.blocker
