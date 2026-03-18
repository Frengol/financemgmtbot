from collections import defaultdict
from typing import Dict, Any, List
from utils import inferir_natureza
from config import logger

def aplicar_map_reduce(dados_lote):
    itens = dados_lote.get("itens", [])
    if not itens: return {}, 0.0, 0.0

    grupos = {}
    soma_descontos_itens = 0.0

    for item in itens:
        nat, cat = inferir_natureza(item.get("categoria"))
        bruto = float(item.get("valor_bruto") or 0.0)
        desc_item = float(item.get("desconto_item") or 0.0)
        
        soma_descontos_itens += desc_item
        val_liquido = max(0.0, bruto - desc_item)
        nome = item.get("nome", "Item")
        
        chave = (nat, cat)
        if chave not in grupos: grupos[chave] = {"valor": 0.0, "itens_desc": []}
        
        grupos[chave]["valor"] += val_liquido
        grupos[chave]["itens_desc"].append(f"▫️ {nome} (R$ {val_liquido:.2f})")

    desc_global = float(dados_lote.get("desconto_global") or 0.0)
    
    if desc_global > 0 and abs(soma_descontos_itens - desc_global) <= 0.05:
        logger.info({"event": "guardrail_discount_neutralized", "saved_value": desc_global})
        desc_global = 0.0 
        dados_lote["desconto_global"] = 0.0 

    if desc_global > 0 and grupos:
        chave_maior = max(grupos, key=lambda k: grupos[k]["valor"])
        grupos[chave_maior]["valor"] = max(0.0, grupos[chave_maior]["valor"] - desc_global)

    total_final = sum(g["valor"] for g in grupos.values())
    return grupos, total_final, desc_global

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

def gerar_texto_edicao(dados_lote):
    linhas = ["--CUPOM_EDIT--", f"Pagamento: {dados_lote.get('metodo_pagamento', 'Não Informado')}"]
    linhas.append(f"Conta: {dados_lote.get('conta', 'Não Informada')}")
    linhas.append(f"Desconto Global: {dados_lote.get('desconto_global', 0.0)}\n")
    for item in dados_lote.get("itens", []):
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
