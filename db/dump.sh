#!/usr/bin/env bash
# Gera um dump SQL completo do banco de métricas.
# Uso: ./db/dump.sh
# O arquivo gerado pode ser commitado para versionamento.

set -euo pipefail

CONTAINER="metrics-postgres"
DB_USER="${POSTGRES_USER:-metrics}"
DB_NAME="${POSTGRES_DB:-gitlab_metrics}"
OUT="$(dirname "$0")/dump.sql"

echo "Gerando dump de ${DB_NAME} em ${OUT} ..."
docker exec "${CONTAINER}" pg_dump -U "${DB_USER}" "${DB_NAME}" > "${OUT}"
echo "Dump concluido: $(wc -l < "${OUT}") linhas."
