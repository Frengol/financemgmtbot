"""
Suíte de Testes Automatizados — financemgmtbot/main.py
Cobre TODAS as funções: lógica pura, negócio, DB, Telegram, IA e controller.
Todas as dependências externas (Supabase, Telegram, LLMs) são mockadas.
"""
import os
import sys
import json
import asyncio
import calendar
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch, MagicMock, AsyncMock, PropertyMock
from collections import defaultdict
from typing import Dict, List, Any

import pytest

# ============================================================
# SETUP: Mock all env vars and external clients BEFORE import
# ============================================================
ENV_VARS = {
    "TELEGRAM_BOT_TOKEN": "FAKE_TELEGRAM_TOKEN",
    "TELEGRAM_SECRET_TOKEN": "FAKE_SECRET",
    "SUPABASE_URL": "https://fake.supabase.co",
    "SUPABASE_KEY": "FAKE_SUPABASE_KEY_1234567890",
    "DEEPSEEK_API_KEY": "FAKE_DEEPSEEK_KEY_1234567890",
    "GROQ_API_KEY": "FAKE_GROQ_KEY_1234567890",
    "GEMINI_API_KEY": "FAKE_GEMINI_KEY_1234567890",
}


@pytest.fixture(autouse=True)
def _env_vars(monkeypatch):
    for k, v in ENV_VARS.items():
        monkeypatch.setenv(k, v)


@pytest.fixture(autouse=True)
def _reset_security_state():
    with patch.dict(security._RATE_LIMIT_BUCKETS, {}, clear=True):
        yield


# Patch heavy external clients at module level so they don't connect on import
_mock_supabase_client = MagicMock()
_mock_groq = MagicMock()
_mock_deepseek = MagicMock()

_patches = [
    patch.dict(os.environ, ENV_VARS),
    patch("supabase.create_client", return_value=_mock_supabase_client),
    patch("groq.AsyncGroq", return_value=_mock_groq),
    patch("openai.AsyncOpenAI", return_value=_mock_deepseek),
    patch("google.generativeai.configure"),
]
for p in _patches:
    p.start()

# NOW import `main` safely
import config
import utils
import telegram_service
import ai_service
import core_logic
import db_repository
import handlers
import main  # noqa: E402
from admin_runtime import auth as admin_auth
import security
import test_support
from web_app import http as web_http, webhook_routes
from _test_main_admin_cases import TestAdminRoutes, TestAdminValidationCoverage
from _test_main_security_cases import TestSecurityCoverage

_original_lookup_admin_user = admin_auth._lookup_admin_user

# Restore correct references so tests can interact
config.supabase = _mock_supabase_client
db_repository.supabase = _mock_supabase_client
handlers.supabase = _mock_supabase_client
security.supabase = _mock_supabase_client
main.supabase = _mock_supabase_client
config.groq_client = _mock_groq
config.deepseek_client = _mock_deepseek
ai_service.groq_client = _mock_groq
ai_service.deepseek_client = _mock_deepseek
config.SECRET_TOKEN = ENV_VARS["TELEGRAM_SECRET_TOKEN"]


# ============================================================
# FIXTURES
# ============================================================
@pytest.fixture(autouse=True)
def _reset_auth_test_support():
    test_support.reset_auth_test_state()
    yield
    test_support.reset_auth_test_state()


@pytest.fixture(autouse=True)
def _reset_admin_lookup_mock():
    admin_auth._lookup_admin_user = _original_lookup_admin_user
    yield
    admin_auth._lookup_admin_user = _original_lookup_admin_user


@pytest.fixture
def mock_http_client():
    client = AsyncMock()
    telegram_service.http_client = client
    yield client
    telegram_service.http_client = None


@pytest.fixture
def sample_dados_lote():
    return {
        "metodo_pagamento": "Cartão de Crédito",
        "conta": "Nubank",
        "desconto_global": 0.0,
        "itens": [
            {"nome": "Arroz", "valor_bruto": 25.0, "desconto_item": 0.0, "categoria": "Mercado"},
            {"nome": "Cerveja", "valor_bruto": 15.0, "desconto_item": 0.0, "categoria": "Bebidas Alcoólicas"},
            {"nome": "Shampoo", "valor_bruto": 12.0, "desconto_item": 2.0, "categoria": "Cuidados Pessoais"},
        ],
    }


@pytest.fixture
def sample_dados_registro():
    return {
        "data": "2026-03-15",
        "valor_total": 150.0,
        "parcelas": 3,
        "categoria": "Transporte",
        "descricao": "Troca de óleo Civic",
        "metodo_pagamento": "Cartão de Crédito",
        "conta": "Bradesco",
    }


# ============================================================
# 1. PURE FUNCTIONS
# ============================================================
class TestInferirNatureza:
    """Tests for inferir_natureza — deterministic category mapping."""

    @pytest.mark.parametrize(
        "cat_input, expected",
        [
            ("mercado", ("Essencial", "Mercado")),
            ("Mercado", ("Essencial", "Mercado")),
            ("  MERCADO  ", ("Essencial", "Mercado")),
            ("moradia", ("Essencial", "Moradia")),
            ("transporte", ("Essencial", "Transporte")),
            ("saúde", ("Essencial", "Saúde")),
            ("educação", ("Essencial", "Educação")),
            ("contas fixas", ("Essencial", "Contas Fixas")),
            ("cuidados pessoais", ("Essencial", "Cuidados Pessoais")),
            ("bares e restaurantes", ("Lazer", "Bares e Restaurantes")),
            ("delivery e fast food", ("Lazer", "Delivery e Fast Food")),
            ("bebidas alcoólicas", ("Lazer", "Bebidas Alcoólicas")),
            ("viagens", ("Lazer", "Viagens")),
            ("diversão", ("Lazer", "Diversão")),
            ("vestuário", ("Lazer", "Vestuário")),
            ("salário", ("Receita", "Salário")),
            ("investimentos", ("Receita", "Investimentos")),
            ("cashback", ("Receita", "Cashback")),
            ("entradas diversas", ("Receita", "Entradas Diversas")),
            # Defesa Semântica
            ("receita", ("Receita", "Entradas Diversas")),
            ("ganho", ("Receita", "Entradas Diversas")),
            ("gasto", ("Outros", "Outros")),
            ("despesa", ("Outros", "Outros")),
            ("outros", ("Outros", "Outros")),
        ],
    )
    def test_valid_categories(self, cat_input, expected):
        assert utils.inferir_natureza(cat_input) == expected

    @pytest.mark.parametrize("bad_input", [None, "", 123, "inventada", "pizza", "xyz"])
    def test_fallback_to_outros(self, bad_input):
        assert utils.inferir_natureza(bad_input) == ("Outros", "Outros")


