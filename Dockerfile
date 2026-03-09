# ── Stage 1: Dependencies ──────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# Install system deps for building wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


# ── Stage 2: Runtime ───────────────────────────────────────────────────────────
FROM python:3.11-slim

# Non-root user for security
RUN groupadd --gid 1001 botgroup && \
    useradd --uid 1001 --gid botgroup --no-create-home --shell /bin/sh botuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy application code (exclude data/backups via .dockerignore)
COPY --chown=botuser:botgroup . .

# Persistent dirs — mounted as volumes in production
RUN mkdir -p data backups && \
    chown -R botuser:botgroup /app

USER botuser

# Health check: SQLite доступна
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import sqlite3; sqlite3.connect('data/trainer.db').execute('SELECT 1').fetchone(); print('ok')" || exit 1

CMD ["python", "main.py"]
