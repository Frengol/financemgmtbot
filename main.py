import os
import json
import logging
import requests
import traceback
import calendar
import random
import string
import math
from flask import Flask, request, jsonify
from supabase import create_client, Client
from postgrest.exceptions import APIError
from openai import OpenAI
from groq import Groq
import google.generativeai as genai
from datetime import datetime, timedelta
from pythonjsonlogger import jsonlogger
from collections import defaultdict

# ==========================================
# OBSERVABILIDADE E APPSEC: Logging e Mascaramento
# ==========================================
logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(message)s %(module)s')
logHandler.setFormatter(formatter)
logger = logging.getLogger(__name__)
logger.addHandler(logHandler)
logger.setLevel(logging.INFO)

app = Flask(__name__)

REQUIRED_VARS = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_SECRET_TOKEN", "SUPABASE_URL", "SUPABASE_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY"]
for var in REQUIRED_VARS:
    if not os.environ.get(var):
        logger.critical({"event": "startup_failed", "reason": f"Missing variable {var}"})
        raise RuntimeError(f"AppSec Fatal Error: Variável de ambiente {var} não configurada.")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
SECRET_TOKEN = os.environ.get("TELEGRAM_SECRET_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

def mascarar_segredos(texto):
    if not isinstance(texto, str): return texto
    return texto.replace(TELEGRAM_TOKEN, "[MASKED_BOT_TOKEN]").replace(SECRET_TOKEN, "[MASKED_SECRET]")

try:
    supabase: Client = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
    groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    deepseek_client = OpenAI(api_key=os.environ.get("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com")
    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
    logger.info({"event": "clients_initialized", "status": "success"})
except Exception as e:
    logger.critical({"event": "init_error", "error": mascarar_segredos(str(e))})
    raise

# ==========================================
# MAPEAMENTO DETERMINÍSTICO E CANÓNICO (Golden Source)
# ==========================================
CATEGORIA_MAP = {
    # Essencial
    "moradia": ("Essencial", "Moradia"), 
    "mercado": ("Essencial", "Mercado"), 
    "transporte": ("Essencial", "Transporte"),
    "saúde": ("Essencial", "Saúde"), 
    "educação": ("Essencial", "Educação"), 
    "contas fixas": ("Essencial", "Contas Fixas"),
    "cuidados pessoais": ("Essencial", "Cuidados Pessoais"),
    # Lazer
    "bares e restaurantes": ("Lazer", "Bares e Restaurantes"), 
    "delivery e fast food": ("Lazer", "Delivery e Fast Food"), 
    "bebidas alcoólicas": ("Lazer", "Bebidas Alcoólicas"), 
    "viagens": ("Lazer", "Viagens"), 
    "diversão": ("Lazer", "Diversão"), 
    "vestuário": ("Lazer", "Vestuário"),
    # Receita
    "salário": ("Receita", "Salário"), 
    "investimentos": ("Receita", "Investimentos"), 
    "cashback": ("Receita", "Cashback"), 
    "entradas diversas": ("Receita", "Entradas Diversas")
}

def inferir_natureza(categoria):
    """Garante 100% de precisão cruzando e formatando Categoria -> Natureza via dicionário Canônico."""
    if not categoria or not isinstance(categoria, str):
        return "Outros", "Outros"
    chave_busca = categoria.strip().lower()
    if chave_busca not in CATEGORIA_MAP:
        return "Outros", categoria.strip().title()
    return CATEGORIA_MAP[chave_busca]

# ==========================================
# INFRAESTRUTURA E COMUNICAÇÃO
# ==========================================
def get_brasilia_time():
    return datetime.utcnow() - timedelta(hours=3)

def enviar_mensagem_telegram(chat_id, texto, reply_markup=None):
    try:
        url = f"{TELEGRAM_API_URL}/sendMessage"
        payload = {"chat_id": chat_id, "text": texto, "parse_mode": "Markdown"}
        if reply_markup: payload["reply_markup"] = reply_markup
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.error({"event": "telegram_send_fail", "error": mascarar_segredos(str(e))})

def editar_mensagem_telegram(chat_id, message_id, texto, reply_markup=None):
    try:
        url = f"{TELEGRAM_API_URL}/editMessageText"
        payload = {"chat_id": chat_id, "message_id": message_id, "text": texto, "parse_mode": "Markdown"}
        if reply_markup: payload["reply_markup"] = reply_markup
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.error({"event": "telegram_edit_fail", "error": mascarar_segredos(str(e))})

def baixar_arquivo_telegram(file_id):
    url_info = f"{TELEGRAM_API_URL}/getFile?file_id={file_id}"
    resp = requests.get(url_info, timeout=10).json()
    if not resp.get("ok"): return None
    download_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{resp['result']['file_path']}"
    return requests.get(download_url, timeout=15).content

def transcrever_audio(audio_bytes):
    tmp_path = f"/tmp/audio_{get_brasilia_time().timestamp()}.ogg"
    with open(tmp_path, "wb") as f: f.write(audio_bytes)
    try:
        with open(tmp_path, "rb") as file:
            transcription = groq_client.audio.transcriptions.create(
                file=(tmp_path, file.read()),
                model="whisper-large-v3",
                prompt="Transcreva este áudio em português sobre finanças, fast food, mercado, faturas e parcelamentos."
            )
        return transcription.text
    finally:
        if os.path.exists(tmp_path): os.remove(tmp_path)

# ==========================================
# MOTORES DE IA (VISÃO E LÓGICA)
# ==========================================
def extrair_tabela_recibo_gemini(image_bytes):
    model = genai.GenerativeModel('gemini-2.5-flash')
    prompt_visao = """
    Atue como um extrator de dados. Extraia a tabela de itens comprados. 
    Colunas obrigatórias: [Nome do Produto] | [Valor Bruto] | [Desconto do Item]. 
    Se não houver desconto no item, use 0.00. Não confunda quantidade com desconto.
    
    Abaixo da tabela, escreva duas linhas estritas:
    Desconto Global: [Apenas o valor numérico do desconto final da nota. Diferencie de subtotais! Subtotal NÃO é desconto. Procure palavras como "Desconto", "Desconto total". Se não houver, escreva 0.00]
    Pagamento: [Infira o método lendo a nota inteira: Pix, Crédito, Débito, Dinheiro, Vale Alimentação. Se impossível saber, escreva Não Informado]
    """
    response = model.generate_content([{"mime_type": "image/jpeg", "data": image_bytes}, prompt_visao])
    return response.text

def processar_texto_com_llm(texto_usuario):
    hoje_bsb = get_brasilia_time()
    
    system_prompt = f"""
    Você é um Copilot Financeiro autônomo. 
    CONTEXTO TEMPORAL INJETADO: Hoje é {hoje_bsb.strftime("%Y-%m-%d")} (Mês: {hoje_bsb.strftime("%m")}, Ano: {hoje_bsb.strftime("%Y")}). Use isso para deduzir termos como "este mês", "hoje", "ontem".

    <diretriz_de_intencao>
    1. "registrar" (um único gasto/receita manual).
    2. "registrar_lote_pendente" (uma lista de itens via cupom fiscal, requer aprovação).
    3. "salvar_edicao_cupom" (se o texto do usuário iniciar com "--CUPOM_EDIT--", salva direto).
    4. "consultar" (saber quanto gastou, buscar histórico por natureza ou categoria). NÃO deduza mês ou ano a menos que explicitamente pedido.
    5. "excluir" (apagar dados incorretos ou em massa). Se o usuário pedir para apagar, tente preencher `filtros_exclusao` com o MÁXIMO de detalhes que ele der.
    </diretriz_de_intencao>

    <regras_de_categoria_estrita_anti_alucinacao>
    Você está PROIBIDO de inventar categorias. Use EXATAMENTE UMA destas:
    - Essencial: "Moradia", "Mercado", "Transporte", "Saúde", "Educação", "Contas Fixas", "Cuidados Pessoais"
    - Lazer: "Bares e Restaurantes", "Delivery e Fast Food", "Bebidas Alcoólicas", "Viagens", "Diversão", "Vestuário"
    - Receita: "Salário", "Investimentos", "Cashback", "Entradas Diversas"
    - Fallback: "Outros". (Use APENAS se não encaixar em nada acima).
    </regras_de_categoria_estrita_anti_alucinacao>

    <regras_de_contexto_negocio>
    - Civic LXL e Golf Generation 2003 = "Transporte".
    - Ifood, hambúrgueres, doces, pizzas = "Delivery e Fast Food".
    - Mesmo se comprados num supermercado, guloseimas e itens de indulgência (Cookies, Tortas, Chocolates, Sorvetes, Salgadinhos, Doces) DEVEM ser classificados isoladamente como "Delivery e Fast Food" e NUNCA como "Mercado".
    - Vinho tinto meio seco, cerveja = "Bebidas Alcoólicas".
    - Santo Antônio do Pinhal, Socorro, Monte Verde, Camanducaia = "Viagens".
    - Steam, For The King 2, Slay the Spire = "Diversão".
    - Apelidos de banco: "roxinho" = Nubank, "laranjinha" = Itaú.
    - Siglas de mercado: "SH" = Shampoo, "ESP" = Esponja.
    </regras_de_contexto_negocio>
    
    <regra_de_fluxo_de_caixa>
    Se o usuário perguntar por "gastos", "despesas" ou "saídas", o `tipo_transacao` é "saida".
    Se perguntar por "ganhos", "entradas", "lucros" ou "recebimentos", o `tipo_transacao` é "entrada".
    Se não ficar claro, deixe null.
    </regra_de_fluxo_de_caixa>

    <formato_de_saida>
    Retorne EXCLUSIVAMENTE este JSON (Não tente deduzir a 'natureza' no registro, o sistema fará isso via Categoria):
    {{
      "intencao": "registrar" | "registrar_lote_pendente" | "salvar_edicao_cupom" | "consultar" | "excluir",
      "raciocinio_interno": "Justifique a intenção.",
      
      "dados_registro": {{
        "valor_total": float, "parcelas": int, "categoria": "...",
        "descricao": "Resumo em 5 palavras", "metodo_pagamento": "...", "conta": "Nome do banco, 'Carteira' ou 'Não Informada'"
      }},

      "dados_lote": {{
        "metodo_pagamento": "...", "conta": "Nome do banco, 'Carteira' ou 'Não Informada'",
        "desconto_global": float (0.0 se não houver),
        "itens": [ 
           {{ "nome": "Item", "valor_bruto": float, "desconto_item": float (0.0 se não houver), "categoria": "..." }}
        ]
      }},

      "filtros_pesquisa": {{ 
         "mes": "MM" (somente se pedido expresso), 
         "ano": "YYYY" (somente se pedido expresso), 
         "natureza": "...", "categoria": "...", "conta": "...",
         "tipo_transacao": "entrada" | "saida" | null
      }},
      
      "filtros_exclusao": {{
         "mes": "MM", "ano": "YYYY", "natureza": "...", "categoria": "...", "conta": "...",
         "valor_exato": float, "metodo_pagamento": "..."
      }}
    }}
    </formato_de_saida>
    """
    
    response = deepseek_client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": texto_usuario}],
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)

# ==========================================
# LÓGICA DE NEGÓCIO: Map-Reduce e Operações DB
# ==========================================
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
    
    msg = f"🧾 **Resumo do Cupom**\n"
    msg += f"💳 Pagamento: {pagamento} ({conta})\n"
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

def gravar_lote_no_banco(dados_lote):
    grupos, total, _ = aplicar_map_reduce(dados_lote)
    if not grupos: return 0, 0.0
    
    data_atual = get_brasilia_time().strftime("%Y-%m-%d")
    registros = []
    
    for (nat, cat), info in grupos.items():
        qtd = len(info["itens_desc"])
        nomes_limpos = [i.replace("▫️ ", "").split(" (")[0] for i in info["itens_desc"]]
        nomes_str = ", ".join(nomes_limpos[:3])
        desc = f"{nomes_str} e +{qtd-3} itens (Cupom)" if qtd > 3 else f"{nomes_str} (Cupom)"
        
        registros.append({
            "data": data_atual, "valor": round(info["valor"], 2), "natureza": nat, "categoria": cat,
            "descricao": desc[:250], "metodo_pagamento": dados_lote.get("metodo_pagamento", "Outros"),
            "conta": dados_lote.get("conta", "Não Informada")
        })
        
    try:
        supabase.table("gastos").insert(registros).execute()
        logger.info({"event": "db_bulk_insert_success", "items_grouped": len(registros), "total_value": total})
        return len(registros), total
    except APIError as e:
        logger.error({"event": "db_error_bulk_insert", "code": e.code, "message": e.message, "dump_payload": registros})
        raise Exception(f"Erro no Banco (Cod: {e.code}): {e.message}")

def add_months_safely(sourcedate, months):
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(year, month)[1])
    return sourcedate.replace(year=year, month=month, day=day)

