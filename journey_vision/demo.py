"""Reproducible acceptance set with fictional subjects and public Journey art."""

from collections import Counter
from hashlib import file_digest
from itertools import combinations
import json
from pathlib import Path
from random import Random
import shutil
import tempfile

from journey_planner.catalog import scan_folder
from journey_vision.lab import Lab
from journey_vision.observe import observe
from journey_vision.steward import interpret


PUBLIC_ART = ("launch_crystal_art.png", "find_crystal_art.png", "guide_crystal_art.png", "manage_crystal_art.png")
PUBLIC_DIR = Path(__file__).resolve().parents[1] / "rainmeter/MiniARKTenderConsole/@Resources/Images/mini_ark_navigator_widget/assets"
PACKAGED_ART = Path(__file__).resolve().parents[1] / "vision-demo-art"
AUTHORITY = "scripted fixture reviewer"
PORTRAIT = "Character Artwork"
ICON = "Icons & Badges"
WALLPAPER = "Wallpaper candidates"
CONCEPT = "Concepts"
ASTER = "import_wallpaper_2026-10-18T14-23-51_v02.png"
BRIAR = "aster_final_02.png"
HOLDOUT = ("new_aster_study.png", "new_aster_take.png", "new_lookalike_01.png", "new_lookalike_02.png")


def _portrait(index, briar=False):
    from PIL import Image, ImageDraw

    shift = (index % 4) * 2 - 3
    pic = Image.new("RGB", (360, 440), (43 + index, 26, 74 + index))
    draw = ImageDraw.Draw(pic)
    draw.ellipse((31, 43, 329, 403), fill=(70, 45, 113), outline="#967dc8", width=2)
    draw.ellipse((73, 54, 287, 334), fill="#281637", outline="#c19dee", width=4)
    draw.polygon(((47, 440), (66, 332), (120, 293), (249, 293), (296, 328), (327, 440)),
                 fill="#874b95" if briar else "#264d73")
    draw.polygon(((107, 310), (172, 375), (251, 307), (224, 440), (143, 440)),
                 fill="#e681bf" if briar else "#6eb8d0")
    draw.ellipse((109 + shift, 111, 253 + shift, 294), fill="#a5737a", outline="#442544", width=4)
    draw.polygon(((90, 201), (92, 110), (149, 78), (236, 94), (276, 157), (260, 228), (225, 164),
                  (167, 155), (131, 221), (102, 257)), fill="#9062ba")
    for x in (143, 211):
        draw.ellipse((x + shift, 199, x + shift + 17, 215), fill="#21152e")
        draw.point((x + shift + 5, 203), fill="white")
    draw.arc((158, 232, 205, 258), 16, 153, fill="#482a48", width=3)
    if briar:
        draw.polygon(((209, 121), (245, 145), (215, 183), (187, 148)), fill="#f2cf9b")
        draw.line((214, 132, 214, 167), fill="#954c66", width=4)
    else:
        draw.ellipse((114, 112, 158, 155), fill="#f3ecb3")
        draw.ellipse((127, 108, 166, 143), fill="#9062ba")
    return pic


