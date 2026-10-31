# The deployable product: the dashboard built to static files and served by the API,
# one container on one port. Models come from Groq (GROQ_API_KEY), so the image needs
# no GPU and no Ollama. docs/DEPLOY.md has the settings.
#
# backend/Dockerfile and docker-compose.yml are the research setup (local Ollama,
# Neo4j, the evaluation stack) and are unchanged.

FROM node:20-slim AS dashboard
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Empty: the dashboard calls the API on its own origin.
ENV VITE_API_BASE_URL=""
RUN npm run build

FROM python:3.13-slim
# git: the analyser clones repositories with it.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements-app.txt .
RUN pip install --no-cache-dir -r requirements-app.txt
COPY backend/app ./app
COPY --from=dashboard /frontend/dist ./frontend-dist
# Analyses made on the demo Mac (local model summaries), copied into the store on
# first start so the examples open instantly. Regenerate with
# `python -m app.product.seed --export-seed`.
COPY backend/seed/product.db ./seed/product.db

ENV FRONTEND_DIST=/app/frontend-dist \
    PRODUCT_DB_PATH=/data/product.db \
    PRODUCT_SEED_DB=/app/seed/product.db \
    LLM_PROVIDER=groq \
    LLM_FALLBACK=none \
    NEO4J_ENABLED=false \
    PUBLIC_MODE=true \
    MAX_REPO_SIZE_MB=60 \
    PYTHONUNBUFFERED=1
# The SQLite store. Mount a persistent volume here, or every redeploy starts empty.
VOLUME /data

EXPOSE 8000
# --proxy-headers: behind the host's load balancer, so per-visitor rate limits see
# the visitor's address rather than the proxy's. PORT is set by most hosts.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
