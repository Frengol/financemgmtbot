# 📜 Manifesto de Arquitetura: Finance Mgmt Bot
**Versão:** V3.3.1 — *GitHub Pages com Sessão Supabase no Browser, Callback Canônico no Frontend e Relay Seguro de Compatibilidade*

## Visão Geral do Produto
O sistema é um Assistente Pessoal (Copilot) Financeiro multimodal orientado a eventos. O núcleo operacional continua centrado no Telegram, onde textos, cupons fiscais e áudios são recebidos e processados via Webhook assíncrono. A evolução V3 introduziu uma segunda superfície oficial: um **Painel Administrativo Web** publicado estaticamente no GitHub Pages, delegando autenticação e operações sensíveis a um backend Python hospedado no Google Cloud Run. A versão atual V3.3 mantém o frontend estático e o backend sem custo extra, mas corrige o problema estrutural de cookie cross-site retornando o painel oficial para **sessão Supabase no browser** e **Bearer token validado server-side** nas rotas `/api/admin/*`, preservando o hardening que não depende de cookie de terceira parte: logs sanitizados, envelope de erro com `requestId`, `cache_aprovacao` cifrada com TTL, headers anti-cache e allowlists administrativas no backend.

A arquitetura preserva os princípios de **Determinismo Local**, **Testabilidade Extrema** e **Segurança Ativa**, mas agora segmenta claramente o sistema em duas bordas:

1. **Canal Conversacional (Telegram):** ingestão multimodal, triagem de intenção, OCR/STT e persistência.
2. **Canal Administrativo (Web SPA):** consulta visual, autenticação de operador, edição manual e acionamento de rotas administrativas auditáveis.

O resultado é uma topologia híbrida onde o frontend pode ser distribuído como ativo estático sem expor credenciais sensíveis, enquanto o backend continua concentrando toda a execução privilegiada, a autenticação forte e a governança operacional.

---

## 1. Stack Tecnológico

* **Gateway Assíncrono & API Backend:** `Quart` — Responsável pelo Webhook Telegram e pela superfície administrativa `/api/admin/*`.
* **Hospedagem Backend:** `Google Cloud Run` — Runtime containerizado para o backend Python com variáveis sensíveis providas por Secret Manager.
* **Frontend Administrativo:** `React` + `Vite` + `Tailwind CSS` + `@tremor/react` — SPA publicada estaticamente no GitHub Pages, com Dashboard analítico, Histórico editável e fila de Aprovações.
* **Persistência & Auth:** `Supabase` / `PostgreSQL` / `GoTrue` — Banco de dados operacional, autenticação upstream do Magic Link e políticas de RLS.
* **Motores Cognitivos (Uso Restrito):**
  - **Roteador de Intenção:** DeepSeek (`deepseek-chat`) — Emite JSON estrito para intenções controladas.
  - **OCR Tabular:** Google Gemini 2.5 Flash — Extrai itens, descontos e forma de pagamento de cupons.
  - **Speech-to-Text:** Groq (`whisper-large-v3`) — Transcrição de áudio `.ogg`.
