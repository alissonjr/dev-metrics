# Dashboard: Jira Kanban Metrics

**UID Grafana:** `jira-kanban-metrics`  
**Acesso:** http://localhost:3000/d/jira-kanban-metrics  
**Fonte de dados:** PostgreSQL — tabelas `jira_issues`, `jira_issue_transitions`, `jira_boards`

Este dashboard apresenta métricas de fluxo Kanban coletadas da API do Jira. Os dados são
coletados pelo serviço `jira-etl` (container `metrics-jira-etl`) e armazenados no banco
`gitlab_metrics`.

**Filtros disponíveis:** Projeto, Quadro (Board), Responsável (Assignee), Tipo de Card.

---

## Como as métricas de tempo são calculadas

Todas as métricas de tempo derivam da tabela `jira_issue_transitions`, que registra cada mudança
de status de cada card com o timestamp exato da transição.

O campo `status_category` classifica cada status em três categorias:

| Categoria       | Significado                     | Exemplos de status               |
|-----------------|---------------------------------|----------------------------------|
| `new`           | Aguardando — na fila            | **Backlog**, **A Fazer**         |
| `indeterminate` | Em andamento — time trabalhando | Fazendo, Review, QA, In Progress |
| `done`          | Concluído                       | Finalizado, Done                 |

> **Atenção:** Backlog e A Fazer compartilham a mesma `status_category = 'new'`, mas têm
> significados distintos. **Backlog** = itens ainda não priorizados. **A Fazer** = cards
> priorizados e prontos para serem puxados. Para diferenciar nas queries, usar o campo `status`.

A categoria que conta como **Action Time** é configurável via `JIRA_ACTIVE_CATEGORIES` no `.env`
(padrão: `indeterminate`).

---

## Seção: Throughput — Cards Entregues

### Cards Concluídos por Semana

Conta cards com `resolved_at` na semana (status_category = 'done').

```sql
SELECT date_trunc('week', resolved_at) AS time,
       COUNT(*) AS "Cards Concluídos"
FROM jira_issues
WHERE resolved_at BETWEEN $__timeFrom() AND $__timeTo()
  AND project_key ~ '$project'
  AND assignee ~ '$assignee'
GROUP BY 1 ORDER BY 1
```

**Interpretação:** Mede a velocidade de entrega do time. Quedas podem indicar impedimentos,
férias ou sprints com cards de escopo muito grande.

---

### Throughput por Projeto / Semana

Mesmo cálculo do anterior, mas segmentado por `project_key`.

**Interpretação:** Permite comparar cadência entre diferentes times ou squads.

---

### Story Points Entregues por Semana

Soma dos story points dos cards resolvidos por semana.

**Interpretação:** Cards sem estimativa de SP são excluídos. Use em paralelo com a contagem de
cards para medir consistência das estimativas do time.

---

### Cards Criados vs Concluídos por Semana

Plota duas séries:
- **Criados:** cards com `created_at` na semana (entrada na fila)
- **Concluídos:** cards com `resolved_at` na semana (saída)

**Interpretação:** Quando "Criados" supera "Concluídos" de forma consistente, o backlog cresce —
sinal de que a demanda supera a capacidade do time.

---

## Seção: Lead Time e Cycle Time

### Definições

- **Lead Time** = `resolved_at` − `created_at`  
  Tempo total desde a criação do card até a resolução. Inclui espera no backlog.

- **Cycle Time** = `resolved_at` − (primeira transição para status `indeterminate`)  
  Tempo desde que o time pegou o card até a entrega. Exclui espera no Backlog e A Fazer.

### Lead Time por Semana (h)

Média do lead time dos cards resolvidos na semana.

**Interpretação:** Reflete a experiência do cliente — quanto tempo um pedido demora desde que é
registrado até ser entregue. Inclui todo o tempo de espera.

---

### Cycle Time por Semana (h)

Média do cycle time dos cards resolvidos na semana.

**Interpretação:** Reflete a eficiência do processo de desenvolvimento. A diferença entre lead
time e cycle time revela quanto tempo os cards ficam esperando antes de o time começar a trabalhar.

---

## Seção: Action Time e Awaiting Time

