import calendar
import html
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any


class DomainValidationError(ValueError):
    """Raised when user-provided financial data violates domain rules."""


CATEGORY_NATURE_MAP = {
    "moradia": ("Essencial", "Moradia"),
    "mercado": ("Essencial", "Mercado"),
    "transporte": ("Essencial", "Transporte"),
    "saúde": ("Essencial", "Saúde"),
    "educação": ("Essencial", "Educação"),
    "contas fixas": ("Essencial", "Contas Fixas"),
    "cuidados pessoais": ("Essencial", "Cuidados Pessoais"),
    "bares e restaurantes": ("Lazer", "Bares e Restaurantes"),
    "delivery e fast food": ("Lazer", "Delivery e Fast Food"),
    "bebidas alcoólicas": ("Lazer", "Bebidas Alcoólicas"),
    "viagens": ("Lazer", "Viagens"),
    "diversão": ("Lazer", "Diversão"),
    "vestuário": ("Lazer", "Vestuário"),
    "salário": ("Receita", "Salário"),
    "investimentos": ("Receita", "Investimentos"),
    "cashback": ("Receita", "Cashback"),
    "entradas diversas": ("Receita", "Entradas Diversas"),
    "receita": ("Receita", "Entradas Diversas"),
    "ganho": ("Receita", "Entradas Diversas"),
    "gasto": ("Outros", "Outros"),
    "despesa": ("Outros", "Outros"),
    "outros": ("Outros", "Outros"),
}

ALLOWED_TRANSACTION_FIELDS = {
    "data",
    "valor",
    "categoria",
    "descricao",
    "metodo_pagamento",
    "conta",
    "natureza",
}

ALLOWED_RECURRING_EXPENSE_FIELDS = {
    "nome",
    "valor",
    "mes_inicio",
    "mes_fim",
    "dia_mes",
    "categoria",
    "metodo_pagamento",
    "conta",
    "ativo",
}

VALID_FILTER_NATURES = {"Essencial", "Lazer", "Receita"}


@dataclass(frozen=True)
class ReceiptAggregation:
    groups: dict[tuple[str, str], dict[str, Any]]
    total: float
    global_discount: float
    discount_neutralized: bool = False


@dataclass(frozen=True)
class TransactionFilters:
    natureza: str | None = None
    categoria: str | None = None
    conta: str | None = None
    valor_exato: float | None = None
    metodo_pagamento: str | None = None
    tipo_transacao: str | None = None
    date_from: str | None = None
    date_to: str | None = None


def clean_text(value: Any, max_length: int, default: str = ""):
    raw = str(value if value is not None else default).strip()
    if not raw:
        raw = default
    return html.escape(raw.replace("\x00", ""), quote=False)[:max_length]


