FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd -m -r financebotuser
WORKDIR /app

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=financebotuser:financebotuser . .

USER financebotuser

EXPOSE 8080

CMD ["sh", "-c", "hypercorn main:app --bind 0.0.0.0:${PORT:-8080}"]
