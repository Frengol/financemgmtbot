# 📜 Manifesto de Arquitetura: Finance Mgmt Bot
**Versão:** V2 — *Clean Code, Determinismo & Segurança Ativa (Webhook Idempotency)*

## Visão Geral do Produto
O sistema é um Assistente Pessoal (Copilot) Financeiro autônomo e de alta performance no Telegram. Opera 100% via arquitetura orientada a eventos (Webhook Assíncrono) processando ingestão fluida e multimodal (Textos arbitrários, Imagens de Cupons Fiscais Tabulares e Áudios curtos). A arquitetura V2 eleva a **Testabilidade Extrema** e a **Manutenibilidade** isolando regras de negócio em domínios estritos (Clean Code). Além de purgar a responsabilidade quantitativa e estrutural do LLM delegando os mapeamentos de fluxos de caixa, rateios percentuais e aprovação explícita a código puramente determinístico local em Python. Alia isso à **Higiene de Segurança Sensível**, com rastreio protegido (Log Masking) e blindagem contra ataques de repetição.

---

## 1. Stack Tecnológico

* **Orquestrador Engine Web:** `Quart` (Asynchronous Microframework) — Gateway hiper-leve apenas para ingestão Webhook.
* **API de Acesso de Dados:** `supabase` / `postgrest-py` — Persistência PostgreSQL em nuvem.
* **Motores Cognitivos (Trieção de IA Restrita):**
  - **Motor NLP & Router (Estratégia Estrita):** DeepSeek (`deepseek-chat`) — Restrito a triar a requisição e montar JSONs estruturados pré-validados para as intenções (`registrar`, `excluir`, `consultar`), sem autonomia de execução.
  - **Motor Visão Tabular (OCR Flash):** Google Gemini 2.5 Flash (`google-generativeai`) — Efetua Spatial Scraping em snapshots de cupons fiscais para extrair colunas estritamente tipadas ("Nome do Produto", "Valor Bruto", "Desconto do Item").
  - **Motor STT:** Groq (`whisper-large-v3`) — Transcrição ultra-rápida (Speech-to-Text) para arquivos `.ogg`.
* **Motor de Scraping e Bot Integration:** `httpx` (Asynchronous Client) — Requisições HTTP non-blocking exclusivas com a API do Telegram (`bot[TOKEN]/sendChatAction`, etc).
* **Fundação de Testes (TDD & Resiliência):** `pytest`, `pytest-asyncio`, `unittest.mock` — 111+ testes com mocks universais que garantem deploy 100% validado sem dependência online (`Offline First`).

---

## 2. Pipeline V2 (Separação de Preocupações & Determinismo)

1. **Ingestão Webhook Gateway:** O `main.py` serve unicamente como Portão Mínimo. Captura os payloads TLS do Telegram, checa rigorosamente a procedência do token estático (`X-Telegram-Bot-Api-Secret-Token`) e devolve sinal `200 OK` na camada de transporte do Quart, empurrando o processamento pesado para as tasks assíncronas (Fast Ack).
2. **Controlador Agente (Handlers):** O arquivo `handlers.py` orquestra as etapas lógicas de alto nível. Reage avaliando incialmente o meio de entrada (Foto → Invoca Visão Gemini; Áudio → Invoca STT Groq; Texto → Pass-through) antes da Triagem NLP do prompt abrangente.
3. **Muralha Anti-Alucinação (LLM Constraints):** O Prompt injeta dinamicamente o Horário UTC-3 Local do servidor contendo o mês e ano fiscal corretos e constrange imperativamente categorias estritas da modelagem do DB (ex: "Cuidados Pessoais" DEVEM ser catalogados como "Essencial"). A "Inteligência Ampla" é castrada em virtude de respostas estritas obrigatórias baseadas num modelo em formato JSON exclusivo.
4. **Extração e Roteamento Determinístico (Core Engine):**
   - **Regra de Negócio Pura:** Arquivos centralizados `core_logic.py` e `utils.py`. Operações monetárias e parsing cronológico saem da responsabilidade e margem de erro da IA.
   - **Rateio Global de Lotes (`aplicar_map_reduce`):** Em caso de fatiamentos difíceis em tíquetes grandes (onde descontos globais do mercado vêm agrupados), executadores Python desconstróiem os itens originais separadamente enquadrando num loop Map/Reduce perfeitamente transparente ao humano — esmagamento absoluto de fraudes matemáticas acidentais do Agente IA.
5. **Decisor DB Abstrato (The Data Layer):** Com a arquitetura de `db_repository.py`, **Lógica Algum** de Negócio ou Controller acessa métodos "query builders". O Controlar repassa um simples dicionário para `consultar_no_banco` e repositório processável traduz a mecânica com `supabase.table().gte().execute()`. Separação impenetrável das camadas e isenção de injeções cruzadas lógicas.
6. **Controle Transacional Assíncrono:** Para compras longas extraídas por visões de imagem, são submetidos rascunhos de itens para curadoria em tabela limpa (`cache_aprovacao`). Todo processamento aguarda um Click Duplo Humano via botão virtual (`Callback Inline Keyboard`) devolvido no Telegram. Nada polui a `gastos` sem crivo.

---

## 3. AppSec e Governança

* **Observabilidade Blindada (JSON Logging & Auto-Masking):** O módulo `config.py` inicializa o framework `python-json-logger`. Exceções severas do core que cuspam stacktraces perigosos via `traceback.format_exc()` ou payloads sensíveis cruzam uma varredora ativa e substituem ativamente as credenciais confidenciais conhecidas localmente para `[MASKED_SECRET]` atômicas antes de gravar no Disk/Serviço Fila nativa das máquinas hospedeiras.
* **Governança de Credenciais e Init Fail-Fast:** Validação inegociável de uma array constrita `REQUIRED_VARS` (`TELEGRAM_BOT_TOKEN`, tokens `DEEPSEEK_` e `GROQ_`, etc) no subida do serviço Quart. Se qualquer variável for ometida, o processo acusa severa advertência com logs pré-processados e força um Exit Process letal (`RuntimeError: AppSec Fatal Error`). O web-server morre antes mesmo de escutar na porta pública de host.
* **Idempotência de Concorrência e Flood:** Resposta definitiva contra as rajadas Retry automáticas do endpoint nativo do próprio Telegram ou duplos cliques inadvertidos dos botões (flood) na tela. Atualizações são injetadas instantaneamente na tabela de rastreio `webhook_idempotencia`. Retrys geram colisão com violação Unique ID `23505 Duplicate Key` do banco, triturando as repetições colaterais sem duplicar saídas do fluxo de caixa orgânico.
* **Prevenção Repositório Sanitário (`.gitignore`):** Todos o log output nativo, CSVs operacionais reveladores e temporários de cache unitário são expurgados do tracking versionado estaticamente para proteger a auditoria em repositórios remotos ou Pull Requests vazadas.
