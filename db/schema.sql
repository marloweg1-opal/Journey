-- Mini ARK Ledger Schema
-- Schema version 1
-- Governing rule: Raw -> Event -> Accepted State. Nothing here treats
-- an AI-generated interpretation as truth on arrival.

CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

-- WHERE information came from. Every other table should be traceable
-- back to a source. No source = no provenance = not trusted.
CREATE TABLE IF NOT EXISTS sources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,          -- 'filesystem_scan' | 'ai_handoff' | 'manual' | 'import'
    label       TEXT,                   -- human-readable origin
    platform    TEXT,                   -- 'Claude' | 'ChatGPT' | 'local' | etc.
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Anything Mini ARK can reason about: a project, a system, a person,
-- a device, a service, a concept.
CREATE TABLE IF NOT EXISTS entities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,          -- 'project' | 'system' | 'person' | 'device' | 'service' | 'concept'
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(entity_type, name)
);

CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id   INTEGER REFERENCES entities(id),
    name        TEXT NOT NULL UNIQUE,
    status      TEXT NOT NULL DEFAULT 'active',   -- active | parked | archived
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Canonical file records. This is what "coherence before autonomy"
-- actually runs on: knowing what exists and whether it changed.
CREATE TABLE IF NOT EXISTS files (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_path  TEXT NOT NULL UNIQUE,
    hash            TEXT,
    size_bytes      INTEGER,
    modified_at     TEXT,
    first_seen_at   TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at    TEXT NOT NULL DEFAULT (datetime('now')),
    status          TEXT NOT NULL DEFAULT 'present',  -- present | missing | deleted
    project_id      INTEGER REFERENCES projects(id)
);

-- One row per completed (or in-progress, or interrupted) filesystem scan.
CREATE TABLE IF NOT EXISTS scans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    root_path       TEXT NOT NULL,
    started_at      TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at    TEXT,
    files_scanned   INTEGER DEFAULT 0,
    files_added     INTEGER DEFAULT 0,
    files_changed   INTEGER DEFAULT 0,
    files_missing   INTEGER DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'running',  -- running | complete | failed | interrupted
    last_committed_path TEXT,   -- most recent file whose row is durably committed
    interrupted_at  TEXT
);

-- What changed. Starts life as 'raw' and only becomes 'accepted' through
-- explicit reconciliation -- never automatically.
CREATE TABLE IF NOT EXISTS events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type          TEXT NOT NULL,     -- 'file_added' | 'file_changed' | 'file_missing' | 'statement_detected' | ...
    description         TEXT NOT NULL,
    entity_id           INTEGER REFERENCES entities(id),
    project_id          INTEGER REFERENCES projects(id),
    source_id           INTEGER REFERENCES sources(id),
    confidence          REAL,              -- 0.0-1.0, NULL if not applicable
    status              TEXT NOT NULL DEFAULT 'raw',  -- raw | proposed | accepted | rejected | superseded
    supersedes_event_id INTEGER REFERENCES events(id),
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS decisions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    project_id  INTEGER REFERENCES projects(id),
    source_id   INTEGER REFERENCES sources(id),
    decided_at  TEXT NOT NULL DEFAULT (datetime('now')),
    status      TEXT NOT NULL DEFAULT 'active'  -- active | reversed | superseded
);

-- Raw AI/session continuity packets, preserved verbatim. Ingestion never
-- auto-canonizes their contents -- see events.status.
CREATE TABLE IF NOT EXISTS handoffs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    packet_id        TEXT UNIQUE,
    source_id        INTEGER REFERENCES sources(id),
    summary          TEXT,
    raw_json         TEXT,               -- full original packet, untouched
    ingested_at      TEXT NOT NULL DEFAULT (datetime('now')),
    requires_review  INTEGER NOT NULL DEFAULT 0
);

-- Changes Mini ARK believes should happen. Never self-executing.
-- severity/urgency per Amendment 1: reconciliation must triage, not dump
-- an undifferentiated pile of 67 things on Jr.
CREATE TABLE IF NOT EXISTS proposals (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    description       TEXT NOT NULL,
    related_event_id  INTEGER REFERENCES events(id),
    project_id        INTEGER REFERENCES projects(id),
    severity          TEXT NOT NULL DEFAULT 'notice',  -- critical | decision | notice | background
    batch_key         TEXT,   -- shared key lets similar proposals collapse into one summary line
    status            TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at       TEXT
);

