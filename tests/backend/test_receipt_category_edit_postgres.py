"""Real-Postgres checks for the receipt category edit migration and its RPCs.

Opt-in: set DUPLICATE_PG_BIN to a PostgreSQL ``bin`` directory (initdb, pg_ctl, psql).
A throwaway cluster is created in a temp dir, listens only on a unix socket and is
removed afterwards. Only synthetic rows are used.
"""

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

PG_BIN = os.environ.get("DUPLICATE_PG_BIN")
MIGRATION = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "20261124_receipt_category_edit.sql"
PORT = "54331"
NOW = "2026-11-23 10:00:00"

pytestmark = pytest.mark.skipif(not PG_BIN, reason="DUPLICATE_PG_BIN not set; real Postgres checks are opt-in")

SCHEMA = """
do $$ begin
    if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
    if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
    if not exists (select 1 from pg_roles where rolname = 'service_role') then create role service_role nologin; end if;
end $$;
create table public.cache_aprovacao (
    id text primary key,
    payload jsonb not null default '{}'::jsonb,
    payload_ciphertext text,
    payload_key_version text,
    preview_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now()),
    kind text default 'receipt_batch',
    expires_at timestamptz default timezone('utc', now()) + interval '24 hours',
    origin_chat_id text,
    origin_user_id text,
    source_update_id bigint
);
create unique index cache_aprovacao_source_update_uidx on public.cache_aprovacao (source_update_id);
insert into public.cache_aprovacao (id, kind, payload, payload_ciphertext, origin_chat_id, origin_user_id, source_update_id, expires_at) values
    ('r', 'receipt_batch', '{}', 'c0', '1', '2', 10, '2026-11-24 10:00:00'),
    ('plain', 'receipt_batch', '{"itens": []}', null, '1', '2', 11, '2026-11-24 10:00:00'),
    ('late', 'receipt_batch', '{}', 'c0', '1', '2', 12, '2026-11-23 09:59:59'),
    ('nodeadline', 'receipt_batch', '{}', 'c0', '1', '2', 13, null),
    ('unbound', 'receipt_batch', '{}', 'c0', null, null, 14, '2026-11-24 10:00:00'),
    ('del', 'delete_confirmation', '{}', 'c0', '1', '2', 15, '2026-11-24 10:00:00'),
    ('dup', 'duplicate_expense', '{}', 'c0', '1', '2', 16, '2026-11-24 10:00:00'),
    ('raceA', 'receipt_batch', '{}', 'c0', '1', '2', 17, '2026-11-24 10:00:00'),
    ('raceB', 'receipt_batch', '{}', 'c0', '1', '2', 18, '2026-11-24 10:00:00'),
    ('raceC', 'receipt_batch', '{}', 'c0', '1', '2', 19, '2026-11-24 10:00:00'),
    ('adm', 'receipt_batch', '{}', 'c0', '1', '2', 20, '2026-11-24 10:00:00'),
    ('disc', 'receipt_batch', '{}', 'c0', '1', '2', 21, '2026-11-24 10:00:00'),
    ('admdisc', 'receipt_batch', '{}', 'c0', null, null, 22, '2026-11-24 10:00:00');
"""

SIGNATURES = (
    "public.edit_receipt_pending(text,text,text,integer,text,jsonb,timestamptz)",
    "public.claim_receipt_approval(text,text,text,integer,timestamptz)",
    "public.claim_receipt_approval_admin(text,timestamptz)",
    "public.discard_receipt_pending(text,text,text)",
    "public.discard_receipt_pending_admin(text)",
)


class Cluster:
    def __init__(self, root: Path):
        self.root = root
        self.data = root / "data"
        self.sock = root / "sock"

    def psql_args(self, *extra):
        return [f"{PG_BIN}/psql", "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-h", str(self.sock), "-p", PORT,
                "-U", "postgres", "-d", "postgres", *extra]

    def run(self, sql: str = None, file: Path = None, check=True):
        args = self.psql_args("-c", sql) if sql is not None else self.psql_args("-f", str(file))
        result = subprocess.run(args, capture_output=True, text=True, timeout=60)
        if check and result.returncode != 0:
            raise AssertionError(result.stderr.strip())
        return result

    def scalar(self, sql: str):
        return self.run(sql).stdout.strip()

    def edit(self, cache_id, chat="1", user="2", rev=0, cipher="c1", now=NOW, preview="{\"summary\": \"Cupom pendente\"}"):
        return self.scalar(
            f"select public.edit_receipt_pending('{cache_id}', {_lit(chat)}, {_lit(user)}, {rev}, {_lit(cipher)}, "
            f"{_lit(preview)}::jsonb, '{now}')"
        ) or None

    def claim(self, cache_id, chat="1", user="2", rev=0, now=NOW):
        return self.scalar(
            f"select claim_status || ':' || coalesce(claim_revision::text, '') "
            f"from public.claim_receipt_approval('{cache_id}', {_lit(chat)}, {_lit(user)}, {rev}, '{now}')"
        )

    def claim_admin(self, cache_id, now=NOW):
        return self.scalar(
            f"select claim_status || ':' || coalesce(claim_revision::text, '') "
            f"from public.claim_receipt_approval_admin('{cache_id}', '{now}')"
        )

    def row(self, cache_id):
        return self.scalar(
            "select concat_ws('|', payload_revision, coalesce(approval_claimed_revision::text, 'null'), payload_ciphertext, "
            f"payload::text, preview_json::text) from public.cache_aprovacao where id = '{cache_id}'"
        )


