"""
Mini ARK classify.

Classification is ordered by meaning before file type:

    protection/ownership -> operational context -> lifecycle ->
    project affinity -> physical type -> placement assessment -> confidence

That ordering is deliberate. A PNG inside a Rainmeter skin is not just
"an image"; a WAV inside a Plex library is not automatically "personal
audio"; a PowerShell helper is operational infrastructure before it is
an arbitrary text file.

This module NEVER creates proposals or touches files. It only returns
structured hints for inventory, placement congruence, and later
maintenance flows.
"""

import re
from pathlib import PureWindowsPath

CONFIRMED = "Confirmed"
STRONGLY_INFERRED = "Strongly_inferred"
TENTATIVE = "Tentative"
UNKNOWN = "Unknown"

LIFECYCLE_PROTECTED = "protected_canonical"
LIFECYCLE_PROJECT = "project_material"
LIFECYCLE_OPERATIONAL = "operational_infrastructure"
LIFECYCLE_TRANSIENT = "transient_residue"
LIFECYCLE_UNKNOWN = "unknown"

EVIDENCE_ORDER = [
    "protection/ownership",
    "operational context",
    "lifecycle",
    "project affinity",
    "physical type",
    "placement assessment",
    "confidence",
]

_KNOWN_PROJECTS = {
    "carebloomos": "CareBloomOS",
    "carebloom": "CareBloomOS",
    "welfare_witchcraft": "Welfare_Witchcraft",
    "welfarewitchcraft": "Welfare_Witchcraft",
    "hexseed": "HEXSEED",
    "mini_ark": "Mini_ARK",
    "miniark": "Mini_ARK",
}

_CAREBLOOM_OWNER_SIGNALS = {
    "carebloom", "cloverstone", "moonstone", "heartstone", "carestone",
    "hexseed", "runescript", "caredrive", "care rail", "carerail",
}

_WELFARE_OWNER_SIGNALS = {
    "welfare_witchcraft", "welfarewitchcraft", "bureaucracy_mancer",
    "bureaucracymancer",
}

_LIVE_RAINMETER_SIGNALS = {"rainmeter", "skins", "illustro"}
_WALLPAPER_ENGINE_SIGNALS = {"wallpaper_engine", "wallpaper engine", "431960"}
_PLEX_SIGNALS = {"plex", "plex media server"}

_OPERATIONAL_FOLDERS = {
    "scripts", "script", "tools", "tooling", "utils", "utilities",
    "automation", "automations", "watchers", "startup", "tasks",
    "scanner", "core", "db", "bin", "config", "configs",
}

_TRANSIENT_SIGNALS = {
    "tmp", "temp", "cache", "caches", "__pycache__", "staging",
    "scratch", "backup", "backups", "bak", "old", "obsolete",
    "installer", "installers", "downloads",
}

_CANONICAL_SIGNALS = {
    "canonical", "source_of_truth", "source-of-truth", "master",
    "locked", "approved", "reference", "references", "manifest",
    "manifests", "records", "agreements", "identity_records",
}

_OLD_ACCOUNT_SIGNALS = {"desktop", "documents", "downloads", "pictures", "videos", "music"}

_SCRIPT_EXTENSIONS = {".ps1", ".py", ".lua", ".bat", ".cmd", ".sh", ".js", ".ts", ".vbs"}
_CONFIG_EXTENSIONS = {".ini", ".json", ".toml", ".yaml", ".yml", ".xml", ".cfg", ".conf"}

_MEDIA_EXTENSIONS = {
    ".jpg": "Images", ".jpeg": "Images", ".png": "Images", ".gif": "Images",
    ".bmp": "Images", ".webp": "Images", ".svg": "Images", ".ico": "Icons",
    ".mp4": "Video", ".mov": "Video", ".avi": "Video", ".mkv": "Video", ".webm": "Video",
    ".mp3": "Audio", ".wav": "Audio", ".flac": "Audio", ".m4a": "Audio", ".aac": "Audio",
    ".ttf": "Fonts", ".otf": "Fonts", ".woff": "Fonts", ".woff2": "Fonts",
}

_LIBRARY_EXTENSIONS = {".pdf": "PDFs", ".epub": "Books", ".mobi": "Books"}


def _path_bits(path: str) -> tuple[PureWindowsPath, list[str], str, str]:
    p = PureWindowsPath(path)
    parts_lower = [part.lower() for part in p.parts]
    joined = " ".join(parts_lower)
    return p, parts_lower, joined, p.suffix.lower()


