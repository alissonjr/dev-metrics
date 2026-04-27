#!/usr/bin/env python3
"""
GitLab Metrics Collector
Coleta dados do GitLab API e armazena em PostgreSQL para Grafana.

Variáveis de ambiente obrigatórias:
    GITLAB_URL          URL base do GitLab  (ex: https://gitlab.empresa.com)
    GITLAB_TOKEN        Personal/Group Access Token com escopo api
    GITLAB_GROUP_ID     ID numérico do grupo raiz
    DATABASE_URL        URL de conexão PostgreSQL

Variáveis opcionais:
    SYNC_INTERVAL_HOURS  Intervalo entre sincronizações completas (padrão: 6)
    HISTORY_DAYS         Quantos dias de histórico na primeira carga (padrão: 365)
    LOG_LEVEL            DEBUG | INFO | WARNING (padrão: INFO)
"""

import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Generator, List, Optional

import psycopg2
import psycopg2.extras
import requests
import schedule
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from db_logger import DbLogger

# ── Configuração ──────────────────────────────────────────────────────────────

GITLAB_URL      = os.environ.get("GITLAB_URL", "").rstrip("/")
GITLAB_TOKEN    = os.environ.get("GITLAB_TOKEN", "")
GROUP_ID        = os.environ.get("GITLAB_GROUP_ID", "")
DATABASE_URL    = os.environ.get("DATABASE_URL", "")
SYNC_INTERVAL   = int(os.environ.get("SYNC_INTERVAL_HOURS", "1"))
HISTORY_DAYS    = int(os.environ.get("HISTORY_DAYS", "365"))
LOG_LEVEL       = os.environ.get("LOG_LEVEL", "INFO").upper()
PER_PAGE        = 100

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("collector")

HEADERS = {"PRIVATE-TOKEN": GITLAB_TOKEN}

_db_logger: Optional[DbLogger] = None


_NOTE_LIMIT = 4000

def _truncate_note(body: str) -> str:
    if len(body) > _NOTE_LIMIT:
        if _db_logger:
            _db_logger.warning("data_truncation",
                               f"MR note truncada de {len(body)} para {_NOTE_LIMIT} chars")
        return body[:_NOTE_LIMIT]
    return body


def _parse_int(value) -> int | None:
    """Converte valor para int. Aceita int, '5', '5+' (GitLab trunca com +)."""
    if value is None:
        return None
    try:
        return int(str(value).rstrip("+"))
    except (ValueError, TypeError):
        return None


# Session com retry automático para erros de rede e DNS
_session = requests.Session()
_retry = Retry(
    total=5,
    backoff_factor=2,           # esperas: 2s, 4s, 8s, 16s, 32s
    status_forcelist=[500, 502, 503, 504],
    allowed_methods=["GET"],
    raise_on_status=False,
)
_session.mount("https://", HTTPAdapter(max_retries=_retry))
_session.mount("http://",  HTTPAdapter(max_retries=_retry))


# ── Helpers HTTP ──────────────────────────────────────────────────────────────

def _get(url: str, params: dict) -> requests.Response:
    """GET com tratamento de rate limit (429) e retry de DNS."""
    while True:
        try:
            resp = _session.get(url, headers=HEADERS, params=params, timeout=90)
        except requests.exceptions.ConnectionError as e:
            log.warning("Erro de conexão (%s) — aguardando 10s e tentando novamente.", e)
            time.sleep(10)
            continue

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 60))
            reset_time  = resp.headers.get("RateLimit-ResetTime", "")
            log.warning("Rate limit atingido (429) — aguardando %ds. Reset: %s", retry_after, reset_time)
            if _db_logger:
                _db_logger.warning("rate_limit", f"GitLab 429 — aguardando {retry_after}s",
                                   details={"reset_time": reset_time})
            time.sleep(retry_after + 1)
            continue

        return resp


