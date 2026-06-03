from datetime import datetime

import pytest

from domain.finance import (
    DomainValidationError,
    aggregate_receipt_items,
    build_installment_records,
    build_receipt_transaction_records,
    build_recurring_transaction_for_reference,
    canonicalize_category,
    compute_recurring_transaction_date,
    infer_transaction_nature,
    normalize_recurring_expense_payload,
    normalize_receipt_payload,
    normalize_register_payload,
    normalize_transaction_filters,
    normalize_transaction_payload,
)


class TestFinanceDomainCategories:
    def test_canonicalizes_category_without_coupling_to_accents_or_case(self):
        assert canonicalize_category("  diversao  ") == "Diversão"
        assert canonicalize_category("SAUDE") == "Saúde"
        assert canonicalize_category("Mercado") == "Mercado"

    def test_infers_nature_from_canonical_category(self):
        assert infer_transaction_nature("mercado") == ("Essencial", "Mercado")
        assert infer_transaction_nature("Bebidas Alcoolicas") == ("Lazer", "Bebidas Alcoólicas")
        assert infer_transaction_nature("receita") == ("Receita", "Entradas Diversas")
        assert infer_transaction_nature("categoria livre") == ("Outros", "Outros")

    def test_keeps_unknown_category_inputs_in_domain_defaults(self):
        assert canonicalize_category(None) is None
        assert canonicalize_category("categoria livre") is None
        assert infer_transaction_nature(None) == ("Outros", "Outros")


class TestFinanceDomainPayloads:
    def test_normalizes_manual_transaction_payload_without_http_or_database(self):
        payload = normalize_transaction_payload({
            "data": "2026-04-05",
            "valor": "12.345",
            "categoria": "mercado",
            "descricao": "  compra mensal  ",
            "metodo_pagamento": "",
            "conta": None,
            "natureza": "Lazer",
        })

        assert payload == {
            "data": "2026-04-05",
            "valor": 12.35,
            "natureza": "Essencial",
            "categoria": "Mercado",
            "descricao": "compra mensal",
            "metodo_pagamento": "Outros",
            "conta": "Nao Informada",
        }

    def test_rejects_invalid_transaction_payload_with_domain_error(self):
        with pytest.raises(DomainValidationError, match="Transaction category is invalid"):
            normalize_transaction_payload({
                "data": "2026-04-05",
                "valor": 10,
                "categoria": "inventada",
                "descricao": "teste",
            })

    def test_normalizes_recurring_expense_payload_and_derives_nature(self):
        payload = normalize_recurring_expense_payload({
            "nome": "Netflix",
            "valor": "39.899",
            "mes_inicio": "2026-04",
            "mes_fim": None,
            "dia_mes": "31",
            "categoria": "diversao",
            "metodo_pagamento": "Cartao de Credito",
            "conta": "Nubank",
        })

        assert payload == {
            "nome": "Netflix",
            "valor": 39.9,
            "mes_inicio": "2026-04-01",
            "mes_fim": None,
            "dia_mes": 31,
            "natureza": "Lazer",
            "categoria": "Diversão",
            "metodo_pagamento": "Cartao de Credito",
            "conta": "Nubank",
            "ativo": True,
        }

    def test_rejects_mes_fim_before_mes_inicio(self):
        with pytest.raises(DomainValidationError, match="mes_fim cannot be before mes_inicio"):
            normalize_recurring_expense_payload({
                "nome": "Academia",
                "valor": 100,
                "mes_inicio": "2026-06-01",
                "mes_fim": "2026-05-01",
                "dia_mes": 5,
                "categoria": "Cuidados Pessoais",
            })

    def test_normalizes_receipt_payload_from_ai_before_orchestration(self):
        payload = normalize_receipt_payload({
            "metodo_pagamento": "",
            "conta": None,
            "desconto_global": "-10",
            "itens": [
                {"nome": "Arroz\x00", "valor_bruto": "12.5", "desconto_item": "-1", "categoria": ""},
                "invalid",
            ],
        })

        assert payload == {
            "metodo_pagamento": "Outros",
            "conta": "Nao Informada",
            "desconto_global": 0.0,
            "itens": [
                {
                    "nome": "Arroz",
                    "valor_bruto": 12.5,
                    "desconto_item": 0.0,
                    "categoria": "Outros",
                }
            ],
        }

    def test_normalizes_register_payload_from_ai_before_database_adapter(self):
        payload = normalize_register_payload({
            "data": "2026-04-05",
            "valor_total": "-12",
            "parcelas": "0",
            "categoria": None,
            "descricao": "",
            "metodo_pagamento": "",
            "conta": "",
        })

        assert payload == {
            "data": "2026-04-05",
            "valor_total": 0.0,
            "parcelas": 1,
            "categoria": "Outros",
            "descricao": "Sem descricao",
            "metodo_pagamento": "Outros",
            "conta": "Nao Informada",
        }

    def test_normalizes_non_object_ai_payloads_to_safe_defaults(self):
        assert normalize_receipt_payload(None) == {
            "metodo_pagamento": "Outros",
            "conta": "Nao Informada",
            "desconto_global": 0.0,
            "itens": [],
        }
        assert normalize_register_payload(None) == {}


