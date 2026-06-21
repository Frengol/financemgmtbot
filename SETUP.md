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
| `DATA_ENCRYPTION_KEY` | `DATA_ENCRYPTION_KEY` | opcional, recomendado para criptografia estavel dos payloads pendentes |

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

Se nao quiser configurar `DATA_ENCRYPTION_KEY` agora, o backend consegue derivar uma chave a partir de outros segredos. Ainda assim, para producao propria, e melhor criar e manter um valor fixo.

Para `RECURRING_EXPENSES_CRON_SECRET`, gere um valor longo e aleatorio. Voce usara exatamente o mesmo valor no GitHub Actions depois.

## 13. Criar as service accounts

Crie uma service account para o Cloud Run rodar a aplicacao:

1. No Google Cloud, va em `IAM & Admin -> Service Accounts`.
2. Clique em `Create service account`.
3. Nome: `cloud-run-financemgmtbot-runtime`.
4. Crie a conta.
5. Va em `IAM`.
6. Conceda a ela o papel `Secret Manager Secret Accessor`.

Essa conta e a identidade do backend em execucao. Sem esse acesso, o Cloud Run pode subir sem conseguir ler os secrets.

O Cloud Build precisa de permissao para construir imagem, publicar no Artifact Registry e atualizar o Cloud Run.

1. No Google Cloud, va em `IAM & Admin -> Service Accounts`.
2. Clique em `Create service account`.
3. Nome: `cloud-build-financemgmtbot`.
4. Crie a conta.
5. Va em `IAM`.
6. Conceda a essa service account os papeis:
   - `Artifact Registry Writer`;
   - `Cloud Run Admin`;
   - `Service Account User` sobre a conta `cloud-run-financemgmtbot-runtime`;
   - `Logs Writer`.

Para a limpeza automatica de versoes antigas do Secret Manager, conceda tambem permissao apenas nos secrets da aplicacao:

- opcao simples: `Secret Manager Secret Version Manager` em cada secret do app;
- opcao mais restrita: papel customizado com `secretmanager.secrets.get`, `secretmanager.versions.list` e `secretmanager.versions.destroy`.

Nao conceda `Secret Manager Admin` ao Cloud Build so por causa dessa limpeza. Nao inclua secrets gerenciados pelo Google, como secrets de Developer Connect/GitHub.

Para um ambiente mais rigoroso, limite cada papel apenas aos recursos necessarios. Para o primeiro setup de uma pessoa leiga, o importante e nao usar uma conta pessoal no trigger.

## 14. Fazer o primeiro deploy no Cloud Run

O primeiro deploy precisa criar o servico e deixar variaveis/secrets corretos. Depois disso, o `cloudbuild.yaml` consegue atualizar a imagem e preservar a configuracao do servico.

O caminho mais direto e usar o Cloud Shell do Google:

1. No Google Cloud Console, clique no icone `Activate Cloud Shell`.
2. Rode os comandos abaixo, trocando os placeholders.

```bash
gcloud config set project <GCP_PROJECT_ID>
gcloud config set run/region <REGION>

git clone https://github.com/<GITHUB_USER>/<REPO_NAME>.git
cd <REPO_NAME>

gcloud builds submit \
  --tag <REGION>-docker.pkg.dev/<GCP_PROJECT_ID>/cloud-run-source-deploy/financemgmtbot-git:initial
```

Depois que a imagem for enviada, crie o servico no Cloud Run:

```bash
gcloud run deploy <SERVICE_NAME> \
  --image <REGION>-docker.pkg.dev/<GCP_PROJECT_ID>/cloud-run-source-deploy/financemgmtbot-git:initial \
  --region <REGION> \
  --platform managed \
  --allow-unauthenticated \
  --service-account cloud-run-financemgmtbot-runtime@<GCP_PROJECT_ID>.iam.gserviceaccount.com \
  --set-env-vars "SUPABASE_URL=<SUPABASE_URL>,SUPABASE_ADMIN_EMAILS=<ADMIN_EMAIL>,SUPABASE_ADMIN_USER_IDS=,SUPABASE_GASTOS_TABLE=gastos,FRONTEND_PUBLIC_URL=<FRONTEND_URL>,FRONTEND_ALLOWED_ORIGINS=<FRONTEND_ORIGIN>,AUTH_TEST_MODE=false,ALLOW_LOCAL_DEV_AUTH=false" \
  --update-secrets "SUPABASE_KEY=SUPABASE_KEY:1,TELEGRAM_BOT_TOKEN=TELEGRAM_BOT_TOKEN:1,TELEGRAM_SECRET_TOKEN=TELEGRAM_SECRET_TOKEN:1,DEEPSEEK_API_KEY=DEEPSEEK_API_KEY:1,GROQ_API_KEY=GROQ_API_KEY:1,GEMINI_API_KEY=GEMINI_API_KEY:1,RECURRING_EXPENSES_CRON_SECRET=recurring-expenses-cron-secret:1,DATA_ENCRYPTION_KEY=DATA_ENCRYPTION_KEY:1"
```

