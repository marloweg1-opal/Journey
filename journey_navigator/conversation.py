"""Interpret live instructions into a small proposal vocabulary."""

import http.client
import json
import re
from threading import BoundedSemaphore

from core.naming_audit import contains_words, words


MODEL = "qwen3:4b"
MAX_PROMPT = 2000
MAX_REPLY = 64 * 1024
RETIRE = r"(?:retire|decommission|phase out|withdraw support for)"
UNSURE = re.compile(r"\b(?:suppose|hypothetical|what if|for example|maybe we|should we)\b", re.I)
NEGATIVE = re.compile(rf"\b(?:do not|don['’]t|never|must not|cannot)\s+(?:\w+\s+){{0,2}}{RETIRE}\b", re.I)
QUOTED = re.compile(r'["“]([^"”\n]+)["”]')
SHORT_COMMAND = re.compile(rf"^(?:please\s+)?{RETIRE}\s+(?:all\s+|the\s+)?(.+?)(?:\s+assets?)?[.!]?$", re.I)
CARECYCLE = re.compile(r"^\s*(.{2,96}?)\s+is\s+(?:about\s+|approximately\s+)?\d{1,8}\s+carecycles? past (?:its |the )?expiration date\s*[,;.!]?\s*(?:i don['’]t need that design anymore|retire (?:that|the) design)[.!]?\s*$", re.I)
SHAPE = {
    "type": "object", "additionalProperties": False, "required": ["action", "family"],
    "properties": {"action": {"enum": ["retire_family", "organize_scope", "find_reference", "unsupported"]},
                   "family": {"type": "string", "maxLength": 96}},
}


def validate_prompt(prompt):
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= MAX_PROMPT:
        raise ValueError("Write one stewardship instruction of up to 2,000 characters.")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in prompt):
        raise ValueError("Use plain text for the stewardship instruction.")
    return prompt.strip()


def _directive(prompt):
    unquoted = QUOTED.sub(" ", prompt)
    return bool(re.search(rf"\b{RETIRE}\b", unquoted, re.I)
                and not UNSURE.search(unquoted) and not NEGATIVE.search(unquoted) and "?" not in unquoted)


def _family(prompt, value):
    if (not isinstance(value, str) or not 2 <= len(value.strip()) <= 96
            or any(char in value for char in "\\/:*?<>|\"\n\r") or not 1 <= len(words(value).split()) <= 10
            or not contains_words(prompt, value)):
        return None
    return value.strip()


def explicit_intent(prompt):
    playful = CARECYCLE.fullmatch(prompt)
    if playful and not UNSURE.search(playful[1]):
        return _family(prompt, playful[1].strip('"“” '))
    if not _directive(prompt):
        return None
    quoted = QUOTED.findall(prompt)
    if len(quoted) == 1:
        return _family(prompt, quoted[0])
    short = SHORT_COMMAND.fullmatch(prompt)
    return _family(prompt, short[1]) if short and not quoted else None


class LocalQwen:
    """Fixed loopback adapter. The model sees the live instruction and schema."""

    def __init__(self, *, port=11434):
        self.port = port
        self.busy = BoundedSemaphore(1)

    def _interpret(self, prompt):
        client = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        body = json.dumps({"model": MODEL, "stream": False, "think": False, "format": SHAPE,
                           "options": {"temperature": 0, "num_predict": 120},
                           "messages": [{"role": "system", "content": (
                               "Classify one live instruction as retire_family, organize_scope, find_reference or unsupported. "
                               "Retirement must be affirmative. For retirement or find, copy the exact design or search phrase. "
                               "For other actions use an empty family. These are read-only proposals. "
                               "You have no file, tool, permission, or execution capabilities.")},
                               {"role": "user", "content": prompt}]}).encode("utf-8")
        try:
            client.request("POST", "/api/chat", body=body, headers={"Content-Type": "application/json"})
            response = client.getresponse()
            if response.status != 200:
                return {"state": "TOOL_UNAVAILABLE", "family": None}
            reply = response.read(MAX_REPLY + 1)
            if len(reply) > MAX_REPLY:
                return {"state": "FAILED", "family": None}
            envelope = json.loads(reply)
            message = envelope["message"]
            if message.get("tool_calls"):
                return {"state": "FAILED", "family": None}
            proposed = json.loads(message["content"])
        finally:
            client.close()
        if not isinstance(proposed, dict) or set(proposed) != {"action", "family"}:
            return {"state": "NEEDS_HUMAN_DECISION", "family": None}
        if proposed["action"] == "organize_scope" and proposed["family"] == "" and re.search(
                r"\b(?:organize|organise|classify|group|arrange)\b", prompt, re.I) and not UNSURE.search(prompt):
            return {"state": "CANDIDATE", "family": None, "intent": "organize"}
        if proposed["action"] == "find_reference" and re.search(r"\b(?:find|search|locate|look for)\b", prompt, re.I) and not UNSURE.search(prompt):
            if term := _family(prompt, proposed["family"]):
                return {"state": "CANDIDATE", "family": None, "intent": "find", "term": term}
        if proposed["action"] != "retire_family":
            return {"state": "NEEDS_HUMAN_DECISION", "family": None}
        family = _family(prompt, proposed["family"]) if _directive(prompt) else None
        return {"state": "CANDIDATE" if family else "NEEDS_HUMAN_DECISION", "family": family}

    def interpret(self, prompt):
        if not self.busy.acquire(blocking=False):
            return {"state": "TOOL_UNAVAILABLE", "family": None}
        try:
            return self._interpret(validate_prompt(prompt))
        except (OSError, http.client.HTTPException):
            return {"state": "TOOL_UNAVAILABLE", "family": None}
        except (ValueError, KeyError, TypeError, AttributeError):
            return {"state": "FAILED", "family": None}
        finally:
            self.busy.release()
