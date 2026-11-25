from collections import defaultdict
from typing import Dict, Any, List
from config import logger
from domain.duplicate_expense import escape_markdown
from domain.finance import aggregate_receipt_items, normalize_receipt_payload

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

def gerar_resumo_cupom(cache_id, payload):
    """Summary of a stored receipt; works on a normalized copy so the stored payload is never mutated."""
    dados_lote = normalize_receipt_payload(payload)
    grupos, total_final, desc_global = aplicar_map_reduce(dados_lote)
    return gerar_mensagem_resumo(cache_id, dados_lote, grupos, total_final, desc_global)

def gerar_lista_itens_cupom(linhas, pagina, paginas, total_itens):
    msg = f"🏷️ **Editar categorias** — {total_itens} itens (página {pagina + 1}/{paginas})\nEscolha o item para corrigir:\n\n"
    for linha in linhas:
        msg += f"#{linha.position} {escape_markdown(linha.name)} — {_format_currency(linha.net_value)} — {escape_markdown(linha.category)}\n"
    return msg

def gerar_tela_item_cupom(linha):
    return (
        f"🏷️ **Item #{linha.position}**\n"
        f"📝 {escape_markdown(linha.name)}\n"
        f"💰 Líquido: {_format_currency(linha.net_value)}\n"
        f"📂 Categoria: {escape_markdown(linha.category)}\n"
        f"📊 Natureza: {escape_markdown(linha.nature)} (definida pela categoria)"
    )

def gerar_seletor_categoria(linha):
    return (
        f"🏷️ **Item #{linha.position}** — {escape_markdown(linha.name)}\n"
        f"Categoria atual: {escape_markdown(linha.category)} · {escape_markdown(linha.nature)}\n\n"
        "Escolha a nova categoria (a natureza acompanha a categoria):"
    )

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

DELETE_PREVIEW_SAMPLE = 10
TELEGRAM_MESSAGE_LIMIT = 4096
_PREVIEW_FIELD_MAX = 200
_ABBREVIATED_MARK = " … (abreviado)"


def _clip(value, limit, default):
    """Full text when it fits; an exceptionally long field is cut and explicitly marked as abbreviated."""
    text = str(value).strip() if value is not None else ""
    if not text:
        return default, False
    if len(text) <= limit:
        return text, False
    return text[:limit].rstrip(), True


def _field(value, limit, default):
    text, abbreviated = _clip(value, limit, default)
    return escape_markdown(text) + (_ABBREVIATED_MARK if abbreviated else "")


def _delete_filter_lines(filters):
    if filters.data:
        period = f"📅 Data: {filters.data}"
    elif filters.date_from and filters.date_from[5:] == "01-01" and filters.date_to[5:] == "12-31":
        period = f"📅 Período: ano {filters.date_from[:4]}"
    elif filters.date_from:
        period = f"📅 Período: {filters.date_from[5:7]}/{filters.date_from[:4]}"
    else:
        period = "📅 sem filtro de data"
    rows = [
        (f"💰 Valor: R$ {filters.valor_exato:.2f}" if filters.valor_exato is not None else "💰 sem filtro de valor"),
        period,
        (f"🏦 Conta: {escape_markdown(filters.conta)}" if filters.conta else "🏦 sem filtro de conta"),
        (f"📂 Categoria: {escape_markdown(filters.categoria)}" if filters.categoria else "📂 sem filtro de categoria"),
        (f"💳 Pagamento (contém): {escape_markdown(filters.metodo_pagamento)}" if filters.metodo_pagamento else "💳 sem filtro de pagamento"),
        (f"📊 Natureza: {escape_markdown(filters.natureza)}" if filters.natureza else "📊 sem filtro de natureza"),
        (
            "↕️ Tipo: " + ("despesas" if filters.tipo_transacao == "saida" else "receitas")
            if filters.tipo_transacao
            else "↕️ sem filtro de tipo"
        ),
    ]
    return [f"▫️ {row}" for row in rows]


def _delete_record_lines(registro):
    descricao = _field(registro.get("descricao"), _PREVIEW_FIELD_MAX, "Sem descrição")
    categoria = _field(registro.get("categoria"), _PREVIEW_FIELD_MAX, "Sem categoria")
    conta = _field(registro.get("conta"), _PREVIEW_FIELD_MAX, "Sem conta")
    pagamento = _field(registro.get("metodo_pagamento"), _PREVIEW_FIELD_MAX, "Sem pagamento")
    data = _field(registro.get("data"), 10, "Sem data")
    return f"▪️ {data} | {_format_currency(registro.get('valor'))} | {descricao}\n   {categoria} · {conta} · {pagamento}\n"


def formatar_previa_exclusao(filters, registros: List[Dict[str, Any]]):
    """Confirmation text for a deletion: applied filters, faithful total and a bounded sample.

    The count is always the full set; only the detail is a sample, and the text says so.
    The sample shrinks if needed so the message always fits a Telegram message.
    """
    total = len(registros)
    if total == 0:
        return "❌ Nenhum registro encontrado com esses critérios para exclusão."

    plural = "registro" if total == 1 else "registros"
    head = (
        "⚠️ **ATENÇÃO: EXCLUSÃO DE DADOS**\n"
        f"Encontrei {total} {plural} para apagar.\n\n"
        "🔎 **Filtros aplicados:**\n" + "\n".join(_delete_filter_lines(filters)) + "\n\n"
    )

    def build(shown):
        body = "📝 **Registros:**\n" + "".join(_delete_record_lines(r) for r in registros[:shown])
        if shown < total:
            body += f"\n(amostra de {shown} de {total}; e mais {total - shown} não exibidos)\n"
            confirm = f"\n🛑 Confirmar apaga os {total} registros, inclusive os não exibidos. Isso é permanente."
        else:
            confirm = f"\n🛑 Confirmar apaga {'o' if total == 1 else 'os'} {total} {plural}. Isso é permanente."
        return head + body + confirm

    shown = min(DELETE_PREVIEW_SAMPLE, total)
    text = build(shown)
    while len(text) > TELEGRAM_MESSAGE_LIMIT and shown > 0:
        shown -= 1
        text = build(shown)
    return text
