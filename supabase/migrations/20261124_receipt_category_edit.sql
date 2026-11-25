-- Receipt category edit: revisioned pending receipts and an atomic approval claim.
-- Apply before deploying the Cloud Run services that read payload_revision and
-- approval_claimed_revision. Safe to re-apply: every statement is idempotent and no
-- existing row is changed (existing receipts read revision 0, approval not started).
--
-- p_now comes from the application on purpose: receipt deadlines are stored as
-- Brasilia wall-clock time without an offset (pre-existing quirk), so comparing them
-- with the same clock that wrote them keeps today's deadline semantics.

alter table public.cache_aprovacao
    add column if not exists payload_revision integer not null default 0;

alter table public.cache_aprovacao
    add column if not exists approval_claimed_revision integer;

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'cache_aprovacao_payload_revision_check'
          and conrelid = 'public.cache_aprovacao'::regclass
    ) then
        alter table public.cache_aprovacao
            add constraint cache_aprovacao_payload_revision_check
            check (payload_revision >= 0);
    end if;
    if not exists (
        select 1
        from pg_constraint
        where conname = 'cache_aprovacao_approval_claim_check'
          and conrelid = 'public.cache_aprovacao'::regclass
    ) then
        alter table public.cache_aprovacao
            add constraint cache_aprovacao_approval_claim_check
            check (approval_claimed_revision is null or approval_claimed_revision = payload_revision);
    end if;
end;
$$;

-- Replaces the encrypted payload and its preview of a bound, unexpired, unclaimed
-- receipt if it is still at p_expected_revision. Never touches expires_at.
-- Returns the new revision, or null when nothing was written.
create or replace function public.edit_receipt_pending(
    p_id text,
    p_chat_id text,
    p_user_id text,
    p_expected_revision integer,
    p_ciphertext text,
    p_preview jsonb,
    p_now timestamptz
)
returns integer
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    new_revision integer;
begin
    if p_id is null or p_expected_revision is null or p_now is null
       or coalesce(btrim(p_chat_id), '') = '' or coalesce(btrim(p_user_id), '') = ''
       or coalesce(p_ciphertext, '') = ''
       or p_preview is null or jsonb_typeof(p_preview) <> 'object' then
        return null;
    end if;

    update public.cache_aprovacao
    set payload_ciphertext = p_ciphertext,
        payload = '{}'::jsonb,
        preview_json = p_preview,
        payload_revision = payload_revision + 1
    where id = p_id
      and kind = 'receipt_batch'
      and origin_chat_id = p_chat_id
      and origin_user_id = p_user_id
      and payload_revision = p_expected_revision
      and approval_claimed_revision is null
      and expires_at > p_now
    returning payload_revision into new_revision;

    return new_revision;
end;
$$;

-- Locks the approval of a bound receipt at p_revision. Statuses:
-- claimed (this call locked it), already_claimed (an approval already started; returns
-- the locked revision, even after the deadline), expired, stale (returns the current
-- revision) and unavailable (missing, other kind or binding mismatch).
create or replace function public.claim_receipt_approval(
    p_id text,
    p_chat_id text,
    p_user_id text,
    p_revision integer,
    p_now timestamptz
)
returns table (claim_status text, claim_revision integer)
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    locked integer;
    current_row record;
begin
    if p_id is null or p_revision is null or p_now is null
       or coalesce(btrim(p_chat_id), '') = '' or coalesce(btrim(p_user_id), '') = '' then
        return query select 'unavailable'::text, null::integer;
        return;
    end if;

    update public.cache_aprovacao c
    set approval_claimed_revision = c.payload_revision
    where c.id = p_id
      and c.kind = 'receipt_batch'
      and c.origin_chat_id = p_chat_id
      and c.origin_user_id = p_user_id
      and c.approval_claimed_revision is null
      and c.payload_revision = p_revision
      and c.expires_at > p_now
    returning c.payload_revision into locked;

    if found then
        return query select 'claimed'::text, locked;
        return;
    end if;

    select c.payload_revision, c.approval_claimed_revision, c.expires_at
    into current_row
    from public.cache_aprovacao c
    where c.id = p_id
      and c.kind = 'receipt_batch'
      and c.origin_chat_id = p_chat_id
      and c.origin_user_id = p_user_id;

    if not found then
        return query select 'unavailable'::text, null::integer;
    elsif current_row.approval_claimed_revision is not null then
        return query select 'already_claimed'::text, current_row.approval_claimed_revision;
    elsif current_row.expires_at is null or current_row.expires_at <= p_now then
        return query select 'expired'::text, null::integer;
    else
        return query select 'stale'::text, current_row.payload_revision;
    end if;
