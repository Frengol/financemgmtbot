# 📜 Manifesto de Arquitetura: Finance Mgmt Bot
**Versão:** V3 — *Frontend Estático, Backend Seguro & Governança Reprodutível*

## Visão Geral do Produto
O sistema é um Assistente Pessoal (Copilot) Financeiro multimodal orientado a eventos. O núcleo operacional continua centrado no Telegram, onde textos, cupons fiscais e áudios são recebidos e processados via Webhook assíncrono. A evolução V3 introduz uma segunda superfície oficial: um **Painel Administrativo Web** publicado estaticamente no GitHub Pages, consumindo autenticação Supabase e delegando operações sensíveis a um backend Python hospedado no Google Cloud Run.

A arquitetura preserva os princípios de **Determinismo Local**, **Testabilidade Extrema** e **Segurança Ativa**, mas agora segmenta claramente o sistema em duas bordas:

1. **Canal Conversacional (Telegram):** ingestão multimodal, triagem de intenção, OCR/STT e persistência.
2. **Canal Administrativo (Web SPA):** consulta visual, autenticação de operador e acionamento de rotas administrativas auditáveis.

O resultado é uma topologia híbrida onde o frontend pode ser distribuído como ativo estático sem expor credenciais sensíveis, enquanto o backend continua concentrando toda a execução privilegiada, a autenticação forte e a governança operacional.

---

## 1. Stack Tecnológico

* **Gateway Assíncrono & API Backend:** `Quart` — Responsável pelo Webhook Telegram e pela superfície administrativa `/api/admin/*`.
* **Hospedagem Backend:** `Google Cloud Run` — Runtime containerizado para o backend Python com variáveis sensíveis providas por Secret Manager.
* **Frontend Administrativo:** `React` + `Vite` + `Tailwind CSS` + `@tremor/react` — SPA publicada estaticamente no GitHub Pages.
* **Persistência & Auth:** `Supabase` / `PostgreSQL` / `GoTrue` — Banco de dados operacional, autenticação do painel web e políticas de RLS.
* **Motores Cognitivos (Uso Restrito):**
  - **Roteador de Intenção:** DeepSeek (`deepseek-chat`) — Emite JSON estrito para intenções controladas.
  - **OCR Tabular:** Google Gemini 2.5 Flash — Extrai itens, descontos e forma de pagamento de cupons.
  - **Speech-to-Text:** Groq (`whisper-large-v3`) — Transcrição de áudio `.ogg`.
* **Integração Telegram:** `httpx` — Cliente HTTP assíncrono para Telegram Bot API.
* **Entrega Contínua:** `GitHub Actions` — CI para testes/backend build/frontend build e deploy automatizado do frontend no GitHub Pages.
* **Fundação de Testes:** `pytest`, `pytest-asyncio`, `unittest.mock` — Cobertura regressiva local do backend e das novas rotas administrativas.

---

## 2. Topologia do Sistema

### 2.1 Borda Webhook (Telegram → Cloud Run)
1. O Telegram envia updates ao endpoint `/`.
2. O backend valida `X-Telegram-Bot-Api-Secret-Token`.
3. O controlador identifica o tipo de carga:
   - Foto → OCR Gemini
   - Áudio → STT Groq
   - Texto → pass-through
4. O payload textual consolidado é enviado ao DeepSeek para emissão de JSON estrito.
5. Regras determinísticas locais validam datas, rateios, categorias e filtros.
6. O backend persiste dados no Supabase e responde ao Telegram.

### 2.2 Borda Administrativa (GitHub Pages → Cloud Run)
1. O usuário acessa a SPA em `https://admin.example.com/app/`.
2. O frontend autentica com Supabase Auth usando Magic Link.
3. A leitura do painel depende de sessão autenticada e das políticas de RLS.
4. Toda operação destrutiva ou administrativa sensível deixa de ser executada diretamente no browser.
5. O frontend chama o backend em `/api/admin/*` com bearer token do usuário Supabase.
6. O backend revalida a identidade, checa allowlists administrativas e executa a operação privilegiada com auditoria.

### 2.3 Separação de Superfícies
* **GitHub Pages** hospeda apenas arquivos estáticos.
* **Cloud Run** hospeda toda a lógica privilegiada, integração Telegram e API administrativa.
* **Supabase** permanece como fonte de verdade de sessão, dados operacionais e regras de acesso por linha.

---

## 3. Pipeline V3 (Separação de Preocupações & Determinismo)