-- Explicit permission tiers (0-5, per constitution). Competence does not
-- confer authority -- this table is the only source of truth for "may."
CREATE TABLE IF NOT EXISTS permissions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tier        INTEGER NOT NULL,     -- 0 Observe .. 5 Sensitive/Consequential
    scope       TEXT NOT NULL,
    granted     INTEGER NOT NULL DEFAULT 0,
    granted_at  TEXT,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS relationships (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    from_entity_id      INTEGER REFERENCES entities(id),
    to_entity_id        INTEGER REFERENCES entities(id),
    relationship_type   TEXT NOT NULL,  -- 'depends_on' | 'part_of' | 'related_to' | ...
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS open_loops (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    description      TEXT NOT NULL,
    project_id       INTEGER REFERENCES projects(id),
    severity         TEXT NOT NULL DEFAULT 'notice',  -- critical | decision | notice | background
    status           TEXT NOT NULL DEFAULT 'open',  -- open | resolved | stale
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now')),
    last_touched_at  TEXT
);

-- Scoped conflicts, per Amendment 1. A conflict between two events/facts
-- has a SCOPE (which entity/project it actually concerns). Only
-- conclusions that depend on that scope are blocked -- a disputed
-- Musicstone label does not stop Mini ARK from finding the dishwasher
-- manual. Mini ARK must never silently pick newest-wins to resolve one
-- of these; resolution requires an explicit decision.
CREATE TABLE IF NOT EXISTS conflicts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_a_event_id   INTEGER REFERENCES events(id),
    fact_b_event_id   INTEGER REFERENCES events(id),
    scope_entity_id   INTEGER REFERENCES entities(id),  -- what this conflict is actually about
    description       TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'conflicted',  -- trusted | provisional | conflicted | deprecated
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at       TEXT,
    resolution_note   TEXT
);

-- Caches ffprobe results per file. This is what makes media-organize
-- resumable: an interrupted run leaves whatever it already probed
-- committed here, and re-running simply skips anything already cached
-- rather than re-probing from zero. Same philosophy as the scanner's
-- unchanged-file skip.
CREATE TABLE IF NOT EXISTS video_duration_cache (
    canonical_path    TEXT PRIMARY KEY,
    duration_seconds  REAL,
    bucket            TEXT,
    probed_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Append-only action log. This is the mechanism behind the "reversible"
-- claim in the spec -- every mutating action gets a row here before it
-- runs, so `ark undo <id>` has something concrete to reverse.
CREATE TABLE IF NOT EXISTS action_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type   TEXT NOT NULL,        -- 'file_move' | 'file_rename' | 'shortcut_created' | ...
    tier          INTEGER NOT NULL,     -- permission tier this action required
    target_path   TEXT,
    previous_state TEXT,                -- JSON snapshot sufficient to reverse the action
    new_state     TEXT,
    status        TEXT NOT NULL DEFAULT 'applied',  -- applied | reversed
    performed_at  TEXT NOT NULL DEFAULT (datetime('now')),
    reversed_at   TEXT
);

-- Per-file resolution of a proposal. Proposals themselves only ever
-- stored an aggregate description ("42 video files") -- this table is
-- what apply() actually walks, one row per file, one decision per file.
-- Mode is per-ITEM, not per-proposal: a batch can be mixed (some files
-- shortcut, some genuinely relocated) per Amendment-1-style granularity.
CREATE TABLE IF NOT EXISTS proposal_items (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id       INTEGER NOT NULL REFERENCES proposals(id),
    canonical_path    TEXT NOT NULL,
    dest_path         TEXT,                              -- NULL for 'quarantine' mode (no chosen destination)
    requested_mode    TEXT NOT NULL DEFAULT 'shortcut',  -- 'move' | 'shortcut' | 'quarantine'
    resolved_mode     TEXT,                              -- what apply ACTUALLY did, after safety checks
    status            TEXT NOT NULL DEFAULT 'pending',    -- pending | applied | skipped | blocked
    block_reason      TEXT,
    action_log_id     INTEGER REFERENCES action_log(id),
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at       TEXT
);

-- What external programs/configs reference a given canonical path.
-- This is how apply() knows a real move would strand a Rainmeter skin,
-- a CareBloomOS reference, etc. Populated either manually
-- (register_dependent) or via a plain-text scan of a config file
-- (scan_config_for_dependents) -- Mini ARK does not guess this on its
-- own; an unregistered dependent is invisible to it by design, same
-- "no silent trust" rule as everything else in this ledger.
CREATE TABLE IF NOT EXISTS file_dependents (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_path      TEXT NOT NULL,       -- the asset being depended on
    program_name        TEXT NOT NULL,       -- 'Rainmeter' | 'CareBloomOS' | 'Welfare Witchcraft' | ...
    reference_location  TEXT,                -- config file the reference lives in
    reference_context   TEXT,                -- the actual line/snippet matched, for the change report
    status              TEXT NOT NULL DEFAULT 'active',   -- active | stale
    detected_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Stewardship identity records. Paths are not identity: a path can
-- change, while a filesystem object, content fingerprint, metadata
-- fingerprint, or logical asset family may persist.
CREATE TABLE IF NOT EXISTS stewardship_file_identities (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    current_path           TEXT NOT NULL,
    normalized_path        TEXT NOT NULL,
    filesystem_object_id   TEXT,
    volume_identity        TEXT,
    content_fingerprint    TEXT,
    metadata_fingerprint   TEXT,
    logical_asset_id       TEXT,
    identity_confidence    REAL,
    first_seen_at          TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at           TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(normalized_path)
);

-- Gate A simulation run identity. Shadow Mode may write Mini ARK
-- evidence, findings, proposals, and reports, but it must not mutate
-- managed filesystem content.
CREATE TABLE IF NOT EXISTS shadow_runs (
    id                           INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at                   TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at                 TEXT,
    scope                        TEXT NOT NULL,
    architecture_policy_version  INTEGER,
    classifier_version           INTEGER,
    placement_policy_version     INTEGER,
    inventory_generation         TEXT,
    status                       TEXT NOT NULL DEFAULT 'running', -- running | complete | failed | interrupted
    files_examined               INTEGER DEFAULT 0,
    files_implicated             INTEGER DEFAULT 0,
    review_families              INTEGER DEFAULT 0,
    estimated_human_decisions    INTEGER DEFAULT 0,
    summary_json                 TEXT,
    report_path                  TEXT,
    evidence_path                TEXT
);

-- Finding: something Mini ARK observed. This is not a proposal, not
-- authorization, and not proof that anything physically happened.
CREATE TABLE IF NOT EXISTS stewardship_findings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_run_id       INTEGER REFERENCES shadow_runs(id),
    finding_type        TEXT NOT NULL,
    subject_type        TEXT,
    path                TEXT,
    classification      TEXT,
    placement_status    TEXT,
    status              TEXT NOT NULL DEFAULT 'open',  -- open | proposed | dismissed | resolved
    reason              TEXT,
    confidence          REAL,
    risk                TEXT,
    evidence_json       TEXT,
    references_json     TEXT,
    dependents_json     TEXT,
    recommended_action  TEXT,
    source_id           INTEGER REFERENCES sources(id),
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at         TEXT
);

