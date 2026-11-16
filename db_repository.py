from postgrest.exceptions import APIError
from config import TRANSACTIONS_TABLE, supabase, logger
from domain.duplicate_expense import pick_first_match
from domain.finance import build_installment_records, build_receipt_transaction_records, normalize_transaction_filters
from utils import get_brasilia_time

DUPLICATE_LOOKUP_PAGE_SIZE = 500
DELETE_BATCH_SIZE = 200
DELETE_CANDIDATE_FIELDS = "id, data, valor, natureza, categoria, descricao, metodo_pagamento, conta"


def _payload_fields_summary(payloads):
    fields = set()
    if isinstance(payloads, list):
        for payload in payloads:
          if isinstance(payload, dict):
              fields.update(payload.keys())
    elif isinstance(payloads, dict):
        fields.update(payloads.keys())

    return sorted(fields)

def aplicar_filtros_query(query_obj, filtros):
    query_obj = query_obj.gte("valor", 0)
    normalized = normalize_transaction_filters(filtros)
    if normalized.natureza:
        query_obj = query_obj.eq("natureza", normalized.natureza)
    if normalized.categoria:
        query_obj = query_obj.eq("categoria", normalized.categoria)
    if normalized.conta:
        query_obj = query_obj.eq("conta", normalized.conta)
    if normalized.valor_exato is not None:
        query_obj = query_obj.eq("valor", normalized.valor_exato)
    if normalized.metodo_pagamento:
        query_obj = query_obj.ilike("metodo_pagamento", f"%{normalized.metodo_pagamento}%")
    if normalized.tipo_transacao == "saida" and not normalized.natureza:
        query_obj = query_obj.neq("natureza", "Receita")
    elif normalized.tipo_transacao == "entrada" and not normalized.natureza:
        query_obj = query_obj.eq("natureza", "Receita")
    if normalized.date_from:
        query_obj = query_obj.gte("data", normalized.date_from)
    if normalized.date_to:
        query_obj = query_obj.lte("data", normalized.date_to)
    return query_obj

def consultar_no_banco(filtros):
    query = supabase.table(TRANSACTIONS_TABLE).select("valor, descricao")
    resposta = aplicar_filtros_query(query, filtros).execute()
    return sum(item["valor"] for item in resposta.data), len(resposta.data)


def _escape_like(value):
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _aplicar_filtros_exclusao(query_obj, filters):
    query_obj = query_obj.gte("valor", 0)
    if filters.valor_exato is not None:
        query_obj = query_obj.eq("valor", filters.valor_exato)
    if filters.data:
        query_obj = query_obj.eq("data", filters.data)
    if filters.date_from:
        query_obj = query_obj.gte("data", filters.date_from)
    if filters.date_to:
        query_obj = query_obj.lte("data", filters.date_to)
    if filters.natureza:
        query_obj = query_obj.eq("natureza", filters.natureza)
    if filters.categoria:
        query_obj = query_obj.eq("categoria", filters.categoria)
    if filters.conta:
        query_obj = query_obj.eq("conta", filters.conta)
    if filters.metodo_pagamento:
        if "*" in filters.metodo_pagamento:
            # PostgREST treats `*` as `%` in ilike; the normalizer refuses it, never widen here.
            raise ValueError("metodo_pagamento with '*' is not searchable")
        query_obj = query_obj.ilike("metodo_pagamento", f"%{_escape_like(filters.metodo_pagamento)}%")
    if filters.tipo_transacao == "saida":
        query_obj = query_obj.neq("natureza", "Receita")
    elif filters.tipo_transacao == "entrada":
        query_obj = query_obj.eq("natureza", "Receita")
    return query_obj


def _valid_record_id(value):
    return (isinstance(value, int) and not isinstance(value, bool)) or (isinstance(value, str) and bool(value))


def _id_sort_key(value):
    return (0, value, "") if isinstance(value, int) else (1, 0, value)


def buscar_candidatos_exclusao(filters):
    """Every record matching the deletion filters, unique and ordered by id.

    Pages through the whole result (stable `order id` + `range`) so the API row limit
    can never hide candidates: the preview count and the frozen ids stay faithful.
    Any failure or malformed page propagates; "could not check" is never "no match".
    """
    found = {}
    start = 0
    while True:
        query = supabase.table(TRANSACTIONS_TABLE).select(DELETE_CANDIDATE_FIELDS)
        response = (
            _aplicar_filtros_exclusao(query, filters)
            .order("id", desc=False)
            .range(start, start + DUPLICATE_LOOKUP_PAGE_SIZE - 1)
            .execute()
        )
        page = getattr(response, "data", None)
        if not isinstance(page, list):
            raise RuntimeError("Deletion candidate lookup is unavailable.")
        for row in page:
            if not isinstance(row, dict) or not _valid_record_id(row.get("id")):
                raise RuntimeError("Deletion candidate lookup returned an unreadable record.")
            found.setdefault(row["id"], row)
        if len(page) < DUPLICATE_LOOKUP_PAGE_SIZE:
            return [found[record_id] for record_id in sorted(found, key=_id_sort_key)]
        start += DUPLICATE_LOOKUP_PAGE_SIZE


def normalizar_ids_exclusao(ids):
    """The frozen ids as a list, or None when they are empty or not usable ids."""
    if not isinstance(ids, list) or not ids or not all(_valid_record_id(i) for i in ids):
        return None
    return ids


