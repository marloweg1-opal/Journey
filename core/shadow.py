"""Gate A Shadow Mode.

Shadow Mode executes the real read-only reasoning path and records what
Mini ARK would propose without mutating managed filesystem content.
"""

from __future__ import annotations

import json
import os
import stat as statmod
import time
from pathlib import Path
from typing import Any

from core.placement import (
    CONGRUENT,
    LIKELY_CONGRUENT,
    PROTECTED_OPERATIONAL,
    TRANSIENT_ACCEPTABLE,
    UNKNOWN,
    doctrine_summary,
    evaluate_placement,
)
from scanner.scanner import normalize_path
from core.patrol import live_discover, initialize_patrol, scoped_policy, compare_observations, check_authority
from core.apply import is_protected, get_active_dependents
from core.dependency_evidence import inspect_references
from core.recovery_domain import observe as recovery_observe
from core.read_guard import require_path_not_held


SHADOW_REPORT_PREFIX = "SHADOW_RUN"


def _stamp() -> str:
    return time.strftime("%Y-%m-%d_%H%M%S")


def _path_like(scope: str) -> str:
    return normalize_path(scope).rstrip("\\/") + "%"


def _metadata_probe(row: Any) -> tuple[str, str | None]:
    row = dict(row)
    path = Path(row["canonical_path"])
    try:
        require_path_not_held(path)
        for candidate in (*reversed(path.parents), path):
            require_path_not_held(path)
            require_path_not_held(candidate)
            info = os.lstat(candidate)
            if statmod.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                return "REPARSE_POINT_SKIPPED", "Live verification would cross a reparse point."
        stat = info
    except FileNotFoundError:
        return "MISSING_DURING_SHADOW", "Path was present in the ledger but missing during Shadow Mode."
    except (OSError, PermissionError) as exc:
        return "UNREADABLE_DURING_SHADOW", f"Could not stat current file: {exc}"
    mtime_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(stat.st_mtime))
    live = row.get('live_observation') or (row if row.get('evidence_source') == 'live_scan' else None)
    if live and (live['size_bytes'] != stat.st_size or live.get('mtime_ns') != stat.st_mtime_ns):
        return 'UNSTABLE_DURING_SCAN', 'Metadata changed between discovery and verification within this sweep.'
    mismatch = 'LEDGER_METADATA_DRIFT' if row.get('evidence_source') in {'both', 'ledger'} else 'UNSTABLE_DURING_SCAN'
    if row["size_bytes"] is not None and row["size_bytes"] != stat.st_size:
        return mismatch, 'Recorded size differs from current metadata; this does not prove concurrent writes.'
    if row["modified_at"] and row["modified_at"] != mtime_iso:
        return mismatch, 'Recorded modified time differs from current metadata; this does not prove concurrent writes.'
    return "stable", None


def _review_family(result: dict[str, Any], instability: str) -> str:
    target = result.get("likely_canonical_placement") or {}
    classification = result.get("classification") or {}
    if instability != "stable":
        return f"unstable::{instability}"
    if result["state"] == PROTECTED_OPERATIONAL:
        return f"protected::{target.get('id', 'unknown')}"
    if result["state"] == UNKNOWN:
        return f"unknown::{classification.get('bucket', 'unknown')}"
    return "::".join(
        [
            result.get("resolution_strategy", "REVIEW"),
            result["state"],
            result.get("recommended_action", "review"),
            target.get("id", "unknown"),
            classification.get("owner", "Unknown"),
        ]
    )


def _risk_for(result: dict[str, Any], instability: str) -> str:
    if instability != "stable":
        return "yellow"
    if result["state"] == PROTECTED_OPERATIONAL:
        return "green"
    if result["state"] in {CONGRUENT, LIKELY_CONGRUENT, TRANSIENT_ACCEPTABLE}:
        return "green"
    if result["state"] == UNKNOWN:
        return "yellow"
    return "yellow"


def _proposal_action_for(result: dict[str, Any], instability: str) -> str | None:
    if instability != "stable":
        return None
    if result["state"] in {CONGRUENT, LIKELY_CONGRUENT, PROTECTED_OPERATIONAL, TRANSIENT_ACCEPTABLE}:
        return None
    if result["state"] == UNKNOWN:
        return "classify_or_defer"
    return result["recommended_action"]