def _landscape(index, dusk):
    from PIL import Image, ImageDraw

    pic = Image.new("RGB", (960, 540))
    draw = ImageDraw.Draw(pic)
    for y in range(540):
        shade = int(y / 8)
        color = (83 + shade, 34 + shade // 2, 76 + shade) if dusk else (38 + shade, 85 + shade, 111 + shade)
        draw.line((0, y, 960, y), fill=color)
    horizon = 290 + index * 4
    draw.ellipse((665 + index * 3, 112, 736 + index * 3, 183), fill="#f1b5a4" if dusk else "#e8f8d5")
    draw.polygon(((0, horizon), (178, 135 if dusk else 230), (369, 299), (511, 175 if dusk else 254),
                  (778, 300), (960, 211), (960, 540), (0, 540)), fill="#39314d" if dusk else "#195e67")
    draw.rectangle((0, 347, 960, 540), fill="#4a385c" if dusk else "#237f89")
    for line in range(17):
        x = (index * 3 + line * 157) % 920
        y = 355 + line * 10
        draw.line((x, y, x + 28 + line * 4, y), fill="#72506a" if dusk else "#5eb4af", width=2)
    return pic


def _icon(index, clover):
    from PIL import Image, ImageDraw

    pic = Image.new("RGBA", (240, 240))
    draw = ImageDraw.Draw(pic)
    hue = (86 + index * 3, 197, 124, 255) if clover else (206, 147 + index * 4, 75, 255)
    if clover:
        for x, y in ((103, 55), (57, 102), (150, 102), (103, 150)):
            draw.ellipse((x - 32, y - 29, x + 32, y + 31), fill=hue, outline="#daf8b4", width=5)
        draw.line((105, 122, 125, 212), fill="#438d62", width=13)
    else:
        draw.ellipse((48, 48, 192, 192), outline=hue, width=18)
        draw.polygon(((120, 15), (137, 104), (221, 120), (137, 138), (120, 222), (104, 138), (19, 120), (104, 104)),
                     fill=hue, outline="#fff0bb")
    return pic


def _concept(index):
    from PIL import Image, ImageDraw

    pic = Image.new("RGB", (416, 288), (226, 214 + index, 197))
    draw = ImageDraw.Draw(pic)
    for x in range(16, 416, 16):
        draw.line((x, 0, x, 288), fill="#cec1b3")
    for y in range(16, 288, 16):
        draw.line((0, y, 416, y), fill="#cec1b3")
    random = Random(index)
    for x, y in ((50, 88), (167, 87), (290, 90)):
        jitter = random.randrange(-6, 7)
        draw.rectangle((x, y + jitter, x + 67, y + 58), outline="#493d42", width=2)
        draw.arc((x + 9, y + 10, x + 56, y + 48), 36, 298, fill="#5e5262", width=2)
        draw.line((x + 1, y + 83, x + 52, y + 79), fill="#7c6262", width=2)
    return pic


def make_sample(root, holdout, public_art=None):
    root.mkdir()
    holdout.mkdir()
    truth = {}

    def write(image, filename, purpose, series, identity="", later=False):
        image.save((holdout if later else root) / filename)
        truth[filename] = {"purpose": purpose, "series": series, "identity": identity}

    for index in range(6):
        a_name = ASTER if index == 0 else (HOLDOUT[index - 4] if index >= 4 else f"violet_design_{index}.png")
        b_name = BRIAR if index == 0 else (HOLDOUT[index - 2] if index >= 4 else f"aster_portrait_{index}.png")
        write(_portrait(index), a_name, PORTRAIT, "Purple portrait composition", "Aster", index >= 4)
        write(_portrait(index, True), b_name, PORTRAIT, "Purple portrait composition", "Briar", index >= 4)
    for index in range(6):
        write(_landscape(index, False), f"small_badge_{index}.png", WALLPAPER, "Coastal scenes")
    for index in range(4):
        write(_landscape(index, True), f"misc_landscape_{index}.png", WALLPAPER, "Dusk scenes")
        write(_concept(index), f"wallpaper_final_{index}.png", CONCEPT, "Diagram sketches")
    for index in range(5):
        write(_icon(index, False), f"orbit_{index}.png", ICON, "Orbit marks")
        write(_icon(index, True), f"clover_{index}.png", ICON, "Clover marks")
    directory = public_art or (PACKAGED_ART if PACKAGED_ART.is_dir() else PUBLIC_DIR)
    for index, filename in enumerate(PUBLIC_ART, 1):
        target = f"public_asset_{index}.png"
        shutil.copyfile(directory / filename, root / target)
        truth[target] = {"purpose": ICON, "series": "Public Journey crystals", "identity": "", "origin": filename}
    return truth


def _snapshot(folder):
    result = {}
    for path in folder.iterdir():
        with path.open("rb") as stream:
            result[path.name] = (file_digest(stream, "sha256").hexdigest(), path.stat().st_mtime_ns)
    return result


def quality(plan, truth):
    records = plan["assets"]
    inferred = [(path, record["purpose"]["label"]) for path, record in records.items()
                if record["purpose"]["state"] == "inferred"]
    identity_counts = Counter(record["identity"]["state"] for record in records.values())
    proposed = [(path, record["identity"]["label"]) for path, record in records.items()
                if record["identity"]["state"] == "proposed_identity"]
    confirmed = [(path, record["identity"]["label"]) for path, record in records.items()
                 if record["identity"]["state"] == "human_confirmed_identity"]
    paired = {frozenset(pair) for collection in plan["virtual_collections"].values() if collection["kind"] == "visual_series"
              for pair in combinations(collection["members"], 2)}
    expected = {frozenset((a, b)) for a, b in combinations(records, 2) if truth[a]["series"] == truth[b]["series"]}
    return {"automatic_purpose_assignments": len(inferred), "correct_automatic_purpose": sum(truth[p]["purpose"] == label for p, label in inferred),
            "unresolved_purpose": sum(record["purpose"]["state"] == "unknown" for record in records.values()),
            "identity_states": dict(identity_counts), "false_proposed_identity": sum(truth[p]["identity"] != label for p, label in proposed),
            "false_confirmed_identity": sum(truth[p]["identity"] != label for p, label in confirmed),
            "same_series_pairs": len(paired & expected), "grouped_pairs": len(paired), "expected_same_series_pairs": len(expected)}


def run_demo(parent, encoder=None):
    sample = Path(tempfile.mkdtemp(prefix="Journey-Vision-Sample-", dir=Path(parent).resolve()))
    root, holdout, workspace = sample / "Sample images", sample / "Holdout", sample / "Review"
    truth = make_sample(root, holdout)
    workspace.mkdir()
    before = _snapshot(root)
    initial = Lab(root, workspace).scan(encoder)
    lab = Lab(root, workspace)
    lab.set_rule(project="Field Studio", filename="{project} - {subject} - {purpose}", folder="{subject}")
    lab.review(ASTER, "confirm", label="Aster", purpose=PORTRAIT, authority=AUTHORITY)
    after_confirm = Lab(root, workspace).scan(encoder)
    if after_confirm["assets"][BRIAR]["identity"]["state"] != "proposed_identity":
        raise AssertionError("The fixture must expose a provisional look-alike error before correction.")
    Lab(root, workspace).review(BRIAR, "reject", label="Aster", authority=AUTHORITY)
    if _snapshot(root) != before:
        raise AssertionError("Initial source images changed.")
    for path in holdout.iterdir():
        shutil.copy2(path, root / path.name)
    before = _snapshot(root)
    final = Lab(root, workspace).scan(encoder)
    reopened = Lab(root, workspace)
    warm = reopened.scan(encoder, ["Generated acceptance sample. The fixture reviewer scripted two decisions through the lab review mechanism."])
    observations, _, _, _ = observe(scan_folder(root), reopened.data["cache"], encoder)
    counterfactual, _, _ = interpret(observations, reopened.data["cache"],
                                     [event for event in reopened.data["reviews"] if event["action"] != "reject"])
    if _snapshot(root) != before:
        raise AssertionError("The final source images changed.")
    report, plan_path = reopened.export(warm)
    comparison = {path: {"truth": truth[path]["identity"],
                         "without_rejection": counterfactual[path]["identity"]["label"] or "unknown",
                         "with_rejection": final["assets"][path]["identity"]["label"] or "unknown",
                         "with_rejection_state": final["assets"][path]["identity"]["state"]} for path in HOLDOUT}
    for item in comparison.values():
        expected = "Aster" if item["truth"] == "Aster" else "unknown"
        if item["without_rejection"] != "Aster" or item["with_rejection"] != expected:
            raise AssertionError("The retained rejection must change later look-alikes and preserve genuine proposals.")
    metrics = {"images": len(truth), "scripted_identity_interventions": 2, "source_preserved": True,
               "initial": initial["counts"], "after_confirmation": after_confirm["counts"],
               "after_rejection_and_new_images": final["counts"], "warm_reopen": warm["counts"],
               "quality_before_review": quality(initial, truth), "quality_after_confirmation": quality(after_confirm, truth),
               "quality_after_review": quality(final, truth),
               "holdout_comparison": comparison, "contextual_name": final["assets"][ASTER]["name"]}
    evidence = workspace / "Acceptance-metrics.json"
    evidence.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report, plan_path, evidence, metrics
