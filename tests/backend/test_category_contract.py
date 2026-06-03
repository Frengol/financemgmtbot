import re
from collections import defaultdict
from pathlib import Path

from domain.finance import CATEGORY_NATURE_MAP


REPO_ROOT = Path(__file__).resolve().parents[2]


def _backend_categories_by_nature():
    categories: dict[str, list[str]] = defaultdict(list)
    for nature, category in CATEGORY_NATURE_MAP.values():
        if category not in categories[nature]:
            categories[nature].append(category)
    return dict(categories)


def _frontend_categories_by_nature():
    source = (REPO_ROOT / "frontend/src/lib/transactions.ts").read_text(encoding="utf-8")
    match = re.search(
        r"export const transactionCategories: Record<TransactionNature, string\[]> = \{(?P<body>.*?)\};",
        source,
        re.DOTALL,
    )
    assert match, "transactionCategories literal not found in frontend contract"

    categories: dict[str, list[str]] = {}
    for nature, raw_values in re.findall(r"\s*(Essencial|Lazer|Receita|Outros): \[(.*?)\],", match.group("body")):
        categories[nature] = re.findall(r"'([^']+)'", raw_values)
    return categories


def test_frontend_categories_match_backend_domain_contract():
    assert _frontend_categories_by_nature() == _backend_categories_by_nature()
