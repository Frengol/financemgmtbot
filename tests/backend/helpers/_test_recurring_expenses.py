import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from postgrest.exceptions import APIError

import main
import admin_runtime.recurring_expenses as recurring_module
from admin_runtime import auth as admin_auth
from admin_runtime import payloads as admin_payloads
from web_app import cron_routes


class TestRecurringExpensePayloadNormalization:
    @pytest.mark.asyncio
    async def test_payload_must_be_dict(self):
        async with main.app.test_request_context("/api/admin/despesas-recorrentes", method="POST"):
            payload, error = admin_payloads._normalize_recurring_expense_payload(None)
        assert payload is None
        assert error.status_code == 400
        error_json = await error.get_json()
        assert "Invalid recurring expense payload" in error_json["message"]

    @pytest.mark.asyncio
    async def test_rejects_extra_fields(self):
        async with main.app.test_request_context("/api/admin/despesas-recorrentes", method="POST"):
            payload, error = admin_payloads._normalize_recurring_expense_payload({
                "nome": "Netflix", "valor": 39.9, "mes_inicio": "2026-04-01",
                "dia_mes": 5, "categoria": "Diversão",
                "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
                "extra": True,
            })
        assert payload is None
        assert error.status_code == 400
        error_json = await error.get_json()
        assert "Unexpected recurring expense fields" in error_json["message"]

    @pytest.mark.asyncio
    async def test_rejects_descricao_in_payload(self):
        async with main.app.test_request_context("/api/admin/despesas-recorrentes", method="POST"):
            payload, error = admin_payloads._normalize_recurring_expense_payload({
                "nome": "Netflix", "valor": 39.9, "mes_inicio": "2026-04-01",
                "dia_mes": 5, "categoria": "Diversão",
                "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
                "descricao": "Netflix mensal",
            })
        assert payload is None
        assert error.status_code == 400
        error_json = await error.get_json()
        assert "Unexpected recurring expense fields" in error_json["message"]

    @pytest.mark.asyncio
    async def test_rejects_natureza_in_payload(self):
        async with main.app.test_request_context("/api/admin/despesas-recorrentes", method="POST"):
            payload, error = admin_payloads._normalize_recurring_expense_payload({
                "nome": "Netflix", "valor": 39.9, "mes_inicio": "2026-04-01",
                "dia_mes": 5, "natureza": "Lazer", "categoria": "Diversão",
                "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
            })
        assert payload is None
        assert error.status_code == 400
        error_json = await error.get_json()
        assert "Unexpected recurring expense fields" in error_json["message"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("missing_field", [
        "nome", "valor", "mes_inicio", "dia_mes", "categoria",
    ])
    async def test_rejects_missing_required_fields(self, missing_field):
        data = {
            "nome": "Netflix", "valor": 39.9, "mes_inicio": "2026-04-01",
            "dia_mes": 5, "categoria": "Diversão",
            "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
        }
        del data[missing_field]
        async with main.app.test_request_context("/api/admin/despesas-recorrentes", method="POST"):
            payload, error = admin_payloads._normalize_recurring_expense_payload(data)
        assert payload is None
        assert error.status_code == 400

    @pytest.mark.asyncio
    async def test_rejects_invalid_mes_inicio_format(self):
        async with main.app.test_request_context("/api/admin/despesas-recorrentes", method="POST"):
            payload, error = admin_payloads._normalize_recurring_expense_payload({
                "nome": "Netflix", "valor": 39.9, "mes_inicio": "04/01/2026",
                "dia_mes": 5, "categoria": "Diversão",
                "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
            })
        assert payload is None
        assert error.status_code == 400
        error_json = await error.get_json()
        assert "mes_inicio must be YYYY-MM" in error_json["message"]

    @pytest.mark.asyncio
    async def test_rejects_invalid_mes_fim_format(self):
        async with main.app.test_request_context("/api/admin/despesas-recorrentes", method="POST"):
            payload, error = admin_payloads._normalize_recurring_expense_payload({
                "nome": "Netflix", "valor": 39.9, "mes_inicio": "2026-04-01",
                "mes_fim": "invalid", "dia_mes": 5, "categoria": "Diversão",
                "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
            })
        assert payload is None
        assert error.status_code == 400
        error_json = await error.get_json()
        assert "mes_fim must be YYYY-MM" in error_json["message"]

    @pytest.mark.asyncio
    async def test_rejects_mes_fim_before_mes_inicio(self):
        async with main.app.test_request_context("/api/admin/despesas-recorrentes", method="POST"):
            payload, error = admin_payloads._normalize_recurring_expense_payload({
                "nome": "Netflix", "valor": 39.9, "mes_inicio": "2026-06-01",
                "mes_fim": "2026-04-01", "dia_mes": 5, "categoria": "Diversão",
                "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
            })
        assert payload is None
        assert error.status_code == 400
        error_json = await error.get_json()
        assert "mes_fim cannot be before mes_inicio" in error_json["message"]

    @pytest.mark.asyncio
    async def test_rejects_invalid_dia_mes(self):
        for dia in [0, -1, 32, "abc"]:
            async with main.app.test_request_context("/api/admin/despesas-recorrentes", method="POST"):
                payload, error = admin_payloads._normalize_recurring_expense_payload({
                    "nome": "Netflix", "valor": 39.9, "mes_inicio": "2026-04-01",
                    "dia_mes": dia, "categoria": "Diversão",
                    "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
                })
            assert payload is None, f"dia_mes={dia} should be rejected"
            assert error.status_code == 400

    @pytest.mark.asyncio
    async def test_rejects_negative_valor(self):
        async with main.app.test_request_context("/api/admin/despesas-recorrentes", method="POST"):
            payload, error = admin_payloads._normalize_recurring_expense_payload({
                "nome": "Netflix", "valor": -1, "mes_inicio": "2026-04-01",
                "dia_mes": 5, "categoria": "Diversão",
                "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
            })
        assert payload is None
        assert error.status_code == 400

    @pytest.mark.asyncio
    async def test_rejects_invalid_valor(self):
        async with main.app.test_request_context("/api/admin/despesas-recorrentes", method="POST"):
            payload, error = admin_payloads._normalize_recurring_expense_payload({
                "nome": "Netflix", "valor": "abc", "mes_inicio": "2026-04-01",
                "dia_mes": 5, "categoria": "Diversão",
                "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
            })
        assert payload is None
        assert error.status_code == 400

    @pytest.mark.asyncio
    async def test_rejects_invalid_categoria(self):
        async with main.app.test_request_context("/api/admin/despesas-recorrentes", method="POST"):
            payload, error = admin_payloads._normalize_recurring_expense_payload({
                "nome": "Netflix", "valor": 39.9, "mes_inicio": "2026-04-01",
                "dia_mes": 5, "categoria": "CategoriaInexistente",
                "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
            })
        assert payload is None
        assert error.status_code == 400
        error_json = await error.get_json()
        assert "category is invalid" in error_json["message"]

    @pytest.mark.asyncio
    async def test_accepts_mes_fim_none(self):
        async with main.app.test_request_context("/api/admin/despesas-recorrentes", method="POST"):
            payload, error = admin_payloads._normalize_recurring_expense_payload({
                "nome": "Netflix", "valor": 39.9, "mes_inicio": "2026-04-01",
                "mes_fim": None, "dia_mes": 5, "categoria": "Diversão",
                "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
            })
        assert error is None
        assert payload["mes_fim"] is None

    @pytest.mark.asyncio
    async def test_normalizes_natureza_from_categoria(self):
        async with main.app.test_request_context("/api/admin/despesas-recorrentes", method="POST"):
            payload, error = admin_payloads._normalize_recurring_expense_payload({
                "nome": "Netflix", "valor": 39.9, "mes_inicio": "2026-04-01",
                "dia_mes": 5, "categoria": "Mercado",
                "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
            })
        assert error is None
        assert payload["natureza"] == "Essencial"
        assert payload["categoria"] == "Mercado"

    @pytest.mark.asyncio
    async def test_normalizes_complete_payload(self):
        async with main.app.test_request_context("/api/admin/despesas-recorrentes", method="POST"):
            payload, error = admin_payloads._normalize_recurring_expense_payload({
                "nome": "Netflix", "valor": 39.9, "mes_inicio": "2026-04-01",
                "mes_fim": "2026-12-01", "dia_mes": 5,
                "categoria": "Diversão", "metodo_pagamento": "Cartao de Credito",
                "conta": "Nubank", "ativo": True,
            })
        assert error is None
        assert payload["nome"] == "Netflix"
        assert payload["valor"] == 39.9
        assert payload["mes_inicio"] == "2026-04-01"
        assert payload["mes_fim"] == "2026-12-01"
        assert payload["dia_mes"] == 5
        assert payload["natureza"] == "Lazer"
        assert payload["categoria"] == "Diversão"
        assert payload["metodo_pagamento"] == "Cartao de Credito"
        assert payload["conta"] == "Nubank"
        assert payload["ativo"] is True


class TestRecurringExpenseCrud:
    _actor = {"id": "u1", "email": "admin@example.com"}

    @pytest.mark.asyncio
    async def test_listar_requires_auth(self):
        async with main.app.test_request_context("/api/admin/despesas-recorrentes"):
            auth_error = recurring_module._json_error("denied", 403, code="AUTH_ACCESS_DENIED")
            with patch.object(recurring_module, "autenticar_admin_request", return_value=(None, auth_error)):
                response = recurring_module.listar_despesas_recorrentes()
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_listar_returns_items(self):
        mock_table = MagicMock()
        mock_table.select.return_value.order.return_value.execute.return_value = MagicMock(data=[
            {"id": "rec-1", "nome": "Netflix", "valor": 39.9, "dia_mes": 5},
        ])

        async with main.app.test_request_context("/api/admin/despesas-recorrentes"):
            with patch.object(recurring_module, "autenticar_admin_request", return_value=(self._actor, None)), \
                 patch.object(recurring_module, "supabase", MagicMock(table=MagicMock(return_value=mock_table))):
                response = recurring_module.listar_despesas_recorrentes()

        assert response.status_code == 200
        payload = await response.get_json()
        assert payload["items"][0]["nome"] == "Netflix"
        mock_table.select.assert_called_once_with(
            "id,nome,valor,mes_inicio,mes_fim,dia_mes,natureza,categoria,metodo_pagamento,conta,ativo,created_at,updated_at"
        )

    @pytest.mark.asyncio
    async def test_criar_requires_auth(self):
        async with main.app.test_request_context("/api/admin/despesas-recorrentes", method="POST"):
            auth_error = recurring_module._json_error("denied", 403, code="AUTH_ACCESS_DENIED")
            with patch.object(recurring_module, "autenticar_admin_request", return_value=(None, auth_error)):
                response = recurring_module.criar_despesa_recorrente({"nome": "Test"})
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_criar_with_valid_payload(self):
        mock_table = MagicMock()
        mock_table.insert.return_value.execute.return_value = MagicMock(data=[{
            "id": "rec-1", "nome": "Netflix", "valor": 39.9,
        }])

        async with main.app.test_request_context("/api/admin/despesas-recorrentes", method="POST"):
            with patch.object(recurring_module, "autenticar_admin_request", return_value=(self._actor, None)), \
                 patch.object(recurring_module, "supabase", MagicMock(table=MagicMock(return_value=mock_table))), \
                 patch.object(recurring_module, "_normalize_recurring_expense_payload", return_value=({"nome": "Netflix"}, None)), \
                 patch.object(recurring_module, "registrar_auditoria_admin") as registrar:
                response = recurring_module.criar_despesa_recorrente({"nome": "Netflix"})

        assert response.status_code == 201
        registrar.assert_called_once()

    @pytest.mark.asyncio
    async def test_atualizar_not_found(self):
        mock_table = MagicMock()
        mock_table.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        async with main.app.test_request_context("/api/admin/despesas-recorrentes/rec-1", method="PATCH"):
            with patch.object(recurring_module, "autenticar_admin_request", return_value=(self._actor, None)), \
                 patch.object(recurring_module, "supabase", MagicMock(table=MagicMock(return_value=mock_table))), \
                 patch.object(recurring_module, "_normalize_recurring_expense_payload", return_value=({"nome": "Updated"}, None)):
                response = recurring_module.atualizar_despesa_recorrente("rec-1", {"nome": "Updated"})

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_deletar_success(self):
        mock_table = MagicMock()
        mock_table.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[{"id": "rec-1"}])
        mock_table.delete.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        async with main.app.test_request_context("/api/admin/despesas-recorrentes/rec-1", method="DELETE"):
            with patch.object(recurring_module, "autenticar_admin_request", return_value=(self._actor, None)), \
                 patch.object(recurring_module, "supabase", MagicMock(table=MagicMock(return_value=mock_table))), \
                 patch.object(recurring_module, "registrar_auditoria_admin") as registrar:
                response = recurring_module.deletar_despesa_recorrente("rec-1")

        assert response.status_code == 200
        registrar.assert_called_once()


