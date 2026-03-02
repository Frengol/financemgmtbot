# Imagem base minimalista para redução de custos (FinOps) e superfície de ataque (AppSec)
FROM python:3.11-slim-bookworm

# Evitar que o Python escreva arquivos .pyc no disco (AppSec/Performance)
ENV PYTHONDONTWRITEBYTECODE=1
# Forçar o stdout/stderr do Python direto para os logs do Cloud Run
ENV PYTHONUNBUFFERED=1

# Instalar dependências do sistema necessárias e limpar cache para manter a imagem leve
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Criar e configurar um usuário não-root (AppSec: previência contra escalonamento de privilégios)
RUN useradd -m -r financebotuser
WORKDIR /app

# Copiar apenas arquivos de dependências primeiro para aproveitar o cache do Docker
COPY requirements.txt .

# Instalar dependências Python
RUN pip install --no-cache-dir -r requirements.txt

# Adicionar o código fonte do projeto
COPY . .

# Ajustar a propriedade dos arquivos para o usuário não-root
RUN chown -R financebotuser:financebotuser /app

# Trocar para o usuário criado
USER financebotuser

# Expor a porta padrão que o Cloud Run espera (via variável de ambiente $PORT)
EXPOSE 8080

# Comando estrito para forçar o Hypercorn (ASGI) ao invés do Gunicorn padrão do Buildpack
CMD ["sh", "-c", "hypercorn main:app --bind 0.0.0.0:${PORT:-8080}"]
