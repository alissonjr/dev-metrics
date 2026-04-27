# Comparacao de Solucoes de Revisao de MR com IA no GitLab Self-Hosted

---

## Resumo Executivo

Este relatorio compara tres abordagens para integrar revisao automatizada de Merge Requests com Inteligencia Artificial em um GitLab self-hosted, utilizando documentacao de boas praticas como base de avaliacao.

| Criterio | GitLab Duo | Webhook + LLM Proprio | Ferramentas Open Source |
|---|---|---|---|
| Custo mensal estimado | $$$$ (alto) | $$ (moderado) | $ a $$$ (variavel) |
| Dificuldade de implementacao | Baixa | Media-Alta | Media |
| Personalizacao | Limitada | Total | Parcial |
| Manutencao | Nenhuma | Alta | Media |
| Time-to-value | Rapido | Lento | Medio |

---

## 1. GitLab Duo (Nativo)

### Descricao

Funcionalidade nativa do GitLab disponivel a partir da versao 16.x com licenca Ultimate. Oferece sugestoes de codigo, resumo de MRs e revisao automatizada diretamente na interface do GitLab.

### Requisitos

- GitLab 16.6+ (idealmente 17.x+)
- Licenca GitLab Ultimate (obrigatoria)
- AI Gateway configurado (self-hosted ou cloud)
- Conexao com provedores de modelo (Google Vertex AI ou Anthropic via GitLab)

### Custos

| Item | Custo Estimado |
|---|---|
| Licenca GitLab Ultimate | ~$99/usuario/mes (minimo) |
| AI Gateway self-hosted | Infraestrutura propria (servidor dedicado) |
| Tokens de LLM (via GitLab) | Incluido na licenca Ultimate (com limites) |
| **Total para 10 devs** | **~$990 a $1.200/mes** |

Nota: O preco da licenca Ultimate costuma ser negociado para times maiores, mas o piso e alto para equipes pequenas.

### Vantagens

- Zero desenvolvimento necessario -- ja vem integrado ao GitLab
- Interface nativa: comentarios aparecem diretamente no diff do MR
- Atualizacoes automaticas com novas versoes do GitLab
- Suporte oficial da GitLab Inc.
- Funcionalidades adicionais incluidas (code suggestions, chat, vulnerability detection)
- Sem necessidade de manter infraestrutura adicional (se usar cloud gateway)

### Desvantagens

- **Custo proibitivo para equipes pequenas** -- licenca Ultimate e a mais cara
- **Personalizacao extremamente limitada** -- nao aceita documentacao customizada de boas praticas como contexto
- Depende de modelos escolhidos pela GitLab (sem controle sobre qual LLM e usado)
- AI Gateway self-hosted exige recursos computacionais significativos (GPU ou API keys proprias)
- No modo cloud, dados do codigo saem do ambiente self-hosted (problema de compliance)
- Nem todas as funcionalidades de IA estao disponiveis para self-hosted (algumas sao SaaS-only)
- Lock-in total na plataforma GitLab

### Dificuldade de Implementacao: 2/10

Basta ativar a feature flag e configurar o AI Gateway. Documentacao oficial disponivel.

---

## 2. Webhook + LLM Proprio (Solucao Custom)

### Descricao

Servico customizado que escuta eventos de Merge Request via webhook, busca o diff pela API do GitLab, monta um prompt com o diff + documentacao de boas praticas, envia para uma LLM e posta o resultado como comentario no MR.

### Arquitetura

```
GitLab MR Event
      |
      v
  Webhook (POST)
      |
      v
  Seu Servico (Python/Node/Go)
      |
      +---> GitLab API: GET /projects/:id/merge_requests/:iid/changes
      |
      +---> Monta prompt: diff + docs de boas praticas
      |
      +---> Envia para LLM (OpenAI / Claude / Ollama)
      |
      +---> GitLab API: POST /projects/:id/merge_requests/:iid/notes
      |
      v
  Comentario no MR com avaliacao
```

### Requisitos

- Servidor para hospedar o servico (pode ser container Docker)
- Acesso a API do GitLab (token com scope `api`)
- Acesso a uma LLM (API externa ou modelo local)
- Documentacao de boas praticas em formato texto

### Custos

**Opcao A: LLM via API (OpenAI/Claude)**

| Item | Custo Estimado |
|---|---|
| Servidor (container pequeno) | ~$5 a $20/mes |
| OpenAI GPT-4o (input+output) | ~$0.01 a $0.05 por MR review |
| Claude 3.5 Sonnet (input+output) | ~$0.01 a $0.04 por MR review |
| **Total para ~200 MRs/mes** | **~$10 a $30/mes** |

