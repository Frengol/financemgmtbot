"""Exclusão pelo Telegram: normalização, busca completa, prévia fiel e proteções do fluxo.

Tudo sintético e offline: um banco em memória substitui o Supabase e a IA nunca é chamada.
"""
import json
import os
import re
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

TEST_ENV = {
    "TELEGRAM_BOT_TOKEN": "FAKE_TELEGRAM_TOKEN",
    "TELEGRAM_SECRET_TOKEN": "FAKE_SECRET",
    "SUPABASE_URL": "https://fake.supabase.co",
    "SUPABASE_KEY": "FAKE_SUPABASE_KEY_1234567890",
    "DEEPSEEK_API_KEY": "FAKE_DEEPSEEK_KEY_1234567890",
    "GROQ_API_KEY": "FAKE_GROQ_KEY_1234567890",
    "GEMINI_API_KEY": "FAKE_GEMINI_KEY_1234567890",
    "TELEGRAM_TASKS_PROJECT": "financemgmtbot",
    "TELEGRAM_TASKS_LOCATION": "southamerica-east1",
    "TELEGRAM_TASKS_QUEUE": "telegram-updates",
    "TELEGRAM_WORKER_URL": "https://worker.example.run.app",
    "TELEGRAM_TASK_INVOKER_SERVICE_ACCOUNT": "telegram-task-invoker@financemgmtbot.iam.gserviceaccount.com",
}
for key, value in TEST_ENV.items():
    os.environ.setdefault(key, value)

for dependency_patch in [
    patch("supabase.create_client", return_value=MagicMock()),
    patch("groq.AsyncGroq", return_value=MagicMock()),
    patch("openai.AsyncOpenAI", return_value=MagicMock()),
    patch("google.genai.Client", return_value=MagicMock()),
]:
    dependency_patch.start()

import ai_service
import config
import core_logic
import db_repository
import handlers
import security
from domain import finance

CHAT = 10
USER = 20
TODAY = datetime(2026, 11, 11, 10, 0, 0)
TODAY_ISO = "2026-11-11"
YESTERDAY_ISO = "2026-11-10"
PREVIEW_LIMIT = 4096


# --------------------------------------------------------------------------
# Banco em memória (transações e cache_aprovacao) com a cadeia PostgREST usada
# --------------------------------------------------------------------------
class FakeTable:
    def __init__(self, db, name):
        self.db = db
        self.name = name
        self.rows = db.tables.setdefault(name, [])
        self.calls = []
        self._filters = []
        self._order = None
        self._range = None
        self._action = "select"
        self._payload = None

    def __getattr__(self, name):
        raise AttributeError(name)

    def _rec(self, name, *args):
        self.calls.append((name, args))
        self.db.log.append((self.name, name, args))
        return self

    def select(self, *args):
        self._action = "select"
        return self._rec("select", *args)

    def insert(self, payload):
        self._action = "insert"
        self._payload = payload
        return self._rec("insert", payload)

    def delete(self):
        self._action = "delete"
        return self._rec("delete")

    def eq(self, column, value):
        self._filters.append(("eq", column, value))
        return self._rec("eq", column, value)

    def neq(self, column, value):
        self._filters.append(("neq", column, value))
        return self._rec("neq", column, value)

    def gte(self, column, value):
        self._filters.append(("gte", column, value))
        return self._rec("gte", column, value)

    def lte(self, column, value):
        self._filters.append(("lte", column, value))
        return self._rec("lte", column, value)

    def ilike(self, column, pattern):
        self._filters.append(("ilike", column, pattern))
        return self._rec("ilike", column, pattern)

    def in_(self, column, values):
        self._filters.append(("in", column, list(values)))
        return self._rec("in_", column, list(values))

    def order(self, column, desc=False):
        self._order = (column, desc)
        return self._rec("order", column, desc)

    def range(self, start, end):
        self._range = (start, end)
        return self._rec("range", start, end)

    def limit(self, size):
        self._range = (0, size - 1)
        return self._rec("limit", size)

    @staticmethod
    def _ilike_regex(pattern):
        # PostgREST documents `*` as an alias of `%` in like/ilike; the server may convert it
        # even after a backslash, so the fake treats it as a wildcard in both positions.
        out, i = "", 0
        while i < len(pattern):
            ch = pattern[i]
            if ch == "\\" and i + 1 < len(pattern) and pattern[i + 1] != "*":
                out += re.escape(pattern[i + 1])
                i += 2
                continue
            out += ".*" if ch in "%*" else "." if ch == "_" else re.escape(ch)
            i += 1
        return re.compile(f"^{out}$", re.IGNORECASE | re.DOTALL)

    def _matches(self, row):
        for op, column, value in self._filters:
            cell = row.get(column)
            if op == "eq" and not cell == value:
                return False
            if op == "neq" and cell == value:
                return False
            if op == "gte" and not (cell is not None and cell >= value):
                return False
            if op == "lte" and not (cell is not None and cell <= value):
                return False
            if op == "ilike" and not (isinstance(cell, str) and self._ilike_regex(value).match(cell)):
                return False
            if op == "in" and cell not in value:
                return False
        return True

    def execute(self):
        if self._action == "insert":
            payloads = self._payload if isinstance(self._payload, list) else [self._payload]
            for payload in payloads:
                row = dict(payload)
                if self.name == self.db.transactions_name and "id" not in row:
                    row["id"] = self.db.next_id()
                self.rows.append(row)
            return MagicMock(data=[dict(r) for r in payloads])
        matched = [r for r in self.rows if self._matches(r)]
        if self._action == "delete":
            for row in matched:
                self.rows.remove(row)
            return MagicMock(data=[dict(r) for r in matched])
        if self._order:
            matched.sort(key=lambda r: r[self._order[0]], reverse=self._order[1])
        if self._range:
            matched = matched[self._range[0]:self._range[1] + 1]
        return MagicMock(data=[dict(r) for r in matched])


class FakeDB:
    def __init__(self):
        self.tables = {}
        self.log = []
        self._id = 0
        self.transactions_name = config.TRANSACTIONS_TABLE

    def next_id(self):
        self._id += 1
        return self._id

    def table(self, name):
        return FakeTable(self, name)

    def add(self, **overrides):
        row = {
            "id": self.next_id(),
            "data": TODAY_ISO,
            "valor": 10.0,
            "natureza": "Essencial",
            "categoria": "Mercado",
            "descricao": "Compra sintética",
            "metodo_pagamento": "Pix",
            "conta": "Nubank",
        }
        row.update(overrides)
        self.tables.setdefault(self.transactions_name, []).append(row)
        return row

    @property
    def transactions(self):
        return self.tables.setdefault(self.transactions_name, [])

    @property
    def pending(self):
        return self.tables.setdefault("cache_aprovacao", [])

    def transaction_deletes(self):
        return [entry for entry in self.log if entry[0] == self.transactions_name and entry[1] == "delete"]

    def transaction_selects(self):
        return [entry for entry in self.log if entry[0] == self.transactions_name and entry[1] == "select"]


