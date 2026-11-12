from datetime import datetime

import pytest

from domain import duplicate_expense as dup

FALLBACK = datetime(2026, 11, 11, 10, 0, 0)


def _dados(**overrides):
    base = {
        "data": "2026-11-10",
        "valor_total": 25.5,
        "parcelas": 1,
        "categoria": "Mercado",
        "descricao": "Padaria Central",
        "metodo_pagamento": "Pix",
        "conta": "Nubank",
    }
    base.update(overrides)
    return base


class TestNormalizeMatchText:
    def test_casefold_accents_trim_and_spaces_but_keeps_punctuation(self):
        assert dup.normalize_match_text("  PÃO   de  Açúcar!! ") == "pao de acucar!!"
        assert dup.normalize_match_text("Straße") == "strasse"

    def test_punctuation_is_preserved_so_it_differs(self):
        assert dup.normalize_match_text("Cafe.") != dup.normalize_match_text("Cafe")

    def test_only_accents_are_removed_not_compatibility_forms(self):
        # NFD keeps fullwidth letters and similar forms distinct (NFKD would fold them).
        assert dup.normalize_match_text("ＣＡＦＥ") != dup.normalize_match_text("cafe")
        assert dup.normalize_match_text("№1") != dup.normalize_match_text("no1")

    def test_decomposed_and_precomposed_accents_are_equal(self):
        assert dup.normalize_match_text("A\u0301gua") == dup.normalize_match_text("Água") == "agua"

    def test_fullwidth_and_punctuation_variants_do_not_form_a_key_match(self):
        base = dup.build_match_key("2026-11-10", 10, "Nubank", "Cafe")
        assert dup.build_match_key("2026-11-10", 10, "Nubank", "Ｃafe") != base
        assert dup.build_match_key("2026-11-10", 10, "Nubank", "Cafe!") != base
        assert dup.build_match_key("2026-11-10", 10, "Nubank", "  CAFÉ ") == base

    def test_non_text_is_empty(self):
        assert dup.normalize_match_text(None) == ""
        assert dup.normalize_match_text(12) == ""


class TestAmountCents:
    @pytest.mark.parametrize(
        "value,expected",
        [(25.5, 2550), ("25.50", 2550), (0.1 + 0.2, 30), (10, 1000), (0.005, 1)],
    )
    def test_cents(self, value, expected):
        assert dup.amount_cents(value) == expected

    @pytest.mark.parametrize("value", [None, True, "abc", float("nan"), float("inf")])
    def test_invalid_values_have_no_cents(self, value):
        assert dup.amount_cents(value) is None


class TestCandidate:
    def test_single_positive_expense_is_frozen_with_fallback_date(self):
        candidate = dup.prepare_duplicate_candidate(_dados(data=""), fallback_date=FALLBACK)
        assert candidate.record["data"] == "2026-11-11"
        assert candidate.transaction["data"] == "2026-11-11"
        assert candidate.transaction["valor_total"] == 25.5
        assert candidate.transaction["parcelas"] == 1
        assert candidate.key == ("2026-11-11", 2550, "nubank", "padaria central")

    def test_frozen_transaction_rebuilds_the_same_record_on_another_day(self):
        from domain.finance import build_installment_records

        candidate = dup.prepare_duplicate_candidate(_dados(data=""), fallback_date=FALLBACK)
        rebuilt = build_installment_records(candidate.transaction, fallback_date=datetime(2030, 1, 1))
        assert rebuilt == [candidate.record]

    def test_invalid_date_uses_fallback(self):
        candidate = dup.prepare_duplicate_candidate(_dados(data="31/02/2026"), fallback_date=FALLBACK)
        assert candidate.record["data"] == "2026-11-11"

    @pytest.mark.parametrize(
        "overrides",
        [
            {"parcelas": 2},
            {"valor_total": 0},
            {"valor_total": -5},
            {"categoria": "Salário"},
            {"conta": ""},
            {"conta": "Nao Informada"},
            {"conta": "  NAO informada "},
            {"descricao": ""},
            {"descricao": "Sem descricao"},
            {"descricao": " SEM   Descrição "},
        ],
    )
    def test_ineligible_inputs_have_no_candidate(self, overrides):
        assert dup.prepare_duplicate_candidate(_dados(**overrides), fallback_date=FALLBACK) is None

    def test_non_dict_has_no_candidate(self):
        assert dup.prepare_duplicate_candidate({}, fallback_date=FALLBACK) is None
        assert dup.prepare_duplicate_candidate("x", fallback_date=FALLBACK) is None