def inserir_no_banco(dados_reg):
    nat_limpa, cat_limpa = inferir_natureza(dados_reg.get("categoria"))
    valor_total = float(dados_reg.get("valor_total") or 0.0)
    parcelas = max(int(dados_reg.get("parcelas") or 1), 1)
    
    valor_base = round(valor_total / parcelas, 2)
    valor_ultima = round(valor_total - (valor_base * (parcelas - 1)), 2)
    
    data_atual = get_brasilia_time()
    registros_em_lote = []
    
    for i in range(parcelas):
        valor_parcela = valor_ultima if i == (parcelas - 1) else valor_base
        data_parcela = add_months_safely(data_atual, i).strftime("%Y-%m-%d")
        desc = dados_reg.get("descricao", "Sem descrição")
        if parcelas > 1: desc = f"{desc} [{i+1}/{parcelas}]"
            
        registros_em_lote.append({
            "data": data_parcela, "valor": valor_parcela, "natureza": nat_limpa, "categoria": cat_limpa,
            "descricao": desc, "metodo_pagamento": dados_reg.get("metodo_pagamento", "Outros"),
            "conta": dados_reg.get("conta", "Não Informada")
        })
        
    try:
        supabase.table("gastos").insert(registros_em_lote).execute()
        logger.info({"event": "db_insert_success", "installments": parcelas})
    except APIError as e:
        logger.error({"event": "db_error_insert", "code": e.code, "message": e.message, "dump_payload": registros_em_lote})
        raise Exception(f"Erro no Banco: {e.message}")

