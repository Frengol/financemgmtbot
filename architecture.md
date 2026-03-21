# 📜 Manifesto de Arquitetura: Finance Mgmt Bot
**Versão:** V3.1.2 — *Frontend Estático, Backend Seguro, Operação Administrativa Completa & Governança Reprodutível*

## Visão Geral do Produto
O sistema é um Assistente Pessoal (Copilot) Financeiro multimodal orientado a eventos. O núcleo operacional continua centrado no Telegram, onde textos, cupons fiscais e áudios são recebidos e processados via Webhook assíncrono. A evolução V3 introduziu uma segunda superfície oficial: um **Painel Administrativo Web** publicado estaticamente no GitHub Pages, consumindo autenticação Supabase e delegando operações sensíveis a um backend Python hospedado no Google Cloud Run. A versão atual V3.1 consolida essa borda administrativa com **CRUD manual de transações**, **estado de autenticação compartilhado no frontend**, **seleção de período por widget** e um **modo local de desenvolvimento** que não afeta a política de segurança de produção.

A arquitetura preserva os princípios de **Determinismo Local**, **Testabilidade Extrema** e **Segurança Ativa**, mas agora segmenta claramente o sistema em duas bordas:

1. **Canal Conversacional (Telegram):** ingestão multimodal, triagem de intenção, OCR/STT e persistência.
2. **Canal Administrativo (Web SPA):** consulta visual, autenticação de operador, edição manual e acionamento de rotas administrativas auditáveis.

O resultado é uma topologia híbrida onde o frontend pode ser distribuído como ativo estático sem expor credenciais sensíveis, enquanto o backend continua concentrando toda a execução privilegiada, a autenticação forte e a governança operacional.

---

## 1. Stack Tecnológico

* **Gateway Assíncrono & API Backend:** `Quart` — Responsável pelo Webhook Telegram e pela superfície administrativa `/api/admin/*`.
* **Hospedagem Backend:** `Google Cloud Run` — Runtime containerizado para o backend Python com variáveis sensíveis providas por Secret Manager.
* **Frontend Administrativo:** `React` + `Vite` + `Tailwind CSS` + `@tremor/react` — SPA publicada estaticamente no GitHub Pages, com Dashboard analítico, Histórico editável e fila de Aprovações.
* **Persistência & Auth:** `Supabase` / `PostgreSQL` / `GoTrue` — Banco de dados operacional, autenticação do painel web e políticas de RLS.
* **Motores Cognitivos (Uso Restrito):**
  - **Roteador de Intenção:** DeepSeek (`deepseek-chat`) — Emite JSON estrito para intenções controladas.
  - **OCR Tabular:** Google Gemini 2.5 Flash — Extrai itens, descontos e forma de pagamento de cupons.
  - **Speech-to-Text:** Groq (`whisper-large-v3`) — Transcrição de áudio `.ogg`.
* **Integração Telegram:** `httpx` — Cliente HTTP assíncrono para Telegram Bot API.
* **Entrega Contínua:** `GitHub Actions` — CI para testes/backend build/frontend build e deploy automatizado do frontend no GitHub Pages.
* **Fundação de Testes:** `pytest`, `pytest-asyncio`, `unittest.mock` — Cobertura regressiva local do backend e das rotas administrativas, incluindo CRUD manual de transações.

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
7. O operador pode criar, editar, excluir, aprovar e rejeitar registros a partir do painel sem expor a `service_role` ao navegador.

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
5. **Camada Administrativa Segura:** `admin_api.py` encapsula listagem, criação, edição e exclusão de transações, aprovação/rejeição de pendências e escrita de trilha de auditoria.
6. **Persistência com Duas Naturezas de Acesso:**
   - **Leitura controlada no frontend:** via `anon key` + sessão autenticada + RLS.
   - **Escrita sensível no backend:** via `service_role` no Cloud Run, fora do navegador.
7. **Orquestração de UI Compartilhada:** o frontend centraliza autenticação em contexto único e concentra o fluxo de criação/edição em um modal reutilizável.
8. **Auditoria Operacional:** ações administrativas críticas escrevem eventos em `auditoria_admin` com ator, alvo, ação e metadados.

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
* O modo local de desenvolvimento é explicitamente isolado:
  - backend: `ALLOW_LOCAL_DEV_AUTH=true`
  - frontend: `VITE_LOCAL_DEV_BYPASS_AUTH=true`
  - ambos só existem para desenvolvimento e não substituem o fluxo oficial de autenticação em produção

### 4.2 Supabase & RLS
* O acesso web é controlado por Supabase Auth.
* A autorização administrativa é reforçada em três níveis:
  1. sessão válida do Supabase
  2. políticas RLS no banco
  3. allowlist opcional por email ou `user_id` no backend
* O frontend também pode aplicar uma allowlist leve por email (`VITE_ALLOWED_ADMIN_EMAILS`) para melhorar UX e bloquear acesso indevido antes de acionar a camada privilegiada, sem substituir backend/RLS.
* A migration versionada cria:
  - `public.admin_users`
  - função `public.is_admin()`
  - políticas de RLS para `gastos`, `cache_aprovacao` e `auditoria_admin`

