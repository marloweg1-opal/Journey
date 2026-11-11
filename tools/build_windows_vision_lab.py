"""Package the standalone Windows x64 lab with pinned Python and Pillow."""

import argparse
from hashlib import file_digest
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

from build_windows_planner import EMBED, PYTHON_VERSION, ROOT, fetch


PILLOW_WHEEL = "pillow-12.2.0-cp314-cp314-win_amd64.whl"
PILLOW_SHA = "4e6c62e9d237e9b65fac06857d511e90d8461a32adcc1b9065ea0c0fa3a28150"
ZIP_NAME = "Journey-Vision-Lab-0.1-Windows-x64.zip"
PUBLIC_ART = ("launch_crystal_art.png", "find_crystal_art.png", "guide_crystal_art.png", "manage_crystal_art.png")


def build(output, cache, wheel):
    cache.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    with wheel.open("rb") as stream:
        if file_digest(stream, "sha256").hexdigest() != PILLOW_SHA:
            raise ValueError(f"Use the pinned {PILLOW_WHEEL} wheel.")
    with TemporaryDirectory(prefix="journey-vision-build-") as temp:
        staging = Path(temp)
        package = staging / "Journey Vision Lab"
        runtime, app = package / "runtime", package / "app"
        runtime.mkdir(parents=True)
        with ZipFile(fetch(cache, EMBED)) as archive:
            archive.extractall(runtime)
        (runtime / "python314._pth").write_text("python314.zip\n.\n../app\n", encoding="ascii")
        with ZipFile(wheel) as archive:
            archive.extractall(app)
        for module, files in (
            ("journey_vision", sorted(path.name for path in (ROOT / "journey_vision").glob("*.py"))),
            ("journey_planner", ("__init__.py", "catalog.py", "plan_file.py")),
            ("core", ("file_paths.py",)),
        ):
            target = app / module
            target.mkdir()
            for name in files:
                shutil.copyfile(ROOT / module / name, target / name)
        art = ROOT / "rainmeter/MiniARKTenderConsole/@Resources/Images/mini_ark_navigator_widget/assets"
        (app / "vision-demo-art").mkdir()
        for name in PUBLIC_ART:
            shutil.copyfile(art / name, app / "vision-demo-art" / name)
        for filename in ("Start Vision Lab.cmd", "VISION-START-HERE.txt"):
            shutil.copyfile(ROOT / "tools/windows" / filename, package / filename)
        shutil.copyfile(ROOT / "docs/VISUAL_LAB.md", package / "VISUAL-LAB.md")
        shutil.copyfile(ROOT / "LICENSE", package / "LICENSE.txt")
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        (package / "BUILD.txt").write_text(f"Journey source commit {commit}\nCPython {PYTHON_VERSION}\nPillow 12.2.0\n", encoding="utf-8")
        destination = output / ZIP_NAME
        with ZipFile(destination, "w", ZIP_DEFLATED, compresslevel=6) as archive:
            for member in sorted(package.rglob("*")):
                if member.is_file():
                    archive.write(member, member.relative_to(staging))
    with destination.open("rb") as stream:
        print(f"{destination}  {file_digest(stream, 'sha256').hexdigest()}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--pillow-wheel", required=True, type=Path)
    args = parser.parse_args()
    build(args.output.resolve(), args.cache.resolve(), args.pillow_wheel.resolve())


if __name__ == "__main__":
    main()