def aplicar_filtros_query(query_obj, filtros):
    query_obj = query_obj.gte("valor", 0)
    if not filtros: return query_obj
    
    # 1. Trava da Vírgula (Anti-arraying)
    raw_cat = filtros.get("categoria")
    if raw_cat and "," in raw_cat:
        raw_cat = None
        
    # 2. Sanitização Estrita de Natureza
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
        # match insensível (ilike) para métodos de pagamento para dar margem de manobra (ex: "pix" vs "Pix")
        query_obj = query_obj.ilike("metodo_pagamento", f"%{filtros['metodo_pagamento']}%")
        
    # 3. Roteador de Fluxo de Caixa (Cashflow Logic)
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

def formatar_relatorio_exclusao(registros):
    total_regs = len(registros)
    if total_regs == 0:
        return "❌ Nenhum registro encontrado com esses critérios para exclusão."
        
    msg = f"⚠️ **ATENÇÃO: EXCLUSÃO DE DADOS**\n"
    msg += f"Encontrei {total_regs} registro(s) correspondente(s):\n\n"
    
    if total_regs <= 10:
        # Relatório Completo (Detailed)
        for r in registros:
            data_formatada = r.get("data", "Sem data")
            msg += f"▫️ *{data_formatada}* | R$ {r['valor']:.2f}\n"
            msg += f"   {r['natureza']} > {r['categoria']}\n"
            msg += f"   💳 {r.get('metodo_pagamento','?')} ({r.get('conta', '?')})\n"
            msg += f"   📝 {r.get('descricao', 'Sem descrição')[:30]}...\n\n"
    else:
        # Relatório Agrupado (Grouped by Date)
        agrupamento = defaultdict(list)
        for r in registros:
            agrupamento[r.get("data", "Sem data")].append(r)
            
        for data, itens in list(agrupamento.items())[:5]: # Mostra max 5 datas diferentes para não explodir msg
            msg += f"📅 **{data}** ({len(itens)} itens)\n"
            for r in itens[:3]: # Mostra max 3 exemplos por data
                msg += f"   ▫️ {r['natureza']} > {r['categoria']} | R$ {r['valor']:.2f}\n"
            if len(itens) > 3:
                msg += f"   ... e mais {len(itens)-3} itens.\n"
            msg += "\n"
        if len(agrupamento) > 5:
            msg += f"*(E itens em outras {len(agrupamento)-5} datas...)*\n"
            
    msg += "\n🛑 **Tem a certeza absoluta que deseja APAGAR isto permanentemente?**"
    return msg

