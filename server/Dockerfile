# syntax=docker/dockerfile:1.7

# ---- Stage 1: build the SPA ----
FROM node:20-alpine AS web-build
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY web/ ./
RUN npm run build


# ---- Stage 2: python runtime ----
FROM python:3.12-slim AS runtime
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY server/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY server/app/ ./app/
COPY --from=web-build /web/dist/ ./static/

ENV TVIR_CONFIG=/app/config/tvs.yaml \
    TVIR_IRDB=/app/flipper-irdb \
    TVIR_DATA=/app/data \
    TVIR_STATIC=/app/static

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=2).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
