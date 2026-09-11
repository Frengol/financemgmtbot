"""Shared Gemini receipt-extraction contract with no application initialization."""

from google.genai import types


GEMINI_PRIMARY_MODEL = "gemini-3.5-flash"
GEMINI_FALLBACK_MODEL = "gemini-3.5-flash-lite"
GEMINI_OCR_MODELS = (
    (GEMINI_PRIMARY_MODEL, 60),
    (GEMINI_FALLBACK_MODEL, 45),
)

RECEIPT_OCR_PROMPT = """
Atue como um extrator de dados. Extraia a tabela de itens comprados.
Colunas obrigatórias: [Nome do Produto] | [Valor Bruto] | [Desconto do Item].
Se não houver desconto no item, use 0.00. Não confunda quantidade com desconto.

Abaixo da tabela, escreva duas linhas estritas:
Desconto Global: [Apenas o valor numérico do desconto final da nota. Diferencie de subtotais! Subtotal NÃO é desconto. Procure palavras como "Desconto", "Desconto total". Se não houver, escreva 0.00]
Pagamento: [Infira o método lendo a nota inteira: Pix, Crédito, Débito, Dinheiro, Vale Alimentação. Se impossível saber, escreva Não Informado]
""".strip()


def build_generate_content_config(timeout_seconds: int) -> types.GenerateContentConfig:
    if timeout_seconds <= 0:
        raise ValueError("OCR timeout must be positive.")
    return types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level="minimal"),
        http_options=types.HttpOptions(
            timeout=timeout_seconds * 1000,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
