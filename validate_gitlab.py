#!/usr/bin/env python3
"""
Script de Validação GitLab — compara contagens da API com o banco de dados.

Uso:
    GITLAB_URL=https://seu-gitlab.com \
    GITLAB_TOKEN=seu-token \
    GITLAB_GROUP_ID=123 \
    DATABASE_URL=postgresql://metrics:metrics@localhost:5432/gitlab_metrics \
    DAYS_BACK=90 \
    python3 validate_gitlab.py

Saída:
    - Tabela no terminal com totais por projeto (API vs banco)
    - Arquivo gitlab_validation_report.json com todos os dados
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, Generator, List, Optional

import time

import psycopg2
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ── Configuração ──────────────────────────────────────────────────────────────

GITLAB_URL   = os.environ.get("GITLAB_URL", "").rstrip("/")
GITLAB_TOKEN = os.environ.get("GITLAB_TOKEN", "")
GROUP_ID     = os.environ.get("GITLAB_GROUP_ID", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
DAYS_BACK    = int(os.environ.get("DAYS_BACK", "90"))
PER_PAGE     = 100

HEADERS = {"PRIVATE-TOKEN": GITLAB_TOKEN}

# Session com retry automático (backoff em erros de rede/timeout)
_session = requests.Session()
_retry = Retry(total=5, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
_session.mount("https://", HTTPAdapter(max_retries=_retry))
_session.mount("http://",  HTTPAdapter(max_retries=_retry))


# ── HTTP ──────────────────────────────────────────────────────────────────────

def paginate(url: str, params: dict = {}) -> Generator[dict, None, None]:
    """Percorre todas as páginas de um endpoint GitLab com paginação."""
    page = 1
    while True:
        resp = _session.get(
            url,
            headers=HEADERS,
            params={**params, "per_page": PER_PAGE, "page": page},
            timeout=90,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data:
            break
        yield from data
        total_pages = int(resp.headers.get("X-Total-Pages", 1))
        if page >= total_pages:
            break
        page += 1


# ── Coleta ────────────────────────────────────────────────────────────────────

def get_projects(group_id: str) -> List[dict]:
    url = f"{GITLAB_URL}/api/v4/groups/{group_id}/projects"
    return list(paginate(url, {"include_subgroups": "true", "archived": "false"}))


def get_mrs(project_id: int, since: str) -> List[dict]:
    url = f"{GITLAB_URL}/api/v4/projects/{project_id}/merge_requests"
    return list(paginate(url, {"state": "all", "created_after": since, "scope": "all"}))


def get_commits(project_id: int, since: str) -> List[dict]:
    url = f"{GITLAB_URL}/api/v4/projects/{project_id}/repository/commits"
    return list(paginate(url, {"since": since, "all": "true", "with_stats": "true"}))


def get_pipelines(project_id: int, since: str) -> List[dict]:
    url = f"{GITLAB_URL}/api/v4/projects/{project_id}/pipelines"
    return list(paginate(url, {"updated_after": since}))


# ── Banco de dados ────────────────────────────────────────────────────────────

def query_db_counts(since: str) -> Dict[int, dict]:
    """
    Retorna contagens por project_id direto do banco.
    Retorna {} se DATABASE_URL não estiver configurada ou a conexão falhar.
    """
    if not DATABASE_URL:
        return {}
    try:
        conn = psycopg2.connect(DATABASE_URL)
        since_ts = since  # já é ISO
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    project_id,
                    COUNT(*)                                              AS total_mrs,
                    COUNT(*) FILTER (WHERE state = 'merged')             AS merged_mrs,
                    COUNT(*) FILTER (WHERE state = 'opened')             AS open_mrs
                FROM merge_requests
                WHERE created_at >= %s
                GROUP BY project_id
            """, (since_ts,))
            mr_rows = {r[0]: {"db_mrs": r[1], "db_merged": r[2], "db_open": r[3]}
                       for r in cur.fetchall()}

            cur.execute("""
                SELECT project_id, COUNT(*) AS total_commits
                FROM commits
                WHERE committed_date >= %s
                GROUP BY project_id
            """, (since_ts,))
            commit_rows = {r[0]: r[1] for r in cur.fetchall()}

            cur.execute("""
                SELECT project_id, COUNT(*) AS total_pipelines
                FROM pipelines
                WHERE created_at >= %s
                GROUP BY project_id
            """, (since_ts,))
            pipeline_rows = {r[0]: r[1] for r in cur.fetchall()}

        conn.close()
        result: Dict[int, dict] = {}
        for pid in set(list(mr_rows) + list(commit_rows) + list(pipeline_rows)):
            result[pid] = {
                **mr_rows.get(pid, {"db_mrs": 0, "db_merged": 0, "db_open": 0}),
                "db_commits":   commit_rows.get(pid, 0),
                "db_pipelines": pipeline_rows.get(pid, 0),
            }
        return result
    except Exception as e:
        print(f"  [AVISO] Não foi possível consultar o banco: {e}")
        return {}


