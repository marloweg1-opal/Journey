"""Bundle the existing Navigator shell and isolated inspection backend."""

import argparse
from hashlib import file_digest
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

from build_windows_ocr import stage_ocr
from build_windows_planner import EMBED, PYTHON_VERSION, ROOT, fetch
from build_windows_vision_lab import PILLOW_SHA


ZIP_NAME = "Journey-Navigator-Guided-Patrol-Windows-x64.zip"


def build(output, cache, wheel, zig):
    cache.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    with wheel.open("rb") as stream:
        if file_digest(stream, "sha256").hexdigest() != PILLOW_SHA:
            raise ValueError("Use the pinned Pillow 12.2.0 Windows x64 wheel.")
    with TemporaryDirectory(prefix="journey-navigator-build-") as temporary:
        staging = Path(temporary)
        package = staging / "Journey Navigator"
        app, runtime = package / "app", package / "runtime"
        runtime.mkdir(parents=True)
        with ZipFile(fetch(cache, EMBED)) as archive:
            archive.extractall(runtime)
        (runtime / "python314._pth").write_text("python314.zip\n.\n../app\n", encoding="ascii")
        with ZipFile(wheel) as archive:
            archive.extractall(app)
        stage_ocr(package / "ocr", cache / "ocr")
        modules = {
            "journey_navigator": ("__init__.py", "__main__.py", "context.py", "links.py", "ocr.py", "workbench.py",
                                  "inspection.html", "inspection.js", "inspection.css", "approval.py", "guided.py", "migrations.py",
                                  "patrol.py", "patrol.html", "patrol.js", "session.py", "install.py", "registry.py",
                                  "conversation.py", "project_audit.py", "stewardship.py", "history.py", "capabilities.py",
                                  "watch.py", "project_pack.py", "project_ui.js"),
            "journey_planner": ("__init__.py", "catalog.py"),
            "journey_vision": ("__init__.py", "observe.py", "steward.py"),
            "core": tuple(item.name for item in (ROOT / 'core').glob('*.py')),
            "db": ("database.py", "schema.sql"),
        }
        for module, names in modules.items():
            destination = app / module
            destination.mkdir()
            for name in names:
                shutil.copyfile(ROOT / module / name, destination / name)
        shutil.copyfile(ROOT / "index.html", app / "index.html")
        profile = app / "examples" / "carebloom"
        profile.mkdir(parents=True)
        shutil.copyfile(ROOT / "examples" / "carebloom" / "project_tokens.json", profile / "project_tokens.json")
        shutil.copyfile(ROOT / "docs/NAVIGATOR_PATROL.md", package / "START-HERE.md")
        shutil.copyfile(ROOT / "LICENSE", package / "LICENSE.txt")
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        (package / "BUILD.txt").write_text(f"Journey source commit {commit}\nCPython {PYTHON_VERSION}\nPillow 12.2.0\nTesseract OCR 5.5.4 (English)\n", encoding="utf-8")
        approval = package / 'Journey Approval.exe'
        subprocess.run([*zig, 'cc', '-target', 'x86_64-windows-gnu', '-municode', '-Os', '-s',
                        'tools/windows/approve.c', '-lcredui', '-ladvapi32', '-lole32', '-o', str(approval)], cwd=ROOT, check=True)
        with approval.open('rb') as stream:
            (package / 'approval.sha256').write_text(file_digest(stream,'sha256').hexdigest(),encoding='ascii')
        resources = staging / "navigator.res"
        subprocess.run([*zig, "rc", f"/fo{resources}", "tools/windows/navigator.rc"], cwd=ROOT, check=True)
        subprocess.run([*zig, "cc", "-target", "x86_64-windows-gnu", "-municode", "-Wl,--subsystem,windows", "-Os", "-s",
                        '-DJOURNEY_MODULE=L"journey_navigator"', '-DJOURNEY_TITLE=L"Journey Navigator"',
                        "tools/windows/launcher.c", str(resources), "-o", str(package / "Journey Navigator.exe")], cwd=ROOT, check=True)
        subprocess.run([*zig, 'cc', '-target', 'x86_64-windows-gnu', '-municode', '-Wl,--subsystem,windows', '-Os', '-s',
                        '-DJOURNEY_MODULE=L"journey_navigator.install"', '-DJOURNEY_TITLE=L"Journey Setup"',
                        'tools/windows/launcher.c',str(resources),'-o',str(package/'Setup Journey.exe')],cwd=ROOT,check=True)
        import json
        checksums={}
        for item in sorted(package.rglob('*')):
            if item.is_file():
                with item.open('rb') as source:
                    checksums[item.relative_to(package).as_posix()]=file_digest(source,'sha256').hexdigest()
        (package/'MANIFEST.json').write_text(json.dumps(checksums,indent=2)+'\n',encoding='utf-8')
        destination = output / ZIP_NAME
        with ZipFile(destination, "w", ZIP_DEFLATED, compresslevel=6) as archive:
            for item in sorted(package.rglob("*")):
                if item.is_file():
                    archive.write(item, item.relative_to(staging))
    with destination.open("rb") as stream:
        print(f"{destination}  {file_digest(stream, 'sha256').hexdigest()}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--pillow-wheel", required=True, type=Path)
    parser.add_argument("--zig")
    args = parser.parse_args()
    zig = [args.zig] if args.zig else [sys.executable, "-m", "ziglang"]
    build(args.output.resolve(), args.cache.resolve(), args.pillow_wheel.resolve(), zig)


if __name__ == "__main__":
    main()
