#!/bin/bash

# Este script orquestra o deploy do Bot de Finanças para o Google Cloud Run
# impondo estritamente as novas políticas de FinOps e AppSec do ARCHITECTURE.MD

PROJECT_ID="financemgmtbot"
SERVICE_NAME="financemgmtbot-git"
REGION="southamerica-east1"

echo "====================================================="
echo "🚀 Iniciando Build & Deploy Finanças Copilot Autônomo"
echo "====================================================="

# 1. Faz o build da imagem Docker baseada no Dockerfile otimizado de segurança
echo "--- Passo 1: Construindo a imagem Docker ---"
gcloud builds submit --tag gcr.io/$PROJECT_ID/$SERVICE_NAME

# 2. Executa o deploy com as armaduras (guardrails) ativadas
# Regras de FinOps aplicadas:
# --max-instances=1: Limita a um único container vivo. Se houver DDoS ou Crash Loop, ele nunca tentará criar dezenas de instâncias
# --concurrency=80: Uma única instância ASGI consegue tratar 80 requisições simultâneas tranquilamente.
# --cpu-boost: Desativado, economizando centavos preciosos na inicialização.

echo "--- Passo 2: Publicando no Google Cloud Run ---"
gcloud run deploy $SERVICE_NAME \
    --image gcr.io/$PROJECT_ID/$SERVICE_NAME \
    --region $REGION \
    --max-instances=1 \
    --concurrency=80 \
    --allow-unauthenticated \
    --cpu=1 \
    --memory=512Mi \
    --timeout=60s

echo "====================================================="
echo "✅ Deploy Concluído com Segurança FinOps Aplicada"
echo "====================================================="