def _lit(value):
    return "null" if value is None else "'" + value.replace("'", "''") + "'"


@pytest.fixture(scope="module")
def cluster():
    root = Path(tempfile.mkdtemp(prefix="receipt-edit-pg-"))
    cl = Cluster(root)
    cl.sock.mkdir()
    try:
        subprocess.run([f"{PG_BIN}/initdb", "-D", str(cl.data), "-U", "postgres", "--auth=trust", "-E", "UTF8"],
                       check=True, capture_output=True, timeout=120)
        subprocess.run([f"{PG_BIN}/pg_ctl", "-D", str(cl.data), "-w", "-l", str(root / "log"), "-o",
                        f"-c listen_addresses='' -c unix_socket_directories='{cl.sock}' -p {PORT} -c TimeZone=UTC", "start"],
                       check=True, capture_output=True, timeout=120)
        cl.run(SCHEMA)
        yield cl
    finally:
        subprocess.run([f"{PG_BIN}/pg_ctl", "-D", str(cl.data), "-m", "immediate", "stop"], capture_output=True, timeout=60)
        shutil.rmtree(root, ignore_errors=True)


def test_migration_applies_and_reapplies_without_touching_rows(cluster):
    query = (
        "select jsonb_agg(to_jsonb(t) - 'payload_revision' - 'approval_claimed_revision' order by id) "
        "from public.cache_aprovacao t"
    )
    before = cluster.scalar(query)
    cluster.run(file=MIGRATION)
    cluster.run(file=MIGRATION)
    assert cluster.scalar(query) == before
    assert cluster.scalar(
        "select count(*) from public.cache_aprovacao where payload_revision <> 0 or approval_claimed_revision is not null"
    ) == "0"


def test_privileges_are_service_role_only(cluster):
    for signature in SIGNATURES:
        assert cluster.scalar(f"select has_function_privilege('service_role', '{signature}', 'EXECUTE')") == "t"
        for role in ("anon", "authenticated", "public"):
            assert cluster.scalar(f"select has_function_privilege('{role}', '{signature}', 'EXECUTE')") == "f"
        config = cluster.scalar(f"select proconfig::text from pg_proc where oid = '{signature}'::regprocedure")
        assert "search_path" in config and "pg_temp" in config
        assert cluster.scalar(f"select prosecdef from pg_proc where oid = '{signature}'::regprocedure") == "t"


def test_constraints_reject_inconsistent_claims(cluster):
    assert cluster.run("update public.cache_aprovacao set approval_claimed_revision = 5 where id = 'r'", check=False).returncode != 0
    assert cluster.run("update public.cache_aprovacao set payload_revision = -1 where id = 'r'", check=False).returncode != 0


def test_edit_rechecks_binding_kind_deadline_and_input(cluster):
    assert cluster.edit("r", chat="9") is None
    assert cluster.edit("r", user="9") is None
    assert cluster.edit("r", chat=None) is None
    assert cluster.edit("r", chat="") is None
    assert cluster.edit("unbound") is None
    assert cluster.edit("del") is None
    assert cluster.edit("dup") is None
    assert cluster.edit("missing") is None
    assert cluster.edit("late") is None
    assert cluster.edit("nodeadline") is None
    assert cluster.edit("r", cipher="") is None
    assert cluster.edit("r", cipher=None) is None
    assert cluster.edit("r", preview="[]") is None
    assert cluster.scalar("select count(*) from public.cache_aprovacao where payload_revision <> 0") == "0"


def test_edit_is_a_revision_cas_that_never_renews_the_deadline(cluster):
    deadline = cluster.scalar("select expires_at from public.cache_aprovacao where id = 'r'")
    assert cluster.edit("r", rev=0, cipher="c1") == "1"
    assert cluster.edit("r", rev=0, cipher="stale") is None
    assert cluster.edit("r", rev=1, cipher="c2", preview='{"summary": "v2"}') == "2"
    assert cluster.row("r") == '2|null|c2|{}|{"summary": "v2"}'
    assert cluster.scalar("select expires_at from public.cache_aprovacao where id = 'r'") == deadline


def test_edit_clears_legacy_plaintext_payload(cluster):
    assert cluster.edit("plain", cipher="enc") == "1"
    assert cluster.row("plain").startswith("1|null|enc|{}|")


