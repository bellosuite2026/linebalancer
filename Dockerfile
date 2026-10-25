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
# TLB_API_KEYS="cle1,cle2" pour activer l'authentification
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