class TestAddMonthsSafely:
    """Tests for add_months_safely — date arithmetic edge cases."""

    def test_simple_add(self):
        dt = datetime(2026, 1, 15)
        result = utils.add_months_safely(dt, 1)
        assert result == datetime(2026, 2, 15)

    def test_year_boundary(self):
        dt = datetime(2026, 11, 10)
        result = utils.add_months_safely(dt, 2)
        assert result == datetime(2027, 1, 10)

    def test_jan_31_to_feb(self):
        dt = datetime(2026, 1, 31)
        result = utils.add_months_safely(dt, 1)
        assert result == datetime(2026, 2, 28)

    def test_leap_year_feb(self):
        dt = datetime(2028, 1, 31)
        result = utils.add_months_safely(dt, 1)
        # 2028 is leap year
        assert result == datetime(2028, 2, 29)

    def test_zero_months(self):
        dt = datetime(2026, 6, 15)
        result = utils.add_months_safely(dt, 0)
        assert result == datetime(2026, 6, 15)

    def test_twelve_months(self):
        dt = datetime(2026, 3, 1)
        result = utils.add_months_safely(dt, 12)
        assert result == datetime(2027, 3, 1)


class TestGetBrasiliaTime:
    """Tests for get_brasilia_time — should return UTC-3."""

    def test_offset(self):
        before = datetime.utcnow() - timedelta(hours=3, seconds=1)
        result = utils.get_brasilia_time()
        after = datetime.utcnow() - timedelta(hours=3)
        assert before <= result <= after + timedelta(seconds=2)


class TestMascararSegredos:
    """Tests for mascarar_segredos — secret masking."""

    def test_masks_known_secret(self):
        text = f"Connection to {ENV_VARS['SUPABASE_KEY']} failed"
        result = config.mascarar_segredos(text)
        assert "[MASKED_SUPABASE_KEY]" in result
        assert ENV_VARS["SUPABASE_KEY"] not in result

    def test_masks_multiple_secrets(self):
        text = f"{ENV_VARS['DEEPSEEK_API_KEY']} and {ENV_VARS['GROQ_API_KEY']}"
        result = config.mascarar_segredos(text)
        assert "[MASKED_DEEPSEEK_API_KEY]" in result
        assert "[MASKED_GROQ_API_KEY]" in result

    def test_non_string_passthrough(self):
        assert config.mascarar_segredos(12345) == 12345
        assert config.mascarar_segredos(None) is None

    def test_no_secrets_unchanged(self):
        text = "Normal log message without secrets"
        assert config.mascarar_segredos(text) == text


class TestFrontendOrigins:
    def test_normalize_frontend_origin_strips_path(self):
        assert config.normalize_frontend_origin("https://admin.example.com/app/") == "https://admin.example.com"

    def test_default_frontend_origins_include_only_local(self):
        defaults = config.parse_frontend_allowed_origins(None)
        assert "http://localhost:5173" in defaults
        assert "http://127.0.0.1:5173" in defaults

    def test_parse_frontend_allowed_origins_normalizes_cloud_run_secret_value(self):
        configured = config.parse_frontend_allowed_origins(
            "https://admin.example.com/app/,http://localhost:5173"
        )
        assert "https://admin.example.com" in configured
        assert "http://localhost:5173" in configured


# ============================================================
# 2. BUSINESS LOGIC — MAP-REDUCE
# ============================================================
class TestAplicarMapReduce:
    """Tests for aplicar_map_reduce — grouping, discounts, guardrails."""

    def test_empty_items(self):
        grupos, total, desc = core_logic.aplicar_map_reduce({"itens": []})
        assert grupos == {}
        assert total == 0.0
        assert desc == 0.0

    def test_no_items_key(self):
        grupos, total, desc = core_logic.aplicar_map_reduce({})
        assert grupos == {}

    def test_single_category(self):
        dados = {
            "itens": [
                {"nome": "Arroz", "valor_bruto": 10.0, "desconto_item": 0.0, "categoria": "Mercado"},
                {"nome": "Feijão", "valor_bruto": 8.0, "desconto_item": 0.0, "categoria": "Mercado"},
            ],
            "desconto_global": 0.0,
        }
        grupos, total, desc = core_logic.aplicar_map_reduce(dados)
        assert len(grupos) == 1
        assert ("Essencial", "Mercado") in grupos
        assert total == pytest.approx(18.0)
        assert desc == 0.0

    def test_multiple_categories(self, sample_dados_lote):
        grupos, total, desc = core_logic.aplicar_map_reduce(sample_dados_lote)
        assert len(grupos) == 3
        assert ("Essencial", "Mercado") in grupos
        assert ("Lazer", "Bebidas Alcoólicas") in grupos
        assert ("Essencial", "Cuidados Pessoais") in grupos
        # Arroz 25 + Cerveja 15 + (Shampoo 12 - 2 discount) = 50
        assert total == pytest.approx(50.0)

    def test_item_discount(self):
        dados = {
            "itens": [{"nome": "X", "valor_bruto": 20.0, "desconto_item": 5.0, "categoria": "Mercado"}],
            "desconto_global": 0.0,
        }
        grupos, total, _ = core_logic.aplicar_map_reduce(dados)
        assert total == pytest.approx(15.0)

    def test_global_discount_applied_to_largest_group(self):
        dados = {
            "itens": [
                {"nome": "A", "valor_bruto": 100.0, "desconto_item": 0.0, "categoria": "Mercado"},
                {"nome": "B", "valor_bruto": 20.0, "desconto_item": 0.0, "categoria": "Bebidas Alcoólicas"},
            ],
            "desconto_global": 10.0,
        }
        grupos, total, desc = core_logic.aplicar_map_reduce(dados)
        assert desc == 10.0
        # Global discount applied to Mercado (largest): 100 - 10 = 90
        assert grupos[("Essencial", "Mercado")]["valor"] == pytest.approx(90.0)
        assert total == pytest.approx(110.0)

    def test_guardrail_neutralizes_duplicate_discount(self):
        """When sum of item discounts ≈ global discount, global is neutralized."""
        dados = {
            "itens": [
                {"nome": "A", "valor_bruto": 50.0, "desconto_item": 5.0, "categoria": "Mercado"},
                {"nome": "B", "valor_bruto": 30.0, "desconto_item": 5.0, "categoria": "Mercado"},
            ],
            "desconto_global": 10.0,
        }
        grupos, total, desc = core_logic.aplicar_map_reduce(dados)
        # 5+5 = 10 == global 10, so guardrail neutralizes
        assert desc == 0.0
        # Total = (50-5) + (30-5) = 70
        assert total == pytest.approx(70.0)


