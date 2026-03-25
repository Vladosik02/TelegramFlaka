# ── Stage 1: Builder ──────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# Устанавливаем зависимости для сборки
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Создаем виртуальное окружение
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Stage 2: Runtime ───────────────────────────────────────────────────────────
FROM python:3.11-slim

# Создаем пользователя
RUN groupadd --gid 1001 botgroup && \
    useradd --uid 1001 --gid botgroup --no-create-home --shell /bin/sh botuser

WORKDIR /app

# Копируем виртуальное окружение целиком
COPY --from=builder /opt/venv /opt/venv
# Прописываем путь к библиотекам в PATH
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

# Копируем код
COPY --chown=botuser:botgroup . .

# Создаем папки и даем права
RUN mkdir -p data backups && \
    chown -R botuser:botgroup /app /opt/venv

USER botuser

# Health check
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import sqlite3; sqlite3.connect('data/trainer.db').execute('SELECT 1').fetchone(); print('ok')" || exit 1

ENTRYPOINT ["python", "main.py"]