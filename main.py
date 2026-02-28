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

logger.info({"event": "startup", "message": "Iniciando conexão com os clientes (Supabase, Groq, DeepSeek)..."})
try:
    supabase: Client = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
    groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    deepseek_client = OpenAI(api_key=os.environ.get("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com")
    logger.info({"event": "clients_initialized", "status": "success"})
except Exception as e:
    logger.critical({"event": "init_error", "error": str(e), "trace": traceback.format_exc()})
    raise

# ==========================================
# FUNÇÕES DE INFRAESTRUTURA (FinOps & Resiliência)
# ==========================================
def enviar_mensagem_telegram(chat_id, texto):
    try:
        url = f"{TELEGRAM_API_URL}/sendMessage"
        payload = {"chat_id": chat_id, "text": texto, "parse_mode": "Markdown"}
        # FinOps: Timeout para evitar travamento da CPU
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.error({"event": "telegram_send_fail", "chat_id": chat_id, "error": str(e)})

def baixar_audio_telegram(file_id):
    url_info = f"{TELEGRAM_API_URL}/getFile?file_id={file_id}"
    resp = requests.get(url_info, timeout=10).json()
    if not resp.get("ok"):
        return None
    file_path = resp["result"]["file_path"]
    download_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
    # FinOps: Timeout estendido para download de mídia
    return requests.get(download_url, timeout=15).content

def transcrever_audio(audio_bytes):
    # Concorrência Segura: Timestamp no nome do arquivo evita colisão
    tmp_path = f"/tmp/audio_{datetime.now().timestamp()}.ogg"
    with open(tmp_path, "wb") as f:
        f.write(audio_bytes)
    
    try:
        with open(tmp_path, "rb") as file:
            transcription = groq_client.audio.transcriptions.create(
                file=(tmp_path, file.read()),
                model="whisper-large-v3",
                prompt="Transcreva este áudio em português brasileiro sobre finanças, fast food, contas e gastos."
            )
        return transcription.text
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

# ==========================================
# MOTOR COGNITIVO E REGRAS DE NEGÓCIO (PO)
# ==========================================
def processar_texto_com_llm(texto_usuario):
    system_prompt = """
    Você é um Arquiteto Financeiro autônomo de altíssima precisão. 
    Sua missão é extrair dados financeiros, pensar logicamente usando o 'raciocinio_interno' para justificar a classificação e retornar EXCLUSIVAMENTE um objeto JSON válido.

    <regras_de_classificacao>
    NATUREZA "Essencial": Gastos de sobrevivência e rotina obrigatória.
    - Inclui: Moradia, Alimentação BÁSICA (itens de supermercado, padaria comum, feira), Saúde, Transporte.
    - Contexto Veicular: Combustível, manutenção, peças ou revisões de veículos (como Civic LXL e Golf Generation 1.6) são sempre "Transporte" (Essencial).

    NATUREZA "Lazer": Desejos, hobbies, luxos e qualidade de vida.
    - Inclui: Viagens, Diversão, Vestuário, e Diversão Gastronômica.
    - Regra de Alimentação: Comidas pedidas por delivery consideradas "besteiras" (hambúrgueres, pizzas, fast food, doces, vinhos como tinto meio seco) ou refeições em restaurantes por lazer NÃO SÃO Essenciais. Classifique-as como "Lazer" -> Categoria: "Bares e Restaurantes" ou "Diversão".
    - Contexto de Viagem: Hospedagens (Pousada Canto do Sabiá, Chalés Aconchego da Serra, Chácara Pedacinho do Céu) ou gastos turísticos em Florianópolis, Monte Verde, Socorro, Santo Antônio do Pinhal ou Camanducaia são "Viagens" (Lazer).
    - Contexto de Diversão: Jogos de videogame (como For The King 2, Slay the Spire) são "Diversão" (Lazer).

    NATUREZA "Receita": Entradas de dinheiro.
    - Inclui: Salário, Vendas, Rendimentos, Cashback.
    </regras_de_classificacao>

    <regras_de_conta_e_pagamento>
    - Se o usuário mencionar apelidos (ex: "roxinho" = Nubank, "laranjinha" = Itaú, "vermelhinho" = Santander).
    - Se o pagamento for em "Dinheiro" ou "Espécie", a conta é "Carteira".
    - Se não for citado o banco/cartão, preencha com "Não Informada".
    </regras_de_conta_e_pagamento>

    <formato_de_saida>
    Você DEVE retornar o JSON com esta estrutura exata:
    {
      "raciocinio_interno": "Explique brevemente como deduziu a natureza, categoria e conta.",
      "valor": float (apenas o número positivo absoluto),
      "natureza": "Essencial" | "Lazer" | "Receita",
      "categoria": "Nome da Categoria",
      "descricao": "Resumo do gasto (até 5 palavras)",
      "metodo_pagamento": "Pix" | "Cartão de Crédito" | "Cartão de Débito" | "Dinheiro" | "Outros",
      "conta": "Nome da Instituição/Conta"
    }
    </formato_de_saida>
    """
    
    response = deepseek_client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": texto_usuario}
        ],
        response_format={"type": "json_object"}
    )
    
    return json.loads(response.choices[0].message.content)

