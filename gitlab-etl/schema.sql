-- ─────────────────────────────────────────────────────────────────────────────
-- Schema GitLab Engineering Metrics
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS gitlab_projects (
    id                   BIGINT PRIMARY KEY,
    name                 TEXT NOT NULL,
    path_with_namespace  TEXT,
    namespace            TEXT,
    web_url              TEXT,
    synced_at            TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS gitlab_users (
    id         BIGINT PRIMARY KEY,
    username   TEXT,
    name       TEXT,
    email      TEXT,
    synced_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ─── Merge Requests ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS gitlab_merge_requests (
    id                 BIGINT PRIMARY KEY,
    iid                INTEGER NOT NULL,
    project_id         BIGINT  NOT NULL REFERENCES gitlab_projects(id),
    title              TEXT,
    author_id          BIGINT,
    author_username    TEXT,
    state              TEXT,    -- opened | closed | merged
    draft              BOOLEAN DEFAULT FALSE,
    source_branch      TEXT,
    target_branch      TEXT,
    -- tamanho do MR
    changes_count      INTEGER, -- número de arquivos alterados
    -- reviews
    user_notes_count   INTEGER DEFAULT 0,
    -- datas-chave para métricas de ciclo
    created_at         TIMESTAMP WITH TIME ZONE,
    updated_at         TIMESTAMP WITH TIME ZONE,
    merged_at          TIMESTAMP WITH TIME ZONE,
    closed_at          TIMESTAMP WITH TIME ZONE,
    -- lead time em horas (criação → merge)
    cycle_time_hours   FLOAT GENERATED ALWAYS AS (
        CASE
            WHEN merged_at IS NOT NULL AND created_at IS NOT NULL
            THEN EXTRACT(EPOCH FROM (merged_at - created_at)) / 3600.0
            ELSE NULL
        END
    ) STORED,
    labels             TEXT[],
    web_url            TEXT,
    synced_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mr_project   ON gitlab_merge_requests(project_id);
CREATE INDEX IF NOT EXISTS idx_mr_author    ON gitlab_merge_requests(author_username);
CREATE INDEX IF NOT EXISTS idx_mr_state     ON gitlab_merge_requests(state);
CREATE INDEX IF NOT EXISTS idx_mr_created   ON gitlab_merge_requests(created_at);
CREATE INDEX IF NOT EXISTS idx_mr_merged    ON gitlab_merge_requests(merged_at);

-- Reviewers designados no MR
CREATE TABLE IF NOT EXISTS gitlab_mr_reviewers (
    mr_id     BIGINT NOT NULL REFERENCES gitlab_merge_requests(id) ON DELETE CASCADE,
    user_id   BIGINT NOT NULL,
    username  TEXT,
    PRIMARY KEY (mr_id, user_id)
);

-- Comentários e notas (code review qualitativo)
CREATE TABLE IF NOT EXISTS gitlab_mr_notes (
    id               BIGINT PRIMARY KEY,
    mr_id            BIGINT NOT NULL REFERENCES gitlab_merge_requests(id) ON DELETE CASCADE,
    project_id       BIGINT NOT NULL,
    author_id        BIGINT,
    author_username  TEXT,
    created_at       TIMESTAMP WITH TIME ZONE,
    updated_at       TIMESTAMP WITH TIME ZONE,
    system           BOOLEAN DEFAULT FALSE,  -- notas de sistema (merge, close, etc.)
    resolvable       BOOLEAN DEFAULT FALSE,
    resolved         BOOLEAN DEFAULT FALSE,
    body             TEXT,
    synced_at        TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notes_mr      ON gitlab_mr_notes(mr_id);
CREATE INDEX IF NOT EXISTS idx_notes_author  ON gitlab_mr_notes(author_username);
CREATE INDEX IF NOT EXISTS idx_notes_created ON gitlab_mr_notes(created_at);

-- ─── Commits ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS gitlab_commits (
    sha              TEXT    NOT NULL,
    project_id       BIGINT  NOT NULL,
    author_name      TEXT,
    author_email     TEXT,
    author_username  TEXT,   -- resolvido via e-mail ↔ usuário GitLab
    committed_date   TIMESTAMP WITH TIME ZONE,
    authored_date    TIMESTAMP WITH TIME ZONE,
    title            TEXT,
    additions        INTEGER DEFAULT 0,
    deletions        INTEGER DEFAULT 0,
    web_url          TEXT,
    synced_at        TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (sha, project_id)
);

CREATE INDEX IF NOT EXISTS idx_commits_author   ON gitlab_commits(author_username);
CREATE INDEX IF NOT EXISTS idx_commits_date     ON gitlab_commits(committed_date);
CREATE INDEX IF NOT EXISTS idx_commits_project  ON gitlab_commits(project_id);

-- Vínculo commit ↔ MR (para calcular tamanho real do MR em linhas)
CREATE TABLE IF NOT EXISTS gitlab_mr_commits (
    mr_id       BIGINT NOT NULL REFERENCES gitlab_merge_requests(id) ON DELETE CASCADE,
    commit_sha  TEXT   NOT NULL,
    project_id  BIGINT NOT NULL,
    PRIMARY KEY (mr_id, commit_sha)
);

-- ─── Pipelines ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS gitlab_pipelines (
    id           BIGINT PRIMARY KEY,
    project_id   BIGINT NOT NULL,
    status       TEXT,   -- running | pending | success | failed | canceled | skipped
    ref          TEXT,
    sha          TEXT,
    source       TEXT,   -- push | web | trigger | schedule | merge_request_event ...
    created_at   TIMESTAMP WITH TIME ZONE,
    updated_at   TIMESTAMP WITH TIME ZONE,
    started_at   TIMESTAMP WITH TIME ZONE,
    finished_at  TIMESTAMP WITH TIME ZONE,
    duration     INTEGER GENERATED ALWAYS AS (
        CASE
            WHEN updated_at IS NOT NULL AND created_at IS NOT NULL
                 AND status IN ('success', 'failed', 'canceled', 'skipped')
            THEN EXTRACT(EPOCH FROM (updated_at - created_at))::INTEGER
            ELSE NULL
        END
    ) STORED, -- estimado: updated_at - created_at (endpoint de lista não retorna duration)
    synced_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pipeline_project ON gitlab_pipelines(project_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_status  ON gitlab_pipelines(status);
CREATE INDEX IF NOT EXISTS idx_pipeline_created ON gitlab_pipelines(created_at);

-- ─── Deployments (DORA: deploy frequency) ────────────────────────────────────

CREATE TABLE IF NOT EXISTS gitlab_deployments (
    id              BIGINT PRIMARY KEY,
    iid             INTEGER,
    project_id      BIGINT NOT NULL REFERENCES gitlab_projects(id),
    environment     TEXT,       -- nome do environment (production, staging, ...)
    status          TEXT,       -- created | running | success | failed | canceled | blocked
    ref             TEXT,
    sha             TEXT,
    user_id         BIGINT,
    user_username   TEXT,
    created_at      TIMESTAMP WITH TIME ZONE,
    updated_at      TIMESTAMP WITH TIME ZONE,
    finished_at     TIMESTAMP WITH TIME ZONE, -- deployable.finished_at quando disponível
    synced_at       TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_deploy_project ON gitlab_deployments(project_id);
CREATE INDEX IF NOT EXISTS idx_deploy_status  ON gitlab_deployments(status);
CREATE INDEX IF NOT EXISTS idx_deploy_env     ON gitlab_deployments(environment);
CREATE INDEX IF NOT EXISTS idx_deploy_created ON gitlab_deployments(created_at);
CREATE INDEX IF NOT EXISTS idx_deploy_updated ON gitlab_deployments(updated_at);

-- ─── Estado de sincronização ─────────────────────────────────────────────────

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

-- MR com linhas alteradas (agregado dos commits vinculados)
CREATE OR REPLACE VIEW gitlab_mr_with_stats AS
SELECT
    mr.*,
    p.path_with_namespace                                    AS project_name,
    COALESCE(cs.additions, 0)                               AS total_additions,
    COALESCE(cs.deletions, 0)                               AS total_deletions,
    COALESCE(cs.additions, 0) + COALESCE(cs.deletions, 0)  AS total_lines_changed
FROM gitlab_merge_requests mr
JOIN gitlab_projects p ON mr.project_id = p.id
LEFT JOIN (
    SELECT
        mc.mr_id,
        SUM(c.additions) AS additions,
        SUM(c.deletions) AS deletions
    FROM gitlab_mr_commits mc
    JOIN gitlab_commits c ON mc.commit_sha = c.sha AND mc.project_id = c.project_id
    GROUP BY mc.mr_id
) cs ON mr.id = cs.mr_id;

-- Taxa de retrabalho por autor (proxy: commits com fix/revert/hotfix/bug)
CREATE OR REPLACE VIEW gitlab_rework_rate AS
SELECT
    author_username,
    COUNT(*)                                                         AS total_commits,
    COUNT(*) FILTER (WHERE title ~* '\y(fix|revert|hotfix|bug|patch|correction)\y') AS rework_commits,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE title ~* '\y(fix|revert|hotfix|bug|patch|correction)\y')
        / NULLIF(COUNT(*), 0),
        2
    )                                                                AS rework_rate_pct
FROM gitlab_commits
GROUP BY author_username;

-- Participação em code review (quem comenta em MRs alheios)
CREATE OR REPLACE VIEW gitlab_review_participation AS
SELECT
    n.author_username                   AS reviewer,
    COUNT(DISTINCT n.mr_id)             AS mrs_reviewed,
    COUNT(*) FILTER (WHERE NOT n.system)      AS total_comments,
    ROUND(
        COUNT(*) FILTER (WHERE NOT n.system)::numeric
        / NULLIF(COUNT(DISTINCT n.mr_id), 0),
        1
    )                                   AS avg_comments_per_mr
FROM gitlab_mr_notes n
JOIN gitlab_merge_requests mr ON n.mr_id = mr.id
WHERE n.author_username != mr.author_username  -- exclui comentários do próprio autor
  AND NOT n.system
GROUP BY n.author_username;