* **Integração Telegram:** `httpx` — Cliente HTTP assíncrono para Telegram Bot API.
* **Entrega Contínua:** `GitHub Actions` — CI para coverage do backend, coverage unitário do frontend, smoke E2E determinístico com Playwright, E2E integrado de autenticação com backend local, auditoria de dependências (`pip-audit`, `npm audit`), secret scanning com `gitleaks`, build/frontend build e deploy automatizado do frontend no GitHub Pages.
* **Fundação de Testes:** `pytest`, `pytest-asyncio`, `pytest-cov`, `coverage.py`, `Vitest`, `@vitest/coverage-v8`, `Playwright` e `unittest.mock` — Cobertura regressiva local do backend e das rotas administrativas, métricas estruturais reais com gate mínimo de `90%`, smoke E2E local com mocks de `/auth/*` e `/api/admin/*` e uma suíte integrada local que percorre `magic-link -> callback -> sessão -> leitura de dados`.

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
1. O usuário acessa a SPA em um origin público controlado, por exemplo `https://admin.example.com/`.
2. O frontend solicita o Magic Link ao backend em `POST /auth/magic-link`.
3. O backend valida allowlist/rate limit e pede ao Supabase o envio do Magic Link com `email_redirect_to` canônico apontando para a rota pública do frontend, por exemplo `https://admin.example.com/auth/callback`; em produção, esse callback não depende mais do `redirectTo` informado pelo navegador.
4. O frontend recebe `access_token` e `refresh_token` do Supabase na rota `/auth/callback` e persiste a sessão usando `supabase.auth.setSession(...)`, ou troca um `code` por sessão com `supabase.auth.exchangeCodeForSession(...)` quando o provedor responder nesse formato.
5. O contexto `useAuth` passa a refletir a sessão oficial do navegador via `supabase.auth.getSession()` e `onAuthStateChange(...)`, com fallback opcional para `GET /auth/session` apenas como compatibilidade legada/local.
6. O storage legado `financemgmtbot-admin-auth-test-session` permanece restrito a loopback (`localhost`/`127.0.0.1`) para E2E e testes locais; em produção o frontend ignora e limpa esse estado assim que detectado.
7. Tokens Bearer do navegador passam por validação mínima de formato (`3` segmentos JWT) antes de qualquer uso. Sessões malformadas são descartadas localmente para impedir estado "UI autenticada / backend inválido".
8. Erros de autenticação Bearer malformada retornam envelope sanitizado com `code=AUTH_SESSION_TOKEN_MALFORMED`, `detail=bearer_malformed` e `requestId`, permitindo que a UI troque o CTA de retry por re-login sem expor mensagem crua do parser JWT.
9. O frontend chama o backend em `/api/admin/*` com `Authorization: Bearer <access_token>`; o caminho cookie+CSRF deixa de ser o fluxo oficial do GitHub Pages.
10. O backend valida o bearer token no lado servidor com Supabase, revalida allowlists administrativas e executa a operação privilegiada com auditoria.
11. O operador continua podendo criar, editar, excluir, aprovar e rejeitar registros a partir do painel sem expor `service_role` ao navegador; o token web oficial passa a ser o token público do Supabase, compatível com o domínio separado do GitHub Pages.
12. O callback legado do backend (`GET /auth/callback`) passa a atuar apenas como relay de compatibilidade: ele preserva `hash` ou `query string` vindos do Supabase e redireciona o navegador para o callback do frontend, sem mais criar sessão cookie para o fluxo oficial do Pages.
13. Falhas operacionais do painel usam envelope sanitizado com `code`, `requestId`, `retryable` e, quando aplicável, `retryAfterSeconds`; erros de sessão agora também podem incluir um `detail` curto e controlado para suporte, sem ecoar detalhes crus de provedores ou do banco.

### 2.3 Separação de Superfícies
* **GitHub Pages** hospeda apenas arquivos estáticos.
* **Cloud Run** hospeda toda a lógica privilegiada, integração Telegram e API administrativa.
* **Supabase** permanece como fonte de verdade de dados operacionais, identidade upstream do Magic Link e regras de acesso por linha.

---

## 3. Pipeline V3 (Separação de Preocupações & Determinismo)

1. **Portão Mínimo de Transporte:** `main.py` mantém-se responsável por aceitar requests, validar origem do Telegram, aplicar CORS apenas às rotas de browser (`/auth/*`, `/api/admin/*`), endurecer headers de resposta e expor rotas administrativas explícitas.
2. **Controlador de Domínio:** `handlers.py` continua orquestrando o fluxo conversacional, sem delegar matemática, datas ou filtros ao modelo.
3. **Muralha Anti-Alucinação:** `ai_service.py` força o DeepSeek a devolver apenas JSON estruturado, com categorias restritas e sem autonomia de execução.
4. **Motor Determinístico Local:** `core_logic.py`, `utils.py` e `db_repository.py` concentram regras financeiras, cronologia, parcelamento e Map/Reduce de cupons.
5. **Camada Administrativa Segura:** `admin_api.py` encapsula listagem, criação, edição e exclusão de transações, aprovação/rejeição de pendências e escrita de trilha de auditoria.
6. **Persistência com Duas Naturezas de Acesso:**
   - **Sessão web do painel:** `public.admin_web_sessions`, mantida apenas pelo backend.
   - **Escrita sensível e leitura privilegiada:** via `service_role` no Cloud Run, fora do navegador.
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
  - `VITE_API_BASE_URL`
* O modo local de desenvolvimento é explicitamente isolado:
  - backend: `ALLOW_LOCAL_DEV_AUTH=true`
  - frontend: `VITE_LOCAL_DEV_BYPASS_AUTH=true`
  - ambos só existem para desenvolvimento e não substituem o fluxo oficial de autenticação em produção

