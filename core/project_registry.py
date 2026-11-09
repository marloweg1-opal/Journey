"""Project asset evidence from selected local records, with no action authority."""

from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import PurePosixPath
import re
from urllib.parse import unquote


PROFILE_FORMAT = "journey-project-naming-1"
PATTERN_FORMAT = "journey-project-naming-2"
DATE_ORDERS = {"DD_MM", "YYYY-MM-DD", "NONE"}
EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".ico", ".svg")
SUFFIXES = "|".join(suffix[1:] for suffix in EXTENSIONS)
REFERENCE = re.compile(
    rf"`([^`\r\n]{{1,512}})`|\[([^\]\r\n]{{1,512}})\]\(([^)\r\n]{{1,1024}})\)"
    rf"|(?<!\w)([\w][\w.-]{{0,200}}\.(?:{SUFFIXES}))\b", re.I,
)
CREATED = re.compile(r"\b(?:created|drawn|authored) (?:on )?(\d{4}-\d{2}-\d{2})\b", re.I)
RELATION = re.compile(r"\b(supersedes|replaces|variant of|derived from)\b", re.I)
LIFECYCLE = re.compile(r"\b(retired|archived|discarded)\b", re.I)
QUALIFIED = re.compile(r"\b(not|never|maybe|might|could|should|would|if)\b", re.I)
CLAIM_TYPES = {"reference", "named_reference", "creation_date", "relationship", "lifecycle"}


def iso_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Use a full calendar date in YYYY-MM-DD format.")
    return date.fromisoformat(value).isoformat()


def text_field(value, length=180):
    if not isinstance(value, str) or not value.strip() or len(value) > length or any(ord(c) < 32 for c in value):
        raise ValueError("The project record contains an invalid text field.")
    return value.strip()


def key_for(value):
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode()).hexdigest()


def asset_name(value):
    """Use a basename as evidence. Paths in archives never authorize file access."""
    if not isinstance(value, str):
        return ""
    name = PurePosixPath(value.strip().replace("\\", "/")).name
    if PurePosixPath(name).suffix.casefold() not in EXTENSIONS:
        return ""
    if len(name) > 255 or re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or name.endswith((" ", ".")):
        return ""
    return name


def render_name(rule, full_date, extension):
    pattern = rule.get("pattern") or rule.get("prefix", "") + "_{date}"
    order = rule["date_order"]
    if order == "NONE":
        return pattern + extension
    day = date.fromisoformat(iso_date(full_date))
    stamp = f"{day.day:02d}_{day.month:02d}" if order == "DD_MM" else day.isoformat()
    return pattern.replace("{date}", stamp) + extension


def profile_date(rule, name):
    """Parse only fields declared by an active profile. Filename dates remain observations."""
    pattern = rule.get("pattern") or rule.get("prefix", "") + "_{date}"
    order = rule["date_order"]
    if order == "NONE":
        return {"state": "undated"} if PurePosixPath(name).stem == pattern else None
    date_rx = r"([0-9]{2})_([0-9]{2})" if order == "DD_MM" else r"([0-9]{4})-([0-9]{2})-([0-9]{2})"
    match = re.fullmatch(re.escape(pattern).replace(re.escape("{date}"), date_rx), PurePosixPath(name).stem)
    if not match:
        return None
    if match.groups() == ("00", "00"):
        return {"day": None, "month": None, "state": "placeholder"}
    if order == "DD_MM":
        day, month = map(int, match.groups())
        year = None
    else:
        year, month, day = map(int, match.groups())
    fields = {"day": day, "month": month} if year is None else {"year": year, "day": day, "month": month}
    try:
        date(2000 if year is None else year, month, day)
    except ValueError:
        return fields | {"state": "invalid"}
    return fields | {"state": "observed"}


def _words(value):
    return " ".join(re.findall(r"[^\W_]+", value.casefold()))


def _matches(signals, text):
    words = f" {_words(text)} "
    return any(f" {signal} " in words for signal in signals)


def _records(document):
    if isinstance(document, dict) and "messages" in document:
        yield document
    elif isinstance(document, list):
        yield from document
    else:
        raise ValueError("Select a native conversation-export JSON array or a normalized conversation.")


def _messages(record):
    if not isinstance(record, dict):
        return
    conversation = record.get("conversation_id") or record.get("id")
    if isinstance(record.get("mapping"), dict):
        for locator, node in record["mapping"].items():
            if isinstance(node, dict):
                yield conversation, node.get("message"), locator
    elif isinstance(record.get("messages"), list):
        for index, message in enumerate(record["messages"]):
            yield conversation, message, f"message-index:{index}"