### 4.3 Operações Sensíveis
* O frontend não executa mais `delete()` crítico diretamente em `gastos` ou `cache_aprovacao`.
* As rotas administrativas exigem bearer token válido do Supabase.
* O backend reconsulta o usuário autenticado antes de permitir exclusão, aprovação ou rejeição.
* O CRUD manual de transações passa pelas rotas administrativas:
  - `GET /api/admin/gastos`
  - `POST /api/admin/gastos`
  - `PATCH /api/admin/gastos/<id>`
  - `DELETE /api/admin/gastos/<id>`
* A fila administrativa de pendências também é exposta de forma controlada:
  - `GET /api/admin/cache-aprovacao`
  - `POST /api/admin/cache-aprovacao/<id>/approve`
  - `POST /api/admin/cache-aprovacao/<id>/reject`

### 4.4 CORS e Fronteira Web
* O backend restringe chamadas do navegador a `FRONTEND_ALLOWED_ORIGINS`.
* O parser de origens normaliza entradas configuradas com caminho completo para o formato de origem (`scheme://host[:port]`), evitando quebra de CORS por erro operacional.
* As origens padrão do código continuam explícitas e fechadas apenas para desenvolvimento local:
  - `http://localhost:5173`
  - `http://127.0.0.1:5173`
* A origem publicada do GitHub Pages deve vir do ambiente do Cloud Run via `FRONTEND_ALLOWED_ORIGINS`, e não hardcoded no repositório.
* O bypass local do backend só é aceito sem bearer quando a flag de desenvolvimento está ligada e a chamada vem do loopback/origem permitida.

### 4.5 Observabilidade Blindada
* Logs seguem em JSON com masking de segredos.
* Logs operacionais não devem registrar payloads brutos de IA, transcrições, conteúdo textual de transações, itens detalhados de cupons nem dumps completos de inserts falhos; devem registrar apenas metadados mínimos como evento, contagem, ids e nomes de campos.
* A trilha `auditoria_admin` deve registrar contexto mínimo da operação administrativa, sem duplicar descrições completas de transações ou payloads integrais de aprovação.
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
  - opcionalmente `ALLOW_LOCAL_DEV_AUTH` apenas fora de produção

### 5.2 Frontend
* O frontend é buildado pelo Vite.
* O artefato `frontend/dist` é publicado no GitHub Pages.
* Em desenvolvimento:
  - `BASE_URL=/`
  - proxy `/api` → backend local `127.0.0.1:8080`
  - bypass local opcional para autenticação de UI sem OTP
* Em produção:
  - `BASE_URL=/financemgmtbot/`
  - chamadas administrativas apontam para o Cloud Run público
  - login oficial via Magic Link do Supabase
* A SPA usa `code splitting` por rota e por dependência pesada de frontend, carregando `Dashboard`, `Histórico`, `Aprovações`, `Login` e o modal transacional sob demanda, com `manualChunks` dedicados para gráficos, tabela, Supabase e vendor base.
* Em telas mobile, o layout principal expõe um acionador discreto no canto superior esquerdo que abre um drawer lateral esquerdo com a navegação entre Dashboard, Aprovações e Histórico, preservando o menu fixo em desktop.
* O Dashboard usa widgets com seletor de mês compacto por card, evitando um filtro global único e permitindo leitura contextual do período.
* O Histórico usa tabela filtrável com edição e exclusão seguras via backend.
* O modal de transações centraliza criação e edição manual com normalização server-side.
* O campo monetário do modal opera em formato local (`12,50`), aceita apenas dígitos e vírgula no cliente e é convertido para valor numérico antes da chamada administrativa.
* A categoria `Outros` é aceita explicitamente pelo frontend e pelo backend como categoria válida de lançamentos manuais.

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
  - `architecture.md` — manifesto vivo da topologia e dos fluxos de segurança

---

## 7. Benefícios Arquiteturais da V3

* **Frontend barato e simples de distribuir:** GitHub Pages resolve publicação do painel sem custo operacional de app server.
* **Backend privilegiado isolado:** toda lógica sensível continua fora do navegador.
* **Segurança reproduzível:** RLS e estruturas administrativas deixam de existir só “no painel” e passam a ser versionadas.
* **Menor acoplamento operacional:** frontend e backend evoluem e escalam em ritmos distintos.
* **Observabilidade e auditoria superiores:** ações administrativas ganham trilha persistente.
* **Operação administrativa completa:** o painel deixa de ser apenas de leitura e passa a suportar manutenção manual segura de lançamentos.
* **Experiência local mais fluida:** desenvolvimento não depende de rate limit do Magic Link, sem comprometer o modelo de segurança de produção.
* **Base sólida para evolução futura:** caso desejado, a próxima iteração pode migrar ainda mais leitura do browser para APIs server-side sem reestruturar o sistema inteiro.
