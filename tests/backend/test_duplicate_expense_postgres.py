"""Real-Postgres checks for the duplicate-expense migration and its decision RPC.

Opt-in: set DUPLICATE_PG_BIN to a PostgreSQL ``bin`` directory (initdb, pg_ctl, psql).
A throwaway cluster is created in a temp dir, listens only on a unix socket and is
removed afterwards. Only synthetic rows are used.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

PG_BIN = os.environ.get("DUPLICATE_PG_BIN")
MIGRATION = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "20261111_duplicate_expense_confirmation.sql"

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
    created_at timestamptz not null default timezone('utc', now()),
    kind text default 'receipt_batch',
    expires_at timestamptz default timezone('utc', now()) + interval '24 hours',
    origin_chat_id text,
    origin_user_id text,
    source_update_id bigint
);
create unique index cache_aprovacao_source_update_uidx on public.cache_aprovacao (source_update_id);
insert into public.cache_aprovacao (id, kind, origin_chat_id, origin_user_id, source_update_id) values
    ('legacy', 'receipt_batch', '1', '2', 10),
    ('open', 'duplicate_expense', '1', '2', 11),
    ('late', 'duplicate_expense', '1', '2', 12),
    ('nodeadline', 'duplicate_expense', '1', '2', 13),
    ('unbound', 'duplicate_expense', null, null, 14),
    ('race', 'duplicate_expense', '1', '2', 15);
update public.cache_aprovacao set expires_at = now() - interval '1 second' where id = 'late';
update public.cache_aprovacao set expires_at = null where id = 'nodeadline';
"""


class Cluster:
    def __init__(self, root: Path):
        self.root = root
        self.data = root / "data"
        self.sock = root / "sock"

    def psql_args(self, *extra):
        return [f"{PG_BIN}/psql", "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-h", str(self.sock), "-p", "54329",
                "-U", "postgres", "-d", "postgres", *extra]

    def run(self, sql: str = None, file: Path = None, check=True):
        args = self.psql_args("-c", sql) if sql is not None else self.psql_args("-f", str(file))
        result = subprocess.run(args, capture_output=True, text=True, timeout=60)
        if check and result.returncode != 0:
            raise AssertionError(result.stderr.strip())
        return result

    def scalar(self, sql: str):
        return self.run(sql).stdout.strip()

    def decide(self, cache_id, chat, user, decision):
        value = self.scalar(f"select public.decide_duplicate_expense('{cache_id}', '{chat}', '{user}', '{decision}')")
        return value or None


@pytest.fixture(scope="module")
def cluster():
    root = Path(tempfile.mkdtemp(prefix="dupexp-pg-"))
    cl = Cluster(root)
    cl.sock.mkdir()
    try:
        subprocess.run([f"{PG_BIN}/initdb", "-D", str(cl.data), "-U", "postgres", "--auth=trust", "-E", "UTF8"],
                       check=True, capture_output=True, timeout=120)
        subprocess.run([f"{PG_BIN}/pg_ctl", "-D", str(cl.data), "-w", "-l", str(root / "log"), "-o",
                        f"-c listen_addresses='' -c unix_socket_directories='{cl.sock}' -p 54329", "start"],
                       check=True, capture_output=True, timeout=120)
        cl.run(SCHEMA)
        yield cl
    finally:
        subprocess.run([f"{PG_BIN}/pg_ctl", "-D", str(cl.data), "-m", "immediate", "stop"], capture_output=True, timeout=60)
        shutil.rmtree(root, ignore_errors=True)


def test_migration_applies_and_reapplies_without_touching_rows(cluster):
    before = cluster.scalar("select jsonb_agg(to_jsonb(t) - 'duplicate_decision' order by id) from public.cache_aprovacao t")
    cluster.run(file=MIGRATION)
    cluster.run(file=MIGRATION)
    after = cluster.scalar("select jsonb_agg(to_jsonb(t) - 'duplicate_decision' order by id) from public.cache_aprovacao t")
    assert before == after
    assert cluster.scalar("select count(*) from public.cache_aprovacao where duplicate_decision is not null") == "0"