class TestMatching:
    def _candidate(self, **overrides):
        return dup.prepare_duplicate_candidate(_dados(**overrides), fallback_date=FALLBACK)

    def _row(self, row_id, **overrides):
        row = {
            "id": row_id,
            "data": "2026-11-10",
            "valor": 25.5,
            "natureza": "Essencial",
            "categoria": "Outros",
            "descricao": "padaria  central",
            "metodo_pagamento": "Dinheiro",
            "conta": "NUBANK",
        }
        row.update(overrides)
        return row

    def test_matches_ignoring_category_method_case_accents_and_spaces(self):
        rows = [self._row(7, descricao="PADARIA   CENTRAL ")]
        assert dup.pick_first_match(self._candidate(), rows)["id"] == 7

    def test_first_id_ascending_wins(self):
        rows = [self._row(9), self._row(3), self._row(5)]
        assert dup.pick_first_match(self._candidate(), rows)["id"] == 3

    def test_mixed_id_types_are_ordered_without_crashing(self):
        rows = [self._row("b"), self._row(2), self._row("a")]
        assert dup.pick_first_match(self._candidate(), rows)["id"] == 2

    @pytest.mark.parametrize(
        "overrides",
        [
            {"valor": 25.51},
            {"data": "2026-11-09"},
            {"conta": "Itau"},
            {"descricao": "Padaria Central."},
            {"descricao": "Sem descricao"},
            {"conta": "Nao Informada"},
            {"conta": ""},
            {"natureza": "Receita"},
            {"valor": -25.5},
            {"valor": "x"},
            {"data": None},
        ],
    )
    def test_non_matches(self, overrides):
        assert dup.pick_first_match(self._candidate(), [self._row(1, **overrides)]) is None

    def test_data_with_time_suffix_still_matches(self):
        assert dup.pick_first_match(self._candidate(), [self._row(1, data="2026-11-10T00:00:00")]) is not None

    def test_non_dict_rows_are_ignored(self):
        assert dup.pick_first_match(self._candidate(), ["x", None]) is None

    def test_snapshot_keeps_only_minimum_fields(self):
        snap = dup.snapshot_matched_record(self._row(4, metodo_pagamento="Pix"))
        assert snap == {
            "id": 4,
            "data": "2026-11-10",
            "valor": 25.5,
            "conta": "NUBANK",
            "descricao": "padaria  central",
        }


class TestPayloadParsing:
    def _payload(self):
        candidate = dup.prepare_duplicate_candidate(_dados(), fallback_date=FALLBACK)
        return {
            "transaction": candidate.transaction,
            "matched_record": {"id": 1, "data": "2026-11-10", "valor": 25.5, "conta": "Nubank", "descricao": "x"},
        }

    def test_valid_payload_roundtrips(self):
        parsed = dup.parse_duplicate_payload(self._payload())
        assert parsed.transaction["descricao"] == "Padaria Central"
        assert parsed.matched_record["id"] == 1

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda p: p.pop("transaction"),
            lambda p: p.pop("matched_record"),
            lambda p: p.update(transaction="x"),
            lambda p: p["transaction"].update(parcelas=2),
            lambda p: p["transaction"].update(valor_total=0),
            lambda p: p["transaction"].update(data="nope"),
            lambda p: p["transaction"].update(data=""),
            lambda p: p["transaction"].update(data=20261110),
            lambda p: p["transaction"].pop("conta"),
            lambda p: p["matched_record"].pop("valor"),
            lambda p: p["matched_record"].update(id=None),
        ],
    )
    def test_invalid_payload_fails_closed(self, mutate):
        payload = self._payload()
        mutate(payload)
        assert dup.parse_duplicate_payload(payload) is None

    def test_unreadable_previous_amount_is_shown_as_unknown(self):
        payload = self._payload()
        payload["matched_record"]["valor"] = "abc"
        parsed = dup.parse_duplicate_payload(payload)
        assert "R$ ?" in dup.format_duplicate_confirmation(parsed)

    def test_non_dict_payload_fails_closed(self):
        assert dup.parse_duplicate_payload(None) is None
        assert dup.parse_duplicate_payload([]) is None


class TestMessages:
    def test_confirmation_text_shows_both_records_and_escapes_dynamic_values(self):
        payload = dup.parse_duplicate_payload(
            {
                "transaction": {
                    "data": "2026-11-11",
                    "valor_total": 12.34,
                    "parcelas": 1,
                    "categoria": "Outros",
                    "descricao": "a_b*c[d`e",
                    "metodo_pagamento": "Pix",
                    "conta": "Conta_1",
                },
                "matched_record": {"id": 1, "data": "2026-11-11", "valor": 12.34, "conta": "C*", "descricao": "x_y"},
            }
        )
        text = dup.format_duplicate_confirmation(payload)
        assert "Este gasto já está registrado. É outro gasto?" in text
        assert "Anterior" in text and "Proposto" in text
        assert "R$ 12.34" in text and "2026-11-11" in text
        assert "a\\_b\\*c\\[d\\`e" in text
        assert "Conta\\_1" in text and "x\\_y" in text and "C\\*" in text

    def test_keyboard_has_only_opaque_action_and_id(self):
        keyboard = dup.duplicate_keyboard("tu_abc")
        buttons = [b for row in keyboard["inline_keyboard"] for b in row]
        assert {b["callback_data"] for b in buttons} == {"dupskip_tu_abc", "dupsave_tu_abc"}
        assert {b["text"] for b in buttons} == {"Já registrei — não salvar", "É outro — salvar"}

    def test_fixed_messages(self):
        assert dup.DUPLICATE_SKIPPED_MESSAGE == "Gasto não salvo. O registro anterior foi mantido."
        assert dup.DUPLICATE_EXPIRED_MESSAGE == (
            "Confirmação expirada. Nenhum novo gasto foi salvo; envie o gasto novamente se necessário."
        )


class TestSavedMessage:
    def test_single_expense_summary_has_the_persisted_values_escaped(self):
        text = dup.format_saved_expense(
            {
                "data": "2026-11-10",
                "valor": 25.5,
                "natureza": "Essencial",
                "categoria": "Mercado",
                "descricao": "Padaria_Central",
                "metodo_pagamento": "Pix",
                "conta": "Nubank",
            }
        )
        assert text.startswith("✅ **Salvo!**")
        assert "R$ 25.50" in text and "Essencial" in text and "Mercado" in text
        assert "2026-11-10" in text and "Nubank (Pix)" in text and "Padaria\\_Central" in text