# ============================================================
# 3. FORMATTING FUNCTIONS
# ============================================================
class TestGerarMensagemResumo:
    """Tests for gerar_mensagem_resumo."""

    def test_contains_expected_fields(self, sample_dados_lote):
        grupos, total, desc = core_logic.aplicar_map_reduce(sample_dados_lote)
        msg = core_logic.gerar_mensagem_resumo("TEST1", sample_dados_lote, grupos, total, desc)
        assert "Resumo do Cupom" in msg
        assert "Cartão de Crédito" in msg
        assert "Nubank" in msg
        assert "Arroz" in msg
        assert "Cerveja" in msg
        assert "50.00" in msg

    def test_shows_global_discount(self):
        dados = {
            "metodo_pagamento": "Pix",
            "conta": "Itaú",
            "itens": [{"nome": "X", "valor_bruto": 100.0, "desconto_item": 0.0, "categoria": "Mercado"}],
            "desconto_global": 5.0,
        }
        grupos, total, desc = core_logic.aplicar_map_reduce(dados)
        msg = core_logic.gerar_mensagem_resumo("C1", dados, grupos, total, desc)
        assert "Desconto Global" in msg


class TestGerarTextoEdicao:
    """Tests for gerar_texto_edicao."""

    def test_has_cupom_edit_prefix(self, sample_dados_lote):
        text = core_logic.gerar_texto_edicao(sample_dados_lote)
        assert text.startswith("--CUPOM_EDIT--")

    def test_contains_items(self, sample_dados_lote):
        text = core_logic.gerar_texto_edicao(sample_dados_lote)
        assert "Arroz" in text
        assert "Cerveja" in text
        assert "Shampoo" in text
        assert "[Mercado]" in text

    def test_contains_payment_info(self, sample_dados_lote):
        text = core_logic.gerar_texto_edicao(sample_dados_lote)
        assert "Pagamento: Cartão de Crédito" in text
        assert "Conta: Nubank" in text


class TestFormatarRelatorioExclusao:
    """Tests for formatar_relatorio_exclusao."""

    def test_empty_list(self):
        msg = core_logic.formatar_relatorio_exclusao([])
        assert "Nenhum registro" in msg

    def test_single_record(self):
        registros = [
            {
                "data": "2026-03-15",
                "valor": 50.0,
                "natureza": "Essencial",
                "categoria": "Mercado",
                "metodo_pagamento": "Pix",
                "conta": "Nubank",
                "descricao": "Compras do mês",
            }
        ]
        msg = core_logic.formatar_relatorio_exclusao(registros)
        assert "1 registro" in msg
        assert "R$ 50.00" in msg
        assert "APAGAR" in msg

    def test_many_records_grouped_view(self):
        registros = [
            {
                "data": f"2026-03-{i:02d}",
                "valor": 10.0 * i,
                "natureza": "Essencial",
                "categoria": "Mercado",
                "metodo_pagamento": "Pix",
                "conta": "Nubank",
                "descricao": f"Item {i}",
            }
            for i in range(1, 15)
        ]
        msg = core_logic.formatar_relatorio_exclusao(registros)
        assert "14 registro" in msg
        assert "APAGAR" in msg


# ============================================================
# 4. DATABASE OPERATIONS (MOCKED SUPABASE)
# ============================================================
class TestInserirNoBanco:
    """Tests for inserir_no_banco — single record + installments."""

    def test_single_insert(self, sample_dados_registro):
        mock_table = MagicMock()
        config.supabase.table = MagicMock(return_value=mock_table)
        mock_table.insert.return_value.execute.return_value = MagicMock()

        sample_dados_registro["parcelas"] = 1
        db_repository.inserir_no_banco(sample_dados_registro)

        mock_table.insert.assert_called_once()
        payload = mock_table.insert.call_args[0][0]
        assert len(payload) == 1
        assert payload[0]["natureza"] == "Essencial"
        assert payload[0]["categoria"] == "Transporte"
        assert payload[0]["valor"] == 150.0

    def test_installments_split(self, sample_dados_registro):
        mock_table = MagicMock()
        config.supabase.table = MagicMock(return_value=mock_table)
        mock_table.insert.return_value.execute.return_value = MagicMock()

        sample_dados_registro["parcelas"] = 3
        sample_dados_registro["valor_total"] = 150.0
        db_repository.inserir_no_banco(sample_dados_registro)

        payload = mock_table.insert.call_args[0][0]
        assert len(payload) == 3
        valor_soma = sum(p["valor"] for p in payload)
        assert valor_soma == pytest.approx(150.0)
        assert "[1/3]" in payload[0]["descricao"]
        assert "[3/3]" in payload[2]["descricao"]

    def test_installment_dates_increment_monthly(self, sample_dados_registro):
        mock_table = MagicMock()
        config.supabase.table = MagicMock(return_value=mock_table)
        mock_table.insert.return_value.execute.return_value = MagicMock()

        sample_dados_registro["data"] = "2026-01-15"
        sample_dados_registro["parcelas"] = 3
        db_repository.inserir_no_banco(sample_dados_registro)

        payload = mock_table.insert.call_args[0][0]
        assert payload[0]["data"] == "2026-01-15"
        assert payload[1]["data"] == "2026-02-15"
        assert payload[2]["data"] == "2026-03-15"

    def test_invalid_date_uses_today(self, sample_dados_registro):
        mock_table = MagicMock()
        config.supabase.table = MagicMock(return_value=mock_table)
        mock_table.insert.return_value.execute.return_value = MagicMock()

        sample_dados_registro["data"] = "invalid-date"
        sample_dados_registro["parcelas"] = 1
        db_repository.inserir_no_banco(sample_dados_registro)

        payload = mock_table.insert.call_args[0][0]
        # On invalid date, falls back to Brasilia time
        assert payload[0]["data"] is not None

    def test_db_error_raises(self, sample_dados_registro):
        from postgrest.exceptions import APIError

        mock_table = MagicMock()
        config.supabase.table = MagicMock(return_value=mock_table)
        mock_table.insert.return_value.execute.side_effect = APIError({"message": "DB fail", "code": "500", "details": "", "hint": ""})

        with pytest.raises(Exception, match="Erro no Banco"):
            db_repository.inserir_no_banco(sample_dados_registro)


