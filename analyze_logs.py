import json
from datetime import datetime

log_file = 'c:/Users/freng/OneDrive/Área de Trabalho/BOTS/financemgmtbot/financemgmtbot/logs/downloaded-logs-20260302-085657.json'

with open(log_file, 'r', encoding='utf-8') as f:
    data = json.load(f)

print(f"Total de linhas de log analisadas: {len(data)}")

requests = []
instances = set()
timestamps = []

for entry in data:
    if 'timestamp' in entry:
        try:
            # Handle standard format: 2026-03-02T11:10:28.672258Z
            ts = datetime.strptime(entry['timestamp'][:26] + 'Z', "%Y-%m-%dT%H:%M:%S.%fZ")
            timestamps.append(ts)
        except ValueError:
            pass
            
    if 'httpRequest' in entry:
        requests.append(entry['httpRequest'])
        
    labels = entry.get('labels', {})
    if 'instanceId' in labels:
        instances.add(labels['instanceId'])
        
if timestamps:
    timestamps.sort()
    inicio = timestamps[0]
    fim = timestamps[-1]
    duracao = fim - inicio
    print(f"Período dos Logs: {inicio} até {fim} (Duração total: {duracao})")
else:
    print("Não foi possível extrair timestamps.")

print(f"Total de Requisições HTTP (httpRequest): {len(requests)}")

status_counts = {}
for req in requests:
    st = str(req.get('status', 'Unknown'))
    status_counts[st] = status_counts.get(st, 0) + 1
    
print(f"Distribuição de Status HTTP: {status_counts}")
print(f"Total de Instâncias Únicas Inicializadas: {len(instances)}")