### 4.2 Supabase & RLS
* O acesso web é controlado por Supabase Auth como identidade upstream e como sessão oficial do navegador no GitHub Pages; o backend mantém `admin_web_sessions` apenas para compatibilidade operacional, testes locais e fluxos legados.
* A autorização administrativa é reforçada em quatro níveis:
  1. Magic Link do Supabase emitido com callback canônico do frontend
  2. bearer token do Supabase validado server-side no backend
  3. políticas RLS no banco
  4. allowlist opcional por email e/ou `user_id` no backend
* O frontend também pode aplicar uma allowlist leve por email (`VITE_ALLOWED_ADMIN_EMAILS`) para melhorar UX e bloquear acesso indevido antes de acionar a camada privilegiada, sem substituir backend/RLS.
* A migration versionada cria:
  - `public.admin_users`
  - função `public.is_admin()`
  - políticas de RLS para `gastos`, `cache_aprovacao` e `auditoria_admin`
  - `public.admin_web_sessions` para compatibilidade operacional e fluxos internos/legados do backend

### 4.3 Operações Sensíveis
* O frontend não executa mais `delete()` crítico diretamente em `gastos` ou `cache_aprovacao`.
* As rotas administrativas oficiais do GitHub Pages exigem `Authorization: Bearer <access_token>` emitido pelo Supabase no browser e validado novamente pelo backend.
* O caminho `cookie HttpOnly + X-CSRF-Token` permanece apenas como compatibilidade interna/legada; ele não é mais o fluxo oficial do painel hospedado no GitHub Pages.
* O backend revalida o bearer token, a allowlist e a expiração antes de permitir exclusão, aprovação ou rejeição.
* O CRUD manual de transações passa pelas rotas administrativas:
  - `GET /api/admin/gastos`
  - `POST /api/admin/gastos`
  - `PATCH /api/admin/gastos/<id>`
  - `DELETE /api/admin/gastos/<id>`
* A fila administrativa de pendências também é exposta de forma controlada:
  - `GET /api/admin/cache-aprovacao`
  - `POST /api/admin/cache-aprovacao/<id>/approve`
  - `POST /api/admin/cache-aprovacao/<id>/reject`
* O fluxo administrativo de autenticação passa pelo backend:
  - `POST /auth/magic-link`
  - callback oficial no frontend `/auth/callback`
  - `GET /auth/callback` no backend apenas como relay seguro de compatibilidade para links antigos ou configuração desalinhada
  - `GET /auth/session` e `POST /auth/logout` apenas como compatibilidade de sessão server-side

### 4.4 CORS e Fronteira Web
* O backend restringe chamadas do navegador a `FRONTEND_ALLOWED_ORIGINS`.
* O parser de origens normaliza entradas configuradas com caminho completo para o formato de origem (`scheme://host[:port]`), evitando quebra de CORS por erro operacional.
* O webhook `/` não publica mais CORS, porque não é uma superfície para browser.
* As origens padrão do código continuam explícitas e fechadas apenas para desenvolvimento local:
  - `http://localhost:5173`
  - `http://127.0.0.1:5173`
* A origem publicada do frontend deve vir do ambiente do Cloud Run via `FRONTEND_ALLOWED_ORIGINS`, e não hardcoded no repositório.
* O bypass local do backend só é aceito sem bearer quando a flag de desenvolvimento está ligada e a chamada vem do loopback/origem permitida.
* Respostas de `/auth/*` e `/api/admin/*` agora incluem `Cache-Control: no-store, private`, `Pragma: no-cache`, `X-Content-Type-Options: nosniff` e `Referrer-Policy: no-referrer`.
* Como o frontend ainda está em GitHub Pages sem edge dedicado, CSP/anti-clickjacking completos continuam dependentes da próxima etapa obrigatória: domínio próprio + borda reversa controlada.

### 4.5 Observabilidade Blindada
* Logs seguem em JSON com masking de segredos.
* Erros administrativos e de autenticação devem compartilhar um `requestId` entre resposta HTTP e logs estruturados, permitindo correlação de suporte sem expor stack trace, query SQL, mensagens cruas de provider ou tokens.
* Logs operacionais não devem registrar payloads brutos de IA, transcrições, conteúdo textual de transações, itens detalhados de cupons, dumps completos de inserts falhos, `access_token`, `refresh_token` ou payloads integrais de `cache_aprovacao`; devem registrar apenas metadados mínimos como evento, contagem, ids e nomes de campos.
* A trilha `auditoria_admin` deve registrar contexto mínimo da operação administrativa, sem duplicar descrições completas de transações ou payloads integrais de aprovação.
* Falhas de auditoria não devem expor credenciais ou corromper o fluxo principal sem log explícito.
* Falhas do webhook e do processamento conversacional devem responder com mensagem genérica ao cliente/usuário, sem ecoar stack trace ou exceção crua.

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
  - `FRONTEND_PUBLIC_URL`
  - `AUTH_CALLBACK_PUBLIC_URL`
  - opcionalmente `APP_SESSION_SECRET`
  - opcionalmente `DATA_ENCRYPTION_KEY`
  - opcionalmente `ALLOW_LOCAL_DEV_AUTH` apenas fora de produção