def iniciar_fluxo_exclusao(chat_id, filtros_exclusao):
    # 1. Trava de Filtro Vazio (Zero-Trust)
    # Remove valores nulos, strings vazias ou zero (mas aceita 0 de valor_exato se for intencional, porem improvavel)
    filtros_validos = {k: v for k, v in filtros_exclusao.items() if v}
    if not filtros_validos:
        enviar_mensagem_telegram(chat_id, "⚠️ **Operação Recusada.**\nNão posso apagar a base inteira sem filtros! Diga-me o valor exato, a data, a categoria ou o método de pagamento da transação que deseja excluir.")
        return

    # 2. Busca Prévia (Dry-Run Select)
    query_select = supabase.table("gastos").select("id, data, valor, natureza, categoria, descricao, metodo_pagamento, conta")
    resposta = aplicar_filtros_query(query_select, filtros_exclusao).execute()
    
    registros = resposta.data
    if not registros:
        enviar_mensagem_telegram(chat_id, "🔎 Não encontrei nenhum gasto com essas características para apagar.")
        return
        
    ids_para_apagar = [r["id"] for r in registros]
    
    # 3. Cache Stateless
    cache_id = "DEL_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
    supabase.table("cache_aprovacao").insert({"id": cache_id, "payload": {"ids": ids_para_apagar}}).execute()
    
    # 4. Formatação Dinâmica de UX
    msg_alerta = formatar_relatorio_exclusao(registros)
    
    teclado = {
        "inline_keyboard": [
            [{"text": "✅ Sim, Apagar", "callback_data": f"confirmdel_{cache_id}"}],
            [{"text": "❌ Cancelar", "callback_data": f"cancelar_{cache_id}"}]
        ]
    }
    enviar_mensagem_telegram(chat_id, msg_alerta, teclado)