1. **Portão Mínimo de Transporte:** `main.py` mantém-se responsável por aceitar requests, validar origem do Telegram, aplicar CORS controlado para o frontend e expor rotas administrativas explícitas.
2. **Controlador de Domínio:** `handlers.py` continua orquestrando o fluxo conversacional, sem delegar matemática, datas ou filtros ao modelo.
3. **Muralha Anti-Alucinação:** `ai_service.py` força o DeepSeek a devolver apenas JSON estruturado, com categorias restritas e sem autonomia de execução.
4. **Motor Determinístico Local:** `core_logic.py`, `utils.py` e `db_repository.py` concentram regras financeiras, cronologia, parcelamento e Map/Reduce de cupons.
5. **Camada Administrativa Segura:** `admin_api.py` encapsula exclusão de transações, aprovação/rejeição de pendências e escrita de trilha de auditoria.
6. **Persistência com Duas Naturezas de Acesso:**
   - **Leitura controlada no frontend:** via `anon key` + sessão autenticada + RLS.
   - **Escrita sensível no backend:** via `service_role` no Cloud Run, fora do navegador.
7. **Auditoria Operacional:** ações administrativas críticas escrevem eventos em `auditoria_admin` com ator, alvo, ação e metadados.

---

## 4. Modelo de Segurança

### 4.1 Credenciais e Segredos
* O backend exige fail-fast com `REQUIRED_VARS` em `config.py`.
* Segredos sensíveis do backend residem fora do repositório:
  - Secret Manager / Cloud Run
  - `.env` local para desenvolvimento
* O frontend usa apenas variáveis públicas de build:
  - `VITE_SUPABASE_URL`
  - `VITE_SUPABASE_ANON_KEY`
  - `VITE_API_BASE_URL`

### 4.2 Supabase & RLS
* O acesso web é controlado por Supabase Auth.
* A autorização administrativa é reforçada em três níveis:
  1. sessão válida do Supabase
  2. políticas RLS no banco
  3. allowlist opcional por email ou `user_id` no backend
* A migration versionada cria:
  - `public.admin_users`
  - função `public.is_admin()`
  - políticas de RLS para `gastos`, `cache_aprovacao` e `auditoria_admin`

### 4.3 Operações Sensíveis
* O frontend não executa mais `delete()` crítico diretamente em `gastos` ou `cache_aprovacao`.
* As rotas administrativas exigem bearer token válido do Supabase.
* O backend reconsulta o usuário autenticado antes de permitir exclusão, aprovação ou rejeição.

### 4.4 CORS e Fronteira Web
* O backend restringe chamadas do navegador a `FRONTEND_ALLOWED_ORIGINS`.
* A origem local `http://localhost:5173` e a origem publicada do GitHub Pages são tratadas explicitamente.

### 4.5 Observabilidade Blindada
* Logs seguem em JSON com masking de segredos.
* Falhas de auditoria não devem expor credenciais ou corromper o fluxo principal sem log explícito.

---

## 5. Deploy & Entrega

### 5.1 Backend
* O backend Python é empacotado em contêiner e executado no Google Cloud Run.
* O serviço recebe:
  - `SUPABASE_URL`
  - `SUPABASE_KEY` (`service_role`)
  - `TELEGRAM_*`
  - `DEEPSEEK_API_KEY`
  - `GROQ_API_KEY`
  - `GEMINI_API_KEY`
  - `SUPABASE_ADMIN_EMAILS` e/ou `SUPABASE_ADMIN_USER_IDS`
  - `FRONTEND_ALLOWED_ORIGINS`

### 5.2 Frontend
* O frontend é buildado pelo Vite.
* O artefato `frontend/dist` é publicado no GitHub Pages.
* Em desenvolvimento:
  - `BASE_URL=/`
  - proxy `/api` → backend local `127.0.0.1:8080`
* Em produção:
  - `BASE_URL=/financemgmtbot/`
  - chamadas administrativas apontam para o Cloud Run público

### 5.3 CI/CD
* `ci.yml`
  - executa `pytest -q`
  - instala dependências do frontend
  - valida `npm run build`
* `deploy-pages.yml`
  - builda o frontend com variáveis públicas
  - publica automaticamente o SPA no GitHub Pages

---

## 6. Governança do Repositório

* O repositório não deve conter:
  - `.env`
  - logs
  - exports CSV
  - caches locais
  - `node_modules`
  - `venv`
* O `.gitignore` foi endurecido para impedir o versionamento desses artefatos sem ocultar arquivos essenciais de build do frontend.
* A documentação operacional mínima vive em:
  - `README.md` — setup e deploy
  - `supabase/migrations/` — governança do banco como código

---

## 7. Benefícios Arquiteturais da V3

* **Frontend barato e simples de distribuir:** GitHub Pages resolve publicação do painel sem custo operacional de app server.
* **Backend privilegiado isolado:** toda lógica sensível continua fora do navegador.
* **Segurança reproduzível:** RLS e estruturas administrativas deixam de existir só “no painel” e passam a ser versionadas.
* **Menor acoplamento operacional:** frontend e backend evoluem e escalam em ritmos distintos.
* **Observabilidade e auditoria superiores:** ações administrativas ganham trilha persistente.
* **Base sólida para evolução futura:** caso desejado, a próxima iteração pode migrar ainda mais leitura do browser para APIs server-side sem reestruturar o sistema inteiro.
