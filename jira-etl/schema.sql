-- ─────────────────────────────────────────────────────────────────────────────
-- Schema Jira Kanban Metrics
-- Métricas: throughput, lead time, cycle time, action time, awaiting time
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS jira_boards (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    type        TEXT,           -- kanban | scrum
    project_key TEXT,
    self_url    TEXT,
    synced_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ─── Issues / Cards ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS jira_issues (
    issue_key           TEXT PRIMARY KEY,      -- ex: PROJ-123
    issue_id            TEXT UNIQUE,           -- ID numérico interno do Jira
    board_id            INTEGER REFERENCES jira_boards(id),
    project_key         TEXT NOT NULL,
    summary             TEXT,
    issue_type          TEXT,                  -- Story | Bug | Task | Epic | Subtask
    priority            TEXT,
    status              TEXT,                  -- status atual
    status_category     TEXT,                  -- new | indeterminate | done
    assignee            TEXT,
    assignee_email      TEXT,
    reporter            TEXT,
    created_at          TIMESTAMP WITH TIME ZONE,
    updated_at          TIMESTAMP WITH TIME ZONE,
    resolved_at         TIMESTAMP WITH TIME ZONE,
    story_points        FLOAT,
    labels              TEXT[],
    -- Métricas de tempo em horas (calculadas a partir das transições)
    lead_time_hours     FLOAT,    -- criação → resolução
    cycle_time_hours    FLOAT,    -- primeiro status ativo → resolução
    action_time_hours   FLOAT,    -- soma do tempo em status ativos (In Progress, etc.)
    awaiting_time_hours FLOAT,    -- lead_time - action_time
    synced_at           TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ji_project    ON jira_issues(project_key);
CREATE INDEX IF NOT EXISTS idx_ji_assignee   ON jira_issues(assignee);
CREATE INDEX IF NOT EXISTS idx_ji_type       ON jira_issues(issue_type);
CREATE INDEX IF NOT EXISTS idx_ji_status     ON jira_issues(status);
CREATE INDEX IF NOT EXISTS idx_ji_status_cat ON jira_issues(status_category);
CREATE INDEX IF NOT EXISTS idx_ji_board      ON jira_issues(board_id);
CREATE INDEX IF NOT EXISTS idx_ji_created    ON jira_issues(created_at);
CREATE INDEX IF NOT EXISTS idx_ji_resolved   ON jira_issues(resolved_at);
CREATE INDEX IF NOT EXISTS idx_ji_updated    ON jira_issues(updated_at);

-- ─── Histórico de transições de status ──────────────────────────────────────

CREATE TABLE IF NOT EXISTS jira_issue_transitions (
    id              BIGSERIAL PRIMARY KEY,
    issue_key       TEXT NOT NULL REFERENCES jira_issues(issue_key) ON DELETE CASCADE,
    from_status     TEXT,
    to_status       TEXT NOT NULL,
    from_category   TEXT,          -- new | indeterminate | done
    to_category     TEXT NOT NULL,
    transitioned_at TIMESTAMP WITH TIME ZONE NOT NULL,
    author          TEXT,
    synced_at       TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(issue_key, transitioned_at, to_status)
);

CREATE INDEX IF NOT EXISTS idx_jit_issue    ON jira_issue_transitions(issue_key);
CREATE INDEX IF NOT EXISTS idx_jit_at       ON jira_issue_transitions(transitioned_at);
CREATE INDEX IF NOT EXISTS idx_jit_category ON jira_issue_transitions(to_category);

-- ─── Sprints ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS jira_sprints (
    id             INTEGER PRIMARY KEY,
    board_id       INTEGER REFERENCES jira_boards(id),
    name           TEXT NOT NULL,
    state          TEXT,            -- active | closed | future
    goal           TEXT,
    start_date     TIMESTAMP WITH TIME ZONE,
    end_date       TIMESTAMP WITH TIME ZONE,
    complete_date  TIMESTAMP WITH TIME ZONE,
    synced_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_js_board  ON jira_sprints(board_id);
CREATE INDEX IF NOT EXISTS idx_js_state  ON jira_sprints(state);
CREATE INDEX IF NOT EXISTS idx_js_start  ON jira_sprints(start_date);

-- Vínculo issue ↔ sprint (um issue pode passar por várias sprints)
CREATE TABLE IF NOT EXISTS jira_sprint_issues (
    sprint_id  INTEGER NOT NULL REFERENCES jira_sprints(id)  ON DELETE CASCADE,
    issue_key  TEXT    NOT NULL REFERENCES jira_issues(issue_key) ON DELETE CASCADE,
    active     BOOLEAN NOT NULL DEFAULT TRUE,   -- FALSE = issue saiu da sprint (transbordo)
    added_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    removed_at TIMESTAMP WITH TIME ZONE,        -- quando saiu da sprint
    PRIMARY KEY (sprint_id, issue_key)
);

CREATE INDEX IF NOT EXISTS idx_jsi_sprint ON jira_sprint_issues(sprint_id);
CREATE INDEX IF NOT EXISTS idx_jsi_issue  ON jira_sprint_issues(issue_key);

-- Migração: adiciona colunas se tabela já existir sem elas
ALTER TABLE jira_sprint_issues ADD COLUMN IF NOT EXISTS active     BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE jira_sprint_issues ADD COLUMN IF NOT EXISTS added_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW();
ALTER TABLE jira_sprint_issues ADD COLUMN IF NOT EXISTS removed_at TIMESTAMP WITH TIME ZONE;

CREATE INDEX IF NOT EXISTS idx_jsi_active ON jira_sprint_issues(sprint_id, active);

-- Colunas de sprint em jira_issues (sprint atual/última do card)
ALTER TABLE jira_issues ADD COLUMN IF NOT EXISTS sprint_id   INTEGER REFERENCES jira_sprints(id);
ALTER TABLE jira_issues ADD COLUMN IF NOT EXISTS sprint_name TEXT;

-- Relação parent (subtasks apontam para o card pai)
ALTER TABLE jira_issues ADD COLUMN IF NOT EXISTS parent_key  TEXT;

-- ─── Estado de sincronização ─────────────────────────────────────────────────
-- (reutiliza sync_state já existente para GitLab; chave: "jira_last_sync")

CREATE TABLE IF NOT EXISTS sync_state (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ─── Logs de integração (compartilhado Jira + GitLab) ────────────────────────

CREATE TABLE IF NOT EXISTS integration_logs (
    id          BIGSERIAL PRIMARY KEY,
    source      TEXT NOT NULL,                                  -- gitlab | jira
    level       TEXT NOT NULL,                                  -- info | warning | error
    event_type  TEXT NOT NULL,                                  -- sync_start | rate_limit | etc.
    message     TEXT NOT NULL,
    project     TEXT,
    rows_synced INTEGER,
    details     JSONB,
    run_id      BIGINT,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_il_source    ON integration_logs(source);
CREATE INDEX IF NOT EXISTS idx_il_level     ON integration_logs(level);
CREATE INDEX IF NOT EXISTS idx_il_event     ON integration_logs(event_type);
CREATE INDEX IF NOT EXISTS idx_il_project   ON integration_logs(project);
CREATE INDEX IF NOT EXISTS idx_il_created   ON integration_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_il_run       ON integration_logs(run_id);

CREATE TABLE IF NOT EXISTS integration_sync_runs (
    id           BIGSERIAL PRIMARY KEY,
    source       TEXT NOT NULL,
    started_at   TIMESTAMP WITH TIME ZONE NOT NULL,
    finished_at  TIMESTAMP WITH TIME ZONE,
    status       TEXT,                                          -- running | success | partial | failed
    rows_synced  INTEGER DEFAULT 0,
    errors_count INTEGER DEFAULT 0,
    since_cursor TEXT,
    details      JSONB,
    created_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_isr_source  ON integration_sync_runs(source);
CREATE INDEX IF NOT EXISTS idx_isr_status  ON integration_sync_runs(status);
CREATE INDEX IF NOT EXISTS idx_isr_started ON integration_sync_runs(started_at);

-- ─── Views analíticas ────────────────────────────────────────────────────────

-- Throughput semanal por projeto/tipo/assignee
CREATE OR REPLACE VIEW jira_throughput_weekly AS
SELECT
    date_trunc('week', resolved_at)                      AS week,
    project_key,
    issue_type,
    assignee,
    COUNT(*)                                             AS cards_done,
    COALESCE(SUM(story_points), 0)                       AS story_points_done,
    ROUND(AVG(lead_time_hours)::numeric,    1)           AS avg_lead_time_h,
    ROUND(AVG(cycle_time_hours)::numeric,   1)           AS avg_cycle_time_h,
    ROUND(AVG(action_time_hours)::numeric,  1)           AS avg_action_time_h,
    ROUND(AVG(awaiting_time_hours)::numeric,1)           AS avg_awaiting_time_h
FROM jira_issues
WHERE resolved_at IS NOT NULL
GROUP BY 1, 2, 3, 4;

-- WIP ativo por status e projeto (apenas trabalho em andamento)
CREATE OR REPLACE VIEW jira_wip AS
SELECT
    project_key,
    status,
    status_category,
    assignee,
    issue_type,
    COUNT(*)  AS cards_in_progress
FROM jira_issues
WHERE status_category = 'indeterminate'
GROUP BY 1, 2, 3, 4, 5;