### 5.2 Frontend
* O frontend é buildado pelo Vite.
* O artefato `frontend/dist` é publicado no GitHub Pages.
* Em desenvolvimento:
  - `BASE_URL=/`
  - proxy `/api`, `/auth` e `/__test__` → backend local `127.0.0.1:8080`
  - bypass local opcional para autenticação de UI sem OTP
* Em produção:
  - `BASE_URL=/financemgmtbot/`
  - chamadas administrativas apontam para o Cloud Run público
  - login oficial via backend `/auth/magic-link`
  - o backend constrói `email_redirect_to` do Supabase usando sempre a rota pública canônica do frontend no GitHub Pages, por exemplo `/auth/callback`
  - `redirectTo` vindo do browser só é aceito em desenvolvimento local ou `AUTH_TEST_MODE`
  - o fallback seguro de retorno do painel usa `FRONTEND_PUBLIC_URL`, nunca `localhost`
  - o build oficial gera `dist/404.html` como cópia funcional de `dist/index.html`, permitindo que o GitHub Pages entregue o shell da SPA para deep links como `/financemgmtbot/auth/callback`
  - `GET /auth/callback` do backend preserva `hash`/`query string` e redireciona para o callback do frontend quando um link antigo ainda cair no `run.app`
  - a SPA manipula apenas o token público de sessão do Supabase no navegador e envia `Authorization: Bearer` para o backend administrativo
  - o frontend exige `VITE_API_BASE_URL`, `VITE_SUPABASE_URL` e `VITE_SUPABASE_ANON_KEY` no build oficial
* A SPA usa `code splitting` por rota e por dependência pesada de frontend, carregando `Dashboard`, `Histórico`, `Aprovações`, `Login` e o modal transacional sob demanda, com `manualChunks` dedicados para gráficos, tabela e vendor base.
* Em telas mobile, o layout principal expõe um acionador discreto no canto superior esquerdo que abre um drawer lateral esquerdo com a navegação entre Dashboard, Aprovações e Histórico, preservando o menu fixo em desktop.
* O Dashboard usa widgets com seletor de mês compacto por card, evitando um filtro global único e permitindo leitura contextual do período.
* O Histórico usa tabela filtrável com edição e exclusão seguras via backend.
* O modal de transações centraliza criação e edição manual com normalização server-side.
* O campo monetário do modal opera em formato local (`12,50`), aceita apenas dígitos e vírgula no cliente e é convertido para valor numérico antes da chamada administrativa.
* A categoria `Outros` é aceita explicitamente pelo frontend e pelo backend como categoria válida de lançamentos manuais.

### 5.3 CI/CD
* `ci.yml`
  - executa `make test-backend-coverage`
  - falha se o relatório do backend ficar abaixo de `90%` em `Lines` ou `Branches`
  - executa `pip-audit` sobre `requirements.txt` e `requirements-dev.txt`
  - instala dependências do frontend
  - executa `npm audit --omit=dev`
  - executa `npm run test:coverage`
  - falha se a cobertura unitária do frontend ficar abaixo de `90%` em `Statements`, `Branches`, `Functions` ou `Lines`
  - valida `npm run verify:build-env`, exigindo `VITE_API_BASE_URL`, `VITE_SUPABASE_URL` e `VITE_SUPABASE_ANON_KEY` vindos de GitHub Actions `Variables` ou `Secrets`
  - valida `npm run build`
  - valida `npm run verify:pages-fallback`, garantindo que `404.html` foi gerado e continua idêntico ao shell da SPA para o GitHub Pages
  - valida `npm run verify:bundle` para garantir que o artefato publicado continua no contrato `Supabase browser session + Authorization Bearer`
  - o scanner do bundle permite apenas os valores públicos esperados do frontend (`VITE_SUPABASE_URL` e `VITE_SUPABASE_ANON_KEY`) e continua bloqueando segredos backend, e-mails inesperados e JWTs não reconhecidos
  - executa `npm run test:e2e` com Playwright em Chromium e Firefox
  - a suíte E2E combina:
    - smoke mockada para regressão rápida de UI
    - integração local com backend Quart em `AUTH_TEST_MODE`, validando magic link, callback no frontend, sessão Supabase no browser e carregamento de `/api/admin/gastos` por bearer
  - executa `gitleaks` com histórico completo no clone da CI
  - publica artefatos de coverage e do relatório Playwright