**Opcao B: LLM local (Ollama com Llama 3 / Mistral / DeepSeek)**

| Item | Custo Estimado |
|---|---|
| Servidor com GPU (ex: 16GB VRAM) | ~$50 a $150/mes (cloud) ou hardware proprio |
| Modelo local | Gratuito |
| **Total** | **~$50 a $150/mes (sem custo por token)** |

**Opcao C: LLM local sem GPU (modelos quantizados)**

| Item | Custo Estimado |
|---|---|
| Servidor CPU (8GB+ RAM) | ~$10 a $30/mes |
| Modelo quantizado (Mistral 7B Q4) | Gratuito |
| **Total** | **~$10 a $30/mes** |

Nota: A qualidade da Opcao C e inferior, mas funcional para revisoes basicas.

### Vantagens

- **Personalizacao total** -- voce define exatamente o prompt, o contexto e os criterios
- **Custo muito baixo** com APIs externas (~$0.02 por review)
- Pode injetar sua documentacao de boas praticas como contexto do prompt
- Total controle sobre qual modelo usar (pode trocar a qualquer momento)
- Dados podem ficar 100% internos (com modelo local)
- Pode evoluir para funcionalidades avancadas:
  - Analise de seguranca
  - Verificacao de padroes de arquitetura
  - Sugestoes de testes faltantes
  - Score de qualidade do MR
- Independente da versao do GitLab (funciona com qualquer versao que suporte webhooks)

### Desvantagens

- **Maior esforco de desenvolvimento** -- precisa criar e manter o servico
- Responsabilidade total pela disponibilidade e manutencao
- Precisa tratar edge cases: MRs muito grandes, timeouts, rate limiting
- Engenharia de prompt requer iteracao para obter boas revisoes
- Sem interface grafica para configuracao (tudo via codigo/config)
- Precisa implementar logica de retry, filas e tratamento de erros
- Modelo local exige tuning e pode ter qualidade inferior a APIs pagas

### Dificuldade de Implementacao: 6/10

Desenvolvimento estimado de 2-4 dias para um MVP funcional, mais 1-2 semanas para robustez (filas, retry, logs, configuracao de prompts).

### Stack Sugerida

```
Runtime:        Python 3.12+ (FastAPI) ou Node.js (Express)
Fila:           Redis + Celery (Python) ou BullMQ (Node)
LLM:            LiteLLM (wrapper universal para qualquer LLM)
Deploy:         Docker container
Monitoramento:  Logs estruturados + metricas de custo por review
```

---

## 3. Ferramentas Open Source e SaaS

### 3.1 DangerJS + LLM

**Descricao:** DangerJS e uma ferramenta de automacao de CI que roda no pipeline do MR e pode executar regras customizadas. Combinado com chamadas a LLM, pode fazer revisao inteligente.

**Custos:**
| Item | Custo Estimado |
|---|---|
| DangerJS | Gratuito (open source) |
| Tempo de CI runner | Incluido no GitLab CI existente |
| Chamadas LLM | ~$0.01 a $0.05 por MR |
| **Total** | **~$5 a $15/mes** |

**Vantagens:**
- Roda dentro do pipeline de CI (sem infra adicional)
- Combina regras deterministicas (lint, tamanho de MR) com analise de IA
- Comunidade ativa e boa documentacao
- Facil de comecar com regras simples e adicionar IA depois

**Desvantagens:**
- Precisa de `Dangerfile` com logica customizada
- Integracao com LLM precisa ser codificada manualmente
- Roda apenas quando o pipeline executa (nao em tempo real)
- Limitado ao contexto do diff (nao tem acesso facil ao repositorio completo)

**Dificuldade: 4/10**

### 3.2 AI Code Reviewer (Open Source)

**Descricao:** Projeto open source que conecta GitLab a provedores de LLM para revisao automatica.

**Custos:**
| Item | Custo Estimado |
|---|---|
| Ferramenta | Gratuita |
| Servidor | ~$5 a $10/mes |
| API LLM | ~$0.01 a $0.05 por MR |
| **Total** | **~$10 a $20/mes** |

**Vantagens:**
- Ja implementa a logica de webhook + API do GitLab
- Reduz tempo de desenvolvimento significativamente
- Suporta multiplos provedores de LLM

**Desvantagens:**
- Projetos menores com manutencao incerta (risco de abandono)
- Personalizacao de prompts pode ser limitada
- Menos controle sobre o fluxo completo
- Pode nao suportar injecao de documentacao customizada sem fork

**Dificuldade: 3/10**

### 3.3 CodeRabbit (SaaS)

