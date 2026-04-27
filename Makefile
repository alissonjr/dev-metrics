.PHONY: help up down build restart logs logs-gitlab logs-jira \
        sync-gitlab sync-jira dump restore psql status


# Exibe todos os comandos disponiveis
help:
	@echo ""
	@echo "Engineering Metrics — comandos disponiveis"
	@echo "--------------------------------------------"
	@echo "  make up              Sobe todos os servicos (postgres, grafana, gitlab-etl, jira-etl)"
	@echo "  make down            Para todos os servicos"
	@echo "  make build           Reconstroi as imagens dos coletores (ETL)"
	@echo "  make restart         Para e sobe novamente todos os servicos"
	@echo ""
	@echo "  make logs            Exibe logs de todos os servicos em tempo real"
	@echo "  make logs-gitlab     Exibe logs do coletor GitLab"
	@echo "  make logs-jira       Exibe logs do coletor Jira"
	@echo "  make status          Exibe o estado dos containers"
	@echo ""
	@echo "  make sync-gitlab     Forca uma nova sincronizacao GitLab (reinicia o container)"
	@echo "  make sync-jira       Forca uma nova sincronizacao Jira (reinicia o container)"
	@echo ""
	@echo "  make dump            Gera dump SQL do banco em db/dump.sql"
	@echo "  make restore         Restaura o banco a partir de db/dump.sql"
	@echo "  make psql            Abre shell interativo do PostgreSQL"
	@echo ""

# -----------------------------------------------------------------------------
# Ciclo de vida
# -----------------------------------------------------------------------------

up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build gitlab-etl jira-etl

restart: down up

# -----------------------------------------------------------------------------
# Logs e monitoramento
# -----------------------------------------------------------------------------

logs:
	docker compose logs -f

logs-gitlab:
	docker logs metrics-gitlab-etl -f

logs-jira:
	docker logs metrics-jira-etl -f

status:
	docker compose ps

# -----------------------------------------------------------------------------
# Sincronizacao manual
# -----------------------------------------------------------------------------

sync-gitlab:
	@echo "Reiniciando coletor GitLab para forcar sincronizacao..."
	docker restart metrics-gitlab-etl
	@echo "Acompanhe com: make logs-gitlab"

sync-jira:
	@echo "Reiniciando coletor Jira para forcar sincronizacao..."
	docker restart metrics-jira-etl
	@echo "Acompanhe com: make logs-jira"

# -----------------------------------------------------------------------------
# Banco de dados
# -----------------------------------------------------------------------------

dump:
	@echo "Gerando dump em db/dump.sql ..."
	docker exec metrics-postgres pg_dump -U $${POSTGRES_USER:-metrics} $${POSTGRES_DB:-gitlab_metrics} > db/dump.sql
	@echo "Dump concluido: $$(wc -l < db/dump.sql) linhas."

restore:
	@echo "Restaurando banco a partir de db/dump.sql ..."
	docker exec -i metrics-postgres psql -U $${POSTGRES_USER:-metrics} -d $${POSTGRES_DB:-gitlab_metrics} < db/dump.sql
	@echo "Restauracao concluida."

psql:
	docker exec -it metrics-postgres psql -U $${POSTGRES_USER:-metrics} -d $${POSTGRES_DB:-gitlab_metrics}
