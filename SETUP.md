# Setup completo para usar o FinanceMgmtBot

Este guia ensina uma pessoa sem familiaridade com deploy a criar a propria instancia do FinanceMgmtBot usando a arquitetura atual do projeto:

- Telegram para conversar com o bot.
- Supabase para banco de dados e login do painel.
- Google Cloud Run para rodar o backend Python.
- GitHub Pages para publicar o painel web.
- GitHub Actions para publicar o frontend e chamar a rotina diaria de despesas recorrentes.

Importante: este documento usa apenas valores de exemplo. Nunca cole tokens reais, chaves privadas, `service_role`, JWTs ou dados financeiros em arquivos versionados, issues, prints publicos ou logs.

## 0. O que voce vai criar

Ao final, voce tera:

- um repositorio GitHub com o codigo;
- um projeto Supabase com tabelas, Auth e um usuario admin;
- um bot no Telegram criado pelo BotFather;
- um servico Cloud Run publico para receber o webhook do Telegram e servir a API administrativa;
- um painel no GitHub Pages;
- um agendamento no GitHub Actions para gerar despesas recorrentes.

Guarde estes nomes para seguir o tutorial:

| Nome usado no guia | Exemplo | O que significa |
| --- | --- | --- |
| `<GITHUB_USER>` | `maria` | seu usuario ou organizacao no GitHub |
| `<REPO_NAME>` | `financemgmtbot` | nome do repositorio |
| `<GCP_PROJECT_ID>` | `maria-finance-bot` | id do projeto no Google Cloud |
| `<REGION>` | `southamerica-east1` | regiao do Cloud Run e Artifact Registry |
| `<SERVICE_NAME>` | `financemgmtbot` | nome do servico no Cloud Run |
| `<AR_REPOSITORY>` | `cloud-run-source-deploy` | repositorio de imagens no Artifact Registry |
| `<FRONTEND_URL>` | `https://maria.github.io/financemgmtbot/` | URL final do painel no GitHub Pages |
| `<FRONTEND_ORIGIN>` | `https://maria.github.io` | origem do painel, sem caminho |
| `<CLOUD_RUN_URL>` | `https://financemgmtbot-xxxxx.a.run.app` | URL final do backend no Cloud Run |
| `<ADMIN_EMAIL>` | `voce@example.com` | e-mail autorizado a entrar no painel |

Observacao importante sobre o GitHub Pages: o projeto esta configurado no Vite com `base: '/financemgmtbot/'`. O caminho mais simples e manter o repositorio com o nome `financemgmtbot`. Se voce usar outro nome, ajuste `frontend/vite.config.ts` antes de publicar.

## 1. Mapa de valores e onde colocar cada um

Use esta tabela como checklist. Ela evita o erro mais perigoso: colocar segredo de backend no frontend.

### Valores publicos do frontend

Esses valores podem aparecer no build do GitHub Pages. Configure em `GitHub -> Settings -> Secrets and variables -> Actions -> Variables`.

| Nome | Exemplo | Onde encontrar |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `<CLOUD_RUN_URL>` | Cloud Run, depois do primeiro deploy |
| `VITE_SUPABASE_URL` | `https://xxxx.supabase.co` | Supabase, Project Settings, API |
| `VITE_SUPABASE_ANON_KEY` | `<SUPABASE_ANON_KEY>` | Supabase, Project Settings, API, anon public |

Opcional:

| Nome | Exemplo | Quando usar |
| --- | --- | --- |
| `VITE_ALLOWED_ADMIN_EMAILS` | `<ADMIN_EMAIL>` | melhora a UX do painel, mas nao substitui a seguranca do backend |

### Secrets do Cloud Run / Secret Manager

Esses valores ficam no Google Secret Manager e sao expostos ao Cloud Run como variaveis de ambiente. Nao coloque no frontend.

| Variavel no Cloud Run | Secret sugerido no Secret Manager | O que e |
| --- | --- | --- |
| `SUPABASE_KEY` | `SUPABASE_KEY` | Supabase `service_role` |
| `TELEGRAM_BOT_TOKEN` | `TELEGRAM_BOT_TOKEN` | token do BotFather |
| `TELEGRAM_SECRET_TOKEN` | `TELEGRAM_SECRET_TOKEN` | segredo criado por voce para validar o webhook |
| `DEEPSEEK_API_KEY` | `DEEPSEEK_API_KEY` | chave da DeepSeek |
| `GROQ_API_KEY` | `GROQ_API_KEY` | chave da Groq |
| `GEMINI_API_KEY` | `GEMINI_API_KEY` | chave da Gemini |
| `RECURRING_EXPENSES_CRON_SECRET` | `recurring-expenses-cron-secret` | segredo da rotina diaria |
| `DATA_ENCRYPTION_KEY` | `DATA_ENCRYPTION_KEY` | obrigatorio e compartilhado entre API e worker para criptografia estavel dos payloads pendentes |