def _contains_any(parts_lower: list[str], joined: str, signals: set[str]) -> str | None:
    tokens = set()
    for part in parts_lower:
        tokens.update(piece for piece in re.split(r"[^a-z0-9]+", part) if piece)
    for signal in signals:
        if " " in signal or "_" in signal or "-" in signal:
            if signal in joined:
                return signal
        elif signal in parts_lower or signal in tokens:
            return signal
    return None


def _known_project(parts_lower: list[str], joined: str) -> tuple[str, str] | tuple[None, None]:
    # Nearest explicit project directory outranks a containing platform name.
    for part in reversed(parts_lower[:-1]):
        if part in _KNOWN_PROJECTS:
            return _KNOWN_PROJECTS[part], part
    for key, project in _KNOWN_PROJECTS.items():
        if re.search(r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])", joined):
            return project, key
    return None, None


def _base_result(bucket: str, confidence: str, reason: str, *, owner: str,
                 lifecycle_class: str, subject_type: str, placement: str,
                 signals: list[str]) -> dict:
    return {
        "bucket": bucket,
        "confidence": confidence,
        "reason": reason,
        "owner": owner,
        "lifecycle_class": lifecycle_class,
        "subject_type": subject_type,
        "placement": placement,
        "signals": signals,
        "evidence_order": EVIDENCE_ORDER,
    }


