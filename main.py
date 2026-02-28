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
from datetime import datetime
from pythonjsonlogger import jsonlogger

# ==========================================
# OBSERVABILIDADE: JSON Logging Estruturado para GCP
# ==========================================
logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(message)s %(module)s')
logHandler.setFormatter(formatter)
logger = logging.getLogger(__name__)
logger.addHandler(logHandler)
logger.setLevel(logging.INFO)

# ==========================================
# CONFIGURAÇÕES E SEGURANÇA (AppSec)
# ==========================================
app = Flask(__name__)

REQUIRED_VARS = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_SECRET_TOKEN", "SUPABASE_URL", "SUPABASE_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY"]
for var in REQUIRED_VARS:
    if not os.environ.get(var):
        logger.critical({"event": "startup_failed", "reason": f"Missing variable {var}"})
        raise RuntimeError(f"AppSec Fatal Error: Variável de ambiente {var} não configurada.")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
SECRET_TOKEN = os.environ.get("TELEGRAM_SECRET_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

try:
    supabase: Client = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
    groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    deepseek_client = OpenAI(api_key=os.environ.get("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com")
    logger.info({"event": "clients_initialized", "status": "success"})
except Exception as e:
    logger.critical({"event": "init_error", "error": str(e), "trace": traceback.format_exc()})
    raise

# ==========================================
# FUNÇÕES DE INFRAESTRUTURA E MOTOR TEMPORAL
# ==========================================
def enviar_mensagem_telegram(chat_id, texto):
    try:
        url = f"{TELEGRAM_API_URL}/sendMessage"
        payload = {"chat_id": chat_id, "text": texto, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.error({"event": "telegram_send_fail", "chat_id": chat_id, "error": str(e)})

def baixar_audio_telegram(file_id):
    url_info = f"{TELEGRAM_API_URL}/getFile?file_id={file_id}"
    resp = requests.get(url_info, timeout=10).json()
    if not resp.get("ok"): return None
    download_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{resp['result']['file_path']}"
    return requests.get(download_url, timeout=15).content

def transcrever_audio(audio_bytes):
    tmp_path = f"/tmp/audio_{datetime.now().timestamp()}.ogg"
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

def add_months_safely(sourcedate, months):
    """Soma meses com segurança sem quebrar no dia 31 (ex: 31 Jan -> 28 Fev)"""
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(year, month)[1])
    return sourcedate.replace(year=year, month=month, day=day)

# ==========================================
# MOTOR COGNITIVO (Intent Router & Strict Enum)
# ==========================================
def processar_texto_com_llm(texto_usuario):
    data_atual = datetime.now().strftime("%Y-%m-%d")
    mes_atual = datetime.now().strftime("%m")
    ano_atual = datetime.now().strftime("%Y")

    system_prompt = f"""
    Você é um Copilot Financeiro autônomo. 
    CONTEXTO TEMPORAL INJETADO: Hoje é {data_atual} (Mês: {mes_atual}, Ano: {ano_atual}). Use isso para deduzir termos como "este mês", "hoje", "ontem".

    <diretriz_de_intencao>
    Determine se o usuário quer:
    1. "registrar" (adicionar um novo gasto/receita).
    2. "consultar" (saber quanto gastou, buscar histórico).
    3. "excluir" (apagar dados incorretos).
    </diretriz_de_intencao>

    <regras_de_categoria_estrita_anti_alucinacao>
    Você está PROIBIDO de inventar categorias. Para registros, use EXATAMENTE UMA destas:
    - Essencial: "Moradia", "Mercado", "Transporte", "Saúde", "Educação", "Contas Fixas"
    - Lazer: "Bares e Restaurantes", "Delivery e Fast Food", "Bebidas alcóolicas", "Viagens", "Diversão", "Vestuário", "Cuidados Pessoais"
    - Receita: "Salário", "Investimentos", "Cashback", "Entradas Diversas"
    - Fallback: "Outros" (Use APENAS se não encaixar em nada acima).
    </regras_de_categoria_estrita_anti_alucinacao>

    <regras_de_contexto_negocio>
    - Civic LXL e Golf Generation 1.6 = "Transporte" (Essencial).
    - Ifood, hambúrgueres, doces, pizzas = "Delivery e Fast Food" (Lazer).
    - Vinho tinto meio seco, cerveja = "Bebidas alcóolicas" (Lazer).
    - Santo Antônio do Pinhal, Socorro, Monte Verde, Camanducaia = "Viagens" (Lazer).
    - Steam, For The King 2, Slay the Spire = "Diversão" (Lazer).
    - Apelidos de banco: "roxinho" = Nubank, "laranjinha" = Itaú.
    </regras_de_contexto_negocio>

    <formato_de_saida>
    Retorne EXCLUSIVAMENTE este JSON:
    {{
      "intencao": "registrar" | "consultar" | "excluir",
      "raciocinio_interno": "Justifique a intenção e, se for registro, as categorias baseando-se nas regras.",
      
      // PREENCHA APENAS SE INTENÇÃO FOR 'registrar'
      "dados_registro": {{
        "valor_total": float (o valor TOTAL da compra, positivo absoluto),
        "parcelas": int (1 para à vista, N para parcelamentos),
        "natureza": "Essencial" | "Lazer" | "Receita",
        "categoria": "Uma da lista estrita",
        "descricao": "Resumo em 5 palavras",
        "metodo_pagamento": "Pix" | "Cartão de Crédito" | "Cartão de Débito" | "Dinheiro" | "Outros",
        "conta": "Instituição"
      }},

      // PREENCHA APENAS SE INTENÇÃO FOR 'consultar' OU 'excluir'
      "filtros_pesquisa": {{
        "mes": "MM" (ex: "02"),
        "ano": "YYYY" (ex: "2026"),
        "categoria": "Filtro de categoria (ou null)",
        "conta": "Filtro de conta (ou null)"
      }},
      
      // PREENCHA APENAS SE INTENÇÃO FOR 'excluir'
      "confirmacao_massa": boolean (True APENAS se o usuário disse explicitamente "Confirmo exclusão em massa" ou "Confirmar exclusão")
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
# DATA LAYER (Banco de Dados & Matemática Pythonica)
# ==========================================
def aplicar_filtros_query(query_obj, filtros):
    if not filtros: return query_obj
    if filtros.get("categoria"): query_obj = query_obj.eq("categoria", filtros["categoria"])
    if filtros.get("conta"): query_obj = query_obj.eq("conta", filtros["conta"])
    if filtros.get("mes") and filtros.get("ano"):
        data_inicio = f"{filtros['ano']}-{filtros['mes']}-01"
        data_fim = f"{filtros['ano']}-{filtros['mes']}-31" 
        query_obj = query_obj.gte("data", data_inicio).lte("data", data_fim)
    return query_obj

def inserir_no_banco(dados_reg):
    payload_audit = {k: v for k, v in dados_reg.items() if k != "raciocinio_interno"}
    logger.info({"event": "db_insert_attempt", "payload": payload_audit})
    
    # 1. Extração Segura dos Números
    valor_total = float(dados_reg.get("valor_total", 0.0))
    parcelas = int(dados_reg.get("parcelas", 1))
    if parcelas < 1: parcelas = 1
    
    # 2. Matemática Exata (Evitando sumiço de centavos)
    valor_base = round(valor_total / parcelas, 2)
    valor_ultima = round(valor_total - (valor_base * (parcelas - 1)), 2)
    
    data_atual = datetime.utcnow()
    registros_em_lote = []
    
    # 3. Geração das Linhas no Tempo
    for i in range(parcelas):
        valor_parcela = valor_ultima if i == (parcelas - 1) else valor_base
        data_parcela = add_months_safely(data_atual, i).strftime("%Y-%m-%d")
        
        desc = dados_reg.get("descricao", "Sem descrição")
        if parcelas > 1:
            desc = f"{desc} [{i+1}/{parcelas}]"
            
        registro = {
            "data": data_parcela,
            "valor": valor_parcela,
            "natureza": dados_reg.get("natureza", "Outros"),
            "categoria": dados_reg.get("categoria", "Outros"),
            "descricao": desc,
            "metodo_pagamento": dados_reg.get("metodo_pagamento", "Outros"),
            "conta": dados_reg.get("conta", "Não Informada")
        }
        registros_em_lote.append(registro)
        
    # 4. Inserção em Massa Transacional
    try:
        supabase.table("gastos").insert(registros_em_lote).execute()
    except APIError as e:
        logger.error({"event": "db_error", "code": e.code, "message": e.message})
        raise Exception(f"Erro no Banco (Cod: {e.code}): {e.message}")

def consultar_no_banco(filtros):
    logger.info({"event": "db_select", "filters": filtros})
    query = supabase.table("gastos").select("valor, descricao")
    query = aplicar_filtros_query(query, filtros)
    resposta = query.execute()
    total = sum(item["valor"] for item in resposta.data)
    return total, len(resposta.data)

def excluir_no_banco(filtros, confirmacao_massa):
    logger.info({"event": "db_delete_attempt", "filters": filtros, "confirmed": confirmacao_massa})
    
    query_check = supabase.table("gastos").select("id", count="exact")
    query_check = aplicar_filtros_query(query_check, filtros)
    qtd_afetada = query_check.execute().count
    
    if qtd_afetada == 0:
        return 0, "Nenhum registro encontrado para estes filtros."
    
    if qtd_afetada > 20 and not confirmacao_massa:
        return qtd_afetada, "⚠️ *Trava de Segurança Ativada!*\nSua ordem afeta mais de 20 registros. Para autorizar, envie o áudio novamente com a frase exata: _'Confirmo exclusão em massa'_."
    
    query_del = supabase.table("gastos").delete()
    query_del = aplicar_filtros_query(query_del, filtros)
    query_del.execute()
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
        if "voice" in message:
            enviar_mensagem_telegram(chat_id, "⏳ *Analisando sua solicitação...*")
            audio_bytes = baixar_audio_telegram(message["voice"]["file_id"])
            texto_analise = transcrever_audio(audio_bytes)
        elif "text" in message:
            texto_analise = message["text"]
        else:
            return jsonify({"status": "ok"}), 200

        analise_ia = processar_texto_com_llm(texto_analise)
        intencao = analise_ia.get("intencao")
        pensamento = analise_ia.get("raciocinio_interno", "")
        logger.info({"event": "intent_routed", "intent": intencao})

        # FLUXO 1: REGISTRAR (C/ Lógica de Parcelamento)
        if intencao == "registrar":
            dados_reg = analise_ia.get("dados_registro", {})
            inserir_no_banco(dados_reg)
            
            val_total = float(dados_reg.get("valor_total", 0.0))
            parcelas = int(dados_reg.get("parcelas", 1))
            val_str = f"R$ {val_total:,.2f}" + (f" (em {parcelas}x)" if parcelas > 1 else "")
            
            msg = (f"✅ **Salvo!**\n💰 {val_str} | 📊 {dados_reg.get('natureza')}\n"
                   f"📂 Categoria: {dados_reg.get('categoria')}\n"
                   f"🏦 {dados_reg.get('conta')} ({dados_reg.get('metodo_pagamento')})\n"
                   f"📝 {dados_reg.get('descricao')}\n\n🧠 *Lógica:* _{pensamento}_")
            enviar_mensagem_telegram(chat_id, msg)

        # FLUXO 2: CONSULTAR
        elif intencao == "consultar":
            filtros = analise_ia.get("filtros_pesquisa", {})
            total, qtd = consultar_no_banco(filtros)
            filtros_txt = ", ".join([f"{k}: {v}" for k,v in filtros.items() if v]) or "Todos"
            
            msg = (f"🔎 **Consulta Concluída**\n\n📊 **Total Gasto:** R$ {total:,.2f}\n"
                   f"📝 Registros: {qtd}\n🎛️ Filtros IA: {filtros_txt}\n\n🧠 *Lógica:* _{pensamento}_")
            enviar_mensagem_telegram(chat_id, msg)

        # FLUXO 3: EXCLUIR
        elif intencao == "excluir":
            filtros = analise_ia.get("filtros_pesquisa", {})
            confirmado = analise_ia.get("confirmacao_massa", False)
            qtd, status_msg = excluir_no_banco(filtros, confirmado)
            
            if status_msg == "excluidos":
                enviar_mensagem_telegram(chat_id, f"🗑️ **Exclusão Concluída**\n{qtd} registro(s) apagado(s).\n🧠 *Lógica:* _{pensamento}_")
            else:
                enviar_mensagem_telegram(chat_id, status_msg)
        else:
            raise Exception("Intenção não reconhecida pela IA.")

    except Exception as e:
        logger.error({"event": "system_failure", "error": str(e), "trace": traceback.format_exc()})
        enviar_mensagem_telegram(chat_id, f"❌ *Falha Sistêmica*\n⚠️ `{str(e)}`")

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))