Exemplo de valores:

```text
<FRONTEND_URL> = https://<GITHUB_USER>.github.io/financemgmtbot/
<FRONTEND_ORIGIN> = https://<GITHUB_USER>.github.io
```

No final, o terminal mostrara a URL do Cloud Run. Guarde esse valor como `<CLOUD_RUN_URL>`.

Validacao rapida:

```bash
curl "<CLOUD_RUN_URL>/api/meta/runtime"
```

Se o servico responder JSON, o backend subiu. Se der erro de startup, revise as variaveis obrigatorias e os secrets.

## 15. Criar o trigger do Cloud Build para proximos deploys

Depois do primeiro deploy, crie um trigger para usar o `cloudbuild.yaml`.

1. No Google Cloud, va em `Cloud Build -> Triggers`.
2. Clique em `Create trigger`.
3. Nome: `deploy-financemgmtbot-cloud-run`.
4. Evento: push na branch principal, normalmente `main`.
5. Conecte o repositorio GitHub.
6. Em `Configuration`, escolha `Cloud Build configuration file`.
7. Local do arquivo: `cloudbuild.yaml`.
8. Em `Service account`, selecione `cloud-build-financemgmtbot`.
9. Confira as substitutions:
   - `_AR_HOSTNAME`: `<REGION>-docker.pkg.dev`;
   - `_AR_REPOSITORY`: `cloud-run-source-deploy`;
   - `_IMAGE_NAME`: `financemgmtbot-git` ou o nome que voce quiser para a imagem;
   - `_SERVICE_NAME`: `<SERVICE_NAME>`;
   - `_REGION`: `<REGION>`;
   - `_SECRET_ID_SUPABASE_KEY`: `SUPABASE_KEY`;
   - `_SECRET_ID_TELEGRAM_BOT_TOKEN`: `TELEGRAM_BOT_TOKEN`;
   - `_SECRET_ID_TELEGRAM_SECRET_TOKEN`: `TELEGRAM_SECRET_TOKEN`;
   - `_SECRET_ID_DEEPSEEK_API_KEY`: `DEEPSEEK_API_KEY`;
   - `_SECRET_ID_GROQ_API_KEY`: `GROQ_API_KEY`;
   - `_SECRET_ID_GEMINI_API_KEY`: `GEMINI_API_KEY`;
   - `_SECRET_ID_RECURRING_EXPENSES_CRON_SECRET`: `recurring-expenses-cron-secret`;
   - `_SECRET_ID_DATA_ENCRYPTION_KEY`: `DATA_ENCRYPTION_KEY`;
   - `_PRUNE_SECRET_VERSIONS`: `true`.
10. Salve.

O `cloudbuild.yaml` resolve a versao numerica habilitada de cada secret antes do deploy, aplica essas versoes no Cloud Run, valida `/api/meta/runtime` e depois remove versoes antigas. Ele nao le valores de secrets e nao imprime payloads.

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

`DATA_ENCRYPTION_KEY` e opcional. Se existir, o script nao destroi versoes criadas ha menos de 7 dias, porque essa chave pode ser necessaria para payloads pendentes de aprovacao.

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

- se a service account `cloud-build-financemgmtbot` tem permissao de versao apenas nos secrets do app;
- se as substitutions `_SECRET_ID_*` batem com os nomes reais no Secret Manager;
- se `_SECRET_ID_RECURRING_EXPENSES_CRON_SECRET` aponta para `recurring-expenses-cron-secret`, caso esse seja o nome usado no seu projeto;
- se `DATA_ENCRYPTION_KEY` existe. Ele e opcional, mas, se a substitution apontar para outro nome, ajuste antes do proximo deploy.

## 24. Referencias oficiais

- Cloud Run environment variables: `https://cloud.google.com/run/docs/configuring/services/environment-variables`
- Cloud Run secrets: `https://cloud.google.com/run/docs/configuring/services/secrets`
- Cloud Build triggers: `https://cloud.google.com/build/docs/triggers`
- GitHub Pages com Actions: `https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages`
- GitHub Actions secrets: `https://docs.github.com/en/actions/concepts/security/about-secrets`
- Supabase Redirect URLs: `https://supabase.com/docs/guides/auth/redirect-urls`
- Telegram Bot API: `https://core.telegram.org/bots/api`
