#!/usr/bin/env python3
"""
Jira Kanban Metrics Collector
Coleta dados da Jira API e armazena em PostgreSQL para Grafana.

Variáveis de ambiente obrigatórias:
    JIRA_URL          URL base do Jira Cloud  (ex: https://empresa.atlassian.net)
    JIRA_EMAIL        E-mail do usuário com acesso à API
    JIRA_TOKEN        API Token (gere em: id.atlassian.com > Security > API tokens)
    JIRA_PROJECTS     Chaves separadas por vírgula (ex: PROJ,DEV,OPS)
    DATABASE_URL      URL de conexão PostgreSQL

Variáveis opcionais:
    SYNC_INTERVAL_HOURS      Intervalo entre sincronizações (padrão: 4)
    HISTORY_DAYS             Dias de histórico na primeira carga (padrão: 365)
    LOG_LEVEL                DEBUG | INFO | WARNING (padrão: INFO)
    JIRA_STORY_POINTS_FIELD  Nome do campo de story points (padrão: story_points)
    ACTIVE_CATEGORIES        Categorias de status ativas separadas por vírgula (padrão: indeterminate)
"""

import base64
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Generator, List, Optional, Tuple

import psycopg2
import psycopg2.extras
import requests
import schedule

from db_logger import DbLogger

# ── Configuração ──────────────────────────────────────────────────────────────

JIRA_URL      = os.environ.get("JIRA_URL", "").rstrip("/")
JIRA_EMAIL    = os.environ.get("JIRA_EMAIL", "")
JIRA_TOKEN    = os.environ.get("JIRA_TOKEN", "")
JIRA_PROJECTS = [p.strip() for p in os.environ.get("JIRA_PROJECTS", "").split(",") if p.strip()]
DATABASE_URL  = os.environ.get("DATABASE_URL", "")
SYNC_INTERVAL = int(os.environ.get("SYNC_INTERVAL_HOURS", "4"))
HISTORY_DAYS  = int(os.environ.get("HISTORY_DAYS", "365"))
LOG_LEVEL     = os.environ.get("LOG_LEVEL", "INFO").upper()
SP_FIELD      = os.environ.get("JIRA_STORY_POINTS_FIELD", "story_points")
ACTIVE_CATS   = set(os.environ.get("ACTIVE_CATEGORIES", "indeterminate").split(","))
MAX_RESULTS   = 100

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("jira-collector")

_creds     = base64.b64encode(f"{JIRA_EMAIL}:{JIRA_TOKEN}".encode()).decode()
_db_logger: Optional[DbLogger] = None
HEADERS = {
    "Authorization": f"Basic {_creds}",
    "Accept":        "application/json",
    "Content-Type":  "application/json",
}

# Mapa fallback para os nomes de status mais comuns (inglês e português).
# Usado quando a API /rest/api/3/status não está acessível.
FALLBACK_STATUS_MAP: Dict[str, str] = {
    # → new (To Do)
    "to do": "new", "a fazer": "new", "backlog": "new",
    "open": "new", "aberto": "new", "aguardando": "new",
    "waiting": "new", "selected for development": "new",
    "ready for development": "new", "pronto para dev": "new",
    "ready": "new",
    # → indeterminate (In Progress)
    "in progress": "indeterminate", "em progresso": "indeterminate",
    "in development": "indeterminate", "em desenvolvimento": "indeterminate",
    "in review": "indeterminate", "em revisão": "indeterminate",
    "em revisao": "indeterminate", "code review": "indeterminate",
    "in testing": "indeterminate", "em teste": "indeterminate",
    "testing": "indeterminate", "homologação": "indeterminate",
    "homologacao": "indeterminate", "blocked": "indeterminate",
    "bloqueado": "indeterminate", "impedido": "indeterminate",
    "qa": "indeterminate",
    # → done
    "done": "done", "concluído": "done", "concluido": "done",
    "feito": "done", "resolved": "done", "resolvido": "done",
    "closed": "done", "fechado": "done", "cancelled": "done",
    "cancelado": "done", "won't do": "done", "won't fix": "done",
    "duplicate": "done", "duplicado": "done",
}


# ── Helpers HTTP ──────────────────────────────────────────────────────────────

class JiraAuthError(Exception):
    """Credenciais inválidas ou sem permissão (HTTP 401/403)."""


