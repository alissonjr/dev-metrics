---
title: Início rápido
description: Do zero aos dashboards rodando localmente em ~5 minutos.
---

Do zero até os dashboards funcionando em poucos minutos.

## Pré-requisitos

- [Docker](https://docs.docker.com/get-docker/) com Docker Compose v2
- [GNU Make](https://www.gnu.org/software/make/)
- Personal Access Token do GitLab e/ou API Token do Jira

## Passos

```bash
# 1. Clone
git clone https://github.com/alissonjr/dev-metrics.git
cd dev-metrics

# 2. Configure
cp .env.example .env
${EDITOR:-vi} .env

# 3. Suba a stack
make up

# 4. Abra o Grafana
# http://localhost:3000   (login: admin / admin)
```

A coleta inicial roda em background. Acompanhe com:

```bash
make logs-gitlab
make logs-jira
```

Dependendo do `HISTORY_DAYS` (padrão: `365`), pode levar de poucos minutos a
algumas horas no primeiro sync.

## Cada coletor é independente

Se você só usa GitLab, deixe todas as variáveis `JIRA_*` em branco. O container
`metrics-jira-etl` vai logar "desativado" e dormir, sem afetar o resto da
stack. O mesmo vale para o sentido contrário.

## Próximos passos

- Veja a página de [Configuração](/dev-metrics/configuracao/) para detalhes
  de tokens e variáveis opcionais.
- Explore os dashboards em [GitLab](/dev-metrics/dashboards/gitlab/),
  [Jira Kanban](/dev-metrics/dashboards/jira-kanban/) e
  [Jira Sprint](/dev-metrics/dashboards/jira-sprint/).