def test_claim_statuses(cluster):
    assert cluster.claim("r", rev=1) == "stale:2"
    assert cluster.claim("r", chat="9", rev=2) == "unavailable:"
    assert cluster.claim("unbound", rev=0) == "unavailable:"
    assert cluster.claim("del", rev=0) == "unavailable:"
    assert cluster.claim("late", rev=0) == "expired:"
    assert cluster.claim("nodeadline", rev=0) == "expired:"
    assert cluster.claim("r", rev=2) == "claimed:2"
    assert cluster.claim("r", rev=2) == "already_claimed:2"
    assert cluster.claim("r", rev=0) == "already_claimed:2"
    # An approval started in time can still be completed after the deadline.
    assert cluster.claim("r", rev=2, now="2026-11-30 00:00:00") == "already_claimed:2"


def test_claimed_rows_cannot_be_edited_or_discarded(cluster):
    assert cluster.edit("r", rev=2) is None
    assert cluster.scalar("select public.discard_receipt_pending('r', '1', '2')") == "claimed"
    assert cluster.scalar("select public.discard_receipt_pending_admin('r')") == "claimed"
    assert cluster.row("r").startswith("2|2|")


def test_admin_claim_takes_the_current_revision(cluster):
    assert cluster.edit("adm", rev=0) == "1"
    assert cluster.claim_admin("adm") == "claimed:1"
    assert cluster.claim_admin("adm") == "already_claimed:1"
    assert cluster.claim("adm", rev=1) == "already_claimed:1"
    assert cluster.claim_admin("late") == "expired:"
    assert cluster.claim_admin("del") == "unavailable:"
    assert cluster.claim_admin("missing") == "unavailable:"


def test_discard(cluster):
    assert cluster.scalar("select public.discard_receipt_pending('disc', '9', '2')") == "unavailable"
    assert cluster.scalar("select public.discard_receipt_pending('del', '1', '2')") == "unavailable"
    assert cluster.scalar("select public.discard_receipt_pending('disc', '1', '2')") == "discarded"
    assert cluster.scalar("select count(*) from public.cache_aprovacao where id = 'disc'") == "0"
    assert cluster.scalar("select public.discard_receipt_pending_admin('admdisc')") == "discarded"
    assert cluster.scalar("select public.discard_receipt_pending_admin('admdisc')") == "unavailable"
    assert cluster.scalar("select public.discard_receipt_pending_admin('del')") == "unavailable"


def _race(cluster, cache_id, statements):
    """Hold the row lock, queue every statement behind it, then release and collect results."""
    locker = subprocess.Popen(cluster.psql_args(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    locker.stdin.write(f"begin;\nselect id from public.cache_aprovacao where id = '{cache_id}' for update;\n")
    locker.stdin.flush()
    locker.stdout.readline()
    workers = [
        subprocess.Popen(cluster.psql_args("-c", sql), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for sql in statements
    ]
    waiting = "0"
    for _ in range(100):
        waiting = cluster.scalar(
            "select count(*) from pg_stat_activity where wait_event_type = 'Lock' and query like '%receipt_%' "
            "and query not like '%pg_stat_activity%'"
        )
        if waiting == str(len(statements)):
            break
        time.sleep(0.1)
    assert waiting == str(len(statements))
    locker.stdin.write("commit;\n")
    locker.stdin.close()
    locker.wait(timeout=30)
    results = []
    for worker in workers:
        out, err = worker.communicate(timeout=60)
        assert worker.returncode == 0, err
        results.append(out.strip())
    return results


def test_concurrent_edit_and_claim_exactly_one_wins(cluster):
    edit_sql = f"select public.edit_receipt_pending('raceA', '1', '2', 0, 'cX', '{{}}'::jsonb, '{NOW}')"
    claim_sql = f"select claim_status from public.claim_receipt_approval('raceA', '1', '2', 0, '{NOW}')"
    edited, claimed = _race(cluster, "raceA", [edit_sql, claim_sql])
    row = cluster.row("raceA")
    if edited == "1":
        assert claimed == "stale" and row.startswith("1|null|cX|")
    else:
        assert edited == "" and claimed == "claimed" and row.startswith("0|0|c0|")


def test_concurrent_claims_exactly_one_wins(cluster):
    sql = f"select claim_status from public.claim_receipt_approval('raceB', '1', '2', 0, '{NOW}')"
    admin_sql = f"select claim_status from public.claim_receipt_approval_admin('raceB', '{NOW}')"
    results = _race(cluster, "raceB", [sql, sql, admin_sql, sql])
    assert sorted(results) == ["already_claimed", "already_claimed", "already_claimed", "claimed"]


def test_concurrent_discard_and_claim_exactly_one_wins(cluster):
    discard_sql = "select public.discard_receipt_pending('raceC', '1', '2')"
    claim_sql = f"select claim_status from public.claim_receipt_approval('raceC', '1', '2', 0, '{NOW}')"
    discarded, claimed = _race(cluster, "raceC", [discard_sql, claim_sql])
    remaining = cluster.scalar("select count(*) from public.cache_aprovacao where id = 'raceC'")
    assert (discarded, claimed, remaining) in {("discarded", "unavailable", "0"), ("claimed", "claimed", "1")}
