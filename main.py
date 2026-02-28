import os
import json
import requests
from flask import Flask, request, jsonify
from supabase import create_client, Client
from openai import OpenAI
from groq import Groq
from datetime import datetime

# ==========================================
# CONFIGURAÇÕES E SEGURANÇA (AppSec)
# ==========================================
app = Flask(__name__)

REQUIRED_VARS = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_SECRET_TOKEN", "SUPABASE_URL", "SUPABASE_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY"]
for var in REQUIRED_VARS:
    if not os.environ.get(var):
        raise RuntimeError(f"AppSec Fatal Error: Variável de ambiente {var} não configurada.")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
SECRET_TOKEN = os.environ.get("TELEGRAM_SECRET_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Inicialização de Clientes
supabase: Client = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
deepseek_client = OpenAI(api_key=os.environ.get("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com")

# ==========================================
# FUNÇÕES DE SERVIÇO (Infraestrutura)
# ==========================================
def enviar_mensagem_telegram(chat_id, texto):
    url = f"{TELEGRAM_API_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": texto, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def baixar_audio_telegram(file_id):
    url_info = f"{TELEGRAM_API_URL}/getFile?file_id={file_id}"
    resp = requests.get(url_info).json()
    if not resp.get("ok"):
        return None
    file_path = resp["result"]["file_path"]
    download_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
    return requests.get(download_url).content

def transcrever_audio(audio_bytes):
    tmp_path = "/tmp/audio.ogg"
    with open(tmp_path, "wb") as f:
        f.write(audio_bytes)
    
    with open(tmp_path, "rb") as file:
        transcription = groq_client.audio.transcriptions.create(
            file=(tmp_path, file.read()),
            model="whisper-large-v3",
            prompt="Transcreva este áudio em português brasileiro sobre finanças, fast food, contas e gastos."
        )
    os.remove(tmp_path)
    return transcription.text

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
      "raciocinio_interno": "Explique brevemente como deduziu a natureza (especialmente se for comida de lazer vs essencial), categoria e conta.",
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
    
    try:
        return json.loads(response.choices[0].message.content)
    except:
        return None

def inserir_no_banco(dados_extraidos):
    # O banco não precisa guardar o pensamento da IA, então removemos o raciocínio.
    if "raciocinio_interno" in dados_extraidos:
        del dados_extraidos["raciocinio_interno"]

    registro = {
        "data": datetime.utcnow().strftime("%Y-%m-%d"),
        "valor": dados_extraidos["valor"],
        "natureza": dados_extraidos["natureza"],
        "categoria": dados_extraidos["categoria"],
        "descricao": dados_extraidos["descricao"],
        "metodo_pagamento": dados_extraidos["metodo_pagamento"],
        "conta": dados_extraidos["conta"]
    }
    
    resposta = supabase.table("gastos").insert(registro).execute()
    return resposta

# ==========================================
# WEBHOOK (Gateway)
# ==========================================
@app.route("/", methods=["POST"])
def telegram_webhook():
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
        
        if "voice" in message:
            enviar_mensagem_telegram(chat_id, "⏳ *Processando áudio...*")
            audio_bytes = baixar_audio_telegram(message["voice"]["file_id"])
            if not audio_bytes:
                return jsonify({"status": "error"}), 200
            texto_analise = transcrever_audio(audio_bytes)
        elif "text" in message:
            texto_analise = message["text"]
        else:
            return jsonify({"status": "unsupported"}), 200

        dados = processar_texto_com_llm(texto_analise)
        
        if dados and "valor" in dados:
            # Salvamos o raciocínio apenas para mandar no Telegram e você auditar (visão de QA)
            pensamento = dados.get("raciocinio_interno", "")
            
            inserir_no_banco(dados) # Aqui o raciocínio é deletado antes de ir pro banco
            
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
             enviar_mensagem_telegram(chat_id, "⚠️ Não consegui entender os valores ou categorizar esta mensagem.")

    except Exception as e:
        enviar_mensagem_telegram(chat_id, "❌ Erro interno no processamento.")
        print(f"Erro: {e}")

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))