O nome da variavel no Cloud Run nao precisa ser igual ao nome do secret. O `cloudbuild.yaml` usa substitutions para mapear cada variavel para o secret correto.

### Variaveis nao secretas do Cloud Run

Configure como variaveis normais no Cloud Run.

| Nome | Valor esperado em producao |
| --- | --- |
| `SUPABASE_URL` | URL do projeto Supabase |
| `SUPABASE_ADMIN_EMAILS` | `<ADMIN_EMAIL>` |
| `SUPABASE_ADMIN_USER_IDS` | opcional, pode ficar vazio |
| `SUPABASE_GASTOS_TABLE` | `gastos` |
| `FRONTEND_PUBLIC_URL` | `<FRONTEND_URL>` |
| `FRONTEND_ALLOWED_ORIGINS` | `<FRONTEND_ORIGIN>` |
| `AUTH_TEST_MODE` | `false` |
| `ALLOW_LOCAL_DEV_AUTH` | `false` |
| `APP_COMPONENT` | `api` no servico publico; `telegram-worker` no worker privado |
| `TELEGRAM_TASKS_PROJECT` | `financemgmtbot` no servico publico |
| `TELEGRAM_TASKS_LOCATION` | `southamerica-east1` no servico publico |
| `TELEGRAM_TASKS_QUEUE` | `telegram-updates` no servico publico |
| `TELEGRAM_WORKER_URL` | URL HTTPS do worker privado |
| `TELEGRAM_TASK_INVOKER_SERVICE_ACCOUNT` | `financemgmtbot-task-invoker@financemgmtbot.iam.gserviceaccount.com` |

### Secrets do GitHub Actions

Configure em `GitHub -> Settings -> Secrets and variables -> Actions -> Secrets`.

| Nome | Valor |
| --- | --- |
| `CLOUD_RUN_BASE_URL` | `<CLOUD_RUN_URL>` |
| `RECURRING_EXPENSES_CRON_SECRET` | exatamente o mesmo valor usado no Cloud Run |

O valor de `RECURRING_EXPENSES_CRON_SECRET` precisa ser igual nos dois lugares. Se for diferente, o workflow do GitHub vai chamar o backend e receber erro de autorizacao.

## 2. Criar o repositorio no GitHub

1. Entre no GitHub.
2. Crie um repositorio chamado `financemgmtbot`.
3. Envie este codigo para o repositorio.
4. Abra `Settings -> Pages`.
5. Em `Build and deployment`, selecione `GitHub Actions`.
6. Ainda nao rode o deploy do Pages. Primeiro voce precisa criar Supabase e Cloud Run.

Se voce quiser usar outro nome de repositorio:

1. Abra `frontend/vite.config.ts`.
2. Troque `base: mode === 'production' ? '/financemgmtbot/' : '/'` para o caminho do seu repo, por exemplo `'/meu-bot-financeiro/'`.
3. Use esse mesmo caminho nas URLs do Supabase Auth.

## 3. Criar o projeto no Supabase

1. Acesse `https://supabase.com`.
2. Crie uma conta ou faca login.
3. Clique em `New project`.
4. Escolha uma organizacao.
5. Dê um nome ao projeto, por exemplo `finance-mgmt-bot`.
6. Crie uma senha forte para o banco e guarde em um gerenciador de senhas.
7. Escolha uma regiao.
8. Clique em `Create new project`.
9. Aguarde o projeto ficar pronto.

Depois que o projeto abrir:

1. Va em `Project Settings -> API`.
2. Copie `Project URL`. Esse valor sera `SUPABASE_URL` e `VITE_SUPABASE_URL`.
3. Copie `anon public`. Esse valor sera `VITE_SUPABASE_ANON_KEY`.
4. Copie `service_role`. Esse valor sera `SUPABASE_KEY` no Secret Manager.
5. Nao coloque o `service_role` em GitHub Variables, GitHub Pages, frontend ou print publico.

## 4. Criar o usuario admin no Supabase Auth

O painel usa Magic Link. Mesmo assim, o usuario precisa existir e estar autorizado.

