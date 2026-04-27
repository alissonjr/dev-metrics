# Dashboard: Jira Sprint Dashboard

**UID Grafana:** `jira-sprint-dashboard`  
**Acesso:** http://localhost:3000/d/jira-sprint-dashboard  
**Fonte de dados:** PostgreSQL — tabelas `jira_sprints`, `jira_sprint_issues`, `jira_issues`

Este dashboard apresenta métricas específicas de sprint: visão geral, burndown, distribuição
dos cards por status/responsável e histórico de velocidade.

**Filtros disponíveis:** Quadro (Board), Sprint (filtrado pelo quadro selecionado).

---

## Como os dados de sprint são coletados

Os sprints são coletados de duas fontes complementares:

1. **Campo `customfield_10020`** nos issues do Jira: contém metadados da sprint vinculada a cada
   card (id, nome, estado, datas). Isso popula `jira_sprints` e `jira_sprint_issues`.

2. **API Agile** (`/rest/agile/1.0/board/{id}/sprint`): usada para buscar `completeDate` de
   sprints fechadas e garantir que todas as sprints do quadro sejam importadas, mesmo sem issues.

---

## Seção: Visão Geral da Sprint

### Período da Sprint

Exibe as datas de início e fim formatadas como `DD/MM → DD/MM/YYYY`.

```sql
SELECT TO_CHAR(start_date AT TIME ZONE 'America/Sao_Paulo', 'DD/MM') || ' → '
    || TO_CHAR(end_date   AT TIME ZONE 'America/Sao_Paulo', 'DD/MM/YYYY') AS "Período"
FROM jira_sprints WHERE id = $sprint::integer
```

---

### Total de Cards

Total de cards vinculados à sprint, independente do status.

```sql
SELECT COUNT(*) AS "Total"
FROM jira_sprint_issues jsi
JOIN jira_issues ji ON jsi.issue_key = ji.issue_key
WHERE jsi.sprint_id = $sprint
```

---

### Cards Concluídos

Cards da sprint com `status_category = 'done'`.

**Nota:** Reflete o estado atual do card, não o estado no momento da sprint. Um card resolvido
após o término da sprint ainda conta como concluído aqui.

---

### Story Points Planejados

Soma dos story points de todos os cards da sprint, incluindo os não concluídos.

---

### Story Points Entregues

Soma dos story points exclusivamente dos cards com `status_category = 'done'`.

---

### Taxa de Conclusão

Percentual de cards concluídos sobre o total. Calculado por contagem de cards, não por SP.

```sql
SELECT ROUND(
  100.0 * COUNT(*) FILTER (WHERE ji.status_category = 'done')
  / NULLIF(COUNT(*), 0), 1
) AS "Conclusão %"
FROM jira_sprint_issues jsi
JOIN jira_issues ji ON jsi.issue_key = ji.issue_key
WHERE jsi.sprint_id = $sprint
```

**Interpretação:** Meta ideal: 100%. Valores abaixo de 80% consecutivos indicam problemas de
planejamento de capacidade ou escopo que cresce durante a sprint.

---

## Seção: Burndown

Os gráficos de burndown são calculados inteiramente via SQL usando `generate_series` — sem
necessidade de tabela de snapshots diários. A lógica gera uma linha por dia da sprint e conta
quantos cards ainda não tinham sido resolvidos até aquela data.

### Burndown — Cards Restantes

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

- **Linha real (vermelho):** cards da sprint ainda não concluídos em cada dia
- **Linha ideal (cinza tracejado):** decréscimo linear do total até zero no último dia da sprint

---

### Burndown — Story Points Restantes

Mesma lógica, substituindo contagem de cards por soma de `story_points`.

- **Linha real (laranja):** SP ainda não entregues em cada dia
- **Linha ideal (cinza tracejado):** decréscimo linear do SP total até zero no último dia

---

## Seção: Sprint — Cards por Coluna

### Qtd de Cards por Status do Kanban

Contagem atual de cards da sprint agrupada por status.

```sql
SELECT ji.status AS "Status", COUNT(*) AS "Cards"
FROM jira_sprint_issues jsi
JOIN jira_issues ji ON jsi.issue_key = ji.issue_key
WHERE jsi.sprint_id = $sprint
GROUP BY ji.status
ORDER BY MIN(
  CASE ji.status_category
    WHEN 'new' THEN 1
    WHEN 'indeterminate' THEN 2
    WHEN 'done' THEN 3 ELSE 4
  END
), COUNT(*) DESC
```

**Interpretação:** Colunas com muitos cards indicam gargalo naquele status. Compare com o Lead
Time do dashboard Kanban para confirmar o impacto.

---

### Qtd de Cards por Responsável

Cards da sprint por responsável, empilhados por categoria de status (done / indeterminate / new).
Note que `new` inclui tanto Backlog quanto A Fazer.

**Interpretação:** Permite ver progresso e carga de cada pessoa na sprint.

---

### Distribuição por Tipo de Card

Pizza com composição da sprint por tipo (Story, Bug, Task, Subtask, Epic).

**Interpretação:** Alta proporção de Bugs em relação a Stories pode indicar débito técnico
acumulado que está desviando capacidade do desenvolvimento de novas funcionalidades.

---

### Story Points por Responsável

SP distribuídos por responsável, separados por categoria de status.

**Interpretação:** Mostra contribuição em termos de esforço estimado — diferente da contagem
de cards, considera o tamanho relativo de cada entrega.

---

## Seção: Sprint — Lista Completa

### Cards da Sprint

Tabela com todos os cards da sprint:

| Coluna        | Fonte                                                             |
|---------------|-------------------------------------------------------------------|
| Card          | `issue_key`                                                       |
| Título        | `summary` (truncado em 80 caracteres)                             |
| Tipo          | `issue_type`                                                      |
| Status        | `status`                                                          |
| Responsável   | `assignee`                                                        |
| SP            | `story_points`                                                    |
| Lead Time (h) | `lead_time_hours` ou horas desde `created_at` até agora, se aberto|

Ordenado por `status_category` (cards em aberto primeiro) para destacar o que ainda precisa de atenção.

---

## Seção: Velocidade Histórica

### Cards Concluídos por Sprint

Quantidade de cards com `status_category = 'done'` por sprint, ordenado por `start_date`.
Limitado às 20 sprints mais recentes do quadro selecionado.

**Interpretação:** Referência histórica de velocidade. Sprints com variação grande indicam
instabilidade de capacidade ou escopo mal dimensionado.

---

### Story Points por Sprint

SP entregues (done) vs SP não entregues (não done) por sprint, em barras empilhadas.

**Interpretação:** Mostra consistência da velocidade em termos de esforço estimado e taxa de
cumprimento dos objetivos da sprint.