class TestFinanceDomainReceiptsAndInstallments:
    def test_aggregates_receipt_and_neutralizes_duplicate_global_discount(self):
        result = aggregate_receipt_items({
            "itens": [
                {"nome": "Arroz", "valor_bruto": 50, "desconto_item": 5, "categoria": "Mercado"},
                {"nome": "Feijao", "valor_bruto": 30, "desconto_item": 5, "categoria": "Mercado"},
            ],
            "desconto_global": 10,
        })

        assert result.global_discount == 0
        assert result.discount_neutralized is True
        assert result.total == pytest.approx(70)
        assert result.groups[("Essencial", "Mercado")]["valor"] == pytest.approx(70)

    def test_builds_receipt_records_without_supabase_dependency(self):
        records, total = build_receipt_transaction_records({
            "metodo_pagamento": "Pix",
            "conta": "Nubank",
            "itens": [
                {"nome": "Arroz", "valor_bruto": 25, "desconto_item": 0, "categoria": "Mercado"},
                {"nome": "Jogo", "valor_bruto": 15, "desconto_item": 0, "categoria": "Diversão"},
            ],
        }, "2026-04-05")

        assert total == pytest.approx(40)
        assert records == [
            {
                "data": "2026-04-05",
                "valor": 25.0,
                "natureza": "Essencial",
                "categoria": "Mercado",
                "descricao": "Arroz (Cupom)",
                "metodo_pagamento": "Pix",
                "conta": "Nubank",
            },
            {
                "data": "2026-04-05",
                "valor": 15.0,
                "natureza": "Lazer",
                "categoria": "Diversão",
                "descricao": "Jogo (Cupom)",
                "metodo_pagamento": "Pix",
                "conta": "Nubank",
            },
        ]

    def test_builds_receipt_records_from_legacy_item_descriptions_when_names_are_absent(self):
        records, total = build_receipt_transaction_records({
            "itens": [
                {"categoria": "Mercado", "valor_bruto": 10, "desconto_item": 0},
                "invalid",
            ],
        }, "2026-04-05")

        assert total == pytest.approx(10)
        assert records[0]["descricao"] == "Item (Cupom)"

    def test_builds_installment_records_with_last_installment_adjustment(self):
        records = build_installment_records(
            {
                "data": "2026-01-31",
                "valor_total": 100,
                "parcelas": 3,
                "categoria": "Transporte",
                "descricao": "Manutencao",
                "metodo_pagamento": "Cartao",
                "conta": "Bradesco",
            },
            fallback_date=datetime(2026, 4, 5),
        )

        assert [record["data"] for record in records] == ["2026-01-31", "2026-02-28", "2026-03-31"]
        assert [record["valor"] for record in records] == [33.33, 33.33, 33.34]
        assert sum(record["valor"] for record in records) == pytest.approx(100)

    def test_builds_installments_from_fallback_date_when_date_is_invalid_or_missing(self):
        invalid_date_records = build_installment_records(
            {
                "data": "not-a-date",
                "valor_total": 20,
                "parcelas": "invalid",
                "categoria": "Mercado",
                "descricao": "Compra",
            },
            fallback_date=datetime(2026, 4, 5),
        )
        missing_date_records = build_installment_records(
            {"valor_total": 20, "parcelas": 1, "categoria": "Mercado", "descricao": "Compra"},
            fallback_date=datetime(2026, 5, 6),
        )

        assert invalid_date_records[0]["data"] == "2026-04-05"
        assert missing_date_records[0]["data"] == "2026-05-06"