def _finding_description(result: dict[str, Any], instability: str, blocking_reason: str | None) -> str:
    target = result.get("likely_canonical_placement") or {}
    if blocking_reason:
        return f"{result['state']}: {blocking_reason}"
    if target.get("path"):
        return f"{result.get('resolution_strategy', 'REVIEW')}: {result['state']}: likely home is {target['path']}"
    return f"{result['state']}: {result['reason']}"


def _write_reports(docs_root: Path, run_id: int, summary: dict[str, Any], evidence: dict[str, Any]) -> tuple[str, str]:
    docs_root.mkdir(parents=True, exist_ok=True)
    stamp = _stamp()
    json_path = docs_root / f"{SHADOW_REPORT_PREFIX}_{run_id}_{stamp}.json"
    md_path = docs_root / f"{SHADOW_REPORT_PREFIX}_{run_id}_{stamp}.md"
    json_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    lines = [
        f"# Shadow Run {run_id}",
        "",
        f"- Scope: `{summary['scope']}`",
        f"- Status: {summary['status']}",
        f"- Files examined: {summary['files_examined']}",
        f"- Files implicated: {summary['files_implicated']}",
        f"- Review families: {summary['review_families']}",
        f"- Estimated human decisions: {summary['estimated_human_decisions']}",
        f"- Managed file mutations: 0",
        "",
        "## Summary",
        "",
    ]
    for state, count in summary["states"].items():
        lines.append(f"- {state}: {count}")
    lines.extend(["", "## Resolution Strategies", ""])
    for strategy, count in summary["resolution_strategies"].items():
        lines.append(f"- {strategy}: {count}")
    lines.extend(["", "## Review Families", ""])
    for family in summary["families"]:
        lines.append(f"- {family['review_family']}: {family['count']} item(s), risk {family['risk']}")
        lines.append(f"  - strategy: {family['resolution_strategy']}")
        lines.append(f"  - action: {family['recommended_action']}")
        if family.get("target"):
            lines.append(f"  - target: `{family['target']}`")
    lines.extend(["", "## Evidence", "", f"Full evidence: `{json_path}`", ""])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return str(md_path), str(json_path)


