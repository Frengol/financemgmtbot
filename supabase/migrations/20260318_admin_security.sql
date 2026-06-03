create table if not exists public.admin_users (
    user_id uuid primary key references auth.users(id) on delete cascade,
    email text unique not null,
    created_at timestamptz not null default timezone('utc', now())
);

alter table public.admin_users enable row level security;

create or replace function public.is_admin()
returns boolean
language sql
stable
as $$
    select exists (
        select 1
        from public.admin_users
        where user_id = auth.uid()
    );
$$;

drop policy if exists "admin_users_select_own" on public.admin_users;
create policy "admin_users_select_own"
on public.admin_users
for select
to authenticated
using (user_id = auth.uid());

alter table public.gastos enable row level security;
alter table public.cache_aprovacao enable row level security;
alter table public.webhook_idempotencia enable row level security;

drop policy if exists "gastos_admin_select" on public.gastos;
create policy "gastos_admin_select"
on public.gastos
for select
to authenticated
using (public.is_admin());

drop policy if exists "gastos_admin_insert" on public.gastos;
create policy "gastos_admin_insert"
on public.gastos
for insert
to authenticated
with check (public.is_admin());

drop policy if exists "gastos_admin_update" on public.gastos;
create policy "gastos_admin_update"
on public.gastos
for update
to authenticated
using (public.is_admin())
with check (public.is_admin());

drop policy if exists "gastos_admin_delete" on public.gastos;
create policy "gastos_admin_delete"
on public.gastos
for delete
to authenticated
using (public.is_admin());

drop policy if exists "cache_aprovacao_admin_select" on public.cache_aprovacao;
create policy "cache_aprovacao_admin_select"
on public.cache_aprovacao
for select
to authenticated
using (public.is_admin());

drop policy if exists "cache_aprovacao_admin_insert" on public.cache_aprovacao;
create policy "cache_aprovacao_admin_insert"
on public.cache_aprovacao
for insert
to authenticated
with check (public.is_admin());

drop policy if exists "cache_aprovacao_admin_update" on public.cache_aprovacao;
create policy "cache_aprovacao_admin_update"
on public.cache_aprovacao
for update
to authenticated
using (public.is_admin())
with check (public.is_admin());

drop policy if exists "cache_aprovacao_admin_delete" on public.cache_aprovacao;
create policy "cache_aprovacao_admin_delete"
on public.cache_aprovacao
for delete
to authenticated
using (public.is_admin());

create table if not exists public.auditoria_admin (
    id uuid primary key default gen_random_uuid(),
    actor_user_id uuid,
    actor_email text,
    action text not null,
    target_table text not null,
    target_id text not null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now())
);

alter table public.auditoria_admin enable row level security;

drop policy if exists "auditoria_admin_select" on public.auditoria_admin;
create policy "auditoria_admin_select"
on public.auditoria_admin
for select
to authenticated
using (public.is_admin());

comment on table public.admin_users is
'Seed this table with the auth.users row that should access the admin SPA. Example: insert into public.admin_users (user_id, email) values (''<AUTH_USER_ID>'', ''admin@example.com'');';