**Descricao:** Plataforma SaaS especializada em revisao de codigo com IA. Suporta GitLab self-hosted.

**Custos:**
| Item | Custo Estimado |
|---|---|
| Plano Pro | ~$15/usuario/mes |
| **Total para 10 devs** | **~$150/mes** |

**Vantagens:**
- Produto maduro e especializado em code review
- Suporta GitLab self-hosted oficialmente
- Interface web para configuracao de regras e preferencias
- Aprende com feedback do time ao longo do tempo
- Suporta arquivos de instrucao customizados (`.coderabbit.yaml`)

**Desvantagens:**
- Dados do codigo saem para servidores externos (compliance)
- Custo cresce linearmente com o numero de desenvolvedores
- Dependencia de terceiro (risco de mudanca de precos/termos)
- Personalizacao limitada ao que a plataforma oferece
- Nao permite usar documentacao propria como base de avaliacao de forma profunda

**Dificuldade: 2/10**

---

## Matriz de Comparacao Detalhada

| Criterio | GitLab Duo | Webhook + LLM | DangerJS + LLM | AI Code Reviewer | CodeRabbit |
|---|---|---|---|---|---|
| **Custo mensal (10 devs, 200 MRs)** | ~$1.000+ | ~$15-30 | ~$5-15 | ~$10-20 | ~$150 |
| **Dificuldade implementacao** | 2/10 | 6/10 | 4/10 | 3/10 | 2/10 |
| **Personalizacao de criterios** | Baixa | Total | Alta | Media | Media |
| **Uso de docs proprias como contexto** | Nao | Sim | Sim (com codigo) | Limitado | Parcial |
| **Dados ficam internos** | Parcial | Sim (com LLM local) | Sim (com LLM local) | Sim (com LLM local) | Nao |
| **Manutencao necessaria** | Nenhuma | Alta | Media | Media | Nenhuma |
| **Qualidade da revisao** | Boa | Depende do modelo/prompt | Depende do modelo/prompt | Depende do modelo | Muito boa |
| **Escalabilidade** | Alta | Alta | Alta | Media | Alta |
| **Risco de lock-in** | Alto | Nenhum | Baixo | Baixo | Medio |
| **Tempo para estar operacional** | 1 dia | 1-2 semanas | 2-3 dias | 1-2 dias | 1 dia |
| **Suporta qualquer versao GitLab** | Nao (16.6+) | Sim | Sim | Sim | Sim |
| **Evolucao/extensibilidade** | Depende da GitLab | Total | Alta | Precisa de fork | Limitada |

---

## Recomendacao por Cenario

### Cenario 1: Equipe pequena (3-5 devs), orcamento limitado

**Recomendado: DangerJS + LLM (OpenAI/Claude)**

- Custo quase zero (~$10/mes)
- Roda no CI existente sem infra adicional
- Permite injetar documentacao de boas praticas no prompt
- Facil de comecar e evoluir incrementalmente

### Cenario 2: Equipe media (5-15 devs), compliance de dados importante

**Recomendado: Webhook + LLM Proprio (com Ollama local)**

- Dados nunca saem do ambiente
- Personalizacao total dos criterios de revisao
- Custo fixo independente do numero de MRs
- Maior investimento inicial, mas retorno a longo prazo

### Cenario 3: Equipe grande (15+ devs), velocidade de adocao e prioridade

**Recomendado: CodeRabbit**

- Produto maduro, pronto para uso imediato
- Custo previsivel por desenvolvedor
- Boa qualidade de revisao sem esforco de engenharia
- Aceita configuracao via arquivo no repositorio

### Cenario 4: Ja possui licenca GitLab Ultimate

**Recomendado: GitLab Duo + Webhook customizado complementar**

- Aproveita o que ja esta pago
- Complementa com webhook proprio para criterios customizados baseados na documentacao do time

---

## Conclusao

Para o objetivo especifico de **avaliar MRs com base em documentacao propria de boas praticas**, a opcao **Webhook + LLM Proprio** e a que oferece melhor custo-beneficio e personalizacao total. Permite montar prompts que incluem integralmente o documento de boas praticas como contexto, garantindo que a revisao siga exatamente os criterios definidos pelo time.

Se tempo de implementacao for critico, **DangerJS + LLM** oferece um meio-termo excelente: roda no CI sem infra adicional, permite personalizacao de prompt com as docs do time e pode ser implementado em poucos dias.

A opcao **GitLab Duo** so se justifica se a licenca Ultimate ja estiver contratada por outros motivos, e mesmo assim nao permite injetar documentacao customizada como criterio de avaliacao.
