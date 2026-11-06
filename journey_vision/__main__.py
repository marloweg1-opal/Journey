"""Run the offline Vision Lab and open its visual review sheet."""

import argparse
import json
from pathlib import Path
import tempfile
import webbrowser

from journey_vision import VERSION
from journey_vision.demo import run_demo
from journey_vision.lab import Lab


def path_from(text):
    value = text.strip().strip('"')
    if not value:
        raise ValueError("Enter a folder path.")
    return Path(value).expanduser().absolute()


def _encoder(filename):
    if not filename:
        return None, []
    from journey_vision.embedding import ClipEncoder

    try:
        return ClipEncoder(path_from(filename)), []
    except (ImportError, OSError, ValueError, RuntimeError) as error:
        return None, [f"Optional CLIP encoder unavailable. Pixel analysis is active. {error}"]


def _inspect(lab, encoder=None, notes=()):
    print("Inspecting the selected folder and comparing image contents…", flush=True)
    plan = lab.scan(encoder, notes)
    report, output = lab.export(plan)
    count = plan["counts"]
    print(f"{count['analyzed']} images · {count['virtual_collections']} virtual collections · "
          f"{count['questions']} grouped questions · {count['cache_hits']} cache hits · {count['seconds']:.2f}s")
    for question in plan["questions"]:
        print(f"  {question['prompt']} ({len(question['members'])} images)")
    for note in plan["notes"]:
        print(f"  {note}")
    print(f"Review sheet   {report}\nPlan           {output}")
    return plan, report


def _interactive():
    print(f"Journey Vision Lab {VERSION} | Local image review")
    print("D  Run the included 40-image demonstration\nI  Inspect a folder I choose\nQ  Quit")
    choice = input("> ").strip().lower()
    if choice == "d":
        parent = input("Where should the example go? Enter uses your temporary folder.\n> ").strip()
        report, output, evidence, _ = run_demo(path_from(parent) if parent else tempfile.gettempdir())
        print(f"Review sheet   {report}\nPlan           {output}\nMeasurements   {evidence}")
        if input("Open the review sheet? [y/N] ").strip().lower() == "y":
            webbrowser.open(report.as_uri())
        return
    if choice != "i":
        return
    print("This lab reads up to 50 raster images. Its workspace stores local thumbnails, decisions, and plans.")
    source = path_from(input("Source folder to inspect\n> "))
    workspace = path_from(input("Existing workspace folder outside the source\n> "))
    lab = Lab(source, workspace)
    plan, report = _inspect(lab)
    while True:
        print("\nO  Open review sheet    R  Review an image    U  Undo last review\n"
              "N  Set naming rule     S  Scan again         Q  Quit")
        try:
            command = input("> ").strip().lower()
            if command == "q":
                return
            if command == "o":
                webbrowser.open(report.as_uri())
                continue
            if command == "r":
                paths = list(plan["assets"])
                number = int(input("Image number from the current review sheet\n> "))
                if not 1 <= number <= len(paths):
                    raise ValueError("Enter an image number from the current review sheet.")
                path = paths[number - 1]
                identity = plan["assets"][path]["identity"]
                print(f"{path}\nIdentity evidence   {identity['label'] or 'Open'} · {identity['state'].replace('_', ' ')}")
                action = input("Type confirm, reject, or purpose. Enter cancels.\n> ").strip().lower()
                if not action:
                    continue
                if action not in ("confirm", "reject", "purpose"):
                    raise ValueError("Choose confirm, reject, or purpose.")
                label = input("Identity to record\n> ") if action in ("confirm", "reject") else ""
                purpose = input("Asset purpose (optional when confirming identity)\n> ") if action != "reject" else ""
                variation = input("Known variation or version (optional)\n> ") if action == "confirm" else ""
                lab.review(path, action, label=label, purpose=purpose, variation=variation)
                print("Review saved.")
            elif command == "u":
                lab.undo()
                print("Last review retracted.")
            elif command == "n":
                print("Naming fields are {project}, {subject}, {purpose}, {variation}, and {stamp}.")
                project = input("Project label (optional)\n> ").strip()
                filename = input("Filename pattern, without the extension\n> ").strip()
                folder = input("Single destination folder pattern, or Enter to keep current folders\n> ").strip()
                lab.set_rule(project=project, filename=filename, folder=folder)
            elif command != "s":
                continue
            plan, report = _inspect(lab)
        except (OSError, ValueError) as error:
            print(f"Could not complete the request. {error}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command")
    demo = commands.add_parser("demo", help="Run the included acceptance demonstration")
    demo.add_argument("--output", default=tempfile.gettempdir(), help="Existing parent folder for generated test files")
    demo.add_argument("--clip", help="Optional pinned CLIP image encoder file")
    for command in ("scan", "review", "undo", "rule"):
        sub = commands.add_parser(command)
        sub.add_argument("source", help="Local source folder to inspect")
        sub.add_argument("workspace", help="Existing local folder outside the source")
        if command == "scan":
            sub.add_argument("--clip", help="Optional pinned CLIP image encoder file")
        elif command == "review":
            sub.add_argument("path", help="Image path relative to the source, using forward slashes")
            sub.add_argument("action", choices=("confirm", "reject", "purpose"))
            sub.add_argument("--label", default="")
            sub.add_argument("--purpose", default="")
            sub.add_argument("--variation", default="")
        elif command == "rule":
            sub.add_argument("--project", default="")
            sub.add_argument("--filename", required=True)
            sub.add_argument("--folder", default="")
    args = parser.parse_args()
    try:
        if args.command is None:
            _interactive()
        elif args.command == "demo":
            encoder, notes = _encoder(args.clip)
            for note in notes:
                print(note)
            report, output, evidence, metrics = run_demo(path_from(args.output), encoder)
            print(f"Review sheet   {report}\nPlan           {output}\nMeasurements   {evidence}")
            print(json.dumps(metrics, ensure_ascii=True, indent=2))
        else:
            lab = Lab(path_from(args.source), path_from(args.workspace))
            if args.command == "scan":
                encoder, notes = _encoder(args.clip)
                _inspect(lab, encoder, notes)
            elif args.command == "review":
                event = lab.review(args.path, args.action, label=args.label, purpose=args.purpose, variation=args.variation)
                print(f"Saved {event['action']} review. Scan again to refresh the plan.")
            elif args.command == "undo":
                lab.undo()
                print("Last review retracted. Scan again to refresh the plan.")
            else:
                lab.set_rule(project=args.project, filename=args.filename, folder=args.folder)
                print("Saved the naming rule. Scan again to refresh the plan.")
    except (EOFError, KeyboardInterrupt):
        print("\nVision Lab closed.")
    except (OSError, ValueError, ImportError, AssertionError) as error:
        parser.exit(1, f"Vision Lab could not complete the request. {error}\n")


if __name__ == "__main__":
    main()
