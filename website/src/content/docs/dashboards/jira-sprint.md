---
title: Dashboard Jira Sprint
description: Visão geral, burndown e velocidade histórica por sprint.
---

**UID Grafana:** `jira-sprint-dashboard`
**Acesso:** `http://localhost:3000/d/jira-sprint-dashboard`
**Fonte de dados:** PostgreSQL - tabelas `jira_sprints`, `jira_sprint_issues`, `jira_issues`

Este dashboard apresenta métricas específicas de sprint: visão geral, burndown,
distribuição dos cards por status/responsável e histórico de velocidade.

**Filtros disponíveis:** Quadro (Board), Sprint (filtrado pelo quadro selecionado).

---

## Como os dados de sprint são coletados

1. **Campo `customfield_10020`** nos issues do Jira: contém metadados da sprint vinculada a cada
   card (id, nome, estado, datas). Isso popula `jira_sprints` e `jira_sprint_issues`.

2. **API Agile** (`/rest/agile/1.0/board/{id}/sprint`): usada para buscar `completeDate` de
   sprints fechadas e garantir que todas as sprints do quadro sejam importadas, mesmo sem issues.

---

## Seção: Visão Geral da Sprint

- **Período da Sprint** - datas de início e fim formatadas
- **Total de Cards** - total vinculado à sprint
- **Cards Concluídos** - cards com `status_category = 'done'`
- **Story Points Planejados / Entregues** - soma de SP no total e nos cards `done`
- **Taxa de Conclusão** - % cards concluídos sobre o total

> **Nota:** Reflete o estado atual do card, não o estado no momento da sprint. Um card resolvido
> após o término da sprint ainda conta como concluído aqui.

**Interpretação:** Meta ideal de Conclusão: 100%. Valores abaixo de 80% consecutivos indicam
problemas de planejamento de capacidade ou escopo que cresce durante a sprint.

---

## Seção: Burndown

Os gráficos de burndown são calculados inteiramente via SQL usando `generate_series` - sem
necessidade de tabela de snapshots diários.

### Burndown - Cards Restantes

```sql
WITH sp AS (
  SELECT id, start_date, end_date FROM jira_sprints WHERE id = $sprint
),
days AS (
  SELECT generate_series(sp.start_date::date, sp.end_date::date, '1 day'::interval) AS day
  FROM sp
),
total AS (
  SELECT COUNT(*) AS total_cards FROM jira_sprint_issues WHERE sprint_id = $sprint
)
SELECT
  d.day AS time,
  (t.total_cards - COUNT(ji.resolved_at) FILTER (WHERE ji.resolved_at::date <= d.day)) AS "Restantes",
  t.total_cards * (1 - EXTRACT(EPOCH FROM (d.day - sp.start_date))
    / NULLIF(EXTRACT(EPOCH FROM (sp.end_date - sp.start_date)), 0)) AS "Ideal"
FROM days d, sp, total t
LEFT JOIN jira_sprint_issues jsi ON jsi.sprint_id = $sprint
LEFT JOIN jira_issues ji ON jsi.issue_key = ji.issue_key
GROUP BY d.day, sp.start_date, sp.end_date, t.total_cards
ORDER BY d.day
```

- **Linha real:** cards da sprint ainda não concluídos em cada dia
- **Linha ideal:** decréscimo linear do total até zero no último dia da sprint

### Burndown - Story Points Restantes

Mesma lógica, substituindo contagem de cards por soma de `story_points`.

---

## Seção: Sprint - Cards por Coluna

- **Qtd de Cards por Status do Kanban** - agrupado por status atual
- **Qtd de Cards por Responsável** - empilhado por categoria de status
- **Distribuição por Tipo de Card** - pizza por tipo (Story, Bug, Task, etc.)
- **Story Points por Responsável** - SP por pessoa, separado por status

**Interpretação:** Colunas com muitos cards indicam gargalo. Alta proporção de Bugs em relação a
Stories pode indicar débito técnico desviando capacidade do time.

---

## Seção: Sprint - Lista Completa

Tabela com todos os cards: card, título (truncado em 80 chars), tipo, status, responsável, SP
e lead time. Ordenada por `status_category` (cards em aberto primeiro).

---

## Seção: Velocidade Histórica

- **Cards Concluídos por Sprint** - últimas 20 sprints do quadro selecionado
- **Story Points por Sprint** - SP entregues vs não entregues, em barras empilhadas

**Interpretação:** Variação grande entre sprints indica instabilidade de capacidade ou escopo
mal dimensionado.
