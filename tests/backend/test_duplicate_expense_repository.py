import os
from datetime import datetime
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

import db_repository
from domain.duplicate_expense import prepare_duplicate_candidate


class FakeQuery:
    """Records the PostgREST chain and serves pre-baked pages for .range()."""

    def __init__(self, pages=None, error=None, malformed=False):
        self.calls = []
        self.pages = list(pages or [])
        self.error = error
        self.malformed = malformed
        self._range = None

    def __getattr__(self, name):
        def method(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name == "range":
                self._range = args
            return self

        return method

    def execute(self):
        if self.error:
            raise self.error
        if self.malformed:
            return MagicMock(data=None)
        return MagicMock(data=self.pages.pop(0) if self.pages else [])


def _candidate(**overrides):
    dados = {
        "data": "2026-11-10",
        "valor_total": 25.5,
        "parcelas": 1,
        "categoria": "Mercado",
        "descricao": "Padaria Central",
        "metodo_pagamento": "Pix",
        "conta": "Nubank",
    }
    dados.update(overrides)
    return prepare_duplicate_candidate(dados, fallback_date=datetime(2026, 11, 11))


def _row(row_id, **overrides):
    row = {"id": row_id, "data": "2026-11-10", "valor": 25.5, "natureza": "Essencial", "conta": "nubank", "descricao": "padaria central"}
    row.update(overrides)
    return row


def _run(query, candidate=None):
    supabase = MagicMock()
    supabase.table.return_value = query
    with patch.object(db_repository, "supabase", supabase):
        result = db_repository.find_matching_expense(candidate or _candidate())
    return result, supabase


class TestFindMatchingExpense:
    def test_filters_date_value_and_expense_in_the_database_in_id_order(self):
        query = FakeQuery(pages=[[_row(3)]])
        result, supabase = _run(query)

        assert result["id"] == 3
        supabase.table.assert_called_once_with(db_repository.TRANSACTIONS_TABLE)
        names = {name: args for name, args, _ in query.calls}
        assert names["eq"] in {("data", "2026-11-10"), ("valor", 25.5)}
        assert ("eq", ("data", "2026-11-10"), {}) in query.calls
        assert ("eq", ("valor", 25.5), {}) in query.calls
        assert ("neq", ("natureza", "Receita"), {}) in query.calls
        assert ("order", ("id",), {"desc": False}) in query.calls
        # no chat/source/category/method filter
        filtered_columns = {args[0] for name, args, _ in query.calls if name in {"eq", "neq", "ilike"}}
        assert filtered_columns == {"data", "valor", "natureza"}

    def test_returns_none_without_match(self):
        result, _ = _run(FakeQuery(pages=[[_row(1, descricao="outra")]]))
        assert result is None

    def test_paginates_without_truncating_and_stops_at_first_match(self):
        size = db_repository.DUPLICATE_LOOKUP_PAGE_SIZE
        page1 = [_row(i, descricao="x") for i in range(1, size + 1)]
        page2 = [_row(size + 1, descricao="x"), _row(size + 2)]
        query = FakeQuery(pages=[page1, page2, [_row(999)]])
        result, _ = _run(query)

        assert result["id"] == size + 2
        ranges = [args for name, args, _ in query.calls if name == "range"]
        assert ranges == [(0, size - 1), (size, 2 * size - 1)]

    def test_paginates_until_a_short_page(self):
        size = db_repository.DUPLICATE_LOOKUP_PAGE_SIZE
        query = FakeQuery(pages=[[_row(i, descricao="x") for i in range(size)], []])
        result, _ = _run(query)
        assert result is None
        assert len([1 for name, *_ in query.calls if name == "range"]) == 2

    def test_query_error_is_raised_never_treated_as_no_match(self):
        with pytest.raises(RuntimeError):
            _run(FakeQuery(error=RuntimeError("boom")))

    def test_malformed_response_fails_closed(self):
        with pytest.raises(RuntimeError, match="unavailable"):
            _run(FakeQuery(malformed=True))