def apagar_registros_por_ids(ids):
    """Delete exactly these ids (in bounded batches to keep request URLs short)."""
    valid_ids = normalizar_ids_exclusao(ids)
    if valid_ids is None:
        raise ValueError("Deletion requires a non-empty list of record ids.")
    for index in range(0, len(valid_ids), DELETE_BATCH_SIZE):
        batch = valid_ids[index:index + DELETE_BATCH_SIZE]
        supabase.table(TRANSACTIONS_TABLE).delete().in_("id", batch).execute()
    return len(valid_ids)


def load_records_by_source_update_id(source_update_id, origin_chat_id=None):
    if source_update_id is None:
        return []
    query = (
        supabase
        .table(TRANSACTIONS_TABLE)
        .select("id, data, valor, natureza, categoria, descricao, metodo_pagamento, conta, source_record_key")
        .eq("source_update_id", source_update_id)
    )
    if origin_chat_id is not None:
        query = query.eq("source_origin_chat_id", origin_chat_id)
    response = query.order("source_record_key").execute()
    data = getattr(response, "data", None)
    return data if isinstance(data, list) else []

def find_matching_expense(candidate):
    """First persisted expense (lowest id) matching the frozen candidate.

    Date, amount and expense-only are filtered in the database; account and
    description are compared in the domain. Any query failure propagates so the
    caller can never mistake "could not check" for "no match".
    """
    record = candidate.record
    start = 0
    while True:
        response = (
            supabase
            .table(TRANSACTIONS_TABLE)
            .select("id, data, valor, natureza, conta, descricao")
            .eq("data", record["data"])
            .eq("valor", record["valor"])
            .neq("natureza", "Receita")
            .order("id", desc=False)
            .range(start, start + DUPLICATE_LOOKUP_PAGE_SIZE - 1)
            .execute()
        )
        page = getattr(response, "data", None)
        if not isinstance(page, list):
            raise RuntimeError("Duplicate expense lookup is unavailable.")
        match = pick_first_match(candidate, page)
        if match is not None:
            return match
        if len(page) < DUPLICATE_LOOKUP_PAGE_SIZE:
            return None
        start += DUPLICATE_LOOKUP_PAGE_SIZE


def _with_effect_keys(registros, source_update_id, prefix, origin_chat_id=None):
    if source_update_id is None:
        return registros
    enriched = []
    for index, record in enumerate(registros, start=1):
        row = {
            **record,
            "source_update_id": source_update_id,
            "source_record_key": f"{prefix}:{index:04d}",
        }
        if origin_chat_id is not None:
            row["source_origin_chat_id"] = origin_chat_id
        enriched.append(row)
    return enriched


def _persist_records(registros, *, source_update_id=None):
    table = supabase.table(TRANSACTIONS_TABLE)
    if source_update_id is None:
        return table.insert(registros).execute()
    return table.upsert(
        registros,
        on_conflict="source_update_id,source_record_key",
        ignore_duplicates=True,
    ).execute()


def _inserir_registros_lote(registros, total, *, source_update_id=None):
    if not registros:
        return 0, 0.0

    try:
        _persist_records(registros, source_update_id=source_update_id)
        logger.info({"event": "db_bulk_insert_success", "items_grouped": len(registros), "total_value": total})
        return len(registros), total
    except APIError as e:
        logger.error({
            "event": "db_error_bulk_insert",
            "code": e.code,
            "message": e.message,
            "payload_fields": _payload_fields_summary(registros),
            "record_count": len(registros),
        })
        raise Exception(f"Erro no Banco (Cod: {e.code}): {e.message}")

def gravar_lote_no_banco_com_registros(dados_lote, *, source_update_id=None, origin_chat_id=None):
    data_atual = get_brasilia_time().strftime("%Y-%m-%d")
    registros, total = build_receipt_transaction_records(dados_lote, data_atual)
    registros = _with_effect_keys(registros, source_update_id, "receipt", origin_chat_id=origin_chat_id)
    linhas, total_salvo = _inserir_registros_lote(
        registros,
        total,
        source_update_id=source_update_id,
    )
    return linhas, total_salvo, registros if linhas else []

def gravar_lote_no_banco(dados_lote, *, source_update_id=None, origin_chat_id=None):
    linhas, total, _ = gravar_lote_no_banco_com_registros(
        dados_lote,
        source_update_id=source_update_id,
        origin_chat_id=origin_chat_id,
    )
    return linhas, total

def inserir_no_banco(dados_reg, *, source_update_id=None, origin_chat_id=None):
    registros_em_lote = build_installment_records(dados_reg, fallback_date=get_brasilia_time())
    registros_em_lote = _with_effect_keys(registros_em_lote, source_update_id, "installment", origin_chat_id=origin_chat_id)
    try:
        _persist_records(registros_em_lote, source_update_id=source_update_id)
        logger.info({"event": "db_insert_success", "installments": len(registros_em_lote)})
        return registros_em_lote
    except APIError as e:
        logger.error({
            "event": "db_error_insert",
            "code": e.code,
            "message": e.message,
            "payload_fields": _payload_fields_summary(registros_em_lote),
            "record_count": len(registros_em_lote),
        })
        raise Exception(f"Erro no Banco: {e.message}")
