"""Operation-bound evidence contract. No production issuer is installed here.

Verifier implementations are trusted application code, never plan/API data.
Implementations must independently authenticate approval, scope, ownership and
action-specific dependency evidence. An empty reference search is insufficient.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
import hashlib
import json
import math
from pathlib import Path
import time


class MoveEvidenceDenied(ValueError):
    pass


def approval_binding(proposal):
    return hashlib.sha256(json.dumps(dict(proposal), sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


@dataclass(frozen=True)
class MoveIdentity:
    sha256: str
    size: int
    inode: int
    device: int
    mtime_ns: int


@dataclass(frozen=True)
class MoveEvidence:
    receipt_id: str
    approval_reference: str
    approval_binding: str
    evidence_references: tuple[str, ...]
    proposal_id: int
    item_id: int
    source: str
    destination: str
    source_scope: str
    destination_scope: str
    identity: MoveIdentity
    issued_at: float
    expires_at: float


class MoveEvidenceVerifier(ABC):
    @abstractmethod
    def verify(self, conn, item, *, phase):
        """Return authenticated MoveEvidence, or deny; recheck revocation each call.

        No default implementation, automatic approval or production issuer exists.
        This interface does not itself grant content-read or mutation authority.
        """


def _within(path, scope):
    if not isinstance(path, str) or not isinstance(scope, str):
        return False
    path, scope = Path(path), Path(scope)
    return (path.is_absolute() and scope.is_absolute()
            and '..' not in path.parts and '..' not in scope.parts
            and path.is_relative_to(scope))


def checked_evidence(verifier, conn, item, *, phase):
    if not isinstance(verifier, MoveEvidenceVerifier):
        raise MoveEvidenceDenied('Trusted code-level verifier required')
    try:
        evidence = verifier.verify(conn, dict(item), phase=phase)
        if type(evidence) is not MoveEvidence or type(evidence.identity) is not MoveIdentity:
            raise MoveEvidenceDenied('Typed operation evidence required')
        proposal = conn.execute('SELECT * FROM proposals WHERE id=?',
                                (item['proposal_id'],)).fetchone()
        current = conn.execute('SELECT * FROM proposal_items WHERE id=?',
                               (item['id'],)).fetchone()
        fields = ('id', 'proposal_id', 'canonical_path', 'dest_path', 'requested_mode')
        if (proposal is None or proposal['status'] != 'approved' or current is None
                or current['status'] != 'pending'
                or any(current[key] != item[key] for key in fields)
                or item['requested_mode'] != 'move'
                or type(evidence.item_id) is not int or type(evidence.proposal_id) is not int
                or evidence.item_id != item['id'] or evidence.proposal_id != item['proposal_id']
                or evidence.source != item['canonical_path']
                or evidence.destination != item['dest_path']
                or evidence.approval_binding != approval_binding(proposal)):
            raise MoveEvidenceDenied('Operation or approval binding changed')
        if not all(isinstance(value, str) and value.strip() for value in
                   (evidence.receipt_id, evidence.approval_reference)):
            raise MoveEvidenceDenied('Evidence provenance required')
        if (type(evidence.evidence_references) is not tuple or not evidence.evidence_references
                or not all(isinstance(ref, str) and ref.strip() for ref in evidence.evidence_references)):
            raise MoveEvidenceDenied('Affirmative action evidence references required')
        if not (_within(evidence.source, evidence.source_scope)
                and _within(evidence.destination, evidence.destination_scope)):
            raise MoveEvidenceDenied('Operation outside evidence scope')
        if any(type(value) not in (int, float) or not math.isfinite(value)
               for value in (evidence.issued_at, evidence.expires_at)):
            raise MoveEvidenceDenied('Invalid evidence validity window')
        if not evidence.issued_at <= time.time() < evidence.expires_at:
            raise MoveEvidenceDenied('Evidence expired or not yet valid')
        identity = asdict(evidence.identity)
        digest = identity.pop('sha256')
        if (not isinstance(digest, str) or len(digest) != 64
                or any(c not in '0123456789abcdef' for c in digest)
                or any(type(v) is not int or v < 0 for v in identity.values())):
            raise MoveEvidenceDenied('Invalid source identity')
        return evidence
    except MoveEvidenceDenied:
        raise
    except Exception:
        # Provider errors must not leak inspected content or permit fallback.
        raise MoveEvidenceDenied('Evidence verifier failed closed') from None
