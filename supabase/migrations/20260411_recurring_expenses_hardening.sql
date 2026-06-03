alter table public.gastos
    add column if not exists recurring_expense_id uuid,
    add column if not exists recurring_reference_date date;

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'gastos_recurring_expense_id_fkey'
          and conrelid = 'public.gastos'::regclass
    ) then
        alter table public.gastos
            add constraint gastos_recurring_expense_id_fkey
            foreign key (recurring_expense_id)
            references public.despesas_recorrentes(id)
            on delete set null;
    end if;
end $$;

create unique index if not exists gastos_recurring_expense_once_idx
    on public.gastos (recurring_expense_id, recurring_reference_date)
    where recurring_expense_id is not null
      and recurring_reference_date is not null;

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'despesas_recorrentes_valor_non_negative'
          and conrelid = 'public.despesas_recorrentes'::regclass
    ) then
        alter table public.despesas_recorrentes
            add constraint despesas_recorrentes_valor_non_negative
            check (valor >= 0);
    end if;
end $$;

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'despesas_recorrentes_dia_mes_range'
          and conrelid = 'public.despesas_recorrentes'::regclass
    ) then
        alter table public.despesas_recorrentes
            add constraint despesas_recorrentes_dia_mes_range
            check (dia_mes between 1 and 31);
    end if;
end $$;

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'despesas_recorrentes_mes_interval_valid'
          and conrelid = 'public.despesas_recorrentes'::regclass
    ) then
        alter table public.despesas_recorrentes
            add constraint despesas_recorrentes_mes_interval_valid
            check (mes_fim is null or mes_fim >= mes_inicio);
    end if;
end $$;

drop policy if exists "despesas_recorrentes_admin_select" on public.despesas_recorrentes;
create policy "despesas_recorrentes_admin_select"
on public.despesas_recorrentes
for select
to authenticated
using ((select public.is_admin()));

drop policy if exists "despesas_recorrentes_admin_insert" on public.despesas_recorrentes;
create policy "despesas_recorrentes_admin_insert"
on public.despesas_recorrentes
for insert
to authenticated
with check ((select public.is_admin()));

drop policy if exists "despesas_recorrentes_admin_update" on public.despesas_recorrentes;
create policy "despesas_recorrentes_admin_update"
on public.despesas_recorrentes
for update
to authenticated
using ((select public.is_admin()))
with check ((select public.is_admin()));

drop policy if exists "despesas_recorrentes_admin_delete" on public.despesas_recorrentes;
create policy "despesas_recorrentes_admin_delete"
on public.despesas_recorrentes
for delete
to authenticated
using ((select public.is_admin()));
