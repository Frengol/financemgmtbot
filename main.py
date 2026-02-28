import os
import json
import requests
from flask import Flask, request, jsonify
from supabase import create_client, Client
from openai import OpenAI
from groq import Groq
from datetime import datetime

# ==========================================
# CONFIGURAÇÕES E APPS (Injeção de Dependências via Env)
# ==========================================
app = Flask(__name__)

# AppSec: Falha rápida (Fail-fast) se faltarem variáveis de ambiente críticas
REQUIRED_VARS = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_SECRET_TOKEN", "SUPABASE_URL", "SUPABASE_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY"]
for var in REQUIRED_VARS:
    if not os.environ.get(var):
        raise RuntimeError(f"AppSec Fatal Error: Variável de ambiente {var} não configurada.")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
SECRET_TOKEN = os.environ.get("TELEGRAM_SECRET_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Inicialização de Clientes (Supabase, Groq, DeepSeek)
supabase: Client = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
deepseek_client = OpenAI(api_key=os.environ.get("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com")

# ==========================================
# FUNÇÕES DE SERVIÇO (Business Logic)
# ==========================================
def enviar_mensagem_telegram(chat_id, texto):
    """Envia o retorno ao usuário de forma assíncrona."""
    url = f"{TELEGRAM_API_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": texto, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def baixar_audio_telegram(file_id):
    """Obtém a URL do arquivo no Telegram e faz o download na memória."""
    url_info = f"{TELEGRAM_API_URL}/getFile?file_id={file_id}"
    resp = requests.get(url_info).json()
    if not resp.get("ok"):
        return None
    file_path = resp["result"]["file_path"]
    download_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
    audio_data = requests.get(download_url).content
    return audio_data

def transcrever_audio(audio_bytes):
    """Usa Groq (Whisper) para transformar voz em texto velozmente."""
    # Salvando temporariamente em disco (necessário para a lib do Groq)
    tmp_path = "/tmp/audio.ogg"
    with open(tmp_path, "wb") as f:
        f.write(audio_bytes)
    
    with open(tmp_path, "rb") as file:
        transcription = groq_client.audio.transcriptions.create(
            file=(tmp_path, file.read()),
            model="whisper-large-v3",
            prompt="Transcreva este áudio em português brasileiro sobre finanças e gastos."
        )
    os.remove(tmp_path)
    return transcription.text

def processar_texto_com_llm(texto_usuario):
    """Usa DeepSeek para extrair entidades financeiras via JSON."""
    system_prompt = """
    Você é um agente financeiro extrator de dados. Analise a entrada do usuário e extraia os dados do gasto.
    Responda EXCLUSIVAMENTE com um JSON válido, sem formatação markdown.
    
    Exemplos de contexto de categorização para melhorar sua precisão:
    - Se o usuário mencionar gastos com manutenção ou combustível do "Civic", "Civic LXL" ou "Golf", a categoria é "Transporte/Veículo".
    - Se o usuário mencionar "Santo Antônio do Pinhal", "Socorro", "Monte Verde", "Camanducaia" ou "Florianópolis", a categoria é "Viagem/Lazer".

    O JSON deve conter:
    - "valor": float (ex: 150.50. Se for entrada/salário, use positivo, se for gasto, use negativo).
    - "categoria": string (ex: "Alimentação", "Transporte/Veículo", "Viagem/Lazer", "Diversão", "Contas Fixas").
    - "descricao": string (resumo do gasto).
    - "metodo_pagamento": string (ex: "Cartão de Crédito", "Pix", "Dinheiro").
    """
    
    response = deepseek_client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": texto_usuario}
        ],
        response_format={"type": "json_object"}
    )
    
    try:
        return json.loads(response.choices[0].message.content)
    except:
        return None

def inserir_no_banco(dados_extraidos):
    """Persiste no PostgreSQL via Supabase garantindo tipagem forte."""
    registro = {
        "data": datetime.utcnow().strftime("%Y-%m-%d"),
        "valor": dados_extraidos["valor"],
        "categoria": dados_extraidos["categoria"],
        "descricao": dados_extraidos["descricao"],
        "metodo_pagamento": dados_extraidos["metodo_pagamento"]
    }
    resposta = supabase.table("gastos").insert(registro).execute()
    return resposta

# ==========================================
# ROTAS E WEBHOOK (Gateway)
# ==========================================
@app.route("/", methods=["POST"])
def telegram_webhook():
    # AppSec: Validação do Token de Segurança (Rejeita tráfego não-Telegram)
    req_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if req_secret != SECRET_TOKEN:
        return jsonify({"error": "Unauthorized"}), 403

    update = request.get_json()
    if not update or "message" not in update:
        return jsonify({"status": "ignored"}), 200

    message = update["message"]
    chat_id = message["chat"]["id"]
    
    try:
        texto_analise = ""
        
        # Roteamento: É áudio (voz) ou texto?
        if "voice" in message:
            enviar_mensagem_telegram(chat_id, "⏳ *Ouvindo o áudio...*")
            audio_bytes = baixar_audio_telegram(message["voice"]["file_id"])
            if not audio_bytes:
                enviar_mensagem_telegram(chat_id, "❌ Erro ao baixar o áudio do Telegram.")
                return jsonify({"status": "error"}), 200
            texto_analise = transcrever_audio(audio_bytes)
        elif "text" in message:
            texto_analise = message["text"]
        else:
            return jsonify({"status": "unsupported_format"}), 200

        # Inteligência Artificial e Banco de Dados
        enviar_mensagem_telegram(chat_id, f"🧠 *Processando:* _{texto_analise}_")
        dados_financeiros = processar_texto_com_llm(texto_analise)
        
        if dados_financeiros and "valor" in dados_financeiros:
            inserir_no_banco(dados_financeiros)
            msg_sucesso = (
                f"✅ **Registro Salvo!**\n\n"
                f"💰 Valor: R$ {abs(dados_financeiros['valor']):.2f}\n"
                f"📂 Categoria: {dados_financeiros['categoria']}\n"
                f"📝 Descrição: {dados_financeiros['descricao']}\n"
                f"💳 Pagamento: {dados_financeiros['metodo_pagamento']}"
            )
            enviar_mensagem_telegram(chat_id, msg_sucesso)
        else:
             enviar_mensagem_telegram(chat_id, "⚠️ Não consegui entender os valores financeiros nesta mensagem.")

    except Exception as e:
        # FinOps/AppSec: Captura falhas silenciosamente para o usuário, mas previne retentativas do Telegram
        enviar_mensagem_telegram(chat_id, "❌ Ocorreu um erro interno ao processar o gasto.")
        print(f"Erro Crítico: {e}")

    # Retorna 200 OK rápido para o Telegram não re-enviar a mensagem
    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    # FinOps: Porta dinâmica lida do ambiente gerenciado pelo Cloud Run
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))