def _get(url: str, params: dict = {}) -> any:
    """
    Faz GET e retorna o JSON. Levanta:
    - JiraAuthError  em 401/403
    - requests.HTTPError  em outros erros HTTP
    """
    resp = requests.get(url, headers=HEADERS, params=params, timeout=60)
    if resp.status_code in (401, 403):
        raise JiraAuthError(f"HTTP {resp.status_code} em {url}")
    resp.raise_for_status()
    return resp.json()


def _get_safe(url: str, params: dict = {}) -> Optional[any]:
    """
    Versão tolerante a falhas: retorna None em qualquer erro.
    Usar para endpoints opcionais (boards, status map).
    """
    try:
        return _get(url, params)
    except JiraAuthError:
        log.warning("Sem permissão em %s (401/403) — ignorando.", url)
        return None
    except Exception as e:
        log.warning("Erro ao acessar %s: %s", url, e)
        return None


def validate_auth() -> None:
    """
    Testa credenciais via /rest/api/3/myself.
    Encerra o processo com sys.exit(1) se falhar.
    """
    try:
        me = _get(f"{JIRA_URL}/rest/api/3/myself")
        log.info("Autenticação OK — usuário: %s <%s>",
                 me.get("displayName", "?"), me.get("emailAddress", "?"))
    except JiraAuthError:
        log.error(
            "Autenticação Jira falhou (401/403).\n"
            "Verifique JIRA_EMAIL e JIRA_TOKEN no .env.\n"
            "Token gerado em: https://id.atlassian.com/manage-profile/security/api-tokens"
        )
        sys.exit(1)
    except Exception as e:
        log.error("Não foi possível conectar ao Jira (%s): %s", JIRA_URL, e)
        sys.exit(1)


def paginate_search(jql: str, fields: List[str]) -> Generator[dict, None, None]:
    """
    Busca issues via POST /rest/api/3/search/jql (Jira Cloud moderno).
    Paginação por nextPageToken (o endpoint não aceita startAt nem expand).
    """
    next_page_token: Optional[str] = None
    while True:
        body: dict = {
            "jql":        jql,
            "maxResults": MAX_RESULTS,
            "fields":     fields,
        }
        if next_page_token:
            body["nextPageToken"] = next_page_token

        while True:
            resp = requests.post(
                f"{JIRA_URL}/rest/api/3/search/jql",
                headers=HEADERS,
                json=body,
                timeout=60,
            )
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 60))
                log.warning("Jira rate limit (429) — aguardando %ds.", retry_after)
                if _db_logger:
                    _db_logger.warning("rate_limit", f"Jira 429 — aguardando {retry_after}s")
                time.sleep(retry_after + 1)
                continue
            if resp.status_code in (401, 403):
                raise JiraAuthError(f"HTTP {resp.status_code} na busca JQL")
            resp.raise_for_status()
            break

        data   = resp.json()
        issues = data.get("issues", [])
        if not issues:
            break
        yield from issues
        next_page_token = data.get("nextPageToken")
        if data.get("isLast", True) or not next_page_token:
            break
        time.sleep(0.1)


def fetch_issue_changelog(issue_key: str) -> List[dict]:
    """
    Busca o histórico completo de transições de status de um issue.
    Usa GET /rest/api/3/issue/{key}/changelog (paginado).
    """
    histories = []
    start_at  = 0
    while True:
        data = _get_safe(
            f"{JIRA_URL}/rest/api/3/issue/{issue_key}/changelog",
            {"maxResults": 100, "startAt": start_at},
        )
        if not data:
            break
        values = data.get("values", [])
        histories.extend(values)
        if data.get("isLast", True) or not values:
            break
        start_at += len(values)
    return histories


# ── Banco de dados ────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(DATABASE_URL)


def init_db(conn) -> None:
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path) as f:
        sql = f.read()
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    log.info("Schema Jira inicializado.")


def get_sync_since(conn) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT value FROM sync_state WHERE key = 'jira_last_sync'")
        row = cur.fetchone()
    if row:
        return row[0]
    default = datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)
    return default.strftime("%Y-%m-%d")