# ==========================================
# WEBHOOK CONTROLLER (Gateway Principal)
# ==========================================
@app.route("/", methods=["POST"])
def telegram_webhook():
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != SECRET_TOKEN:
        return jsonify({"error": "Unauthorized"}), 403

    update = request.get_json()
    if not update: return jsonify({"status": "ignored"}), 200

    update_id = update.get("update_id")
    if update_id:
        try:
            resp_idem = supabase.table("webhook_idempotencia").select("update_id").eq("update_id", update_id).execute()
            if resp_idem.data:
                return jsonify({"status": "ignored", "reason": "duplicate"}), 200
            supabase.table("webhook_idempotencia").insert({"update_id": update_id}).execute()
        except Exception as e:
            logger.warning({"event": "idempotency_check_failed", "error": str(e)})

    try:
        if "callback_query" in update:
            cb = update["callback_query"]
            chat_id = cb["message"]["chat"]["id"]
            msg_id = cb["message"]["message_id"]
            acao_bruta = cb["data"]
            
            # Tratamento de Botões Padrão vs Exclusão
            if acao_bruta.startswith("confirmdel_"):
                acao = "confirmdel"
                cache_id = acao_bruta.split("_")[1]
            else:
                acao, cache_id = acao_bruta.split("_")
            
            requests.post(f"{TELEGRAM_API_URL}/answerCallbackQuery", json={"callback_query_id": cb["id"]})
            
            resp = supabase.table("cache_aprovacao").select("payload").eq("id", cache_id).execute()
            if not resp.data:
                editar_mensagem_telegram(chat_id, msg_id, "❌ Rascunho expirado ou já processado.")
                return jsonify({"status": "ok"}), 200
                
            payload_cache = resp.data[0]["payload"]
            
            if acao == "aprovar":
                gravar_lote_no_banco(payload_cache)
                supabase.table("cache_aprovacao").delete().eq("id", cache_id).execute()
                editar_mensagem_telegram(chat_id, msg_id, "✅ **Cupom Aprovado e Salvo!**")
                
            elif acao == "editar":
                texto_edit = gerar_texto_edicao(payload_cache)
                supabase.table("cache_aprovacao").delete().eq("id", cache_id).execute()
                editar_mensagem_telegram(chat_id, msg_id, f"📝 **MODO EDIÇÃO**\nCopie, altere as categorias/valores e envie:\n\n`{texto_edit}`")
                
            elif acao == "confirmdel":
                ids = payload_cache.get("ids", [])
                # Hard Delete utilizando array de IDs exatos garantindo que nada fora do escopo seja apagado
                supabase.table("gastos").delete().in_("id", ids).execute()
                supabase.table("cache_aprovacao").delete().eq("id", cache_id).execute()
                editar_mensagem_telegram(chat_id, msg_id, f"🗑️ **Exclusão Efetuada!** ({len(ids)} registros apagados).")
                
            elif acao == "cancelar":
                supabase.table("cache_aprovacao").delete().eq("id", cache_id).execute()
                editar_mensagem_telegram(chat_id, msg_id, "❌ **Operação Cancelada.** A base de dados não foi alterada.")
                
            return jsonify({"status": "ok"}), 200

        if "message" not in update: return jsonify({"status": "ignored"}), 200
        message = update["message"]
        chat_id = message["chat"]["id"]
        texto_analise = ""

        logger.info({"event": "webhook_received", "type": "photo" if "photo" in message else "voice" if "voice" in message else "text"})

        if "photo" in message:
            enviar_mensagem_telegram(chat_id, "👀 *Lendo cupom fiscal...*")
            foto_id = message["photo"][-1]["file_id"]
            img_bytes = baixar_arquivo_telegram(foto_id)
            tabela_md = extrair_tabela_recibo_gemini(img_bytes)
            texto_analise = f"Contexto: {message.get('caption', '')}\n\nNota Fiscal Extratada:\n{tabela_md}"
            logger.info({"event": "ocr_completed", "model": "gemini-2.5-flash"})
        elif "voice" in message:
            enviar_mensagem_telegram(chat_id, "⏳ *Ouvindo...*")
            texto_analise = transcrever_audio(baixar_arquivo_telegram(message["voice"]["file_id"]))
            logger.info({"event": "stt_completed", "model": "whisper-large-v3"})
        elif "text" in message:
            texto_analise = message["text"]
        else:
            return jsonify({"status": "ok"}), 200

        analise_ia = processar_texto_com_llm(texto_analise)
        intencao = analise_ia.get("intencao")

        logger.info({"event": "llm_routed", "intent": intencao, "payload_ia": analise_ia})

        if intencao == "registrar_lote_pendente":
            dados_lote = analise_ia.get("dados_lote", {})
            logger.info({"event": "items_extracted", "items_count": len(dados_lote.get("itens", []))})
            
            grupos, total_final, desc_global = aplicar_map_reduce(dados_lote)
            
            cache_id = "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
            supabase.table("cache_aprovacao").insert({"id": cache_id, "payload": dados_lote}).execute()
            
            logger.info({"event": "cache_created", "cache_id": cache_id})
            
            texto_resumo = gerar_mensagem_resumo(cache_id, dados_lote, grupos, total_final, desc_global)
            teclado = {
                "inline_keyboard": [
                    [{"text": "✅ Aprovar", "callback_data": f"aprovar_{cache_id}"}],
                    [{"text": "✏️ Editar", "callback_data": f"editar_{cache_id}"}, {"text": "❌ Cancelar", "callback_data": f"cancelar_{cache_id}"}]
                ]
            }
            enviar_mensagem_telegram(chat_id, texto_resumo, teclado)

        elif intencao == "salvar_edicao_cupom":
            dados_lote = analise_ia.get("dados_lote", {})
            linhas, soma = gravar_lote_no_banco(dados_lote)
            enviar_mensagem_telegram(chat_id, f"✅ **Edição Salva!**\n📊 **Total:** R$ {soma:,.2f}\n📝 Registos: {linhas}")

        elif intencao == "registrar":
            dados_reg = analise_ia.get("dados_registro", {})
            inserir_no_banco(dados_reg)
            val_total = float(dados_reg.get("valor_total") or 0.0)
            parcelas = int(dados_reg.get("parcelas") or 1)
            val_str = f"R$ {val_total:,.2f}" + (f" (em {parcelas}x)" if parcelas > 1 else "")
            
            nat_inf, cat_inf = inferir_natureza(dados_reg.get('categoria'))
            msg = (f"✅ **Salvo!**\n💰 {val_str} | 📊 {nat_inf}\n"
                   f"📂 Categoria: {cat_inf}\n"
                   f"🏦 {dados_reg.get('conta')} ({dados_reg.get('metodo_pagamento')})\n"
                   f"📝 {dados_reg.get('descricao')}")
            enviar_mensagem_telegram(chat_id, msg)

        elif intencao == "consultar":
            filtros = analise_ia.get("filtros_pesquisa", {})
            total, qtd = consultar_no_banco(filtros)
            
            f_mes = filtros.get("mes")
            f_ano = filtros.get("ano")
            
            if f_mes and f_ano:
                try:
                    str_data = f"{int(f_mes):02d}/{int(f_ano)}"
                except ValueError:
                    str_data = f"{f_mes}/{f_ano}"
            elif f_ano:
                str_data = str(f_ano)
            else:
                str_data = "Nenhum"
                
            f_cat = filtros.get("categoria")
            f_nat = filtros.get("natureza")
            f_tipo = filtros.get("tipo_transacao")
            
            if f_tipo == "saida" and not f_nat:
                msg_total = f"📊 **Total de Gastos (Saídas):** R$ {total:,.2f}\n"
            elif f_tipo == "entrada" and not f_nat:
                msg_total = f"📊 **Total de Ganhos (Entradas):** R$ {total:,.2f}\n"
            else:
                msg_total = f"📊 **Total:** R$ {total:,.2f}\n"
                
            msg = msg_total + f"📝 Registros: {qtd}\n🎛️ Filtros: {str_data}\n"
            
            if f_cat and not (f_cat and "," in f_cat): 
                nat_inferred, cat_clean = inferir_natureza(f_cat)
                msg += f"🗂️ Categoria: {cat_clean} ({nat_inferred})"
            elif f_nat:
                nat_title = f_nat.strip().title()
                if nat_title in ["Essencial", "Lazer", "Receita"]: 
                    msg += f"🗂️ Natureza: {nat_title}"
                else:
                     msg += f"🗂️ Natureza: Todas"
            else:
                msg += f"🗂️ Busca Global"
                
            enviar_mensagem_telegram(chat_id, msg)

        elif intencao == "excluir":
            # Nova UX Interativa de Segurança (Interactive Delete)
            filtros_exc = analise_ia.get("filtros_exclusao", {})
            iniciar_fluxo_exclusao(chat_id, filtros_exc)
            
        else:
            raise Exception("Intenção não reconhecida.")

    except Exception as e:
        erro_tratado = mascarar_segredos(traceback.format_exc())
        logger.error({"event": "system_failure", "error": str(e), "traceback": erro_tratado})
        enviar_mensagem_telegram(chat_id, f"❌ *Falha Sistémica*\n⚠️ `{str(e)}`")

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))