---
title: Dashboard GitLab
description: Métricas de Merge Requests, code review, commits, pipelines e DORA.
---

**UID Grafana:** `gitlab-eng-metrics`
**Acesso:** `http://localhost:3000/d/gitlab-eng-metrics`
**Fonte de dados:** PostgreSQL - tabelas `gitlab_merge_requests`, `gitlab_commits`, `gitlab_mr_notes`, `gitlab_pipelines`

Este dashboard consolida métricas de engenharia coletadas da API do GitLab. Os
dados são coletados pelo serviço `gitlab-etl` (container `metrics-gitlab-etl`)
e armazenados no banco `gitlab_metrics`.

---

## Seção: Merge Requests

### MRs Criados por Mês

Conta os Merge Requests abertos por mês, usando `created_at` como referência de data.

```sql
SELECT date_trunc('month', created_at) AS time,
       COUNT(*) AS "MRs Criados"
FROM gitlab_merge_requests
WHERE created_at BETWEEN $__timeFrom() AND $__timeTo()
GROUP BY 1 ORDER BY 1
```

**Interpretação:** Indica a cadência de desenvolvimento - quantos trabalhos novos foram submetidos
para revisão a cada mês. Picos podem refletir entregas próximas a deadlines.

---

### MRs Mergeados por Mês

Conta os MRs que chegaram ao estado `merged` por mês, usando `merged_at`.

**Interpretação:** Quando consistentemente abaixo de "MRs Criados", indica acúmulo de revisões
pendentes - sinal de gargalo no processo de code review.

---

### MRs por Autor - Volume e Ciclo

Tabela consolidada por autor com volume de MRs e tempo médio de ciclo (abertura até merge).

**Interpretação:** Ciclo médio alto pode indicar MRs grandes, falta de revisores ou dependências
externas que bloqueiam o merge.

---

## Seção: Tamanho de MRs

Média de arquivos alterados e linhas modificadas (additions + deletions) por MR, por autor.

**Interpretação:** MRs com mais de 500 linhas tendem a receber revisões superficiais, aumentando
o risco de bugs passarem despercebidos. Use como referência para definir limites de tamanho.

---

## Seção: Commits e Linhas de Código

Volume de commits e linhas modificadas por mês e por autor (adições, deleções, saldo líquido).

**Interpretação:** Não mede qualidade. Refatorações de limpeza podem ter alto volume sem entregar
funcionalidade nova. Saldo negativo geralmente indica refatoração ou limpeza.

---

## Seção: Code Review

### Participação em Code Review

Conta comentários feitos em MRs de outros autores. Não inclui auto-comentários.

**Como é construído:** Cruza a tabela `gitlab_mr_notes` com `gitlab_merge_requests` excluindo
registros onde `notes.author_username = mr.author_username`.

**Interpretação:** Baixa participação de alguns membros pode indicar silos de conhecimento ou
sobrecarga que impede engajamento em revisões.

---

### Tempo Médio de 1ª Resposta no Review

Tempo entre a abertura do MR e o primeiro comentário de qualquer outro autor, em horas.

**Interpretação:** Valores acima de 24h indicam que MRs ficam aguardando revisor por muito tempo,
o que aumenta o custo de context switch para o autor quando o feedback chegar.

---

## Seção: Taxa de Retrabalho

Proxy baseado em mensagens de commit. Classifica como retrabalho commits cujas mensagens
contêm: `fix`, `revert`, `bug`, `hotfix`, `correction`.

**Limitação:** Subestima retrabalho em times que não usam essas palavras nas mensagens de commit,
e pode superestimar em times que usam "fix" para ajustes normais. Use como indicador de tendência,
não como valor absoluto.

---

## Seção: Pipelines e CI/CD

### Taxa de Sucesso de Pipelines por Projeto

Por projeto: total de execuções, quantidade de sucesso, falha e percentual.

**Interpretação:** Projetos com taxa abaixo de 80% merecem atenção. Pode indicar testes frágeis,
infraestrutura instável ou merges que quebram a build com frequência.

---

### Pipelines por Status ao Longo dos Meses

Volume mensal de pipelines por status: `success`, `failed`, `canceled`.

**Interpretação:** Picos de `failed` podem indicar instabilidade introduzida por mudanças recentes.
Alta taxa de `canceled` pode indicar pipelines redundantes.