class Env:
    def __init__(self, db):
        self.db = db
        self.send = AsyncMock(return_value={"message_id": 11})
        self.edit = AsyncMock(return_value={})

    def sent_texts(self):
        return [call.args[1] for call in self.send.await_args_list]

    def edited_texts(self):
        return [call.args[2] for call in self.edit.await_args_list]

    def last_markup(self):
        for arg in self.send.await_args.args:
            if isinstance(arg, dict) and "inline_keyboard" in arg:
                return arg
        return None

    def button_ids(self):
        markup = self.last_markup()
        return [b["callback_data"] for row in markup["inline_keyboard"] for b in row] if markup else []

    def pending_rows(self):
        return list(self.db.pending)

    def stored_ids(self):
        row = self.db.pending[-1]
        return security.decrypt_pending_payload(row["payload_ciphertext"])["ids"]

    async def start(self, filters, user=USER):
        await handlers.iniciar_fluxo_exclusao(CHAT, filters, origin_user_id=user)

    async def callback(self, data, chat=CHAT, user=USER, update_id=900):
        update = {
            "update_id": update_id,
            "callback_query": {"id": "cb", "data": data, "from": {"id": user}, "message": {"chat": {"id": chat}, "message_id": 50}},
        }
        await handlers.processar_update_assincrono(update, source_update_id=update_id)


@pytest.fixture
def env():
    db = FakeDB()
    environment = Env(db)
    patches = [
        patch.object(handlers, "supabase", db),
        patch.object(db_repository, "supabase", db),
        patch.object(security, "supabase", db),
        patch.object(handlers, "enviar_mensagem_telegram", environment.send),
        patch.object(handlers, "editar_mensagem_telegram", environment.edit),
        patch.object(handlers, "responder_callback_telegram", AsyncMock()),
    ]
    for p in patches:
        p.start()
    yield environment
    for p in reversed(patches):
        p.stop()


def _normalized(raw):
    result = finance.normalize_delete_request(raw)
    assert isinstance(result, finance.DeleteFilters), result
    return result


def _refused(raw):
    result = finance.normalize_delete_request(raw)
    assert isinstance(result, finance.DeleteRefusal), result
    return result.reason


# --------------------------------------------------------------------------
# CA1 / CA2: normalização estrita e exclusiva da exclusão
# --------------------------------------------------------------------------
class TestNormalizeDeleteRequest:
    def test_zero_is_a_real_amount_filter(self):
        filters = _normalized({"valor_exato": 0, "data": TODAY_ISO, "tipo_transacao": "saida"})
        assert filters.valor_exato == 0.0 and filters.valor_exato is not None
        assert filters.data == TODAY_ISO
        assert filters.tipo_transacao == "saida"
        assert filters.escopo == "um"

    @pytest.mark.parametrize("zero", [0, 0.0, "0", "0.00"])
    def test_zero_forms_are_kept(self, zero):
        assert _normalized({"valor_exato": zero}).valor_exato == 0.0

    def test_result_is_frozen(self):
        filters = _normalized({"valor_exato": 5})
        with pytest.raises(Exception):
            filters.valor_exato = 6

    def test_no_data_is_assumed_when_absent(self):
        filters = _normalized({"valor_exato": 0})
        assert filters.data is None and filters.date_from is None and filters.date_to is None

    def test_day_month_and_year_periods_are_faithful(self):
        day = _normalized({"data": "2026-02-28"})
        assert (day.data, day.date_from, day.date_to) == ("2026-02-28", None, None)
        month = _normalized({"mes": "02", "ano": "2028"})
        assert (month.data, month.date_from, month.date_to) == (None, "2028-02-01", "2028-02-29")
        year = _normalized({"ano": 2026})
        assert (year.date_from, year.date_to) == ("2026-01-01", "2026-12-31")

    def test_day_consistent_with_month_and_year_is_accepted(self):
        filters = _normalized({"data": "2026-11-11", "mes": "11", "ano": "2026"})
        assert filters.data == "2026-11-11" and filters.date_from is None

    @pytest.mark.parametrize(
        "raw,reason",
        [
            ({"data": "2026-13-01"}, "data_invalida"),
            ({"data": "2026-02-30"}, "data_invalida"),
            ({"data": "2026-1-5"}, "data_invalida"),
            ({"data": "11/11/2026"}, "data_invalida"),
            ({"data": 20261111}, "data_invalida"),
            ({"valor_exato": 5, "mes": "03"}, "mes_sem_ano"),
            ({"valor_exato": 5, "mes": "13", "ano": "2026"}, "periodo_invalido"),
            ({"valor_exato": 5, "mes": "00", "ano": "2026"}, "periodo_invalido"),
            ({"valor_exato": 5, "ano": "26"}, "periodo_invalido"),
            ({"valor_exato": 5, "ano": "abcd"}, "periodo_invalido"),
            ({"data": "2026-11-11", "mes": "10", "ano": "2026"}, "periodo_conflitante"),
            ({"data": "2026-11-11", "ano": "2025"}, "periodo_conflitante"),
            ({"data": "2026-11-11", "mes": "11"}, "mes_sem_ano"),
        ],
    )
    def test_invalid_or_conflicting_period_asks_for_clarification(self, raw, reason):
        assert _refused(raw) == reason

    @pytest.mark.parametrize(
        "raw,reason",
        [
            ({"valor_exato": "abc"}, "valor_invalido"),
            ({"valor_exato": -1}, "valor_invalido"),
            ({"valor_exato": True}, "valor_invalido"),
            ({"valor_exato": float("nan")}, "valor_invalido"),
            ({"valor_exato": float("inf")}, "valor_invalido"),
            ({"valor_exato": "1,5"}, "valor_invalido"),
            ({"categoria": "Inventada"}, "categoria_invalida"),
            ({"categoria": "Mercado,Lazer"}, "categoria_invalida"),
            ({"categoria": "despesa"}, "categoria_invalida"),
            ({"natureza": "Banana"}, "natureza_invalida"),
            ({"valor_exato": 1, "tipo_transacao": "tudo"}, "tipo_invalido"),
            ({"conta": ["Nubank"]}, "campo_invalido"),
            ({"metodo_pagamento": 5}, "campo_invalido"),
        ],
    )
    def test_informed_field_that_does_not_normalize_is_refused_not_dropped(self, raw, reason):
        assert _refused(raw) == reason

    def test_every_informed_field_must_normalize_even_with_other_valid_criteria(self):
        assert _refused({"valor_exato": 0, "categoria": "Inventada"}) == "categoria_invalida"

    @pytest.mark.parametrize("payment", ["*", "Cartão *1234", "*1234", "Pix*", "Car*tão", "\\*", "Cartão \\*1234", "100\\%*", "**"])
    def test_payment_method_with_asterisk_is_refused_anywhere(self, payment):
        assert _refused({"metodo_pagamento": payment}) == "campo_invalido"

    @pytest.mark.parametrize(
        "extra",
        [{"valor_exato": 0}, {"data": TODAY_ISO}, {"categoria": "Mercado"}, {"conta": "Nubank"}, {"tipo_transacao": "saida"}, {"escopo": "varios"}],
    )
    def test_payment_method_with_asterisk_refuses_the_whole_request_with_other_filters(self, extra):
        assert _refused({**extra, "metodo_pagamento": "Cartão *1234"}) == "campo_invalido"

    def test_account_with_asterisk_is_plain_equality_and_stays_valid(self):
        assert _normalized({"conta": "Conta *1234"}).conta == "Conta *1234"

    @pytest.mark.parametrize("payment", ["Pix", "Cartão 1234", "100%", "100%_", "a_b", "100\\%\\_"])
    def test_payment_method_without_asterisk_stays_valid(self, payment):
        assert _normalized({"metodo_pagamento": payment}).metodo_pagamento == payment

    def test_categories_and_natures_are_canonical(self):
        filters = _normalized({"categoria": "mercado", "natureza": "essencial"})
        assert (filters.categoria, filters.natureza) == ("Mercado", "Essencial")
        assert _normalized({"categoria": "Saude"}).categoria == "Saúde"
        assert _normalized({"natureza": "Outros"}).natureza == "Outros"

    def test_empty_values_count_as_not_informed(self):
        filters = _normalized({"valor_exato": None, "data": "", "conta": "  ", "categoria": None, "mes": "", "ano": "", "natureza": "Lazer"})
        assert filters.valor_exato is None and filters.data is None and filters.conta is None
        assert filters.natureza == "Lazer"

    @pytest.mark.parametrize("raw", [{}, {"tipo_transacao": "saida"}, {"tipo_transacao": "entrada"}, {"escopo": "varios"}, {"conta": ""}])
    def test_no_identifying_criterion_is_refused(self, raw):
        assert _refused(raw) == "sem_criterio"

    @pytest.mark.parametrize("raw", [None, [], "tudo", 5])
    def test_non_dict_is_refused(self, raw):
        assert _refused(raw) == "sem_criterio"

    @pytest.mark.parametrize(
        "raw",
        [{"valor_exato": 5}, {"data": TODAY_ISO}, {"mes": "03", "ano": "2026"}, {"ano": "2026"}, {"categoria": "Mercado"},
         {"natureza": "Lazer"}, {"conta": "Nubank"}, {"metodo_pagamento": "Pix"}],
    )
    def test_each_identifying_criterion_is_enough(self, raw):
        assert isinstance(finance.normalize_delete_request(raw), finance.DeleteFilters)

    def test_incomplete_flag_true_refuses_even_with_filters(self):
        assert _refused({"pedido_incompleto": True, "data": TODAY_ISO, "valor_exato": 0}) == "pedido_incompleto"

    @pytest.mark.parametrize("flag", ["true", 1, "sim", None, False, 0])
    def test_only_boolean_true_marks_incomplete(self, flag):
        assert isinstance(finance.normalize_delete_request({"pedido_incompleto": flag, "valor_exato": 5}), finance.DeleteFilters)

    @pytest.mark.parametrize("scope,expected", [("um", "um"), ("varios", "varios"), (" VARIOS ", "varios"), (None, "um"), ("todos", "um"), (3, "um"), ("", "um")])
    def test_scope_defaults_to_single(self, scope, expected):
        assert _normalized({"valor_exato": 5, "escopo": scope}).escopo == expected

    def test_type_only_restricts(self):
        assert _normalized({"valor_exato": 5, "tipo_transacao": "saida"}).tipo_transacao == "saida"
        assert _normalized({"valor_exato": 5}).tipo_transacao is None


