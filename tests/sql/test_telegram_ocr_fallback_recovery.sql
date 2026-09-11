\set ON_ERROR_STOP on

create extension if not exists pgcrypto;
create extension if not exists dblink;

do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'anon') then
        create role anon nologin;
    end if;
    if not exists (select 1 from pg_roles where rolname = 'authenticated') then
        create role authenticated nologin;
    end if;
    if not exists (select 1 from pg_roles where rolname = 'service_role') then
        create role service_role nologin;
    end if;
end;
$$;

create table public.gastos (
    id uuid primary key default gen_random_uuid(),
    data date not null,
    valor numeric(12,2) not null,
    natureza text not null,
    categoria text not null,
    descricao text not null,
    metodo_pagamento text not null,
    conta text not null,
    created_at timestamptz not null default timezone('utc', now())
);
create table public.cache_aprovacao (
    id text primary key,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now())
);
create table public.webhook_idempotencia (
    update_id bigint primary key,
    created_at timestamptz not null default timezone('utc', now())
);

\ir ../../supabase/migrations/20260815_telegram_update_reliability.sql

insert into public.gastos (data, valor, natureza, categoria, descricao, metodo_pagamento, conta)
values (date '2026-09-08', 52.00, 'Essencial', 'Mercado', 'fixture', 'Pix', 'Carteira');
insert into public.cache_aprovacao (id, payload)
values ('fixture-pending', '{"test":true}'::jsonb);
insert into public.webhook_idempotencia (update_id, status, attempt_count, stage, completed_at)
values (42, 'completed', 1, 'completed', timezone('utc', now()));

create temporary table preserved_before as
select
    (select jsonb_agg(to_jsonb(row_data) order by row_data.id::text) from public.gastos row_data) as gastos,
    (select jsonb_agg(to_jsonb(row_data) order by row_data.id) from public.cache_aprovacao row_data) as pendencias,
    (select status from public.webhook_idempotencia where update_id = 42) as completed_status;

\ir ../../supabase/migrations/20260908_telegram_ocr_fallback_recovery.sql
\ir ../../supabase/migrations/20260908_telegram_ocr_fallback_recovery.sql

do $$
declare
    current_snapshot record;
begin
    select
        (select jsonb_agg(to_jsonb(row_data) order by row_data.id::text) from public.gastos row_data) as gastos,
        (select jsonb_agg(to_jsonb(row_data) order by row_data.id) from public.cache_aprovacao row_data) as pendencias,
        (select status from public.webhook_idempotencia where update_id = 42) as completed_status
    into current_snapshot;

    if current_snapshot.gastos is distinct from (select gastos from preserved_before)
       or current_snapshot.pendencias is distinct from (select pendencias from preserved_before)
       or current_snapshot.completed_status is distinct from (select completed_status from preserved_before) then
        raise exception 'migration changed existing financial, pending, or completed data';
    end if;

    if has_function_privilege('anon', 'public.claim_webhook_update_v2(bigint,text,integer)', 'EXECUTE')
       or has_function_privilege('authenticated', 'public.claim_webhook_update_v2(bigint,text,integer)', 'EXECUTE')
       or not has_function_privilege('service_role', 'public.claim_webhook_update_v2(bigint,text,integer)', 'EXECUTE') then
        raise exception 'claim RPC permissions are not service-role-only';
    end if;
end;
$$;

do $$
declare
    result record;
begin
    select * into result from public.claim_webhook_update_v2(100, 'owner-aaaaaaaaaaaaaaaa', 300);
    if not result.claimed or result.ocr_round_count <> 0 then
        raise exception 'initial claim failed';
    end if;

    select * into result from public.claim_webhook_update_v2(100, 'owner-bbbbbbbbbbbbbbbb', 300);
    if result.claimed then
        raise exception 'active lease was stolen';
    end if;

    update public.webhook_idempotencia
    set lease_expires_at = timezone('utc', now()) - interval '1 second'
    where update_id = 100;
    select * into result from public.claim_webhook_update_v2(100, 'owner-bbbbbbbbbbbbbbbb', 300);
    if not result.claimed then
        raise exception 'expired lease was not reclaimed';
    end if;

    for expected_round in 1..3 loop
        select * into result from public.reserve_webhook_ocr_round_v2(100, 'owner-bbbbbbbbbbbbbbbb');
        if not result.reserved or result.ocr_round_count <> expected_round then
            raise exception 'OCR round % was not reserved', expected_round;
        end if;
    end loop;
    select * into result from public.reserve_webhook_ocr_round_v2(100, 'owner-bbbbbbbbbbbbbbbb');
    if result.reserved or result.ocr_round_count <> 3 then
        raise exception 'OCR round limit was not enforced';
    end if;

    if not public.reset_webhook_ocr_rounds_v2(100, 'owner-bbbbbbbbbbbbbbbb') then
        raise exception 'OCR round reset failed';
    end if;
    if (select ocr_round_count from public.webhook_idempotencia where update_id = 100) <> 0 then
        raise exception 'OCR round reset was not persisted';
    end if;

    if not public.prepare_webhook_terminal_failure_v2(
        100,
        'owner-bbbbbbbbbbbbbbbb',
        'ocr_unavailable',
        '503'
    ) then
        raise exception 'terminal decision was not persisted';
    end if;
    if not public.fail_webhook_update_v2(100, 'owner-bbbbbbbbbbbbbbbb', 'telegram_delivery', 'timeout') then
        raise exception 'terminal delivery retry state was not persisted';
    end if;

    select * into result from public.claim_webhook_update_v2(100, 'owner-cccccccccccccccc', 300);
    if not result.claimed or result.terminal_reason <> 'ocr_unavailable' then
        raise exception 'terminal delivery was not resumed';
    end if;
    if not public.terminal_fail_webhook_update_v2(
        100,
        'owner-cccccccccccccccc',
        'telegram_delivery',
        '503',
        true
    ) then
        raise exception 'terminal delivery completion failed';
    end if;
    if not (select terminal_delivery_confirmed from public.webhook_idempotencia where update_id = 100) then
        raise exception 'terminal delivery confirmation was not persisted';
    end if;
end;
$$;

create temporary table concurrent_claim_results (claimed boolean not null);
select dblink_connect('claim_a', 'dbname=financemgmtbot user=postgres password=test-only host=127.0.0.1');
select dblink_send_query(
    'claim_a',
    $$select claimed from public.claim_webhook_update_v2(200, 'owner-concurrent-aaaa', 300)$$
);
insert into concurrent_claim_results
select claimed from public.claim_webhook_update_v2(200, 'owner-concurrent-bbbb', 300);
insert into concurrent_claim_results
select claimed from dblink_get_result('claim_a') as result(claimed boolean);
select dblink_disconnect('claim_a');

do $$
begin
    if (select count(*) from concurrent_claim_results where claimed) <> 1 then
        raise exception 'concurrent claims did not produce exactly one owner';
    end if;
end;
$$;