1. No Supabase, va em `Authentication -> Users`.
2. Clique em `Add user`.
3. Informe o seu e-mail de admin (`<ADMIN_EMAIL>`).
4. Se houver opcao para confirmar automaticamente o e-mail, deixe confirmado.
5. Salve.
6. Abra o usuario criado e copie o `User UID`.
7. Guarde esse UID. Ele sera usado para inserir o admin na tabela `admin_users`.

## 5. Criar as tabelas base no Supabase

As migrations versionadas em `supabase/migrations/` configuram seguranca, auditoria e despesas recorrentes. Antes delas, um projeto Supabase novo precisa das tabelas base `gastos`, `cache_aprovacao` e `webhook_idempotencia`.

1. No Supabase, va em `SQL Editor`.
2. Clique em `New query`.
3. Cole o SQL abaixo.
4. Clique em `Run`.

```sql
create extension if not exists pgcrypto;

create table if not exists public.gastos (
    id uuid primary key default gen_random_uuid(),
    data date not null,
    valor numeric(12,2) not null check (valor >= 0),
    natureza text not null,
    categoria text not null,
    descricao text not null,
    metodo_pagamento text not null default 'Outros',
    conta text not null default 'Nao Informada',
    created_at timestamptz not null default timezone('utc', now())
);

create index if not exists gastos_data_idx
    on public.gastos (data desc);

create index if not exists gastos_categoria_idx
    on public.gastos (categoria);

create index if not exists gastos_natureza_idx
    on public.gastos (natureza);

create table if not exists public.cache_aprovacao (
    id text primary key,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.webhook_idempotencia (
    update_id bigint primary key,
    created_at timestamptz not null default timezone('utc', now())
);
```

## 6. Aplicar as migrations do projeto

Agora aplique as migrations do repositorio em ordem de nome.

1. No Supabase, continue em `SQL Editor`.
2. Para cada arquivo abaixo, abra o arquivo no GitHub, copie todo o conteudo, cole em uma nova query e clique em `Run`.
3. Siga exatamente esta ordem:

```text
supabase/migrations/20260318_admin_security.sql
supabase/migrations/20260403_bff_auth_and_pending_security.sql
supabase/migrations/20260410_despesas_recorrentes.sql
supabase/migrations/20260410_drop_admin_web_sessions.sql
supabase/migrations/20260411_recurring_expenses_hardening.sql
supabase/migrations/20260412_remove_recurring_expense_description.sql
supabase/migrations/20260815_telegram_update_reliability.sql
```

Se o Supabase avisar que algum objeto ja existe, confira a mensagem. Muitos comandos usam `if not exists` e podem ser reexecutados, mas erros de tabela inexistente normalmente indicam que a etapa das tabelas base foi pulada.

## 7. Autorizar o admin no banco

1. No Supabase, va em `SQL Editor`.
2. Clique em `New query`.
3. Troque `<ADMIN_USER_ID>` pelo `User UID` copiado no Auth.
4. Troque `<ADMIN_EMAIL>` pelo e-mail do admin.
5. Rode:

```sql
insert into public.admin_users (user_id, email)
values ('<ADMIN_USER_ID>', '<ADMIN_EMAIL>')
on conflict (user_id) do update
set email = excluded.email;
```

Validacao rapida:

```sql
select user_id, email, created_at
from public.admin_users;
```

Deve aparecer o seu e-mail.

## 8. Criar as chaves de IA

O backend exige as tres chaves abaixo para iniciar:

- `DEEPSEEK_API_KEY` para o roteador de intencao com DeepSeek V4 Pro.
- `GROQ_API_KEY` para transcricao de audio.
- `GEMINI_API_KEY` para OCR de cupons/imagens.

Crie as contas nos provedores, gere uma chave de API em cada um e guarde os valores. Se voce nao pretende usar audio ou imagem agora, ainda assim o backend atual exige as variaveis configuradas.

## 9. Criar o bot no Telegram

1. Abra o Telegram.
2. Procure por `@BotFather`.
3. Envie `/newbot`.
4. Escolha um nome visivel para o bot.
5. Escolha um username que termine em `bot`, por exemplo `meu_financeiro_bot`.
6. O BotFather vai retornar um token.
7. Guarde esse token como `TELEGRAM_BOT_TOKEN`.

Agora crie o segredo do webhook:

1. Gere uma string aleatoria com letras, numeros, `_` e `-`.
2. Exemplo de formato: `troque-este-valor-por-um-segredo-longo`.
3. Guarde como `TELEGRAM_SECRET_TOKEN`.