-- Stewardship proposal: what Mini ARK recommends. This table is
-- intentionally separate from findings and operations so "thought it
-- should happen" never becomes indistinguishable from "did happen."
CREATE TABLE IF NOT EXISTS stewardship_proposals (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_run_id        INTEGER REFERENCES shadow_runs(id),
    finding_id           INTEGER REFERENCES stewardship_findings(id),
    capability_id        TEXT,
    owner                TEXT,
    domain               TEXT,
    operation            TEXT,
    description          TEXT NOT NULL,
    proposed_action      TEXT NOT NULL,
    subject_count        INTEGER DEFAULT 1,
    confidence           REAL,
    risk                 TEXT,
    approval_required    INTEGER NOT NULL DEFAULT 1,
    preview_available    INTEGER NOT NULL DEFAULT 0,
    undo_available       INTEGER NOT NULL DEFAULT 0,
    status               TEXT NOT NULL DEFAULT 'pending', -- pending | reviewed | approved | rejected | superseded
    review_group_key     TEXT,
    review_cost          INTEGER DEFAULT 1,
    proof                TEXT,
    created_at           TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at          TEXT
);

-- Stewardship operation: what Mini ARK was authorized to attempt. It
-- has a machine state so interrupted/crashed work can be resumed or
-- explained from reality.
CREATE TABLE IF NOT EXISTS stewardship_operations (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id          INTEGER REFERENCES stewardship_proposals(id),
    capability_id        TEXT,
    owner                TEXT,
    domain               TEXT,
    operation            TEXT,
    state                TEXT NOT NULL DEFAULT 'PROPOSED',
    commit_phase         TEXT NOT NULL DEFAULT 'PLANNED',
    batch_key            TEXT,
    batch_index          INTEGER,
    batch_total          INTEGER,
    idempotency_key      TEXT,
    expected_state_json  TEXT,
    actual_state_json    TEXT,
    reason               TEXT,
    confidence           REAL,
    risk                 TEXT,
    approval_proof       TEXT,
    preview_proof        TEXT,
    verification_proof   TEXT,
    undo_proof           TEXT,
    started_at           TEXT,
    completed_at         TEXT,
    updated_at           TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(idempotency_key)
);

-- Stewardship event: what physically happened while an operation ran.
-- Events are append-only operational evidence.
CREATE TABLE IF NOT EXISTS stewardship_operation_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id         INTEGER NOT NULL REFERENCES stewardship_operations(id),
    event_type           TEXT NOT NULL,
    commit_phase         TEXT,
    path                 TEXT,
    previous_state_json  TEXT,
    new_state_json       TEXT,
    status               TEXT NOT NULL DEFAULT 'observed',
    proof                TEXT,
    created_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Hard floor of paths apply() will never move or shortcut-replace,
-- regardless of any proposal, mode request, or permission tier.
-- Table is editable/extendable, but critical Windows system paths are
-- ALSO hardcoded in apply.py itself -- a bad row here can widen the
-- protected set but can never narrow the non-negotiable OS floor.
--
-- Also doubles as the RESERVATION mechanism: a folder you've built
-- as scaffolding (architecture that exists before it's populated) can
-- be marked here with category='user_reserved' so find-empty never
-- flags it -- or anything above it in the tree -- as a dead end, and
-- apply() never moves/shortcuts/quarantines it or anything under it.
CREATE TABLE IF NOT EXISTS protected_paths (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path_prefix TEXT NOT NULL UNIQUE,
    reason      TEXT,
    category    TEXT NOT NULL DEFAULT 'user_reserved',   -- 'user_reserved' | 'system_floor_extension'
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (1, datetime('now'));