def set_sync_since(conn, value: str) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO sync_state(key, value, updated_at)
            VALUES ('jira_last_sync', %s, NOW())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
        """, (value,))
    conn.commit()


# ── Mapeamento status → categoria ─────────────────────────────────────────────

def build_status_map() -> Dict[str, str]:
    """
    Busca todos os status via API e retorna {nome_lower: category_key}.
    Em caso de falha, usa FALLBACK_STATUS_MAP para garantir classificação básica.
    category_key: 'new' | 'indeterminate' | 'done'
    """
    status_map = dict(FALLBACK_STATUS_MAP)  # começa com o fallback

    data = _get_safe(f"{JIRA_URL}/rest/api/3/status")
    if isinstance(data, list):
        for s in data:
            if not isinstance(s, dict):
                continue
            name     = (s.get("name") or "").strip().lower()
            category = (s.get("statusCategory") or {}).get("key", "new")
            if name:
                status_map[name] = category
        api_count = len(data)
    else:
        api_count = 0
        log.warning("API de status retornou formato inesperado (%s) — usando somente fallback.",
                    type(data).__name__)

    log.info("Status map: %d entradas (%d da API + fallback embutido).",
             len(status_map), api_count)
    return status_map


# ── Métricas de tempo ─────────────────────────────────────────────────────────

def compute_time_metrics(
    transitions:  List[dict],
    created_at:   Optional[datetime],
    resolved_at:  Optional[datetime],
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """
    Retorna: (lead_time_h, cycle_time_h, action_time_h, awaiting_time_h)

    - lead_time    : criação → resolução
    - cycle_time   : primeiro status ativo → resolução
    - action_time  : soma do tempo em status de categoria ACTIVE_CATS
    - awaiting_time: lead_time - action_time
    """
    if not resolved_at:
        return None, None, None, None

    lead_time_h: Optional[float] = None
    if created_at:
        lead_time_h = max(0.0, (resolved_at - created_at).total_seconds() / 3600.0)

    if not transitions:
        return lead_time_h, None, None, None

    sorted_trans = sorted(transitions, key=lambda t: t["transitioned_at"])

    first_active_at: Optional[datetime] = None
    action_seconds  = 0.0

    for i, trans in enumerate(sorted_trans):
        enter_at = trans["transitioned_at"]
        if enter_at >= resolved_at:
            break

        if i + 1 < len(sorted_trans):
            exit_at = min(sorted_trans[i + 1]["transitioned_at"], resolved_at)
        else:
            exit_at = resolved_at

        duration = max(0.0, (exit_at - enter_at).total_seconds())
        category = trans.get("to_category", "new")

        if category in ACTIVE_CATS:
            action_seconds += duration
            if first_active_at is None:
                first_active_at = enter_at

    cycle_time_h: Optional[float] = None
    if first_active_at:
        cycle_time_h = max(0.0, (resolved_at - first_active_at).total_seconds() / 3600.0)

    action_time_h   = action_seconds / 3600.0
    awaiting_time_h = (lead_time_h - action_time_h) if lead_time_h is not None else None

    return lead_time_h, cycle_time_h, action_time_h, awaiting_time_h


# ── Parsers ───────────────────────────────────────────────────────────────────

def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        from dateutil import parser as dp
        return dp.parse(value)
    except Exception:
        return None


_unknown_statuses: set = set()


def parse_transitions(histories: List[dict], status_map: Dict[str, str]) -> List[dict]:
    """Extrai transições de status do changelog do Jira."""
    transitions = []
    for history in histories:
        for item in history.get("items", []):
            if item.get("field") != "status":
                continue
            ts = parse_datetime(history.get("created"))
            if ts is None:
                continue
            from_name = (item.get("fromString") or "").strip().lower()
            to_name   = (item.get("toString")   or "").strip().lower()

            for sname in (from_name, to_name):
                if sname and sname not in status_map and sname not in _unknown_statuses:
                    _unknown_statuses.add(sname)
                    log.warning("Status desconhecido no mapa: '%s' — usando categoria 'new' como fallback.", sname)
                    if _db_logger:
                        _db_logger.warning("unknown_status",
                                           f"Status '{sname}' não encontrado no mapa — fallback para 'new'",
                                           details={"status_name": sname})

            transitions.append({
                "from_status":     item.get("fromString"),
                "to_status":       item.get("toString"),
                "from_category":   status_map.get(from_name, "new"),
                "to_category":     status_map.get(to_name,   "new"),
                "transitioned_at": ts,
                "author":          (history.get("author") or {}).get("displayName"),
            })
    return transitions


def extract_story_points(fields: dict) -> Optional[float]:
    for key in (SP_FIELD, "story_points", "customfield_10016", "customfield_10028"):
        val = fields.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    return None


def extract_sprints(fields: dict) -> List[dict]:
    """
    Extrai a lista de sprints de customfield_10020.
    Retorna lista de dicts com: id, name, state, boardId, goal, startDate, endDate.
    """
    raw = fields.get("customfield_10020")
    if not raw or not isinstance(raw, list):
        return []
    return [s for s in raw if isinstance(s, dict) and s.get("id")]


def current_sprint(sprints: List[dict]) -> Optional[dict]:
    """Retorna o sprint 'active' ou o último da lista."""
    if not sprints:
        return None
    active = [s for s in sprints if s.get("state") == "active"]
    return active[0] if active else sprints[-1]


# ── Upserts ───────────────────────────────────────────────────────────────────

def upsert_sprint(conn, sprint: dict, known_board_ids: set) -> None:
    """Upsert sprint a partir dos dados de customfield_10020 ou da Agile API."""
    board_id = sprint.get("boardId") or sprint.get("originBoardId")
    # só seta FK se o board já está na tabela
    if board_id not in known_board_ids:
        board_id = None
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO jira_sprints(id, board_id, name, state, goal, start_date, end_date, complete_date, synced_at)
            VALUES (%(id)s, %(board_id)s, %(name)s, %(state)s, %(goal)s,
                    %(start_date)s, %(end_date)s, %(complete_date)s, NOW())
            ON CONFLICT (id) DO UPDATE SET
                name          = EXCLUDED.name,
                state         = EXCLUDED.state,
                goal          = COALESCE(EXCLUDED.goal, jira_sprints.goal),
                start_date    = COALESCE(EXCLUDED.start_date, jira_sprints.start_date),
                end_date      = COALESCE(EXCLUDED.end_date, jira_sprints.end_date),
                complete_date = COALESCE(EXCLUDED.complete_date, jira_sprints.complete_date),
                board_id      = COALESCE(EXCLUDED.board_id, jira_sprints.board_id),
                synced_at     = NOW()
        """, {
            "id":           sprint["id"],
            "board_id":     board_id,
            "name":         sprint.get("name", ""),
            "state":        sprint.get("state", ""),
            "goal":         sprint.get("goal") or None,
            "start_date":   parse_datetime(sprint.get("startDate")),
            "end_date":     parse_datetime(sprint.get("endDate")),
            "complete_date": parse_datetime(sprint.get("completeDate")),
        })