end;
$$;

-- Admin panel variant: the BFF already authenticated the admin, so there is no chat
-- binding and it approves the current revision. Same statuses minus stale.
create or replace function public.claim_receipt_approval_admin(
    p_id text,
    p_now timestamptz
)
returns table (claim_status text, claim_revision integer)
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    locked integer;
    current_row record;
begin
    if p_id is null or p_now is null then
        return query select 'unavailable'::text, null::integer;
        return;
    end if;

    update public.cache_aprovacao c
    set approval_claimed_revision = c.payload_revision
    where c.id = p_id
      and c.kind = 'receipt_batch'
      and c.approval_claimed_revision is null
      and c.expires_at > p_now
    returning c.payload_revision into locked;

    if found then
        return query select 'claimed'::text, locked;
        return;
    end if;

    select c.approval_claimed_revision, c.expires_at
    into current_row
    from public.cache_aprovacao c
    where c.id = p_id
      and c.kind = 'receipt_batch';

    if not found then
        return query select 'unavailable'::text, null::integer;
    elsif current_row.approval_claimed_revision is not null then
        return query select 'already_claimed'::text, current_row.approval_claimed_revision;
    else
        return query select 'expired'::text, null::integer;
    end if;
end;
$$;

-- Deletes a bound receipt only while no approval has started.
-- Returns discarded, claimed or unavailable.
create or replace function public.discard_receipt_pending(
    p_id text,
    p_chat_id text,
    p_user_id text
)
returns text
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    if p_id is null or coalesce(btrim(p_chat_id), '') = '' or coalesce(btrim(p_user_id), '') = '' then
        return 'unavailable';
    end if;

    delete from public.cache_aprovacao
    where id = p_id
      and kind = 'receipt_batch'
      and origin_chat_id = p_chat_id
      and origin_user_id = p_user_id
      and approval_claimed_revision is null;

    if found then
        return 'discarded';
    end if;

    if exists (
        select 1
        from public.cache_aprovacao
        where id = p_id
          and kind = 'receipt_batch'
          and origin_chat_id = p_chat_id
          and origin_user_id = p_user_id
    ) then
        return 'claimed';
    end if;
    return 'unavailable';
end;
$$;

create or replace function public.discard_receipt_pending_admin(
    p_id text
)
returns text
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    if p_id is null then
        return 'unavailable';
    end if;

    delete from public.cache_aprovacao
    where id = p_id
      and kind = 'receipt_batch'
      and approval_claimed_revision is null;

    if found then
        return 'discarded';
    end if;

    if exists (select 1 from public.cache_aprovacao where id = p_id and kind = 'receipt_batch') then
        return 'claimed';
    end if;
    return 'unavailable';
end;
$$;

revoke all on function public.edit_receipt_pending(text, text, text, integer, text, jsonb, timestamptz) from public, anon, authenticated;
revoke all on function public.claim_receipt_approval(text, text, text, integer, timestamptz) from public, anon, authenticated;
revoke all on function public.claim_receipt_approval_admin(text, timestamptz) from public, anon, authenticated;
revoke all on function public.discard_receipt_pending(text, text, text) from public, anon, authenticated;
revoke all on function public.discard_receipt_pending_admin(text) from public, anon, authenticated;

grant execute on function public.edit_receipt_pending(text, text, text, integer, text, jsonb, timestamptz) to service_role;
grant execute on function public.claim_receipt_approval(text, text, text, integer, timestamptz) to service_role;
grant execute on function public.claim_receipt_approval_admin(text, timestamptz) to service_role;
grant execute on function public.discard_receipt_pending(text, text, text) to service_role;
grant execute on function public.discard_receipt_pending_admin(text) to service_role;

comment on function public.edit_receipt_pending(text, text, text, integer, text, jsonb, timestamptz) is
'Revision CAS edit of a bound receipt_batch pending item. Available only to the service_role runtime.';
comment on function public.claim_receipt_approval(text, text, text, integer, timestamptz) is
'Atomic approval claim of a bound receipt_batch revision. Available only to the service_role runtime.';
comment on function public.claim_receipt_approval_admin(text, timestamptz) is
'Atomic approval claim of the current receipt_batch revision for the admin BFF. Available only to the service_role runtime.';
comment on function public.discard_receipt_pending(text, text, text) is
'Deletes a bound receipt_batch pending item unless its approval started. Available only to the service_role runtime.';
comment on function public.discard_receipt_pending_admin(text) is
'Deletes a receipt_batch pending item for the admin BFF unless its approval started. Available only to the service_role runtime.';