class TestRecurringExpenseGeneration:
    _actor = {"id": "u1", "email": "admin@example.com"}

    @pytest.mark.asyncio
    async def test_gerar_despesas_recorrentes_idempotente(self):
        mock_rec = MagicMock()
        mock_rec.select.return_value.eq.return_value.gte.return_value.lte.return_value.execute.return_value = MagicMock(data=[])

        mock_gastos = MagicMock()
        mock_gastos.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        mock_gastos.insert.return_value.execute.return_value = MagicMock(data=[{"id": "g-1"}])

        def table_switch(name):
            if name == "despesas_recorrentes":
                return mock_rec
            if name == "gastos":
                return mock_gastos
            return MagicMock()

        async with main.app.test_request_context("/api/cron/recurring-expenses", method="POST"):
            with patch.object(recurring_module, "supabase", MagicMock(table=MagicMock(side_effect=table_switch))), \
                 patch.object(recurring_module, "registrar_auditoria_admin"):
                response = recurring_module._executar_geracao_recorrente("2026-04-05", self._actor)

        assert response.status_code == 200
        payload = await response.get_json()
        assert payload["generated"] >= 0

    def test_compute_gasto_date_with_invalid_day_falls_back_to_last_day(self):
        date = recurring_module._compute_gasto_date(2026, 2, 31)
        assert date == "2026-02-28"

        date2 = recurring_module._compute_gasto_date(2024, 2, 31)
        assert date2 == "2024-02-29"

    def test_compute_gasto_date_normal_day(self):
        assert recurring_module._compute_gasto_date(2026, 4, 5) == "2026-04-05"

    def _build_supabase_mock(self, recurring_records, existing_gastos=None, transactions_table=None, insert_side_effect=None):
        mock_rec = MagicMock()
        mock_rec.select.return_value.eq.return_value.lte.return_value.execute.return_value = MagicMock(data=recurring_records)

        mock_gastos = MagicMock()
        mock_gastos.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=existing_gastos or [])
        if insert_side_effect is not None:
            mock_gastos.insert.return_value.execute.side_effect = insert_side_effect
        else:
            mock_gastos.insert.return_value.execute.return_value = MagicMock(data=[{"id": "g-1"}])

        transactions_table = transactions_table or recurring_module.TRANSACTIONS_TABLE

        def table_switch(name):
            if name == "despesas_recorrentes":
                return mock_rec
            if name == transactions_table:
                return mock_gastos
            return MagicMock()

        return MagicMock(table=MagicMock(side_effect=table_switch)), mock_gastos

    @pytest.mark.asyncio
    async def test_gerar_skips_when_dia_mes_does_not_match_reference_day(self):
        records = [{
            "id": "rec-1", "nome": "Netflix", "valor": 39.9, "dia_mes": 10,
            "mes_inicio": "2026-04-01", "mes_fim": None,
            "categoria": "Diversão", "natureza": "Lazer",
            "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
        }]
        supabase_mock, gastos_mock = self._build_supabase_mock(records)

        async with main.app.test_request_context("/api/cron/recurring-expenses", method="POST"):
            with patch.object(recurring_module, "supabase", supabase_mock), \
                 patch.object(recurring_module, "registrar_auditoria_admin"):
                response = recurring_module._executar_geracao_recorrente("2026-04-05", self._actor)

        assert response.status_code == 200
        payload = await response.get_json()
        assert payload["generated"] == 0
        gastos_mock.insert.assert_not_called()

    @pytest.mark.asyncio
    async def test_gerar_skips_expired_mes_fim(self):
        records = [{
            "id": "rec-1", "nome": "Old", "valor": 10.0, "dia_mes": 5,
            "mes_inicio": "2026-01-01", "mes_fim": "2026-03-01",
            "categoria": "Diversão", "natureza": "Lazer",
            "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
        }]
        supabase_mock, gastos_mock = self._build_supabase_mock(records)

        async with main.app.test_request_context("/api/cron/recurring-expenses", method="POST"):
            with patch.object(recurring_module, "supabase", supabase_mock), \
                 patch.object(recurring_module, "registrar_auditoria_admin"):
                response = recurring_module._executar_geracao_recorrente("2026-04-05", self._actor)

        assert response.status_code == 200
        payload = await response.get_json()
        assert payload["generated"] == 0
        gastos_mock.insert.assert_not_called()

    @pytest.mark.asyncio
    async def test_gerar_includes_record_when_mes_fim_equals_reference_month(self):
        records = [{
            "id": "rec-1", "nome": "Boundary", "valor": 12.0, "dia_mes": 5,
            "mes_inicio": "2026-01-01", "mes_fim": "2026-04-01",
            "categoria": "Diversão", "natureza": "Lazer",
            "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
        }]
        supabase_mock, gastos_mock = self._build_supabase_mock(records)

        async with main.app.test_request_context("/api/cron/recurring-expenses", method="POST"):
            with patch.object(recurring_module, "supabase", supabase_mock), \
                 patch.object(recurring_module, "registrar_auditoria_admin"):
                response = recurring_module._executar_geracao_recorrente("2026-04-05", self._actor)

        assert response.status_code == 200
        payload = await response.get_json()
        assert payload["generated"] == 1
        gastos_mock.insert.assert_called_once()

    @pytest.mark.asyncio
    async def test_gerar_skips_existing_gasto_for_idempotency(self):
        records = [{
            "id": "rec-1", "nome": "Netflix", "valor": 39.9, "dia_mes": 5,
            "mes_inicio": "2026-04-01", "mes_fim": None,
            "categoria": "Diversão", "natureza": "Lazer",
            "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
        }]
        duplicate_error = APIError({
            "code": "23505",
            "message": "duplicate key value violates unique constraint",
            "details": "Key already exists.",
            "hint": "",
        })
        supabase_mock, gastos_mock = self._build_supabase_mock(records, insert_side_effect=duplicate_error)

        async with main.app.test_request_context("/api/cron/recurring-expenses", method="POST"):
            with patch.object(recurring_module, "supabase", supabase_mock), \
                 patch.object(recurring_module, "registrar_auditoria_admin"):
                response = recurring_module._executar_geracao_recorrente("2026-04-05", self._actor)

        assert response.status_code == 200
        payload = await response.get_json()
        assert payload["generated"] == 0
        gastos_mock.insert.assert_called_once()

    @pytest.mark.asyncio
    async def test_gerar_processes_multiple_records_same_day(self):
        records = [
            {
                "id": "rec-1", "nome": "Netflix", "valor": 39.9, "dia_mes": 5,
                "mes_inicio": "2026-04-01", "mes_fim": None,
                "categoria": "Diversão", "natureza": "Lazer",
                "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
            },
            {
                "id": "rec-2", "nome": "Spotify", "valor": 19.9, "dia_mes": 5,
                "mes_inicio": "2026-04-01", "mes_fim": None,
                "categoria": "Diversão", "natureza": "Lazer",
                "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
            },
        ]
        supabase_mock, gastos_mock = self._build_supabase_mock(records)

        async with main.app.test_request_context("/api/cron/recurring-expenses", method="POST"):
            with patch.object(recurring_module, "supabase", supabase_mock), \
                 patch.object(recurring_module, "registrar_auditoria_admin"):
                response = recurring_module._executar_geracao_recorrente("2026-04-05", self._actor)

        assert response.status_code == 200
        payload = await response.get_json()
        assert payload["generated"] == 2
        assert gastos_mock.insert.call_count == 2

    @pytest.mark.asyncio
    async def test_gerar_uses_configured_transactions_table(self):
        records = [{
            "id": "rec-qa", "nome": "QA", "valor": 10.0, "dia_mes": 5,
            "mes_inicio": "2026-04-01", "mes_fim": None,
            "categoria": "Diversão", "natureza": "Lazer",
            "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
        }]
        supabase_mock, gastos_mock = self._build_supabase_mock(records, transactions_table="gastos_qa")

        async with main.app.test_request_context("/api/cron/recurring-expenses", method="POST"):
            with patch.object(recurring_module, "TRANSACTIONS_TABLE", "gastos_qa"), \
                 patch.object(recurring_module, "supabase", supabase_mock), \
                 patch.object(recurring_module, "registrar_auditoria_admin"):
                response = recurring_module._executar_geracao_recorrente("2026-04-05", self._actor)

        assert response.status_code == 200
        payload = await response.get_json()
        assert payload["generated"] == 1
        supabase_mock.table.assert_any_call("gastos_qa")
        gastos_mock.insert.assert_called_once()

    @pytest.mark.asyncio
    async def test_gerar_records_recurring_origin_on_insert(self):
        records = [{
            "id": "rec-1", "nome": "Netflix", "valor": 39.9, "dia_mes": 5,
            "mes_inicio": "2026-04-01", "mes_fim": None,
            "categoria": "Diversão", "natureza": "Lazer",
            "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
        }]
        supabase_mock, gastos_mock = self._build_supabase_mock(records)

        async with main.app.test_request_context("/api/cron/recurring-expenses", method="POST"):
            with patch.object(recurring_module, "supabase", supabase_mock), \
                 patch.object(recurring_module, "registrar_auditoria_admin"):
                response = recurring_module._executar_geracao_recorrente("2026-04-05", self._actor)

        assert response.status_code == 200
        inserted_gasto = gastos_mock.insert.call_args.args[0]
        assert inserted_gasto["recurring_expense_id"] == "rec-1"
        assert inserted_gasto["recurring_reference_date"] == "2026-04-05"
        assert inserted_gasto["descricao"] == "Netflix"

        recurring_table = supabase_mock.table("despesas_recorrentes")
        recurring_table.select.assert_called_with(
            "id,nome,valor,mes_inicio,mes_fim,dia_mes,natureza,categoria,metodo_pagamento,conta,ativo"
        )

    @pytest.mark.asyncio
    async def test_gerar_duplicate_unique_conflict_is_treated_as_already_generated(self):
        records = [{
            "id": "rec-1", "nome": "Netflix", "valor": 39.9, "dia_mes": 5,
            "mes_inicio": "2026-04-01", "mes_fim": None,
            "categoria": "Diversão", "natureza": "Lazer",
            "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
        }]
        duplicate_error = APIError({
            "code": "23505",
            "message": "duplicate key value violates unique constraint",
            "details": "Key already exists.",
            "hint": "",
        })
        supabase_mock, gastos_mock = self._build_supabase_mock(records, insert_side_effect=duplicate_error)

        async with main.app.test_request_context("/api/cron/recurring-expenses", method="POST"):
            with patch.object(recurring_module, "supabase", supabase_mock), \
                 patch.object(recurring_module, "registrar_auditoria_admin"), \
                 patch.object(recurring_module.logger, "error") as log_error:
                response = recurring_module._executar_geracao_recorrente("2026-04-05", self._actor)

        assert response.status_code == 200
        payload = await response.get_json()
        assert payload["generated"] == 0
        gastos_mock.insert.assert_called_once()
        log_error.assert_not_called()

    @pytest.mark.asyncio
    async def test_gerar_similar_recurring_expenses_do_not_block_each_other(self):
        records = [
            {
                "id": "rec-1", "nome": "Assinatura A", "valor": 39.9, "dia_mes": 5,
                "mes_inicio": "2026-04-01", "mes_fim": None,
                "categoria": "Diversão", "natureza": "Lazer",
                "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
            },
            {
                "id": "rec-2", "nome": "Assinatura B", "valor": 39.9, "dia_mes": 5,
                "mes_inicio": "2026-04-01", "mes_fim": None,
                "categoria": "Diversão", "natureza": "Lazer",
                "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
            },
        ]
        supabase_mock, gastos_mock = self._build_supabase_mock(records)

        async with main.app.test_request_context("/api/cron/recurring-expenses", method="POST"):
            with patch.object(recurring_module, "supabase", supabase_mock), \
                 patch.object(recurring_module, "registrar_auditoria_admin"):
                response = recurring_module._executar_geracao_recorrente("2026-04-05", self._actor)

        assert response.status_code == 200
        payload = await response.get_json()
        assert payload["generated"] == 2
        inserted_payloads = [call.args[0] for call in gastos_mock.insert.call_args_list]
        assert [payload["recurring_expense_id"] for payload in inserted_payloads] == ["rec-1", "rec-2"]

    @pytest.mark.asyncio
    async def test_gerar_rejects_invalid_data_referencia_format(self):
        async with main.app.test_request_context("/api/cron/recurring-expenses", method="POST"):
            response = recurring_module._executar_geracao_recorrente("05/04/2026", self._actor)

        assert response.status_code == 400
        payload = await response.get_json()
        assert "data_referencia must be in YYYY-MM-DD" in payload["message"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("reference_date", "expected_date"),
        [
            ("2026-02-28", "2026-02-28"),
            ("2024-02-29", "2024-02-29"),
        ],
    )
    async def test_gerar_uses_last_day_when_recurring_day_does_not_exist_in_month(self, reference_date, expected_date):
        records = [{
            "id": "rec-31", "nome": "Assinatura", "valor": 31.0, "dia_mes": 31,
            "mes_inicio": "2024-01-01", "mes_fim": None,
            "categoria": "Diversão", "natureza": "Lazer",
            "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
        }]
        supabase_mock, gastos_mock = self._build_supabase_mock(records)

        async with main.app.test_request_context("/api/cron/recurring-expenses", method="POST"):
            with patch.object(recurring_module, "supabase", supabase_mock), \
                 patch.object(recurring_module, "registrar_auditoria_admin"):
                response = recurring_module._executar_geracao_recorrente(reference_date, self._actor)

        assert response.status_code == 200
        payload = await response.get_json()
        assert payload["generated"] == 1
        inserted_gasto = gastos_mock.insert.call_args.args[0]
        assert inserted_gasto["data"] == expected_date
        assert inserted_gasto["descricao"] == "Assinatura"
        assert "nome" not in inserted_gasto

    @pytest.mark.asyncio
    async def test_gerar_does_not_use_last_day_fallback_before_month_end(self):
        records = [{
            "id": "rec-31", "nome": "Assinatura", "valor": 31.0, "dia_mes": 31,
            "mes_inicio": "2026-01-01", "mes_fim": None,
            "categoria": "Diversão", "natureza": "Lazer",
            "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
        }]
        supabase_mock, gastos_mock = self._build_supabase_mock(records)

        async with main.app.test_request_context("/api/cron/recurring-expenses", method="POST"):
            with patch.object(recurring_module, "supabase", supabase_mock), \
                 patch.object(recurring_module, "registrar_auditoria_admin"):
                response = recurring_module._executar_geracao_recorrente("2026-02-27", self._actor)

        assert response.status_code == 200
        payload = await response.get_json()
        assert payload["generated"] == 0
        gastos_mock.insert.assert_not_called()