def upsert_sprint_issue(conn, sprint_id: int, issue_key: str) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO jira_sprint_issues(sprint_id, issue_key, active, added_at)
            VALUES (%s, %s, TRUE, NOW())
            ON CONFLICT (sprint_id, issue_key) DO UPDATE SET
                active     = TRUE,
                removed_at = NULL
        """, (sprint_id, issue_key))


def upsert_board(conn, board: dict) -> None:
    project = (board.get("location") or {}).get("projectKey")
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO jira_boards(id, name, type, project_key, self_url, synced_at)
            VALUES (%(id)s, %(name)s, %(type)s, %(project_key)s, %(self_url)s, NOW())
            ON CONFLICT (id) DO UPDATE SET
                name        = EXCLUDED.name,
                type        = EXCLUDED.type,
                project_key = EXCLUDED.project_key,
                synced_at   = NOW()
        """, {
            "id":          board["id"],
            "name":        board.get("name", ""),
            "type":        board.get("type", ""),
            "project_key": project,
            "self_url":    board.get("self", ""),
        })


def upsert_issue(conn, issue_key: str, issue_id: str, board_id: Optional[int],
                 project_key: str, fields: dict, transitions: List[dict],
                 sprint_id: Optional[int] = None, sprint_name: Optional[str] = None) -> None:
    issuetype    = fields.get("issuetype") or {}
    status_obj   = fields.get("status")    or {}
    status_cat   = (status_obj.get("statusCategory") or {}).get("key", "new")
    assignee_obj = fields.get("assignee")  or {}
    reporter_obj = fields.get("reporter")  or {}
    priority_obj = fields.get("priority")  or {}
    parent_obj   = fields.get("parent")    or {}

    created_at  = parse_datetime(fields.get("created"))
    updated_at  = parse_datetime(fields.get("updated"))
    resolved_at = parse_datetime(fields.get("resolutiondate"))

    lead_h, cycle_h, action_h, awaiting_h = compute_time_metrics(
        transitions, created_at, resolved_at
    )

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO jira_issues(
                issue_key, issue_id, board_id, project_key,
                summary, issue_type, priority, status, status_category,
                assignee, assignee_email, reporter,
                created_at, updated_at, resolved_at,
                story_points, labels,
                lead_time_hours, cycle_time_hours, action_time_hours, awaiting_time_hours,
                sprint_id, sprint_name,
                parent_key,
                synced_at
            ) VALUES (
                %(issue_key)s, %(issue_id)s, %(board_id)s, %(project_key)s,
                %(summary)s, %(issue_type)s, %(priority)s, %(status)s, %(status_category)s,
                %(assignee)s, %(assignee_email)s, %(reporter)s,
                %(created_at)s, %(updated_at)s, %(resolved_at)s,
                %(story_points)s, %(labels)s,
                %(lead_h)s, %(cycle_h)s, %(action_h)s, %(awaiting_h)s,
                %(sprint_id)s, %(sprint_name)s,
                %(parent_key)s,
                NOW()
            )
            ON CONFLICT (issue_key) DO UPDATE SET
                board_id            = EXCLUDED.board_id,
                status              = EXCLUDED.status,
                status_category     = EXCLUDED.status_category,
                assignee            = EXCLUDED.assignee,
                assignee_email      = EXCLUDED.assignee_email,
                updated_at          = EXCLUDED.updated_at,
                resolved_at         = EXCLUDED.resolved_at,
                story_points        = EXCLUDED.story_points,
                labels              = EXCLUDED.labels,
                lead_time_hours     = EXCLUDED.lead_time_hours,
                cycle_time_hours    = EXCLUDED.cycle_time_hours,
                action_time_hours   = EXCLUDED.action_time_hours,
                awaiting_time_hours = EXCLUDED.awaiting_time_hours,
                sprint_id           = EXCLUDED.sprint_id,
                sprint_name         = EXCLUDED.sprint_name,
                parent_key          = EXCLUDED.parent_key,
                synced_at           = NOW()
        """, {
            "issue_key":      issue_key,
            "issue_id":       issue_id,
            "board_id":       board_id,
            "project_key":    project_key,
            "summary":        (fields.get("summary") or "")[:500],
            "issue_type":     issuetype.get("name"),
            "priority":       priority_obj.get("name"),
            "status":         status_obj.get("name"),
            "status_category": status_cat,
            "assignee":       assignee_obj.get("displayName"),
            "assignee_email": (assignee_obj.get("emailAddress") or "").lower() or None,
            "reporter":       reporter_obj.get("displayName"),
            "created_at":     created_at,
            "updated_at":     updated_at,
            "resolved_at":    resolved_at,
            "story_points":   extract_story_points(fields),
            "labels":         fields.get("labels") or [],
            "lead_h":         lead_h,
            "cycle_h":        cycle_h,
            "action_h":       action_h,
            "awaiting_h":     awaiting_h,
            "sprint_id":      sprint_id,
            "sprint_name":    sprint_name,
            "parent_key":     parent_obj.get("key"),
        })


def upsert_transitions(conn, issue_key: str, transitions: List[dict]) -> None:
    if not transitions:
        return
    with conn.cursor() as cur:
        for t in transitions:
            cur.execute("""
                INSERT INTO jira_issue_transitions(
                    issue_key, from_status, to_status,
                    from_category, to_category,
                    transitioned_at, author, synced_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (issue_key, transitioned_at, to_status) DO NOTHING
            """, (
                issue_key,
                t["from_status"], t["to_status"],
                t["from_category"], t["to_category"],
                t["transitioned_at"], t["author"],
            ))


# ── Coleta por projeto ────────────────────────────────────────────────────────

def fetch_boards_for_project(project_key: str) -> List[dict]:
    """Busca boards via Agile API. Retorna lista vazia se indisponível."""
    boards = []
    start  = 0
    while True:
        data = _get_safe(
            f"{JIRA_URL}/rest/agile/1.0/board",
            {"projectKeyOrId": project_key, "maxResults": 50, "startAt": start},
        )
        if data is None:
            break
        values = data.get("values", [])
        boards.extend(values)
        if data.get("isLast", True) or not values:
            break
        start += len(values)
    return boards


def fetch_sprints_for_board(board_id: int) -> List[dict]:
    """Busca todos os sprints de um board (active, closed, future)."""
    sprints = []
    start   = 0
    while True:
        data = _get_safe(
            f"{JIRA_URL}/rest/agile/1.0/board/{board_id}/sprint",
            {"maxResults": 50, "startAt": start, "state": "active,closed,future"},
        )
        if data is None:
            break
        values = data.get("values", [])
        sprints.extend(values)
        if data.get("isLast", True) or not values:
            break
        start += len(values)
    return sprints


def collect_project(conn, project_key: str, since: str,
                    status_map: Dict[str, str],
                    board_map: Dict[str, int],
                    known_board_ids: set) -> int:
    """Coleta issues atualizados desde `since`. Retorna qtd processada."""
    log.info("  Coletando projeto: %s", project_key)

    jql = (
        f'project = "{project_key}" '
        f'AND updated >= "{since}" '
        f"ORDER BY updated ASC"
    )
    fields = list(dict.fromkeys([
        "summary", "issuetype", "status", "assignee", "reporter",
        "created", "updated", "resolutiondate", "priority", "labels",
        SP_FIELD, "customfield_10016", "customfield_10028",
        "customfield_10020",   # sprint
        "parent",              # subtask → card pai
    ]))

    board_id = board_map.get(project_key)
    count    = 0

    for issue in paginate_search(jql, fields):
        issue_key = issue["key"]
        issue_id  = str(issue["id"])
        flds      = issue.get("fields") or {}

        # ── Sprints do issue ──────────────────────────────────────────────────
        sprints = extract_sprints(flds)
        for sp in sprints:
            try:
                upsert_sprint(conn, sp, known_board_ids)
            except Exception as e:
                log.debug("Sprint %s: %s", sp.get("id"), e)

        cur_sp     = current_sprint(sprints)
        sprint_id  = cur_sp["id"]   if cur_sp else None
        sprint_name = cur_sp["name"] if cur_sp else None

        # ── Changelog e transições ────────────────────────────────────────────
        histories   = fetch_issue_changelog(issue_key)
        transitions = parse_transitions(histories, status_map)

        upsert_issue(conn, issue_key, issue_id, board_id, project_key,
                     flds, transitions, sprint_id, sprint_name)
        upsert_transitions(conn, issue_key, transitions)

        # ── Vínculos sprint ↔ issue ───────────────────────────────────────────
        # Marca como removido (transbordo) vínculos que não estão mais no Jira
        current_sprint_ids = {sp["id"] for sp in sprints}
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE jira_sprint_issues
                SET    active = FALSE, removed_at = NOW()
                WHERE  issue_key = %s
                  AND  active = TRUE
                  AND  sprint_id != ALL(%s)
            """, (issue_key, list(current_sprint_ids)))
        for sp in sprints:
            try:
                upsert_sprint_issue(conn, sp["id"], issue_key)
            except Exception:
                pass

        count += 1
        if count % 50 == 0:
            conn.commit()
            log.info("    %s: %d issues …", project_key, count)

    conn.commit()
    log.info("    %s: %d issues.", project_key, count)
    return count