# --------------------------------------------------------------------------
# CA1 / CA2: busca completa no repositório
# --------------------------------------------------------------------------
def _calls(table, name):
    return [args for call, args in table.calls if call == name]


class TestBuscarCandidatosExclusao:
    def test_zero_day_and_expense_type_are_combined_with_and(self, env):
        db = env.db
        zero_today = db.add(valor=0.0)
        db.add(valor=0.0, data=YESTERDAY_ISO)
        db.add(valor=15.0)
        db.add(valor=0.0, natureza="Receita", categoria="Salário")
        filters = _normalized({"valor_exato": 0, "data": TODAY_ISO, "tipo_transacao": "saida"})

        rows = db_repository.buscar_candidatos_exclusao(filters)

        assert [r["id"] for r in rows] == [zero_today["id"]]
        select = db.transaction_selects()
        assert select
        logged = [(name, args) for table, name, args in db.log if table == db.transactions_name]
        assert ("eq", ("valor", 0.0)) in logged
        assert ("eq", ("data", TODAY_ISO)) in logged
        assert ("neq", ("natureza", "Receita")) in logged
        assert ("gte", ("valor", 0)) in logged

    def test_entry_type_only_returns_income(self, env):
        db = env.db
        db.add(valor=0.0)
        income = db.add(valor=0.0, natureza="Receita", categoria="Salário")
        rows = db_repository.buscar_candidatos_exclusao(_normalized({"valor_exato": 0, "tipo_transacao": "entrada"}))
        assert [r["id"] for r in rows] == [income["id"]]

    def test_zero_without_date_adds_no_date_filter(self, env):
        env.db.add(valor=0.0)
        env.db.add(valor=0.0, data=YESTERDAY_ISO)
        rows = db_repository.buscar_candidatos_exclusao(_normalized({"valor_exato": 0}))
        assert len(rows) == 2
        names = [(name, args[0]) for table, name, args in env.db.log if table == env.db.transactions_name and args]
        assert ("eq", "data") not in names and ("gte", "data") not in names and ("lte", "data") not in names

    def test_month_and_year_periods_filter_inclusively(self, env):
        db = env.db
        inside = [db.add(data="2026-02-01"), db.add(data="2026-02-28")]
        db.add(data="2026-03-01")
        db.add(data="2025-02-10")
        month = db_repository.buscar_candidatos_exclusao(_normalized({"mes": "02", "ano": "2026"}))
        assert [r["id"] for r in month] == [r["id"] for r in inside]
        year = db_repository.buscar_candidatos_exclusao(_normalized({"ano": "2026"}))
        assert len(year) == 3

    def test_identifying_fields_filter_by_equality(self, env):
        db = env.db
        target = db.add(categoria="Transporte", natureza="Essencial", conta="Itaú", metodo_pagamento="Cartão de Crédito")
        db.add(categoria="Mercado")
        db.add(conta="Nubank")
        rows = db_repository.buscar_candidatos_exclusao(
            _normalized({"categoria": "Transporte", "natureza": "Essencial", "conta": "Itaú", "metodo_pagamento": "crédito"})
        )
        assert [r["id"] for r in rows] == [target["id"]]

    def test_payment_pattern_escapes_wildcards(self, env):
        db = env.db
        literal = db.add(metodo_pagamento="100%_cartão")
        db.add(metodo_pagamento="100 cartão")
        db.add(metodo_pagamento="Pix")
        rows = db_repository.buscar_candidatos_exclusao(_normalized({"metodo_pagamento": "100%_"}))
        assert [r["id"] for r in rows] == [literal["id"]]
        logged = [args for table, name, args in env.db.log if name == "ilike"]
        assert logged == [("metodo_pagamento", "%100\\%\\_%")]

    @pytest.mark.parametrize("payment", ["*", "Cartão *1234", "Pix*", "\\*"])
    def test_repository_refuses_asterisk_payment_without_querying(self, env, payment):
        env.db.add(metodo_pagamento="Cartão 1234")
        filters = finance.DeleteFilters(valor_exato=0.0, metodo_pagamento=payment)
        with pytest.raises(ValueError):
            db_repository.buscar_candidatos_exclusao(filters)
        assert [name for _, name, _ in env.db.log if name in ("ilike", "range", "execute")] == []

    def test_negative_values_stay_excluded(self, env):
        env.db.add(valor=-5.0)
        assert db_repository.buscar_candidatos_exclusao(_normalized({"categoria": "Mercado"})) == []

    def test_pagination_returns_every_candidate_sorted_without_duplicates(self, env):
        db = env.db
        total = 1234
        for _ in range(total):
            db.add(valor=0.0)
        db.transactions.reverse()  # o fake entrega cada página em ordem de armazenamento invertida
        filters = _normalized({"valor_exato": 0, "escopo": "varios"})

        rows = db_repository.buscar_candidatos_exclusao(filters)

        ids = [r["id"] for r in rows]
        assert len(ids) == total and ids == sorted(set(ids)) == list(range(1, total + 1))
        ranges = [args for table, name, args in db.log if name == "range"]
        size = db_repository.DUPLICATE_LOOKUP_PAGE_SIZE
        assert ranges == [(0, size - 1), (size, 2 * size - 1), (2 * size, 3 * size - 1)]
        assert ("id", False) in [args for table, name, args in db.log if name == "order"]

    def test_exact_page_boundary_stops_on_empty_next_page(self, env):
        size = db_repository.DUPLICATE_LOOKUP_PAGE_SIZE
        for _ in range(size):
            env.db.add(valor=0.0)
        rows = db_repository.buscar_candidatos_exclusao(_normalized({"valor_exato": 0, "escopo": "varios"}))
        assert len(rows) == size
        ranges = [args for table, name, args in env.db.log if name == "range"]
        assert ranges == [(0, size - 1), (size, 2 * size - 1)]

    def test_duplicated_ids_across_pages_are_collapsed(self):
        size = db_repository.DUPLICATE_LOOKUP_PAGE_SIZE
        page_one = [{"id": i, "valor": 0.0} for i in range(1, size + 1)]
        page_two = [{"id": size, "valor": 0.0}, {"id": size + 1, "valor": 0.0}]
        pages = [page_one, page_two]

        class Pager:
            def __getattr__(self, name):
                return lambda *a, **k: self

            def execute(self):
                return MagicMock(data=pages.pop(0))

        fake = MagicMock()
        fake.table.return_value = Pager()
        with patch.object(db_repository, "supabase", fake):
            rows = db_repository.buscar_candidatos_exclusao(_normalized({"valor_exato": 0, "escopo": "varios"}))
        assert [r["id"] for r in rows] == list(range(1, size + 2))

    @pytest.mark.parametrize("bad", [None, {"id": 1}, [{"valor": 0.0}], ["x"], [{"id": True}], [{"id": None}]])
    def test_malformed_response_fails_loudly(self, bad):
        class Broken:
            def __getattr__(self, name):
                return lambda *a, **k: self

            def execute(self):
                return MagicMock(data=bad)

        fake = MagicMock()
        fake.table.return_value = Broken()
        with patch.object(db_repository, "supabase", fake):
            with pytest.raises(RuntimeError):
                db_repository.buscar_candidatos_exclusao(_normalized({"valor_exato": 0}))

    def test_existing_query_helper_keeps_its_contract(self, env):
        env.db.add(valor=7.0)
        env.db.add(valor=8.0)
        assert db_repository.consultar_no_banco({"valor_exato": 7}) == (7.0, 1)