O `TELEGRAM_SECRET_TOKEN` nao e o token do bot. Ele e um segundo segredo que o Telegram enviara no header `X-Telegram-Bot-Api-Secret-Token`, e o backend vai conferir antes de processar mensagens.

## 10. Criar o projeto no Google Cloud

1. Acesse `https://console.cloud.google.com`.
2. Crie ou selecione uma conta Google.
3. Crie um projeto.
4. Use um id simples, por exemplo `<GCP_PROJECT_ID>`.
5. Ative billing se o Google pedir. Cloud Run costuma ter camada gratuita, mas o Google Cloud exige billing habilitado para varios recursos.
6. No topo do console, confirme que o projeto selecionado e o projeto novo.

Habilite as APIs:

1. Va em `APIs & Services -> Library`.
2. Habilite:
   - Cloud Run API;
   - Cloud Build API;
   - Artifact Registry API;
   - Secret Manager API.
   - Cloud Tasks API.

## 11. Criar o Artifact Registry

O `cloudbuild.yaml` publica a imagem Docker em um repositorio do Artifact Registry.

1. No Google Cloud, va em `Artifact Registry`.
2. Clique em `Create repository`.
3. Nome: `cloud-run-source-deploy`, ou outro nome se voce tambem for ajustar as substitutions do trigger.
4. Format: `Docker`.
5. Mode: `Standard`.
6. Region: `<REGION>`, por exemplo `southamerica-east1`.
7. Clique em `Create`.

Se voce usar outro nome ou regiao, configure isso no Cloud Build trigger depois, em `Substitution variables`, sem alterar a logica do deploy pelo console.

## 12. Criar secrets no Google Secret Manager

Crie os secrets antes do primeiro deploy. Isso permite que o Cloud Run ja nasca com as variaveis sensiveis corretas.

1. No Google Cloud, va em `Security -> Secret Manager`.
2. Clique em `Create secret`.
3. Crie um secret para cada item:

```text
SUPABASE_KEY
TELEGRAM_BOT_TOKEN
TELEGRAM_SECRET_TOKEN
DEEPSEEK_API_KEY
GROQ_API_KEY
GEMINI_API_KEY
RECURRING_EXPENSES_CRON_SECRET
DATA_ENCRYPTION_KEY
```

Para `DATA_ENCRYPTION_KEY`, gere uma chave Fernet. Se voce tiver Python local:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

`DATA_ENCRYPTION_KEY` e obrigatorio no fluxo dividido. API e worker devem apontar para a mesma versao do secret para que ambos consigam ler o mesmo payload pendente cifrado.

Para `RECURRING_EXPENSES_CRON_SECRET`, gere um valor longo e aleatorio. Voce usara exatamente o mesmo valor no GitHub Actions depois.

## 13. Preflight obrigatorio e identidades dedicadas

Nao configure projeto, regiao nem ADC local. Use sempre os flags explicitos abaixo. Antes de qualquer alteracao, inventarie a conta ativa, os servicos, o trigger e os vinculos da conta padrao:

```bash
gcloud auth list --filter=status:ACTIVE
gcloud services list --enabled --project=financemgmtbot
gcloud run services describe financemgmtbot-git --project=financemgmtbot --region=southamerica-east1 --format=json
gcloud builds triggers list --project=financemgmtbot --region=southamerica-east1 --format=json
gcloud projects get-iam-policy financemgmtbot --project=financemgmtbot --format=json
```

Crie tres identidades de runtime separadas. A identidade dedicada de build
`financemgmtbot-deploy@financemgmtbot.iam.gserviceaccount.com` ja existe e deve
ser reutilizada. Estes comandos alteram IAM e so devem ser executados durante o
rollout aprovado:

```bash
gcloud iam service-accounts create financemgmtbot-api --project=financemgmtbot --display-name="Finance Mgmt API runtime"
gcloud iam service-accounts create financemgmtbot-worker --project=financemgmtbot --display-name="Finance Mgmt Telegram worker"
gcloud iam service-accounts create financemgmtbot-task-invoker --project=financemgmtbot --display-name="Finance Mgmt task invoker"
```

Conceda `Secret Manager Secret Accessor` por secret, nunca no projeto inteiro:

- API runtime: `SUPABASE_KEY`, `TELEGRAM_SECRET_TOKEN`, `recurring-expenses-cron-secret` e `DATA_ENCRYPTION_KEY`.
- Worker runtime: `SUPABASE_KEY`, `TELEGRAM_BOT_TOKEN`, `DEEPSEEK_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY` e `DATA_ENCRYPTION_KEY`.

Exemplo, repetido apenas para os pares acima:

```bash
gcloud secrets add-iam-policy-binding SUPABASE_KEY --project=financemgmtbot --member="serviceAccount:financemgmtbot-api@financemgmtbot.iam.gserviceaccount.com" --role="roles/secretmanager.secretAccessor"
gcloud secrets add-iam-policy-binding SUPABASE_KEY --project=financemgmtbot --member="serviceAccount:financemgmtbot-worker@financemgmtbot.iam.gserviceaccount.com" --role="roles/secretmanager.secretAccessor"
```

O build runtime recebe `roles/run.admin`, `roles/artifactregistry.writer` e `roles/logging.logWriter` nos recursos necessarios e `roles/iam.serviceAccountUser` somente sobre `financemgmtbot-api` e `financemgmtbot-worker`. Para a limpeza de secrets, mantenha o papel customizado restrito com `secretmanager.secrets.get`, `secretmanager.versions.list` e `secretmanager.versions.destroy`. Nao conceda `Editor` nem `Secret Manager Admin`.

Nao retire `Editor` da conta padrao automaticamente. Primeiro confirme que nenhum outro recurso a utiliza; a remocao e uma operacao posterior e separadamente autorizada.

## 14. Criar a fila pausada e preparar o worker privado

Depois de aplicar `20260815_telegram_update_reliability.sql`, habilite a API e crie a fila regional ainda pausada:

```bash
gcloud services enable cloudtasks.googleapis.com --project=financemgmtbot
gcloud tasks queues create telegram-updates --project=financemgmtbot --location=southamerica-east1 --max-attempts=12 --min-backoff=5s --max-backoff=300s --max-retry-duration=3600s --max-concurrent-dispatches=1 --max-dispatches-per-second=1
gcloud tasks queues pause telegram-updates --project=financemgmtbot --location=southamerica-east1
```

Restrinja enqueue, emissao do token OIDC e invocacao do worker:

```bash
gcloud tasks queues add-iam-policy-binding telegram-updates --project=financemgmtbot --location=southamerica-east1 --member="serviceAccount:financemgmtbot-api@financemgmtbot.iam.gserviceaccount.com" --role="roles/cloudtasks.enqueuer"
gcloud iam service-accounts add-iam-policy-binding financemgmtbot-task-invoker@financemgmtbot.iam.gserviceaccount.com --project=financemgmtbot --member="serviceAccount:financemgmtbot-api@financemgmtbot.iam.gserviceaccount.com" --role="roles/iam.serviceAccountUser"
```

O `cloudbuild.yaml` publica uma imagem imutavel e faz rollout primeiro de `financemgmtbot-worker` privado (`ingress=internal`, sem anonimo, concorrencia `1`, timeout `240s`) e depois de `financemgmtbot-git` publico (`concorrencia=10`, timeout `30s`). O worker aplica um budget interno de `150s`; a task usa deadline de `180s`.

