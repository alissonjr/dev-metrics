# Metricas de Engenharia -- GitLab + Apache DevLake + Grafana + SonarQube

Guia completo para medir indicadores de performance de times de desenvolvimento usando GitLab self-hosted como fonte de dados, Apache DevLake como motor de coleta e transformacao, Grafana como dashboard e SonarQube como analise de qualidade de codigo.

**Objetivo:** Medir indicadores por desenvolvedor individual e por time/squad, para uso em PDIs, 1:1s e avaliacao de performance coletiva.

---

## Indice

1. [Arquitetura Geral](#1-arquitetura-geral)
2. [Instalacao e Configuracao](#2-instalacao-e-configuracao)
3. [Configuracao do GitLab](#3-configuracao-do-gitlab)
4. [Configuracao do DevLake](#4-configuracao-do-devlake)
5. [Configuracao do SonarQube](#5-configuracao-do-sonarqube)
6. [Padronizacao de MRs e Labels](#6-padronizacao-de-mrs-e-labels)
7. [Metricas Detalhadas e Queries](#7-metricas-detalhadas-e-queries)
8. [Dashboards por Desenvolvedor](#8-dashboards-por-desenvolvedor)
9. [Dashboards por Time](#9-dashboards-por-time)
10. [PDI e 1:1 -- Como Usar os Dados](#10-pdi-e-11----como-usar-os-dados)
11. [Links Uteis](#11-links-uteis)

---

## 1. Arquitetura Geral

```
GitLab Self-Hosted ──────┐
                         │
SonarQube ───────────────┼──> Apache DevLake ──> PostgreSQL/MySQL ──> Grafana
                         │
GitLab CI (pipelines) ───┘
```

**Fluxo de dados:**

1. DevLake coleta dados do GitLab via API (MRs, commits, issues, pipelines, reviews)
2. DevLake coleta dados do SonarQube via API (code smells, bugs, cobertura, duplicacao)
3. DevLake normaliza e armazena tudo em tabelas padronizadas (domain layer)
4. Grafana consulta essas tabelas para gerar dashboards e graficos
5. Voce filtra por desenvolvedor, por time, por repositorio e por periodo

---

## 2. Instalacao e Configuracao

### 2.1 Pre-requisitos

- Docker e Docker Compose instalados
- GitLab self-hosted (Community Edition 11+ ou Enterprise)
- Acesso de rede entre DevLake e GitLab (mesma rede ou VPN)
- Dominio ou IP fixo para DevLake e Grafana

### 2.2 Instalacao do Apache DevLake

```bash
# Clonar o repositorio do DevLake
git clone https://github.com/apache/incubator-devlake.git
cd incubator-devlake

# Copiar o arquivo de configuracao
cp env.example .env
```

Edite o `.env`:

```env
# Banco de dados do DevLake (pode ser MySQL ou PostgreSQL)
DB_URL=mysql://merico:merico@mysql:3306/lake?charset=utf8mb4&parseTime=True
# Porta da Config UI
DEVLAKE_PORT=8080
# Porta do Grafana
GRAFANA_PORT=3002
# Chave de encriptacao (gere uma aleatoria)
ENCRYPTION_SECRET=sua-chave-aleatoria-aqui
```

```bash
# Subir tudo com Docker Compose
docker compose up -d

# Verificar se esta rodando
docker compose ps
```

Apos subir, acesse:
- Config UI: http://localhost:8080
- Grafana: http://localhost:3002 (usuario: admin / senha: admin)

### 2.3 Instalacao do SonarQube

Se voce ainda nao tem um SonarQube rodando:

```bash
# docker-compose.sonarqube.yml
cat > docker-compose.sonarqube.yml << 'EOF'
version: "3.8"
services:
  sonarqube:
    image: sonarqube:lts-community
    container_name: sonarqube
    ports:
      - "9000:9000"
    environment:
      - SONAR_JDBC_URL=jdbc:postgresql://sonar-db:5432/sonar
      - SONAR_JDBC_USERNAME=sonar
      - SONAR_JDBC_PASSWORD=sonar
    volumes:
      - sonarqube_data:/opt/sonarqube/data
      - sonarqube_logs:/opt/sonarqube/logs
      - sonarqube_extensions:/opt/sonarqube/extensions
    depends_on:
      - sonar-db

  sonar-db:
    image: postgres:15
    container_name: sonar-db
    environment:
      - POSTGRES_USER=sonar
      - POSTGRES_PASSWORD=sonar
      - POSTGRES_DB=sonar
    volumes:
      - sonar_db_data:/var/lib/postgresql/data

volumes:
  sonarqube_data:
  sonarqube_logs:
  sonarqube_extensions:
  sonar_db_data:
EOF

docker compose -f docker-compose.sonarqube.yml up -d
```

Acesse http://localhost:9000 (usuario: admin / senha: admin).

### 2.4 Configuracao do SonarQube Scanner no GitLab CI

Adicione ao `.gitlab-ci.yml` de cada repositorio:

```yaml
sonarqube-check:
  stage: test
  image:
    name: sonarsource/sonar-scanner-cli:latest
    entrypoint: [""]
  variables:
    SONAR_HOST_URL: "http://seu-sonarqube:9000"
    SONAR_TOKEN: "${SONAR_TOKEN}"
    GIT_DEPTH: "0"
  script:
    - sonar-scanner
      -Dsonar.projectKey=${CI_PROJECT_PATH_SLUG}
      -Dsonar.projectName="${CI_PROJECT_NAME}"
      -Dsonar.sources=.
      -Dsonar.host.url=${SONAR_HOST_URL}
      -Dsonar.token=${SONAR_TOKEN}
      -Dsonar.qualitygate.wait=true
  allow_failure: true
  only:
    - merge_requests
    - main
    - develop
```

---

## 3. Configuracao do GitLab

### 3.1 Criar Personal Access Token

1. Acesse GitLab > User Settings > Access Tokens
2. Crie um token com os seguintes escopos:
   - `api` (acesso completo a API)
   - `read_repository`
   - `read_user`
3. Salve o token -- ele sera usado na configuracao do DevLake

**Para um token de grupo (recomendado para varios repos):**
1. Acesse o grupo > Settings > Access Tokens
2. Crie com role "Reporter" ou superior
3. Escopos: `api`, `read_repository`

### 3.2 Dados que o DevLake Coleta do GitLab

| Entidade | O que coleta |
|---|---|
| Merge Requests | Titulo, autor, reviewer, datas (criacao, merge, close), labels, linhas alteradas |
| MR Notes/Comments | Comentarios de review, timestamps |
| MR Commits | Commits vinculados a cada MR |
| Issues | Titulo, tipo, labels, assignee, datas, status |
| Pipelines | Jobs de CI/CD, status, duracao, timestamps |
| Commits | SHA, autor, data, additions, deletions, mensagem |

---

## 4. Configuracao do DevLake

### 4.1 Adicionar Conexao com GitLab

1. Abra Config UI: http://localhost:8080
2. Va em Connections > Add Connection > GitLab
3. Preencha:
   - **Connection Name:** GitLab Empresa
   - **Endpoint:** https://seu-gitlab.empresa.com/api/v4/
   - **Token:** o token criado no passo anterior
4. Teste a conexao e salve

### 4.2 Adicionar Conexao com SonarQube

1. Connections > Add Connection > SonarQube
2. Preencha:
   - **Connection Name:** SonarQube Empresa
   - **Endpoint:** http://seu-sonarqube:9000/api/
   - **Token:** token gerado em SonarQube > My Account > Security > Tokens

### 4.3 Criar Projeto no DevLake

1. Va em Projects > Add New Project
2. Nomeie o projeto (ex: "Time Backend", "Time Frontend")
3. Habilite DORA Metrics
4. Associe:
   - A conexao do GitLab com os repositorios do time
   - A conexao do SonarQube com os projetos correspondentes

### 4.4 Configurar Times e Membros

Esta e a parte mais importante para medir por time e por dev:

1. Va em Config UI > Settings > Teams (ou use a API)
2. Crie os times:
   ```
   Time Backend: dev1@empresa.com, dev2@empresa.com, dev3@empresa.com
   Time Frontend: dev4@empresa.com, dev5@empresa.com
   Time Mobile: dev6@empresa.com, dev7@empresa.com
   ```
3. O DevLake vai mapear automaticamente os autores de commits/MRs para seus respectivos times

**Via API (alternativa):**

```bash
# Criar time
curl -X POST http://localhost:8080/api/rest/plugins/org/teams \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Time Backend",
    "alias": "backend",
    "parentId": 0
  }'

# Associar membro ao time
curl -X POST http://localhost:8080/api/rest/plugins/org/teams/{team_id}/members \
  -H "Content-Type: application/json" \
  -d '{
    "userId": "account_id_do_dev",
    "name": "Nome do Dev"
  }'
```

### 4.5 Configurar Scope Config para DORA

Na tela de scope config de cada conexao GitLab, defina:

- **Deployment:** Padrao de nome do pipeline/job que representa deploy
  - Exemplo: `(?i)(deploy|release|publish)`
- **Incident:** Labels do GitLab que representam bugs/incidentes
  - Exemplo: issues com label `bug` ou `incident`

### 4.6 Agendar Coleta Automatica

No DevLake, apos criar o projeto, configure o Blueprint:

- **Frequencia:** A cada 6 horas (ou diariamente)
- **Tipo de sincronizacao:** Incremental (para GitLab suporta incremental para issues e MRs)

---

## 5. Configuracao do SonarQube

### 5.1 Quality Profile

Configure um Quality Profile para cada linguagem com regras que incluam:

- **Unused code** (codigo nao utilizado / dead code)
- **Code smells** gerais
- **Bugs** potenciais
- **Vulnerabilidades** de seguranca
- **Duplicacoes** de codigo

### 5.2 Quality Gate

Crie um Quality Gate customizado:

| Condicao | Operador | Valor |
|---|---|---|
| Coverage on New Code | menor que | 80% |
| Duplicated Lines on New Code | maior que | 3% |
| Maintainability Rating on New Code | pior que | A |
| Reliability Rating on New Code | pior que | A |
| Security Rating on New Code | pior que | A |

### 5.3 Tags de Regras Relevantes para Dead Code

No SonarQube, as regras que detectam "dead code" estao sob as tags:
- `unused` - codigo nao utilizado (variaveis, imports, metodos, classes)
- `dead-code` - codigo morto (blocos inalcancaveis)
- `clumsy` - codigo desnecessariamente complexo

Para filtrar issues de dead code na API:
```
GET /api/issues/search?tags=unused,dead-code&componentKeys=seu-projeto
```

---

## 6. Padronizacao de MRs e Labels

Para extrair dados de forma mais rica, padronize a forma como o time escreve MRs e usa labels.

### 6.1 Labels Obrigatorias nos MRs

Crie estas labels em cada repositorio do GitLab:

**Por tipo de mudanca:**
- `type::feature` - Nova funcionalidade
- `type::bugfix` - Correcao de bug
- `type::refactor` - Refatoracao
- `type::hotfix` - Correcao urgente em producao
- `type::chore` - Manutencao (deps, configs, CI)
- `type::docs` - Documentacao
- `type::test` - Testes

**Por time (se um repo e compartilhado entre times):**
- `team::backend`
- `team::frontend`
- `team::mobile`
- `team::devops`
- `team::data`

**Por prioridade:**
- `priority::critical`
- `priority::high`
- `priority::medium`
- `priority::low`

### 6.2 Template de MR no GitLab

Crie um arquivo `.gitlab/merge_request_templates/Default.md` em cada repo:

```markdown
## Descricao

[Descreva o que foi feito e por que]

## Tipo de mudanca

- [ ] Feature
- [ ] Bugfix
- [ ] Refactor
- [ ] Hotfix
- [ ] Chore

## Checklist

- [ ] Testes criados/atualizados
- [ ] Code review solicitado
- [ ] Documentacao atualizada (se aplicavel)
- [ ] Labels adicionadas (type::, team::)

## Issue relacionada

Closes #

## Screenshots (se aplicavel)
```

### 6.3 Template de Titulo de MR

Padronize os titulos para facilitar filtragem:

```
[TIPO] Descricao curta (#issue)
```

Exemplos:
- `[FEATURE] Adicionar filtro de busca por data (#123)`
- `[BUGFIX] Corrigir calculo de frete para regioes norte (#456)`
- `[REFACTOR] Extrair servico de notificacao (#789)`

### 6.4 Labels em Issues para Bugs

Para a metrica de "taxa de bugs" funcionar no DevLake, as issues de bug devem ter:
- Label `type::bug` ou `bug`
- Configurar no Scope Config do DevLake que `type::bug` = Bug type

---

## 7. Metricas Detalhadas e Queries

Todas as queries abaixo sao para uso no Grafana conectado ao banco do DevLake. O DevLake usa o schema `domain layer` com tabelas normalizadas.

### 7.1 Tempo Medio de Revisao de Codigo (PR Review Time)

**O que mede:** Tempo entre o primeiro comentario em um MR e o merge.

**Tabela no DevLake:** `project_pr_metrics` (campo `pr_review_time` em minutos)

**Fonte oficial:** https://devlake.apache.org/docs/Metrics/PRReviewTime

**Query -- Media mensal geral:**

```sql
SELECT
  DATE_FORMAT(pr.created_date, '%Y-%m') AS mes,
  ROUND(AVG(ppm.pr_review_time) / 60, 1) AS review_time_horas
FROM
  pull_requests pr
  JOIN project_pr_metrics ppm ON pr.id = ppm.id
WHERE
  $__timeFilter(pr.created_date)
  AND pr.base_repo_id IN ($repo_id)
GROUP BY 1
ORDER BY 1;
```

**Query -- Por desenvolvedor:**

```sql
SELECT
  pr.author_name AS desenvolvedor,
  COUNT(pr.id) AS total_mrs,
  ROUND(AVG(ppm.pr_review_time) / 60, 1) AS review_time_medio_horas,
  ROUND(MIN(ppm.pr_review_time) / 60, 1) AS review_time_min_horas,
  ROUND(MAX(ppm.pr_review_time) / 60, 1) AS review_time_max_horas
FROM
  pull_requests pr
  JOIN project_pr_metrics ppm ON pr.id = ppm.id
WHERE
  $__timeFilter(pr.created_date)
  AND pr.base_repo_id IN ($repo_id)
GROUP BY 1
ORDER BY 3 DESC;
```

**Query -- Por time (requer mapeamento de times no DevLake):**

```sql
SELECT
  t.name AS time,
  COUNT(pr.id) AS total_mrs,
  ROUND(AVG(ppm.pr_review_time) / 60, 1) AS review_time_medio_horas
FROM
  pull_requests pr
  JOIN project_pr_metrics ppm ON pr.id = ppm.id
  JOIN accounts a ON pr.author_id = a.id
  JOIN team_users tu ON a.id = tu.user_id
  JOIN teams t ON tu.team_id = t.id
WHERE
  $__timeFilter(pr.created_date)
GROUP BY 1
ORDER BY 3 DESC;
```

**Benchmarks de referencia:**
| Nivel | Review Time |
|---|---|
| Elite | Menos de 2 horas |
| Alto | 2 a 8 horas |
| Medio | 8 a 24 horas |
| Baixo | Mais de 24 horas |

---

### 7.2 Tempo de Ciclo (PR Cycle Time)

**O que mede:** Tempo total do primeiro commit ate o deploy, composto por:
- Coding Time (primeiro commit ate abrir o MR)
- Pickup Time (MR aberto ate primeiro review)
- Review Time (primeiro review ate aprovacao)
- Deploy Time (merge ate deploy em producao)

**Tabela no DevLake:** `project_pr_metrics` (campo `pr_cycle_time` em minutos)

**Fonte oficial:** https://devlake.apache.org/docs/Metrics/PRCycleTime

**Query -- Tendencia mensal:**

```sql
SELECT
  DATE_FORMAT(pr.created_date, '%Y-%m') AS mes,
  ROUND(AVG(ppm.pr_cycle_time) / 60, 1) AS cycle_time_horas,
  ROUND(AVG(ppm.pr_coding_time) / 60, 1) AS coding_time_horas,
  ROUND(AVG(ppm.pr_pickup_time) / 60, 1) AS pickup_time_horas,
  ROUND(AVG(ppm.pr_review_time) / 60, 1) AS review_time_horas,
  ROUND(AVG(ppm.pr_deploy_time) / 60, 1) AS deploy_time_horas
FROM
  pull_requests pr
  JOIN project_pr_metrics ppm ON pr.id = ppm.id
WHERE
  $__timeFilter(pr.created_date)
  AND pr.base_repo_id IN ($repo_id)
GROUP BY 1
ORDER BY 1;
```

**Query -- Por desenvolvedor (breakdown):**

```sql
SELECT
  pr.author_name AS desenvolvedor,
  COUNT(pr.id) AS total_mrs,
  ROUND(AVG(ppm.pr_cycle_time) / 60, 1) AS cycle_time_horas,
  ROUND(AVG(ppm.pr_coding_time) / 60, 1) AS coding_horas,
  ROUND(AVG(ppm.pr_pickup_time) / 60, 1) AS pickup_horas,
  ROUND(AVG(ppm.pr_review_time) / 60, 1) AS review_horas,
  ROUND(AVG(ppm.pr_deploy_time) / 60, 1) AS deploy_horas
FROM
  pull_requests pr
  JOIN project_pr_metrics ppm ON pr.id = ppm.id
WHERE
  $__timeFilter(pr.created_date)
  AND pr.base_repo_id IN ($repo_id)
GROUP BY 1
ORDER BY 3 DESC;
```

**Benchmarks de referencia:**
| Nivel | Cycle Time |
|---|---|
| Elite | Menos de 1 dia |
| Alto | 1 a 3 dias |
| Medio | 3 a 7 dias |
| Baixo | Mais de 7 dias |

---

### 7.3 Frequencia de Deploy

**O que mede:** Quantos deploys para producao sao feitos por periodo.

**Metrica DORA oficial.** Requer que os pipelines/jobs de deploy estejam configurados no Scope Config do DevLake.

**Fonte oficial:** https://devlake.apache.org/docs/Metrics/DeploymentFrequency

**Query -- Frequencia semanal:**

```sql
SELECT
  DATE_FORMAT(finished_date, '%Y-%u') AS semana,
  COUNT(*) AS deploys
FROM
  cicd_deployment_commits
WHERE
  $__timeFilter(finished_date)
  AND result = 'SUCCESS'
  AND environment = 'PRODUCTION'
GROUP BY 1
ORDER BY 1;
```

**Query -- Frequencia por repositorio:**

```sql
SELECT
  cdc.repo_url,
  DATE_FORMAT(cdc.finished_date, '%Y-%m') AS mes,
  COUNT(*) AS deploys
FROM
  cicd_deployment_commits cdc
WHERE
  $__timeFilter(cdc.finished_date)
  AND cdc.result = 'SUCCESS'
  AND cdc.environment = 'PRODUCTION'
GROUP BY 1, 2
ORDER BY 1, 2;
```

**Benchmarks DORA:**
| Nivel | Frequencia |
|---|---|
| Elite | Sob demanda (varias vezes ao dia) |
| Alto | Entre 1 vez por dia e 1 vez por semana |
| Medio | Entre 1 vez por semana e 1 vez por mes |
| Baixo | Menos de 1 vez por mes |

---

### 7.4 Tamanho Medio dos MRs (PR Size)

**O que mede:** Quantidade media de linhas alteradas (additions + deletions) por MR.

**Fonte oficial:** https://devlake.apache.org/docs/Metrics/PRSize

**Query -- Tendencia mensal:**

```sql
WITH _pr_sizes AS (
  SELECT
    DATE_FORMAT(pr.created_date, '%Y-%m') AS mes,
    pr.id AS pr_id,
    SUM(c.additions) + SUM(c.deletions) AS loc
  FROM
    pull_requests pr
    LEFT JOIN pull_request_commits prc ON pr.id = prc.pull_request_id
    LEFT JOIN commits c ON prc.commit_sha = c.sha
  WHERE
    $__timeFilter(pr.created_date)
    AND pr.base_repo_id IN ($repo_id)
  GROUP BY 1, 2
)
SELECT
  mes,
  ROUND(AVG(loc), 0) AS tamanho_medio_linhas,
  ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY loc), 0) AS mediana_linhas,
  COUNT(DISTINCT pr_id) AS total_mrs
FROM _pr_sizes
GROUP BY 1
ORDER BY 1;
```

**Query -- Por desenvolvedor:**

```sql
WITH _pr_sizes AS (
  SELECT
    pr.author_name AS desenvolvedor,
    pr.id AS pr_id,
    SUM(c.additions) + SUM(c.deletions) AS loc
  FROM
    pull_requests pr
    LEFT JOIN pull_request_commits prc ON pr.id = prc.pull_request_id
    LEFT JOIN commits c ON prc.commit_sha = c.sha
  WHERE
    $__timeFilter(pr.created_date)
    AND pr.base_repo_id IN ($repo_id)
  GROUP BY 1, 2
)
SELECT
  desenvolvedor,
  COUNT(DISTINCT pr_id) AS total_mrs,
  ROUND(AVG(loc), 0) AS tamanho_medio,
  MIN(loc) AS menor_mr,
  MAX(loc) AS maior_mr
FROM _pr_sizes
GROUP BY 1
ORDER BY 3 DESC;
```

**Benchmarks sugeridos:**
| Nivel | Linhas por MR |
|---|---|
| Otimo | Menos de 200 linhas |
| Bom | 200 a 400 linhas |
| Atencao | 400 a 800 linhas |
| Problema | Mais de 800 linhas |

---

### 7.5 Taxa de Retrabalho (Rework Rate)

**O que mede:** Porcentagem de codigo que e reescrito pouco tempo apos ser entregue. Indica falta de planejamento, requisitos mal definidos ou qualidade de review insuficiente.

**ATENCAO:** O DevLake NAO calcula essa metrica nativamente. Os dados necessarios existem nas tabelas (commits, commit_files, commit_line_change), mas o calculo precisa ser feito via query customizada.

**Query -- Taxa de retrabalho por desenvolvedor (arquivos alterados novamente em ate 14 dias):**

```sql
WITH recent_changes AS (
  -- Todos os arquivos alterados por cada dev nos commits mergeados
  SELECT
    c.author_name,
    cf.file_path,
    c.authored_date,
    c.sha
  FROM
    commits c
    JOIN commit_files cf ON c.sha = cf.commit_sha
  WHERE
    $__timeFilter(c.authored_date)
    AND c.message NOT LIKE 'Merge%'
),
rework AS (
  -- Arquivos onde o MESMO dev alterou novamente em ate 14 dias
  SELECT
    r1.author_name,
    r1.file_path,
    r1.authored_date AS primeira_alteracao,
    r2.authored_date AS segunda_alteracao
  FROM
    recent_changes r1
    JOIN recent_changes r2
      ON r1.author_name = r2.author_name
      AND r1.file_path = r2.file_path
      AND r2.authored_date > r1.authored_date
      AND DATEDIFF(r2.authored_date, r1.authored_date) <= 14
      AND r1.sha != r2.sha
)
SELECT
  rc.author_name AS desenvolvedor,
  COUNT(DISTINCT CONCAT(rc.file_path, rc.sha)) AS total_alteracoes,
  COUNT(DISTINCT CONCAT(rw.file_path, rw.primeira_alteracao)) AS alteracoes_retrabalhadas,
  ROUND(
    COUNT(DISTINCT CONCAT(rw.file_path, rw.primeira_alteracao)) * 100.0
    / NULLIF(COUNT(DISTINCT CONCAT(rc.file_path, rc.sha)), 0),
    1
  ) AS taxa_retrabalho_pct
FROM
  recent_changes rc
  LEFT JOIN rework rw
    ON rc.author_name = rw.author_name
    AND rc.file_path = rw.file_path
    AND rc.authored_date = rw.primeira_alteracao
GROUP BY 1
ORDER BY 4 DESC;
```

**Query -- Taxa de retrabalho mensal do time:**

```sql
WITH monthly_changes AS (
  SELECT
    DATE_FORMAT(c.authored_date, '%Y-%m') AS mes,
    c.author_name,
    cf.file_path,
    c.authored_date,
    c.sha
  FROM
    commits c
    JOIN commit_files cf ON c.sha = cf.commit_sha
  WHERE
    $__timeFilter(c.authored_date)
    AND c.message NOT LIKE 'Merge%'
),
rework AS (
  SELECT
    m1.mes,
    m1.file_path,
    m1.sha
  FROM
    monthly_changes m1
    JOIN monthly_changes m2
      ON m1.file_path = m2.file_path
      AND m2.authored_date > m1.authored_date
      AND DATEDIFF(m2.authored_date, m1.authored_date) <= 14
      AND m1.sha != m2.sha
)
SELECT
  mc.mes,
  COUNT(DISTINCT mc.sha) AS total_commits,
  COUNT(DISTINCT rw.sha) AS commits_retrabalhados,
  ROUND(
    COUNT(DISTINCT rw.sha) * 100.0 / NULLIF(COUNT(DISTINCT mc.sha), 0),
    1
  ) AS taxa_retrabalho_pct
FROM
  monthly_changes mc
  LEFT JOIN rework rw ON mc.sha = rw.sha AND mc.mes = rw.mes
GROUP BY 1
ORDER BY 1;
```

**Benchmarks sugeridos:**
| Nivel | Retrabalho |
|---|---|
| Saudavel | Menos de 10% |
| Atencao | 10% a 20% |
| Problema | 20% a 35% |
| Critico | Mais de 35% |

---

### 7.6 Dead Code (via SonarQube)

**O que mede:** Codigo existente no repositorio que nao e utilizado (variaveis, metodos, classes, imports nao referenciados).

**Fonte de dados:** SonarQube, coletado pelo DevLake nas tabelas `cq_issues` e `cq_file_metrics`.

**ATENCAO:** O DevLake NAO tem dashboard pronto para dead code. Ele importa os dados do SonarQube, mas voce precisa de queries customizadas.

**Query -- Total de issues de dead code por projeto:**

```sql
SELECT
  cqi.component,
  COUNT(*) AS total_dead_code_issues,
  SUM(CASE WHEN cqi.severity = 'MAJOR' THEN 1 ELSE 0 END) AS major,
  SUM(CASE WHEN cqi.severity = 'MINOR' THEN 1 ELSE 0 END) AS minor,
  SUM(CASE WHEN cqi.severity = 'INFO' THEN 1 ELSE 0 END) AS info
FROM
  cq_issues cqi
WHERE
  cqi.type = 'CODE_SMELL'
  AND (cqi.rule LIKE '%UnusedLocalVariable%'
    OR cqi.rule LIKE '%UnusedPrivateMethod%'
    OR cqi.rule LIKE '%UnusedImport%'
    OR cqi.rule LIKE '%UnusedPrivateField%'
    OR cqi.rule LIKE '%DeadStore%'
    OR cqi.rule LIKE '%unused%'
    OR cqi.rule LIKE '%dead%')
GROUP BY 1
ORDER BY 2 DESC;
```

**Query -- Tendencia mensal de code smells (inclui dead code):**

```sql
SELECT
  DATE_FORMAT(cqi.created_date, '%Y-%m') AS mes,
  COUNT(*) AS total_code_smells,
  SUM(CASE
    WHEN cqi.rule LIKE '%unused%' OR cqi.rule LIKE '%dead%'
    THEN 1 ELSE 0
  END) AS dead_code_issues
FROM
  cq_issues cqi
WHERE
  cqi.type = 'CODE_SMELL'
  AND $__timeFilter(cqi.created_date)
GROUP BY 1
ORDER BY 1;
```

**Complemento via API direta do SonarQube (para dados mais detalhados):**

```bash
# Dead code por projeto
curl -s "http://seu-sonarqube:9000/api/issues/search?\
tags=unused&\
componentKeys=seu-projeto&\
types=CODE_SMELL&\
ps=500" \
-H "Authorization: Bearer SEU_TOKEN" | jq '.total'

# Por arquivo
curl -s "http://seu-sonarqube:9000/api/measures/component_tree?\
component=seu-projeto&\
metricKeys=code_smells,bugs,vulnerabilities,duplicated_lines_density&\
qualifiers=FIL&\
ps=100&\
s=metric,name&\
metricSort=code_smells&\
asc=false" \
-H "Authorization: Bearer SEU_TOKEN"
```

---

### 7.7 Taxa de Bugs

**O que mede:** Quantidade de bugs por 1.000 linhas de codigo.

**Fonte oficial:** https://devlake.apache.org/docs/Metrics/BugCountPer1kLinesOfCode

**Pre-requisito:** Issues do GitLab com type ou label `bug` devem estar mapeadas no Scope Config do DevLake como "Bug".

**Query -- Tendencia mensal:**

```sql
WITH _line_of_code AS (
  SELECT
    DATE_FORMAT(authored_date, '%Y-%m') AS mes,
    SUM(additions + deletions) AS line_count
  FROM
    commits
  WHERE
    message NOT LIKE 'Merge%'
    AND $__timeFilter(authored_date)
  GROUP BY 1
),
_bug_count AS (
  SELECT
    DATE_FORMAT(created_date, '%Y-%m') AS mes,
    COUNT(*) AS bug_count
  FROM
    issues
  WHERE
    type = 'BUG'
    AND $__timeFilter(created_date)
  GROUP BY 1
)
SELECT
  loc.mes,
  COALESCE(bc.bug_count, 0) AS bugs,
  loc.line_count AS linhas_alteradas,
  ROUND(COALESCE(bc.bug_count, 0) * 1000.0 / NULLIF(loc.line_count, 0), 2)
    AS bugs_por_1k_linhas
FROM
  _line_of_code loc
  LEFT JOIN _bug_count bc ON bc.mes = loc.mes
ORDER BY 1;
```

**Query -- Bugs por desenvolvedor (baseado em assignee):**

```sql
SELECT
  i.assignee_name AS desenvolvedor,
  COUNT(*) AS total_bugs,
  SUM(CASE WHEN i.priority = 'CRITICAL' OR i.priority = 'HIGH' THEN 1 ELSE 0 END)
    AS bugs_criticos
FROM
  issues i
WHERE
  i.type = 'BUG'
  AND $__timeFilter(i.created_date)
GROUP BY 1
ORDER BY 2 DESC;
```

**Query -- Bugs por time:**

```sql
SELECT
  t.name AS time,
  COUNT(i.id) AS total_bugs,
  SUM(CASE WHEN i.status = 'DONE' THEN 1 ELSE 0 END) AS bugs_resolvidos,
  ROUND(
    SUM(CASE WHEN i.status = 'DONE' THEN 1 ELSE 0 END) * 100.0 / COUNT(i.id),
    1
  ) AS taxa_resolucao_pct
FROM
  issues i
  JOIN accounts a ON i.assignee_id = a.id
  JOIN team_users tu ON a.id = tu.user_id
  JOIN teams t ON tu.team_id = t.id
WHERE
  i.type = 'BUG'
  AND $__timeFilter(i.created_date)
GROUP BY 1
ORDER BY 2 DESC;
```

**Benchmarks sugeridos:**
| Nivel | Bugs/1k LOC |
|---|---|
| Excelente | Menos de 0.5 |
| Bom | 0.5 a 2.0 |
| Atencao | 2.0 a 5.0 |
| Critico | Mais de 5.0 |

---

## 8. Dashboards por Desenvolvedor

### 8.1 Painel Individual -- "Performance Card"

Crie um dashboard no Grafana com as seguintes variaveis:

```
Nome da variavel: developer
Tipo: Query
Query: SELECT DISTINCT author_name FROM pull_requests ORDER BY author_name
```

Paineis sugeridos para o dashboard individual:

| Painel | Tipo de grafico | Query base |
|---|---|---|
| MRs entregues (mes) | Stat/Counter | COUNT de PRs merged por $developer |
| Cycle Time medio | Gauge | AVG(pr_cycle_time) do $developer |
| Review Time medio | Gauge | AVG(pr_review_time) do $developer |
| Tamanho medio dos MRs | Gauge | AVG de linhas por PR do $developer |
| Bugs atribuidos | Stat/Counter | COUNT issues type=BUG assignee=$developer |
| Taxa de retrabalho | Gauge | Query customizada de retrabalho para $developer |
| Commits por semana | Time series | COUNT commits por semana do $developer |
| Evolucao do Cycle Time | Time series | Tendencia mensal do cycle time do $developer |

### 8.2 Exemplo de Query para o Card Individual

```sql
-- Resumo do trimestre para um dev
SELECT
  pr.author_name,
  COUNT(DISTINCT pr.id) AS mrs_mergeados,
  ROUND(AVG(ppm.pr_cycle_time) / 60, 1) AS cycle_time_medio_h,
  ROUND(AVG(ppm.pr_review_time) / 60, 1) AS review_time_medio_h,
  ROUND(AVG(ppm.pr_pickup_time) / 60, 1) AS pickup_time_medio_h,
  (SELECT COUNT(*) FROM issues i
   WHERE i.assignee_name = pr.author_name
   AND i.type = 'BUG'
   AND $__timeFilter(i.created_date)) AS bugs_atribuidos
FROM
  pull_requests pr
  JOIN project_pr_metrics ppm ON pr.id = ppm.id
WHERE
  pr.author_name = '$developer'
  AND $__timeFilter(pr.created_date)
  AND pr.merged_date IS NOT NULL
GROUP BY 1;
```

---

## 9. Dashboards por Time

### 9.1 Painel de Time -- "Squad Health"

Variavel Grafana:

```
Nome: team
Tipo: Query
Query: SELECT DISTINCT name FROM teams ORDER BY name
```

Paineis sugeridos:

| Painel | Descricao |
|---|---|
| Throughput do Time | Total de MRs mergeados por semana/mes |
| Cycle Time do Time | Media e mediana de cycle time |
| DORA -- Deploy Frequency | Deploys por semana |
| DORA -- Change Failure Rate | % de deploys que causaram incidente |
| Tamanho medio dos MRs | Media de linhas alteradas |
| Bugs abertos vs resolvidos | Tendencia mensal |
| Code Smells (SonarQube) | Total e tendencia |
| Dead Code | Issues de codigo nao utilizado |
| Ranking de desenvolvedores | Tabela com metricas de cada dev do time |

### 9.2 Comparativo Entre Times

```sql
SELECT
  t.name AS time,
  COUNT(DISTINCT pr.id) AS mrs_mergeados,
  ROUND(AVG(ppm.pr_cycle_time) / 60, 1) AS cycle_time_h,
  ROUND(AVG(ppm.pr_review_time) / 60, 1) AS review_time_h,
  COUNT(DISTINCT CASE WHEN i.type = 'BUG' THEN i.id END) AS bugs
FROM
  teams t
  JOIN team_users tu ON t.id = tu.team_id
  JOIN accounts a ON tu.user_id = a.id
  LEFT JOIN pull_requests pr ON a.id = pr.author_id
    AND pr.merged_date IS NOT NULL
    AND $__timeFilter(pr.created_date)
  LEFT JOIN project_pr_metrics ppm ON pr.id = ppm.id
  LEFT JOIN issues i ON a.id = i.assignee_id
    AND i.type = 'BUG'
    AND $__timeFilter(i.created_date)
GROUP BY 1
ORDER BY 2 DESC;
```

---

## 10. PDI e 1:1 -- Como Usar os Dados

### 10.1 Metricas Recomendadas por Objetivo de PDI

| Objetivo do PDI | Metricas para acompanhar |
|---|---|
| Melhorar qualidade de codigo | Taxa de bugs, code smells, dead code, cobertura de testes |
| Aumentar velocidade de entrega | Cycle time, coding time, PR size |
| Melhorar colaboracao | Review time (como reviewer), quantidade de reviews feitos, pickup time |
| Reduzir retrabalho | Taxa de retrabalho, taxa de bugs de regressao |
| Consistencia | Frequencia de commits, MRs por sprint, coding days |

### 10.2 Modelo de Relatorio para 1:1

Para cada desenvolvedor, gere um snapshot mensal com:

```
RELATORIO MENSAL -- [Nome do Dev] -- [Mes/Ano]

VOLUME DE ENTREGAS
- MRs mergeados: X (mes anterior: Y) [variacao: +Z%]
- Commits: X
- Linhas alteradas: X

QUALIDADE
- Bugs atribuidos: X (criticos: Y)
- Taxa de retrabalho: X%
- Tamanho medio dos MRs: X linhas

VELOCIDADE
- Cycle Time medio: X horas (meta: < Y horas)
- Review Time medio: X horas
- Pickup Time medio: X horas

CONTRIBUICAO PARA O TIME
- Reviews realizados: X
- Tempo medio como reviewer: X horas

EVOLUCAO (vs mes anterior)
- Cycle Time: [melhorou/piorou] X%
- Bugs: [melhorou/piorou] X%
- Retrabalho: [melhorou/piorou] X%
```

### 10.3 Query para Gerar Relatorio do 1:1

```sql
WITH dev_metrics AS (
  SELECT
    pr.author_name,
    DATE_FORMAT(pr.created_date, '%Y-%m') AS mes,
    COUNT(DISTINCT pr.id) AS mrs_mergeados,
    ROUND(AVG(ppm.pr_cycle_time) / 60, 1) AS cycle_time_h,
    ROUND(AVG(ppm.pr_review_time) / 60, 1) AS review_time_h,
    ROUND(AVG(ppm.pr_pickup_time) / 60, 1) AS pickup_time_h
  FROM
    pull_requests pr
    JOIN project_pr_metrics ppm ON pr.id = ppm.id
  WHERE
    pr.author_name = '$developer'
    AND pr.merged_date IS NOT NULL
  GROUP BY 1, 2
),
dev_bugs AS (
  SELECT
    i.assignee_name AS author_name,
    DATE_FORMAT(i.created_date, '%Y-%m') AS mes,
    COUNT(*) AS bugs
  FROM issues i
  WHERE i.type = 'BUG' AND i.assignee_name = '$developer'
  GROUP BY 1, 2
)
SELECT
  dm.mes,
  dm.mrs_mergeados,
  dm.cycle_time_h,
  dm.review_time_h,
  dm.pickup_time_h,
  COALESCE(db.bugs, 0) AS bugs
FROM
  dev_metrics dm
  LEFT JOIN dev_bugs db ON dm.author_name = db.author_name AND dm.mes = db.mes
ORDER BY dm.mes DESC
LIMIT 6;
```

### 10.4 Cuidados ao Usar Metricas em Avaliacoes

- NUNCA use uma metrica isolada para avaliar performance.
- MRs pequenos nao significam necessariamente melhor trabalho -- o contexto importa.
- Cycle time alto pode ser problema de processo (review lento) e nao do dev.
- Bugs sao naturais -- o importante e a tendencia, nao o numero absoluto.
- Compare o dev com ele mesmo ao longo do tempo, nao com outros devs.
- Use os dados para CONVERSAR, nao para punir. O objetivo e desenvolvimento.
- Considere o tipo de trabalho: refatoracao gera mais retrabalho que feature nova.

---

## 11. Links Uteis

### Documentacao Oficial

| Recurso | URL |
|---|---|
| DevLake - Docs | https://devlake.apache.org/docs/Overview |
| DevLake - Metricas | https://devlake.apache.org/docs/Metrics |
| DevLake - DORA | https://devlake.apache.org/docs/DORA |
| DevLake - Data Sources | https://devlake.apache.org/docs/Overview/SupportedDataSources |
| DevLake - Domain Layer Schema | https://devlake.apache.org/docs/DataModels/DevLakeDomainLayerSchema |
| DevLake - GitLab Plugin | https://devlake.apache.org/docs/Plugins/gitlab |
| DevLake - SonarQube Plugin | https://devlake.apache.org/docs/Plugins/sonarqube |
| DevLake - How to Organize Projects | https://devlake.apache.org/docs/Configuration/HowToOrganizeDevlakeProjects |
| DevLake - Grafana Guide | https://devlake.apache.org/docs/Configuration/Dashboards/GrafanaUserGuide |
| SonarQube - Docs | https://docs.sonarsource.com/sonarqube/latest/ |
| SonarQube - Web API | https://docs.sonarsource.com/sonarqube/latest/extension-guide/web-api/ |
| GitLab API | https://docs.gitlab.com/ee/api/ |

### Repositorios

| Recurso | URL |
|---|---|
| DevLake GitHub | https://github.com/apache/incubator-devlake |
| DevLake Grafana Dashboards | https://github.com/apache/incubator-devlake/tree/main/grafana |
| DevLake Live Demo | https://grafana-lake.demo.devlake.io |

### Comunidade

| Recurso | URL |
|---|---|
| DevLake Slack | https://join.slack.com/t/devlake-io/shared_invite/zt-1lkgbdmys-AU2azidzO1u~mtjlg9my7A |
| DevLake Issues | https://github.com/apache/incubator-devlake/issues |

---

## Apendice: Resumo das Metricas

| Metrica | Fonte | Nativo no DevLake | Precisa de query customizada | Precisa de SonarQube |
|---|---|---|---|---|
| Tempo de revisao | GitLab MRs | Sim | Nao | Nao |
| Tempo de ciclo | GitLab MRs + CI | Sim | Nao | Nao |
| Frequencia de deploy | GitLab CI | Sim | Nao | Nao |
| Tamanho dos MRs | GitLab MRs | Sim | Nao | Nao |
| Taxa de retrabalho | GitLab commits | Nao | Sim | Nao |
| Dead code | SonarQube | Nao | Sim | Sim |
| Taxa de bugs | GitLab issues | Sim | Nao | Nao |
| Por desenvolvedor | GitLab | Parcial | Sim (queries com filtro author_name) | - |
| Por time | DevLake Teams | Parcial | Sim (queries com JOIN teams) | - |
