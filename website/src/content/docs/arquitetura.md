---
title: Arquitetura
description: Diagramas de ETL, system design e processo de sync do dev-metrics.
---

Três visões da mesma plataforma: como os dados entram (ETL), como os serviços
se conectam (system design) e como o ciclo de coleta roda no tempo (processo).

## Pipeline ETL

Dois coletores em Python seguem o mesmo padrão Extract / Transform / Load. Cada
um lê uma API REST, normaliza o JSON e deriva métricas (cycle time, lead time,
action e awaiting time), e grava no PostgreSQL de forma idempotente via UPSERT.

![Pipeline ETL: GitLab e Jira passam pelo coletor Python (extract, transform, load) até o PostgreSQL e o Grafana](/dev-metrics/etl-diagram.svg)

- **Extract** usa `requests` com paginação e sync incremental ancorado em `sync_state`.
- **Transform** normaliza os payloads e calcula as colunas derivadas de tempo.
- **Load** faz UPSERT com `psycopg2` e registra o resultado em `integration_logs`.

## System Design

Quatro containers sobem com um `make up`, todos na mesma rede do Docker Compose.
Os coletores falam HTTPS com as APIs externas, escrevem no PostgreSQL pela porta
5432 interna, e o Grafana lê o mesmo banco e serve os dashboards na porta 3000.

![System design: quatro containers Docker Compose (dois coletores, PostgreSQL e Grafana) consumindo as APIs do GitLab e Jira e servindo o navegador na porta 3000](/dev-metrics/system-design.svg)

| Container             | Papel                                  | Detalhe              |
|-----------------------|----------------------------------------|----------------------|
| `metrics-gitlab-etl`  | Coleta da GitLab REST API              | sync a cada 6h       |
| `metrics-jira-etl`    | Coleta da Jira REST API                | sync a cada 4h       |
| `metrics-postgres`    | Armazenamento compartilhado            | db `gitlab_metrics`  |
| `metrics-grafana`     | Visualização e dashboards              | porta `3000`         |

Cada coletor é independente: deixe as variáveis do outro grupo em branco e o
container correspondente apenas loga "desativado" e dorme, sem afetar o resto.

## Processo de Sync

Cada coletor roda um ciclo agendado. A cada disparo ele lê o último ponto de
sincronização, extrai apenas o que mudou, transforma, carrega, registra o run e
atualiza o checkpoint antes de dormir até o próximo intervalo. Falhas são
capturadas e registradas em `integration_logs` sem derrubar o ciclo.

![Process design: ciclo de sync agendado, do disparo do scheduler até o sleep, com tratamento de erro registrado em integration_logs](/dev-metrics/process-design.svg)

O sync incremental via `sync_state` evita reprocessar todo o histórico a cada
ciclo. O `HISTORY_DAYS` (padrão `365`) define apenas a profundidade do primeiro
sync; os seguintes só puxam o delta.