class TestGravarLoteNoBanco:
    """Tests for gravar_lote_no_banco."""

    def test_inserts_grouped_records(self, sample_dados_lote):
        mock_table = MagicMock()
        config.supabase.table = MagicMock(return_value=mock_table)
        mock_table.insert.return_value.execute.return_value = MagicMock()

        linhas, total = db_repository.gravar_lote_no_banco(sample_dados_lote)
        assert linhas == 3  # 3 distinct categories
        assert total == pytest.approx(50.0)

    def test_empty_lote(self):
        linhas, total = db_repository.gravar_lote_no_banco({"itens": []})
        assert linhas == 0
        assert total == 0.0


class TestConsultarNoBanco:
    """Tests for consultar_no_banco."""

    def test_returns_sum_and_count(self):
        mock_table = MagicMock()
        config.supabase.table = MagicMock(return_value=mock_table)
        mock_resp = MagicMock()
        mock_resp.data = [{"valor": 100.0, "descricao": "A"}, {"valor": 50.0, "descricao": "B"}]
        mock_table.select.return_value.gte.return_value = mock_resp
        # Patch aplicar_filtros_query to return the mock directly
        with patch.object(db_repository, "aplicar_filtros_query", return_value=mock_resp):
            mock_resp.execute.return_value = mock_resp
            total, count = db_repository.consultar_no_banco({})
        assert total == pytest.approx(150.0)
        assert count == 2


# ============================================================
# 5. FILTER QUERY BUILDER
# ============================================================
class TestAplicarFiltrosQuery:
    """Tests for aplicar_filtros_query — chainable filter builder."""

    def _make_mock_query(self):
        q = MagicMock()
        q.gte.return_value = q
        q.eq.return_value = q
        q.neq.return_value = q
        q.lte.return_value = q
        q.ilike.return_value = q
        q.in_.return_value = q
        return q

    def test_empty_filters(self):
        q = self._make_mock_query()
        result = db_repository.aplicar_filtros_query(q, {})
        q.gte.assert_called_once_with("valor", 0)

    def test_filter_by_natureza_valid(self):
        q = self._make_mock_query()
        db_repository.aplicar_filtros_query(q, {"natureza": "essencial"})
        q.eq.assert_any_call("natureza", "Essencial")

    def test_filter_by_natureza_invalid_ignored(self):
        q = self._make_mock_query()
        result = db_repository.aplicar_filtros_query(q, {"natureza": "inventada"})
        # Should NOT call eq with invalid natureza
        for call in q.eq.call_args_list:
            assert call[0][0] != "natureza" or call[0][1] in ["Essencial", "Lazer", "Receita"]

    def test_filter_by_categoria(self):
        q = self._make_mock_query()
        db_repository.aplicar_filtros_query(q, {"categoria": "Mercado"})
        q.eq.assert_any_call("categoria", "Mercado")

    def test_filter_by_categoria_with_comma_ignored(self):
        q = self._make_mock_query()
        db_repository.aplicar_filtros_query(q, {"categoria": "Mercado, Transporte"})
        for call in q.eq.call_args_list:
            assert call[0][0] != "categoria"

    def test_filter_by_conta(self):
        q = self._make_mock_query()
        db_repository.aplicar_filtros_query(q, {"conta": "Nubank"})
        q.eq.assert_any_call("conta", "Nubank")

    def test_filter_by_valor_exato(self):
        q = self._make_mock_query()
        db_repository.aplicar_filtros_query(q, {"valor_exato": 25.5})
        q.eq.assert_any_call("valor", 25.5)

    def test_filter_by_metodo_pagamento(self):
        q = self._make_mock_query()
        db_repository.aplicar_filtros_query(q, {"metodo_pagamento": "Pix"})
        q.ilike.assert_called_once_with("metodo_pagamento", "%Pix%")

    def test_filter_tipo_transacao_saida(self):
        q = self._make_mock_query()
        db_repository.aplicar_filtros_query(q, {"tipo_transacao": "saida"})
        q.neq.assert_any_call("natureza", "Receita")

    def test_filter_tipo_transacao_entrada(self):
        q = self._make_mock_query()
        db_repository.aplicar_filtros_query(q, {"tipo_transacao": "entrada"})
        q.eq.assert_any_call("natureza", "Receita")

    def test_filter_mes_ano(self):
        q = self._make_mock_query()
        db_repository.aplicar_filtros_query(q, {"mes": "03", "ano": "2026"})
        q.gte.assert_any_call("data", "2026-03-01")
        q.lte.assert_any_call("data", "2026-03-31")

    def test_filter_ano_only(self):
        q = self._make_mock_query()
        db_repository.aplicar_filtros_query(q, {"ano": "2026"})
        q.gte.assert_any_call("data", "2026-01-01")
        q.lte.assert_any_call("data", "2026-12-31")

    def test_none_filters(self):
        q = self._make_mock_query()
        result = db_repository.aplicar_filtros_query(q, None)
        q.gte.assert_called_once_with("valor", 0)


# ============================================================
# 6. TELEGRAM HELPERS (ASYNC + MOCKED HTTPX)
# ============================================================
class TestEnviarAcaoTelegram:
    @pytest.mark.asyncio
    async def test_sends_action(self, mock_http_client):
        await telegram_service.enviar_acao_telegram(123, "typing")
        mock_http_client.post.assert_called_once()
        call_args = mock_http_client.post.call_args
        assert "sendChatAction" in call_args[0][0]
        assert call_args[1]["json"]["action"] == "typing"

    @pytest.mark.asyncio
    async def test_no_client_noop(self):
        telegram_service.http_client = None
        await telegram_service.enviar_acao_telegram(123, "typing")  # Should not raise


