"""Stage the locked Windows OCR runtime and package notices from MSYS2."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from hashlib import file_digest
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
from urllib.request import urlopen


MIRROR = "https://repo.msys2.org/mingw/ucrt64/"
MANIFEST = Path(__file__).with_name("windows") / "ocr-runtime.json"


def fetch_package(cache, entry):
    path = cache / entry["file"]
    if not path.is_file():
        partial = path.with_suffix(".partial")
        with urlopen(MIRROR + path.name, timeout=60) as source, partial.open("wb") as output:
            shutil.copyfileobj(source, output)
        partial.replace(path)
    with path.open("rb") as source:
        actual = file_digest(source, "sha256").hexdigest()
    if actual != entry["sha256"]:
        raise ValueError(f"Checksum mismatch for {path.name}. Remove the cached package and retry.")
    return path


@contextmanager
def package_contents(path):
    if sys.version_info >= (3, 14):
        with tarfile.open(path, "r:zst") as archive:
            yield archive
    else:
        with subprocess.Popen(["zstd", "-dc", str(path)], stdout=subprocess.PIPE) as decompressor:
            with tarfile.open(fileobj=decompressor.stdout, mode="r|") as archive:
                yield archive
            if decompressor.wait():
                raise ValueError(f"Could not decompress {path.name}.")


def stage_ocr(destination, cache):
    packages = json.loads(MANIFEST.read_text(encoding="utf-8"))
    cache.mkdir(parents=True, exist_ok=True)
    destination.mkdir()
    with ThreadPoolExecutor(max_workers=8) as executor:
        paths = list(executor.map(lambda entry: fetch_package(cache, entry), packages))
    for entry, path in zip(packages, paths):
        selected = set(entry["members"])
        with package_contents(path) as archive:
            for member in archive:
                if member.name not in selected or not member.isfile():
                    continue
                relative = PurePosixPath(member.name)
                output = destination / relative.name if relative.parts[1] == "bin" else destination.joinpath(*relative.parts[2:])
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, output.open("wb") as target:
                    shutil.copyfileobj(source, target)
                selected.remove(member.name)
        if selected:
            raise ValueError(f"Missing approved files in {path.name}: {', '.join(sorted(selected))}")
    shutil.copyfile(MANIFEST, destination / "THIRD-PARTY.json")
    (destination / "README.txt").write_text(
        "Tesseract OCR and English data, supplied as separate, replaceable MSYS2 UCRT64 binaries.\n"
        "THIRD-PARTY.json lists the upstream package hashes, licensing, and source archives.\n"
        "Package binaries are available at " + MIRROR + "\n"
        "Copyright and license files supplied with the binary packages are under licenses/.\n",
        encoding="utf-8",
    )
