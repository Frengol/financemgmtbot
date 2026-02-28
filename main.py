import os
import json
import logging
import requests
import traceback
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
# FUNÇÕES DE INFRAESTRUTURA (FinOps & I/O)
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
                prompt="Transcreva este áudio em português sobre finanças, fast food, mercado, faturas e contas."
            )
        return transcription.text
    finally:
        if os.path.exists(tmp_path): os.remove(tmp_path)

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
    2. "consultar" (saber quanto gastou, totais, buscar histórico).
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
      "raciocinio_interno": "Justifique a intenção e, se for registro, justifique as categorias baseando-se nas regras.",
      
      // PREENCHA APENAS SE INTENÇÃO FOR 'registrar'
      "dados_registro": {{
        "valor": float (positivo absoluto),
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
# DATA LAYER (Operações de Banco com Lógica de Negócio)
# ==========================================
def aplicar_filtros_query(query_obj, filtros):
    if not filtros: return query_obj
    
    if filtros.get("categoria"):
        query_obj = query_obj.eq("categoria", filtros["categoria"])
    if filtros.get("conta"):
        query_obj = query_obj.eq("conta", filtros["conta"])
    if filtros.get("mes") and filtros.get("ano"):
        # Matemática de Range de Datas delegada ao Python/Supabase
        data_inicio = f"{filtros['ano']}-{filtros['mes']}-01"
        data_fim = f"{filtros['ano']}-{filtros['mes']}-31" 
        query_obj = query_obj.gte("data", data_inicio).lte("data", data_fim)
    
    return query_obj

def inserir_no_banco(dados_reg):
    logger.info({"event": "db_insert", "payload": dados_reg})
    registro = {
        "data": datetime.utcnow().strftime("%Y-%m-%d"),
        "valor": dados_reg.get("valor", 0.0),
        "natureza": dados_reg.get("natureza", "Outros"),
        "categoria": dados_reg.get("categoria", "Outros"),
        "descricao": dados_reg.get("descricao", ""),
        "metodo_pagamento": dados_reg.get("metodo_pagamento", "Outros"),
        "conta": dados_reg.get("conta", "Não Informada")
    }
    try:
        supabase.table("gastos").insert(registro).execute()
    except APIError as e:
        logger.error({"event": "db_error", "code": e.code, "message": e.message})
        raise Exception(f"Erro no Banco (Cod: {e.code}): {e.message}")

def consultar_no_banco(filtros):
    logger.info({"event": "db_select", "filters": filtros})
    query = supabase.table("gastos").select("valor, descricao")
    query = aplicar_filtros_query(query, filtros)
    
    resposta = query.execute()
    dados = resposta.data
    
    # Matemática no Backend (Livre de Alucinação)
    total = sum(item["valor"] for item in dados)
    quantidade = len(dados)
    return total, quantidade

def excluir_no_banco(filtros, confirmacao_massa):
    logger.info({"event": "db_delete_attempt", "filters": filtros, "confirmed": confirmacao_massa})
    
    # Dry-Run (Verifica raio de impacto antes de excluir)
    query_check = supabase.table("gastos").select("id", count="exact")
    query_check = aplicar_filtros_query(query_check, filtros)
    check_resp = query_check.execute()
    
    qtd_afetada = check_resp.count
    if qtd_afetada == 0:
        return 0, "Nenhum registro encontrado para estes filtros."
    
    # Guardrail de Arquitetura (Trava de Segurança)
    if qtd_afetada > 20 and not confirmacao_massa:
        return qtd_afetada, "⚠️ *Trava de Segurança Ativada!*\nSua ordem afeta dezenas de registros. Para autorizar, envie o áudio novamente incluindo a frase: _'Confirmo exclusão em massa'_."
    
    # Execução real da deleção
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

        # LLM Roteador
        analise_ia = processar_texto_com_llm(texto_analise)
        intencao = analise_ia.get("intencao")
        pensamento = analise_ia.get("raciocinio_interno", "")
        logger.info({"event": "intent_routed", "intent": intencao, "logic": pensamento})

        # FLUXO 1: REGISTRAR
        if intencao == "registrar":
            dados_reg = analise_ia.get("dados_registro", {})
            inserir_no_banco(dados_reg)
            msg = (f"✅ **Salvo!**\n💰 R$ {dados_reg['valor']:.2f} | 📊 {dados_reg['natureza']}\n"
                   f"📂 Categoria: {dados_reg['categoria']}\n"
                   f"🏦 {dados_reg['conta']} ({dados_reg['metodo_pagamento']})\n"
                   f"📝 {dados_reg['descricao']}\n\n🧠 *Lógica:* _{pensamento}_")
            enviar_mensagem_telegram(chat_id, msg)

        # FLUXO 2: CONSULTAR
        elif intencao == "consultar":
            filtros = analise_ia.get("filtros_pesquisa", {})
            total, qtd = consultar_no_banco(filtros)
            filtros_txt = ", ".join([f"{k}: {v}" for k,v in filtros.items() if v]) or "Todos"
            
            msg = (f"🔎 **Consulta Concluída**\n\n"
                   f"📊 **Total Gasto:** R$ {total:.2f}\n"
                   f"📝 Registros: {qtd}\n"
                   f"🎛️ Filtros IA: {filtros_txt}\n\n🧠 *Lógica:* _{pensamento}_")
            enviar_mensagem_telegram(chat_id, msg)

        # FLUXO 3: EXCLUIR
        elif intencao == "excluir":
            filtros = analise_ia.get("filtros_pesquisa", {})
            confirmado = analise_ia.get("confirmacao_massa", False)
            qtd, status_msg = excluir_no_banco(filtros, confirmado)
            
            if status_msg == "excluidos":
                enviar_mensagem_telegram(chat_id, f"🗑️ **Exclusão Concluída**\n{qtd} registro(s) apagado(s) com sucesso.\n🧠 *Lógica IA:* _{pensamento}_")
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