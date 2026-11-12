-- Repeated-expense warning: durable, immutable decision on a pending confirmation.
-- Apply before deploying the Cloud Run services that send duplicate_expense items.
-- Safe to re-apply: every statement is idempotent and no existing row is changed.

alter table public.cache_aprovacao
    add column if not exists duplicate_decision text;

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'cache_aprovacao_duplicate_decision_check'
          and conrelid = 'public.cache_aprovacao'::regclass
    ) then
        alter table public.cache_aprovacao
            add constraint cache_aprovacao_duplicate_decision_check
            check (duplicate_decision is null or duplicate_decision in ('save', 'skip', 'expired'));
    end if;
end;
$$;

-- Records the first valid decision and returns the canonical one. The decision is
-- immutable: later calls (opposite, repeated or concurrent) return the stored value.
-- Binding (kind, chat and user, all non-null and equal) is re-checked here, and a
-- decision requested after expires_at (or without a deadline) is stored as 'expired'.
-- Returns null when the item does not exist or does not match the binding.
create or replace function public.decide_duplicate_expense(
    p_id text,
    p_chat_id text,
    p_user_id text,
    p_decision text
)
returns text
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    canonical text;
begin
    if p_decision is null or p_decision not in ('save', 'skip') then
        raise exception 'invalid duplicate decision';
    end if;
    if p_id is null or p_chat_id is null or p_user_id is null then
        return null;
    end if;

    update public.cache_aprovacao
    set duplicate_decision = case
            when expires_at is null or expires_at <= now() then 'expired'
            else p_decision
        end
    where id = p_id
      and kind = 'duplicate_expense'
      and origin_chat_id = p_chat_id
      and origin_user_id = p_user_id
      and duplicate_decision is null
    returning duplicate_decision into canonical;

    if found then
        return canonical;
    end if;

    select duplicate_decision
    into canonical
    from public.cache_aprovacao
    where id = p_id
      and kind = 'duplicate_expense'
      and origin_chat_id = p_chat_id
      and origin_user_id = p_user_id;

    return canonical;
end;
$$;

revoke all on function public.decide_duplicate_expense(text, text, text, text) from public, anon, authenticated;
grant execute on function public.decide_duplicate_expense(text, text, text, text) to service_role;

comment on function public.decide_duplicate_expense(text, text, text, text) is
'Atomic, immutable decision for duplicate_expense confirmations. Available only to the service_role runtime.';
