#!/usr/bin/env bash
# Restaura o banco a partir do dump.sql.
# Uso: ./db/restore.sh
# ATENCAO: isso sobrescreve todos os dados existentes no banco.

set -euo pipefail

CONTAINER="metrics-postgres"
DB_USER="${POSTGRES_USER:-metrics}"
DB_NAME="${POSTGRES_DB:-gitlab_metrics}"
DUMP="$(dirname "$0")/dump.sql"

if [ ! -f "${DUMP}" ]; then
  echo "Erro: arquivo ${DUMP} nao encontrado."
  exit 1
fi

echo "Restaurando ${DB_NAME} a partir de ${DUMP} ..."
docker exec -i "${CONTAINER}" psql -U "${DB_USER}" -d "${DB_NAME}" < "${DUMP}"
echo "Restauracao concluida."
