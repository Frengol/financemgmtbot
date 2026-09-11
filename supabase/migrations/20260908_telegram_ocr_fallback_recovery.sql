-- Durable OCR rounds and terminal-notice delivery for Telegram receipt updates.
-- Apply before deploying code that calls the v2 RPCs.

begin;
set local lock_timeout = '5s';
set local statement_timeout = '60s';

alter table public.webhook_idempotencia
    add column if not exists ocr_round_count integer not null default 0,
    add column if not exists terminal_reason text,
    add column if not exists terminal_delivery_confirmed boolean;

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'webhook_idempotencia_ocr_round_count_check'
          and conrelid = 'public.webhook_idempotencia'::regclass
    ) then
        alter table public.webhook_idempotencia
            add constraint webhook_idempotencia_ocr_round_count_check
            check (ocr_round_count between 0 and 3) not valid;
    end if;

    if not exists (
        select 1
        from pg_constraint
        where conname = 'webhook_idempotencia_terminal_reason_check'
          and conrelid = 'public.webhook_idempotencia'::regclass
    ) then
        alter table public.webhook_idempotencia
            add constraint webhook_idempotencia_terminal_reason_check
            check (
                terminal_reason is null
                or terminal_reason in (
                    'ocr_unavailable',
                    'ocr_rejected',
                    'telegram_delivery_permanent'
                )
            ) not valid;
    end if;

    if not exists (
        select 1
        from pg_constraint
        where conname = 'webhook_idempotencia_terminal_delivery_check'
          and conrelid = 'public.webhook_idempotencia'::regclass
    ) then
        alter table public.webhook_idempotencia
            add constraint webhook_idempotencia_terminal_delivery_check
            check (terminal_delivery_confirmed is null or terminal_reason is not null) not valid;
    end if;
end;
$$;

alter table public.webhook_idempotencia
    validate constraint webhook_idempotencia_ocr_round_count_check;
alter table public.webhook_idempotencia
    validate constraint webhook_idempotencia_terminal_reason_check;
alter table public.webhook_idempotencia
    validate constraint webhook_idempotencia_terminal_delivery_check;

create or replace function public.claim_webhook_update_v2(
    p_update_id bigint,
    p_lease_owner text,
    p_lease_seconds integer default 300
)
returns table (
    claimed boolean,
    status text,
    attempt_count integer,
    progress_message_id bigint,
    ocr_round_count integer,
    terminal_reason text,
    error_code text
)
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    claimed_row public.webhook_idempotencia%rowtype;
    did_claim boolean := false;
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
        ocr_round_count,
        terminal_reason,
        terminal_delivery_confirmed,
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
        0,
        null,
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
        stage = case
            when public.webhook_idempotencia.terminal_reason is null then 'claimed'
            else 'terminal_delivery_pending'
        end,
        error_code = case
            when public.webhook_idempotencia.terminal_reason is null then null
            else public.webhook_idempotencia.error_code
        end,
        started_at = coalesce(public.webhook_idempotencia.started_at, excluded.started_at),
        completed_at = null,
        updated_at = excluded.updated_at
    where public.webhook_idempotencia.status = 'retryable_failed'
       or (
           public.webhook_idempotencia.status = 'processing'
           and public.webhook_idempotencia.lease_expires_at <= timezone('utc', now())
       )
    returning * into claimed_row;

    did_claim := found;

    if not did_claim then
        select *
        into claimed_row
        from public.webhook_idempotencia ledger
        where ledger.update_id = p_update_id;
    end if;

    return query
    select
        did_claim,
        claimed_row.status,
        claimed_row.attempt_count,
        claimed_row.progress_message_id,
        claimed_row.ocr_round_count,
        claimed_row.terminal_reason,
        claimed_row.error_code;
end;
$$;

