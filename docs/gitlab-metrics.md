# Dashboard: GitLab Engineering Metrics

**UID Grafana:** `gitlab-eng-metrics`  
**Acesso:** http://localhost:3000/d/gitlab-eng-metrics  
**Fonte de dados:** PostgreSQL — tabelas `merge_requests`, `commits`, `notes`, `pipelines`

Este dashboard consolida métricas de engenharia coletadas da API do GitLab. Os dados são
coletados pelo serviço `etl` (container `metrics-etl`) e armazenados no banco `gitlab_metrics`.

---

## Seção: Merge Requests

### MRs Criados por Mês

Conta os Merge Requests abertos por mês, usando `created_at` como referência de data.

```sql
SELECT date_trunc('month', created_at) AS time,
       COUNT(*) AS "MRs Criados"
FROM merge_requests
WHERE created_at BETWEEN $__timeFrom() AND $__timeTo()
GROUP BY 1 ORDER BY 1
```

**Interpretação:** Indica a cadência de desenvolvimento — quantos trabalhos novos foram submetidos
para revisão a cada mês. Picos podem refletir entregas próximas a deadlines.

---

### MRs Mergeados por Mês

Conta os MRs que chegaram ao estado `merged` por mês, usando `merged_at`.

```sql
SELECT date_trunc('month', merged_at) AS time,
       COUNT(*) AS "MRs Mergeados"
FROM merge_requests
WHERE state = 'merged'
  AND merged_at BETWEEN $__timeFrom() AND $__timeTo()
GROUP BY 1 ORDER BY 1
```

**Interpretação:** Quando consistentemente abaixo de "MRs Criados", indica acúmulo de revisões
pendentes — sinal de gargalo no processo de code review.

---

### MRs por Autor — Volume e Ciclo

Tabela consolidada por autor com volume de MRs e tempo médio de ciclo (abertura até merge).

```sql
SELECT author_username AS "Autor",
       COUNT(*)        AS "MRs Criados",
       COUNT(*) FILTER (WHERE state = 'merged') AS "Mergeados",
       ROUND(100.0 * COUNT(*) FILTER (WHERE state = 'merged') / NULLIF(COUNT(*),0), 1) AS "Taxa Merge %",
       ROUND(AVG(EXTRACT(EPOCH FROM (merged_at - created_at)) / 3600)
             FILTER (WHERE state = 'merged'), 1) AS "Ciclo Médio (h)"
FROM merge_requests
WHERE created_at BETWEEN $__timeFrom() AND $__timeTo()
GROUP BY author_username
ORDER BY "MRs Criados" DESC
```

**Interpretação:** Ciclo médio alto pode indicar MRs grandes, falta de revisores ou dependências
externas que bloqueiam o merge.

---

## Seção: Tamanho de MRs

### MR Size — Arquivos e Linhas por Autor

Média de arquivos alterados e linhas modificadas (additions + deletions) por MR, por autor.

**Interpretação:** MRs com mais de 500 linhas tendem a receber revisões superficiais, aumentando
o risco de bugs passarem despercebidos. Use como referência para definir limites de tamanho.

---

## Seção: Commits e Linhas de Código

### Commits por Mês

Volume de commits por mês, incluindo branches em aberto e MRs.

**Interpretação:** Indica nível de atividade de desenvolvimento. Semanas com zero commits podem
indicar feriados, bloqueios ou períodos de planejamento de sprint.

---

### Linhas Modificadas por Mês

Soma de linhas adicionadas e deletadas por mês — proxy de volume de mudanças no código.

**Interpretação:** Não mede qualidade. Refatorações de limpeza podem ter alto volume sem entregar
funcionalidade nova. Analise em conjunto com throughput de MRs.

---

### Commits e Linhas por Autor

Por autor: total de commits, linhas adicionadas, deletadas e saldo líquido.

**Interpretação:** Saldo negativo (mais deleções que adições) geralmente indica refatoração ou
limpeza de código — pode ser positivo dependendo do contexto.

---

## Seção: Code Review

### Participação em Code Review

Conta comentários feitos em MRs de outros autores. Não inclui auto-comentários.

**Como é construído:** Cruza a tabela `notes` com `merge_requests` excluindo registros onde
`notes.author_username = merge_requests.author_username`.

**Interpretação:** Baixa participação de alguns membros pode indicar silos de conhecimento ou
sobrecarga que impede engajamento em revisões.

---

### Tempo Médio de 1ª Resposta no Review

Tempo entre a abertura do MR e o primeiro comentário de qualquer outro autor, em horas.

```sql
SELECT mr.author_username AS "Autor",
       ROUND(AVG(
         EXTRACT(EPOCH FROM (first_note.created_at - mr.created_at)) / 3600
       ), 1) AS "1ª Resposta (h)"
FROM merge_requests mr
JOIN LATERAL (
  SELECT MIN(created_at) AS created_at
  FROM notes
  WHERE mr_id = mr.id AND author_username != mr.author_username
) first_note ON true
WHERE ...
```

**Interpretação:** Valores acima de 24h indicam que MRs ficam aguardando revisor por muito tempo,
o que aumenta o custo de context switch para o autor quando o feedback chegar.

---

## Seção: Taxa de Retrabalho

### Taxa de Retrabalho por Autor

Proxy baseado em mensagens de commit. Classifica como retrabalho commits cujas mensagens
contêm as palavras: `fix`, `revert`, `bug`, `hotfix`, `correction`.

```sql
ROUND(100.0 * COUNT(*) FILTER (WHERE title ~* '\y(fix|revert|bug|hotfix|correction)\y')
      / NULLIF(COUNT(*), 0), 1) AS "Retrabalho %"
```

**Limitação:** Subestima retrabalho em times que não usam essas palavras nas mensagens de commit,
e pode superestimar em times que usam "fix" para ajustes normais de desenvolvimento. Use como
indicador de tendência, não como valor absoluto.

---

### Retrabalho % ao Longo dos Meses

Percentual mensal de commits classificados como retrabalho sobre o total de commits do mês.

**Interpretação:** Tendência crescente pode indicar pressão por velocidade sacrificando qualidade,
ou aumento de bugs em produção exigindo correções urgentes.

---

## Seção: Pipelines e CI/CD

### Taxa de Sucesso de Pipelines por Projeto

Por projeto: total de execuções, quantidade de sucesso, falha e percentual de sucesso.

**Interpretação:** Projetos com taxa abaixo de 80% merecem atenção. Pode indicar testes frágeis,
infraestrutura instável ou merges que quebram a build com frequência.

---

### Pipelines por Status ao Longo dos Meses

Volume mensal de pipelines por status: `success`, `failed`, `canceled`.

**Interpretação:** Picos de `failed` podem indicar instabilidade introduzida por mudanças recentes.
Alta taxa de `canceled` pode indicar pipelines redundantes ou desenvolvedores cancelando runs
antes da conclusão para economizar tempo.
