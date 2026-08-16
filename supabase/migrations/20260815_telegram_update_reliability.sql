-- Durable Telegram processing ledger and idempotent financial effects.
-- Apply before deploying either Cloud Run service.

alter table public.webhook_idempotencia
    add column if not exists status text,
    add column if not exists attempt_count integer not null default 0,
    add column if not exists lease_owner text,
    add column if not exists lease_expires_at timestamptz,
    add column if not exists stage text,
    add column if not exists error_code text,
    add column if not exists progress_message_id bigint,
    add column if not exists started_at timestamptz,
    add column if not exists completed_at timestamptz,
    add column if not exists updated_at timestamptz not null default timezone('utc', now());

update public.webhook_idempotencia
set status = 'completed',
    completed_at = coalesce(completed_at, created_at),
    updated_at = coalesce(updated_at, created_at)
where status is null;

alter table public.webhook_idempotencia
    alter column status set default 'completed',
    alter column status set not null;

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'webhook_idempotencia_status_check'
          and conrelid = 'public.webhook_idempotencia'::regclass
    ) then
        alter table public.webhook_idempotencia
            add constraint webhook_idempotencia_status_check
            check (status in ('processing', 'retryable_failed', 'completed', 'terminal_failed'));
    end if;
end;
$$;

create index if not exists webhook_idempotencia_lease_idx
    on public.webhook_idempotencia (lease_expires_at)
    where status = 'processing';

alter table public.gastos
    add column if not exists source_update_id bigint,
    add column if not exists source_record_key text,
    add column if not exists source_origin_chat_id bigint;

create unique index if not exists gastos_source_effect_uidx
    on public.gastos (source_update_id, source_record_key);

alter table public.cache_aprovacao
    add column if not exists source_update_id bigint;

create unique index if not exists cache_aprovacao_source_update_uidx
    on public.cache_aprovacao (source_update_id);

create or replace function public.claim_webhook_update(
    p_update_id bigint,
    p_lease_owner text,
    p_lease_seconds integer default 180
)
returns table (
    claimed boolean,
    status text,
    attempt_count integer,
    progress_message_id bigint
)
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    claimed_row public.webhook_idempotencia%rowtype;
begin
    if p_update_id is null or coalesce(length(p_lease_owner), 0) < 16 then
        raise exception 'invalid ledger claim arguments';
    end if;
    if p_lease_seconds < 30 or p_lease_seconds > 900 then
        raise exception 'invalid ledger lease duration';
    end if;

    insert into public.webhook_idempotencia (
        update_id,
        status,
        attempt_count,
        lease_owner,
        lease_expires_at,
        stage,
        error_code,
        started_at,
        completed_at,
        updated_at
    ) values (
        p_update_id,
        'processing',
        1,
        p_lease_owner,
        timezone('utc', now()) + make_interval(secs => p_lease_seconds),
        'claimed',
        null,
        timezone('utc', now()),
        null,
        timezone('utc', now())
    )
    on conflict (update_id) do update
    set status = 'processing',
        attempt_count = public.webhook_idempotencia.attempt_count + 1,
        lease_owner = excluded.lease_owner,
        lease_expires_at = excluded.lease_expires_at,
        stage = 'claimed',
        error_code = null,
        started_at = coalesce(public.webhook_idempotencia.started_at, excluded.started_at),
        completed_at = null,
        updated_at = excluded.updated_at
    where public.webhook_idempotencia.status = 'retryable_failed'
       or (
           public.webhook_idempotencia.status = 'processing'
           and public.webhook_idempotencia.lease_expires_at <= timezone('utc', now())
       )
    returning * into claimed_row;

    if found then
        return query
        select true, claimed_row.status, claimed_row.attempt_count, claimed_row.progress_message_id;
        return;
    end if;

    select *
    into claimed_row
    from public.webhook_idempotencia ledger
    where ledger.update_id = p_update_id;

    return query
    select false, claimed_row.status, claimed_row.attempt_count, claimed_row.progress_message_id;
end;
$$;

create or replace function public.update_webhook_stage(
    p_update_id bigint,
    p_lease_owner text,
    p_stage text,
    p_progress_message_id bigint default null
)
returns boolean
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    update public.webhook_idempotencia
    set stage = left(coalesce(p_stage, 'processing'), 80),
        progress_message_id = coalesce(p_progress_message_id, progress_message_id),
        updated_at = timezone('utc', now())
    where update_id = p_update_id
      and status = 'processing'
      and lease_owner = p_lease_owner;
    return found;
end;
$$;

create or replace function public.complete_webhook_update(
    p_update_id bigint,
    p_lease_owner text
)
returns boolean
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    update public.webhook_idempotencia
    set status = 'completed',
        stage = 'completed',
        lease_owner = null,
        lease_expires_at = null,
        error_code = null,
        completed_at = timezone('utc', now()),
        updated_at = timezone('utc', now())
    where update_id = p_update_id
      and status = 'processing'
      and lease_owner = p_lease_owner;
    return found;
end;
$$;

create or replace function public.fail_webhook_update(
    p_update_id bigint,
    p_lease_owner text,
    p_stage text,
    p_error_code text
)
returns boolean
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    update public.webhook_idempotencia
    set status = 'retryable_failed',
        stage = left(coalesce(p_stage, 'processing'), 80),
        error_code = left(coalesce(p_error_code, 'unknown'), 80),
        lease_owner = null,
        lease_expires_at = null,
        updated_at = timezone('utc', now())
    where update_id = p_update_id
      and status = 'processing'
      and lease_owner = p_lease_owner;
    return found;
end;
$$;

create or replace function public.terminal_fail_webhook_update(
    p_update_id bigint,
    p_lease_owner text,
    p_stage text,
    p_error_code text
)
returns boolean
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    update public.webhook_idempotencia
    set status = 'terminal_failed',
        stage = left(coalesce(p_stage, 'processing'), 80),
        error_code = left(coalesce(p_error_code, 'unknown'), 80),
        lease_owner = null,
        lease_expires_at = null,
        completed_at = timezone('utc', now()),
        updated_at = timezone('utc', now())
    where update_id = p_update_id
      and status = 'processing'
      and lease_owner = p_lease_owner;
    return found;
end;
$$;

revoke all on function public.claim_webhook_update(bigint, text, integer) from public, anon, authenticated;
revoke all on function public.update_webhook_stage(bigint, text, text, bigint) from public, anon, authenticated;
revoke all on function public.complete_webhook_update(bigint, text) from public, anon, authenticated;
revoke all on function public.fail_webhook_update(bigint, text, text, text) from public, anon, authenticated;
revoke all on function public.terminal_fail_webhook_update(bigint, text, text, text) from public, anon, authenticated;

grant execute on function public.claim_webhook_update(bigint, text, integer) to service_role;
grant execute on function public.update_webhook_stage(bigint, text, text, bigint) to service_role;
grant execute on function public.complete_webhook_update(bigint, text) to service_role;
grant execute on function public.fail_webhook_update(bigint, text, text, text) to service_role;
grant execute on function public.terminal_fail_webhook_update(bigint, text, text, text) to service_role;

comment on table public.webhook_idempotencia is
'Stateful Telegram update ledger. Claims and transitions are available only to the service_role runtime.';