class TestApagarRegistrosPorIds:
    def test_deletes_only_given_ids_in_bounded_batches(self, env):
        db = env.db
        rows = [db.add() for _ in range(450)]
        keep = db.add()
        deleted = db_repository.apagar_registros_por_ids([r["id"] for r in rows])
        assert deleted == 450
        assert [r["id"] for r in db.transactions] == [keep["id"]]
        batches = [args[1] for table, name, args in db.log if name == "in_"]
        assert len(batches) == 3 and all(len(b) <= db_repository.DELETE_BATCH_SIZE for b in batches)

    @pytest.mark.parametrize("bad", [[], None, "1,2", [True], [None], [1.5], {"id": 1}, [{"id": 1}]])
    def test_invalid_ids_never_reach_the_database(self, env, bad):
        env.db.add()
        with pytest.raises(ValueError):
            db_repository.apagar_registros_por_ids(bad)
        assert env.db.transaction_deletes() == [] and len(env.db.transactions) == 1


# --------------------------------------------------------------------------
# CA5: prévia
# --------------------------------------------------------------------------
def _record(index, **overrides):
    row = {
        "id": index,
        "data": TODAY_ISO,
        "valor": 0.0,
        "natureza": "Essencial",
        "categoria": "Mercado",
        "descricao": f"Descrição {index}",
        "metodo_pagamento": "Pix",
        "conta": "Nubank",
    }
    row.update(overrides)
    return row


