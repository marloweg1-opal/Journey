"""Build the standalone Journey x64 Windows ZIP with a pinned CPython runtime."""

import argparse
from hashlib import file_digest, sha256
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.request import urlretrieve
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
PYTHON_VERSION = "3.14.10"
TCL_VERSION = "9.0.4"
EMBED = f"python-{PYTHON_VERSION}-embed-amd64.zip"
DOWNLOADS = {
    EMBED: (EMBED, "90905e64a840557d8c1bc4f5b74db3d7ee85e3ffb217611cac1c7813acea4159"),
    "tcltk.msi": ("amd64/tcltk.msi", "9642593510b188aa35dcdf1995cbe2b3c3c07446a0ac1dd0c1d1958bf25526f5"),
}
ZIP_NAME = "Journey-1.0-RC1-Windows-x64.zip"
BUILD_FILES = ("launcher.c", "launcher.rc", "launcher.manifest")
APP_FILES = ("__init__.py", "__main__.py", "catalog.py", "desktop.py", "plan_file.py")


def fetch(cache, name):
    remote, checksum = DOWNLOADS[name]
    path = cache / name
    if not path.exists():
        urlretrieve(f"https://www.python.org/ftp/python/{PYTHON_VERSION}/{remote}", path)
    with path.open("rb") as stream:
        actual = file_digest(stream, "sha256").hexdigest()
    if actual != checksum:
        raise ValueError(f"Checksum mismatch for {path}. Remove the cache copy and rebuild.")
    return path


def extract_tk(installer, staging, runtime, msiextract):
    staging.mkdir()
    if os.name == "nt":
        subprocess.run(["msiexec.exe", "/a", str(installer), "/qn", f"TARGETDIR={staging}"], check=True)
    else:
        subprocess.run([msiextract, "-C", str(staging), str(installer)], check=True, stdout=subprocess.DEVNULL)

    shutil.copytree(staging / "Lib" / "tkinter", runtime / "tkinter",
                    ignore=shutil.ignore_patterns("__pycache__", "test", "tests"))
    dlls = runtime / "DLLs"
    dlls.mkdir()
    for name in ("_tkinter.pyd", "tcl90.dll", "tcl9tk90.dll", "libtommath.dll", "zlib1.dll"):
        shutil.copyfile(staging / "DLLs" / name, dlls / name)
    for library, folder in (("tcl", "tcl9.0"), ("tk", "tk9.0")):
        with ZipFile(staging / "tcl" / f"lib{library}{TCL_VERSION}.zip") as scripts:
            # Ship a real script directory so initialization works independently
            # of registry values or the user's TCL_LIBRARY / TK_LIBRARY settings.
            for member in scripts.namelist():
                path = PurePosixPath(member)
                if len(path.parts) < 2 or member.endswith("/"):
                    continue
                if path.parts[0] != f"{library}_library" or ".." in path.parts:
                    raise ValueError(f"Unexpected Tcl/Tk script archive path {member!r}")
                output = runtime / "tcl" / folder / Path(*path.parts[1:])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(scripts.read(member))
    for folder in ("dde1.4", "registry1.3"):
        shutil.copytree(staging / "tcl" / folder, runtime / "tcl" / folder)
    shutil.copyfile(staging / "tcl" / "tk9.0" / "demos" / "license.terms", runtime / "TCL-TK-LICENSE.txt")
    if not (runtime / "tcl" / "tcl9.0" / "init.tcl").is_file():
        raise RuntimeError("Tcl initialization script is missing.")
    if not (runtime / "tcl" / "tk9.0" / "tk.tcl").is_file():
        raise RuntimeError("Tk initialization script is missing.")


def bundle(output, cache, zig, msiextract):
    output.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    embedded = fetch(cache, EMBED)
    tk = fetch(cache, "tcltk.msi")
    with TemporaryDirectory(prefix="journey-build-") as temp:
        staging = Path(temp)
        package = staging / "Journey"
        runtime = package / "runtime"
        app = package / "app"
        runtime.mkdir(parents=True)
        with ZipFile(embedded) as archive:
            archive.extractall(runtime)
        (runtime / "python314._pth").write_text("python314.zip\n.\nDLLs\n../app\n", encoding="ascii")
        extract_tk(tk, staging / "tcltk", runtime, msiextract)

        (app / "journey_planner").mkdir(parents=True)
        for name in APP_FILES:
            shutil.copyfile(ROOT / "journey_planner" / name, app / "journey_planner" / name)
        (app / "core").mkdir()
        shutil.copyfile(ROOT / "core" / "file_paths.py", app / "core" / "file_paths.py")
        (app / "assets").mkdir()
        shutil.copyfile(ROOT / "assets" / "journey.ico", app / "assets" / "journey.ico")
        (package / "launcher-source").mkdir()
        for name in BUILD_FILES:
            shutil.copyfile(ROOT / "tools" / "windows" / name, package / "launcher-source" / name)
        shutil.copyfile(ROOT / "tools" / "windows" / "START-HERE.txt", package / "START-HERE.txt")
        shutil.copyfile(ROOT / "LICENSE", package / "LICENSE.txt")
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        (package / "BUILD.txt").write_text(
            f"Journey source commit: {commit}\n"
            "Source repository: https://github.com/marloweg1-opal/Journey\n"
            f"Windows CPython: {PYTHON_VERSION}\n"
            f"Tcl/Tk: {TCL_VERSION}\n"
            "Runtime source: https://www.python.org/downloads/release/python-31410/\n"
            "Journey launcher: unsigned x64 Windows executable\n",
            encoding="utf-8",
        )

        resources = staging / "launcher.res"
        subprocess.run([*zig, "rc", f"/fo{resources}", "tools/windows/launcher.rc"], cwd=ROOT, check=True)
        subprocess.run([
            *zig, "cc", "-target", "x86_64-windows-gnu", "-municode", "-Wl,--subsystem,windows", "-Os", "-s",
            "tools/windows/launcher.c", str(resources), "-o", str(package / "Journey.exe"),
        ], cwd=ROOT, check=True)
        zip_path = output / ZIP_NAME
        with ZipFile(zip_path, "w", ZIP_DEFLATED, compresslevel=6) as archive:
            for entry in sorted(package.rglob("*")):
                if entry.is_file():
                    archive.write(entry, entry.relative_to(staging))
    print(f"{zip_path}  {sha256(zip_path.read_bytes()).hexdigest()}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="Directory for the ZIP file")
    parser.add_argument("--cache", type=Path, required=True, help="Directory for the pinned runtime downloads")
    parser.add_argument("--zig", help="Path to Zig 0.15.2. Defaults to python -m ziglang.")
    parser.add_argument("--msiextract", default="msiextract", help="msiextract command for Linux builds")
    args = parser.parse_args()
    zig = [args.zig] if args.zig else [sys.executable, "-m", "ziglang"]
    bundle(args.output.resolve(), args.cache.resolve(), zig, args.msiextract)


if __name__ == "__main__":
    main()