class TestFinanceDomainFiltersAndRecurring:
    def test_normalizes_filters_as_data_before_repository_applies_query(self):
        filters = normalize_transaction_filters({
            "natureza": "inventada",
            "categoria": "Mercado, Transporte",
            "tipo_transacao": "saida",
            "mes": "04",
            "ano": "2026",
            "valor_exato": "12.50",
            "metodo_pagamento": "Pix",
        })

        assert filters.natureza is None
        assert filters.categoria is None
        assert filters.tipo_transacao == "saida"
        assert filters.date_from == "2026-04-01"
        assert filters.date_to == "2026-04-30"
        assert filters.valor_exato == 12.5
        assert filters.metodo_pagamento == "Pix"

    def test_ignores_invalid_numeric_and_date_filters_without_throwing(self):
        monthly_filters = normalize_transaction_filters({
            "categoria": "Mercado",
            "valor_exato": "invalid",
            "mes": "invalid",
            "ano": "2026",
            "conta": "Nubank",
        })
        yearly_filters = normalize_transaction_filters({"ano": "2026"})

        assert monthly_filters.categoria == "Mercado"
        assert monthly_filters.valor_exato is None
        assert monthly_filters.date_from is None
        assert monthly_filters.conta == "Nubank"
        assert yearly_filters.date_from == "2026-01-01"
        assert yearly_filters.date_to == "2026-12-31"

    def test_recurring_date_clamps_to_last_day_of_month(self):
        assert compute_recurring_transaction_date(2026, 2, 31) == "2026-02-28"
        assert compute_recurring_transaction_date(2024, 2, 31) == "2024-02-29"

    def test_builds_recurring_transaction_only_for_matching_reference_date(self):
        rec = {
            "id": "rec-1",
            "nome": "Assinatura",
            "valor": 29.9,
            "mes_inicio": "2026-01-01",
            "mes_fim": "2026-12-01",
            "dia_mes": 31,
            "natureza": "Lazer",
            "categoria": "Diversão",
            "metodo_pagamento": "Pix",
            "conta": "Nubank",
        }

        assert build_recurring_transaction_for_reference(rec, "2026-02-27") is None
        assert build_recurring_transaction_for_reference(rec, "2026-02-28") == {
            "data": "2026-02-28",
            "valor": 29.9,
            "natureza": "Lazer",
            "categoria": "Diversão",
            "descricao": "Assinatura",
            "metodo_pagamento": "Pix",
            "conta": "Nubank",
            "recurring_expense_id": "rec-1",
            "recurring_reference_date": "2026-02-28",
        }

    def test_skips_recurring_transactions_outside_active_months_or_invalid_end_month(self):
        base = {
            "id": "rec-1",
            "nome": "Assinatura",
            "valor": 29.9,
            "mes_inicio": "2026-03-01",
            "dia_mes": 5,
        }

        assert build_recurring_transaction_for_reference(base, "2026-02-05") is None
        assert build_recurring_transaction_for_reference({**base, "mes_inicio": "2026-01-01", "mes_fim": "invalid"}, "2026-02-05") is None
        assert build_recurring_transaction_for_reference({**base, "mes_inicio": "2026-01-01", "mes_fim": "2026-01-01"}, "2026-02-05") is None
