import calendar
from datetime import datetime
from postgrest.exceptions import APIError
from config import supabase, logger
from security import sanitize_plain_text
from utils import inferir_natureza, get_brasilia_time, add_months_safely
from core_logic import aplicar_map_reduce


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
    if not filtros: return query_obj
    
    raw_cat = filtros.get("categoria")
    if raw_cat and "," in raw_cat:
        raw_cat = None
        
    raw_nat = filtros.get("natureza")
    if raw_nat:
        nat_title = raw_nat.strip().title()
        if nat_title not in ["Essencial", "Lazer", "Receita"]:
            raw_nat = None
        else:
            raw_nat = nat_title
            
    if raw_nat: 
        query_obj = query_obj.eq("natureza", raw_nat)
        
    if raw_cat: 
        _, cat_canonica = inferir_natureza(raw_cat)
        query_obj = query_obj.eq("categoria", cat_canonica)
        
    if filtros.get("conta"): 
        query_obj = query_obj.eq("conta", filtros["conta"])
        
    if filtros.get("valor_exato"):
        query_obj = query_obj.eq("valor", float(filtros["valor_exato"]))
        
    if filtros.get("metodo_pagamento"):
        query_obj = query_obj.ilike("metodo_pagamento", f"%{filtros['metodo_pagamento']}%")
        
    tipo_tx = filtros.get("tipo_transacao")
    if tipo_tx == "saida" and not raw_nat:
        query_obj = query_obj.neq("natureza", "Receita")
    elif tipo_tx == "entrada" and not raw_nat:
        query_obj = query_obj.eq("natureza", "Receita")
        
    if filtros.get("mes") and filtros.get("ano"):
        try:
            ano, mes = int(filtros["ano"]), int(filtros["mes"])
            ultimo_dia = calendar.monthrange(ano, mes)[1]
            query_obj = query_obj.gte("data", f"{ano}-{mes:02d}-01").lte("data", f"{ano}-{mes:02d}-{ultimo_dia:02d}")
        except ValueError:
            pass
    elif filtros.get("ano"):
        try:
            ano = int(filtros["ano"])
            query_obj = query_obj.gte("data", f"{ano}-01-01").lte("data", f"{ano}-12-31")
        except ValueError:
            pass
            
    return query_obj

def consultar_no_banco(filtros):
    query = supabase.table("gastos").select("valor, descricao")
    resposta = aplicar_filtros_query(query, filtros).execute()
    return sum(item["valor"] for item in resposta.data), len(resposta.data)

def gravar_lote_no_banco(dados_lote):
    grupos, total, _ = aplicar_map_reduce(dados_lote)
    if not grupos: return 0, 0.0
    
    data_atual = get_brasilia_time().strftime("%Y-%m-%d")
    registros = []
    
    for (nat, cat), info in grupos.items():
        qtd = len(info["itens_desc"])
        nomes_limpos = [str(i).replace("▫️ ", "").split(" (")[0] for i in info["itens_desc"]]
        nomes_top3 = [n for idx, n in enumerate(nomes_limpos) if idx < 3]
        nomes_str = ", ".join(nomes_top3)
        desc: str = f"{nomes_str} e +{qtd-3} itens (Cupom)" if qtd > 3 else f"{nomes_str} (Cupom)"
        desc_limitada = sanitize_plain_text(desc, 250, "Cupom")
        
        registros.append({
            "data": data_atual, "valor": float(f"{info['valor']:.2f}"), "natureza": nat, "categoria": cat,
            "descricao": desc_limitada,
            "metodo_pagamento": sanitize_plain_text(dados_lote.get("metodo_pagamento"), 120, "Outros"),
            "conta": sanitize_plain_text(dados_lote.get("conta"), 120, "Nao Informada")
        })
        
    try:
        supabase.table("gastos").insert(registros).execute()
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

def inserir_no_banco(dados_reg):
    nat_limpa, cat_limpa = inferir_natureza(dados_reg.get("categoria"))
    valor_total = float(dados_reg.get("valor_total") or 0.0)
    parcelas = max(int(dados_reg.get("parcelas") or 1), 1)
    
    valor_base = float(f"{(valor_total / parcelas):.2f}")
    valor_ultima = float(f"{(valor_total - (valor_base * (parcelas - 1))):.2f}")
    
    data_informada = dados_reg.get("data")
    if data_informada:
        try:
            data_base_dt = datetime.strptime(data_informada, "%Y-%m-%d")
        except (ValueError, TypeError):
            data_base_dt = get_brasilia_time()
    else:
        data_base_dt = get_brasilia_time()
        
    registros_em_lote = []
    
    for i in range(parcelas):
        valor_parcela = valor_ultima if i == (parcelas - 1) else valor_base
        data_parcela = add_months_safely(data_base_dt, i).strftime("%Y-%m-%d")
        desc = sanitize_plain_text(dados_reg.get("descricao"), 250, "Sem descricao")
        if parcelas > 1: desc = f"{desc} [{i+1}/{parcelas}]"
            
        registros_em_lote.append({
            "data": data_parcela, "valor": valor_parcela, "natureza": nat_limpa, "categoria": cat_limpa,
            "descricao": sanitize_plain_text(desc, 250, "Sem descricao"),
            "metodo_pagamento": sanitize_plain_text(dados_reg.get("metodo_pagamento"), 120, "Outros"),
            "conta": sanitize_plain_text(dados_reg.get("conta"), 120, "Nao Informada")
        })
        
    try:
        supabase.table("gastos").insert(registros_em_lote).execute()
        logger.info({"event": "db_insert_success", "installments": parcelas})
    except APIError as e:
        logger.error({
            "event": "db_error_insert",
            "code": e.code,
            "message": e.message,
            "payload_fields": _payload_fields_summary(registros_em_lote),
            "record_count": len(registros_em_lote),
        })
        raise Exception(f"Erro no Banco: {e.message}")