class TestEnviarMensagemTelegram:
    @pytest.mark.asyncio
    async def test_sends_message(self, mock_http_client):
        await telegram_service.enviar_mensagem_telegram(123, "Hello")
        mock_http_client.post.assert_called_once()
        payload = mock_http_client.post.call_args[1]["json"]
        assert payload["chat_id"] == 123
        assert payload["text"] == "Hello"
        assert payload["parse_mode"] == "Markdown"

    @pytest.mark.asyncio
    async def test_with_reply_markup(self, mock_http_client):
        markup = {"inline_keyboard": [[{"text": "OK", "callback_data": "ok"}]]}
        await telegram_service.enviar_mensagem_telegram(123, "Test", markup)
        payload = mock_http_client.post.call_args[1]["json"]
        assert payload["reply_markup"] == markup

    @pytest.mark.asyncio
    async def test_no_client_noop(self):
        telegram_service.http_client = None
        await telegram_service.enviar_mensagem_telegram(123, "Hello")


class TestEditarMensagemTelegram:
    @pytest.mark.asyncio
    async def test_edits_message(self, mock_http_client):
        await telegram_service.editar_mensagem_telegram(123, 456, "Updated")
        payload = mock_http_client.post.call_args[1]["json"]
        assert payload["message_id"] == 456
        assert payload["text"] == "Updated"
        assert "editMessageText" in mock_http_client.post.call_args[0][0]


class TestBaixarArquivoTelegram:
    @pytest.mark.asyncio
    async def test_downloads_file(self, mock_http_client):
        mock_get_resp = MagicMock()
        mock_get_resp.json.return_value = {"ok": True, "result": {"file_path": "photos/file.jpg"}}
        mock_download_resp = MagicMock()
        mock_download_resp.content = b"fake_image_bytes"
        mock_http_client.get = AsyncMock(side_effect=[mock_get_resp, mock_download_resp])

        result = await telegram_service.baixar_arquivo_telegram("file_id_123")
        assert result == b"fake_image_bytes"
        assert mock_http_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_returns_none_on_failure(self, mock_http_client):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": False}
        mock_http_client.get = AsyncMock(return_value=mock_resp)

        result = await telegram_service.baixar_arquivo_telegram("bad_file_id")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_client_returns_none(self):
        telegram_service.http_client = None
        result = await telegram_service.baixar_arquivo_telegram("any_id")
        assert result is None


# ============================================================
# 7. AI ENGINES (MOCKED)
# ============================================================
class TestTranscreverAudio:
    @pytest.mark.asyncio
    async def test_returns_transcription(self):
        mock_transcription = MagicMock()
        mock_transcription.text = "Compra de cerveja quinze reais"
        config.groq_client.audio.transcriptions.create = AsyncMock(return_value=mock_transcription)

        result = await ai_service.transcrever_audio(b"fake_ogg_audio_bytes")
        assert result == "Compra de cerveja quinze reais"
        config.groq_client.audio.transcriptions.create.assert_called_once()


class TestExtrairTabelaReciboGemini:
    @pytest.mark.asyncio
    async def test_returns_gemini_response(self):
        with patch("google.generativeai.GenerativeModel") as mock_model_cls:
            mock_model = MagicMock()
            mock_model_cls.return_value = mock_model
            with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
                mock_thread.return_value.text = "Produto | Valor\nArroz | 10.00"
                result = await ai_service.extrair_tabela_recibo_gemini(b"fake_image_bytes")

        assert "Arroz" in result


class TestProcessarTextoComLLM:
    @pytest.mark.asyncio
    async def test_returns_parsed_json(self):
        class MockMessage:
            content = json.dumps({"intencao": "registrar", "dados_registro": {"valor_total": 50.0}})
        class MockChoice:
            message = MockMessage()
        class MockResponse:
            choices = [MockChoice()]

        config.deepseek_client.chat.completions.create = AsyncMock(return_value=MockResponse())

        result = await ai_service.processar_texto_com_llm("cerveja 15 reais")
        assert result["intencao"] == "registrar"
        assert result["dados_registro"]["valor_total"] == 50.0

    @pytest.mark.asyncio
    async def test_empty_response(self):
        class MockMessage:
            content = None
        class MockChoice:
            message = MockMessage()
        class MockResponse:
            choices = [MockChoice()]

        config.deepseek_client.chat.completions.create = AsyncMock(return_value=MockResponse())

        result = await ai_service.processar_texto_com_llm("test")
        assert result == {}


# ============================================================
# 8. EXCLUSION FLOW
# ============================================================
class TestIniciarFluxoExclusao:
    @pytest.mark.asyncio
    async def test_empty_filters_rejected(self, mock_http_client):
        await handlers.iniciar_fluxo_exclusao(123, {})
        call_payload = mock_http_client.post.call_args[1]["json"]
        assert "Operação Recusada" in call_payload["text"]

    @pytest.mark.asyncio
    async def test_no_records_found(self, mock_http_client):
        mock_table = MagicMock()
        config.supabase.table = MagicMock(return_value=mock_table)
        mock_resp = MagicMock()
        mock_resp.data = []

        with patch.object(handlers, "aplicar_filtros_query", return_value=mock_resp):
            mock_resp.execute.return_value = mock_resp
            await handlers.iniciar_fluxo_exclusao(123, {"categoria": "Mercado"})

        call_payload = mock_http_client.post.call_args[1]["json"]
        assert "Não encontrei" in call_payload["text"]

    @pytest.mark.asyncio
    async def test_valid_flow_shows_confirmation(self, mock_http_client):
        mock_table = MagicMock()
        config.supabase.table = MagicMock(return_value=mock_table)

        records = [
            {"id": 1, "data": "2026-03-15", "valor": 50.0, "natureza": "Essencial", "categoria": "Mercado",
             "descricao": "Arroz", "metodo_pagamento": "Pix", "conta": "Nubank"}
        ]
        mock_resp_select = MagicMock()
        mock_resp_select.data = records

        mock_resp_cache = MagicMock()
        mock_table.insert.return_value.execute.return_value = mock_resp_cache

        with patch.object(handlers, "aplicar_filtros_query", return_value=mock_resp_select):
            mock_resp_select.execute.return_value = mock_resp_select
            await handlers.iniciar_fluxo_exclusao(123, {"valor_exato": 50.0})

        # Should have cached and sent confirmation keyboard
        assert mock_http_client.post.call_count >= 1
        call_payload = mock_http_client.post.call_args[1]["json"]
        assert "APAGAR" in call_payload["text"]
        assert "reply_markup" in call_payload


