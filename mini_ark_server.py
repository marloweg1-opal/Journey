"""Local Mini ARK Navigator server.

Serves the static Navigator and exposes localhost-only retrieval over
Mini ARK's SQLite ledger plus durable Markdown docs.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import stat
import threading
import binascii
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parent
PUBLIC_STATIC_PATHS = frozenset({'/index.html'})
DB_PATH = ROOT / "ark.sqlite"
DOCS_ROOT = ROOT / "docs"
ARK_CMD = ROOT / "ark.cmd"
LOGS_ROOT = ROOT / "logs"
ASSET_PIPELINE_ROOT = ROOT / "asset_pipeline"
ASSET_INBOX = ASSET_PIPELINE_ROOT / "inbox"
ASSET_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
DEFAULT_TIMEOUT_SECONDS = 120
MEDIA_INVENTORY_LOCK = threading.Lock()
# Trusted host integration only. Browser payloads cannot supply a policy, scope,
# ledger, approval or limits. No production assessment grant is installed.
ASSESSMENT_POLICY = None
ASSESSMENT_LOCK = threading.Lock()
PREVIEW_LOCK = threading.RLock()
PREVIEW_RECEIPTS = {}
DURABLE_DOC_PREFIXES = (
    "CASUAL_CONGRUENCY_MVP_HANDOFF",
    "CANONICAL_PLACEMENT_DOCTRINE",
    "HANDBOOK",
    "USER_GUIDE",
    "CODEX_HANDOFF",
    "HEXSEED_EXPRESSION_FRAMEWORK",
    "JOURNEY_NAMING_ARCHITECTURE",
    "MINI_ARK_STATUS",
    "R_DRIVE_DOCTRINE",
    "PROJECT_BOUNDARIES",
    "STEWARDSHIP_RELEASE_CANDIDATE_HANDOFF",
    "ASSET_PIPELINE_DOCTRINE",
)

SYSTEM_NOISE_PREFIXES = (
    r"R:\Windows",
    r"R:\Program Files",
    r"R:\Program Files (x86)",
    r"R:\ProgramData",
    r"R:\System Volume Information",
    r"R:\$RECYCLE.BIN",
)

ACTION_DEFS = {
    'recovery-status': {'title':'Recovery & Repair','mode':'manage','risk':'green'},
    'media-inventory-resume': {'title':'Continue Media Inventory','mode':'manage','risk':'green'},
    'perception-policy': {'title':'Perception Policy','mode':'manage','risk':'green'},
    "patrol-status": {"title": "Patrol Status", "mode": "manage", "risk": "green"},
    "doctor": {
        "title": "Diagnostics",
        "mode": "launch",
        "risk": "green",
        "command": [str(ARK_CMD), "doctor"],
        "timeout": 60,
    },
    "brief": {
        "title": "Current Brief",
        "mode": "launch",
        "risk": "green",
        "command": [str(ARK_CMD), "brief"],
        "timeout": 60,
    },
    "token-registry": {
        "title": "Token Registry",
        "mode": "manage",
        "risk": "green",
        "command": [str(ARK_CMD), "tokens"],
        "timeout": 60,
    },
    "route-registry": {
        "title": "Project Routes",
        "mode": "manage",
        "risk": "green",
        "command": [str(ARK_CMD), "routes"],
        "timeout": 60,
    },
    "placement-doctrine": {
        "title": "Placement Doctrine",
        "mode": "manage",
        "risk": "green",
        "command": [str(ARK_CMD), "placement"],
        "timeout": 60,
    },
    "stewardship-contract": {
        "title": "Stewardship Contract",
        "mode": "manage",
        "risk": "green",
        "command": [str(ARK_CMD), "stewardship-contract"],
        "timeout": 60,
    },
    "shadow-run": {
        "title": "Shadow Run",
        "mode": "launch",
        "risk": "green",
        "timeout": 180,
    },
    "expression-slots": {
        "title": "Expression Slots",
        "mode": "manage",
        "risk": "green",
        "command": [str(ARK_CMD), "expression-slots"],
        "timeout": 60,
    },
    "placement-check": {
        "title": "Placement Check",
        "mode": "launch",
        "risk": "green",
        "timeout": 60,
    },
    "inventory-r": {
        "title": "Inventory Scan",
        "mode": "launch",
        "risk": "green",
        "command": [str(ARK_CMD), "inventory", "--under", "R:\\"],
        "timeout": 180,
    },
    "duplicates-r": {
        "title": "Duplicate Review",
        "mode": "launch",
        "risk": "green",
        "command": [str(ARK_CMD), "check-duplicates", "--under", "R:\\"],
        "timeout": 120,
    },
    "diagnose-r": {
        "title": "Path Diagnostics",
        "mode": "launch",
        "risk": "green",
        "command": [str(ARK_CMD), "diagnose", "--under", "R:\\"],
        "timeout": 180,
    },
    "reservations": {
        "title": "Reservations",
        "mode": "manage",
        "risk": "green",
        "command": [str(ARK_CMD), "list-reservations"],
        "timeout": 60,
    },
    "receipts": {
        "title": "Operation Receipts",
        "mode": "manage",
        "risk": "green",
        "command": [str(ARK_CMD), "receipts"],
        "timeout": 60,
    },
    "name-preview": {
        "title": "Name Preview",
        "mode": "launch",
        "risk": "green",
        "timeout": 60,
    },
    "date-index": {
        "title": "Date Index",
        "mode": "launch",
        "risk": "green",
        "timeout": 180,
    },
    "photo-taxonomy": {
        "title": "Photo Slideshow Taxonomy",
        "mode": "launch",
        "risk": "green",
        "command": [str(ARK_CMD), "photo-taxonomy"],
        "timeout": 60,
    },
    "asset-pipeline-doctrine": {
        "title": "Asset Pipeline Doctrine",
        "mode": "manage",
        "risk": "green",
        "builtin": "asset_pipeline_doctrine",
    },
    "naming-status": {
        "title": "Naming Status",
        "mode": "manage",
        "risk": "green",
        "builtin": "naming_status",
    },
    "expression-framework": {
        "title": "Expression Framework",
        "mode": "manage",
        "risk": "green",
        "builtin": "expression_framework",
    },
    "logs": {
        "title": "Logs",
        "mode": "manage",
        "risk": "green",
        "builtin": "logs",
    },
    "tests": {
        "title": "Test Suite",
        "mode": "manage",
        "risk": "green",
        "command": [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        "timeout": 120,
    },
    "git-status": {
        "title": "Git State",
        "mode": "manage",
        "risk": "green",
        "command": ["git", "status", "-sb"],
        "timeout": 30,
    },
    "profile-migration-plan": {
        "title": "R Profile Migration Map",
        "mode": "launch",
        "risk": "yellow",
        "command": [str(ARK_CMD), "profile-migration-map"],
        "timeout": 300,
    },
    "r-hierarchy-scan": {
        "title": "R: Hierarchy Scan",
        "mode": "launch",
        "risk": "green",
        "command": [str(ARK_CMD), "r-hierarchy-scan"],
        "timeout": 240,
    },
    "assets-deconstruct-inbox": {
        "title": "Asset Sheet Deconstructor",
        "mode": "launch",
        "risk": "yellow",
        "command": [sys.executable, "-m", "asset_pipeline", "run-inbox"],
        "timeout": 300,
    },
    "assets-intake": {
        "title": "Asset Intake",
        "mode": "launch",
        "risk": "yellow",
        "timeout": 900,
    },
    "assets-auto-deconstruct": {
        "title": "Smart Asset Intake",
        "mode": "launch",
        "risk": "yellow",
        "timeout": 300,
    },
    "assets-compose-master": {
        "title": "Batch Master Composer",
        "mode": "launch",
        "risk": "yellow",
        "timeout": 600,
    },
    "assets-nine-slice": {
        "title": "9-Slice Builder",
        "mode": "launch",
        "risk": "yellow",
        "timeout": 120,
    },
    "assets-treat": {
        "title": "Asset Treatment Bench",
        "mode": "launch",
        "risk": "yellow",
        "timeout": 120,
    },
    "assets-precision-icons": {
        "title": "Icon Precision Pass",
        "mode": "launch",
        "risk": "green",
        "timeout": 120,
    },
    "assets-repair-icons": {
        "title": "Asset Repair Pass",
        "mode": "launch",
        "risk": "green",
        "timeout": 120,
    },
    "assets-review-job": {
        "title": "Asset Job Review",
        "mode": "launch",
        "risk": "green",
        "timeout": 120,
    },
    "assets-approve-job": {
        "title": "Approve Asset Job",
        "mode": "launch",
        "risk": "yellow",
        "timeout": 120,
    },
    "assets-brief": {
        "title": "Recipe-Bound ImageGen Brief",
        "mode": "launch",
        "risk": "green",
        "timeout": 60,
    },
}


def _json_response(handler: SimpleHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


MAX_REQUEST_BODY_BYTES = 32 * 1024 * 1024


class RequestBodyError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _unique_request_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate request field')
        result[key] = value
    return result


def _read_json_body(handler: SimpleHTTPRequestHandler) -> dict:
    if handler.headers.get('Transfer-Encoding'):
        raise RequestBodyError('Transfer-Encoding is not supported.')
    if handler.headers.get('Content-Encoding', 'identity').lower() != 'identity':
        raise RequestBodyError('Compressed request bodies are not supported.', 415)
    lengths = handler.headers.get_all('Content-Length', [])
    if len(lengths) > 1:
        raise RequestBodyError('Ambiguous Content-Length.')
    value = lengths[0] if lengths else '0'
    if not value.isascii() or not value.isdecimal() or len(value) > 10:
        raise RequestBodyError('Invalid Content-Length.')
    length = int(value)
    if length > MAX_REQUEST_BODY_BYTES:
        raise RequestBodyError('Request exceeds the 32 MiB body limit; use a local asset path.', 413)
    if length == 0:
        return {}
    raw = handler.rfile.read(length)
    if len(raw) != length:
        raise RequestBodyError('Incomplete request body.')
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_request_fields)
    except (UnicodeError, ValueError, RecursionError):
        raise RequestBodyError('Request must contain a valid UTF-8 JSON object.') from None
    if not isinstance(payload, dict):
        raise RequestBodyError('Request must contain a JSON object.')
    return payload


def _run_command(command: list[str], timeout: int = DEFAULT_TIMEOUT_SECONDS) -> dict:
    if command and command[0] == str(ARK_CMD):
        command = [sys.executable, "-B", str(ROOT / "ark.py"), *command[1:]]
    started = time.time()
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
            env=env,
        )
        output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
        return {
            "ok": completed.returncode == 0,
            "exit_code": completed.returncode,
            "duration_seconds": round(time.time() - started, 2),
            "output": output,
        }
    except subprocess.TimeoutExpired as exc:
        output = "\n".join(part.decode("utf-8", errors="replace") if isinstance(part, bytes) else part
                           for part in (exc.stdout or "", exc.stderr or "") if part).strip()
        return {
            "ok": False,
            "exit_code": None,
            "duration_seconds": round(time.time() - started, 2),
            "output": output,
            "error": f"Timed out after {timeout} seconds.",
        }
    except OSError as exc:
        return {
            "ok": False,
            "exit_code": None,
            "duration_seconds": round(time.time() - started, 2),
            "output": "",
            "error": str(exc),
        }


def _safe_asset_filename(name: str) -> str:
    cleaned = Path(str(name or "asset-sheet.png")).name.strip()
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", cleaned).strip(" .")
    if not cleaned:
        cleaned = "asset-sheet.png"
    path = Path(cleaned)
    suffix = path.suffix.lower()
    if suffix not in ASSET_SUFFIXES:
        cleaned = f"{cleaned}.png"
    return cleaned


def _normalize_local_path(raw_path: str) -> Path:
    value = str(raw_path or "").strip().strip('"')
    marker = "file:///"
    marker_index = value.lower().find(marker)
    if marker_index >= 0:
        value = value[marker_index:]
    if value.lower().startswith("file:///"):
        parsed = urlparse(value)
        value = unquote(parsed.path).lstrip("/")
        if len(value) >= 3 and value[1] == ":":
            value = value.replace("/", "\\")
    elif value.lower().startswith("file://"):
        parsed = urlparse(value)
        value = unquote(parsed.path or parsed.netloc).lstrip("/")
        if len(value) >= 3 and value[1] == ":":
            value = value.replace("/", "\\")
    return Path(value)


def _asset_destination(filename: str) -> Path:
    ASSET_INBOX.mkdir(parents=True, exist_ok=True)
    candidate = ASSET_INBOX / _safe_asset_filename(filename)
    if not candidate.exists():
        return candidate
    stamp = time.strftime("%Y%m%d-%H%M%S")
    stem = candidate.stem
    suffix = candidate.suffix
    indexed = ASSET_INBOX / f"{stem}__{stamp}{suffix}"
    counter = 2
    while indexed.exists():
        indexed = ASSET_INBOX / f"{stem}__{stamp}-{counter}{suffix}"
        counter += 1
    return indexed


def _archive_asset_inbox_file(path: Path) -> Path:
    try:
        if path.resolve().parent != ASSET_INBOX.resolve():
            return path
    except OSError:
        return path
    archive = ASSET_INBOX / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    destination = archive / path.name
    if destination.exists():
        stamp = time.strftime("%Y%m%d-%H%M%S")
        destination = archive / f"{path.stem}__{stamp}{path.suffix}"
        counter = 2
        while destination.exists():
            destination = archive / f"{path.stem}__{stamp}-{counter}{path.suffix}"
            counter += 1
    shutil.move(str(path), str(destination))
    return destination


def _copy_asset_path_to_inbox(raw_path: str) -> Path:
    source = _normalize_local_path(raw_path)
    if not source.exists() or not source.is_file():
        raise ValueError("Asset sheet path must point to an existing file.")
    if source.suffix.lower() not in ASSET_SUFFIXES:
        raise ValueError(f"Unsupported asset sheet type: {source.suffix or '(none)'}")
    try:
        if source.resolve().parent == ASSET_INBOX.resolve():
            return source
    except OSError:
        pass
    destination = _asset_destination(source.name)
    try:
        if source.resolve() == destination.resolve():
            return destination
    except OSError:
        pass
    shutil.copy2(source, destination)
    return destination


def _write_asset_upload_to_inbox(filename: str, data_base64: str) -> Path:
    if not data_base64:
        raise ValueError("Uploaded asset sheet is empty.")
    encoded = str(data_base64)
    if "," in encoded and encoded.lstrip().lower().startswith("data:"):
        encoded = encoded.split(",", 1)[1]
    destination = _asset_destination(filename)
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Uploaded asset sheet was not valid base64.") from exc
    if not content:
        raise ValueError("Uploaded asset sheet is empty.")
    destination.write_bytes(content)
    return destination


def asset_deconstruct_from_payload(payload: dict) -> tuple[dict, int]:
    saved_to = None
    try:
        if payload.get("path"):
            saved_to = _copy_asset_path_to_inbox(str(payload.get("path")))
        elif payload.get("data_base64"):
            saved_to = _write_asset_upload_to_inbox(
                str(payload.get("filename") or "asset-sheet.png"),
                str(payload.get("data_base64") or ""),
            )
    except ValueError as exc:
        return {"ok": False, "action": "assets-deconstruct-inbox", "error": str(exc)}, 400
    result = _run_command(
        ACTION_DEFS["assets-deconstruct-inbox"]["command"],
        timeout=ACTION_DEFS["assets-deconstruct-inbox"].get("timeout", DEFAULT_TIMEOUT_SECONDS),
    )
    return {
        "ok": result["ok"],
        "action": "assets-deconstruct-inbox",
        "title": ACTION_DEFS["assets-deconstruct-inbox"]["title"],
        "saved_to": str(saved_to) if saved_to else None,
        **result,
    }, 200


def _save_payload_asset(payload: dict, default_filename: str = "asset-sheet.png") -> Path | None:
    if payload.get("path"):
        return _copy_asset_path_to_inbox(str(payload.get("path")))
    if payload.get("data_base64"):
        return _write_asset_upload_to_inbox(
            str(payload.get("filename") or default_filename),
            str(payload.get("data_base64") or ""),
        )
    return None


def _save_payload_assets(payload: dict) -> list[Path]:
    saved: list[Path] = []
    paths = payload.get("paths")
    if isinstance(paths, list):
        for raw_path in paths:
            if str(raw_path).strip():
                saved.append(_copy_asset_path_to_inbox(str(raw_path)))
    elif payload.get("path"):
        raw_paths = [part.strip() for part in re.split(r"[\r\n]+", str(payload.get("path"))) if part.strip()]
        for raw_path in raw_paths:
            saved.append(_copy_asset_path_to_inbox(raw_path))

    files = payload.get("files")
    if isinstance(files, list):
        for index, file_payload in enumerate(files, start=1):
            if not isinstance(file_payload, dict):
                continue
            saved.append(
                _write_asset_upload_to_inbox(
                    str(file_payload.get("filename") or f"asset-sheet-{index}.png"),
                    str(file_payload.get("data_base64") or ""),
                )
            )
    elif payload.get("data_base64"):
        saved_asset = _save_payload_asset(payload)
        if saved_asset is not None:
            saved.append(saved_asset)

    unique: list[Path] = []
    seen: set[str] = set()
    for path in saved:
        key = str(path.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def asset_auto_deconstruct_from_payload(payload: dict) -> tuple[dict, int]:
    try:
        saved_to = _save_payload_asset(payload)
        if saved_to is None:
            raise ValueError("Asset sheet path or upload is required.")
        command = [
            sys.executable,
            "-m",
            "asset_pipeline",
            "auto-deconstruct",
            str(saved_to),
            "--alpha-threshold",
            str(_int_payload(payload, "alpha_threshold", 8)),
            "--min-area",
            str(_int_payload(payload, "min_area", 5000)),
            "--padding",
            str(_int_payload(payload, "padding", 0)),
            "--group",
            str(payload.get("group", "detected_assets")).strip() or "detected_assets",
            "--name-prefix",
            str(payload.get("name_prefix", "asset")).strip() or "asset",
        ]
        if payload.get("complete", True):
            command.append("--complete")
            command.extend(["--complete-min-area", str(_int_payload(payload, "complete_min_area", 300))])
            command.extend(["--split-alpha-threshold", str(_int_payload(payload, "split_alpha_threshold", 32))])
        job = str(payload.get("job", "")).strip()
        if job:
            command.extend(["--job", job])
    except ValueError as exc:
        return {"ok": False, "action": "assets-auto-deconstruct", "error": str(exc)}, 400
    result = _run_command(command, timeout=ACTION_DEFS["assets-auto-deconstruct"].get("timeout", DEFAULT_TIMEOUT_SECONDS))
    archived_to = _archive_asset_inbox_file(saved_to) if result["ok"] else None
    return {
        "ok": result["ok"],
        "action": "assets-auto-deconstruct",
        "title": ACTION_DEFS["assets-auto-deconstruct"]["title"],
        "saved_to": str(saved_to),
        "archived_to": str(archived_to) if archived_to else None,
        **result,
    }, 200


def asset_compose_master_from_payload(payload: dict) -> tuple[dict, int]:
    try:
        saved = _save_payload_assets(payload)
        if len(saved) < 2:
            raise ValueError("At least two asset sheets are required for a master compose.")
        command = [
            sys.executable,
            "-m",
            "asset_pipeline",
            "compose-master",
            *[str(path) for path in saved],
            "--alpha-threshold",
            str(_int_payload(payload, "alpha_threshold", 8)),
            "--min-area",
            str(_int_payload(payload, "min_area", 5000)),
            "--complete",
            "--complete-min-area",
            str(_int_payload(payload, "complete_min_area", 300)),
            "--split-alpha-threshold",
            str(_int_payload(payload, "split_alpha_threshold", 32)),
            "--input-padding",
            str(_int_payload(payload, "input_padding", 0)),
            "--gutter",
            str(_int_payload(payload, "gutter", 48)),
            "--margin",
            str(_int_payload(payload, "margin", 96)),
            "--group",
            str(payload.get("group", "master_assets")).strip() or "master_assets",
            "--group-mode",
            str(payload.get("group_mode", "keep_separate")).strip() or "keep_separate",
            "--name-prefix",
            str(payload.get("name_prefix", "asset")).strip() or "asset",
        ]
        cell_size = str(payload.get("cell_size", "")).strip()
        columns = str(payload.get("columns", "")).strip()
        job = str(payload.get("job", "")).strip()
        if cell_size:
            command.extend(["--cell-size", str(_int_payload(payload, "cell_size"))])
        if columns:
            command.extend(["--columns", str(_int_payload(payload, "columns"))])
        if job:
            command.extend(["--job", job])
    except ValueError as exc:
        return {"ok": False, "action": "assets-compose-master", "error": str(exc)}, 400
    result = _run_command(command, timeout=ACTION_DEFS["assets-compose-master"].get("timeout", DEFAULT_TIMEOUT_SECONDS))
    archived = []
    if result["ok"]:
        for path in saved:
            archived_path = _archive_asset_inbox_file(path)
            archived.append(str(archived_path))
    return {
        "ok": result["ok"],
        "action": "assets-compose-master",
        "title": ACTION_DEFS["assets-compose-master"]["title"],
        "saved_to": [str(path) for path in saved],
        "archived_to": archived,
        **result,
    }, 200


def asset_intake_from_payload(payload: dict) -> tuple[dict, int]:
    try:
        saved = _save_payload_assets(payload)
        if not saved:
            raise ValueError("At least one asset sheet is required.")
        command = [
            sys.executable,
            "-m",
            "asset_pipeline",
            "asset-intake",
            *[str(path) for path in saved],
            "--alpha-threshold",
            str(_int_payload(payload, "alpha_threshold", 8)),
            "--min-area",
            str(_int_payload(payload, "min_area", 5000)),
            "--complete-min-area",
            str(_int_payload(payload, "complete_min_area", 300)),
            "--split-alpha-threshold",
            str(_int_payload(payload, "split_alpha_threshold", 32)),
            "--precision-padding",
            str(_int_payload(payload, "precision_padding", 8)),
            "--repair-min-component-area",
            str(_int_payload(payload, "repair_min_component_area", 24)),
            "--max-fill-ratio",
            str(_float_payload(payload, "max_fill_ratio", 0.08)),
            "--group-mode",
            str(payload.get("group_mode", "keep_separate")).strip() or "keep_separate",
            "--archive-inputs",
        ]
        job = str(payload.get("job", "")).strip()
        family = str(payload.get("family", "")).strip()
        label = str(payload.get("label", "")).strip()
        if job:
            command.extend(["--job", job])
        if family:
            command.extend(["--family", family])
        if label:
            command.extend(["--label", label])
        if bool(payload.get("no_auto_approve")):
            command.append("--no-auto-approve")
        if bool(payload.get("allow_duplicates")):
            command.append("--allow-duplicates")
    except ValueError as exc:
        return {"ok": False, "action": "assets-intake", "error": str(exc)}, 400
    result = _run_command(command, timeout=ACTION_DEFS["assets-intake"].get("timeout", DEFAULT_TIMEOUT_SECONDS))
    return {
        "ok": result["ok"],
        "action": "assets-intake",
        "title": ACTION_DEFS["assets-intake"]["title"],
        "saved_to": [str(path) for path in saved],
        **result,
    }, 200


def _required_asset_path(payload: dict) -> str:
    raw_path = str(payload.get("path", "")).strip()
    if not raw_path:
        raise ValueError("Asset path is required.")
    path = _normalize_local_path(raw_path)
    if not path.exists() or not path.is_file():
        raise ValueError("Asset path must point to an existing file.")
    if path.suffix.lower() not in ASSET_SUFFIXES:
        raise ValueError(f"Unsupported asset type: {path.suffix or '(none)'}")
    return str(path)


def _int_payload(payload: dict, key: str, default: int | None = None) -> int:
    value = payload.get(key, default)
    if value is None or value == "":
        raise ValueError(f"{key} is required.")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer.") from exc


def _float_payload(payload: dict, key: str, default: float = 0.0) -> float:
    value = payload.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number.") from exc


def asset_nine_slice_from_payload(payload: dict) -> tuple[dict, int]:
    try:
        path = _required_asset_path(payload)
        command = [
            sys.executable,
            "-m",
            "asset_pipeline",
            "nine-slice",
            path,
        ]
        supplied_any = False
        for key in ("left", "top", "right", "bottom"):
            if str(payload.get(key, "")).strip():
                command.extend([f"--{key}", str(_int_payload(payload, key))])
                supplied_any = True
        if not supplied_any:
            command.append("--auto")
        job = str(payload.get("job", "")).strip()
        if job:
            command.extend(["--job", job])
    except ValueError as exc:
        return {"ok": False, "action": "assets-nine-slice", "error": str(exc)}, 400
    result = _run_command(command, timeout=ACTION_DEFS["assets-nine-slice"].get("timeout", DEFAULT_TIMEOUT_SECONDS))
    return {"ok": result["ok"], "action": "assets-nine-slice", "title": ACTION_DEFS["assets-nine-slice"]["title"], **result}, 200


def asset_treat_from_payload(payload: dict) -> tuple[dict, int]:
    try:
        path = _required_asset_path(payload)
        command = [sys.executable, "-m", "asset_pipeline", "treat", path]
        job = str(payload.get("job", "")).strip()
        if job:
            command.extend(["--job", job])
        if bool(payload.get("trim")):
            command.append("--trim")
        padding = _int_payload(payload, "padding", 0)
        if padding:
            command.extend(["--padding", str(padding)])
        max_width = str(payload.get("max_width", "")).strip()
        max_height = str(payload.get("max_height", "")).strip()
        if max_width:
            command.extend(["--max-width", str(_int_payload(payload, "max_width"))])
        if max_height:
            command.extend(["--max-height", str(_int_payload(payload, "max_height"))])
        tint = str(payload.get("tint", "")).strip()
        if tint:
            command.extend(["--tint", tint, "--tint-strength", str(_float_payload(payload, "tint_strength", 0.0))])
        shadow_blur = _int_payload(payload, "shadow_blur", 0)
        shadow_offset_x = _int_payload(payload, "shadow_offset_x", 0)
        shadow_offset_y = _int_payload(payload, "shadow_offset_y", 0)
        shadow_opacity = _int_payload(payload, "shadow_opacity", 128)
        if shadow_blur or shadow_offset_x or shadow_offset_y:
            command.extend(
                [
                    "--shadow-blur",
                    str(shadow_blur),
                    "--shadow-offset-x",
                    str(shadow_offset_x),
                    "--shadow-offset-y",
                    str(shadow_offset_y),
                    "--shadow-opacity",
                    str(shadow_opacity),
                ]
            )
    except ValueError as exc:
        return {"ok": False, "action": "assets-treat", "error": str(exc)}, 400
    result = _run_command(command, timeout=ACTION_DEFS["assets-treat"].get("timeout", DEFAULT_TIMEOUT_SECONDS))
    return {"ok": result["ok"], "action": "assets-treat", "title": ACTION_DEFS["assets-treat"]["title"], **result}, 200


def asset_precision_icons_from_payload(payload: dict) -> tuple[dict, int]:
    try:
        job = str(payload.get("job", "")).strip()
        if not job:
            raise ValueError("Job name is required.")
        command = [
            sys.executable,
            "-m",
            "asset_pipeline",
            "precision-icons",
            job,
            "--padding",
            str(_int_payload(payload, "padding", 8)),
            "--alpha-threshold",
            str(_int_payload(payload, "alpha_threshold", 1)),
        ]
        target_size = str(payload.get("target_size", "")).strip()
        if target_size:
            command.extend(["--target-size", target_size])
        if bool(payload.get("not_square")):
            command.append("--not-square")
    except ValueError as exc:
        return {"ok": False, "action": "assets-precision-icons", "error": str(exc)}, 400
    result = _run_command(command, timeout=ACTION_DEFS["assets-precision-icons"].get("timeout", DEFAULT_TIMEOUT_SECONDS))
    return {
        "ok": result["ok"],
        "action": "assets-precision-icons",
        "title": ACTION_DEFS["assets-precision-icons"]["title"],
        **result,
    }, 200


def asset_repair_icons_from_payload(payload: dict) -> tuple[dict, int]:
    try:
        job = str(payload.get("job", "")).strip()
        if not job:
            raise ValueError("Job name is required.")
        command = [
            sys.executable,
            "-m",
            "asset_pipeline",
            "repair-icons",
            job,
            "--alpha-threshold",
            str(_int_payload(payload, "alpha_threshold", 1)),
            "--min-component-area",
            str(_int_payload(payload, "min_component_area", 24)),
        ]
        if bool(payload.get("keep_largest_component")):
            command.append("--keep-largest-component")
        if not bool(payload.get("smooth_alpha", True)):
            command.append("--no-smooth-alpha")
        if bool(payload.get("reshape_candidate")):
            command.append("--reshape-candidate")
            command.extend(["--max-fill-ratio", str(_float_payload(payload, "max_fill_ratio", 0.08))])
    except ValueError as exc:
        return {"ok": False, "action": "assets-repair-icons", "error": str(exc)}, 400
    result = _run_command(command, timeout=ACTION_DEFS["assets-repair-icons"].get("timeout", DEFAULT_TIMEOUT_SECONDS))
    return {
        "ok": result["ok"],
        "action": "assets-repair-icons",
        "title": ACTION_DEFS["assets-repair-icons"]["title"],
        **result,
    }, 200


def asset_review_job_from_payload(payload: dict) -> tuple[dict, int]:
    job = str(payload.get("job", "")).strip()
    if not job:
        return {"ok": False, "action": "assets-review-job", "error": "Job name is required."}, 400
    command = [sys.executable, "-m", "asset_pipeline", "review-job", job]
    result = _run_command(command, timeout=ACTION_DEFS["assets-review-job"].get("timeout", DEFAULT_TIMEOUT_SECONDS))
    return {
        "ok": result["ok"],
        "action": "assets-review-job",
        "title": ACTION_DEFS["assets-review-job"]["title"],
        **result,
    }, 200


def asset_approve_job_from_payload(payload: dict) -> tuple[dict, int]:
    job = str(payload.get("job", "")).strip()
    if not job:
        return {"ok": False, "action": "assets-approve-job", "error": "Job name is required."}, 400
    command = [sys.executable, "-m", "asset_pipeline", "approve-job", job]
    family = str(payload.get("family", "")).strip()
    label = str(payload.get("label", "")).strip()
    if family:
        command.extend(["--family", family])
    if label:
        command.extend(["--label", label])
    result = _run_command(command, timeout=ACTION_DEFS["assets-approve-job"].get("timeout", DEFAULT_TIMEOUT_SECONDS))
    return {
        "ok": result["ok"],
        "action": "assets-approve-job",
        "title": ACTION_DEFS["assets-approve-job"]["title"],
        **result,
    }, 200


def asset_brief_from_payload(payload: dict) -> tuple[dict, int]:
    try:
        job = str(payload.get("job", "")).strip()
        slots = str(payload.get("slots", "")).strip()
        if not job:
            raise ValueError("Job name is required.")
        if not slots:
            raise ValueError("Asset slots are required.")
        command = [
            sys.executable,
            "-m",
            "asset_pipeline",
            "brief",
            "--job",
            job,
            "--slots",
            slots,
            "--columns",
            str(_int_payload(payload, "columns", 3)),
            "--cell-width",
            str(_int_payload(payload, "cell_width", 512)),
            "--cell-height",
            str(_int_payload(payload, "cell_height", 512)),
            "--gutter-x",
            str(_int_payload(payload, "gutter_x", 48)),
            "--gutter-y",
            str(_int_payload(payload, "gutter_y", 48)),
            "--margin-x",
            str(_int_payload(payload, "margin_x", 96)),
            "--margin-y",
            str(_int_payload(payload, "margin_y", 96)),
            "--background",
            str(payload.get("background", "transparent")).strip() or "transparent",
            "--group",
            str(payload.get("group", "generated_assets")).strip() or "generated_assets",
        ]
        safe_zone_width = str(payload.get("safe_zone_width", "")).strip()
        safe_zone_height = str(payload.get("safe_zone_height", "")).strip()
        style = str(payload.get("style", "")).strip()
        if safe_zone_width:
            command.extend(["--safe-zone-width", str(_int_payload(payload, "safe_zone_width"))])
        if safe_zone_height:
            command.extend(["--safe-zone-height", str(_int_payload(payload, "safe_zone_height"))])
        if style:
            command.extend(["--style", style])
    except ValueError as exc:
        return {"ok": False, "action": "assets-brief", "error": str(exc)}, 400
    result = _run_command(command, timeout=ACTION_DEFS["assets-brief"].get("timeout", DEFAULT_TIMEOUT_SECONDS))
    return {"ok": result["ok"], "action": "assets-brief", "title": ACTION_DEFS["assets-brief"]["title"], **result}, 200


def _connect() -> sqlite3.Connection | None:
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _terms(query: str) -> list[str]:
    return [term.strip().lower() for term in query.split() if term.strip()]


def _matches(text: str, terms: list[str]) -> bool:
    haystack = text.lower()
    return all(term in haystack for term in terms)


def _match_score(text: str, terms: list[str]) -> int:
    haystack = text.lower()
    return sum(1 for term in terms if term in haystack)


def _snippet(text: str, terms: list[str], width: int = 180) -> str:
    cleaned = " ".join(text.split())
    if not cleaned:
        return ""
    lower = cleaned.lower()
    positions = [lower.find(term) for term in terms if lower.find(term) >= 0]
    start = max(min(positions) - 45, 0) if positions else 0
    snippet = cleaned[start:start + width]
    if start:
        snippet = "..." + snippet
    if start + width < len(cleaned):
        snippet += "..."
    return snippet


def _is_system_noise(path: str) -> bool:
    lowered = path.lower()
    return any(lowered.startswith(prefix.lower()) for prefix in SYSTEM_NOISE_PREFIXES)


def _search_docs(terms: list[str], limit: int) -> list[dict]:
    results = []
    minimum_score = min(len(terms), max(2, len(terms) // 2))
    docs = [ROOT / "README.md"]
    docs.extend(path for path in DOCS_ROOT.glob("*.md") if path.name.startswith(DURABLE_DOC_PREFIXES))
    for path in docs:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        score = _match_score(text, terms)
        if score < minimum_score:
            continue
        rel = str(path.relative_to(ROOT))
        results.append({
            "group": "ARK DOCS",
            "title": path.stem.replace("_", " "),
            "summary": _snippet(text, terms),
            "path": str(path),
            "command": f'notepad "{path}"',
            "risk": "green",
            "touches": ["Local Markdown docs", "No project files"],
            "details": f"Matched durable Mini ARK documentation: {rel}",
            "_score": score,
        })
    results.sort(key=lambda item: (-item.pop("_score"), item["title"]))
    return results[:limit]


def _query_rows(conn: sqlite3.Connection, sql: str, params: tuple, group: str,
                title_field: str, summary_field: str | None, terms: list[str],
                limit: int) -> list[dict]:
    results = []
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error:
        return results
    for row in rows:
        title = str(row[title_field] or "")
        summary_source = str(row[summary_field] or "") if summary_field else title
        if _is_system_noise(title) or _is_system_noise(summary_source):
            continue
        combined = f"{title} {summary_source}"
        if not _matches(combined, terms):
            continue
        results.append({
            "group": group,
            "title": title[:120] or group,
            "summary": _snippet(summary_source or title, terms),
            "path": "",
            "command": ".\\ark.cmd brief",
            "risk": "green",
            "touches": ["Mini ARK SQLite ledger", "No project files"],
            "details": f"Matched {group.lower()} in the local Mini ARK ledger.",
        })
        if len(results) >= limit:
            break
    return results


def _search_sqlite(terms: list[str], limit: int) -> list[dict]:
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        results = []
        like = "%" + "%".join(terms) + "%"
        searches = [
            ("SELECT canonical_path FROM files WHERE canonical_path LIKE ? ORDER BY last_seen_at DESC LIMIT 80",
             (like,), "FILES", "canonical_path", "canonical_path"),
            ("SELECT description FROM events WHERE description LIKE ? ORDER BY created_at DESC LIMIT 80",
             (like,), "EVENTS", "description", "description"),
            ("SELECT description FROM decisions WHERE description LIKE ? ORDER BY decided_at DESC LIMIT 80",
             (like,), "DECISIONS", "description", "description"),
            ("SELECT description FROM proposals WHERE description LIKE ? ORDER BY created_at DESC LIMIT 80",
             (like,), "PROPOSALS", "description", "description"),
            ("SELECT description FROM open_loops WHERE description LIKE ? ORDER BY updated_at DESC LIMIT 80",
             (like,), "OPEN LOOPS", "description", "description"),
            ("SELECT summary FROM handoffs WHERE summary LIKE ? ORDER BY ingested_at DESC LIMIT 80",
             (like,), "HANDOFFS", "summary", "summary"),
            ("SELECT path_prefix, reason FROM protected_paths WHERE path_prefix LIKE ? OR reason LIKE ? ORDER BY created_at DESC LIMIT 80",
             (like, like), "RESERVATIONS", "path_prefix", "reason"),
        ]
        for sql, params, group, title_field, summary_field in searches:
            remaining = limit - len(results)
            if remaining <= 0:
                break
            results.extend(_query_rows(conn, sql, params, group, title_field, summary_field, terms, remaining))
        return results[:limit]
    finally:
        conn.close()


def search(query: str) -> dict:
    terms = _terms(query)
    if not terms:
        return {"query": query, "results": []}
    docs = _search_docs(terms, 10)
    ledger = _search_sqlite(terms, 20)
    return {"query": query, "results": docs + ledger}


def action_catalog() -> dict:
    return {
        "actions": [
            {
                "id": action_id,
                "title": data["title"],
                "mode": data["mode"],
                "risk": data["risk"],
                "runs": " ".join(data.get("command", [])) if data.get("command") else data.get("builtin", ""),
            }
            for action_id, data in ACTION_DEFS.items()
        ]
    }


def _latest_rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.Error:
        return []


def status() -> dict:
    conn = _connect()
    db_status = "missing"
    scan_count = 0
    open_loops = 0
    pending_proposals = 0
    approved_proposals = 0
    recent_actions = []
    if conn is not None:
        try:
            db_status = "ready"
            scan_row = conn.execute("SELECT COUNT(*) AS c FROM scans;").fetchone()
            scan_count = scan_row["c"] if scan_row else 0
            loop_row = conn.execute("SELECT COUNT(*) AS c FROM open_loops WHERE status='open';").fetchone()
            open_loops = loop_row["c"] if loop_row else 0
            pending_row = conn.execute("SELECT COUNT(*) AS c FROM proposals WHERE status='pending';").fetchone()
            pending_proposals = pending_row["c"] if pending_row else 0
            approved_row = conn.execute("SELECT COUNT(*) AS c FROM proposals WHERE status='approved';").fetchone()
            approved_proposals = approved_row["c"] if approved_row else 0
            recent_actions = [
                dict(row) for row in _latest_rows(
                    conn,
                    "SELECT id, action_type, created_at, summary FROM action_log ORDER BY id DESC LIMIT 5;",
                )
            ]
        finally:
            conn.close()
    git = _run_command(["git", "status", "-sb"], timeout=15)
    tests = {"state": "not_run", "summary": "Run from Manage."}
    return {
        "state": "ready" if db_status == "ready" else "needs_attention",
        "db": db_status,
        "scan_count": scan_count,
        "open_loops": open_loops,
        "pending_proposals": pending_proposals,
        "approved_proposals": approved_proposals,
        "git": git,
        "tests": tests,
        "recent_actions": recent_actions,
    }


def logs(limit: int = 20) -> dict:
    if not LOGS_ROOT.exists():
        return {"logs": []}
    rows = []
    for path in sorted(LOGS_ROOT.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        if not path.is_file():
            continue
        rows.append({
            "name": path.name,
            "path": str(path),
            "size": path.stat().st_size,
            "modified": path.stat().st_mtime,
        })
    return {"logs": rows}


def asset_pipeline_doctrine() -> dict:
    config_path = ROOT / "config" / "asset_pipeline_doctrine.json"
    doc_path = DOCS_ROOT / "ASSET_PIPELINE_DOCTRINE.md"
    config = {}
    doc = ""
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            config = {"error": f"Could not read {config_path}"}
    if doc_path.exists():
        try:
            doc = doc_path.read_text(encoding="utf-8")
        except OSError:
            doc = f"Could not read {doc_path}"
    return {
        "doctrine": config,
        "doc_path": str(doc_path),
        "config_path": str(config_path),
        "summary": doc,
    }


def naming_status() -> dict:
    config_path = ROOT / "config" / "naming_status.json"
    doc_path = DOCS_ROOT / "JOURNEY_NAMING_ARCHITECTURE.md"
    config = {}
    doc = ""
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            config = {"error": f"Could not read {config_path}"}
    if doc_path.exists():
        try:
            doc = doc_path.read_text(encoding="utf-8")
        except OSError:
            doc = f"Could not read {doc_path}"
    return {
        "status": config,
        "doc_path": str(doc_path),
        "config_path": str(config_path),
        "summary": doc,
    }


def expression_framework() -> dict:
    config_path = ROOT / "config" / "expression_framework.json"
    doc_path = DOCS_ROOT / "HEXSEED_EXPRESSION_FRAMEWORK.md"
    config = {}
    doc = ""
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            config = {"error": f"Could not read {config_path}"}
    if doc_path.exists():
        try:
            doc = doc_path.read_text(encoding="utf-8")
        except OSError:
            doc = f"Could not read {doc_path}"
    return {
        "framework": config,
        "doc_path": str(doc_path),
        "config_path": str(config_path),
        "summary": doc,
    }


def asset_jobs(limit: int = 60) -> dict:
    outbox = ASSET_PIPELINE_ROOT / "outbox"
    if not outbox.exists():
        return {"jobs": []}
    jobs = []
    for job_dir in sorted((path for path in outbox.iterdir() if path.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True):
        if job_dir.name.startswith("_") or "__source_" in job_dir.name:
            continue
        manifests = {
            "deconstruct": job_dir / "manifest.json",
            "repair": job_dir / "repair-manifest.json",
            "precision": job_dir / "precision-manifest.json",
            "nine_slice": job_dir / "nine-slice.tokens.json",
            "master": job_dir / "master-manifest.json",
            "intake": job_dir / "asset-intake-summary.json",
            "approval": job_dir / "approval-manifest.json",
        }
        stages = [stage for stage, path in manifests.items() if path.exists()]
        asset_count = None
        source_stage = None
        contact_sheet = None
        for manifest_path in (
            manifests["intake"],
            manifests["precision"],
            manifests["repair"],
            manifests["master"],
            manifests["deconstruct"],
            manifests["approval"],
        ):
            if not manifest_path.exists():
                continue
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            asset_count = (
                data.get("asset_count")
                or data.get("summary", {}).get("asset_count")
                or data.get("intake", {}).get("asset_count")
                or data.get("review", {}).get("asset_count")
                or len(data.get("assets", []))
            )
            source_stage = data.get("source_stage") or data.get("stage")
            contact_sheet = data.get("contact_sheet")
            break
        jobs.append(
            {
                "job": job_dir.name,
                "path": str(job_dir),
                "modified": job_dir.stat().st_mtime,
                "stages": stages,
                "asset_count": asset_count,
                "source_stage": source_stage,
                "contact_sheet": contact_sheet,
            }
        )
        if len(jobs) >= limit:
            break
    return {"jobs": jobs}


def proposals() -> dict:
    conn = _connect()
    if conn is None:
        return {"proposals": []}
    try:
        rows = conn.execute(
            """SELECT id, status, description, created_at, resolved_at
               FROM proposals
               WHERE status IN ('pending', 'approved')
               ORDER BY id DESC
               LIMIT 40;"""
        ).fetchall()
        result = []
        for row in rows:
            items = conn.execute(
                """SELECT
                     COUNT(*) AS total,
                     SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,
                     SUM(CASE WHEN status='skipped' THEN 1 ELSE 0 END) AS skipped,
                     SUM(CASE WHEN status='applied' THEN 1 ELSE 0 END) AS applied
                   FROM proposal_items WHERE proposal_id=?;""",
                (row["id"],),
            ).fetchone()
            item_counts = dict(items) if items else {}
            data = dict(row)
            data["items"] = {key: int(value or 0) for key, value in item_counts.items()}
            held = conn.execute("SELECT COUNT(*) FROM proposal_items WHERE proposal_id=? AND status='pending' AND requested_mode='quarantine'", (row["id"],)).fetchone()[0]
            data["quarantine_held"] = held
            if held:
                from core.action_evidence import quarantine_hold
                data["hold_reason"] = quarantine_hold()
            result.append(data)
        return {"proposals": result}
    finally:
        conn.close()


def proposal_items(proposal_id: int, limit: int = 80) -> dict:
    conn = _connect()
    if conn is None:
        return {"items": []}
    try:
        rows = conn.execute(
            """SELECT id, status, requested_mode, canonical_path, dest_path AS target_path
               FROM proposal_items
               WHERE proposal_id=?
               ORDER BY id
               LIMIT ?;""",
            (proposal_id, limit),
        ).fetchall()
        from core.action_evidence import quarantine_hold
        items = [dict(row) for row in rows]
        for item in items:
            if item["requested_mode"] == "quarantine" and item["status"] == "pending":
                item["hold_reason"] = quarantine_hold()
        return {"proposal_id": proposal_id, "items": items}
    finally:
        conn.close()


def patrol_status():
    from core.patrol_state import read_state
    conn = _connect()
    if conn is None:
        return {"ok": False, "error": "Ledger unavailable"}
    try:
        runs = [json.loads(r["summary_json"]) for r in conn.execute("SELECT summary_json FROM shadow_runs WHERE summary_json IS NOT NULL ORDER BY id DESC LIMIT 10")]
        policies = [dict(r) for r in conn.execute("SELECT * FROM patrol_policy_events ORDER BY id DESC")]
        return {"ok": True, "action": "patrol-status", "runs": runs, "policies": policies, "control_state": read_state(conn),
                "authority": "Shadow", "background_schedule": "not_enabled", "gate_b": "not_ready"}
    finally:
        conn.close()


def assessment_action(action_id, payload):
    from core import bounded_assessment as assessment
    from core.process_lock import process_lock
    from core.placement import load_placement_doctrine
    policy = ASSESSMENT_POLICY
    if payload:
        return {'ok': False, 'error': 'Assessment accepts no browser-supplied scope, limits or authority'}, 400
    if action_id == 'assessment-continue' and policy is None:
        return {'ok': False, 'error': 'No approved assessment scope deployed. Historical evidence remains available.'}, 403
    try:
        # Read status never initializes configuration, schemas or a missing ledger.
        if action_id == 'assessment-status':
            conn = sqlite3.connect(DB_PATH.absolute().as_uri() + '?mode=ro', uri=True, timeout=1)
            try:
                deadline = time.monotonic() + 10
                conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
                baseline = assessment.historical_baseline(conn, doctrine=load_placement_doctrine(ROOT))
                present = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='assessment_runs'").fetchone()
                latest = (conn.execute('SELECT id FROM assessment_runs WHERE root=? ORDER BY id DESC LIMIT 1', (str(Path(policy['scope']).absolute()),)).fetchone()
                          if policy else conn.execute('SELECT id FROM assessment_runs ORDER BY id DESC LIMIT 1').fetchone()) if present else None
                retained = assessment.report(conn, latest[0]) if latest else None
                return {'ok': True, 'action': 'assessment-status', 'baseline': baseline,
                        'assessment': retained, 'can_continue': policy is not None and (retained is None or retained['state'] == 'PENDING'),
                        'approved_scope': policy['scope'] if policy else None,
                        'readiness': 'Scope approval not deployed' if policy is None else 'Current authority rechecked on each batch'}, 200
            finally:
                conn.close()
        if not ASSESSMENT_LOCK.acquire(blocking=False):
            return {'ok': False, 'error': 'Assessment batch already active; refresh retained progress'}, 409
        try:
            # Existing lock is process-released on crash; serializes all retained
            # progress writes without a new worker or scheduler.
            with process_lock(str(DB_PATH) + '.assessment.lock'):
                authorize = policy['authorize']
                scope = policy['scope']
                assessment.allowed(scope, authorize)
                conn = sqlite3.connect(DB_PATH.absolute().as_uri() + '?mode=rw', uri=True, timeout=1)
                try:
                    run = assessment.start(conn, scope, load_placement_doctrine(ROOT), authorize)
                    result = assessment.batch(conn, run, authorize)
                    return {'ok': True, 'action': 'assessment-continue', 'assessment': result,
                            'can_continue': result['state'] == 'PENDING'}, 200
                finally:
                    conn.close()
        finally:
            ASSESSMENT_LOCK.release()
    except (OSError, ValueError, sqlite3.Error, RuntimeError) as exc:
        return {'ok': False, 'error': str(exc)}, 409


def run_action(action_id: str, payload: dict) -> tuple[dict, int]:
    if action_id in {'work-policy', 'work-policy-preview'}:
        from core.work_policy import inspect_store
        expected = set() if action_id == 'work-policy' else {'intention'}
        if type(payload) is not dict or set(payload) != expected:
            return {'ok': False, 'error': 'Only a policy intention is accepted; no authority fields'}, 400
        if action_id == 'work-policy-preview' and type(payload['intention']) is not str:
            return {'ok': False, 'error': 'Policy intention must be text'}, 400
        try:
            result = inspect_store(DB_PATH, payload.get('intention'))
            return {'ok': True, 'action': action_id, 'policy': result}, 200
        except (OSError, sqlite3.Error, ValueError) as exc:
            return {'ok': False, 'error': str(exc), 'policy_state': 'UNKNOWN'}, 409
    if action_id in {'assessment-status', 'assessment-continue'}:
        return assessment_action(action_id, payload)
    if action_id == 'media-inventory-resume':
        if not (ROOT/'private'/'media_recovery'/'inventory-v2.sqlite').is_file():
            return {'ok':False,'error':'No registered continuation task'},409
        if not MEDIA_INVENTORY_LOCK.acquire(blocking=False):
            return {'ok':False,'error':'A media inventory batch is already running'},409
        try:
            result = _run_command([sys.executable,'-B',str(ROOT/'work'/'resume_media_inventory.py'),
                                   '--max-directories','100','--max-seconds','15','--hash-files','100'],timeout=60)
            return {'action':action_id,**result},200
        finally:
            MEDIA_INVENTORY_LOCK.release()
    if action_id == 'recovery-status':
        from core.recovery_domain import capability_status
        summary = ROOT/'private'/'media_recovery'/'latest_summary.json'
        return {'ok':True,'action':action_id,**capability_status(),
                'personal_media_task':json.loads(summary.read_text(encoding='utf-8')) if summary.is_file() else {'state':'NOT_STARTED'}},200
    if action_id in {'perception-policy','perception-policy-set'}:
        from core.perception_policy import effective_policy, set_policy
        conn = _connect()
        if conn is None:
            return {'ok':False,'error':'Ledger unavailable'},503
        try:
            path = payload.get('path')
            if not path:
                if action_id == 'perception-policy-set':
                    return {'ok':False,'error':'Policy scope path is required'},400
                return {'ok':True,'action':action_id,'default':'SEALED','providers_enabled':False,
                        'retention':False,'learning':False,'inspection':'structural_only'},200
            if action_id == 'perception-policy-set':
                if payload.get('confirmed') is not True:
                    return {'ok':False,'error':'Explicit confirmation required for policy changes'},409
                set_policy(conn,path,payload.get('mode'),reason=payload.get('reason'),
                    purposes=payload.get('purposes',[]),retention=payload.get('retention',False),learning=payload.get('learning',False))
            return {'ok':True,'action':action_id,'policy':effective_policy(conn,path,purpose=payload.get('purpose')),'providers_enabled':False},200
        except (ValueError,TypeError) as exc:
            return {'ok':False,'error':str(exc)},400
        finally:
            conn.close()
    if action_id == "patrol-control":
        from core.patrol_state import update_state
        conn = _connect()
        if conn is None:
            return {"ok": False, "error": "Ledger unavailable"}, 503
        try:
            state = update_state(conn, version=payload.get('version'), paused=payload.get('paused'), reason=payload.get('reason'))
            return {"ok": True, "action": "patrol-control", "control_state": state}, 200
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}, 409
        finally:
            conn.close()
    if action_id == "patrol-status":
        return patrol_status(), 200
    if action_id == "shadow-run":
        scope = str(payload.get("path") or payload.get("scope") or "").strip()
        if not scope:
            return {"ok": False, "action": "shadow-run", "error": "Scope path is required."}, 400
        command = [str(ARK_CMD), "shadow", "--scope", scope, "--json"]
        limit = str(payload.get("limit", "")).strip()
        if limit:
            command.extend(["--limit", limit])
        result = _run_command(command, timeout=ACTION_DEFS["shadow-run"].get("timeout", DEFAULT_TIMEOUT_SECONDS))
        return {"ok": result["ok"], "action": "shadow-run", "scope": scope, **result, "patrol": patrol_status()}, 200
    if action_id == "placement-check":
        path = str(payload.get("path", "")).strip()
        if not path:
            return {"ok": False, "action": "placement-check", "error": "Path is required."}, 400
        command = [str(ARK_CMD), "placement", path]
        result = _run_command(command, timeout=ACTION_DEFS["placement-check"].get("timeout", DEFAULT_TIMEOUT_SECONDS))
        return {"ok": result["ok"], "action": "placement-check", "path": path, **result}, 200
    if action_id == "name-preview":
        path = str(payload.get("path", "")).strip()
        if not path:
            return {"ok": False, "error": "Path is required."}, 400
        command = [str(ARK_CMD), "name-preview", path]
        role = str(payload.get("role", "")).strip()
        project = str(payload.get("project", "")).strip()
        if role:
            command.extend(["--role", role])
        if project:
            command.extend(["--project", project])
        result = _run_command(command, timeout=ACTION_DEFS["name-preview"].get("timeout", DEFAULT_TIMEOUT_SECONDS))
        return {"ok": result["ok"], "action": "name-preview", "path": path, **result}, 200
    if action_id == "date-index":
        path = str(payload.get("path", "")).strip()
        if not path:
            return {"ok": False, "error": "Path is required."}, 400
        command = [str(ARK_CMD), "date-index", path, "--recursive"]
        result = _run_command(command, timeout=ACTION_DEFS["date-index"].get("timeout", DEFAULT_TIMEOUT_SECONDS))
        return {"ok": result["ok"], "action": "date-index", "path": path, **result}, 200
    if action_id in {"scan", "ingest"}:
        path = str(payload.get("path", "")).strip()
        if not path:
            return {"ok": False, "error": "Path is required."}, 400
        command = [str(ARK_CMD), action_id, path]
        timeout = 300 if action_id == "scan" else 120
        result = _run_command(command, timeout=timeout)
        return {"ok": result["ok"], "action": action_id, "path": path, **result}, 200
    if action_id == "assets-deconstruct-inbox":
        return asset_deconstruct_from_payload(payload)
    if action_id == "assets-intake":
        return asset_intake_from_payload(payload)
    if action_id == "assets-auto-deconstruct":
        return asset_auto_deconstruct_from_payload(payload)
    if action_id == "assets-compose-master":
        return asset_compose_master_from_payload(payload)
    if action_id == "assets-nine-slice":
        return asset_nine_slice_from_payload(payload)
    if action_id == "assets-treat":
        return asset_treat_from_payload(payload)
    if action_id == "assets-precision-icons":
        return asset_precision_icons_from_payload(payload)
    if action_id == "assets-repair-icons":
        return asset_repair_icons_from_payload(payload)
    if action_id == "assets-review-job":
        return asset_review_job_from_payload(payload)
    if action_id == "assets-approve-job":
        return asset_approve_job_from_payload(payload)
    if action_id == "assets-brief":
        return asset_brief_from_payload(payload)
    action = ACTION_DEFS.get(action_id)
    if action is None:
        return {"ok": False, "error": f"Unknown action: {action_id}"}, 404
    if action.get("builtin") == "logs":
        return {"ok": True, **logs()}, 200
    if action.get("builtin") == "asset_pipeline_doctrine":
        return {"ok": True, "action": action_id, "title": action["title"], **asset_pipeline_doctrine()}, 200
    if action.get("builtin") == "naming_status":
        return {"ok": True, "action": action_id, "title": action["title"], **naming_status()}, 200
    if action.get("builtin") == "expression_framework":
        return {"ok": True, "action": action_id, "title": action["title"], **expression_framework()}, 200
    result = _run_command(action["command"], timeout=action.get("timeout", DEFAULT_TIMEOUT_SECONDS))
    return {"ok": result["ok"], "action": action_id, "title": action["title"], **result}, 200


def approve_proposal(proposal_id: int) -> tuple[dict, int]:
    result = _run_command([str(ARK_CMD), "approve", str(proposal_id)], timeout=60)
    return {"ok": result["ok"], "action": "approve", "proposal_id": proposal_id, **result}, 200


def _proposal_fingerprint(proposal_id):
    conn = _connect()
    if conn is None:
        raise ValueError("Ledger unavailable")
    try:
        proposal = conn.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
        if proposal is None or proposal["status"] != "approved":
            raise ValueError("Proposal is not approved")
        items = [dict(r) for r in conn.execute("SELECT * FROM proposal_items WHERE proposal_id=? ORDER BY id", (proposal_id,))]
        paths = []
        for item in items:
            if item["status"] != "pending":
                continue
            for path in (item["canonical_path"], item["dest_path"]):
                if not path:
                    continue
                try:
                    meta = os.lstat(path)
                    paths.append((path, meta.st_size, meta.st_mtime_ns, meta.st_ino, meta.st_mode))
                except FileNotFoundError:
                    paths.append((path, "absent"))
        dependencies = [dict(r) for r in conn.execute("SELECT * FROM file_dependents ORDER BY id")]
        protections = [dict(r) for r in conn.execute("SELECT * FROM protected_paths ORDER BY id")]
        return hashlib.sha256(json.dumps([dict(proposal),items,paths,dependencies,protections],sort_keys=True).encode()).hexdigest()
    finally:
        conn.close()


def apply_proposal(proposal_id: int, execute: bool, confirmed: bool, preview_token: str = "") -> tuple[dict, int]:
    with PREVIEW_LOCK:
        return _apply_proposal_locked(proposal_id, execute, confirmed, preview_token)


def _apply_proposal_locked(proposal_id, execute, confirmed, preview_token):
    command = [str(ARK_CMD), "apply", str(proposal_id)]
    if not execute:
        command.append("--preview")
    elif confirmed is not True:
        return {
            "ok": False,
            "requires_confirmation": True,
            "error": "Apply execution requires explicit confirmation in the Navigator after preview.",
        }, 409
    try:
        fingerprint = _proposal_fingerprint(proposal_id)
    except (ValueError, OSError) as exc:
        return {"ok": False, "error": str(exc)}, 409
    if execute:
        receipt = PREVIEW_RECEIPTS.pop(preview_token, None)
        if not receipt or receipt[0] != proposal_id or receipt[1] != fingerprint or time.monotonic() > receipt[2]:
            return {"ok": False, "error": "Preview is missing, expired, used, or changed. Review a fresh preview before Apply."}, 409
    result = _run_command(command, timeout=300)
    token = None
    if not execute and result["ok"]:
        try:
            current_fingerprint = _proposal_fingerprint(proposal_id)
        except (ValueError, OSError) as exc:
            return {"ok": False, "error": f"Preview conditions could not be verified. Preview again: {exc}"}, 409
        if current_fingerprint != fingerprint:
            return {"ok": False, "error": "Proposal conditions changed during preview. Preview again."}, 409
        token = secrets.token_urlsafe(32)
        now = time.monotonic()
        for old in list(PREVIEW_RECEIPTS):
            if PREVIEW_RECEIPTS[old][2] < now or PREVIEW_RECEIPTS[old][0] == proposal_id:
                del PREVIEW_RECEIPTS[old]
        PREVIEW_RECEIPTS[token] = (proposal_id, fingerprint, now + 600)
    return {
        "ok": result["ok"],
        "action": "apply_execute" if execute else "apply_preview",
        "proposal_id": proposal_id,
        "preview_token": token,
        **result,
    }, 200


def skip_proposal_item(item_id: int, reason: str | None = None) -> tuple[dict, int]:
    command = [str(ARK_CMD), "skip-item", str(item_id)]
    if reason:
        command.extend(["--reason", reason])
    result = _run_command(command, timeout=60)
    return {"ok": result["ok"], "action": "skip_item", "item_id": item_id, **result}, 200


def set_proposal_item_mode(item_id: int, mode: str) -> tuple[dict, int]:
    if mode not in {"move", "shortcut", "quarantine"}:
        return {"ok": False, "error": "Mode must be move, shortcut, or quarantine."}, 400
    result = _run_command([str(ARK_CMD), "set-item-mode", str(item_id), mode], timeout=60)
    return {"ok": result["ok"], "action": "set_item_mode", "item_id": item_id, "mode": mode, **result}, 200


def undo_operation_bridge(op_id: int, confirmed: bool) -> tuple[dict, int]:
    if confirmed is not True:
        return {
            "ok": False,
            "requires_confirmation": True,
            "error": "Undo requires explicit confirmation in the Navigator.",
        }, 409
    from core.recovery_inspection import inspect_operation
    conn = _connect()
    if conn is None:
        return {'ok':False, 'error':'Ledger unavailable'}, 503
    try:
        recovery = inspect_operation(conn, op_id)
        if recovery['state'] != 'UNDO_AVAILABLE':
            return {'ok':False, 'action':'undo', 'error':recovery['state'], 'recovery':recovery}, 409
    finally:
        conn.close()
    result = _run_command([str(ARK_CMD), "undo", str(op_id)], timeout=180)
    return {"ok": result["ok"], "action": "undo", "op_id": op_id, **result}, 200


def _private_request_path(path):
    # Preserve the existing application route; this guard restricts static files.
    if urlparse(path).path == '/api/logs':
        return False
    parts = unquote(urlparse(path).path).replace('\\', '/').lower().split('/')
    # Reject Windows aliases before suffix checks (including NTFS streams).
    if any(':' in part or '\x00' in part or part.endswith((' ', '.')) for part in parts):
        return True
    return (any(part in {'private', '.git', 'docs', 'logs', 'handoffs_inbox', 'config'} for part in parts)
            or any(part.endswith(('.sqlite', '.sqlite-wal', '.sqlite-shm', '.sqlite-journal',
                                  '.db', '.db-wal', '.db-shm', '.db-journal', '.md')) for part in parts)
            or parts[-1] in {'config.json', 'asset-index.json'})


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def send_head(self):
        path = unquote(urlparse(self.path).path)
        resource = '/index.html' if path == '/' else path
        if _private_request_path(self.path) or resource not in PUBLIC_STATIC_PATHS:
            return self.list_directory(None)
        target = Path(self.directory) / resource.lstrip('/')
        try:
            # Check ancestors before touching children; never traverse a known link.
            for part in (*reversed(target.parents), target):
                info = part.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    return self.list_directory(None)
            if not stat.S_ISREG(info.st_mode):
                return self.list_directory(None)
        except OSError:
            return self.list_directory(None)
        return super().send_head()

    def list_directory(self, path):
        # Directory names can disclose private work even when file reads deny.
        self.send_response(403)
        self.send_header('Content-Length', '0')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        return None

    def do_GET(self):  # noqa: N802
        try:
            self._get()
        except Exception as exc:
            _json_response(self, {"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)

    def do_HEAD(self):  # noqa: N802
        if _private_request_path(self.path):
            self.send_response(403)
            self.send_header('Content-Length', '0')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            return
        super().do_HEAD()

    def _get(self):
        parsed = urlparse(self.path)
        if _private_request_path(self.path):
            _json_response(self, {'ok':False,'error':'Private local evidence is not a static web resource'},403)
            return
        if parsed.path == "/api/search":
            query = parse_qs(parsed.query).get("q", [""])[0]
            _json_response(self, search(query))
            return
        if parsed.path == "/api/actions":
            _json_response(self, action_catalog())
            return
        if parsed.path == "/api/status":
            _json_response(self, status())
            return
        if parsed.path == "/api/logs":
            _json_response(self, logs())
            return
        if parsed.path == "/api/assets/jobs":
            _json_response(self, asset_jobs())
            return
        if parsed.path == "/api/proposals":
            _json_response(self, proposals())
            return
        if parsed.path.startswith("/api/proposals/") and parsed.path.endswith("/items"):
            parts = parsed.path.strip("/").split("/")
            try:
                proposal_id = int(parts[2])
            except (IndexError, ValueError):
                _json_response(self, {"ok": False, "error": "Invalid proposal id."}, 400)
                return
            _json_response(self, proposal_items(proposal_id))
            return
        super().do_GET()

    def _council_origin(self, post=False):
        port = self.server.server_address[1]
        host = self.headers.get('Host')
        if host not in (f'127.0.0.1:{port}', f'localhost:{port}'):
            return False
        origin = self.headers.get('Origin')
        return (self.client_address[0] in ('127.0.0.1', '::1')
                and self.headers.get('Sec-Fetch-Site') not in ('cross-site', 'same-site')
                and (origin == f'http://{host}' if post or origin else True))

    def do_POST(self):  # noqa: N802
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{self.headers.get('Host')}":
            _json_response(self, {"ok": False, "error": "Use the local Navigator for actions."}, 403)
            return
        try:
            self._post()
        except RequestBodyError as exc:
            self.close_connection = True
            _json_response(self, {'ok': False, 'error': str(exc)}, exc.status)
        except Exception as exc:
            _json_response(self, {"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)

    def _post(self):
        parsed = urlparse(self.path)
        if parsed.path in ('/api/actions/assessment-status', '/api/actions/assessment-continue',
                           '/api/actions/work-policy', '/api/actions/work-policy-preview'):
            if not self._council_origin(post=True):
                _json_response(self, {'ok': False, 'error': 'Local Navigator origin required.'}, 403)
                return
        payload = _read_json_body(self)
        if parsed.path.startswith("/api/actions/"):
            action_id = parsed.path.removeprefix("/api/actions/")
            result, status_code = run_action(action_id, payload)
            _json_response(self, result, status_code)
            return
        parts = parsed.path.strip("/").split("/")
        if len(parts) == 4 and parts[:2] == ["api", "proposals"]:
            try:
                proposal_id = int(parts[2])
            except ValueError:
                _json_response(self, {"ok": False, "error": "Invalid proposal id."}, 400)
                return
            if parts[3] == "approve":
                result, status_code = approve_proposal(proposal_id)
                _json_response(self, result, status_code)
                return
            if parts[3] == "apply-preview":
                result, status_code = apply_proposal(proposal_id, execute=False, confirmed=False)
                _json_response(self, result, status_code)
                return
            if parts[3] == "apply":
                result, status_code = apply_proposal(
                    proposal_id,
                    execute=True,
                    confirmed=payload.get("confirmed"),
                    preview_token=str(payload.get("preview_token", "")),
                )
                _json_response(self, result, status_code)
                return
        if len(parts) == 4 and parts[:2] == ["api", "proposal-items"]:
            try:
                item_id = int(parts[2])
            except ValueError:
                _json_response(self, {"ok": False, "error": "Invalid proposal item id."}, 400)
                return
            if parts[3] == "skip":
                reason = str(payload.get("reason", "")).strip() or None
                result, status_code = skip_proposal_item(item_id, reason)
                _json_response(self, result, status_code)
                return
            if parts[3] == "mode":
                result, status_code = set_proposal_item_mode(item_id, str(payload.get("mode", "")).strip())
                _json_response(self, result, status_code)
                return
        if len(parts) == 3 and parts[:2] == ["api", "undo"]:
            try:
                op_id = int(parts[2])
            except ValueError:
                _json_response(self, {"ok": False, "error": "Invalid operation id."}, 400)
                return
            result, status_code = undo_operation_bridge(op_id, confirmed=payload.get("confirmed"))
            _json_response(self, result, status_code)
            return
        _json_response(self, {"ok": False, "error": "Unknown endpoint."}, 404)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("port", type=int)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
