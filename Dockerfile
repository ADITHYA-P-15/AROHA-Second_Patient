FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run typecheck && npm run lint && npm test
RUN npm run build

FROM python:3.12-slim
ARG GIT_SHA=dev
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 GIT_SHA=$GIT_SHA PYTHONPATH=/app/backend
WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt
COPY backend/ /app/backend/
RUN cd /app/backend && DATABASE_URL=sqlite:///./test_phase1.db SEED_DEMO=false SECRET_KEY=test-secret-key python -m pytest tests -q --tb=short && rm -f /app/backend/test_phase1.db
COPY --from=frontend /build/dist /app/frontend/dist
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh && useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
ENTRYPOINT ["/app/docker-entrypoint.sh"]
