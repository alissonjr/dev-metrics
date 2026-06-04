---
title: Dashboard Jira Kanban
description: Throughput, lead time, cycle time, action time, awaiting time e WIP.
---

**UID Grafana:** `jira-kanban-metrics`
**Acesso:** `http://localhost:3000/d/jira-kanban-metrics`
**Fonte de dados:** PostgreSQL - tabelas `jira_issues`, `jira_issue_transitions`, `jira_boards`

Este dashboard apresenta métricas de fluxo Kanban coletadas da API do Jira. Os
dados são coletados pelo serviço `jira-etl` (container `metrics-jira-etl`) e
armazenados no banco `gitlab_metrics`.

**Filtros disponíveis:** Projeto, Quadro (Board), Responsável (Assignee), Tipo de Card.

---

## Como as métricas de tempo são calculadas

Todas as métricas de tempo derivam da tabela `jira_issue_transitions`, que registra cada mudança
de status de cada card com o timestamp exato da transição.

O campo `status_category` classifica cada status em três categorias:

| Categoria       | Significado                     | Exemplos de status               |
|-----------------|---------------------------------|----------------------------------|
| `new`           | Aguardando - na fila            | **Backlog**, **A Fazer**         |
| `indeterminate` | Em andamento - time trabalhando | Fazendo, Review, QA, In Progress |
| `done`          | Concluído                       | Finalizado, Done                 |

> **Atenção:** Backlog e A Fazer compartilham a mesma `status_category = 'new'`, mas têm
> significados distintos. **Backlog** = itens ainda não priorizados. **A Fazer** = cards
> priorizados e prontos para serem puxados. Para diferenciar nas queries, usar o campo `status`.

A categoria que conta como **Action Time** é configurável via `JIRA_ACTIVE_CATEGORIES` no `.env`
(padrão: `indeterminate`).

---

## Seção: Throughput - Cards Entregues

### Cards Concluídos por Semana

Conta cards com `resolved_at` na semana (`status_category = 'done'`).

**Interpretação:** Mede a velocidade de entrega do time. Quedas podem indicar impedimentos,
férias ou sprints com cards de escopo muito grande.

---

### Story Points Entregues por Semana

Soma dos story points dos cards resolvidos por semana.

**Interpretação:** Cards sem estimativa de SP são excluídos. Use em paralelo com a contagem de
cards para medir consistência das estimativas do time.

---

### Cards Criados vs Concluídos por Semana

Plota duas séries: Criados (`created_at`) vs Concluídos (`resolved_at`).

**Interpretação:** Quando "Criados" supera "Concluídos" de forma consistente, o backlog cresce -
sinal de que a demanda supera a capacidade do time.

---

## Seção: Lead Time e Cycle Time

### Definições

- **Lead Time** = `resolved_at` − `created_at`
  Tempo total desde a criação do card até a resolução. Inclui espera no backlog.

- **Cycle Time** = `resolved_at` − (primeira transição para `indeterminate`)
  Tempo desde que o time pegou o card até a entrega. Exclui espera no Backlog e A Fazer.

### Lead Time por Semana (h)

**Interpretação:** Reflete a experiência do cliente - quanto tempo um pedido demora desde que é
registrado até ser entregue. Inclui todo o tempo de espera.

---

### Cycle Time por Semana (h)

**Interpretação:** Reflete a eficiência do processo de desenvolvimento. A diferença entre lead
time e cycle time revela quanto tempo os cards ficam esperando antes de o time começar a trabalhar.

---

## Seção: Action Time e Awaiting Time

### Definições

- **Action Time** = soma do tempo em status de categoria `indeterminate`
  (ex: Fazendo, In Progress, Review, QA)

- **Awaiting Time** = Lead Time − Action Time
  Tempo em que o card ficou parado em fila (`new`), aguardando review ou em transição.

Ambos são calculados no ETL ao processar o histórico de transições de cada card.

---

### Action Time vs Awaiting Time por Colaborador

**Interpretação:** Razão alta de Awaiting/Action indica gargalos fora do controle do
desenvolvedor - cards esperando em filas de review, QA ou aguardando decisões externas.

---

### Lead Time Médio por Coluna do Kanban

**Interpretação:** Colunas de espera com tempo alto indicam gargalos no fluxo. Colunas de ação
com tempo alto podem indicar complexidade ou sobrecarga do responsável.

---

## Seção: WIP - Work in Progress

### Backlog

Cards com status 'Backlog' (`status ILIKE '%backlog%' AND status_category = 'new'`).

### A Fazer

Cards com `status_category = 'new'` excluindo os que estão no Backlog.

### WIP Geral (Ativo)

Total de cards com `status_category = 'indeterminate'`.

### WIP Ativo por Colaborador

WIP atual por responsável.

**Interpretação:** Mais de 3 cards simultâneos em `indeterminate` por pessoa pode indicar
multitasking excessivo.

---

## Seção: Por Tipo de Card

### Cards Concluídos por Tipo

Pizza com proporção de cards entregues por tipo (Story, Bug, Task, Subtask, Epic).

**Interpretação:** Alta proporção de Bugs pode indicar débito técnico ou instabilidade que desvia
capacidade do time do desenvolvimento de features.
