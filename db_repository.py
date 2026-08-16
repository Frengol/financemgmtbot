from postgrest.exceptions import APIError
from config import TRANSACTIONS_TABLE, supabase, logger
from domain.finance import build_installment_records, build_receipt_transaction_records, normalize_transaction_filters
from utils import get_brasilia_time


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