class TestFormatarPreviaExclusao:
    def test_all_filters_present_are_shown_with_real_values(self):
        filters = _normalized({
            "valor_exato": 0, "data": TODAY_ISO, "conta": "Nubank", "categoria": "Mercado", "metodo_pagamento": "Pix",
            "natureza": "Essencial", "tipo_transacao": "saida",
        })
        text = core_logic.formatar_previa_exclusao(filters, [_record(1)])
        assert "R$ 0.00" in text and TODAY_ISO in text
        assert "Nubank" in text and "Mercado" in text and "Pix" in text and "Essencial" in text
        assert "sem filtro de" not in text
        assert "1 registro" in text

    def test_every_absence_is_stated(self):
        text = core_logic.formatar_previa_exclusao(_normalized({"categoria": "Mercado"}), [_record(1)])
        for absent in ("valor", "data", "conta", "pagamento", "natureza", "tipo"):
            assert f"sem filtro de {absent}" in text
        assert "sem filtro de categoria" not in text

    @pytest.mark.parametrize(
        "raw,expected",
        [({"mes": "03", "ano": "2026"}, "03/2026"), ({"ano": "2026"}, "2026"), ({"data": "2026-03-15"}, "2026-03-15")],
    )
    def test_period_is_shown(self, raw, expected):
        text = core_logic.formatar_previa_exclusao(_normalized(raw), [_record(1)])
        assert expected in text and "sem filtro de data" not in text

    def test_each_record_shows_its_fields(self):
        filters = _normalized({"valor_exato": 12.5})
        rows = [_record(1, valor=12.5, descricao="Café", categoria="Bares e Restaurantes", conta="Itaú", metodo_pagamento="Débito", data="2026-05-04")]
        text = core_logic.formatar_previa_exclusao(filters, rows)
        for part in ("2026-05-04", "R$ 12.50", "Café", "Bares e Restaurantes", "Itaú", "Débito"):
            assert part in text

    def test_small_set_lists_everything_without_sample_notice(self):
        rows = [_record(i) for i in range(1, 4)]
        text = core_logic.formatar_previa_exclusao(_normalized({"valor_exato": 0, "escopo": "varios"}), rows)
        assert all(f"Descrição {i}" in text for i in (1, 2, 3))
        assert "amostra" not in text and "não exibidos" not in text
        assert "3 registros" in text

    def test_large_set_shows_faithful_total_sample_and_omitted(self):
        rows = [_record(i) for i in range(1, 1235)]
        text = core_logic.formatar_previa_exclusao(_normalized({"valor_exato": 0, "escopo": "varios"}), rows)
        assert "1234" in text
        assert "amostra de 10 de 1234" in text
        assert "mais 1224 não exibidos" in text
        assert "inclusive os não exibidos" in text
        assert "Descrição 10" in text and "Descrição 11" not in text
        assert len(text) <= PREVIEW_LIMIT

    def test_user_text_is_markdown_escaped_and_none_is_handled(self):
        rows = [_record(1, descricao="a_b*c`d[e", conta=None, categoria=None, metodo_pagamento=None), _record(2, descricao=None)]
        text = core_logic.formatar_previa_exclusao(_normalized({"valor_exato": 0, "escopo": "varios"}), rows)
        assert "a\\_b\\*c\\`d\\[e" in text
        assert "None" not in text

    def test_user_filter_text_is_escaped(self):
        text = core_logic.formatar_previa_exclusao(_normalized({"conta": "Banco_X*"}), [_record(1)])
        assert "Banco\\_X\\*" in text

    def test_pathological_text_still_fits_in_a_telegram_message(self):
        nasty = "_*`[\\" * 30
        rows = [_record(i, descricao=nasty, conta=nasty, categoria=nasty, metodo_pagamento=nasty) for i in range(1, 60)]
        filters = _normalized({"conta": "_" * 120, "metodo_pagamento": "_`[\\" * 30, "valor_exato": 0, "escopo": "varios"})
        text = core_logic.formatar_previa_exclusao(filters, rows)
        assert len(text) <= PREVIEW_LIMIT
        assert "59" in text and "não exibidos" in text

    def test_sample_shrinks_and_stays_truthful_when_the_message_would_overflow(self):
        rows = [_record(i) for i in range(1, 40)]
        filters = _normalized({"valor_exato": 0, "escopo": "varios"})
        with patch.object(core_logic, "TELEGRAM_MESSAGE_LIMIT", 800):
            text = core_logic.formatar_previa_exclusao(filters, rows)
        shown = int(re.search(r"amostra de (\d+) de 39", text).group(1))
        assert len(text) <= 800 and shown < core_logic.DELETE_PREVIEW_SAMPLE
        assert f"mais {39 - shown} não exibidos" in text and f"Descrição {shown}" in text
        assert "inclusive os não exibidos" in text

    def test_payment_filter_is_shown_as_contains_not_equality(self):
        text = core_logic.formatar_previa_exclusao(_normalized({"metodo_pagamento": "Cartão"}), [_record(1, metodo_pagamento="Cartão de crédito")])
        assert "Pagamento (contém): Cartão" in text
        assert "Pagamento: Cartão" not in text
        assert "Cartão de crédito" in text

    def test_payment_as_fragment_matches_longer_value_and_preview_is_faithful(self, env):
        db = env.db
        target = db.add(valor=0.0, metodo_pagamento="Cartão de crédito")
        db.add(valor=0.0, metodo_pagamento="Pix")
        filters = _normalized({"metodo_pagamento": "Cartão"})
        rows = db_repository.buscar_candidatos_exclusao(filters)
        assert [r["id"] for r in rows] == [target["id"]]
        text = core_logic.formatar_previa_exclusao(filters, rows)
        assert "Pagamento (contém): Cartão" in text and "Cartão de crédito" in text

    def test_payment_wildcards_are_escaped_in_the_query_and_the_preview_says_contains(self, env):
        literal = env.db.add(metodo_pagamento="100%_cartão")
        env.db.add(metodo_pagamento="100 cartão")
        filters = _normalized({"metodo_pagamento": "100%_"})
        rows = db_repository.buscar_candidatos_exclusao(filters)
        assert [r["id"] for r in rows] == [literal["id"]]
        assert [a for _, n, a in env.db.log if n == "ilike"] == [("metodo_pagamento", "%100\\%\\_%")]
        assert "Pagamento (contém): 100%\\_" in core_logic.formatar_previa_exclusao(filters, rows)

    def test_long_item_fields_are_shown_in_full_when_they_fit(self):
        long_desc = "Compra de supermercado do mês com várias coisas " + "x" * 40
        long_cat = "Bares e Restaurantes e outras categorias longas"
        long_account = "Conta corrente principal do banco muito longo"
        long_payment = "Cartão de crédito Visa final 1234 platinum"
        rows = [_record(1, descricao=long_desc, categoria=long_cat, conta=long_account, metodo_pagamento=long_payment)]
        text = core_logic.formatar_previa_exclusao(_normalized({"valor_exato": 0}), rows)
        for part in (long_desc, long_cat, long_account, long_payment):
            assert part in text
        assert "abreviado" not in text

    def test_exceptionally_large_field_is_explicitly_marked_as_abbreviated(self):
        huge = "y" * 5000
        rows = [_record(1, descricao=huge), _record(2)]
        text = core_logic.formatar_previa_exclusao(_normalized({"valor_exato": 0, "escopo": "varios"}), rows)
        assert "abreviado" in text and huge not in text
        assert len(text) <= PREVIEW_LIMIT
        assert "2 registros" in text

    def test_abbreviation_marker_only_on_the_abbreviated_item(self):
        rows = [_record(1, descricao="z" * 5000), _record(2, descricao="Curta")]
        text = core_logic.formatar_previa_exclusao(_normalized({"valor_exato": 0, "escopo": "varios"}), rows)
        assert text.count("abreviado") == 1
        assert "Curta" in text

    def test_sample_with_large_items_stays_honest_about_omitted(self):
        rows = [_record(i, descricao="w" * 5000) for i in range(1, 30)]
        text = core_logic.formatar_previa_exclusao(_normalized({"valor_exato": 0, "escopo": "varios"}), rows)
        shown = int(re.search(r"amostra de (\d+) de 29", text).group(1))
        assert len(text) <= PREVIEW_LIMIT
        assert f"mais {29 - shown} não exibidos" in text and "inclusive os não exibidos" in text

    def test_empty_selection_has_no_confirmation_text(self):
        text = core_logic.formatar_previa_exclusao(_normalized({"valor_exato": 0}), [])
        assert "Nenhum registro" in text and "Confirmar" not in text

    def test_old_report_is_untouched(self):
        text = core_logic.formatar_relatorio_exclusao([{"data": TODAY_ISO, "valor": 1.0, "natureza": "Lazer", "categoria": "Viagens", "descricao": "x", "metodo_pagamento": "Pix", "conta": "Nubank"}])
        assert "ATENÇÃO: EXCLUSÃO DE DADOS" in text