def paginate(url: str, params: dict = {}, label: str = "") -> Generator[dict, None, None]:
    """Percorre todas as páginas de um endpoint GitLab respeitando rate limits."""
    page = 1
    while True:
        resp = _get(url, {**params, "per_page": PER_PAGE, "page": page})

        if resp.status_code == 404:
            log.debug("404 em %s — ignorando.", url)
            return
        resp.raise_for_status()

        data = resp.json()
        if not data:
            break
        yield from data

        total_pages = int(resp.headers.get("X-Total-Pages", 1))
        if label and total_pages > 1:
            log.debug("  %s — página %d/%d", label, page, total_pages)
        if page >= total_pages:
            break
        page += 1

        # Desacelera proativamente quando restam poucas requisições na janela
        remaining = int(resp.headers.get("RateLimit-Remaining", 2000))
        limit     = int(resp.headers.get("RateLimit-Limit", 2000))
        if remaining < limit * 0.1:   # abaixo de 10% do limite
            reset_in = max(0, int(resp.headers.get("RateLimit-Reset", 0)) - int(time.time()))
            wait     = min(reset_in + 1, 30)
            log.warning("Rate limit baixo (%d/%d restantes) — aguardando %ds.", remaining, limit, wait)
            time.sleep(wait)


# ── Banco de dados ────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(DATABASE_URL)


def init_db(conn) -> None:
    """Cria as tabelas se não existirem."""
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path) as f:
        sql = f.read()
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    log.info("Schema inicializado.")


