"""
Mini ARK security hooks.

Per Amendment 1: "Security architecture begins early. Sensitive
capability does not unlock until the corresponding protections exist."

This module is deliberately small right now. It does NOT implement
encryption, credential vaults, or threat modeling -- that arrives before
Tier 4+ unlocks, as its own dedicated phase. What it enforces today is
the discipline that makes that later phase possible without a rewrite.
"""

import re

# Patterns that should never appear in logs or the ledger. Not
# exhaustive -- a real secrets-scanner is a Tier 4 prerequisite, not a
# Phase 1 one. This is a first line of defense against obvious mistakes.
_SECRET_LIKE_PATTERNS = [
    re.compile(r"api[_-]?key", re.IGNORECASE),
    re.compile(r"password\s*[:=]", re.IGNORECASE),
    re.compile(r"secret[_-]?key", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),
]


def scrub_for_logging(text: str) -> str:
    """
    Defense-in-depth check before anything gets written to a log or the
    ledger. Flags rather than silently strips, so a real leak is
    visible and investigatable rather than quietly vanished.
    """
    for pattern in _SECRET_LIKE_PATTERNS:
        if pattern.search(text):
            return "[REDACTED -- possible credential detected, see caller]"
    return text


def assert_not_administrator_path(path: str):
    """
    Mini ARK does not assume administrator access, per Amendment 1.
    This is a soft guard: it flags paths that typically require
    elevated permissions on Windows, so a scan/operation fails loudly
    and safely rather than silently requesting more access than granted.
    """
    elevated_indicators = ["System32", "Program Files\\WindowsApps", "\\Windows\\"]
    for indicator in elevated_indicators:
        if indicator.lower() in path.lower():
            print(f"[WARNING] {path} typically requires elevated access. "
                  f"Mini ARK does not request administrator rights automatically.")
            return False
    return True
