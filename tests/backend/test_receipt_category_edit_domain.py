import copy
import json

import pytest

from domain.finance import (
    CATEGORY_NATURE_MAP,
    RECEIPT_EDIT_PAGE_SIZE,
    RECEIPT_ITEM_CATEGORIES,
    DomainValidationError,
    aggregate_receipt_items,
    build_receipt_transaction_records,
    paginate_receipt_rows,
    receipt_item_rows,
    set_receipt_item_category,
)


def _receipt(**overrides):
    base = {
        "metodo_pagamento": "Crédito",
        "conta": "Nubank",
        "desconto_global": 0.0,
        "itens": [
            {"nome": "Arroz", "valor_bruto": 30.0, "desconto_item": 0.0, "categoria": "Mercado"},
            {"nome": "Cerveja", "valor_bruto": 12.5, "desconto_item": 0.5, "categoria": "Mercado"},
            {"nome": "Sabonete", "valor_bruto": 4.0, "desconto_item": 0.0, "categoria": "Cuidados Pessoais"},
        ],
    }
    base.update(overrides)
    return base


def _category_index(name):
    return [category for category, _ in RECEIPT_ITEM_CATEGORIES].index(name)


class TestCanonicalCategoryList:
    def test_order_is_fixed_because_the_index_travels_in_callbacks(self):
        assert RECEIPT_ITEM_CATEGORIES == (
            ("Moradia", "Essencial"),
            ("Mercado", "Essencial"),
            ("Transporte", "Essencial"),
            ("Saúde", "Essencial"),
            ("Educação", "Essencial"),
            ("Contas Fixas", "Essencial"),
            ("Cuidados Pessoais", "Essencial"),
            ("Bares e Restaurantes", "Lazer"),
            ("Delivery e Fast Food", "Lazer"),
            ("Bebidas Alcoólicas", "Lazer"),
            ("Viagens", "Lazer"),
            ("Diversão", "Lazer"),
            ("Vestuário", "Lazer"),
            ("Outros", "Outros"),
        )

    def test_has_no_income_and_no_duplicated_aliases(self):
        categories = [category for category, _ in RECEIPT_ITEM_CATEGORIES]
        assert len(categories) == len(set(categories))
        assert all(nature != "Receita" for _, nature in RECEIPT_ITEM_CATEGORIES)
        assert "Gasto" not in categories and "Despesa" not in categories

    def test_covers_every_expense_category_of_the_canonical_map(self):
        expected = {(category, nature) for nature, category in CATEGORY_NATURE_MAP.values() if nature != "Receita"}
        assert set(RECEIPT_ITEM_CATEGORIES) == expected


class TestItemRows:
    def test_rows_keep_original_positions_net_values_and_effective_categories(self):
        rows = receipt_item_rows(_receipt())
        assert [(r.position, r.name, r.net_value, r.category, r.nature) for r in rows] == [
            (1, "Arroz", 30.0, "Mercado", "Essencial"),
            (2, "Cerveja", 12.0, "Mercado", "Essencial"),
            (3, "Sabonete", 4.0, "Cuidados Pessoais", "Essencial"),
        ]

    def test_equal_names_are_distinguished_by_position(self):
        receipt = _receipt(itens=[
            {"nome": "Pão", "valor_bruto": 5.0, "desconto_item": 0.0, "categoria": "Mercado"},
            {"nome": "Pão", "valor_bruto": 5.0, "desconto_item": 0.0, "categoria": "Mercado"},
        ])
        rows = receipt_item_rows(receipt)
        assert [r.position for r in rows] == [1, 2]

    def test_unknown_or_alias_categories_show_their_effective_value(self):
        receipt = _receipt(itens=[
            {"nome": "X", "valor_bruto": 1.0, "desconto_item": 0.0, "categoria": "categoria livre"},
            {"nome": "Y", "valor_bruto": 1.0, "desconto_item": 0.0, "categoria": "despesa"},
        ])
        assert [(r.category, r.nature) for r in receipt_item_rows(receipt)] == [("Outros", "Outros"), ("Outros", "Outros")]

    @pytest.mark.parametrize(
        "receipt",
        [None, "x", [], {}, {"itens": []}, {"itens": "x"}, {"itens": [{"nome": "a"}, "bad"]}],
        ids=repr,
    )
    def test_insufficient_payload_fails_closed(self, receipt):
        assert receipt_item_rows(receipt) is None

    def test_pagination_is_stable_and_clamped(self):
        items = [{"nome": f"I{i}", "valor_bruto": 1.0, "desconto_item": 0.0, "categoria": "Mercado"} for i in range(1, 20)]
        rows = receipt_item_rows(_receipt(itens=items))
        assert RECEIPT_EDIT_PAGE_SIZE == 8
        page_rows, page, pages = paginate_receipt_rows(rows, 1)
        assert [r.position for r in page_rows] == list(range(9, 17)) and (page, pages) == (1, 3)
        page_rows, page, pages = paginate_receipt_rows(rows, 2)
        assert [r.position for r in page_rows] == [17, 18, 19] and page == 2
        assert paginate_receipt_rows(rows, 99)[1] == 2
        assert paginate_receipt_rows(rows, -1)[1] == 0

    def test_large_receipts_are_not_artificially_limited(self):
        items = [{"nome": f"I{i}", "valor_bruto": 1.0, "desconto_item": 0.0, "categoria": "Mercado"} for i in range(1200)]
        receipt = _receipt(itens=items)
        rows = receipt_item_rows(receipt)
        assert rows[-1].position == 1200
        updated = set_receipt_item_category(receipt, 1200, _category_index("Outros"))
        assert updated["itens"][1199]["categoria"] == "Outros"


