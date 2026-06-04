---
title: Configuração
description: Tokens, variáveis de ambiente e ajustes opcionais.
---

Toda a configuração mora no `.env` na raiz do projeto. Copie do template e
preencha:

```bash
cp .env.example .env
```

## Variáveis principais

| Variável          | Descrição                                                |
|-------------------|----------------------------------------------------------|
| `GITLAB_URL`      | URL base do GitLab (ex: `https://gitlab.com`)            |
| `GITLAB_TOKEN`    | Personal Access Token do GitLab                          |
| `GITLAB_GROUP_ID` | ID numérico do grupo raiz no GitLab                      |
| `JIRA_URL`        | URL do Jira Cloud (ex: `https://your-team.atlassian.net`)|
| `JIRA_EMAIL`      | E-mail da conta Jira                                     |
| `JIRA_TOKEN`      | API Token do Jira                                        |
| `JIRA_PROJECTS`   | Chaves dos projetos separadas por vírgula                |

## Variáveis opcionais

| Variável                   | Padrão          | Descrição                                          |
|----------------------------|-----------------|----------------------------------------------------|
| `SYNC_INTERVAL_HOURS`      | `6`             | Intervalo entre syncs do GitLab                    |
| `JIRA_SYNC_INTERVAL_HOURS` | `4`             | Intervalo entre syncs do Jira                      |
| `HISTORY_DAYS`             | `365`           | Profundidade do sync inicial                       |
| `LOG_LEVEL`                | `INFO`          | `DEBUG`, `INFO`, `WARNING`                         |
| `JIRA_STORY_POINTS_FIELD`  | `story_points`  | Nome do campo de SP no Jira                        |
| `JIRA_ACTIVE_CATEGORIES`   | `indeterminate` | Categorias que contam como Action Time             |

## Token GitLab

1. Acesse **GitLab > User Settings > Access Tokens**
   - GitLab.com: <https://gitlab.com/-/user_settings/personal_access_tokens>
   - Self-hosted: `https://<sua-instancia>/-/user_settings/personal_access_tokens`
2. Crie um token com escopos: `api`, `read_repository`, `read_user`
3. Copie o valor para `GITLAB_TOKEN` no `.env`

Para encontrar o `GITLAB_GROUP_ID`: abra o grupo > **Settings > General**.
O ID numérico aparece abaixo do nome.

## Token Jira

1. Acesse <https://id.atlassian.com/manage-profile/security/api-tokens>
2. Clique em **Create API token**, dê um nome e copie o token
3. Cole em `JIRA_TOKEN`, preencha `JIRA_EMAIL` com a conta usada
4. Liste os projetos em `JIRA_PROJECTS` (ex: `ENG,OPS,PROD`)

## Desativando um coletor

Para usar só um dos dois (só GitLab ou só Jira), basta deixar **todas** as
variáveis do outro grupo em branco. O container do coletor desligado vai
logar "desativado" e dormir, sem causar restart loop.