### Definições

- **Action Time** = soma do tempo em que o card esteve em status de categoria `indeterminate`  
  (ex: Fazendo, In Progress, Review, QA, QA Feature, QA Reprovado, Pronto para Produção)

- **Awaiting Time** = Lead Time − Action Time  
  Tempo em que o card ficou parado em fila (`new`), aguardando review, bloqueado ou em transição.

Ambos são calculados no ETL (`collector.py`) ao processar o histórico de transições de cada card:

```python
def compute_time_metrics(transitions, created_at, resolved_at):
    action_hours = 0
    for i, t in enumerate(sorted(transitions, key=lambda x: x["at"])):
        if t["to_category"] == ACTIVE_CATEGORY:   # indeterminate
            next_t = transitions[i+1]["at"] if i+1 < len(transitions) else resolved_at
            action_hours += (next_t - t["at"]).total_seconds() / 3600
    lead_hours     = (resolved_at - created_at).total_seconds() / 3600
    cycle_start    = # primeira transição para indeterminate
    cycle_hours    = (resolved_at - cycle_start).total_seconds() / 3600
    awaiting_hours = lead_hours - action_hours
    return lead_hours, cycle_hours, action_hours, awaiting_hours
```

---

### Action Time vs Awaiting Time por Colaborador (h médio)

Barchart horizontal com média de horas de action e awaiting por responsável.

**Interpretação:** Razão alta de Awaiting/Action indica gargalos fora do controle do
desenvolvedor — cards esperando em filas de review, QA ou aguardando decisões externas.

---

### Lead Time Médio por Coluna do Kanban

Tempo médio (em horas) que os cards resolvidos passaram em cada coluna/status do Jira. Barras
verdes representam colunas de ação (`indeterminate`) e barras amarelas representam colunas de
espera (`new`, `done`).

**Interpretação:** Colunas de espera com tempo alto indicam gargalos no fluxo — filas de review,
QA ou aguardando decisões externas. Colunas de ação com tempo alto podem indicar complexidade ou
sobrecarga do responsável.

---

### Horas Somadas por Tipo de Tempo / Semana

Soma total (não média) de horas de action e awaiting dos cards resolvidos na semana.

**Interpretação:** Mostra a carga absoluta do time e a proporção entre tempo produtivo (action)
e tempo ocioso/bloqueado (awaiting).

---

## Seção: Por Colaborador

### Métricas Completas por Colaborador

Tabela consolidada com todas as métricas por responsável no período filtrado:
cards entregues, SP entregues, lead time médio, cycle time médio, action time médio, awaiting time médio.

---

## Seção: Por Tipo de Card

### Cards Concluídos por Tipo

Pizza com proporção de cards entregues por tipo (Story, Bug, Task, Subtask, Epic).

**Interpretação:** Alta proporção de Bugs pode indicar débito técnico ou instabilidade que desvia
capacidade do time do desenvolvimento de features.

---

### Lead Time Médio por Tipo de Card

Barchart comparando lead time médio entre tipos.

**Interpretação:** Bugs costumam ter lead time menor por urgência. Epics e Stories mais complexas
têm lead time naturalmente maior. Comparar com cycle time revela onde cada tipo passa mais tempo.

---

## Seção: WIP — Work in Progress

### Backlog

Contador de cards com status 'Backlog' (`status ILIKE '%backlog%' AND status_category = 'new'`).

**Interpretação:** Indica o volume de itens que ainda não foram priorizados para execução.

---

### A Fazer

Contador de cards com `status_category = 'new'` excluindo os que estão no Backlog.

**Interpretação:** Cards priorizados e prontos para serem puxados pelo time. Um número alto
indica fila de trabalho represado antes da execução.

---

### WIP Geral (Ativo)

Contador total de cards em trabalho ativo (`status_category = 'indeterminate'`).

**Interpretação:** Serve como visão executiva de carga real em execução.

---

### WIP Ativo por Colaborador

WIP atual por responsável: quantidade de cards em trabalho ativo.

**Interpretação:** Permite identificar sobrecarga individual. Mais de 3 cards simultâneos em
`indeterminate` por pessoa pode indicar multitasking excessivo.

---

