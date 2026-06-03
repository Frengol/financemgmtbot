create table if not exists public.admin_web_sessions (
    session_id_hash text primary key,
    user_id uuid not null references auth.users(id) on delete cascade,
    email text,
    created_at timestamptz not null default timezone('utc', now()),
    last_seen_at timestamptz not null default timezone('utc', now()),
    expires_at timestamptz not null,
    revoked_at timestamptz,
    user_agent_hash text,
    ip_hash text
);

alter table public.admin_web_sessions enable row level security;

create index if not exists admin_web_sessions_expires_at_idx
    on public.admin_web_sessions (expires_at)
    where revoked_at is null;

create index if not exists admin_web_sessions_user_id_idx
    on public.admin_web_sessions (user_id);

alter table public.cache_aprovacao
    add column if not exists kind text,
    add column if not exists payload_ciphertext text,
    add column if not exists payload_key_version text,
    add column if not exists preview_json jsonb not null default '{}'::jsonb,
    add column if not exists expires_at timestamptz,
    add column if not exists origin_chat_id text,
    add column if not exists origin_user_id text;

update public.cache_aprovacao
set kind = case
        when kind is not null then kind
        when jsonb_typeof(payload) = 'object' and payload ? 'ids' then 'delete_confirmation'
        else 'receipt_batch'
    end,
    expires_at = coalesce(
        expires_at,
        case
            when created_at is not null then created_at + interval '24 hours'
            else timezone('utc', now()) + interval '24 hours'
        end
    ),
    preview_json = coalesce(preview_json, '{}'::jsonb)
where kind is null
   or expires_at is null
   or preview_json is null;

alter table public.cache_aprovacao
    alter column kind set default 'receipt_batch',
    alter column expires_at set default timezone('utc', now()) + interval '24 hours',
    alter column preview_json set default '{}'::jsonb;

create index if not exists cache_aprovacao_expires_at_idx
    on public.cache_aprovacao (expires_at);

create index if not exists cache_aprovacao_kind_idx
    on public.cache_aprovacao (kind);

comment on table public.admin_web_sessions is
'Server-side admin web sessions used by the BFF flow. Store only opaque session hashes and expiry metadata.';