# --------------------------------------------------------------------------
# CA1–CA5: fluxo iniciar_fluxo_exclusao
# --------------------------------------------------------------------------
class TestFluxoExclusao:
    @pytest.mark.asyncio
    async def test_zero_of_the_day_selects_only_that_expense(self, env):
        db = env.db
        target = db.add(valor=0.0)
        db.add(valor=0.0, data=YESTERDAY_ISO)
        db.add(valor=15.0)
        db.add(valor=0.0, natureza="Receita", categoria="Salário")
        await env.start({"valor_exato": 0, "data": TODAY_ISO, "tipo_transacao": "saida"})

        assert env.stored_ids() == [target["id"]]
        assert env.button_ids() == [f"confirmdel_{env.db.pending[-1]['id']}", f"cancelar_{env.db.pending[-1]['id']}"]
        text = env.sent_texts()[0]
        assert "R$ 0.00" in text and TODAY_ISO in text
        assert db.transaction_deletes() == []
        assert len(db.transactions) == 4

    @pytest.mark.asyncio
    async def test_zero_without_date_does_not_assume_today(self, env):
        db = env.db
        db.add(valor=0.0)
        db.add(valor=0.0, data=YESTERDAY_ISO)
        await env.start({"valor_exato": 0, "escopo": "varios"})
        assert len(env.stored_ids()) == 2
        assert "sem filtro de data" in env.sent_texts()[0]

    @pytest.mark.asyncio
    async def test_exact_day_month_and_year_are_faithful(self, env):
        db = env.db
        day = db.add(data="2026-04-10")
        db.add(data="2026-04-11")
        db.add(data="2026-05-10")
        await env.start({"data": "2026-04-10"})
        assert env.stored_ids() == [day["id"]]
        await env.start({"mes": "04", "ano": "2026", "escopo": "varios"})
        assert len(env.stored_ids()) == 2
        await env.start({"ano": "2026", "escopo": "varios"})
        assert len(env.stored_ids()) == 3

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "raw",
        [
            {"data": "2026-13-45"},
            {"valor_exato": 5, "mes": "03"},
            {"data": "2026-11-11", "mes": "10", "ano": "2026"},
            {"valor_exato": "abc"},
            {"categoria": "Inventada"},
        ],
    )
    async def test_unclear_requests_ask_for_clarification_without_querying(self, env, raw):
        env.db.add(valor=5.0)
        await env.start(raw)
        assert env.db.transaction_selects() == []
        assert env.db.pending == [] and env.last_markup() is None
        assert len(env.sent_texts()) == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payment", ["*", "Cartão *1234", "Cartão \\*1234", "Pix*"])
    @pytest.mark.parametrize("extra", [{}, {"valor_exato": 0}, {"data": TODAY_ISO, "tipo_transacao": "saida"}, {"conta": "Nubank", "escopo": "varios"}])
    async def test_asterisk_payment_refuses_whole_request_without_querying_or_pending(self, env, payment, extra):
        env.db.add(valor=0.0, metodo_pagamento="Cartão 1234")
        env.db.add(valor=0.0, metodo_pagamento="Pix")
        await env.start({**extra, "metodo_pagamento": payment})
        assert env.db.transaction_selects() == []
        assert env.db.transaction_deletes() == []
        assert env.db.pending == [] and env.last_markup() is None
        assert len(env.sent_texts()) == 1 and "método de pagamento" in env.sent_texts()[0]

    @pytest.mark.asyncio
    async def test_account_with_asterisk_is_equality_and_still_selects(self, env):
        target = env.db.add(valor=0.0, conta="Conta *1234")
        env.db.add(valor=0.0, conta="Conta 51234")
        await env.start({"conta": "Conta *1234", "escopo": "varios"})
        assert env.stored_ids() == [target["id"]]

    @pytest.mark.asyncio
    async def test_single_scope_with_one_candidate_shows_preview(self, env):
        target = env.db.add(valor=0.0)
        await env.start({"valor_exato": 0, "escopo": "um"})
        assert env.stored_ids() == [target["id"]]
        assert env.last_markup() is not None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scope", ["um", None, "invalido"])
    async def test_single_scope_with_many_candidates_asks_for_more_criteria(self, env, scope):
        for _ in range(3):
            env.db.add(valor=0.0)
        raw = {"valor_exato": 0}
        if scope is not None:
            raw["escopo"] = scope
        await env.start(raw)
        text = env.sent_texts()[0]
        assert "3" in text and "outro critério" in text
        assert env.db.pending == [] and env.last_markup() is None
        assert env.db.transaction_deletes() == []

    @pytest.mark.asyncio
    async def test_several_scope_with_many_candidates_shows_preview_with_all_ids(self, env):
        for _ in range(3):
            env.db.add(valor=0.0)
        await env.start({"valor_exato": 0, "escopo": "varios"})
        assert env.stored_ids() == [1, 2, 3]
        assert "3 registros" in env.sent_texts()[0]

    @pytest.mark.asyncio
    async def test_no_candidates_means_no_confirmation(self, env):
        env.db.add(valor=7.0)
        await env.start({"valor_exato": 0})
        assert "Não encontrei" in env.sent_texts()[0]
        assert env.db.pending == [] and env.last_markup() is None

    @pytest.mark.asyncio
    async def test_incomplete_request_keeps_previous_pending_untouched(self, env):
        env.db.add(valor=0.0)
        await env.start({"valor_exato": 0})
        before = [dict(r) for r in env.db.pending]
        selects_before = len(env.db.transaction_selects())
        env.send.reset_mock()

        await env.start({"pedido_incompleto": True, "data": TODAY_ISO, "valor_exato": 0})

        assert [dict(r) for r in env.db.pending] == before
        assert len(env.db.transaction_selects()) == selects_before
        assert env.db.transaction_deletes() == []
        assert env.last_markup() is None
        assert "identifi" in env.sent_texts()[0]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("raw", [{}, {"tipo_transacao": "saida"}, {"tipo_transacao": "entrada", "escopo": "varios"}, {"pedido_incompleto": "true"}])
    async def test_delete_everything_or_type_only_is_refused(self, env, raw):
        for _ in range(3):
            env.db.add(valor=0.0)
        await env.start(raw)
        assert "Operação Recusada" in env.sent_texts()[0]
        assert env.db.transaction_selects() == [] and env.db.pending == []
        assert len(env.db.transactions) == 3

    @pytest.mark.asyncio
    async def test_all_candidates_are_stored_beyond_one_page_and_preview_fits(self, env):
        total = 1234
        for _ in range(total):
            env.db.add(valor=0.0)
        env.db.transactions.reverse()
        await env.start({"valor_exato": 0, "escopo": "varios"})
        ids = env.stored_ids()
        assert ids == list(range(1, total + 1))
        text = env.sent_texts()[0]
        assert "1234" in text and "mais 1224 não exibidos" in text and "inclusive os não exibidos" in text
        assert len(text) <= PREVIEW_LIMIT

    @pytest.mark.asyncio
    async def test_origin_is_bound_to_chat_and_sender(self, env):
        env.db.add(valor=0.0)
        await env.start({"valor_exato": 0}, user=USER)
        row = env.db.pending[-1]
        assert row["kind"] == "delete_confirmation"
        assert row["origin_chat_id"] == str(CHAT) and row["origin_user_id"] == str(USER)
        assert row["payload"] == {} and "ids" not in json.dumps(row["payload"])
        assert security.decrypt_pending_payload(row["payload_ciphertext"]) == {"ids": [1]}
        assert row["expires_at"]

    @staticmethod
    async def _send_text(text, llm_result, update_id):
        llm = AsyncMock(return_value=llm_result)
        update = {"update_id": update_id, "message": {"chat": {"id": CHAT}, "from": {"id": USER}, "text": text}}
        with patch.object(handlers, "processar_texto_com_llm", llm), \
                patch.object(handlers, "allow_request", return_value=True), \
                patch.object(handlers, "_resume_existing_effect", AsyncMock(return_value=False)):
            await handlers.processar_update_assincrono(update, source_update_id=update_id)
        return llm

    @pytest.mark.asyncio
    async def test_isolated_fragment_alone_asks_to_identify_again_without_side_effects(self, env):
        env.db.add(valor=0.0)
        transactions_before = [dict(r) for r in env.db.transactions]
        # resposta de IA simulada: não prova acurácia do modelo real
        simulated = {"intencao": "excluir", "filtros_exclusao": {"pedido_incompleto": True, "data": TODAY_ISO}}

        llm = await self._send_text("só o de hoje", simulated, 5100)

        assert llm.await_args.args == ("só o de hoje",)
        assert "identifi" in env.sent_texts()[0] and env.last_markup() is None
        assert env.db.transaction_selects() == [] and env.db.transaction_deletes() == []
        assert env.db.pending == []
        assert [dict(r) for r in env.db.transactions] == transactions_before

    @pytest.mark.asyncio
    async def test_isolated_fragment_after_a_previous_request_does_not_confirm_or_inherit(self, env):
        env.db.add(valor=0.0)
        await env.start({"valor_exato": 0, "data": TODAY_ISO})
        pending_before = [dict(r) for r in env.db.pending]
        selects_before = len(env.db.transaction_selects())
        transactions_before = [dict(r) for r in env.db.transactions]
        env.send.reset_mock()
        simulated = {"intencao": "excluir", "filtros_exclusao": {"pedido_incompleto": True}}

        llm = await self._send_text("só o de hoje", simulated, 5101)

        assert llm.await_args.args == ("só o de hoje",)
        assert "identifi" in env.sent_texts()[0] and env.last_markup() is None
        assert len(env.db.transaction_selects()) == selects_before
        assert env.db.transaction_deletes() == []
        assert [dict(r) for r in env.db.pending] == pending_before
        assert [dict(r) for r in env.db.transactions] == transactions_before

    @pytest.mark.asyncio
    async def test_update_handler_still_passes_the_ai_contract_through(self, env):
        llm = AsyncMock(return_value={"intencao": "excluir", "filtros_exclusao": {"valor_exato": 0, "data": TODAY_ISO, "escopo": "um", "tipo_transacao": "saida"}})
        env.db.add(valor=0.0)
        update = {"update_id": 5000, "message": {"chat": {"id": CHAT}, "from": {"id": USER}, "text": "apague a despesa de zero de hoje"}}
        with patch.object(handlers, "processar_texto_com_llm", llm), \
                patch.object(handlers, "allow_request", return_value=True), \
                patch.object(handlers, "_resume_existing_effect", AsyncMock(return_value=False)):
            await handlers.processar_update_assincrono(update, source_update_id=5000)
        assert env.last_markup() is not None and env.stored_ids() == [1]