* Pré-commit/local:
  - mudanças com risco de exposição devem rodar `make audit-repo-security` antes de commit quando `gitleaks` estiver disponível localmente
  - `make audit-repo-security` varre o repositório Git e o diff atual rastreado, evitando falsos positivos em `.env` locais ignorados e artefatos gerados fora do Git
  - fixtures de teste não devem conter literais completos que casem com scanners de segredos; tokens/JWTs simulados devem ser montados por fragmentos em tempo de execução
  - `make pre-push` é o gate local padrão antes de qualquer push e agrega secret scanning, coverage do backend, coverage do frontend, build de produção e `verify:bundle`
  - o gate local também valida `npm run verify:pages-fallback` para impedir publicação de um build sem fallback de SPA no GitHub Pages
  - `make pre-push` e `make pre-push-full` injetam placeholders públicos seguros para `VITE_API_BASE_URL`, `VITE_SUPABASE_URL` e `VITE_SUPABASE_ANON_KEY` durante a validação local do build
  - quando necessário validar o gate com valores públicos específicos do ambiente, os overrides locais devem usar `FRONTEND_BUILD_API_BASE_URL`, `FRONTEND_BUILD_SUPABASE_URL` e `FRONTEND_BUILD_SUPABASE_ANON_KEY`
  - `make pre-push-full` estende o gate padrão com `npm run test:e2e --prefix frontend` e deve ser usado para mudanças de auth, frontend, CI, build, deploy, contrato público ou segurança
  - o hook local é opt-in e pode ser instalado com `make install-git-hooks`; ele roda apenas `make pre-push`
* `deploy-pages.yml`
  - instala dependências com `npm ci`
  - valida `npm run verify:build-env` antes do build, aceitando `VITE_API_BASE_URL`, `VITE_SUPABASE_URL` e `VITE_SUPABASE_ANON_KEY` vindos de Repository Variables ou Secrets
  - builda o frontend com `VITE_API_BASE_URL`, `VITE_SUPABASE_URL` e `VITE_SUPABASE_ANON_KEY` vindos de Repository Variables ou Secrets
  - valida `npm run verify:pages-fallback` antes de publicar, garantindo que o GitHub Pages consegue servir o shell da SPA em deep links
  - valida o bundle com `npm run verify:bundle` antes de publicar o artefato no GitHub Pages, reutilizando exatamente a mesma política de scan da CI
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
* Evidências de pentest, anotações operacionais e notebooks de segurança devem permanecer fora do repositório público ou passar por redação completa antes de publicação.
* Toda publicação pública deve partir de um clone Git íntegro e passar pela checklist documentada em `PUBLIC_RELEASE.md`, incluindo auditoria de histórico e validação de supply chain.

---

## 7. Benefícios Arquiteturais da V3

* **Frontend barato e simples de distribuir:** GitHub Pages resolve publicação do painel sem custo operacional de app server.
* **Backend privilegiado isolado:** toda lógica sensível continua fora do navegador.
* **Login compatível com domínio separado:** o painel volta a operar de forma estável em `github.io` usando sessão pública do Supabase no browser e bearer validado novamente no backend.
* **Fila de pendências mais segura:** `cache_aprovacao` deixa de expor payload bruto ao painel e passa a operar com preview mínimo, ciphertext e expiração.
* **Segurança reproduzível:** RLS e estruturas administrativas deixam de existir só “no painel” e passam a ser versionadas.
* **Menor acoplamento operacional:** frontend e backend evoluem e escalam em ritmos distintos.
* **Observabilidade e auditoria superiores:** ações administrativas ganham trilha persistente.
* **Operação administrativa completa:** o painel deixa de ser apenas de leitura e passa a suportar manutenção manual segura de lançamentos.
* **Experiência local mais fluida:** desenvolvimento não depende de rate limit do Magic Link, sem comprometer o modelo de segurança de produção.
* **Cobertura real do fluxo crítico:** o login administrativo e a leitura de dados deixam de depender apenas de mocks e passam a ter regressão automatizada de ponta a ponta em ambiente local controlado.
* **Base sólida para evolução futura:** a próxima etapa natural é adicionar domínio próprio + edge reverso para CSP/anti-clickjacking completos sem reestruturar o sistema inteiro.