# ── Sync completo ─────────────────────────────────────────────────────────────

def run_sync() -> None:
    global _db_logger, _unknown_statuses
    _unknown_statuses = set()
    log.info("═══ Iniciando sincronização Jira ════════════════════════════════")
    start = time.time()

    conn = get_conn()
    _db_logger = DbLogger("jira", DATABASE_URL)
    try:
        since = get_sync_since(conn)
        _db_logger.start_run(since)
        _db_logger.info("sync_start", f"Sincronizando desde {since}")

        log.info("Carregando mapa de status …")
        status_map = build_status_map()

        # ── Boards ───────────────────────────────────────────────────────────
        board_map: Dict[str, int] = {}
        known_board_ids: set      = set()
        for project_key in JIRA_PROJECTS:
            boards = fetch_boards_for_project(project_key)
            for b in boards:
                try:
                    upsert_board(conn, b)
                    known_board_ids.add(b["id"])
                    if project_key not in board_map:
                        board_map[project_key] = b["id"]
                except Exception as e:
                    log.warning("Erro ao salvar board %s: %s", b.get("name"), e)
            conn.commit()
            log.info("  %s: %d board(s).", project_key, len(boards))

        # ── Sprints via Agile API ─────────────────────────────────────────────
        sprint_count = 0
        for bid in known_board_ids:
            for sp in fetch_sprints_for_board(bid):
                sp["boardId"] = bid
                try:
                    upsert_sprint(conn, sp, known_board_ids)
                    sprint_count += 1
                except Exception as e:
                    log.debug("Sprint %s: %s", sp.get("id"), e)
        conn.commit()
        log.info("Sprints coletados via Agile API: %d.", sprint_count)

        # ── Issues ───────────────────────────────────────────────────────────
        total   = 0
        success = 0
        for project_key in JIRA_PROJECTS:
            try:
                n = collect_project(conn, project_key, since, status_map,
                                    board_map, known_board_ids)
                total   += n
                success += 1
                _db_logger.rows += n
            except JiraAuthError as e:
                log.error("Sem permissão no projeto %s: %s", project_key, e)
                _db_logger.error("auth_error", str(e), project=project_key)
                conn.rollback()
            except Exception as e:
                log.error("Erro ao coletar %s: %s", project_key, e)
                _db_logger.error("project_error", str(e), project=project_key)
                conn.rollback()

        if success > 0:
            new_since = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%d")
            set_sync_since(conn, new_since)
        else:
            log.warning("Nenhum projeto coletado com sucesso — cursor de sync mantido em %s.", since)
            _db_logger.warning("sync_no_progress", "Nenhum projeto coletado — cursor mantido")

        elapsed = time.time() - start
        status  = "success" if success == len(JIRA_PROJECTS) else ("partial" if success > 0 else "failed")
        _db_logger.finish_run(status, {
            "elapsed_s":       round(elapsed, 1),
            "projects_ok":     success,
            "projects_total":  len(JIRA_PROJECTS),
            "issues_synced":   total,
            "unknown_statuses": list(_unknown_statuses),
        })
        log.info("═══ Sync concluído em %.0fs — %d issues processados ════", elapsed, total)

    except Exception as e:
        log.error("Erro crítico no sync: %s", e)
        _db_logger.error("sync_critical", str(e))
        _db_logger.finish_run("failed")
        conn.rollback()
    finally:
        conn.close()