def get_sync_since(conn, key: str) -> str:
    """Retorna a data do último sync. Na primeira vez usa HISTORY_DAYS."""
    with conn.cursor() as cur:
        cur.execute("SELECT value FROM sync_state WHERE key = %s", (key,))
        row = cur.fetchone()
    if row:
        return row[0]
    default = (datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%dT00:00:00Z")
    return default


def set_sync_since(conn, key: str, value: str) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO sync_state(key, value, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
        """, (key, value))
    conn.commit()


# ── Upserts ───────────────────────────────────────────────────────────────────

def upsert_project(conn, p: dict) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO gitlab_projects(id, name, path_with_namespace, namespace, web_url, synced_at)
            VALUES (%(id)s, %(name)s, %(path_with_namespace)s, %(namespace)s, %(web_url)s, NOW())
            ON CONFLICT (id) DO UPDATE SET
                name                = EXCLUDED.name,
                path_with_namespace = EXCLUDED.path_with_namespace,
                namespace           = EXCLUDED.namespace,
                web_url             = EXCLUDED.web_url,
                synced_at           = NOW()
        """, {
            "id":                   p["id"],
            "name":                 p.get("name", ""),
            "path_with_namespace":  p.get("path_with_namespace", ""),
            "namespace":            (p.get("namespace") or {}).get("name", ""),
            "web_url":              p.get("web_url", ""),
        })


def upsert_mr(conn, mr: dict) -> None:
    author = mr.get("author") or {}
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO gitlab_merge_requests(
                id, iid, project_id, title, author_id, author_username,
                state, draft, source_branch, target_branch,
                changes_count, user_notes_count,
                created_at, updated_at, merged_at, closed_at,
                labels, web_url, synced_at
            ) VALUES (
                %(id)s, %(iid)s, %(project_id)s, %(title)s, %(author_id)s, %(author_username)s,
                %(state)s, %(draft)s, %(source_branch)s, %(target_branch)s,
                %(changes_count)s, %(user_notes_count)s,
                %(created_at)s, %(updated_at)s, %(merged_at)s, %(closed_at)s,
                %(labels)s, %(web_url)s, NOW()
            )
            ON CONFLICT (id) DO UPDATE SET
                state             = EXCLUDED.state,
                draft             = EXCLUDED.draft,
                changes_count     = EXCLUDED.changes_count,
                user_notes_count  = EXCLUDED.user_notes_count,
                updated_at        = EXCLUDED.updated_at,
                merged_at         = EXCLUDED.merged_at,
                closed_at         = EXCLUDED.closed_at,
                labels            = EXCLUDED.labels,
                synced_at         = NOW()
        """, {
            "id":               mr["id"],
            "iid":              mr["iid"],
            "project_id":       mr["project_id"],
            "title":            mr.get("title", ""),
            "author_id":        author.get("id"),
            "author_username":  author.get("username", "unknown"),
            "state":            mr.get("state", ""),
            "draft":            mr.get("draft", False) or mr.get("work_in_progress", False),
            "source_branch":    mr.get("source_branch", ""),
            "target_branch":    mr.get("target_branch", ""),
            "changes_count":    _parse_int(mr.get("changes_count")),
            "user_notes_count": mr.get("user_notes_count", 0),
            "created_at":       mr.get("created_at"),
            "updated_at":       mr.get("updated_at"),
            "merged_at":        mr.get("merged_at"),
            "closed_at":        mr.get("closed_at"),
            "labels":           mr.get("labels", []),
            "web_url":          mr.get("web_url", ""),
        })


def upsert_mr_reviewers(conn, mr_id: int, reviewers: List[dict]) -> None:
    if not reviewers:
        return
    with conn.cursor() as cur:
        for r in reviewers:
            cur.execute("""
                INSERT INTO gitlab_mr_reviewers(mr_id, user_id, username)
                VALUES (%s, %s, %s)
                ON CONFLICT (mr_id, user_id) DO NOTHING
            """, (mr_id, r.get("id"), r.get("username")))


def upsert_mr_notes(conn, notes: List[dict], mr_id: int, project_id: int) -> None:
    with conn.cursor() as cur:
        for n in notes:
            author = n.get("author") or {}
            cur.execute("""
                INSERT INTO gitlab_mr_notes(
                    id, mr_id, project_id, author_id, author_username,
                    created_at, updated_at, system, resolvable, resolved,
                    body, synced_at
                ) VALUES (
                    %(id)s, %(mr_id)s, %(project_id)s, %(author_id)s, %(author_username)s,
                    %(created_at)s, %(updated_at)s, %(system)s, %(resolvable)s, %(resolved)s,
                    %(body)s, NOW()
                )
                ON CONFLICT (id) DO UPDATE SET
                    resolved   = EXCLUDED.resolved,
                    updated_at = EXCLUDED.updated_at,
                    synced_at  = NOW()
            """, {
                "id":               n["id"],
                "mr_id":            mr_id,
                "project_id":       project_id,
                "author_id":        author.get("id"),
                "author_username":  author.get("username", "unknown"),
                "created_at":       n.get("created_at"),
                "updated_at":       n.get("updated_at"),
                "system":           n.get("system", False),
                "resolvable":       n.get("resolvable", False),
                "resolved":         n.get("resolved", False),
                "body":             _truncate_note(n.get("body") or ""),
            })


def upsert_commit(conn, c: dict, project_id: int, email_map: dict, name_map: dict) -> None:
    stats    = c.get("stats") or {}
    email    = (c.get("author_email") or "").lower()
    username = email_map.get(email) or name_map.get((c.get("author_name") or "").lower())
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO gitlab_commits(
                sha, project_id, author_name, author_email, author_username,
                committed_date, authored_date, title,
                additions, deletions, web_url, synced_at
            ) VALUES (
                %(sha)s, %(project_id)s, %(author_name)s, %(author_email)s, %(author_username)s,
                %(committed_date)s, %(authored_date)s, %(title)s,
                %(additions)s, %(deletions)s, %(web_url)s, NOW()
            )
            ON CONFLICT (sha, project_id) DO NOTHING
        """, {
            "sha":             c["id"],
            "project_id":      project_id,
            "author_name":     c.get("author_name", ""),
            "author_email":    (c.get("author_email") or "").lower(),
            "author_username": username,
            "committed_date":  c.get("committed_date"),
            "authored_date":   c.get("authored_date"),
            "title":           (c.get("title") or c.get("message", ""))[:500],
            "additions":       stats.get("additions", 0) or 0,
            "deletions":       stats.get("deletions", 0) or 0,
            "web_url":         c.get("web_url", ""),
        })


def upsert_mr_commits(conn, mr_id: int, project_id: int, commit_shas: List[str]) -> None:
    with conn.cursor() as cur:
        for sha in commit_shas:
            cur.execute("""
                INSERT INTO gitlab_mr_commits(mr_id, commit_sha, project_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (mr_id, commit_sha) DO NOTHING
            """, (mr_id, sha, project_id))