create or replace function public.update_webhook_stage_v2(
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
    set stage = case
            when terminal_reason is null then left(coalesce(p_stage, 'processing'), 80)
            else 'terminal_delivery_pending'
        end,
        progress_message_id = coalesce(p_progress_message_id, progress_message_id),
        updated_at = timezone('utc', now())
    where update_id = p_update_id
      and status = 'processing'
      and lease_owner = p_lease_owner;
    return found;
end;
$$;

create or replace function public.reserve_webhook_ocr_round_v2(
    p_update_id bigint,
    p_lease_owner text
)
returns table (reserved boolean, ocr_round_count integer)
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    next_round integer;
begin
    update public.webhook_idempotencia
    set ocr_round_count = public.webhook_idempotencia.ocr_round_count + 1,
        stage = 'ocr',
        updated_at = timezone('utc', now())
    where update_id = p_update_id
      and status = 'processing'
      and lease_owner = p_lease_owner
      and terminal_reason is null
      and public.webhook_idempotencia.ocr_round_count < 3
    returning public.webhook_idempotencia.ocr_round_count into next_round;

    if found then
        return query select true, next_round;
        return;
    end if;

    select ledger.ocr_round_count
    into next_round
    from public.webhook_idempotencia ledger
    where ledger.update_id = p_update_id;

    return query select false, coalesce(next_round, 0);
end;
$$;

create or replace function public.reset_webhook_ocr_rounds_v2(
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
    set ocr_round_count = 0,
        stage = 'ocr_completed',
        error_code = null,
        updated_at = timezone('utc', now())
    where update_id = p_update_id
      and status = 'processing'
      and lease_owner = p_lease_owner
      and terminal_reason is null;
    return found;
end;
$$;

create or replace function public.prepare_webhook_terminal_failure_v2(
    p_update_id bigint,
    p_lease_owner text,
    p_terminal_reason text,
    p_error_code text
)
returns boolean
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    if p_terminal_reason not in (
        'ocr_unavailable',
        'ocr_rejected',
        'telegram_delivery_permanent'
    ) then
        raise exception 'invalid terminal reason';
    end if;

    update public.webhook_idempotencia
    set terminal_reason = p_terminal_reason,
        terminal_delivery_confirmed = null,
        stage = 'terminal_delivery_pending',
        error_code = left(coalesce(p_error_code, 'unknown'), 80),
        updated_at = timezone('utc', now())
    where update_id = p_update_id
      and status = 'processing'
      and lease_owner = p_lease_owner;
    return found;
end;
$$;

create or replace function public.complete_webhook_update_v2(
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
        ocr_round_count = 0,
        terminal_reason = null,
        terminal_delivery_confirmed = null,
        completed_at = timezone('utc', now()),
        updated_at = timezone('utc', now())
    where update_id = p_update_id
      and status = 'processing'
      and lease_owner = p_lease_owner
      and terminal_reason is null;
    return found;
end;
$$;

create or replace function public.fail_webhook_update_v2(
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
        stage = case
            when terminal_reason is null then left(coalesce(p_stage, 'processing'), 80)
            else 'terminal_delivery_pending'
        end,
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

create or replace function public.terminal_fail_webhook_update_v2(
    p_update_id bigint,
    p_lease_owner text,
    p_stage text,
    p_error_code text,
    p_delivery_confirmed boolean
)
returns boolean
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    update public.webhook_idempotencia
    set status = 'terminal_failed',
        stage = left(coalesce(p_stage, 'telegram_delivery'), 80),
        error_code = left(coalesce(p_error_code, 'unknown'), 80),
        terminal_delivery_confirmed = p_delivery_confirmed,
        lease_owner = null,
        lease_expires_at = null,
        completed_at = timezone('utc', now()),
        updated_at = timezone('utc', now())
    where update_id = p_update_id
      and status = 'processing'
      and lease_owner = p_lease_owner
      and terminal_reason is not null;
    return found;
end;
$$;

revoke all on function public.claim_webhook_update_v2(bigint, text, integer) from public, anon, authenticated;
revoke all on function public.update_webhook_stage_v2(bigint, text, text, bigint) from public, anon, authenticated;
revoke all on function public.reserve_webhook_ocr_round_v2(bigint, text) from public, anon, authenticated;
revoke all on function public.reset_webhook_ocr_rounds_v2(bigint, text) from public, anon, authenticated;
revoke all on function public.prepare_webhook_terminal_failure_v2(bigint, text, text, text) from public, anon, authenticated;
revoke all on function public.complete_webhook_update_v2(bigint, text) from public, anon, authenticated;
revoke all on function public.fail_webhook_update_v2(bigint, text, text, text) from public, anon, authenticated;
revoke all on function public.terminal_fail_webhook_update_v2(bigint, text, text, text, boolean) from public, anon, authenticated;

grant execute on function public.claim_webhook_update_v2(bigint, text, integer) to service_role;
grant execute on function public.update_webhook_stage_v2(bigint, text, text, bigint) to service_role;
grant execute on function public.reserve_webhook_ocr_round_v2(bigint, text) to service_role;
grant execute on function public.reset_webhook_ocr_rounds_v2(bigint, text) to service_role;
grant execute on function public.prepare_webhook_terminal_failure_v2(bigint, text, text, text) to service_role;
grant execute on function public.complete_webhook_update_v2(bigint, text) to service_role;
grant execute on function public.fail_webhook_update_v2(bigint, text, text, text) to service_role;
grant execute on function public.terminal_fail_webhook_update_v2(bigint, text, text, text, boolean) to service_role;

comment on column public.webhook_idempotencia.ocr_round_count is
'Consecutive OCR rounds reserved before provider calls; reset only after a confirmed OCR response.';
comment on column public.webhook_idempotencia.terminal_reason is
'Sanitized terminal reason persisted before attempting the final Telegram notice.';
comment on column public.webhook_idempotencia.terminal_delivery_confirmed is
'Whether Telegram confirmed delivery of the terminal notice; null while delivery is pending.';

commit;