def _safe_float(value: Any, default: float = 0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_lookup(value: str):
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_only.strip().lower()


def _category_aliases():
    aliases: dict[str, str] = {}
    for category_key, (_, canonical_category) in CATEGORY_NATURE_MAP.items():
        aliases[normalize_lookup(category_key)] = category_key
        aliases[normalize_lookup(canonical_category)] = category_key
    return aliases


CATEGORY_ALIASES = _category_aliases()


def canonicalize_category(category: Any):
    if not isinstance(category, str):
        return None
    category_key = CATEGORY_ALIASES.get(normalize_lookup(category))
    if not category_key:
        return None
    return CATEGORY_NATURE_MAP[category_key][1]


def infer_transaction_nature(category: Any):
    if not isinstance(category, str):
        return "Outros", "Outros"
    category_key = CATEGORY_ALIASES.get(normalize_lookup(category))
    if not category_key:
        return "Outros", "Outros"
    return CATEGORY_NATURE_MAP[category_key]


def _canonical_category_key(category: Any):
    if not isinstance(category, str):
        return None
    return CATEGORY_ALIASES.get(normalize_lookup(category))


def normalize_transaction_payload(payload: dict[str, Any] | None):
    if not isinstance(payload, dict):
        raise DomainValidationError("Invalid transaction payload.")

    extra_fields = sorted(set(payload.keys()) - ALLOWED_TRANSACTION_FIELDS)
    if extra_fields:
        raise DomainValidationError("Unexpected transaction fields provided.")

    raw_date = str(payload.get("data") or "").strip()
    try:
        normalized_date = datetime.strptime(raw_date, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise DomainValidationError("Transaction date must be in YYYY-MM-DD format.") from exc

    try:
        normalized_value = round(float(payload.get("valor")), 2)
    except (TypeError, ValueError) as exc:
        raise DomainValidationError("Transaction value must be numeric.") from exc

    if normalized_value < 0:
        raise DomainValidationError("Transaction value must be zero or positive.")

    description = clean_text(payload.get("descricao"), 250)
    if not description:
        raise DomainValidationError("Transaction description is required.")

    category_key = _canonical_category_key(str(payload.get("categoria") or "").strip())
    if not category_key:
        raise DomainValidationError("Transaction category is invalid.")

    normalized_nature, normalized_category = CATEGORY_NATURE_MAP[category_key]
    return {
        "data": normalized_date,
        "valor": normalized_value,
        "natureza": normalized_nature,
        "categoria": normalized_category,
        "descricao": description,
        "metodo_pagamento": clean_text(payload.get("metodo_pagamento"), 120, "Outros") or "Outros",
        "conta": clean_text(payload.get("conta"), 120, "Nao Informada") or "Nao Informada",
    }


def parse_month_date(raw: str | None, field_name: str):
    if raw is None:
        return None
    raw_str = str(raw).strip()
    if not raw_str:
        return None

    for date_format in ("%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.strptime(raw_str, date_format).strftime("%Y-%m-%d")
        except ValueError:
            continue

    raise DomainValidationError(f"{field_name} must be YYYY-MM or YYYY-MM-DD format.")


def normalize_recurring_expense_payload(payload: dict[str, Any] | None):
    if not isinstance(payload, dict):
        raise DomainValidationError("Invalid recurring expense payload.")

    extra_fields = sorted(set(payload.keys()) - ALLOWED_RECURRING_EXPENSE_FIELDS)
    if extra_fields:
        raise DomainValidationError("Unexpected recurring expense fields provided.")

    required = {"nome", "valor", "mes_inicio", "dia_mes", "categoria"}
    missing = sorted(required - set(payload.keys()))
    if missing:
        raise DomainValidationError(f"Missing required fields: {', '.join(missing)}.")

    nome = clean_text(payload.get("nome"), 120)
    if not nome:
        raise DomainValidationError("Recurring expense name is required.")

    try:
        normalized_value = round(float(payload.get("valor")), 2)
    except (TypeError, ValueError) as exc:
        raise DomainValidationError("Recurring expense value must be numeric.") from exc

    if normalized_value < 0:
        raise DomainValidationError("Recurring expense value must be zero or positive.")

    mes_inicio = parse_month_date(payload.get("mes_inicio"), "mes_inicio")
    mes_fim = parse_month_date(payload.get("mes_fim"), "mes_fim")
    if mes_fim is not None and mes_inicio is not None and mes_fim < mes_inicio:
        raise DomainValidationError("mes_fim cannot be before mes_inicio.")

    try:
        dia_mes = int(payload.get("dia_mes"))
    except (TypeError, ValueError) as exc:
        raise DomainValidationError("dia_mes must be an integer between 1 and 31.") from exc

    if dia_mes < 1 or dia_mes > 31:
        raise DomainValidationError("dia_mes must be an integer between 1 and 31.")

    category_key = _canonical_category_key(str(payload.get("categoria") or "").strip())
    if not category_key:
        raise DomainValidationError("Recurring expense category is invalid.")

    normalized_nature, normalized_category = CATEGORY_NATURE_MAP[category_key]
    ativo = payload.get("ativo")

    return {
        "nome": nome,
        "valor": normalized_value,
        "mes_inicio": mes_inicio,
        "mes_fim": mes_fim,
        "dia_mes": dia_mes,
        "natureza": normalized_nature,
        "categoria": normalized_category,
        "metodo_pagamento": clean_text(payload.get("metodo_pagamento"), 120, "Outros") or "Outros",
        "conta": clean_text(payload.get("conta"), 120, "Nao Informada") or "Nao Informada",
        "ativo": bool(ativo) if ativo is not None else True,
    }


def normalize_receipt_payload(receipt: Any):
    if not isinstance(receipt, dict):
        return {"metodo_pagamento": "Outros", "conta": "Nao Informada", "desconto_global": 0.0, "itens": []}

    normalized_items = []
    items = receipt.get("itens")
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        normalized_items.append({
            "nome": clean_text(item.get("nome"), 120, "Item") or "Item",
            "valor_bruto": max(0.0, _safe_float(item.get("valor_bruto"))),
            "desconto_item": max(0.0, _safe_float(item.get("desconto_item"))),
            "categoria": clean_text(item.get("categoria"), 80, "Outros") or "Outros",
        })

    return {
        "metodo_pagamento": clean_text(receipt.get("metodo_pagamento"), 120, "Outros") or "Outros",
        "conta": clean_text(receipt.get("conta"), 120, "Nao Informada") or "Nao Informada",
        "desconto_global": max(0.0, _safe_float(receipt.get("desconto_global"))),
        "itens": normalized_items,
    }


def normalize_register_payload(transaction: Any):
    if not isinstance(transaction, dict):
        return {}

    return {
        "data": str(transaction.get("data") or "").strip(),
        "valor_total": max(0.0, _safe_float(transaction.get("valor_total"))),
        "parcelas": max(1, _safe_int(transaction.get("parcelas"), 1)),
        "categoria": clean_text(transaction.get("categoria"), 80, "Outros") or "Outros",
        "descricao": clean_text(transaction.get("descricao"), 120, "Sem descricao") or "Sem descricao",
        "metodo_pagamento": clean_text(transaction.get("metodo_pagamento"), 120, "Outros") or "Outros",
        "conta": clean_text(transaction.get("conta"), 120, "Nao Informada") or "Nao Informada",
    }


def aggregate_receipt_items(receipt: dict[str, Any] | None):
    receipt = receipt if isinstance(receipt, dict) else {}
    items = receipt.get("itens") if isinstance(receipt.get("itens"), list) else []
    if not items:
        return ReceiptAggregation({}, 0.0, 0.0, False)

    groups: dict[tuple[str, str], dict[str, Any]] = {}
    item_discounts_sum = 0.0

    for item in items:
        if not isinstance(item, dict):
            continue
        nature, category = infer_transaction_nature(item.get("categoria"))
        gross_value = _safe_float(item.get("valor_bruto"))
        item_discount = _safe_float(item.get("desconto_item"))
        item_discounts_sum += item_discount
        net_value = max(0.0, gross_value - item_discount)
        name = clean_text(item.get("nome"), 120, "Item") or "Item"
        key = (nature, category)

        if key not in groups:
            groups[key] = {"valor": 0.0, "itens_desc": [], "item_names": []}

        groups[key]["valor"] += net_value
        groups[key]["itens_desc"].append(f"▫️ {name} (R$ {net_value:.2f})")
        groups[key]["item_names"].append(name)

    global_discount = _safe_float(receipt.get("desconto_global"))
    discount_neutralized = False
    if global_discount > 0 and abs(item_discounts_sum - global_discount) <= 0.05:
        global_discount = 0.0
        discount_neutralized = True

    if global_discount > 0 and groups:
        largest_group_key = max(groups, key=lambda key: groups[key]["valor"])
        groups[largest_group_key]["valor"] = max(0.0, groups[largest_group_key]["valor"] - global_discount)

    total = sum(group["valor"] for group in groups.values())
    return ReceiptAggregation(groups, total, global_discount, discount_neutralized)


def build_receipt_transaction_records(receipt: dict[str, Any] | None, reference_date: str):
    aggregation = aggregate_receipt_items(receipt)
    if not aggregation.groups:
        return [], 0.0

    receipt = receipt if isinstance(receipt, dict) else {}
    records = []
    for (nature, category), info in aggregation.groups.items():
        names = info.get("item_names") or []
        if not names:
            names = [str(item).replace("▫️ ", "").split(" (")[0] for item in info.get("itens_desc", [])]
        top_names = [name for index, name in enumerate(names) if index < 3]
        names_label = ", ".join(top_names)
        description = f"{names_label} e +{len(names)-3} itens (Cupom)" if len(names) > 3 else f"{names_label} (Cupom)"
        records.append({
            "data": reference_date,
            "valor": float(f"{info['valor']:.2f}"),
            "natureza": nature,
            "categoria": category,
            "descricao": clean_text(description, 250, "Cupom"),
            "metodo_pagamento": clean_text(receipt.get("metodo_pagamento"), 120, "Outros"),
            "conta": clean_text(receipt.get("conta"), 120, "Nao Informada"),
        })

    return records, aggregation.total


def add_months_safely(source_date: datetime, months: int):
    month = source_date.month - 1 + months
    year = source_date.year + month // 12
    month = month % 12 + 1
    day = min(source_date.day, calendar.monthrange(year, month)[1])
    return source_date.replace(year=year, month=month, day=day)


def build_installment_records(transaction: dict[str, Any], *, fallback_date: datetime):
    nature, category = infer_transaction_nature(transaction.get("categoria"))
    total_value = _safe_float(transaction.get("valor_total"))
    installments = max(_safe_int(transaction.get("parcelas"), 1), 1)
    base_value = float(f"{(total_value / installments):.2f}")
    last_value = float(f"{(total_value - (base_value * (installments - 1))):.2f}")

    raw_date = transaction.get("data")
    if raw_date:
        try:
            base_date = datetime.strptime(str(raw_date), "%Y-%m-%d")
        except (ValueError, TypeError):
            base_date = fallback_date
    else:
        base_date = fallback_date

    records = []
    for index in range(installments):
        installment_value = last_value if index == installments - 1 else base_value
        installment_date = add_months_safely(base_date, index).strftime("%Y-%m-%d")
        description = clean_text(transaction.get("descricao"), 250, "Sem descricao")
        if installments > 1:
            description = f"{description} [{index + 1}/{installments}]"
        records.append({
            "data": installment_date,
            "valor": installment_value,
            "natureza": nature,
            "categoria": category,
            "descricao": clean_text(description, 250, "Sem descricao"),
            "metodo_pagamento": clean_text(transaction.get("metodo_pagamento"), 120, "Outros"),
            "conta": clean_text(transaction.get("conta"), 120, "Nao Informada"),
        })
    return records


def normalize_transaction_filters(filters: dict[str, Any] | None):
    filters = filters if isinstance(filters, dict) else {}

    raw_category = filters.get("categoria")
    category = None
    if raw_category and "," not in str(raw_category):
        _, category = infer_transaction_nature(str(raw_category))

    raw_nature = filters.get("natureza")
    nature = None
    if raw_nature:
        candidate_nature = str(raw_nature).strip().title()
        if candidate_nature in VALID_FILTER_NATURES:
            nature = candidate_nature

    transaction_type = filters.get("tipo_transacao")
    if transaction_type not in {"entrada", "saida"}:
        transaction_type = None

    exact_value = None
    if filters.get("valor_exato"):
        try:
            exact_value = float(filters["valor_exato"])
        except (TypeError, ValueError):
            exact_value = None

    date_from = None
    date_to = None
    if filters.get("mes") and filters.get("ano"):
        try:
            year, month = int(filters["ano"]), int(filters["mes"])
            last_day = calendar.monthrange(year, month)[1]
            date_from = f"{year}-{month:02d}-01"
            date_to = f"{year}-{month:02d}-{last_day:02d}"
        except ValueError:
            pass
    elif filters.get("ano"):
        try:
            year = int(filters["ano"])
            date_from = f"{year}-01-01"
            date_to = f"{year}-12-31"
        except ValueError:
            pass

    return TransactionFilters(
        natureza=nature,
        categoria=category,
        conta=str(filters["conta"]).strip() if filters.get("conta") else None,
        valor_exato=exact_value,
        metodo_pagamento=str(filters["metodo_pagamento"]).strip() if filters.get("metodo_pagamento") else None,
        tipo_transacao=transaction_type,
        date_from=date_from,
        date_to=date_to,
    )


def compute_recurring_transaction_date(year: int, month: int, day: int):
    last_day = calendar.monthrange(year, month)[1]
    effective_day = min(day, last_day)
    return f"{year}-{month:02d}-{effective_day:02d}"


def recurring_expense_applies_to_reference_month(expense: dict[str, Any], reference: datetime):
    month_start = f"{reference.year}-{reference.month:02d}-01"
    mes_inicio = str(expense.get("mes_inicio") or "")
    if mes_inicio and mes_inicio > month_start:
        return False

    mes_fim = expense.get("mes_fim")
    if mes_fim:
        try:
            end_month = datetime.strptime(str(mes_fim), "%Y-%m-%d")
        except ValueError:
            return False
        if reference.year > end_month.year or (reference.year == end_month.year and reference.month > end_month.month):
            return False

    return True


def build_recurring_transaction_for_reference(expense: dict[str, Any], reference_date: str):
    reference = datetime.strptime(reference_date, "%Y-%m-%d")
    if not recurring_expense_applies_to_reference_month(expense, reference):
        return None

    day = _safe_int(expense.get("dia_mes"), 1)
    transaction_date = compute_recurring_transaction_date(reference.year, reference.month, day)
    if transaction_date != reference_date:
        return None

    return {
        "data": transaction_date,
        "valor": expense.get("valor"),
        "natureza": expense.get("natureza"),
        "categoria": expense.get("categoria"),
        "descricao": expense.get("nome"),
        "metodo_pagamento": expense.get("metodo_pagamento"),
        "conta": expense.get("conta"),
        "recurring_expense_id": expense.get("id"),
        "recurring_reference_date": transaction_date,
    }