def upsert_deployment(conn, dep: dict, project_id: int) -> None:
    user       = dep.get("user") or {}
    env        = dep.get("environment") or {}
    deployable = dep.get("deployable") or {}
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO gitlab_deployments(
                id, iid, project_id, environment, status, ref, sha,
                user_id, user_username,
                created_at, updated_at, finished_at, synced_at
            ) VALUES (
                %(id)s, %(iid)s, %(project_id)s, %(environment)s, %(status)s, %(ref)s, %(sha)s,
                %(user_id)s, %(user_username)s,
                %(created_at)s, %(updated_at)s, %(finished_at)s, NOW()
            )
            ON CONFLICT (id) DO UPDATE SET
                status      = EXCLUDED.status,
                updated_at  = EXCLUDED.updated_at,
                finished_at = EXCLUDED.finished_at,
                synced_at   = NOW()
        """, {
            "id":             dep["id"],
            "iid":            dep.get("iid"),
            "project_id":     project_id,
            "environment":    env.get("name"),
            "status":         dep.get("status", ""),
            "ref":            dep.get("ref", ""),
            "sha":            dep.get("sha", ""),
            "user_id":        user.get("id"),
            "user_username":  user.get("username"),
            "created_at":     dep.get("created_at"),
            "updated_at":     dep.get("updated_at"),
            "finished_at":    deployable.get("finished_at"),
        })


def upsert_pipeline(conn, pl: dict, project_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO gitlab_pipelines(
                id, project_id, status, ref, sha, source,
                created_at, updated_at, synced_at
            ) VALUES (
                %(id)s, %(project_id)s, %(status)s, %(ref)s, %(sha)s, %(source)s,
                %(created_at)s, %(updated_at)s, NOW()
            )
            ON CONFLICT (id) DO UPDATE SET
                status      = EXCLUDED.status,
                updated_at  = EXCLUDED.updated_at,
                synced_at   = NOW()
        """, {
            "id":          pl["id"],
            "project_id":  project_id,
            "status":      pl.get("status", ""),
            "ref":         pl.get("ref", ""),
            "sha":         pl.get("sha", ""),
            "source":      pl.get("source", ""),
            "created_at":  pl.get("created_at"),
            "updated_at":  pl.get("updated_at"),
        })


# ── Coleta por entidade ───────────────────────────────────────────────────────