O worker registra `media_get_file`, `media_download`, `ocr`, `stt`, `llm` e `telegram_delivery` separadamente. Para investigar uma atualização sem expor conteúdo do cupom, use somente metadados sanitizados:

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.location="southamerica-east1" AND (jsonPayload.update_id=611390377 OR jsonPayload.error_code="ResourceExhausted")' --project=financemgmtbot --freshness=7d --format='value(timestamp,jsonPayload.event,jsonPayload.update_id,jsonPayload.attempt,jsonPayload.stage,jsonPayload.provider,jsonPayload.error_code,jsonPayload.duration_ms)'
```

Repetições de `media_download` ou `ResourceExhausted` para o mesmo `update_id` devem gerar alerta operacional. A criação/alteração de alertas e da fila continua sendo uma operação de infraestrutura separada e exige autorização explícita; este diagnóstico não altera recursos do Google Cloud.

Configure `_SUPABASE_URL`, `_FRONTEND_PUBLIC_URL` e `_FRONTEND_ALLOWED_ORIGIN` no trigger antes do primeiro build. O build falha se essas substitutions nao forem informadas.

## 15. Migrar o trigger e executar o rollout

Antes do build, mova o trigger para a identidade dedicada:

```bash
gcloud builds triggers update github cloudbuild-yaml-09-04-26 --project=financemgmtbot --region=southamerica-east1 --service-account="projects/financemgmtbot/serviceAccounts/financemgmtbot-deploy@financemgmtbot.iam.gserviceaccount.com" --build-config=cloudbuild.yaml
```

Ordem obrigatoria do rollout:

1. aplicar a migration e validar as funcoes RPC como `service_role`;
2. criar identidades e IAM;
3. criar e pausar a fila;
4. executar o build, que publica o worker privado e depois a API:

```bash
gcloud builds submit --project=financemgmtbot --region=southamerica-east1 --service-account="financemgmtbot-deploy@financemgmtbot.iam.gserviceaccount.com" --config=cloudbuild.yaml --substitutions="_SUPABASE_URL=<SUPABASE_URL>,_FRONTEND_PUBLIC_URL=<FRONTEND_URL>,_FRONTEND_ALLOWED_ORIGIN=<FRONTEND_ORIGIN>"
```

5. conceder invocacao somente ao task invoker depois que o worker existir:

```bash
gcloud run services add-iam-policy-binding financemgmtbot-worker --project=financemgmtbot --region=southamerica-east1 --member="serviceAccount:financemgmtbot-task-invoker@financemgmtbot.iam.gserviceaccount.com" --role="roles/run.invoker"
```

6. comprovar que chamada anonima ao worker recebe `401` ou `403` e que o invocador OIDC recebe `200`;
7. liberar a fila somente depois dos testes de autenticacao:

```bash
gcloud tasks queues resume telegram-updates --project=financemgmtbot --location=southamerica-east1
```

Depois do cupom sintetico de validacao, confirme uma task, uma unica pendencia, ledger `completed`, entrega `telegram_delivery_confirmed`, fila vazia e ausencia de novo `504`. Aplique `location=southamerica-east1` no filtro de Logging e confira as duas revisoes e service accounts anexadas. Nunca registre o payload do cupom nessa validacao.

O `cloudbuild.yaml` resolve versoes numericas dos secrets, substitui integralmente os bindings com `--set-secrets` e listas separadas por servico, valida `/api/meta/runtime` e protege versoes ainda referenciadas pelas revisoes dos dois servicos antes da limpeza. Essa substituicao integral e obrigatoria na migracao do servico unificado: `--update-secrets` preservaria bindings antigos e poderia manter credenciais de OCR/LLM na API publica.

### 15.1 Limpeza segura de versoes de secrets

Por padrao, o deploy automatico mantem as 2 versoes habilitadas mais recentes de cada secret gerenciado pelo app e destroi versoes ativas mais antigas. Ele tambem protege versoes ainda referenciadas por revisoes do Cloud Run.

Secrets incluidos na limpeza:

```text
SUPABASE_KEY
TELEGRAM_BOT_TOKEN
TELEGRAM_SECRET_TOKEN
DEEPSEEK_API_KEY
GROQ_API_KEY
GEMINI_API_KEY
recurring-expenses-cron-secret
DATA_ENCRYPTION_KEY
```

`DATA_ENCRYPTION_KEY` e obrigatorio. O script nao destroi versoes criadas ha menos de 7 dias, porque essa chave pode ser necessaria para payloads pendentes de aprovacao.

Para ver o que seria destruido sem executar:

```bash
python3 scripts/prune_secret_versions.py prune \
  --project <GCP_PROJECT_ID> \
  --secret SUPABASE_KEY
```

Para executar manualmente depois de revisar o dry-run:

```bash
python3 scripts/prune_secret_versions.py prune \
  --project <GCP_PROJECT_ID> \
  --secret SUPABASE_KEY \
  --execute