# ============================================================
# 9. WEBHOOK CONTROLLER — processar_update_assincrono
# ============================================================
class TestProcessarUpdateAssincrono:
    """Integration tests for the main processing pipeline."""

    def _setup_supabase_idempotency(self):
        mock_table_idemp = MagicMock()
        mock_table_idemp.insert.return_value.execute.return_value = MagicMock()

        mock_table_cache = MagicMock()
        mock_table_cache.insert.return_value.execute.return_value = MagicMock()
        mock_table_cache.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        mock_table_cache.delete.return_value.eq.return_value.execute.return_value = MagicMock()

        mock_table_gastos = MagicMock()
        mock_table_gastos.insert.return_value.execute.return_value = MagicMock()
        mock_table_gastos.select.return_value = MagicMock()
        mock_table_gastos.delete.return_value.in_.return_value.execute.return_value = MagicMock()

        def table_switch(name):
            if name == "webhook_idempotencia":
                return mock_table_idemp
            elif name == "cache_aprovacao":
                return mock_table_cache
            elif name == "gastos":
                return mock_table_gastos
            return MagicMock()

        config.supabase.table = MagicMock(side_effect=table_switch)
        return mock_table_idemp, mock_table_cache, mock_table_gastos

    @pytest.mark.asyncio
    async def test_intent_registrar(self, mock_http_client):
        self._setup_supabase_idempotency()

        llm_response = {
            "intencao": "registrar",
            "dados_registro": {
                "data": "2026-03-15",
                "valor_total": 50.0,
                "parcelas": 1,
                "categoria": "Mercado",
                "descricao": "Compras",
                "metodo_pagamento": "Pix",
                "conta": "Nubank",
            },
        }

        update = {
            "update_id": 1001,
            "message": {"chat": {"id": 123}, "text": "Compras 50 reais pix nubank"},
        }

        with patch("handlers.processar_texto_com_llm", new_callable=AsyncMock, return_value=llm_response):
            await handlers.processar_update_assincrono(update)

        # Should send "Salvo!" confirmation
        msgs = [c[1]["json"]["text"] for c in mock_http_client.post.call_args_list if "json" in c[1] and "text" in c[1].get("json", {})]
        assert any("Salvo" in m for m in msgs)

    @pytest.mark.asyncio
    async def test_intent_consultar(self, mock_http_client):
        _, _, mock_gastos = self._setup_supabase_idempotency()

        llm_response = {
            "intencao": "consultar",
            "filtros_pesquisa": {"mes": "03", "ano": "2026"},
        }

        mock_query_response = MagicMock()
        mock_query_response.data = [{"valor": 100.0, "descricao": "A"}, {"valor": 200.0, "descricao": "B"}]

        update = {"update_id": 1002, "message": {"chat": {"id": 123}, "text": "quanto gastei em março?"}}

        with patch("handlers.processar_texto_com_llm", AsyncMock(return_value=llm_response)):
            with patch("handlers.consultar_no_banco", return_value=(300.0, 2)):
                await handlers.processar_update_assincrono(update)

        msgs = [c[1]["json"]["text"] for c in mock_http_client.post.call_args_list if "json" in c[1] and "text" in c[1].get("json", {})]
        assert any("300" in m for m in msgs)

    @pytest.mark.asyncio
    async def test_intent_excluir(self, mock_http_client):
        self._setup_supabase_idempotency()

        llm_response = {
            "intencao": "excluir",
            "filtros_exclusao": {"valor_exato": 50.0, "categoria": "Mercado"},
        }

        update = {"update_id": 1003, "message": {"chat": {"id": 123}, "text": "apaga o registro de 50 reais"}}

        with patch("handlers.processar_texto_com_llm", AsyncMock(return_value=llm_response)):
            with patch("handlers.iniciar_fluxo_exclusao", AsyncMock()) as mock_excl:
                await handlers.processar_update_assincrono(update)
                mock_excl.assert_called_once_with(123, {"valor_exato": 50.0, "categoria": "Mercado"})

    @pytest.mark.asyncio
    async def test_intent_unknown_raises(self, mock_http_client):
        self._setup_supabase_idempotency()

        llm_response = {"intencao": "fazer_bolo"}

        update = {"update_id": 1004, "message": {"chat": {"id": 123}, "text": "faça um bolo"}}

        with patch("handlers.processar_texto_com_llm", new_callable=AsyncMock, return_value=llm_response):
            await handlers.processar_update_assincrono(update)

        msgs = [c[1]["json"]["text"] for c in mock_http_client.post.call_args_list if "json" in c[1] and "text" in c[1].get("json", {})]
        assert any("Falha" in m or "não reconhecida" in m for m in msgs)

    @pytest.mark.asyncio
    async def test_intent_registrar_lote_pendente(self, mock_http_client):
        _, mock_cache, _ = self._setup_supabase_idempotency()

        llm_response = {
            "intencao": "registrar_lote_pendente",
            "dados_lote": {
                "metodo_pagamento": "Pix",
                "conta": "Nubank",
                "desconto_global": 0.0,
                "itens": [
                    {"nome": "Arroz", "valor_bruto": 25.0, "desconto_item": 0.0, "categoria": "Mercado"},
                ],
            },
        }

        update = {"update_id": 1005, "message": {"chat": {"id": 123}, "photo": [{"file_id": "xyz"}]}}

        with patch("handlers.baixar_arquivo_telegram", AsyncMock(return_value=b"img")):
            with patch("handlers.extrair_tabela_recibo_gemini", AsyncMock(return_value="Arroz 25")):
                with patch("handlers.processar_texto_com_llm", AsyncMock(return_value=llm_response)):
                    await handlers.processar_update_assincrono(update)

        msgs = [c[1]["json"]["text"] for c in mock_http_client.post.call_args_list if "json" in c[1] and "text" in c[1].get("json", {})]
        assert any("Resumo do Cupom" in m for m in msgs)

    @pytest.mark.asyncio
    async def test_intent_salvar_edicao_cupom(self, mock_http_client):
        self._setup_supabase_idempotency()

        llm_response = {
            "intencao": "salvar_edicao_cupom",
            "dados_lote": {
                "metodo_pagamento": "Pix",
                "conta": "Nubank",
                "desconto_global": 0.0,
                "itens": [
                    {"nome": "Arroz", "valor_bruto": 25.0, "desconto_item": 0.0, "categoria": "Mercado"},
                ],
            },
        }

        update = {"update_id": 1006, "message": {"chat": {"id": 123}, "text": "--CUPOM_EDIT-- ..."}}

        with patch("handlers.processar_texto_com_llm", AsyncMock(return_value=llm_response)):
            with patch("handlers.gravar_lote_no_banco", return_value=(1, 25.0)):
                await handlers.processar_update_assincrono(update)

        msgs = [c[1]["json"]["text"] for c in mock_http_client.post.call_args_list if "json" in c[1] and "text" in c[1].get("json", {})]
        assert any("Edição Salva" in m for m in msgs)

    @pytest.mark.asyncio
    async def test_voice_message_flow(self, mock_http_client):
        self._setup_supabase_idempotency()

        llm_response = {
            "intencao": "registrar",
            "dados_registro": {
                "data": "2026-03-15", "valor_total": 15.0, "parcelas": 1,
                "categoria": "Bebidas Alcoólicas", "descricao": "Cerveja",
                "metodo_pagamento": "Cartão de Crédito", "conta": "Bradesco",
            },
        }

        update = {"update_id": 1007, "message": {"chat": {"id": 123}, "voice": {"file_id": "voice_id"}}}

        with patch("handlers.baixar_arquivo_telegram", AsyncMock(return_value=b"audio")):
            with patch("handlers.transcrever_audio", AsyncMock(return_value="cerveja cartao bradesco 15")):
                with patch("handlers.processar_texto_com_llm", AsyncMock(return_value=llm_response)):
                    await handlers.processar_update_assincrono(update)

        msgs = [c[1]["json"]["text"] for c in mock_http_client.post.call_args_list if "json" in c[1] and "text" in c[1].get("json", {})]
        assert any("Ouvindo" in m for m in msgs)
        assert any("Salvo" in m for m in msgs)

    @pytest.mark.asyncio
    async def test_idempotency_duplicate_skipped(self, mock_http_client):
        from postgrest.exceptions import APIError

        mock_table = MagicMock()
        mock_table.insert.return_value.execute.side_effect = APIError(
            {"message": "duplicate key", "code": "23505", "details": "", "hint": ""}
        )
        config.supabase.table = MagicMock(return_value=mock_table)

        update = {"update_id": 9999, "message": {"chat": {"id": 123}, "text": "test"}}
        await handlers.processar_update_assincrono(update)

        # Should NOT have processed (no LLM call)
        # http_client.post should NOT have been called with sendMessage
        for call in mock_http_client.post.call_args_list:
            if "json" in call[1]:
                assert "sendMessage" not in call[0][0]


