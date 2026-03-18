import re

with open("test_main.py", "r", encoding="utf-8") as f:
    code = f.read()

# Replace Imports
code = code.replace("import main  # noqa: E402", 
"""import config
import utils
import telegram_service
import ai_service
import core_logic
import db_repository
import handlers
import main  # noqa: E402""")

# Module Mappings for function calls
mappings = {
    # Utils
    r"main\.inferir_natureza": "utils.inferir_natureza",
    r"main\.add_months_safely": "utils.add_months_safely",
    r"main\.get_brasilia_time": "utils.get_brasilia_time",
    r"main\.CATEGORIA_MAP": "utils.CATEGORIA_MAP",
    # Config
    r"main\.mascarar_segredos": "config.mascarar_segredos",
    r"main\.deepseek_client": "config.deepseek_client",
    r"main\.groq_client": "config.groq_client",
    r"main\.logger": "config.logger",
    r"main\.supabase": "config.supabase",
    r"main\.http_client": "telegram_service.http_client",
    # Core
    r"main\.aplicar_map_reduce": "core_logic.aplicar_map_reduce",
    r"main\.gerar_mensagem_resumo": "core_logic.gerar_mensagem_resumo",
    r"main\.gerar_texto_edicao": "core_logic.gerar_texto_edicao",
    r"main\.formatar_relatorio_exclusao": "core_logic.formatar_relatorio_exclusao",
    # DB
    r"main\.aplicar_filtros_query": "db_repository.aplicar_filtros_query",
    r"main\.inserir_no_banco": "db_repository.inserir_no_banco",
    r"main\.gravar_lote_no_banco": "db_repository.gravar_lote_no_banco",
    r"main\.consultar_no_banco": "db_repository.consultar_no_banco",
    # AI
    r"main\.transcrever_audio": "ai_service.transcrever_audio",
    r"main\.extrair_tabela_recibo_gemini": "ai_service.extrair_tabela_recibo_gemini",
    r"main\.processar_texto_com_llm": "ai_service.processar_texto_com_llm",
    # Telegram
    r"main\.enviar_acao_telegram": "telegram_service.enviar_acao_telegram",
    r"main\.enviar_mensagem_telegram": "telegram_service.enviar_mensagem_telegram",
    r"main\.editar_mensagem_telegram": "telegram_service.editar_mensagem_telegram",
    r"main\.baixar_arquivo_telegram": "telegram_service.baixar_arquivo_telegram",
    # Handlers
    r"main\.iniciar_fluxo_exclusao": "handlers.iniciar_fluxo_exclusao",
    r"main\.processar_update_assincrono": "handlers.processar_update_assincrono",
}

for old, new in mappings.items():
    code = re.sub(old, new, code)

# Mock Patches (patch.object main -> mock directly where used)
# Many of them are used in handlers:
handlers_mocks = [
    "transcrever_audio", "baixar_arquivo_telegram", "extrair_tabela_recibo_gemini",
    "processar_texto_com_llm", "gravar_lote_no_banco", "iniciar_fluxo_exclusao",
    "inserir_no_banco", "consultar_no_banco", "enviar_mensagem_telegram", "editar_mensagem_telegram"
]

for func in handlers_mocks:
    code = re.sub(rf'patch\.object\(main, "{func}"', rf'patch("handlers.{func}"', code)

with open("test_main.py", "w", encoding="utf-8") as f:
    f.write(code)

print("Tests refactored successfully")