```

Se voce precisar pausar a limpeza automatica, altere a substitution `_PRUNE_SECRET_VERSIONS` para `false` no trigger. A aplicacao continua fazendo deploy normalmente, mas as versoes antigas voltam a acumular custo.

## 16. Configurar GitHub Actions para o frontend

Agora que voce tem `<CLOUD_RUN_URL>`, configure as variaveis publicas do frontend.

1. No GitHub, abra o repositorio.
2. Va em `Settings -> Secrets and variables -> Actions`.
3. Clique na aba `Variables`.
4. Crie:

```text
VITE_API_BASE_URL=<CLOUD_RUN_URL>
VITE_SUPABASE_URL=<SUPABASE_URL>
VITE_SUPABASE_ANON_KEY=<SUPABASE_ANON_KEY>
VITE_ALLOWED_ADMIN_EMAILS=<ADMIN_EMAIL>
```

Nao crie `SUPABASE_KEY` aqui. O frontend usa apenas `anon public`, nunca `service_role`.

O gate de audit do CI roda com `--audit-level=high`. Aceite documentado (16/08/2026): 2 vulnerabilidades moderadas no react-router 6.30.4 (GHSA-wrjc-x8rr-h8h6, GHSA-337j-9hxr-rhxg); a correcao exige migracao breaking para react-router-dom 7.18.2, adiada.

Agora configure os secrets do workflow de despesas recorrentes:

1. Ainda em `Settings -> Secrets and variables -> Actions`.
2. Clique na aba `Secrets`.
3. Crie:

```text
CLOUD_RUN_BASE_URL=<CLOUD_RUN_URL>
RECURRING_EXPENSES_CRON_SECRET=<MESMO_VALOR_DO_SECRET_DO_CLOUD_RUN>
```

## 17. Publicar o GitHub Pages

1. No GitHub, va em `Settings -> Pages`.
2. Em `Source`, selecione `GitHub Actions`.
3. Va em `Actions`.
4. Abra o workflow `Deploy Frontend to GitHub Pages`.
5. Clique em `Run workflow`.
6. Aguarde concluir.
7. Volte em `Settings -> Pages` e copie a URL publicada.

Ela deve ser parecida com:

```text
https://<GITHUB_USER>.github.io/financemgmtbot/
```

Se essa URL for diferente da que voce usou em `FRONTEND_PUBLIC_URL`, atualize o Cloud Run:

```bash
gcloud run services update <SERVICE_NAME> \
  --region <REGION> \
  --update-env-vars "FRONTEND_PUBLIC_URL=<FRONTEND_URL>,FRONTEND_ALLOWED_ORIGINS=<FRONTEND_ORIGIN>"
```

## 18. Configurar Supabase Auth para o Magic Link

Agora que o GitHub Pages existe, ajuste as URLs de login.

1. No Supabase, va em `Authentication -> URL Configuration`.
2. Em `Site URL`, coloque:

```text
<FRONTEND_URL>
```

3. Em `Redirect URLs`, adicione:

```text
<FRONTEND_URL>auth/callback
```

Exemplo:

```text
https://<GITHUB_USER>.github.io/financemgmtbot/auth/callback
```

4. Salve.

Nao deixe `localhost` como Site URL de producao. Isso faz o Magic Link voltar para o computador local em vez do painel publicado.

## 19. Testar o painel web

1. Abra `<FRONTEND_URL>`.
2. Digite `<ADMIN_EMAIL>` na tela de login.
3. Clique para receber o Magic Link.
4. Abra o e-mail recebido.
5. Clique no link.
6. Voce deve voltar para o painel no GitHub Pages.
7. Verifique se o Dashboard, Historico, Aprovacoes e Despesas Recorrentes carregam sem erro.

Se o login funcionar mas a API falhar:

- confirme `VITE_API_BASE_URL` no GitHub Variables;
- confirme `FRONTEND_ALLOWED_ORIGINS` no Cloud Run;
- confirme se `<ADMIN_EMAIL>` esta em `SUPABASE_ADMIN_EMAILS`;
- confirme se o usuario foi inserido em `public.admin_users`;
- veja logs do Cloud Run.

## 20. Configurar o webhook do Telegram

Com o Cloud Run publico, configure o Telegram para enviar mensagens ao backend.

No terminal, rode:

```bash
curl -X POST "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
  -d "url=<CLOUD_RUN_URL>/" \
  -d "secret_token=<TELEGRAM_SECRET_TOKEN>" \
  -d "drop_pending_updates=true"