class TestRecurringExpenseRoutes:
    @pytest.mark.asyncio
    async def test_routes_require_bearer(self):
        async with main.app.test_client() as client:
            resp_list = await client.get("/api/admin/despesas-recorrentes")
            resp_create = await client.post("/api/admin/despesas-recorrentes", json={})

        assert resp_list.status_code == 401
        assert resp_create.status_code == 401

    @pytest.mark.asyncio
    async def test_admin_execute_route_is_not_available(self):
        async with main.app.test_client() as client:
            resp_exec = await client.post("/api/admin/despesas-recorrentes/executar")

        assert resp_exec.status_code in {404, 405}

    @pytest.mark.asyncio
    async def test_admin_routes_full_crud_flow(self):
        auth_response = MagicMock()
        auth_response.user = {"id": "user-1", "email": "admin@example.com"}

        mock_recurring = MagicMock()
        mock_recurring.select.return_value.order.return_value.execute.return_value = MagicMock(data=[])
        mock_recurring.insert.return_value.execute.return_value = MagicMock(data=[{
            "id": "rec-1", "nome": "Netflix", "valor": 39.9, "mes_inicio": "2026-04-01",
            "dia_mes": 5, "natureza": "Lazer", "categoria": "Diversão",
            "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
            "ativo": True,
        }])
        mock_recurring.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[{"id": "rec-1"}])
        mock_recurring.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        mock_recurring.delete.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        mock_audit = MagicMock()
        mock_audit.insert.return_value.execute.return_value = MagicMock()

        def table_switch(name):
            if name == "despesas_recorrentes":
                return mock_recurring
            if name == "auditoria_admin":
                return mock_audit
            return MagicMock()

        async with main.app.test_client() as client:
            with patch.object(admin_auth, "_lookup_admin_user", return_value={"user_id": "user-1", "email": "admin@example.com"}), \
                 patch.object(admin_auth, "ADMIN_EMAILS", frozenset({"admin@example.com"})), \
                 patch.object(admin_auth, "ADMIN_USER_IDS", frozenset({"user-1"})), \
                 patch.object(admin_auth, "auth_test_mode_enabled", return_value=False), \
                 patch.object(admin_auth.supabase.auth, "get_user", MagicMock(return_value=auth_response)), \
                 patch.object(recurring_module, "supabase", MagicMock(table=MagicMock(side_effect=table_switch))), \
                 patch.object(recurring_module, "_normalize_recurring_expense_payload", return_value=({"nome": "Netflix"}, None)):
                # CREATE
                create_resp = await client.post(
                    "/api/admin/despesas-recorrentes",
                    headers={"Authorization": "Bearer header.payload.signature"},
                    json={
                        "nome": "Netflix", "valor": 39.9, "mes_inicio": "2026-04-01",
                        "dia_mes": 5, "categoria": "Diversão",
                        "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
                    },
                )
                assert create_resp.status_code == 201

                # LIST
                list_resp = await client.get(
                    "/api/admin/despesas-recorrentes",
                    headers={"Authorization": "Bearer header.payload.signature"},
                )
                assert list_resp.status_code == 200

                # UPDATE
                update_resp = await client.patch(
                    "/api/admin/despesas-recorrentes/rec-1",
                    headers={"Authorization": "Bearer header.payload.signature"},
                    json={"nome": "Netflix Updated"},
                )
                assert update_resp.status_code == 200

                # DELETE
                delete_resp = await client.delete(
                    "/api/admin/despesas-recorrentes/rec-1",
                    headers={"Authorization": "Bearer header.payload.signature"},
                )
                assert delete_resp.status_code == 200


