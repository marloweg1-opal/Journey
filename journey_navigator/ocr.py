"""Local text recognition on the pixels already authorized for inspection."""

import csv
from hashlib import file_digest, sha256
from io import BytesIO, StringIO
import os
from pathlib import Path
import re
import shutil
import subprocess


PIPELINE = "tesseract-eng-sparse-1600-v2"
TIMEOUT = 3
MAX_SIDE = 1600
MAX_LINES = 160
MIN_WORD_CONFIDENCE = 25


class LocalOcr:
    def __init__(self, executable, data_dir=None):
        self.executable = Path(executable).resolve(strict=True)
        self.data_args = ("--tessdata-dir", str(Path(data_dir).resolve(strict=True))) if data_dir else ()
        version = self._run(("--version",)).splitlines()[0].strip()
        available = self._run(("--list-langs", *self.data_args))
        if not version.startswith("tesseract ") or "eng" not in available.splitlines():
            raise ValueError("The local text reader requires Tesseract and its English language data.")
        listed = re.search(r'"([^"\n]+)"', available)
        if data_dir is None and listed:
            data_dir = listed[1]
        fingerprint = "system"
        if data_dir:
            with (Path(data_dir) / "eng.traineddata").open("rb") as model:
                fingerprint = file_digest(model, "sha256").hexdigest()
        self.version = version
        self.model = fingerprint
        self.key = sha256(f"{PIPELINE}:{version}:{fingerprint}".encode()).hexdigest()

    def _run(self, args, data=None):
        env = {key: value for key, value in os.environ.items()
               if key.upper() not in {"TESSDATA_PREFIX", "OMP_NUM_THREADS", "OMP_THREAD_LIMIT"}}
        env.update(OMP_THREAD_LIMIT="1", OMP_NUM_THREADS="1")
        result = subprocess.run([str(self.executable), *args], input=data, capture_output=True,
                                cwd=self.executable.parent, env=env, timeout=TIMEOUT, check=True,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        return result.stdout.decode("utf-8", errors="replace")

    def recognize(self, image):
        from PIL import Image

        reduced = image.copy()
        reduced.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
        background = Image.new("RGBA", reduced.size, "white")
        background.alpha_composite(reduced)
        with BytesIO() as png:
            background.convert("L").save(png, format="PNG")
            pixels = png.getvalue()
        text = self._run(("stdin", "stdout", *self.data_args, "-l", "eng", "--oem", "1",
                          "--psm", "11", "tsv"), pixels)
        lines = {}
        raw_text = False
        for row in csv.DictReader(StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE):
            try:
                value = (row["text"] or "").strip()[:240]
                raw_text |= bool(value)
                confidence = float(row["conf"])
                if not value or confidence < MIN_WORD_CONFIDENCE:
                    continue
                key = row["block_num"], row["par_num"], row["line_num"]
                top = int(row["top"]) / reduced.height
                word = value, confidence, top
                lines.setdefault(key, []).append(word)
            except (KeyError, TypeError, ValueError):
                continue
        rows = [{"text": " ".join(item[0] for item in words)[:500],
                 "confidence": round(min(item[1] for item in words), 1),
                 "top": round(min(item[2] for item in words), 3)}
                for words in list(lines.values())[:MAX_LINES]]
        readable = any(row["confidence"] >= 60 and any(re.search(r"[aeiouy]", word, re.I)
                       for word in re.findall(r"[^\W\d_]{3,}", row["text"])) for row in rows)
        status = "read" if readable else "unreliable" if raw_text else "no_text"
        return {"status": status, "lines": rows, "provider": self.version,
                "language": "eng", "model": self.model, "pipeline": PIPELINE}


def find_local_ocr():
    if os.name == "nt":
        bundled = Path(__file__).resolve().parents[2] / "ocr"
        folders = [bundled]
        program_files = os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles")
        if program_files:
            folders.append(Path(program_files) / "Tesseract-OCR")
        candidates = [(folder / "tesseract.exe", folder / "tessdata") for folder in folders]
    else:
        executable = shutil.which("tesseract")
        candidates = [(Path(executable), None)] if executable else []
    for executable, data in candidates:
        if not executable.is_file():
            continue
        try:
            return LocalOcr(executable, data)
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            continue
    return None