# --------------------------------------------------------------------------
# CA6: proteções do fluxo de confirmação com o store real (cifrado) e banco fake
# --------------------------------------------------------------------------
async def _prepared(env, **overrides):
    """Prévia concluída para 2 registros; devolve (ids congelados, id da pendência)."""
    env.db.add(valor=0.0)
    env.db.add(valor=0.0)
    env.db.add(valor=9.0)
    await env.start({"valor_exato": 0, "escopo": "varios", **overrides})
    return env.stored_ids(), env.db.pending[-1]["id"]


class TestConfirmacao:
    @pytest.mark.asyncio
    async def test_confirm_deletes_exactly_the_frozen_ids_even_with_new_rows(self, env):
        ids, cache_id = await _prepared(env)
        assert ids == [1, 2] and env.db.transaction_deletes() == []
        newcomer = env.db.add(valor=0.0)  # criado depois da prévia
        await env.callback(f"confirmdel_{cache_id}")
        remaining = [r["id"] for r in env.db.transactions]
        assert remaining == [3, newcomer["id"]]
        assert "2 registros apagados" in env.edited_texts()[-1]
        assert env.db.pending == []

    @pytest.mark.asyncio
    async def test_cancel_removes_pending_without_deleting_and_blocks_later_confirm(self, env):
        _, cache_id = await _prepared(env)
        await env.callback(f"cancelar_{cache_id}")
        assert env.db.transaction_deletes() == [] and env.db.pending == []
        assert "Cancelada" in env.edited_texts()[-1]
        await env.callback(f"confirmdel_{cache_id}", update_id=901)
        assert env.db.transaction_deletes() == [] and len(env.db.transactions) == 3
        assert "expirado ou já processado" in env.edited_texts()[-1]

    @pytest.mark.asyncio
    async def test_replayed_confirmation_deletes_once(self, env):
        _, cache_id = await _prepared(env)
        await env.callback(f"confirmdel_{cache_id}")
        assert len(env.db.transaction_deletes()) == 1
        env.db.add(valor=0.0)
        await env.callback(f"confirmdel_{cache_id}", update_id=901)
        assert len(env.db.transaction_deletes()) == 1
        assert "expirado ou já processado" in env.edited_texts()[-1]
        assert len(env.db.transactions) == 2

    @pytest.mark.asyncio
    async def test_expired_pending_is_removed_without_deleting(self, env):
        _, cache_id = await _prepared(env)
        env.db.pending[-1]["expires_at"] = (TODAY - timedelta(days=30)).isoformat()
        await env.callback(f"confirmdel_{cache_id}")
        assert env.db.transaction_deletes() == [] and env.db.pending == []
        assert "expirado ou já processado" in env.edited_texts()[-1]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("chat,user", [(CHAT + 1, USER), (CHAT, USER + 1)])
    async def test_wrong_chat_or_sender_cannot_confirm(self, env, chat, user):
        _, cache_id = await _prepared(env)
        await env.callback(f"confirmdel_{cache_id}", chat=chat, user=user)
        assert env.db.transaction_deletes() == [] and len(env.db.pending) == 1
        assert "Operação não autorizada" in env.edited_texts()[-1]
        assert len(env.db.transactions) == 3

    @pytest.mark.asyncio
    async def test_wrong_kind_cannot_be_used_to_delete(self, env):
        env.db.add(valor=0.0)
        record = security.store_pending_item({"itens": []}, kind="receipt_batch", origin_chat_id=CHAT, origin_user_id=USER)
        await env.callback(f"confirmdel_{record['id']}")
        assert env.db.transaction_deletes() == [] and len(env.db.transactions) == 1
        assert "Tipo de pendência inválido" in env.edited_texts()[-1]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", [{"ids": []}, {"ids": "1,2"}, {"ids": [None]}, {"ids": [True]}, {"ids": [{"id": 1}]}, {}])
    async def test_empty_or_malformed_ids_never_delete(self, env, payload):
        env.db.add(valor=0.0)
        record = security.store_pending_item(payload, kind="delete_confirmation", origin_chat_id=CHAT, origin_user_id=USER)
        await env.callback(f"confirmdel_{record['id']}")
        assert env.db.transaction_deletes() == [] and len(env.db.transactions) == 1
        assert "inválid" in env.edited_texts()[-1]

    @pytest.mark.asyncio
    async def test_starting_the_flow_never_deletes(self, env):
        await _prepared(env)
        await env.start({"valor_exato": 0, "escopo": "varios"})
        await env.start({"valor_exato": 99})
        assert env.db.transaction_deletes() == []
        assert len(env.db.transactions) == 3


