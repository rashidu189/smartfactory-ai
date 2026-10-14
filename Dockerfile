# ---------- 1. Build the Angular 14 frontend ----------
FROM node:18-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npx ng build --configuration production

# ---------- 2. Python API + static hosting ----------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080 \
    FRONTEND_DIR=/app/frontend_dist LOCAL_STORAGE_DIR=/tmp/smartfactory_files SQLITE_PATH=/tmp/smartfactory_dev.db
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY backend/data ./data
COPY --from=web /web/dist/smartfactory-ui ./frontend_dist
RUN useradd -m appuser && mkdir -p /data && chown appuser /data
USER appuser
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1
