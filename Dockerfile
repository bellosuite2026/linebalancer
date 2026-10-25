# Image serveur : API + moteur (sans GUI). Hébergement conteneur hors serverless.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt
COPY engine/ engine/
COPY api/ api/
COPY data/ data/
EXPOSE 8000
# Config par variables d'environnement (voir .env.example). Render fournit $PORT.
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
