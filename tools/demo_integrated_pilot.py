"""Create a small, wholly invented Journey demonstration in a new directory."""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

from core.project_registry import PATTERN_FORMAT


def illustration(path, dimensions, color):
    image = Image.new("RGB", dimensions, "#142639")
    drawing = ImageDraw.Draw(image)
    width, height = dimensions
    drawing.rounded_rectangle((20, 20, width - 20, height - 20), radius=18, outline=color, width=6)
    for index in range(1, 5):
        x = width * index // 5
        drawing.ellipse((x - 18, height // 2 - 18, x + 18, height // 2 + 18), fill=color)
    image.save(path)


def native_record(conversation, messages, title="Studio Fixture"):
    return {"id": conversation, "title": title, "mapping": {
        identifier: {"id": identifier, "parent": messages[index - 1][0] if index else None,
                     "message": {"id": identifier, "author": {"role": role}, "create_time": 1780000000 + index,
                                 "content": {"parts": [text, *parts]}}}
        for index, (identifier, role, text, parts) in enumerate(messages)}}


def make_demo(base):
    base.mkdir()
    collection, exports = base / "Collection copies", base / "Local exports"
    collection.mkdir()
    exports.mkdir()
    (collection / "Archive").mkdir()
    for filename, dimensions, color in (
        ("render_a.png", (1100, 640), "#5de3af"), ("Old Drawing Desk.png", (320, 220), "#ffaa67"),
        ("Clarity Desk.png", (380, 240), "#ed95b8")):
        illustration(collection / filename, dimensions, color)
    (collection / "Old Drawing Desk history.md").write_text("A previous design referenced Old Drawing Desk.png.\n", encoding="utf-8")
    profile = {"format": PATTERN_FORMAT, "project": "Studio Fixture", "signals": ["Studio Fixture"], "rules": []}
    pack = base / "Studio-fixture-pack.json"
    pack.write_text(json.dumps({"format": "journey-project-pack-1", "profile": profile}), encoding="utf-8")
    tick = chr(96)
    message = ("demo-panel", "user", f"For Studio Fixture, {tick}render_a.png{tick} is a CareRail interface layout.",
               [{"content_type": "image_asset_pointer", "asset_pointer": "sediment://file_synthetic", "width": 1100, "height": 640}])
    relation = ("demo-revision", "user", f"For Studio Fixture, {tick}Clarity Desk.png{tick} replaces {tick}Old Drawing Desk.png{tick}.", [])
    notes = ("demo-unrelated", "user", "Private example text excluded from the project index.", [])
    (exports / "conversations-001.json").write_text(json.dumps([native_record("demo-original", [message, relation]),
        native_record("demo-unrelated", [notes], title="Unrelated sample")]), encoding="utf-8")
    (exports / "conversations-002.json").write_text(json.dumps([native_record("demo-branch", [message])]), encoding="utf-8")
    return collection, exports, pack


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="New directory for the synthetic demo")
    args = parser.parse_args()
    for path in make_demo(args.output.resolve()):
        print(path)
