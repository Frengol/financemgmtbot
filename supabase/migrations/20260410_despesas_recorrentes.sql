create table if not exists public.despesas_recorrentes (
    id uuid primary key default gen_random_uuid(),
    nome text not null,
    valor numeric(12,2) not null,
    mes_inicio date not null,
    mes_fim date,
    dia_mes integer not null,
    natureza text not null,
    categoria text not null,
    metodo_pagamento text not null,
    conta text not null,
    ativo boolean not null default true,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

alter table public.despesas_recorrentes enable row level security;

create index if not exists despesas_recorrentes_ativo_idx
    on public.despesas_recorrentes (ativo)
    where ativo = true;

create index if not exists despesas_recorrentes_mes_idx
    on public.despesas_recorrentes (mes_inicio, mes_fim)
    where ativo = true;

drop policy if exists "despesas_recorrentes_admin_select" on public.despesas_recorrentes;
create policy "despesas_recorrentes_admin_select"
on public.despesas_recorrentes
for select
to authenticated
using (public.is_admin());

drop policy if exists "despesas_recorrentes_admin_insert" on public.despesas_recorrentes;
create policy "despesas_recorrentes_admin_insert"
on public.despesas_recorrentes
for insert
to authenticated
with check (public.is_admin());

drop policy if exists "despesas_recorrentes_admin_update" on public.despesas_recorrentes;
create policy "despesas_recorrentes_admin_update"
on public.despesas_recorrentes
for update
to authenticated
using (public.is_admin())
with check (public.is_admin());

drop policy if exists "despesas_recorrentes_admin_delete" on public.despesas_recorrentes;
create policy "despesas_recorrentes_admin_delete"
on public.despesas_recorrentes
for delete
to authenticated
using (public.is_admin());

comment on table public.despesas_recorrentes is
'Recurring expenses registry. Each active entry for a given month and day generates a gasto record whose descricao is the recurring expense nome.';
