# =============================================================================
# Dockerfile — Inventory App
# Multi-stage: Node builds React, Python serves everything
# =============================================================================

# ── Stage 1: Build React frontend ─────────────────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

# Install dependencies first (cached layer)
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci

# Copy source and build
COPY frontend/ ./
RUN npm run build


# ── Stage 2: Python app ───────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py ./
COPY src/ ./src/
COPY blueprints/ ./blueprints/

# Copy built React app from stage 1
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Don't run as root
RUN useradd -m -u 1000 appuser && chown -R appuser /app
USER appuser

# Gunicorn — 2 workers, 120s timeout for long submit operations
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "app:app"]

EXPOSE 8000
