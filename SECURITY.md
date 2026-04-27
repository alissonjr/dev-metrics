# Política de Segurança

## Versões suportadas

Apenas a branch `main` recebe correções de segurança. O projeto não emite
releases versionadas — sempre rode a partir do último commit estável.

## Reportando uma vulnerabilidade

Se você encontrou uma falha de segurança, **não abra uma issue pública**.

Por favor, use o canal privado do GitHub:

1. Acesse a aba **Security** do repositório
2. Clique em **Report a vulnerability**
3. Descreva a falha, o impacto e, se possível, passos para reproduzir

Caso prefira e-mail, envie para o mantenedor listado no `git log` (busque o
autor da maioria dos commits recentes).

## O que esperar

- Confirmação de recebimento em até 7 dias corridos
- Avaliação inicial e plano de correção em até 30 dias
- Crédito público no anúncio da correção, se você desejar

Por se tratar de um projeto self-hosted que processa dados internos da sua
organização, o impacto de uma falha geralmente é local — mas tokens
expostos em logs, dumps ou queries SQL injetadas no Grafana são exemplos
de problemas que merecem report privado.

## Boas práticas para quem usa o projeto

- **Nunca commite o `.env`** — o `.gitignore` já bloqueia, mas confira
- **Rotacione tokens** GitLab/Jira após qualquer suspeita de vazamento
- **Não exponha o Grafana publicamente** sem TLS e autenticação reforçada;
  o setup padrão (porta 3000, admin/admin) é só para uso local
- **Não publique o `db/dump.sql`** — ele contém dados de issues, MRs e
  commits que podem ser sensíveis. O `.gitignore` já bloqueia o arquivo.
