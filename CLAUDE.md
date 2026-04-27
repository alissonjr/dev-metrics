# Engineering Metrics Platform

Plataforma self-hosted de métricas de engenharia que coleta dados do GitLab e Jira e os visualiza em dashboards Grafana. Toda a infraestrutura roda localmente via Docker Compose. Projeto escrito em português (BR).

## Arquitetura

```
GitLab API  -->  gitlab-etl (Python)  -->  PostgreSQL  <--  Grafana
Jira API    -->  jira-etl   (Python)  -->  (mesmo DB)  <--  Grafana
```

Quatro serviços Docker:
- **`metrics-postgres`**: PostgreSQL 16 compartilhado (`gitlab_metrics`)
- **`metrics-gitlab-etl`**: Coleta da GitLab REST API — sync a cada 6h
- **`metrics-jira-etl`**: Coleta da Jira REST API — sync a cada 4h
- **`metrics-grafana`**: Grafana 12.1.0 com dashboards auto-provisionados

## Stack

- Python 3 + `requests` + `psycopg2` + `schedule`
- PostgreSQL 16 Alpine
- Grafana 12.1.0
- Docker Compose v2
- GNU Make como interface principal

## Estrutura de Diretórios

```
gitlab-etl/
  collector.py     # Coleta MRs, commits, notas, pipelines (auth: PRIVATE-TOKEN)
  schema.sql       # Tabelas e views GitLab
  db_logger.py     # Logs estruturados → tabela integration_logs

jira-etl/
  collector.py     # Coleta issues, sprints, transições (auth: Basic Base64)
  schema.sql       # Tabelas e views Jira
  db_logger.py     # Mesmo padrão do GitLab ETL

grafana/
  dashboards/      # JSONs provisionados automaticamente
  provisioning/    # Configs de datasource (PostgreSQL)

db/
  dump.sql         # Dump versionado dos dados coletados
  dump.sh / restore.sh
```

## Tabelas Principais

**GitLab:** `gitlab_projects`, `gitlab_users`, `gitlab_merge_requests` (tem `cycle_time_hours` gerado), `gitlab_mr_notes`, `gitlab_mr_reviewers`, `gitlab_mr_commits`, `gitlab_commits`, `gitlab_pipelines`, `gitlab_deployments`, `sync_state`, `integration_logs`, `integration_sync_runs`

**Views GitLab:** `gitlab_mr_with_stats`, `gitlab_rework_rate`, `gitlab_review_participation`

**Jira:** `jira_boards`, `jira_issues` (colunas: `lead_time_hours`, `cycle_time_hours`, `action_time_hours`, `awaiting_time_hours`), `jira_issue_transitions`, `jira_sprints`, `jira_sprint_issues`

**Views Jira:** `jira_throughput_weekly`, `jira_wip`

## Dashboards Grafana

| Dashboard | UID |
|---|---|
| GitLab Engineering Metrics | `gitlab-eng-metrics` |
| Jira Kanban Metrics | `jira-kanban-metrics` |
| Jira Sprint Dashboard | `jira-sprint-dashboard` |

Métricas: cycle time de MR, participação em code review, rework rate, taxa de sucesso de pipeline, deploy frequency (DORA) por projeto/ambiente, lead/cycle/action/awaiting time Jira, throughput, WIP, burndown de sprint.

## Configuração (.env)

```
GITLAB_URL, GITLAB_TOKEN, GITLAB_GROUP_ID
JIRA_URL, JIRA_EMAIL, JIRA_TOKEN, JIRA_PROJECTS
HISTORY_DAYS=365          # profundidade do sync inicial
SYNC_INTERVAL_HOURS=6     # GitLab
JIRA_SYNC_INTERVAL_HOURS=4
JIRA_ACTIVE_CATEGORIES=indeterminate  # categorias que contam como "action time"
```

## Comandos Makefile

```
make up/down/restart/logs/logs-gitlab/logs-jira
make sync-gitlab/sync-jira   # força sync manual
make dump/restore             # backup/restore do PostgreSQL
make psql/build/status
```
