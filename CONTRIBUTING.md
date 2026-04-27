# Contribuindo

Obrigado pelo interesse em contribuir! Este guia descreve como propor mudanças
no `dev-metrics`. Toda a comunicação do projeto é em português (BR), mas PRs em
inglês também são bem-vindos.

## Formas de contribuir

- **Reportar bugs** — abra uma [issue](../../issues/new/choose) usando o
  template de bug e inclua passos para reproduzir.
- **Sugerir melhorias** — abra uma issue de feature descrevendo o problema que
  motiva a mudança, não só a solução desejada.
- **Adicionar dashboards** — basta um JSON novo em
  `grafana/dashboards/Engineering/` ou `grafana/dashboards/Operations/`. Eles
  são provisionados automaticamente.
- **Estender os coletores** — adicione campos/tabelas em
  `gitlab-etl/` ou `jira-etl/`. Lembre-se de atualizar o `schema.sql`
  correspondente.
- **Melhorar a documentação** — `docs/*.md` descrevem cada painel; correções e
  exemplos extras ajudam muito.

## Setup local

```bash
# 1. Fork + clone
git clone https://github.com/<seu-fork>/dev-metrics.git
cd dev-metrics

# 2. Configure as credenciais (use uma conta GitLab/Jira de teste se possível)
cp .env.example .env
${EDITOR:-vi} .env

# 3. Suba a stack
make up

# 4. Acompanhe a coleta
make logs-gitlab
make logs-jira
```

Para iterar rápido em mudanças nos coletores, rebuild e reinicie só o serviço
afetado:

```bash
docker compose build gitlab-etl && docker compose up -d gitlab-etl
```

## Antes de abrir o PR

Rode estas verificações localmente. O CI roda as mesmas:

```bash
# JSON dos dashboards é válido
find grafana/dashboards -name '*.json' -exec python -m json.tool {} \; > /dev/null

# docker-compose.yml é válido
docker compose config --quiet

# Lint Python (opcional, mas recomendado)
pip install ruff
ruff check gitlab-etl jira-etl
```

Confirme também que:

- Os containers sobem com `make up` sem erros
- Os dashboards carregam em `http://localhost:3000` sem painéis quebrados
- O coletor afetado completa pelo menos um ciclo (`make logs-<gitlab|jira>`)

## Padrão de PR

- Um PR por mudança lógica — evite misturar refactor com nova feature
- Descreva o **porquê** da mudança, não só o **o quê** (o diff já mostra o quê)
- Atualize a documentação relevante em `docs/` ou no `README.md` quando o
  comportamento muda
- Se a mudança altera o schema do banco, mencione no PR como migrar (ou
  adicione um script `ALTER TABLE`)

Mensagens de commit em PT ou EN são aceitas. Prefira o formato:

```
área: resumo curto no imperativo

Detalhes opcionais sobre a motivação e impacto.
```

Exemplos de área: `gitlab-etl`, `jira-etl`, `grafana`, `docs`, `ci`,
`docker`, `makefile`.

## Reportando vulnerabilidades

**Não** abra issue pública para falhas de segurança. Veja
[`SECURITY.md`](SECURITY.md) para o canal correto.

## Licença

Ao abrir um PR, você concorda em licenciar sua contribuição sob os mesmos
termos do projeto: [MIT](LICENSE).
