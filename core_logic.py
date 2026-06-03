from collections import defaultdict
from typing import Dict, Any, List
from config import logger
from domain.finance import aggregate_receipt_items

def _format_currency(value):
    try:
        numeric_value = float(value or 0.0)
    except (TypeError, ValueError):
        numeric_value = 0.0
    return f"R$ {numeric_value:,.2f}"

def _sort_text(value):
    return str(value or "").casefold()

def _receipt_item_sort_key(item):
    if not isinstance(item, dict):
        return "", ""
    return _sort_text(item.get("categoria")), _sort_text(item.get("nome"))

def aplicar_map_reduce(dados_lote):
    resultado = aggregate_receipt_items(dados_lote)
    if resultado.discount_neutralized:
        logger.info({"event": "guardrail_discount_neutralized", "saved_value": dados_lote.get("desconto_global")})
        dados_lote["desconto_global"] = 0.0
    return resultado.groups, resultado.total, resultado.global_discount

def gerar_mensagem_resumo(cache_id, dados_lote, grupos, total_final, desc_global):
    pagamento = dados_lote.get("metodo_pagamento", "Não Informado")
    conta = dados_lote.get("conta", "Não Informada")
    
    msg = f"🧾 **Resumo do Cupom**\n💳 Pagamento: {pagamento} ({conta})\n"
    if desc_global > 0: msg += f"📉 Desconto Global Aplicado: R$ {desc_global:.2f} (Rateado no grupo maior)\n"
    msg += "\n"
    
    for (nat, cat), info in grupos.items():
        msg += f"📦 **{cat} ({nat})** - R$ {info['valor']:.2f}\n"
        for item_txt in info["itens_desc"]:
            msg += f"{item_txt}\n"
        msg += "\n"
        
    msg += f"*\nTotal Líquido Validado: R$ {total_final:,.2f}*"
    return msg

def formatar_resumo_registros_salvos(registros: List[Dict[str, Any]]):
    if not registros:
        return "✅ **Cupom salvo!**\n📝 Nenhum registro foi gerado."

    primeiro = registros[0]
    data = primeiro.get("data") or "Não informada"
    pagamento = primeiro.get("metodo_pagamento") or "Não informado"
    conta = primeiro.get("conta") or "Não informada"
    total = sum(float(registro.get("valor") or 0.0) for registro in registros if isinstance(registro, dict))

    msg = (
        "✅ **Cupom salvo!**\n"
        f"🗓️ Data: {data}\n"
        f"💳 Pagamento: {pagamento}\n"
        f"🏦 Banco/conta: {conta}\n\n"
        "📌 **Registros salvos:**\n"
    )

    for index, registro in enumerate(registros, start=1):
        natureza = registro.get("natureza") or "Não informada"
        categoria = registro.get("categoria") or "Não informada"
        msg += f"{index}. {_format_currency(registro.get('valor'))} | {natureza} > {categoria}\n"

    msg += f"\n📊 **Total:** {_format_currency(total)}\n📝 Registros: {len(registros)}"
    return msg

def gerar_texto_edicao(dados_lote):
    linhas = ["--CUPOM_EDIT--", f"Pagamento: {dados_lote.get('metodo_pagamento', 'Não Informado')}"]
    linhas.append(f"Conta: {dados_lote.get('conta', 'Não Informada')}")
    linhas.append(f"Desconto Global: {dados_lote.get('desconto_global', 0.0)}\n")
    itens = [item for item in dados_lote.get("itens", []) if isinstance(item, dict)]
    itens_ordenados = sorted(itens, key=_receipt_item_sort_key)
    for item in itens_ordenados:
        cat = item.get("categoria", "Outros")
        linhas.append(f"[{cat}] {item.get('nome')} : Bruto={item.get('valor_bruto', 0.0)} | Desconto={item.get('desconto_item', 0.0)}")
    return "\n".join(linhas)

def formatar_relatorio_exclusao(registros: List[Dict[str, Any]]):
    total_regs = len(registros)
    if total_regs == 0:
        return "❌ Nenhum registro encontrado com esses critérios para exclusão."
        
    msg = f"⚠️ **ATENÇÃO: EXCLUSÃO DE DADOS**\nEncontrei {total_regs} registro(s) correspondente(s):\n\n"
    
    if total_regs <= 10:
        for r in registros:
            data_formatada = r.get("data", "Sem data")
            msg += f"▫️ *{data_formatada}* | R$ {r['valor']:.2f}\n   {r['natureza']} > {r['categoria']}\n   💳 {r.get('metodo_pagamento','?')} ({r.get('conta', '?')})\n   📝 {r.get('descricao', 'Sem descrição')[:30]}...\n\n"
    else:
        agrupamento = defaultdict(list)
        for r in registros: agrupamento[r.get("data", "Sem data")].append(r)
            
        chaves_top5 = [k for i, k in enumerate(agrupamento.keys()) if i < 5]
        for data in chaves_top5:
            itens = agrupamento[data]
            msg += f"📅 **{data}** ({len(itens)} itens)\n"
            itens_top3 = [it for it_i, it in enumerate(itens) if it_i < 3]
            for r in itens_top3:
                msg += f"   ▫️ {r['natureza']} > {r['categoria']} | R$ {r['valor']:.2f}\n"
            if len(itens) > 3: msg += f"   ... e mais {len(itens)-3} itens.\n"
            msg += "\n"
        if len(agrupamento) > 5:
            msg += f"*(E itens em outras {len(agrupamento)-5} datas...)*\n"
            
    msg += "\n🛑 **Tem a certeza absoluta que deseja APAGAR isto permanentemente?**"
    return msg
