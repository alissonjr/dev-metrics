"""
DbLogger — grava logs estruturados no PostgreSQL e espelha no logging Python.
Usa conexão própria para não interferir nas transações do coletor.
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import psycopg2

log = logging.getLogger("db_logger")


class DbLogger:
    def __init__(self, source: str, db_url: str):
        self._source  = source
        self._db_url  = db_url
        self._conn    = None
        self._run_id: Optional[int] = None
        self.rows     = 0
        self.errors   = 0

    # ── conexão própria ───────────────────────────────────────────────────────

    def _get_conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self._db_url)
            self._conn.autocommit = True
        return self._conn

    def close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()

    # ── escrita no banco ──────────────────────────────────────────────────────

    def _write(
        self,
        level:      str,
        event_type: str,
        message:    str,
        project:    Optional[str] = None,
        rows:       Optional[int] = None,
        details:    Optional[dict] = None,
    ) -> None:
        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO integration_logs
                        (source, level, event_type, message, project, rows_synced, details, run_id, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """, (
                    self._source,
                    level,
                    event_type,
                    message,
                    project,
                    rows,
                    json.dumps(details) if details else None,
                    self._run_id,
                ))
        except Exception as exc:
            log.debug("DbLogger write falhou (continuando sem log no banco): %s", exc)
            self._conn = None  # força reconexão na próxima tentativa

    # ── API de log ────────────────────────────────────────────────────────────

    def info(self, event_type: str, message: str, **kw: Any) -> None:
        log.info("[%s] %s", event_type, message)
        self._write("info", event_type, message, **kw)

    def warning(self, event_type: str, message: str, **kw: Any) -> None:
        log.warning("[%s] %s", event_type, message)
        self._write("warning", event_type, message, **kw)

    def error(self, event_type: str, message: str, **kw: Any) -> None:
        log.error("[%s] %s", event_type, message)
        self._write("error", event_type, message, **kw)
        self.errors += 1

    # ── controle de run ───────────────────────────────────────────────────────

    def start_run(self, since_cursor: str) -> None:
        self.rows   = 0
        self.errors = 0
        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO integration_sync_runs
                        (source, started_at, status, since_cursor)
                    VALUES (%s, NOW(), 'running', %s)
                    RETURNING id
                """, (self._source, since_cursor))
                self._run_id = cur.fetchone()[0]
        except Exception as exc:
            log.debug("DbLogger start_run falhou: %s", exc)
            self._conn = None

    def finish_run(self, status: str, details: Optional[dict] = None) -> None:
        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE integration_sync_runs
                    SET finished_at  = NOW(),
                        status       = %s,
                        rows_synced  = %s,
                        errors_count = %s,
                        details      = %s
                    WHERE id = %s
                """, (
                    status,
                    self.rows,
                    self.errors,
                    json.dumps(details) if details else None,
                    self._run_id,
                ))
        except Exception as exc:
            log.debug("DbLogger finish_run falhou: %s", exc)
            self._conn = None
        finally:
            self.close()