# --------------------------------------------------------------------------
# Contrato com a IA (prompt): data, tipo, escopo e pedido incompleto
# --------------------------------------------------------------------------
class TestPromptContract:
    @pytest.mark.asyncio
    async def test_exclusion_contract_is_in_the_prompt_and_today_rule_is_register_only(self):
        class Msg:
            content = json.dumps({"intencao": "excluir"})

        class Choice:
            message = Msg()

        class Response:
            choices = [Choice()]

        create = AsyncMock(return_value=Response())
        fake_client = MagicMock()
        fake_client.chat.completions.create = create
        with patch.object(ai_service, "deepseek_client", fake_client), \
                patch.object(ai_service, "get_brasilia_time", lambda: TODAY):
            await ai_service.processar_texto_com_llm("apague a despesa de zero de hoje")
        prompt = create.call_args.kwargs["messages"][0]["content"]

        assert f"Hoje é {TODAY_ISO}" in prompt
        block = prompt[prompt.index('"filtros_exclusao"'):]
        for field in ('"data": "YYYY-MM-DD"', '"tipo_transacao"', '"escopo"', '"pedido_incompleto"', '"valor_exato"'):
            assert field in block
        assert "um" in block and "varios" in block
        # a regra de hoje vale só para o registro; a exclusão não preenche período não citado
        assert "Se omitido, use a data de hoje" not in prompt
        assert re.search(r"dados_registro[^\n]*data de hoje|data de hoje[^\n]*dados_registro", prompt)
        assert "não preencha data" in prompt.lower().replace("\n", " ")
        assert "pedido_incompleto" in prompt and "true" in prompt

    @pytest.mark.asyncio
    async def test_isolated_fragment_is_an_incomplete_delete_request_in_the_prompt(self):
        class Msg:
            content = json.dumps({"intencao": "excluir", "filtros_exclusao": {"pedido_incompleto": True}})

        class Choice:
            message = Msg()

        class Response:
            choices = [Choice()]

        create = AsyncMock(return_value=Response())
        fake_client = MagicMock()
        fake_client.chat.completions.create = create
        with patch.object(ai_service, "deepseek_client", fake_client), \
                patch.object(ai_service, "get_brasilia_time", lambda: TODAY):
            await ai_service.processar_texto_com_llm("só o de hoje")
        prompt = create.call_args.kwargs["messages"][0]["content"]
        rules = prompt[prompt.index("<regras_de_exclusao>"):prompt.index("</regras_de_exclusao>")]
        flat = " ".join(rules.split()).lower()

        assert "só o de hoje" in flat
        fragment_rule = flat[flat.index("só o de hoje") - 400: flat.index("só o de hoje") + 400]
        assert "sem o verbo excluir" in fragment_rule
        assert '"excluir"' in fragment_rule and "pedido_incompleto" in fragment_rule and "true" in fragment_rule
        assert "não registre" in fragment_rule and "não consulte" in fragment_rule