# ── Bootstrap ─────────────────────────────────────────────────────────────────

def validate_env() -> bool:
    """
    Retorna True se o coletor deve rodar; False se está desativado por falta
    completa de configuração Jira. Sai com erro em config parcial ou se
    DATABASE_URL faltar.
    """
    if not os.environ.get("DATABASE_URL"):
        log.error("DATABASE_URL ausente — verifique docker-compose.yml.")
        sys.exit(1)

    user_vars = ["JIRA_URL", "JIRA_EMAIL", "JIRA_TOKEN", "JIRA_PROJECTS"]
    set_vars = [v for v in user_vars if os.environ.get(v)]

    if not set_vars:
        return False  # totalmente sem config — coletor desativado

    missing = [v for v in user_vars if not os.environ.get(v)]
    if missing:
        log.error("Configuração Jira incompleta. Faltam: %s", ", ".join(missing))
        log.error("Preencha todas as variáveis Jira no .env, ou deixe todas vazias para desativar este coletor.")
        sys.exit(1)
    return True


def run_disabled_loop() -> None:
    log.warning("Coletor Jira desativado: JIRA_URL/JIRA_EMAIL/JIRA_TOKEN/JIRA_PROJECTS não configurados no .env.")
    log.warning("Para ativar: preencha as variáveis e rode `make sync-jira`.")
    while True:
        time.sleep(3600)


def wait_for_db(retries: int = 20, delay: int = 5) -> None:
    for attempt in range(1, retries + 1):
        try:
            psycopg2.connect(DATABASE_URL).close()
            log.info("Banco de dados disponível.")
            return
        except psycopg2.OperationalError:
            log.info("Aguardando banco … (%d/%d)", attempt, retries)
            time.sleep(delay)
    log.error("Banco não disponível após %d tentativas.", retries)
    sys.exit(1)


def main() -> None:
    if not validate_env():
        run_disabled_loop()
        return
    wait_for_db()
    validate_auth()  # testa credenciais antes de qualquer coleta

    conn = get_conn()
    init_db(conn)
    conn.close()

    run_sync()

    log.info("Próximas sincronizações a cada %d hora(s).", SYNC_INTERVAL)
    schedule.every(SYNC_INTERVAL).hours.do(run_sync)
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
