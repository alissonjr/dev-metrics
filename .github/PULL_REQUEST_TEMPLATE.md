<!--
Obrigado pela contribuição! Antes de enviar, leia CONTRIBUTING.md.
Preencha as seções abaixo — pode remover o que não se aplica.
-->

## O que muda

<!-- Resumo em 1-2 frases. Foco no porquê, não só no quê. -->

## Issue relacionada

<!-- Closes #123 / Refs #123 / N/A -->

## Tipo

- [ ] Bug fix
- [ ] Nova feature / dashboard / métrica
- [ ] Refactor (sem mudança de comportamento)
- [ ] Mudança de schema do banco
- [ ] Documentação
- [ ] Infra / CI

## Checklist

- [ ] `docker compose config --quiet` passa
- [ ] `python -m json.tool` valida todos os JSONs em `grafana/dashboards/`
- [ ] `ruff check gitlab-etl jira-etl` passa (se mexeu em Python)
- [ ] Subi a stack com `make up` e os dashboards afetados carregam sem erro
- [ ] Atualizei a documentação relevante (`README.md` ou `docs/*.md`)
- [ ] Se mudei o schema, descrevi como migrar dados existentes

## Como testar

<!-- Passos que um revisor pode seguir para validar a mudança. -->

## Screenshots / dados

<!-- Para dashboards: prints antes/depois. Para métricas: amostras das queries. -->