class TestCronRecurringExpensesEndpoint:
    @pytest.mark.asyncio
    async def test_returns_503_when_cron_secret_not_configured(self):
        async with main.app.test_client() as client:
            with patch.object(cron_routes, "RECURRING_EXPENSES_CRON_SECRET", ""):
                resp = await client.post(
                    "/api/cron/recurring-expenses",
                    headers={"X-Cron-Secret": "anything"},
                )
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_returns_401_without_header(self):
        async with main.app.test_client() as client:
            with patch.object(cron_routes, "RECURRING_EXPENSES_CRON_SECRET", "the-secret"):
                resp = await client.post("/api/cron/recurring-expenses")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_returns_401_with_wrong_header(self):
        async with main.app.test_client() as client:
            with patch.object(cron_routes, "RECURRING_EXPENSES_CRON_SECRET", "the-secret"):
                resp = await client.post(
                    "/api/cron/recurring-expenses",
                    headers={"X-Cron-Secret": "nope"},
                )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_rate_limit_runs_before_generation(self):
        gerar = MagicMock(return_value=("ok", 200))

        async with main.app.test_client() as client:
            with patch.object(cron_routes, "CRON_RATE_LIMIT", 1, create=True), \
                 patch.object(cron_routes, "CRON_RATE_WINDOW_SECONDS", 60, create=True), \
                 patch.object(cron_routes, "RECURRING_EXPENSES_CRON_SECRET", "the-secret"), \
                 patch.object(cron_routes, "_executar_geracao_recorrente", gerar):
                first = await client.post(
                    "/api/cron/recurring-expenses",
                    json={},
                    headers={"X-Cron-Secret": "the-secret"},
                )
                second = await client.post(
                    "/api/cron/recurring-expenses",
                    json={},
                    headers={"X-Cron-Secret": "the-secret"},
                )

        assert first.status_code == 200
        assert second.status_code == 429
        payload = await second.get_json()
        assert payload["code"] == "CRON_RATE_LIMITED"
        gerar.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejects_large_payload_before_generation(self):
        gerar = MagicMock(return_value=("ok", 200))

        async with main.app.test_client() as client:
            with patch.object(cron_routes, "MAX_CRON_BODY_BYTES", 8, create=True), \
                 patch.object(cron_routes, "RECURRING_EXPENSES_CRON_SECRET", "the-secret"), \
                 patch.object(cron_routes, "_executar_geracao_recorrente", gerar):
                resp = await client.post(
                    "/api/cron/recurring-expenses",
                    data='{"data_referencia":"2026-04-01"}',
                    headers={"X-Cron-Secret": "the-secret", "Content-Type": "application/json"},
                )

        assert resp.status_code == 413
        gerar.assert_not_called()

    @pytest.mark.asyncio
    async def test_executes_generation_when_secret_matches(self):
        records = [{
            "id": "rec-1", "nome": "Netflix", "valor": 39.9, "dia_mes": 5,
            "mes_inicio": "2026-04-01", "mes_fim": None,
            "categoria": "Diversão", "natureza": "Lazer",
            "metodo_pagamento": "Cartao de Credito", "conta": "Nubank",
        }]
        mock_rec = MagicMock()
        mock_rec.select.return_value.eq.return_value.lte.return_value.execute.return_value = MagicMock(data=records)
        mock_gastos = MagicMock()
        mock_gastos.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        mock_gastos.insert.return_value.execute.return_value = MagicMock(data=[{"id": "g-1"}])

        def table_switch(name):
            if name == "despesas_recorrentes":
                return mock_rec
            if name == "gastos":
                return mock_gastos
            return MagicMock()

        async with main.app.test_client() as client:
            with patch.object(cron_routes, "RECURRING_EXPENSES_CRON_SECRET", "the-secret"), \
                 patch.object(recurring_module, "supabase", MagicMock(table=MagicMock(side_effect=table_switch))), \
                 patch.object(recurring_module, "registrar_auditoria_admin") as registrar:
                resp = await client.post(
                    "/api/cron/recurring-expenses",
                    headers={"X-Cron-Secret": "the-secret", "Content-Type": "application/json"},
                    json={"data_referencia": "2026-04-05"},
                )

        assert resp.status_code == 200
        body = await resp.get_json()
        assert body["generated"] == 1
        assert body["reference_date"] == "2026-04-05"
        registrar.assert_called_once()
        actor_arg, action_arg, *_ = registrar.call_args.args
        assert action_arg == "generate_recurring_expenses_cron"
        assert actor_arg["id"] == "system-cron"

    @pytest.mark.asyncio
    async def test_propagates_invalid_data_referencia(self):
        async with main.app.test_client() as client:
            with patch.object(cron_routes, "RECURRING_EXPENSES_CRON_SECRET", "the-secret"):
                resp = await client.post(
                    "/api/cron/recurring-expenses",
                    headers={"X-Cron-Secret": "the-secret", "Content-Type": "application/json"},
                    json={"data_referencia": "05/04/2026"},
                )
        assert resp.status_code == 400