def _texts(message):
    content = message.get("content")
    if isinstance(content, str):
        yield content
    elif isinstance(content, dict) and isinstance(content.get("parts"), list):
        for part in content.get("parts", []):
            if isinstance(part, str):
                yield part
            elif isinstance(part, dict):
                for key in ("text", "transcript"):
                    if isinstance(part.get(key), str):
                        yield part[key]
    metadata = message.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("attachments"), list):
        for attachment in metadata["attachments"]:
            if isinstance(attachment, dict):
                name = asset_name(attachment.get("name") or attachment.get("file_name"))
                if name:
                    yield "`" + name + "`"


def _source(archive, conversation, message, locator):
    author = message.get("author")
    role = author.get("role") if isinstance(author, dict) else message.get("role")
    if role not in ("user", "assistant"):
        return None
    conversation, message_id = text_field(conversation, 120), text_field(message.get("id") or locator, 120)
    created = message.get("create_time")
    authored = None
    if type(created) in (int, float):
        try:
            authored = datetime.fromtimestamp(created, timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            pass
    return {"archive": archive, "conversation": conversation, "message": message_id, "role": role, "authored": authored}


def claim_id(claim):
    source = claim["source"]
    return key_for([source["conversation"], source["message"], source["role"],
                    claim["name"], claim["kind"], claim["value"]])


def _claims(line, signals, in_project, source):
    names = []
    for match in REFERENCE.finditer(line):
        code, label, link, bare = match.groups()
        name = asset_name(code or label or bare) or (asset_name(unquote(link)) if link else "")
        if name and (in_project or _matches(signals, name)):
            names.append((name, match.start(), match.end()))
    for name, _, _ in names:
        yield {"name": name, "kind": "reference", "value": "", "source": source}
    if not names or QUALIFIED.search(line) or "?" in line:
        return
    if len(names) == 1:
        name = names[0][0]
        created, lifecycle = CREATED.search(line), LIFECYCLE.search(line)
        if created:
            try:
                value = iso_date(created[1])
            except ValueError:
                return
            yield {"name": name, "kind": "creation_date", "value": value, "source": source}
        if lifecycle:
            yield {"name": name, "kind": "lifecycle", "value": lifecycle[1].casefold(), "source": source}
    if len(names) == 2:
        (name, _, end), (related, start, _) = names
        relation = RELATION.search(line, end, start)
        if relation and name != related:
            yield {"name": name, "kind": "relationship",
                   "value": {"relation": relation[1].casefold(), "asset": related}, "source": source}


def archive_claims(document, archive, project_signals, *, limit=5000):
    """Retain only structured, project-matching evidence with message provenance."""
    signals = tuple(filter(None, map(_words, project_signals)))
    claims = {}
    for record in _records(document):
        if isinstance(record, dict) and record.get("is_do_not_remember") is True:
            continue
        for conversation, message, locator in _messages(record):
            if not isinstance(message, dict):
                continue
            try:
                source = _source(archive, conversation, message, locator)
            except ValueError:
                continue  # Without an ID the evidence cannot be attributed.
            if source is None:
                continue
            texts = [text[:30_000] for text in _texts(message)]
            in_project = any(_matches(signals, text) for text in texts)
            for text in texts:
                for line in text.splitlines():
                    for claim in _claims(line, signals, in_project, source):
                        claims.setdefault(claim_id(claim), claim)
                        if len(claims) > limit:
                            raise ValueError("This archive has too much matching evidence. Select a smaller export.")
    return claims


def creation_index_claims(document, archive, project_signals, *, limit=5000):
    """Project output references from Journey's existing Asset Pipeline index."""
    signals = tuple(filter(None, map(_words, project_signals)))
    claims = {}
    for fingerprint, record in document["entries"].items():
        if not isinstance(record, dict) or record.get("fingerprint") != fingerprint:
            continue
        operation = record.get("operation")
        if not isinstance(operation, str) or not isinstance(record.get("outputs"), dict):
            continue
        source = {"archive": archive, "conversation": "asset-pipeline/" + text_field(operation, 80),
                  "message": text_field(fingerprint, 120), "role": "creation_record", "authored": None}
        job = record.get("job")
        in_project = isinstance(job, str) and _matches(signals, job)
        pending = [record["outputs"]]
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
            elif isinstance(value, str) and (in_project or _matches(signals, value)):
                name = asset_name(value)
                if name:
                    claim = {"name": name, "kind": "reference", "value": "", "source": source}
                    claims.setdefault(claim_id(claim), claim)
                    if len(claims) > limit:
                        raise ValueError("This creation index has too much matching evidence.")
    return claims