def build_email_map(conn, group_id: str) -> tuple[dict, dict]:
    """
    Mapeia email → username e nome → username para resolver autores de commits.
    O mapa de email requer token com acesso a dados de usuário (admin ou owner).
    O mapa de nome é sempre construído e usado como fallback.
    Retorna (email_map, name_map).
    """
    email_map = {}
    name_map  = {}
    try:
        url = f"{GITLAB_URL}/api/v4/groups/{group_id}/members/all"
        for member in paginate(url, {}, "membros do grupo"):
            uid      = member.get("id")
            username = member.get("username", "")
            try:
                user_resp = requests.get(
                    f"{GITLAB_URL}/api/v4/users/{uid}",
                    headers=HEADERS, timeout=10
                )
                if user_resp.ok:
                    u     = user_resp.json()
                    email = (u.get("email") or u.get("public_email") or "").lower()
                    name  = u.get("name", "")
                    if email:
                        email_map[email] = username
                    if name:
                        name_map[name.lower()] = username
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO gitlab_users(id, username, name, email, synced_at)
                            VALUES (%s, %s, %s, %s, NOW())
                            ON CONFLICT (id) DO UPDATE SET
                                username  = EXCLUDED.username,
                                name      = EXCLUDED.name,
                                email     = EXCLUDED.email,
                                synced_at = NOW()
                        """, (uid, username, name, email))
            except Exception:
                pass
        conn.commit()
    except Exception as e:
        log.warning("Não foi possível buscar membros via API: %s", e)

    # Complementa name_map com os registros já gravados em gitlab_users
    with conn.cursor() as cur:
        cur.execute("SELECT username, name FROM gitlab_users WHERE name IS NOT NULL AND name != ''")
        for row in cur.fetchall():
            name_map.setdefault(row[1].lower(), row[0])

    log.info("  Mapas de resolução: %d e-mails, %d nomes.", len(email_map), len(name_map))
    return email_map, name_map


def backfill_commit_usernames(conn, email_map: dict, name_map: dict) -> None:
    """Resolve author_username nos commits já gravados que ainda estão NULL."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT sha, project_id, author_email, author_name
            FROM gitlab_commits
            WHERE author_username IS NULL
        """)
        rows = cur.fetchall()

    if not rows:
        return

    updated = 0
    with conn.cursor() as cur:
        for sha, project_id, author_email, author_name in rows:
            username = (
                email_map.get((author_email or "").lower())
                or name_map.get((author_name or "").lower())
            )
            if username:
                cur.execute("""
                    UPDATE gitlab_commits SET author_username = %s
                    WHERE sha = %s AND project_id = %s
                """, (username, sha, project_id))
                updated += 1
    conn.commit()
    log.info("  Backfill commits: %d/%d resolvidos.", updated, len(rows))


def collect_project_data(conn, project: dict, since: str, dep_since: str,
                         email_map: dict, name_map: dict) -> None:
    pid  = project["id"]
    name = project["path_with_namespace"]
    log.info("  Coletando: %s", name)

    upsert_project(conn, project)
    conn.commit()

    # ── MRs ──────────────────────────────────────────────────────────────────
    mr_url = f"{GITLAB_URL}/api/v4/projects/{pid}/merge_requests"
    mr_params = {"state": "all", "updated_after": since, "scope": "all"}
    mr_count = 0
    for mr in paginate(mr_url, mr_params, f"MRs {name}"):
        # O endpoint de lista não retorna changes_count — busca individual
        if mr.get("changes_count") is None:
            detail = _get(
                f"{GITLAB_URL}/api/v4/projects/{pid}/merge_requests/{mr['iid']}",
                {}
            )
            if detail.ok:
                mr["changes_count"] = detail.json().get("changes_count")

        upsert_mr(conn, mr)
        upsert_mr_reviewers(conn, mr["id"], mr.get("reviewers") or [])

        # Notas (comentários de review)
        notes_url = f"{GITLAB_URL}/api/v4/projects/{pid}/merge_requests/{mr['iid']}/notes"
        notes = list(paginate(notes_url, {}, f"notes MR#{mr['iid']}"))
        upsert_mr_notes(conn, notes, mr["id"], pid)

        # Commits do MR (para tamanho real em linhas)
        commits_url = f"{GITLAB_URL}/api/v4/projects/{pid}/merge_requests/{mr['iid']}/commits"
        commit_shas = [c["id"] for c in paginate(commits_url, {}, f"commits MR#{mr['iid']}")]
        upsert_mr_commits(conn, mr["id"], pid, commit_shas)

        mr_count += 1
        if mr_count % 50 == 0:
            conn.commit()

    conn.commit()
    log.info("    MRs: %d", mr_count)
    if _db_logger:
        _db_logger.rows += mr_count

    # ── Commits ──────────────────────────────────────────────────────────────
    commit_url = f"{GITLAB_URL}/api/v4/projects/{pid}/repository/commits"
    commit_params = {"since": since, "all": "true", "with_stats": "true"}
    commit_count = 0
    try:
        for c in paginate(commit_url, commit_params, f"commits {name}"):
            upsert_commit(conn, c, pid, email_map, name_map)
            commit_count += 1
            if commit_count % 200 == 0:
                conn.commit()
        conn.commit()
    except requests.HTTPError as e:
        log.warning("    Commits indisponíveis para %s: %s", name, e)
        if _db_logger:
            _db_logger.warning("commits_unavailable", str(e), project=name)
    log.info("    Commits: %d", commit_count)
    if _db_logger:
        _db_logger.rows += commit_count

    # ── Pipelines ─────────────────────────────────────────────────────────────
    pipe_url = f"{GITLAB_URL}/api/v4/projects/{pid}/pipelines"
    pipe_params = {"updated_after": since, "order_by": "updated_at", "sort": "desc"}
    pipe_count = 0
    for pl in paginate(pipe_url, pipe_params, f"pipelines {name}"):
        upsert_pipeline(conn, pl, pid)
        pipe_count += 1
        if pipe_count % 200 == 0:
            conn.commit()
    conn.commit()
    log.info("    Pipelines: %d", pipe_count)

    # ── Deployments ──────────────────────────────────────────────────────────
    dep_url    = f"{GITLAB_URL}/api/v4/projects/{pid}/deployments"
    dep_params = {"updated_after": dep_since, "order_by": "updated_at", "sort": "desc"}
    dep_count  = 0
    try:
        for dep in paginate(dep_url, dep_params, f"deployments {name}"):
            upsert_deployment(conn, dep, pid)
            dep_count += 1
            if dep_count % 200 == 0:
                conn.commit()
        conn.commit()
    except requests.HTTPError as e:
        log.warning("    Deployments indisponíveis para %s: %s", name, e)
        if _db_logger:
            _db_logger.warning("deployments_unavailable", str(e), project=name)
    log.info("    Deployments: %d", dep_count)
    if _db_logger:
        _db_logger.rows += dep_count


# ── Sync completo ─────────────────────────────────────────────────────────────

def run_sync() -> None:
    global _db_logger
    log.info("═══ Iniciando sincronização ══════════════════════════════════════")
    start = time.time()

    conn = get_conn()
    _db_logger = DbLogger("gitlab", DATABASE_URL)
    try:
        since = get_sync_since(conn, "last_sync")
        _db_logger.start_run(since)
        _db_logger.info("sync_start", f"Sincronizando desde {since}")

        # Deployments: se a tabela estiver vazia, faz backfill de HISTORY_DAYS
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM gitlab_deployments")
            deploy_count = cur.fetchone()[0]
        if deploy_count == 0:
            dep_since = (datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)) \
                        .strftime("%Y-%m-%dT00:00:00Z")
            log.info("Tabela gitlab_deployments vazia — backfill de %d dias (desde %s).",
                     HISTORY_DAYS, dep_since)
            _db_logger.info("deployments_backfill",
                            f"Backfill inicial de deployments desde {dep_since}")
        else:
            dep_since = since

        log.info("Construindo mapa de usuários ...")
        email_map, name_map = build_email_map(conn, GROUP_ID)

        log.info("Resolvendo commits históricos sem username ...")
        backfill_commit_usernames(conn, email_map, name_map)

        log.info("Buscando projetos do grupo %s ...", GROUP_ID)
        projects_url = f"{GITLAB_URL}/api/v4/groups/{GROUP_ID}/projects"
        projects = list(paginate(projects_url, {"include_subgroups": "true", "archived": "false"}))
        log.info("  %d projeto(s) encontrado(s).", len(projects))

        project_errors = 0
        for proj in projects:
            try:
                collect_project_data(conn, proj, since, dep_since, email_map, name_map)
            except Exception as e:
                pname = proj.get("path_with_namespace", "?")
                log.error("Erro ao coletar projeto %s: %s", pname, e)
                _db_logger.error("project_error", str(e), project=pname)
                project_errors += 1
                conn.rollback()

        new_since = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        set_sync_since(conn, "last_sync", new_since)

        elapsed = time.time() - start
        status = "partial" if project_errors else "success"
        _db_logger.finish_run(status, {"elapsed_s": round(elapsed, 1),
                                        "projects": len(projects),
                                        "project_errors": project_errors})
        log.info("═══ Sync concluído em %.0fs ══════════════════════════════════════", elapsed)
    except Exception as e:
        log.error("Erro crítico no sync: %s", e)
        _db_logger.error("sync_critical", str(e))
        _db_logger.finish_run("failed")
        conn.rollback()
    finally:
        conn.close()


# ── Bootstrap ─────────────────────────────────────────────────────────────────

def validate_env() -> None:
    missing = [v for v in ["GITLAB_URL", "GITLAB_TOKEN", "GITLAB_GROUP_ID", "DATABASE_URL"]
               if not os.environ.get(v)]
    if missing:
        log.error("Variáveis de ambiente obrigatórias ausentes: %s", ", ".join(missing))
        sys.exit(1)


def wait_for_db(retries: int = 20, delay: int = 5) -> None:
    for attempt in range(1, retries + 1):
        try:
            conn = psycopg2.connect(DATABASE_URL)
            conn.close()
            log.info("Banco de dados disponível.")
            return
        except psycopg2.OperationalError:
            log.info("Aguardando banco de dados ... (%d/%d)", attempt, retries)
            time.sleep(delay)
    log.error("Banco de dados não disponível após %d tentativas.", retries)
    sys.exit(1)


def main() -> None:
    validate_env()
    wait_for_db()

    # Inicializa schema
    conn = get_conn()
    init_db(conn)
    conn.close()

    # Primeira carga
    run_sync()

    # Agenda sincronizações periódicas
    log.info("Próximas sincronizações a cada %d hora(s).", SYNC_INTERVAL)
    schedule.every(SYNC_INTERVAL).hours.do(run_sync)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