def classify_path(path: str) -> dict:
    p, parts_lower, joined, ext = _path_bits(path)
    project, project_signal = _known_project(parts_lower, joined)
    old_account_hit = next((part for part in parts_lower if part in _OLD_ACCOUNT_SIGNALS), None)

    live_rainmeter_signal = _contains_any(parts_lower, joined, _LIVE_RAINMETER_SIGNALS)
    wallpaper_signal = _contains_any(parts_lower, joined, _WALLPAPER_ENGINE_SIGNALS)
    plex_signal = _contains_any(parts_lower, joined, _PLEX_SIGNALS)
    canonical_signal = _contains_any(parts_lower, joined, _CANONICAL_SIGNALS)

    if live_rainmeter_signal:
        owner = "CareBloomOS" if _contains_any(parts_lower, joined, _CAREBLOOM_OWNER_SIGNALS) else "Rainmeter"
        return _base_result(
            "System_Records/Operational_Manifests",
            CONFIRMED,
            f"live Rainmeter path signal '{live_rainmeter_signal}' outranks extension '{ext or '(none)'}'",
            owner=owner,
            lifecycle_class=LIFECYCLE_PROTECTED,
            subject_type="live_surface",
            placement="live_rainmeter",
            signals=[live_rainmeter_signal],
        )

    if wallpaper_signal:
        owner = "CareBloomOS" if _contains_any(parts_lower, joined, _CAREBLOOM_OWNER_SIGNALS) else "Wallpaper Engine"
        return _base_result(
            "System_Records/Operational_Manifests",
            CONFIRMED,
            f"Wallpaper Engine path signal '{wallpaper_signal}' marks this as a live surface",
            owner=owner,
            lifecycle_class=LIFECYCLE_PROTECTED,
            subject_type="live_surface",
            placement="wallpaper_engine",
            signals=[wallpaper_signal],
        )

    if plex_signal:
        media_bucket = _MEDIA_EXTENSIONS.get(ext)
        bucket = f"Media/{media_bucket}" if media_bucket else "Intake/Needs_Classification"
        return _base_result(
            bucket,
            STRONGLY_INFERRED if media_bucket else TENTATIVE,
            f"Plex library context '{plex_signal}' outranks personal-folder assumptions",
            owner="Plex",
            lifecycle_class=LIFECYCLE_PROJECT,
            subject_type="media_library_item" if media_bucket else "library_item",
            placement="application_library",
            signals=[s for s in [plex_signal, ext] if s],
        )

    if ext in _SCRIPT_EXTENSIONS or ext in _CONFIG_EXTENSIONS:
        context_signal = _contains_any(parts_lower, joined, _OPERATIONAL_FOLDERS)
        if context_signal or ext in _SCRIPT_EXTENSIONS:
            owner = project or ("CareBloomOS" if _contains_any(parts_lower, joined, _CAREBLOOM_OWNER_SIGNALS) else "Unknown")
            bucket = f"RuneScript/Projects/{project}" if project else "System_Records/Mini_ARK_Manifests"
            confidence = STRONGLY_INFERRED
            return _base_result(
                bucket,
                confidence,
                f"operational file '{p.name}' classified before physical type; signal '{context_signal or ext}'",
                owner=owner,
                lifecycle_class=LIFECYCLE_OPERATIONAL,
                subject_type="script" if ext in _SCRIPT_EXTENSIONS else "configuration",
                placement="operational_context",
                signals=[s for s in [project_signal, context_signal, ext] if s],
            )

    if project:
        media_bucket = _MEDIA_EXTENSIONS.get(ext)
        subject = "project_asset" if media_bucket else "project_material"
        return _base_result(
            f"RuneScript/Projects/{project}",
            STRONGLY_INFERRED,
            f"path signal '{project_signal}' identifies known project '{project}'; extension remains supporting evidence only",
            owner=project,
            lifecycle_class=LIFECYCLE_PROJECT,
            subject_type=subject,
            placement="project_context",
            signals=[s for s in [project_signal, ext] if s],
        )

    if canonical_signal:
        return _base_result(
            "Library/Reference_Collections",
            STRONGLY_INFERRED,
            f"lifecycle signal '{canonical_signal}' found without a stronger project owner",
            owner="Unknown",
            lifecycle_class=LIFECYCLE_PROTECTED,
            subject_type="canonical_reference",
            placement="lifecycle_context",
            signals=[canonical_signal],
        )

    transient_signal = _contains_any(parts_lower, joined, _TRANSIENT_SIGNALS)
    if transient_signal:
        return _base_result(
            "Intake/Needs_Classification",
            TENTATIVE,
            f"transient/residue signal '{transient_signal}' requires review before any action",
            owner="Unknown",
            lifecycle_class=LIFECYCLE_TRANSIENT,
            subject_type="transient_or_residue",
            placement="transient_context",
            signals=[transient_signal],
        )

    if ext in _MEDIA_EXTENSIONS:
        subcat = _MEDIA_EXTENSIONS[ext]
        reason = f"file extension '{ext}' identifies physical type as {subcat}, with no stronger owner"
        if old_account_hit:
            reason += f"; old account folder '{old_account_hit}' is source context only"
        return _base_result(
            f"Media/{subcat}",
            STRONGLY_INFERRED,
            reason,
            owner="Unknown",
            lifecycle_class=LIFECYCLE_UNKNOWN,
            subject_type=f"media_{subcat.lower()}",
            placement="physical_type_only",
            signals=[s for s in [old_account_hit, ext] if s],
        )

    if ext in _LIBRARY_EXTENSIONS:
        return _base_result(
            f"Library/{_LIBRARY_EXTENSIONS[ext]}",
            STRONGLY_INFERRED,
            f"file extension '{ext}' identifies reference/library material, with no stronger owner",
            owner="Unknown",
            lifecycle_class=LIFECYCLE_UNKNOWN,
            subject_type="library_item",
            placement="physical_type_only",
            signals=[ext],
        )

    if old_account_hit:
        return _base_result(
            "Intake/From_User_Accounts",
            TENTATIVE,
            f"old account folder '{old_account_hit}' is source information, not final placement",
            owner="Unknown",
            lifecycle_class=LIFECYCLE_UNKNOWN,
            subject_type="unknown_user_file",
            placement="source_context_only",
            signals=[old_account_hit],
        )

    return _base_result(
        "Intake/Needs_Classification",
        UNKNOWN,
        "no usable signal (no owner, operational context, lifecycle hint, or recognized extension)",
        owner="Unknown",
        lifecycle_class=LIFECYCLE_UNKNOWN,
        subject_type="unknown",
        placement="unknown",
        signals=[],
    )


def classify_all(conn, root_path: str = None) -> dict:
    """Read-only classification of every 'present' file under root_path.
    Returns per-bucket, per-confidence counts and sample paths -- never
    writes a proposal or touches a file."""
    where = "WHERE status = 'present'"
    params = []
    if root_path:
        from scanner.scanner import normalize_path
        where += " AND canonical_path LIKE ?"
        params.append(normalize_path(root_path) + "%")

    rows = conn.execute(f"SELECT canonical_path FROM files {where};", params).fetchall()

    buckets = {}
    lifecycle = {}
    for r in rows:
        result = classify_path(r["canonical_path"])
        key = (result["bucket"], result["confidence"])
        if key not in buckets:
            buckets[key] = {"count": 0, "examples": []}
        buckets[key]["count"] += 1
        if len(buckets[key]["examples"]) < 5:
            buckets[key]["examples"].append(r["canonical_path"])

        lifecycle_key = result["lifecycle_class"]
        lifecycle[lifecycle_key] = lifecycle.get(lifecycle_key, 0) + 1

    return {
        "status": "classified",
        "total_files": len(rows),
        "buckets": buckets,
        "lifecycle": lifecycle,
    }