# ── Relatório ─────────────────────────────────────────────────────────────────

def _diff(api_val: int, db_val: int) -> str:
    """Retorna string colorida com a diferença API - DB."""
    if db_val == 0 and api_val == 0:
        return "  ok"
    delta = api_val - db_val
    if delta == 0:
        return "  ok"
    sign = "+" if delta > 0 else ""
    return f"{sign}{delta:,}"


def run_report(projects: List[dict], since: str) -> None:
    since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
    sep  = "=" * 90
    line = "─" * 90

    print(f"\n{sep}")
    print(f"  RELATÓRIO DE VALIDAÇÃO — GitLab API vs Banco de Dados")
    print(f"  Período : últimos {DAYS_BACK} dias  (desde {since_dt.date()})")
    print(f"  Grupo   : {GROUP_ID}  |  Projetos: {len(projects)}")
    has_db = bool(DATABASE_URL)
    print(f"  Banco   : {'conectado' if has_db else 'não configurado (DATABASE_URL ausente)'}")
    print(f"{sep}\n")

    print("Consultando banco de dados ..." if has_db else "Pulando consulta ao banco (sem DATABASE_URL).")
    db_counts = query_db_counts(since)

    totals: Dict[str, int] = {"mrs": 0, "merged": 0, "commits": 0, "pipelines": 0,
                               "additions": 0, "deletions": 0}
    author_mrs: Dict[str, int] = {}
    author_commits: Dict[str, int] = {}
    author_lines: Dict[str, int] = {}
    project_rows = []

    for proj in projects:
        pid  = proj["id"]
        name = proj["path_with_namespace"]
        print(f"  ▸ {name} (id={pid})")

        try:
            print("      Coletando MRs ...", end="\r")
            mrs      = get_mrs(pid, since)
            merged   = [m for m in mrs if m["state"] == "merged"]
            open_mrs = [m for m in mrs if m["state"] == "opened"]
            closed   = [m for m in mrs if m["state"] == "closed"]

            for mr in mrs:
                u = mr.get("author") or {}
                a = u.get("username", "unknown")
                author_mrs[a] = author_mrs.get(a, 0) + 1

            print("      Coletando commits ...", end="\r")
            commits = get_commits(pid, since)
            p_add = p_del = 0
            for c in commits:
                a = c.get("author_name", "unknown")
                author_commits[a] = author_commits.get(a, 0) + 1
                stats = c.get("stats") or {}
                add = stats.get("additions", 0) or 0
                dlt = stats.get("deletions", 0) or 0
                p_add += add
                p_del += dlt
                author_lines[a] = author_lines.get(a, 0) + add + dlt

            print("      Coletando pipelines ...", end="\r")
            pipelines = get_pipelines(pid, since)

            db = db_counts.get(pid, {})
            project_rows.append({
                "project":       name,
                "project_id":    pid,
                "mrs":           len(mrs),
                "merged":        len(merged),
                "open":          len(open_mrs),
                "closed":        len(closed),
                "commits":       len(commits),
                "additions":     p_add,
                "deletions":     p_del,
                "pipelines":     len(pipelines),
                "db_mrs":        db.get("db_mrs", "—"),
                "db_merged":     db.get("db_merged", "—"),
                "db_commits":    db.get("db_commits", "—"),
                "db_pipelines":  db.get("db_pipelines", "—"),
            })

            totals["mrs"]       += len(mrs)
            totals["merged"]    += len(merged)
            totals["commits"]   += len(commits)
            totals["pipelines"] += len(pipelines)
            totals["additions"] += p_add
            totals["deletions"] += p_del

            print(f"      MRs: {len(mrs):>4}  (merged={len(merged)}, open={len(open_mrs)})  "
                  f"Commits: {len(commits):>5}  Pipelines: {len(pipelines):>4}     ")

        except Exception as e:
            print(f"      [ERRO] {e} — projeto ignorado, continuando...")
            project_rows.append({"project": name, "project_id": pid,
                                  "mrs": "ERRO", "merged": "-", "open": "-",
                                  "closed": "-", "commits": "-",
                                  "additions": "-", "deletions": "-",
                                  "pipelines": "-",
                                  "db_mrs": "-", "db_merged": "-",
                                  "db_commits": "-", "db_pipelines": "-"})

    # ── Totais por projeto ────────────────────────────────────────────────────
    print(f"\n{line}")
    if has_db:
        print(f"  {'Projeto':<42} {'MRs(API)':>8} {'MRs(DB)':>8} {'Δ':>5} {'Commits(API)':>12} {'Commits(DB)':>11} {'Δ':>5}")
        print(f"  {'-'*42} {'--------':>8} {'-------':>8} {'-----':>5} {'------------':>12} {'-----------':>11} {'-----':>5}")
        for r in project_rows:
            if isinstance(r["mrs"], int):
                d_mr  = _diff(r["mrs"],     r["db_mrs"]     if isinstance(r["db_mrs"],    int) else 0)
                d_c   = _diff(r["commits"], r["db_commits"] if isinstance(r["db_commits"], int) else 0)
                print(f"  {r['project']:<42} {r['mrs']:>8} {r['db_mrs']:>8} {d_mr:>5} "
                      f"{r['commits']:>12} {r['db_commits']:>11} {d_c:>5}")
            else:
                print(f"  {r['project']:<42} {'ERRO':>8}")
    else:
        print(f"  {'Projeto':<50} {'MRs':>5} {'Merged':>7} {'Commits':>8} {'Pipelines':>10}")
        print(f"  {'-'*50} {'-----':>5} {'-------':>7} {'--------':>8} {'----------':>10}")
        for r in project_rows:
            print(f"  {r['project']:<50} {r['mrs']:>5} {r['merged']:>7} {r['commits']:>8} {r['pipelines']:>10}")

    # ── Totais gerais ─────────────────────────────────────────────────────────
    print(f"\n{line}")
    print(f"  TOTAIS CONSOLIDADOS (API)")
    print(f"{line}")
    print(f"  MRs criados no período :  {totals['mrs']:>6,}")
    print(f"  MRs mergeados          :  {totals['merged']:>6,}")
    print(f"  Commits                :  {totals['commits']:>6,}")
    print(f"  Linhas adicionadas     :  {totals['additions']:>6,}")
    print(f"  Linhas removidas       :  {totals['deletions']:>6,}")
    print(f"  Pipelines              :  {totals['pipelines']:>6,}")

    # ── Por autor ─────────────────────────────────────────────────────────────
    print(f"\n{line}")
    print(f"  MRs POR AUTOR (top 30)")
    print(f"{line}")
    print(f"  {'Autor':<40} {'MRs':>6}")
    for author, count in sorted(author_mrs.items(), key=lambda x: -x[1])[:30]:
        print(f"  {author:<40} {count:>6}")

    print(f"\n{line}")
    print(f"  COMMITS POR AUTOR — com linhas modificadas (top 30)")
    print(f"{line}")
    print(f"  {'Autor':<40} {'Commits':>8} {'Linhas':>8}")
    for author, count in sorted(author_commits.items(), key=lambda x: -x[1])[:30]:
        lines = author_lines.get(author, 0)
        print(f"  {author:<40} {count:>8} {lines:>8}")

    print(f"\n{sep}\n")

    # ── Salva JSON ────────────────────────────────────────────────────────────
    output = {
        "generated_at":    datetime.now(timezone.utc).isoformat(),
        "period_days":     DAYS_BACK,
        "since":           since,
        "group_id":        GROUP_ID,
        "db_available":    has_db,
        "totals":          totals,
        "projects":        project_rows,
        "mrs_by_author":   dict(sorted(author_mrs.items(),    key=lambda x: -x[1])),
        "commits_by_author": dict(sorted(author_commits.items(), key=lambda x: -x[1])),
        "lines_by_author": dict(sorted(author_lines.items(),  key=lambda x: -x[1])),
    }
    output_file = "gitlab_validation_report.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"  Relatório JSON salvo em: {output_file}\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    errors = []
    if not GITLAB_URL:
        errors.append("GITLAB_URL não definida")
    if not GITLAB_TOKEN:
        errors.append("GITLAB_TOKEN não definida")
    if not GROUP_ID:
        errors.append("GITLAB_GROUP_ID não definida")
    if errors:
        for e in errors:
            print(f"ERRO: {e}")
        print("\nExemplo:")
        print("  GITLAB_URL=https://gitlab.empresa.com \\")
        print("  GITLAB_TOKEN=glpat-xxxx \\")
        print("  GITLAB_GROUP_ID=42 \\")
        print("  DAYS_BACK=90 \\")
        print("  python3 validate_gitlab.py")
        sys.exit(1)

    since = (datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%dT00:00:00Z")

    print(f"Conectando a {GITLAB_URL} ...")
    print(f"Buscando projetos do grupo {GROUP_ID} ...")
    projects = get_projects(GROUP_ID)
    print(f"Encontrados {len(projects)} projeto(s).\n")

    run_report(projects, since)


if __name__ == "__main__":
    main()