class TestSetItemCategory:
    def test_changing_beer_does_not_touch_rice(self):
        receipt = _receipt()
        updated = set_receipt_item_category(receipt, 2, _category_index("Bebidas Alcoólicas"))
        rows = receipt_item_rows(updated)
        assert (rows[0].category, rows[0].nature) == ("Mercado", "Essencial")
        assert (rows[1].category, rows[1].nature) == ("Bebidas Alcoólicas", "Lazer")

    def test_only_the_raw_category_of_that_item_changes(self):
        receipt = _receipt(desconto_global=3.0, extra_field={"kept": True})
        receipt["itens"][1]["quantidade"] = 6
        original = copy.deepcopy(receipt)
        updated = set_receipt_item_category(receipt, 2, _category_index("Bebidas Alcoólicas"))

        assert receipt == original  # input is never mutated
        expected = copy.deepcopy(original)
        expected["itens"][1]["categoria"] = "Bebidas Alcoólicas"
        assert json.dumps(updated, sort_keys=True) == json.dumps(expected, sort_keys=True)

    def test_regrouping_moves_the_global_discount_to_the_new_largest_group(self):
        receipt = _receipt(
            desconto_global=2.0,
            itens=[
                {"nome": "Arroz", "valor_bruto": 10.0, "desconto_item": 0.0, "categoria": "Mercado"},
                {"nome": "Cerveja", "valor_bruto": 8.0, "desconto_item": 0.0, "categoria": "Mercado"},
                {"nome": "Vinho", "valor_bruto": 7.0, "desconto_item": 0.0, "categoria": "Mercado"},
            ],
        )
        before = aggregate_receipt_items(receipt)
        assert before.groups[("Essencial", "Mercado")]["valor"] == 23.0
        updated = set_receipt_item_category(receipt, 2, _category_index("Bebidas Alcoólicas"))
        updated = set_receipt_item_category(updated, 3, _category_index("Bebidas Alcoólicas"))
        after = aggregate_receipt_items(updated)
        assert after.groups[("Lazer", "Bebidas Alcoólicas")]["valor"] == 13.0  # 15 - 2
        assert after.groups[("Essencial", "Mercado")]["valor"] == 10.0
        assert after.total == pytest.approx(23.0)
        records, total = build_receipt_transaction_records(updated, "2026-11-23")
        assert {(r["natureza"], r["categoria"], r["valor"]) for r in records} == {
            ("Essencial", "Mercado", 10.0),
            ("Lazer", "Bebidas Alcoólicas", 13.0),
        }
        assert all(r["conta"] == "Nubank" and r["metodo_pagamento"] == "Crédito" for r in records)

    def test_global_discount_neutralization_is_preserved(self):
        receipt = _receipt(desconto_global=0.5)
        updated = set_receipt_item_category(receipt, 2, _category_index("Bebidas Alcoólicas"))
        aggregation = aggregate_receipt_items(updated)
        assert aggregation.discount_neutralized is True
        assert updated["desconto_global"] == 0.5  # the informed value is kept raw
        assert aggregation.total == pytest.approx(46.0)

    @pytest.mark.parametrize("current", ["Mercado", "mercado", "MERCADO "])
    def test_same_effective_category_returns_none(self, current):
        receipt = _receipt()
        receipt["itens"][0]["categoria"] = current
        assert set_receipt_item_category(receipt, 1, _category_index("Mercado")) is None

    def test_alias_with_same_effective_category_returns_none(self):
        receipt = _receipt()
        receipt["itens"][0]["categoria"] = "despesa"
        assert set_receipt_item_category(receipt, 1, _category_index("Outros")) is None

    @pytest.mark.parametrize("position", [0, -1, 4, True, "1", None, 1.0])
    def test_invalid_position_raises(self, position):
        with pytest.raises(DomainValidationError):
            set_receipt_item_category(_receipt(), position, 0)

    @pytest.mark.parametrize("category_index", [-1, 14, True, "0", None, 0.0])
    def test_invalid_category_raises(self, category_index):
        with pytest.raises(DomainValidationError):
            set_receipt_item_category(_receipt(), 1, category_index)

    @pytest.mark.parametrize("receipt", [None, {}, {"itens": []}, {"itens": ["bad"]}], ids=repr)
    def test_invalid_payload_raises(self, receipt):
        with pytest.raises(DomainValidationError):
            set_receipt_item_category(receipt, 1, 0)