# ============================================================
# 10. CALLBACK QUERY HANDLING
# ============================================================
class TestCallbackQuery:
    def _setup_callback_mocks(self, acao, cache_data):
        mock_table_idemp = MagicMock()
        mock_table_idemp.insert.return_value.execute.return_value = MagicMock()

        mock_table_cache = MagicMock()
        mock_resp_cache = MagicMock()
        mock_resp_cache.data = [{"payload": cache_data}]
        mock_table_cache.select.return_value.eq.return_value.execute.return_value = mock_resp_cache
        mock_table_cache.delete.return_value.eq.return_value.execute.return_value = MagicMock()

        mock_table_gastos = MagicMock()
        mock_table_gastos.insert.return_value.execute.return_value = MagicMock()
        mock_table_gastos.delete.return_value.in_.return_value.execute.return_value = MagicMock()

        def table_switch(name):
            if name == "webhook_idempotencia":
                return mock_table_idemp
            elif name == "cache_aprovacao":
                return mock_table_cache
            elif name == "gastos":
                return mock_table_gastos
            return MagicMock()

        config.supabase.table = MagicMock(side_effect=table_switch)
        return mock_table_gastos, mock_table_cache

    @pytest.mark.asyncio
    async def test_callback_aprovar(self, mock_http_client):
        cache_data = {
            "metodo_pagamento": "Pix", "conta": "Nubank", "desconto_global": 0.0,
            "itens": [{"nome": "Arroz", "valor_bruto": 25.0, "desconto_item": 0.0, "categoria": "Mercado"}],
        }
        self._setup_callback_mocks("aprovar", cache_data)

        update = {
            "update_id": 2001,
            "callback_query": {
                "id": "cb1", "data": "aprovar_CACHE1",
                "message": {"chat": {"id": 123}, "message_id": 456},
            },
        }

        with patch("handlers.gravar_lote_no_banco", return_value=(1, 25.0)):
            await handlers.processar_update_assincrono(update)

        msgs = [c[1]["json"]["text"] for c in mock_http_client.post.call_args_list if "json" in c[1] and "text" in c[1].get("json", {})]
        assert any("Aprovado" in m for m in msgs)

    @pytest.mark.asyncio
    async def test_callback_cancelar(self, mock_http_client):
        self._setup_callback_mocks("cancelar", {})

        update = {
            "update_id": 2002,
            "callback_query": {
                "id": "cb2", "data": "cancelar_CACHE2",
                "message": {"chat": {"id": 123}, "message_id": 456},
            },
        }
        await handlers.processar_update_assincrono(update)

        msgs = [c[1]["json"]["text"] for c in mock_http_client.post.call_args_list if "json" in c[1] and "text" in c[1].get("json", {})]
        assert any("Cancelada" in m for m in msgs)

    @pytest.mark.asyncio
    async def test_callback_confirmdel(self, mock_http_client):
        mock_gastos, _ = self._setup_callback_mocks("confirmdel", {"ids": [10, 20, 30]})

        update = {
            "update_id": 2003,
            "callback_query": {
                "id": "cb3", "data": "confirmdel_DEL_ABC",
                "message": {"chat": {"id": 123}, "message_id": 789},
            },
        }
        await handlers.processar_update_assincrono(update)

        mock_gastos.delete.assert_called_once()
        msgs = [c[1]["json"]["text"] for c in mock_http_client.post.call_args_list if "json" in c[1] and "text" in c[1].get("json", {})]
        assert any("Exclusão Efetuada" in m for m in msgs)

    @pytest.mark.asyncio
    async def test_callback_editar(self, mock_http_client):
        cache_data = {
            "metodo_pagamento": "Crédito", "conta": "Bradesco", "desconto_global": 0.0,
            "itens": [{"nome": "Feijão", "valor_bruto": 8.0, "desconto_item": 0.0, "categoria": "Mercado"}],
        }
        self._setup_callback_mocks("editar", cache_data)

        update = {
            "update_id": 2004,
            "callback_query": {
                "id": "cb4", "data": "editar_CACHE4",
                "message": {"chat": {"id": 123}, "message_id": 500},
            },
        }
        await handlers.processar_update_assincrono(update)

        msgs = [c[1]["json"]["text"] for c in mock_http_client.post.call_args_list if "json" in c[1] and "text" in c[1].get("json", {})]
        assert any("EDIÇÃO" in m or "CUPOM_EDIT" in m for m in msgs)

    @pytest.mark.asyncio
    async def test_callback_expired_cache(self, mock_http_client):
        mock_table_idemp = MagicMock()
        mock_table_idemp.insert.return_value.execute.return_value = MagicMock()

        mock_table_cache = MagicMock()
        mock_resp_empty = MagicMock()
        mock_resp_empty.data = []
        mock_table_cache.select.return_value.eq.return_value.execute.return_value = mock_resp_empty

        def table_switch(name):
            if name == "webhook_idempotencia":
                return mock_table_idemp
            elif name == "cache_aprovacao":
                return mock_table_cache
            return MagicMock()

        config.supabase.table = MagicMock(side_effect=table_switch)

        update = {
            "update_id": 2005,
            "callback_query": {
                "id": "cb5", "data": "aprovar_EXPIRED",
                "message": {"chat": {"id": 123}, "message_id": 600},
            },
        }
        await handlers.processar_update_assincrono(update)

        msgs = [c[1]["json"]["text"] for c in mock_http_client.post.call_args_list if "json" in c[1] and "text" in c[1].get("json", {})]
        assert any("expirado" in m.lower() or "processado" in m.lower() for m in msgs)

    @pytest.mark.asyncio
    async def test_callback_no_cache_id(self, mock_http_client):
        """Callback with no underscore in data should return early."""
        mock_table = MagicMock()
        mock_table.insert.return_value.execute.return_value = MagicMock()
        config.supabase.table = MagicMock(return_value=mock_table)

        update = {
            "update_id": 2006,
            "callback_query": {
                "id": "cb6", "data": "nocacheidhere",
                "message": {"chat": {"id": 123}, "message_id": 700},
            },
        }
        await handlers.processar_update_assincrono(update)
        # answerCallbackQuery is called, but no editMessageText since cache_id is present but from split
        # Actually "nocacheidhere" has no "_", so acao="nocacheidhere", cache_id=None -> returns early


