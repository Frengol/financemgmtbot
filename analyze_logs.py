import json
import sys
from collections import Counter

log_file = 'c:/Users/freng/OneDrive/Área de Trabalho/BOTS/financemgmtbot/financemgmtbot/downloaded-logs-20260302-124934.json'

with open(log_file, 'r', encoding='utf-8') as f:
    data = json.load(f)

print(f"Total de linhas de log analisadas: {len(data)}")

errors = []
for entry in data:
    text_payload = entry.get('textPayload', '')
    if 'Traceback' in text_payload or 'ERROR' in text_payload or 'Exception' in text_payload or 'Error' in text_payload:
        errors.append(text_payload)

print(f"Mostrando os últimos erros únicos ou relevantes...")
shown = set()
for err in errors:
    # Mostra apenas um trecho para não estourar o console, mas captura erro diferente
    short_err = err[:300]
    if short_err not in shown:
        print("-------------")
        print(err)
        shown.add(short_err)

