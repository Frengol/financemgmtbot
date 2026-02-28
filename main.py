import os
import json
import logging
import requests
import traceback
import calendar
from flask import Flask, request, jsonify
from supabase import create_client, Client
from postgrest.exceptions import APIError
from openai import OpenAI
from groq import Groq
import google.generativeai as genai
from datetime import datetime, timedelta
from pythonjsonlogger import jsonlogger

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
    """AppSec: Previne vazamento de PII e tokens nos dumps de erro."""
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
# INFRAESTRUTURA E MOTOR TEMPORAL
# ==========================================
def get_brasilia_time():
    return datetime.utcnow() - timedelta(hours=3)

def enviar_mensagem_telegram(chat_id, texto):
    try:
        url = f"{TELEGRAM_API_URL}/sendMessage"
        payload = {"chat_id": chat_id, "text": texto, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.error({"event": "telegram_send_fail", "chat_id": chat_id, "error": mascarar_segredos(str(e))})

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

def extrair_tabela_recibo_gemini(image_bytes):
    model = genai.GenerativeModel('gemini-2.5-flash')
    prompt_visao = "Atue como um extrator de dados. Converta os itens comprados neste recibo em uma tabela Markdown estrita com as colunas: [Nome do Produto] | [Valor Total do Item]. Ignore cabeçalhos, CNPJ, troco, descontos totais e métodos de pagamento. Retorne APENAS a tabela."
    response = model.generate_content([{"mime_type": "image/jpeg", "data": image_bytes}, prompt_visao])
    return response.text

def add_months_safely(sourcedate, months):
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(year, month)[1])
    return sourcedate.replace(year=year, month=month, day=day)

# ==========================================
# SANITIZAÇÃO E ROTEAMENTO (Data Governance)
# ==========================================
def sanitizar_dados(natureza, categoria):
    """QA Guardrail: Normaliza strings e aplica o Fallback estrito para 'Outros'."""
    cat = categoria.strip().title() if categoria and isinstance(categoria, str) else "Outros"
    nat = natureza.strip().title() if natureza and isinstance(natureza, str) else "Outros"
    if nat not in ["Essencial", "Lazer", "Receita", "Outros"]:
        nat = "Outros"
    return nat, cat

