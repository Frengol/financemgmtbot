import asyncio
import json
import os
import random
import tempfile
import time

import httpx
from google.genai import types

from utils import get_brasilia_time
from config import gemini_client, groq_client, deepseek_client, logger


GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_OCR_TIMEOUTS_SECONDS = (60, 45)
GEMINI_INTERNAL_RETRY_DELAY_RANGE_SECONDS = (0.5, 1.5)


class AIProviderError(RuntimeError):
    """Sanitized provider error used at the worker boundary."""

    def __init__(self, message, *, error_code):
        super().__init__(message)
        self.error_code = error_code


class AIProviderRetryableError(AIProviderError):
    pass


class AIProviderPermanentError(AIProviderError):
    pass


def _provider_error_code(exc):
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return str(code)
    if isinstance(code, str) and code.strip():
        return code.strip()[:40]
    return type(exc).__name__


def _is_retryable_provider_error(exc):
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code.isdigit():
        code = int(code)
    if code in {408, 429, 500, 502, 503, 504}:
        return True
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException, httpx.NetworkError)):
        return True
    return type(exc).__name__ in {
        "ResourceExhausted",
        "RateLimitError",
        "APITimeoutError",
        "ReadTimeout",
        "ServiceUnavailable",
    }


def _provider_log_fields(source_update_id=None, worker_attempt=None):
    fields = {}
    if source_update_id is not None:
        fields["update_id"] = source_update_id
    if worker_attempt is not None:
        fields["worker_attempt"] = worker_attempt
    return fields


def _log_provider_failure(provider, stage, exc, started_at, *, source_update_id=None, worker_attempt=None):
    logger.warning(
        {
            "event": "ai_provider_failure",
            "provider": provider,
            "stage": stage,
            "error_code": _provider_error_code(exc),
            "classification": "retryable" if _is_retryable_provider_error(exc) else "permanent",
            "duration_ms": round((time.monotonic() - started_at) * 1000),
            **_provider_log_fields(source_update_id, worker_attempt),
        }
    )

async def transcrever_audio(audio_bytes, *, source_update_id=None, worker_attempt=None):
    if not audio_bytes:
        raise ValueError("Audio payload is empty.")
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp_file:
        tmp_path = tmp_file.name
        tmp_file.write(audio_bytes)
    try:
        with open(tmp_path, "rb") as file_to_read:
            started_at = time.monotonic()
            try:
                transcription = await asyncio.wait_for(
                    groq_client.audio.transcriptions.create(
                        file=(tmp_path, file_to_read.read()),
                        model="whisper-large-v3",
                        prompt="Transcreva este áudio em português sobre finanças, fast food, mercado, faturas e parcelamentos."
                    ),
                    timeout=45,
                )
            except Exception as exc:
                _log_provider_failure(
                    "groq",
                    "stt",
                    exc,
                    started_at,
                    source_update_id=source_update_id,
                    worker_attempt=worker_attempt,
                )
                raise
        return transcription.text
    finally:
        if os.path.exists(tmp_path): os.remove(tmp_path)

async def extrair_tabela_recibo_gemini(image_bytes, *, source_update_id=None, worker_attempt=None):
    if not image_bytes:
        raise ValueError("Image payload is empty.")
    if gemini_client is None:
        raise AIProviderRetryableError("Gemini client is unavailable.", error_code="client_unavailable")
    prompt_visao = """
    Atue como um extrator de dados. Extraia a tabela de itens comprados. 
    Colunas obrigatórias: [Nome do Produto] | [Valor Bruto] | [Desconto do Item]. 
    Se não houver desconto no item, use 0.00. Não confunda quantidade com desconto.
    
    Abaixo da tabela, escreva duas linhas estritas:
    Desconto Global: [Apenas o valor numérico do desconto final da nota. Diferencie de subtotais! Subtotal NÃO é desconto. Procure palavras como "Desconto", "Desconto total". Se não houver, escreva 0.00]
    Pagamento: [Infira o método lendo a nota inteira: Pix, Crédito, Débito, Dinheiro, Vale Alimentação. Se impossível saber, escreva Não Informado]
    """
    last_error = None
    for attempt, timeout_seconds in enumerate(GEMINI_OCR_TIMEOUTS_SECONDS, start=1):
        started_at = time.monotonic()
        try:
            response = await gemini_client.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                    prompt_visao,
                ],
                config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                    http_options=types.HttpOptions(
                        timeout=timeout_seconds * 1000,
                        retry_options=types.HttpRetryOptions(attempts=1),
                    ),
                ),
            )
            logger.info(
                {
                    "event": "ai_provider_completed",
                    "provider": "gemini",
                    "stage": "ocr",
                    "model": GEMINI_MODEL,
                    "attempt": attempt,
                    "duration_ms": round((time.monotonic() - started_at) * 1000),
                    **_provider_log_fields(source_update_id, worker_attempt),
                }
            )
            if not getattr(response, "text", None):
                raise AIProviderPermanentError("Gemini returned an empty OCR response.", error_code="empty_response")
            return response.text
        except AIProviderPermanentError:
            raise
        except Exception as exc:
            last_error = exc
            _log_provider_failure(
                "gemini",
                "ocr",
                exc,
                started_at,
                source_update_id=source_update_id,
                worker_attempt=worker_attempt,
            )
            if not _is_retryable_provider_error(exc):
                raise AIProviderPermanentError("Gemini rejected the OCR request.", error_code=_provider_error_code(exc)) from exc
            if attempt == len(GEMINI_OCR_TIMEOUTS_SECONDS):
                raise AIProviderRetryableError("Gemini OCR is temporarily unavailable.", error_code=_provider_error_code(exc)) from exc
            delay = random.uniform(*GEMINI_INTERNAL_RETRY_DELAY_RANGE_SECONDS)
            logger.info(
                {
                    "event": "ai_provider_internal_retry",
                    "provider": "gemini",
                    "stage": "ocr",
                    "model": GEMINI_MODEL,
                    "attempt": attempt + 1,
                    "previous_error_code": _provider_error_code(exc),
                    "delay_ms": round(delay * 1000),
                    **_provider_log_fields(source_update_id, worker_attempt),
                }
            )
            await asyncio.sleep(delay)
    raise AIProviderRetryableError("Gemini OCR is temporarily unavailable.", error_code=_provider_error_code(last_error))

async def processar_texto_com_llm(texto_usuario, *, source_update_id=None, worker_attempt=None):
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
    - Transcrições de áudio como "piques", "pics" ou "pis" SIGNIFICAM o método de pagamento "Pix".
    - Cronologia: Se o usuário citar datas retroativas ("ontem", "anteontem", "dia 15"), CALCULE a data exata (YYYY-MM-DD) usando o CONTEXTO TEMPORAL INJETADO. Se omitido, use a data de hoje.
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
        "data": "YYYY-MM-DD",
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
    
    started_at = time.monotonic()
    try:
        response = await asyncio.wait_for(
            deepseek_client.chat.completions.create(
                model="deepseek-v4-pro",
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": texto_usuario}],
                response_format={"type": "json_object"},
                extra_body={"thinking": {"type": "disabled"}},
            ),
            timeout=45,
        )
    except Exception as exc:
        _log_provider_failure(
            "deepseek",
            "llm",
            exc,
            started_at,
            source_update_id=source_update_id,
            worker_attempt=worker_attempt,
        )
        raise
    texto_resposta = response.choices[0].message.content
    return json.loads(str(texto_resposta) if texto_resposta else "{}")