def inserir_no_banco(dados_extraidos):
    # Auditoria de Dados: Dump do Payload (excluindo o raciocínio longo para poupar log)
    payload_audit = {k: v for k, v in dados_extraidos.items() if k != "raciocinio_interno"}
    logger.info({"event": "db_insert_attempt", "payload": payload_audit})

    if "raciocinio_interno" in dados_extraidos:
        del dados_extraidos["raciocinio_interno"]

    registro = {
        "data": datetime.utcnow().strftime("%Y-%m-%d"),
        "valor": dados_extraidos.get("valor", 0.0),
        "natureza": dados_extraidos.get("natureza", "Outros"),
        "categoria": dados_extraidos.get("categoria", "Outros"),
        "descricao": dados_extraidos.get("descricao", ""),
        "metodo_pagamento": dados_extraidos.get("metodo_pagamento", "Outros"),
        "conta": dados_extraidos.get("conta", "Não Informada")
    }
    
    try:
        resposta = supabase.table("gastos").insert(registro).execute()
        return resposta
    except APIError as e:
        # Tratamento Granular de Banco de Dados: Dump de Exceção PostgREST
        logger.error({"event": "db_error", "code": e.code, "message": e.message, "hint": e.hint})
        raise Exception(f"Erro no Banco de Dados (Cod: {e.code}): {e.message}")

# ==========================================
# WEBHOOK (Gateway com Tratamento de Erros)
# ==========================================
@app.route("/", methods=["POST"])
def telegram_webhook():
    req_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if req_secret != SECRET_TOKEN:
        logger.warning({"event": "unauthorized_access", "reason": "Invalid Secret Token"})
        return jsonify({"error": "Unauthorized"}), 403

    update = request.get_json()
    if not update or "message" not in update:
        return jsonify({"status": "ignored"}), 200

    message = update["message"]
    chat_id = message["chat"]["id"]
    
    try:
        texto_analise = ""
        
        if "voice" in message:
            logger.info({"event": "processing_voice", "chat_id": chat_id})
            enviar_mensagem_telegram(chat_id, "⏳ *Ouvindo o áudio...*")
            audio_bytes = baixar_audio_telegram(message["voice"]["file_id"])
            if not audio_bytes:
                raise Exception("Não foi possível fazer o download do áudio no Telegram.")
            
            texto_analise = transcrever_audio(audio_bytes)
            logger.info({"event": "audio_transcribed", "text": texto_analise})
            
        elif "text" in message:
            texto_analise = message["text"]
            logger.info({"event": "processing_text", "text": texto_analise})
        else:
            return jsonify({"status": "unsupported"}), 200

        dados = processar_texto_com_llm(texto_analise)
        
        if dados and "valor" in dados:
            pensamento = dados.get("raciocinio_interno", "")
            
            inserir_no_banco(dados)
            logger.info({"event": "record_saved_successfully"})
            
            msg_sucesso = (
                f"✅ **Registro Salvo!**\n\n"
                f"💰 Valor: R$ {dados['valor']:.2f}\n"
                f"📊 Natureza: {dados['natureza']}\n"
                f"📂 Categoria: {dados['categoria']}\n"
                f"🏦 Conta: {dados['conta']} ({dados['metodo_pagamento']})\n"
                f"📝 Descrição: {dados['descricao']}\n\n"
                f"🧠 *Lógica:* _{pensamento}_"
            )
            enviar_mensagem_telegram(chat_id, msg_sucesso)
        else:
            raise Exception("A Inteligência Artificial não retornou dados no formato esperado.")

    except Exception as e:
        # Tratamento Global: Fail-Fast & Acknowledge (com Dump de Pilha)
        erro_detalhado = traceback.format_exc()
        logger.error({"event": "request_failed", "error": str(e), "traceback": erro_detalhado, "input": texto_analise if 'texto_analise' in locals() else None})
        
        msg_erro = f"❌ *Falha ao registrar o gasto!*\n\n⚠️ *Motivo:* `{str(e)}`\n\n_Verifique os logs no Google Cloud para mais detalhes._"
        enviar_mensagem_telegram(chat_id, msg_erro)

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))