def processar_texto_com_llm(texto_usuario):
    hoje_bsb = get_brasilia_time()
    
    system_prompt = f"""
    Você é um Copilot Financeiro autônomo. 
    CONTEXTO TEMPORAL INJETADO: Hoje é {hoje_bsb.strftime("%Y-%m-%d")} (Mês: {hoje_bsb.strftime("%m")}, Ano: {hoje_bsb.strftime("%Y")}). Use isso para deduzir termos como "este mês", "hoje", "ontem".

    <diretriz_de_intencao>
    1. "registrar" (um único gasto/receita).
    2. "registrar_lote" (uma lista de itens via cupom fiscal).
    3. "consultar" (saber quanto gastou, buscar histórico).
    4. "excluir" (apagar dados incorretos).
    </diretriz_de_intencao>

    <regras_de_categoria_estrita_anti_alucinacao>
    Você está PROIBIDO de inventar categorias. Use EXATAMENTE UMA destas:
    - Essencial: "Moradia", "Mercado", "Transporte", "Saúde", "Educação", "Contas Fixas"
    - Lazer: "Bares e Restaurantes", "Delivery e Fast Food", "Bebidas alcóolicas", "Viagens", "Diversão", "Vestuário", "Cuidados Pessoais"
    - Receita: "Salário", "Investimentos", "Cashback", "Entradas Diversas"
    - Fallback: "Outros".  (Use APENAS se não encaixar em nada acima).
    </regras_de_categoria_estrita_anti_alucinacao>

    <regras_de_contexto_negocio>
    - Civic LXL e Golf Generation 2003 = "Transporte" (Essencial).
    - Ifood, hambúrgueres, doces, pizzas = "Delivery e Fast Food" (Lazer).
    - Vinho tinto meio seco, cerveja = "Bebidas alcóolicas" (Lazer).
    - Santo Antônio do Pinhal, Socorro, Monte Verde, Camanducaia = "Viagens" (Lazer).
    - Steam, For The King 2, Slay the Spire = "Diversão" (Lazer).
    - Apelidos de banco: "roxinho" = Nubank, "laranjinha" = Itaú.
    </regras_de_contexto_negocio>

    <formato_de_saida>
    Retorne EXCLUSIVAMENTE este JSON:
    {{
      "intencao": "registrar" | "registrar_lote" | "consultar" | "excluir",
      "raciocinio_interno": "Justifique a intenção.",
      
      "dados_registro": {{
        "valor_total": float, "parcelas": int, "natureza": "...", "categoria": "...",
        "descricao": "Resumo", "metodo_pagamento": "...", "conta": "Nome do banco, 'Carteira', ou 'Não Informada'"
      }},

      "dados_lote": {{
        "metodo_pagamento": "...", "conta": "Nome do banco, 'Carteira', ou 'Não Informada'",
        "itens": [ {{ "nome": "Item", "valor": float, "natureza": "...", "categoria": "..." }} ]
      }},

      "filtros_pesquisa": {{ "mes": "MM", "ano": "YYYY", "categoria": "...", "conta": "..." }},
      "confirmacao_massa": boolean
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
# DATA LAYER & MAP-REDUCE
# ==========================================
def agrupar_inserir_lote(dados_lote):
    itens = dados_lote.get("itens", [])
    if not itens: return 0, 0.0
    
    conta = dados_lote.get("conta", "Não Informada")
    metodo = dados_lote.get("metodo_pagamento", "Outros")
    
    grupos = {}
    total_geral = 0.0
    
    for item in itens:
        nat_limpa, cat_limpa = sanitizar_dados(item.get("natureza"), item.get("categoria"))
        val = float(item.get("valor") or 0.0)
        nome = item.get("nome", "Item Desconhecido")
        
        chave_grupo = (nat_limpa, cat_limpa)
        if chave_grupo not in grupos:
            grupos[chave_grupo] = {"valor": 0.0, "nomes": []}
        
        grupos[chave_grupo]["valor"] += val
        grupos[chave_grupo]["nomes"].append(nome)
        total_geral += val

    data_atual = get_brasilia_time().strftime("%Y-%m-%d")
    registros_em_lote = []
    
    for (nat, cat), info in grupos.items():
        qtd_nomes = len(info["nomes"])
        nomes_str = ", ".join(info["nomes"][:3])
        desc = f"{nomes_str} e +{qtd_nomes-3} itens (Cupom)" if qtd_nomes > 3 else f"{nomes_str} (Cupom)"
        
        registros_em_lote.append({
            "data": data_atual, "valor": round(info["valor"], 2), "natureza": nat, "categoria": cat,
            "descricao": desc[:250], "metodo_pagamento": metodo, "conta": conta
        })
        
    try:
        supabase.table("gastos").insert(registros_em_lote).execute()
        # Happy Path Logging (Lean)
        logger.info({"event": "db_bulk_insert_success", "items_grouped": len(registros_em_lote), "total_value": total_geral})
        return len(registros_em_lote), total_geral
    except APIError as e:
        # Error Path Logging (Deep Dump da variável que quebrou)
        logger.error({"event": "db_error_bulk_insert", "code": e.code, "message": e.message, "dump_payload": registros_em_lote})
        raise Exception(f"Erro no Banco (Cod: {e.code}): {e.message}")

def inserir_no_banco(dados_reg):
    nat_limpa, cat_limpa = sanitizar_dados(dados_reg.get("natureza"), dados_reg.get("categoria"))
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
    if filtros.get("categoria"): query_obj = query_obj.eq("categoria", filtros["categoria"])
    if filtros.get("conta"): query_obj = query_obj.eq("conta", filtros["conta"])
    if filtros.get("mes") and filtros.get("ano"):
        ano, mes = int(filtros["ano"]), int(filtros["mes"])
        ultimo_dia = calendar.monthrange(ano, mes)[1]
        query_obj = query_obj.gte("data", f"{ano}-{mes:02d}-01").lte("data", f"{ano}-{mes:02d}-{ultimo_dia:02d}")
    return query_obj

def consultar_no_banco(filtros):
    query = supabase.table("gastos").select("valor, descricao")
    resposta = aplicar_filtros_query(query, filtros).execute()
    return sum(item["valor"] for item in resposta.data), len(resposta.data)

def excluir_no_banco(filtros, confirmacao_massa):
    query_check = supabase.table("gastos").select("id", count="exact")
    qtd_afetada = aplicar_filtros_query(query_check, filtros).execute().count
    
    if qtd_afetada == 0: return 0, "Nenhum registro encontrado."
    if qtd_afetada > 20 and not confirmacao_massa:
        return qtd_afetada, "⚠️ *Trava de Segurança Ativada!*\nMais de 20 registros. Confirme com: _'Confirmo exclusão em massa'_."
    
    query_del = supabase.table("gastos").delete()
    aplicar_filtros_query(query_del, filtros).execute()
    return qtd_afetada, "excluidos"

# ==========================================
# WEBHOOK CONTROLLER (Gateway Principal)
# ==========================================
@app.route("/", methods=["POST"])
def telegram_webhook():
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != SECRET_TOKEN:
        return jsonify({"error": "Unauthorized"}), 403

    update = request.get_json()
    if not update or "message" not in update: return jsonify({"status": "ignored"}), 200

    message = update["message"]
    chat_id = message["chat"]["id"]
    
    try:
        texto_analise = ""
        # Processamento Multimodal (Pipeline 2 Estágios)
        if "photo" in message:
            enviar_mensagem_telegram(chat_id, "👁️ *Lendo cupom fiscal...*")
            foto_id = message["photo"][-1]["file_id"]
            img_bytes = baixar_arquivo_telegram(foto_id)
            tabela_md = extrair_tabela_recibo_gemini(img_bytes)
            texto_analise = f"Contexto do usuário: {message.get('caption', '')}\n\nNota Fiscal:\n{tabela_md}"
            
        elif "voice" in message:
            enviar_mensagem_telegram(chat_id, "⏳ *Ouvindo...*")
            texto_analise = transcrever_audio(baixar_arquivo_telegram(message["voice"]["file_id"]))
        elif "text" in message:
            texto_analise = message["text"]
        else:
            return jsonify({"status": "ok"}), 200

        analise_ia = processar_texto_com_llm(texto_analise)
        intencao = analise_ia.get("intencao")
        
        if intencao == "registrar":
            dados_reg = analise_ia.get("dados_registro", {})
            inserir_no_banco(dados_reg)
            val_total = float(dados_reg.get("valor_total") or 0.0)
            msg = f"✅ **Salvo!**\n💰 R$ {val_total:,.2f} | 📊 {dados_reg.get('categoria')}\n🏦 {dados_reg.get('conta')}"
            enviar_mensagem_telegram(chat_id, msg)

        elif intencao == "registrar_lote":
            dados_lote = analise_ia.get("dados_lote", {})
            linhas_geradas, soma_total = agrupar_inserir_lote(dados_lote)
            msg = f"🧾 **Cupom Agrupado!**\n📊 **Total:** R$ {soma_total:,.2f}\n📝 Registros: {linhas_geradas}"
            enviar_mensagem_telegram(chat_id, msg)

        elif intencao == "consultar":
            filtros = analise_ia.get("filtros_pesquisa", {})
            total, qtd = consultar_no_banco(filtros)
            msg = f"🔎 **Consulta**\n📊 **Total:** R$ {total:,.2f}\n📝 Registros: {qtd}"
            enviar_mensagem_telegram(chat_id, msg)

        elif intencao == "excluir":
            filtros = analise_ia.get("filtros_pesquisa", {})
            confirmado = analise_ia.get("confirmacao_massa", False)
            qtd, status_msg = excluir_no_banco(filtros, confirmado)
            msg = f"🗑️ **Exclusão**\n{qtd} apagados." if status_msg == "excluidos" else status_msg
            enviar_mensagem_telegram(chat_id, msg)
        else:
            raise Exception("Intenção não reconhecida.")

    except Exception as e:
        erro_tratado = mascarar_segredos(traceback.format_exc())
        # Error Path Logging (Deep Dump geral)
        logger.error({"event": "system_failure", "error": str(e), "traceback": erro_tratado})
        enviar_mensagem_telegram(chat_id, f"❌ *Falha Sistêmica*\n⚠️ `{str(e)}`")

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))