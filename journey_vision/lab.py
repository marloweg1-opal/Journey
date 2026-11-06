"""Local, scope-bound workspace for observation, review, and plan export."""

from datetime import datetime, timezone
from hashlib import sha256
from html import escape
import json
import os
from pathlib import Path
import stat
from time import perf_counter
from uuid import uuid4

from core.file_paths import safe_metadata
from journey_planner.catalog import MAX_PROJECT_BYTES, absolute_path, check_local_drive, component, relative_path, scan_folder
from journey_planner.plan_file import _output_path, _read, _write
from journey_vision.observe import FEATURE_VERSION, image_bytes, observe
from journey_vision.steward import DEFAULT_RULE, active_reviews, draft_names, interpret, review_index, validate_rule


STATE_FORMAT = "journey-vision-lab-1"
MAX_REVIEWS = 400


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Lab:
    def __init__(self, root, workspace):
        root = absolute_path(root)
        check_local_drive(root)
        if not stat.S_ISDIR(safe_metadata(root).st_mode):
            raise ValueError("Choose a local folder to inspect.")
        self.root = root.resolve(strict=True)
        self.state_path = _output_path(self.root, absolute_path(workspace) / "Journey-Vision-State.json", ".json")
        self.revision = None
        self.data = {"format": STATE_FORMAT, "root": str(self.root), "feature_version": FEATURE_VERSION,
                     "cache": {}, "last": {}, "reviews": [], "rule": dict(DEFAULT_RULE)}
        if os.path.lexists(self.state_path):
            raw = _read(self.state_path)
            try:
                saved = json.loads(raw)
                if saved["format"] != STATE_FORMAT or Path(saved["root"]) != self.root:
                    raise ValueError("This workspace belongs to a different source or format.")
                if not all(isinstance(saved[key], kind) for key, kind in
                           (("cache", dict), ("last", dict), ("reviews", list), ("rule", dict))):
                    raise ValueError("Invalid workspace state.")
                if saved["feature_version"] != FEATURE_VERSION:
                    raise ValueError("This workspace uses a different visual descriptor version.")
                validate_rule(**saved["rule"])
            except (KeyError, TypeError, AttributeError) as error:
                raise ValueError("This is not a compatible Journey Vision Lab workspace.") from error
            self.data = saved
            self.revision = sha256(raw).hexdigest()

    def save(self):
        data = (json.dumps(self.data, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
        if len(data) > MAX_PROJECT_BYTES:
            raise ValueError("The workspace reached its 24 MiB limit. Choose a fresh workspace for another sample.")
        self.revision = _write(self.root, self.state_path, ".json", data, self.revision)

    def scan(self, encoder=None, notes=()):
        start = perf_counter()
        inventory = scan_folder(self.root)
        cache = self.data["cache"]
        assets, skipped, counts, limitations = observe(inventory, cache, encoder)
        records, collections, questions = interpret(assets, cache, self.data["reviews"])
        draft_names(inventory, records, self.data["rule"])
        self.data["last"] = {path: item["digest"] for path, item in assets.items()}
        retained = {*self.data["last"].values(), *(event["digest"] for event in self.data["reviews"] if "digest" in event)}
        self.data["cache"] = {digest: entry for digest, entry in cache.items() if digest in retained}
        self.save()
        return {"format": "journey-vision-review-plan-1", "source": str(self.root), "observed_at": inventory.scanned_at,
                "descriptors": FEATURE_VERSION, "encoder": encoder.identifier if counts["model_runs"] or any(
                    item["embedding"] is not None for item in assets.values()) else None,
                "counts": {**counts, "analyzed": len(records), "virtual_collections": len(collections),
                           "questions": len(questions), "seconds": round(perf_counter() - start, 4)},
                "notes": [*notes, *limitations], "skipped": {**inventory.gaps, **skipped},
                "naming_rule": self.data["rule"], "reviews": self.data["reviews"].copy(),
                "assets": records, "virtual_collections": collections, "questions": questions}

    def review(self, path, action, *, label="", purpose="", variation="", authority="local operator"):
        if action not in ("confirm", "reject", "purpose"):
            raise ValueError("Choose confirm, reject, or purpose.")
        path = relative_path(path)
        digest = self.data["last"].get(path)
        if not digest or sha256(image_bytes(self.root / path)).hexdigest() != digest:
            raise ValueError("The selected image is outside the last scan or has changed. Scan again before reviewing.")
        label, purpose, variation = label.strip(), purpose.strip(), variation.strip()
        if action in ("confirm", "reject"):
            component(label)
        if action == "purpose" or purpose:
            component(purpose)
        if variation:
            component(variation)
        if action == "confirm":
            identities, _ = review_index(self.data["reviews"])
            conflicts = [e["label"] for key, e in identities.get(digest, {}).items()
                         if e["action"] == "confirm" and key != label.casefold()]
            if conflicts:
                raise ValueError(f"This image is confirmed as {conflicts[0]}. Reject or undo that decision before replacing it.")
        return self._append({"action": action, "path": path, "digest": digest, "label": label, "purpose": purpose,
                             "variation": variation, "authority": authority})

    def undo(self, *, authority="local operator"):
        reviews = active_reviews(self.data["reviews"])
        if not reviews:
            raise ValueError("There are no active decisions to undo.")
        return self._append({"action": "undo", "target": reviews[-1]["id"], "authority": authority})

    def _append(self, event):
        if len(self.data["reviews"]) >= MAX_REVIEWS:
            raise ValueError("This experiment supports up to 400 review events per workspace.")
        record = {"id": uuid4().hex, "at": _now(), **event}
        self.data["reviews"].append(record)
        try:
            self.save()
        except (ValueError, OSError):
            self.data["reviews"].pop()
            raise
        return record

    def set_rule(self, **settings):
        previous = self.data["rule"]
        self.data["rule"] = validate_rule(**settings)
        try:
            self.save()
        except (ValueError, OSError):
            self.data["rule"] = previous
            raise

    def export(self, plan):
        basename = datetime.now().strftime("Journey-Vision-%Y%m%d-%H%M%S-") + uuid4().hex[:6]
        report = self.state_path.with_name(f"{basename}.html")
        plan_path = report.with_suffix(".json")
        data = json.dumps(plan, ensure_ascii=True, indent=2) + "\n"
        _write(self.root, plan_path, ".json", data.encode("utf-8"))
        report_text = report_html(plan, self.data["cache"])
        _write(self.root, report, ".html", report_text.encode("utf-8", errors="backslashreplace"))
        return report, plan_path


def report_html(plan, cache):
    def safe(value):
        return escape(str(value))

    assets = plan["assets"]
    numbers = {path: number for number, path in enumerate(assets, 1)}

    def links(paths):
        return " · ".join(f'<a href="#asset-{numbers[path]}">#{numbers[path]}</a>' for path in paths)

    questions = "".join(f'<li>{safe(item["prompt"])}<br>{links(item["members"])}</li>' for item in plan["questions"])
    collections = "".join(f'<li>{safe(label)} <span class="muted">({len(group["members"])})</span><br>{links(group["members"])}</li>'
                          for label, group in plan["virtual_collections"].items())
    cards = []
    for path, record in assets.items():
        identity, purpose, name = record["identity"], record["purpose"], record["name"]
        identity_label = identity["label"] or ", ".join(e["label"] for e in identity.get("rejections", [])) or "Open"
        label = f"{identity_label} · {identity['state'].replace('_', ' ')}"
        thumb = safe(cache[record["digest"]]["features"]["thumbnail"])
        neighbors = " · ".join(f'<a href="#asset-{numbers[item["path"]]}">#{numbers[item["path"]]}</a> '
                               + ("same content" if item["same_content"] else "possible variation" if item["possible_variation"]
                                  else safe(item["state"].replace("_", " "))) for item in record["relationships"])
        suppressed = ", ".join(entry["label"] for entry in identity.get("suppressed", []))
        physical = name["destination"] or "Name needs identification"
        cards.append(f'''<article id="asset-{numbers[path]}"><img src="data:image/webp;base64,{thumb}" alt="Thumbnail of {safe(path)}">
<h3>#{numbers[path]} <span class="path">{safe(path)}</span></h3>
<p><strong>{safe(label)}</strong><br>{safe(identity["reason"])}</p>
{f'<p>Suppressed by a correction · {safe(suppressed)}</p>' if suppressed else ''}
<p><strong>{safe(purpose["label"] or "Purpose open")}</strong> · {safe(purpose["state"].replace("_", " "))}<br>{safe(purpose["reason"])}</p>
<p class="muted">{neighbors}</p><details><summary>Physical naming preview</summary>
<p class="path">{safe(physical)}</p><p>{safe(name["reason"])} {safe(name.get("blocker", ""))}</p></details></article>''')
    warnings = "".join(f"<li>{safe(note)}</li>" for note in plan["notes"])
    warnings += "".join(f'<li><span class="path">{safe(path)}</span> · {safe(reason)}</li>' for path, reason in plan["skipped"].items())
    count = plan["counts"]
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">
<title>Journey Vision Lab | Review</title><style>
body{{margin:0;background:#f2f6f2;color:#1a2c29;font:16px/1.5 system-ui,sans-serif}} main{{max-width:1260px;margin:auto;padding:28px 20px 60px}}
header{{background:#123b36;color:white;padding:24px;border-radius:14px}} h1,h2,h3,p{{margin:.25em 0 .6em}} h1{{font-size:2rem}} h3{{font-size:1rem}}
.path{{overflow-wrap:anywhere}} .muted{{color:#475e54}} a{{color:#175843}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(245px,1fr));gap:12px}}
section{{margin:20px 0}} article,.panel{{background:white;border:1px solid #d5dfd8;border-radius:10px;padding:13px}} article:target{{outline:3px solid #257754}}
img{{width:100%;height:112px;object-fit:contain;background:#465266;border-radius:6px}} summary{{cursor:pointer;font-weight:600}} li{{margin:.35em 0}} .caption{{color:#b6e4ce}}
</style></head><body><main><header><div class="caption">JOURNEY · LOCAL VISUAL EXPERIMENT</div><h1>Image review</h1>
<p class="path">{safe(plan["source"])}</p><p>{count["analyzed"]} images · {count["virtual_collections"]} virtual collections · {count["questions"]} review questions · {count["cache_hits"]} cached</p></header>
<section class="panel"><h2>Review questions</h2><p>Use the numbered images in the Vision Lab console to record an answer. Each answer is tied to the selected image.</p>
<ul>{questions or "<li>There are no grouped questions for this scan. You can still review an individual image.</li>"}</ul></section>
<section class="panel"><h2>Virtual collections</h2><p>An image can belong to several collections. Physical destinations are separate previews.</p><ul>{collections or "<li>No collection has enough evidence yet.</li>"}</ul></section>
{f'<section class="panel"><h2>Coverage</h2><ul>{warnings}</ul></section>' if warnings else ''}
<section><h2>Inspected images</h2><div class="grid">{''.join(cards)}</div></section>
<p class="muted">Local snapshot. Review questions, suggested identities, and naming previews grant no permission to change source files.</p>
</main></body></html>'''