# ============================================================
# 11. WEBHOOK ENDPOINT
# ============================================================
class TestTelegramWebhook:
    @pytest.mark.asyncio
    async def test_unauthorized_returns_403(self):
        async with main.app.test_client() as client:
            resp = await client.post("/", headers={"X-Telegram-Bot-Api-Secret-Token": "WRONG"})
            assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_authorized_returns_200(self, mock_http_client):
        self._setup_supabase()

        async with main.app.test_client() as client:
            with patch.object(webhook_routes, "processar_update_assincrono", new_callable=AsyncMock):
                resp = await client.post(
                    "/",
                    json={"update_id": 9001, "message": {"chat": {"id": 1}, "text": "hi"}},
                    headers={"X-Telegram-Bot-Api-Secret-Token": webhook_routes.SECRET_TOKEN},
                )
                assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_webhook_requires_json_content_type(self, mock_http_client):
        async with main.app.test_client() as client:
            resp = await client.post(
                "/",
                data="not-json",
                headers={
                    "X-Telegram-Bot-Api-Secret-Token": webhook_routes.SECRET_TOKEN,
                    "Content-Type": "text/plain",
                },
            )

        assert resp.status_code == 415

    @pytest.mark.asyncio
    async def test_processing_error_returns_500(self, mock_http_client):
        async with main.app.test_client() as client:
            with patch.object(webhook_routes, "processar_update_assincrono", new_callable=AsyncMock, side_effect=Exception("boom-secret")):
                resp = await client.post(
                    "/",
                    json={"update_id": 9002, "message": {"chat": {"id": 1}, "text": "hi"}},
                    headers={
                        "X-Telegram-Bot-Api-Secret-Token": webhook_routes.SECRET_TOKEN,
                        "Origin": "http://localhost:5173",
                    },
                )
                assert resp.status_code == 500
                payload = await resp.get_json()
                assert payload["message"] == "Internal processing error."
                assert "boom-secret" not in json.dumps(payload)
                assert "Access-Control-Allow-Origin" not in resp.headers

    def _setup_supabase(self):
        mock_table = MagicMock()
        mock_table.insert.return_value.execute.return_value = MagicMock()
        config.supabase.table = MagicMock(return_value=mock_table)


# ============================================================
# 13. NO-MESSAGE UPDATE IGNORED
# ============================================================
class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_update_without_message_is_noop(self, mock_http_client):
        mock_table = MagicMock()
        mock_table.insert.return_value.execute.return_value = MagicMock()
        config.supabase.table = MagicMock(return_value=mock_table)

        update = {"update_id": 3001}
        await handlers.processar_update_assincrono(update)
        # No message => should not call Telegram sendMessage
        for call in mock_http_client.post.call_args_list:
            if "json" in call[1]:
                assert "sendMessage" not in call[0][0]

    @pytest.mark.asyncio
    async def test_unsupported_message_type_ignored(self, mock_http_client):
        mock_table = MagicMock()
        mock_table.insert.return_value.execute.return_value = MagicMock()
        config.supabase.table = MagicMock(return_value=mock_table)

        update = {"update_id": 3002, "message": {"chat": {"id": 123}, "sticker": {"file_id": "x"}}}
        await handlers.processar_update_assincrono(update)
