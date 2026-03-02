# 📜 Manifesto de Arquitetura: Copilot Financeiro Autônomo
**Versão:** V7.0 - *ASGI, FinOps & Defense-in-Depth*

## Visão Geral do Produto
O sistema é um Agente Financeiro Autônomo Multimodal, Interativo e Multidirecional. Opera de forma **stateless (sem estado)** em nuvem, compreendendo linguagem natural (texto, voz e imagens de cupons fiscais) para executar operações CRUD complexas. Introduz a mecânica de **Confirmação Interativa (Human-in-the-Loop)**, gerando rascunhos em cache e solicitando a aprovação do usuário via botões no Telegram, garantindo absoluta integridade dos dados para ingestão contábil no Looker Studio.

---

## 1. Stack Tecnológico (Infraestrutura Serverless Async)

* **Gateway & Interface:** Telegram Webhook API (suporte a Text, Voice, Photo e Callback Queries / Teclados Inline).
* **Computação Ponto-a-Ponto:** Google Cloud Run (Autoscaling de 0 a 1 instância, Serverless Lifecycle c/ CPU Zero-Cost em ociosidade).
  * **Conteinerização Explícita (AppSec/FinOps):** Deploy **estrito via Dockerfile**. Proibido depender de Cloud Native Buildpacks com Gunicorn para prevenir colapso de ambiente ASGI. Imagem base minimalista (`python:3.11-slim`), usuário não-root, e CMD forçado para `hypercorn`.
  * **Segurança de Limitação de Escala (FinOps Anti-Crash):** O serviço deve operar imutavelmente sob as regras `--max-instances=1` e `--concurrency=80`. Esta contenção blinda o Cloud Run Billing Free Tier contra falhas de boot sob estresse de milhões de *httpRequest* defeituosos.
  * **Geografia FinOps (Custo Zero Obrigatório):** O Deploy obrigatoriamente deve ocorrer na região `us-central1` (Iowa, EUA) ou equivalentes Tier 1 do GCP. Desdobramentos em regiões Tier 2 (como `southamerica-east1` - São Paulo) invalidam totalmente o Free Tier causando cobrança em cada invocação.
  * **Gestão de Dependências Fluidas (AppSec/Anti-Crash):** Bibliotecas Core (Quart, Hypercorn) devem usar pinning de evolução livre (`>=` ou `~=`) no `requirements.txt`. Proíbe-se a fixação estrita (`==`) de frameworks ASGI para evitar o empacotamento prolongado de CVEs (Vulnerabilidades) legadas e blindar o sistema contra quebras transitivas de API em pacotes base (ex: remoção de chaves no Werkzeug 3.0+).
* **Framework Core (ASGI):** `Quart` (Servidor Web Assíncrono Nativo) em tandem com `Hypercorn` ASGI Server, abolindo o legado do `Flask` + `Gunicorn`.
* **Pooling & I/O Network:** Cliente HTTPX Assíncrono (`httpx.AsyncClient`) gerenciado pelo Lifespan `@app.before_serving` com terminação de conexões atômicas.
* **Camadas de Persistência no Supabase (PostgreSQL):**
  * **Oficial:** Tabela `gastos`.
  * **Cache Stateless:** Tabela `cache_aprovacao` (retenção temporária via `pg_cron`).
  * **Idempotência (Zero-Read):** Tabela `webhook_idempotencia` intercepta nativamente duplicidades usando Unique Constraint ('23505') abolindo `SELECT` redundantes.
* **Orquestrador Cognitivo Híbrido (IA):**
  * **STT (Transcrição Audiovisual):** API Groq (modelo `whisper-large-v3`) encapsulado via `AsyncGroq`.
  * **OCR Semântico Inteligente:** API Google Gemini (`gemini-2.5-flash`). Lê notas na íntegra para extrair Itens.
  * **LLM Router (Cérebro Lógico):** API DeepSeek (`deepseek-chat`) via `AsyncOpenAI`. Forçado a formatação Strict JSON Object.

---

## 2. Padrão Architectural de Execução (FinOps Event-Driven Polling)

Para blindar o bot contra flutuações de custo no Cloud Run (evitando a política cara "CPU Always Allocated"), a infraestrutura de request atua como um "Event-Driven Callback":
1. O *Cloud Run* desperta nativamente via Webhook HTTP Request (Telegram).
2. O Quart atende envia instantaneamente o sinal "ChatAction (Typing / Upload)" e solta o processamento cognitivo bruto (`processar_update_assincrono`) na memória via recurso nativo ASGI `current_app.add_background_task()`.
3. O Request primário fecha c/ um `200 OK` (aplacando o Timeout do Telegram de <10s) enquanto a corrotina continua usando os recursos da Box até que termine de responder via Callback assíncrono. 

---

## 3. Contrato de Engenharia de Prompt e Governança de Dados

A IA atua estritamente como tradutor semântico e extrator de intenções. O *System Prompt* é blindado e seu contrato estrutural jamais pode perder linhas ou diretrizes. A IA tem a sua carga cognitiva reduzida (*Token Saving*) e a sua precisão aumentada através da intersecção com lógica de Backend.

* **Sincronização Temporal Geográfica:** Injeção do Horário de Brasília (UTC-3) no cabeçalho.
* **Cronologia Semântica (Fato Gerador):** O LLM calcula datas retroativas baseado no contexto temporal injetado (`data` vs `created_at`).
* **Mapeamento Determinístico (Golden Source):** A Natureza é extraída do LLM e mapeada através de dicionário algorítmico (`CATEGORIA_MAP`), forçando gravação exata.
* **Zero-Trust Category Enforcement:** Recusa e anula qualquer tentativa de criação livre, recuando para *Outros > Outros*.
* **Defesa Semântica:** Mapeamento ativo de bugs de extração comum de IA (ex: enviar "Gasto" transversal na categoria).
* **Expansão Cognitiva de Exclusão:** Esquema amplo para Soft-Delete via `filtros_exclusao`.

---

## 4. Delegação Matemática e Operações Base de Dados (Map-Reduce)

* **Matemática Híbrida e Guardrail de Descontos:** A prova real previne dupla dedução neutralizando descontos globais do somatório dos Itens do recibo na extração Gemini.
* **Roteador Cronológico Automático:** Fallback seguro para data do servidor se o Date parser colapsar.
* **Projeção de Parcelamentos (Centavo Exato):** Divisão de Float ajustando dízima com precisão cronológica.
* **Blindagem Zero-Trust de Exclusão (Anti-Truncate):** Exclusões ocorrem estritamente com validação array In_() evitando deletes sem cláusula de IDs fixos `WHERE`. Validação ASGI de falsos Typos Pydantic incluída em runtime.

---

## 5. AppSec e Blindagens de Engenharia

* **Zero-Leak Data Handling:** Manipulação de voice/photo delegada à lib nativa `tempfile.NamedTemporaryFile` do Sistema Operacional (OS Security e Permisson Management) garantindo apago após Garbage Collection do Python, suplantando strings com caminhos fixos (`/tmp/...`).
* **Masking de Variáveis Universais:** Tracebacks e Logs são higienizados por algoritmo que percorre iterativamente todas as variáveis globais (`REQUIRED_VARS`), protegendo tokens STT, LLM e Cloud Tokens.
* **Auditoria Localizada (Timezone Override):** Logging puro no `postgres`.
* **Idempotência de Webhook (Prevenção de Duplicidade):** Garantia de execução At-Least-Once-Exactly.