def test_privileges_are_service_role_only(cluster):
    signature = "public.decide_duplicate_expense(text,text,text,text)"
    assert cluster.scalar(f"select has_function_privilege('service_role', '{signature}', 'EXECUTE')") == "t"
    for role in ("anon", "authenticated", "public"):
        assert cluster.scalar(f"select has_function_privilege('{role}', '{signature}', 'EXECUTE')") == "f"
    config = cluster.scalar(f"select proconfig::text from pg_proc where oid = '{signature}'::regprocedure")
    assert "search_path" in config and "pg_temp" in config
    assert cluster.scalar(f"select prosecdef from pg_proc where oid = '{signature}'::regprocedure") == "t"


def test_check_constraint_rejects_unknown_decisions(cluster):
    result = cluster.run("update public.cache_aprovacao set duplicate_decision = 'maybe' where id = 'open'", check=False)
    assert result.returncode != 0


def test_wrong_binding_kind_or_decision_does_not_decide(cluster):
    assert cluster.decide("open", "9", "2", "save") is None
    assert cluster.decide("open", "1", "9", "save") is None
    assert cluster.decide("legacy", "1", "2", "save") is None
    assert cluster.decide("missing", "1", "2", "save") is None
    assert cluster.decide("unbound", "1", "2", "save") is None
    assert cluster.run("select public.decide_duplicate_expense('open', '1', '2', 'bogus')", check=False).returncode != 0
    assert cluster.scalar("select public.decide_duplicate_expense('open', null, '2', 'save')") == ""
    undecided = cluster.scalar("select count(*) from public.cache_aprovacao where duplicate_decision is not null")
    assert undecided == "0"


def test_first_decision_is_immutable(cluster):
    assert cluster.decide("open", "1", "2", "skip") == "skip"
    assert cluster.decide("open", "1", "2", "save") == "skip"
    assert cluster.decide("open", "1", "2", "skip") == "skip"
    assert cluster.scalar("select duplicate_decision from public.cache_aprovacao where id = 'open'") == "skip"


def test_decision_after_deadline_or_without_deadline_is_expired_and_never_save(cluster):
    assert cluster.decide("late", "1", "2", "save") == "expired"
    assert cluster.decide("late", "1", "2", "skip") == "expired"
    assert cluster.decide("nodeadline", "1", "2", "save") == "expired"


def test_save_accepted_in_time_survives_expiry(cluster):
    cluster.run(
        "insert into public.cache_aprovacao (id, kind, origin_chat_id, origin_user_id, source_update_id) "
        "values ('intime', 'duplicate_expense', '1', '2', 20)"
    )
    assert cluster.decide("intime", "1", "2", "save") == "save"
    cluster.run("update public.cache_aprovacao set expires_at = now() - interval '1 hour' where id = 'intime'")
    assert cluster.decide("intime", "1", "2", "skip") == "save"
    assert cluster.decide("intime", "1", "2", "save") == "save"


def test_concurrent_opposite_decisions_yield_one_canonical_value(cluster):
    """Many sessions queue on a held row lock, then race; all must report the same winner."""
    locker = subprocess.Popen(cluster.psql_args(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    locker.stdin.write("begin;\nselect id from public.cache_aprovacao where id = 'race' for update;\n")
    locker.stdin.flush()
    locker.stdout.readline()  # the locked id: lock is held once this line arrives

    workers = []
    for index in range(8):
        decision = "save" if index % 2 else "skip"
        workers.append(subprocess.Popen(
            cluster.psql_args("-c", f"select public.decide_duplicate_expense('race', '1', '2', '{decision}')"),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
    # Wait until every worker is blocked on the row lock before releasing it.
    for _ in range(100):
        waiting = cluster.scalar("select count(*) from pg_stat_activity where wait_event_type = 'Lock' and query like '%decide_duplicate_expense%'")
        if waiting == "8":
            break
        subprocess.run(["sleep", "0.1"])
    assert waiting == "8"
    locker.stdin.write("commit;\n")
    locker.stdin.close()
    locker.wait(timeout=30)

    results = []
    for worker in workers:
        out, err = worker.communicate(timeout=60)
        assert worker.returncode == 0, err
        results.append(out.strip())
    stored = cluster.scalar("select duplicate_decision from public.cache_aprovacao where id = 'race'")
    assert stored in ("save", "skip")
    assert set(results) == {stored}