def run_shadow(conn, *, scope: str, docs_root: str, limit: int | None = None, verify_current: bool = True) -> dict[str, Any]:
    from core.patrol_state import read_state
    if read_state(conn)['paused']:
        raise PermissionError('Patrol is paused or its persisted state requires review')
    initialize_patrol(conn)
    limit = min(limit or 500, 5000)
    if limit < 1:
        raise ValueError("Shadow limit must be positive")
    placement_policy = doctrine_summary().get("placement_policy") or 2
    cur = conn.execute(
        """INSERT INTO shadow_runs
        (scope, architecture_policy_version, classifier_version, placement_policy_version, inventory_generation, status)
        VALUES (?, ?, ?, ?, ?, 'running');""",
        (scope, 1, 2, placement_policy, "ledger:files"),
    )
    run_id = cur.lastrowid
    conn.commit()

    normalized = normalize_path(scope).rstrip("\\/")
    escaped = normalized.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    params: list[Any] = [normalized, escaped + "\\%"]
    limit_clause = ""
    if limit is not None and limit > 0:
        limit_clause = " LIMIT ?"
        params.append(limit)
    rows = conn.execute(
        f"""SELECT canonical_path, hash, size_bytes, modified_at
            FROM files
            WHERE status='present' AND (canonical_path = ? COLLATE NOCASE OR canonical_path LIKE ? ESCAPE '!')
            ORDER BY canonical_path{limit_clause};""",
        tuple(params),
    ).fetchall()
    ledger_rows = {normalize_path(r["canonical_path"]).casefold(): dict(r) for r in rows}
    discovery = {"complete": False, "errors": [], "skipped": [], "disabled": True}
    live_rows = []
    if verify_current:
        live_rows, discovery = live_discover(scope, max_files=limit)
    combined = {}
    for row in live_rows:
        key = normalize_path(row["canonical_path"]).casefold()
        if key in ledger_rows:
            row = {**ledger_rows[key], "evidence_source": "both", 'live_observation':row}
        combined[key] = row
    for key, row in ledger_rows.items():
        if key not in combined and len(combined) < limit:
            combined[key] = {**row, "evidence_source": "ledger"}
    rows = sorted(combined.values(), key=lambda r: r["canonical_path"].casefold())
    dependency_search = inspect_references([r['canonical_path'] for r in rows], [scope],
        max_files=64, max_bytes=500_000, max_seconds=2, privacy_conn=conn) if verify_current else None
    evidence_source = "both" if live_rows and ledger_rows else "live_scan" if verify_current else "ledger"
    posture = scoped_policy(conn, scope, "lifecycle")
    observations = []

    findings = []
    proposals = []
    family_map: dict[str, dict[str, Any]] = {}
    state_counts: dict[str, int] = {}
    strategy_counts: dict[str, int] = {}
    files_implicated = 0

    for row in rows:
        result = evaluate_placement(row["canonical_path"])
        reservation = is_protected(conn, row["canonical_path"])
        dependencies = get_active_dependents(conn, row["canonical_path"])
        if reservation or dependencies:
            result.update(state=PROTECTED_OPERATIONAL, placement_congruence=PROTECTED_OPERATIONAL,
                          resolution_strategy="LEAVE", recommended_action="leave_protected",
                          reason=reservation or "Registered application dependencies require this location",
                          operational_location={"path": row["canonical_path"]})
        path_posture = scoped_policy(conn, row["canonical_path"], "lifecycle")
        instability, blocking_reason = _metadata_probe(row) if verify_current else ("stable", None)
        review_family = _review_family(result, instability)
        risk = _risk_for(result, instability)
        proposal_action = _proposal_action_for(result, instability)
        state = instability if instability != "stable" else result["state"]
        bounded_references = [r for r in (dependency_search or {}).get('references', []) if r['target']==row['canonical_path']]
        observations.append({"path": row["canonical_path"], "size": row["size_bytes"],
                             "modified": row["modified_at"], "state": state,
                             "strategy": result["resolution_strategy"],
                             "target": result.get("likely_canonical_placement"),
                             'dependency_references': bounded_references,
                             'inspected_content_fingerprint':next((r['fingerprint'] for r in (dependency_search or {}).get('checked', []) if r['path']==row['canonical_path']), None),
                             'registered_references':[dict(d) for d in dependencies],
                             "lifecycle": path_posture, "policy": placement_policy})
        state_counts[state] = state_counts.get(state, 0) + 1
        strategy = "REVIEW" if instability != "stable" else result.get("resolution_strategy", "REVIEW")
        strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
        target = result.get("likely_canonical_placement") or {}
        classification = result.get("classification") or {}
        interesting = state not in {CONGRUENT, LIKELY_CONGRUENT}
        if not interesting:
            continue
        files_implicated += 1
        evidence = {
            'recovery_observation': recovery_observe(row['canonical_path'],row['size_bytes']),
            "placement": result,
            "instability": instability,
            "blocking_reason": blocking_reason,
            "policy_rule": "shadow_mode_no_managed_files_mutated",
            "evidence_source": row["evidence_source"],
            'dependency_evidence': {
                'dependency_state':'UNKNOWN',
                'registered_references':[dict(d) for d in dependencies],
                'bounded_references':bounded_references,
                'observation':next((r for r in (dependency_search or {}).get('target_observations', []) if r['target']==row['canonical_path']), {'reference_observation':'NOT_INSPECTED'}),
                'coverage_source':'run.summary.dependency_coverage',
            },
            "lifecycle_posture": path_posture,
            "delegated_authority": check_authority(conn, row["canonical_path"], "placement", {"managed_mutation": True}, shadow=True),
            "attention_posture": "REVIEW_QUEUE" if proposal_action else "SILENT",
        }
        cur = conn.execute(
            """INSERT INTO stewardship_findings
            (shadow_run_id, finding_type, subject_type, path, classification, placement_status,
             status, reason, confidence, risk, evidence_json, references_json, dependents_json,
             recommended_action)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);""",
            (
                run_id,
                "shadow_placement",
                classification.get("subject_type"),
                row["canonical_path"],
                json.dumps(classification),
                state,
                "open",
                _finding_description(result, instability, blocking_reason),
                0.0 if instability != "stable" else None,
                risk,
                json.dumps(evidence),
                json.dumps({"status": "registered_checked", "items": [dict(d) for d in dependencies]}),
                json.dumps({"status": "not_checked"}),
                proposal_action or f"strategy:{strategy}",
            ),
        )
        finding_id = cur.lastrowid
        conn.execute("""UPDATE stewardship_proposals SET status='superseded',resolved_at=datetime('now')
                        WHERE status IN ('pending','reviewed') AND finding_id IN (
                          SELECT f.id FROM stewardship_findings f JOIN shadow_runs r ON r.id=f.shadow_run_id
                          WHERE f.path=? AND r.scope=? AND r.id<>?)""",
                     (row["canonical_path"],scope,run_id))
        conn.execute("UPDATE stewardship_findings SET resolution_strategy=?,evidence_source=?,lifecycle_posture=?,attention_posture=?,confidence_dimensions_json=? WHERE id=?",
                     (strategy,row["evidence_source"],path_posture["value"],evidence["attention_posture"],json.dumps(result["confidence_dimensions"]),finding_id))
        findings.append({"id": finding_id, "path": row["canonical_path"], "state": state, "review_family": review_family})
        if proposal_action:
            description = f"Shadow proposal for {row['canonical_path']}: {proposal_action}"
            cur = conn.execute(
                """INSERT INTO stewardship_proposals
                (shadow_run_id, finding_id, capability_id, owner, domain, operation, description,
                 proposed_action, subject_count, confidence, risk, approval_required, preview_available,
                 undo_available, status, review_group_key, review_cost, proof)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);""",
                (
                    run_id,
                    finding_id,
                    "shadow-placement",
                    classification.get("owner"),
                    "placement",
                    "shadow",
                    description,
                    proposal_action,
                    1,
                    None,
                    risk,
                    1,
                    0,
                    0,
                    "pending",
                    review_family,
                    1,
                    "shadow_only_no_files_mutated",
                ),
            )
            proposal_id = cur.lastrowid
            conn.execute("UPDATE stewardship_proposals SET resolution_strategy=? WHERE id=?", (strategy,proposal_id))
            proposals.append({"id": proposal_id, "finding_id": finding_id, "review_family": review_family})
        family = family_map.setdefault(
            review_family,
            {
                "review_family": review_family,
                "count": 0,
                "risk": risk,
                "resolution_strategy": strategy,
                "recommended_action": "verify_metadata" if instability != "stable" else proposal_action or result.get("recommended_action"),
                "target": target.get("path"),
                "examples": [],
            },
        )
        family["count"] += 1
        if len(family["examples"]) < 5:
            family["examples"].append(row["canonical_path"])

    conn.commit()
    families = sorted(family_map.values(), key=lambda item: (-item["count"], item["review_family"]))
    estimated_decisions = len([family for family in families if family["recommended_action"] not in {"leave", "leave_protected"}])
    comparison = compare_observations(conn, normalized.casefold(), run_id, observations, complete=discovery["complete"])
    run_status = "complete" if discovery["complete"] or not verify_current else "partial"
    summary = {
        "shadow_run_id": run_id,
        "scope": scope,
        "status": run_status,
        "evidence_source": evidence_source,
        "coverage": discovery,
        'dependency_coverage': {k:v for k,v in (dependency_search or {}).items() if k not in {'references','structured_candidates','target_observations'}},
        "lifecycle_posture": posture,
        "attention_posture": "DIGEST" if comparison["added"] or comparison["changed"] or comparison["not_observed"] else "SILENT",
        "comparison": comparison,
        "budget": {"files": limit, "entries": 10000, "seconds": 15, "depth": 20},
        "files_examined": len(rows),
        "files_implicated": files_implicated,
        "review_families": len(families),
        "estimated_human_decisions": estimated_decisions,
        "states": state_counts,
        "resolution_strategies": strategy_counts,
        "families": families,
        "managed_file_mutations": 0,
    }
    evidence = {"summary": summary, "findings": findings, "proposals": proposals, "families": families}
    report_path, evidence_path = _write_reports(Path(docs_root), run_id, summary, evidence)
    conn.execute(
        """UPDATE shadow_runs
           SET completed_at=datetime('now'), status=?, inventory_generation=?, files_examined=?, files_implicated=?,
               review_families=?, estimated_human_decisions=?, summary_json=?, report_path=?, evidence_path=?
           WHERE id=?;""",
        (
            run_status,
            evidence_source,
            len(rows),
            files_implicated,
            len(families),
            estimated_decisions,
            json.dumps(summary),
            report_path,
            evidence_path,
            run_id,
        ),
    )
    conn.commit()
    summary["report_path"] = report_path
    summary["evidence_path"] = evidence_path
    return summary