```

Validacao:

```bash
curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getWebhookInfo"
```

Confira se a URL retornada e `<CLOUD_RUN_URL>/`.

Agora abra o bot no Telegram e envie uma mensagem simples, por exemplo:

```text
gastei 25 reais no mercado hoje
```

Depois confira:

- se o bot respondeu no Telegram;
- se apareceu um registro no painel;
- se os logs do Cloud Run nao mostram erro.

## 21. Testar despesas recorrentes

O workflow `.github/workflows/run-recurring-expenses.yml` chama o endpoint:

```text
POST <CLOUD_RUN_URL>/api/cron/recurring-expenses
```

Ele roda diariamente as `03:05 UTC`, que corresponde a `00:05 BRT`.

Para testar manualmente:

1. No painel, cadastre uma despesa recorrente em `Despesas Recorrentes`.
2. No GitHub, va em `Actions`.
3. Abra `Daily recurring expenses generation`.
4. Clique em `Run workflow`.
5. Opcionalmente informe `data_referencia` no formato `YYYY-MM-DD`.
6. Aguarde o workflow terminar.
7. Abra `Historico` no painel e veja se o gasto foi criado.

Se falhar com autorizacao, confira:

- `RECURRING_EXPENSES_CRON_SECRET` no GitHub Secrets;
- `RECURRING_EXPENSES_CRON_SECRET` no Secret Manager/Cloud Run;
- os dois precisam ser exatamente iguais;
- `CLOUD_RUN_BASE_URL` precisa ser a URL base do Cloud Run, sem caminho extra.

## 22. Checklist final de producao

Antes de entregar para outra pessoa usar, confira:

- `SUPABASE_KEY` aparece somente no Google Secret Manager/Cloud Run.
- `VITE_SUPABASE_ANON_KEY` aparece somente como valor publico do frontend.
- `AUTH_TEST_MODE=false` no Cloud Run.
- `ALLOW_LOCAL_DEV_AUTH=false` no Cloud Run.
- `FRONTEND_PUBLIC_URL=<FRONTEND_URL>` no Cloud Run.
- `FRONTEND_ALLOWED_ORIGINS=<FRONTEND_ORIGIN>` no Cloud Run.
- `SUPABASE_ADMIN_EMAILS=<ADMIN_EMAIL>` no Cloud Run.
- usuario admin existe em `Authentication -> Users`.
- usuario admin existe em `public.admin_users`.
- `Site URL` e `Redirect URLs` do Supabase apontam para GitHub Pages, nao para localhost.
- GitHub Pages abre o painel.
- Magic Link funciona.
- `GET <CLOUD_RUN_URL>/api/meta/runtime` responde.
- Telegram `getWebhookInfo` mostra `<CLOUD_RUN_URL>/`.
- Bot responde a uma mensagem simples.
- Workflow `Daily recurring expenses generation` roda manualmente.
- Cloud Build consegue listar/destroir versoes antigas apenas dos secrets do app.
- Secret Manager fica com no maximo 2 versoes habilitadas por secret do app, salvo versoes protegidas por revisoes do Cloud Run.

## 23. Problemas comuns

### O Magic Link volta para localhost

Corrija no Supabase:

- `Authentication -> URL Configuration -> Site URL`;
- `Redirect URLs`;
- use `<FRONTEND_URL>` e `<FRONTEND_URL>auth/callback`.

### O painel abre, mas tudo da erro de API

Verifique:

- `VITE_API_BASE_URL` no GitHub Variables;
- `FRONTEND_ALLOWED_ORIGINS` no Cloud Run;
- se o Cloud Run esta publico;
- logs do Cloud Run.

### O backend nao inicia

Normalmente falta alguma variavel obrigatoria:

- `TELEGRAM_BOT_TOKEN`;
- `TELEGRAM_SECRET_TOKEN`;
- `SUPABASE_URL`;
- `SUPABASE_KEY`;
- `DEEPSEEK_API_KEY`;
- `GROQ_API_KEY`;
- `GEMINI_API_KEY`.

### O bot recebe mensagem mas nao grava no banco

Verifique:

- tabelas base criadas;
- migrations aplicadas em ordem;
- `SUPABASE_KEY` e `SUPABASE_URL`;
- se a tabela usada no Cloud Run e `gastos`;
- logs do Cloud Run.

### O cron de recorrencias nao cria gasto

Verifique:

- despesa recorrente ativa no painel;
- `dia_mes` e periodo da recorrencia;
- `RECURRING_EXPENSES_CRON_SECRET` igual no GitHub e Cloud Run;
- `CLOUD_RUN_BASE_URL` correto;
- logs do workflow no GitHub Actions.

### O deploy falha na limpeza de secrets

Verifique:

- se a service account `financemgmtbot-deploy` tem permissao de versao apenas nos secrets do app;
- se as substitutions `_SECRET_ID_*` batem com os nomes reais no Secret Manager;
- se `_SECRET_ID_RECURRING_EXPENSES_CRON_SECRET` aponta para `recurring-expenses-cron-secret`, caso esse seja o nome usado no seu projeto;
- se `DATA_ENCRYPTION_KEY` existe e possui uma versao habilitada; se a substitution apontar para outro nome, ajuste antes do proximo deploy.

## 24. Referencias oficiais

- Cloud Run environment variables: `https://cloud.google.com/run/docs/configuring/services/environment-variables`
- Cloud Run secrets: `https://cloud.google.com/run/docs/configuring/services/secrets`
- Cloud Build triggers: `https://cloud.google.com/build/docs/triggers`
- GitHub Pages com Actions: `https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages`
- GitHub Actions secrets: `https://docs.github.com/en/actions/concepts/security/about-secrets`
- Supabase Redirect URLs: `https://supabase.com/docs/guides/auth/redirect-urls`
- Telegram Bot API: `https://core.telegram.org/bots/api`
