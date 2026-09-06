# Sea Anchor — FastAPI + built frontend, one process.
# Listen on $PORT (Render) or 8000.

FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ENV VITE_API_BASE=""
RUN npm run build

FROM python:3.12-slim-bookworm
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000
COPY requirements-serve.txt .
RUN pip install --no-cache-dir -r requirements-serve.txt
COPY api/ api/
COPY src/ src/
COPY --from=ui /ui/dist frontend/dist
EXPOSE 8000
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
