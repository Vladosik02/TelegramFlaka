"""
tests/conftest.py — Общие фикстуры для всех тестов.

Стратегия изоляции:
  • Каждый тест работает с in-memory SQLite (не трогает data/trainer.db).
  • get_connection патчится в КАЖДОМ модуле, который его импортирует
    ('from db.connection import get_connection' создаёт локальную ссылку
     — патч db.connection не затрагивает её).
  • Вспомогательная функция insert_user создаёт тестового пользователя.
"""
import os

# ── Заглушки переменных окружения ─────────────────────────────────────────────
# Устанавливаем ДО первого импорта config.py — иначе он упадёт с ValueError.
# В CI значения уже заданы через env: в workflow — там они непустые, не затронем.
# Используем "or" вместо setdefault, чтобы перезаписать пустые строки тоже.
if not os.environ.get("TELEGRAM_TOKEN"):
    os.environ["TELEGRAM_TOKEN"] = "test_token_ci"
if not os.environ.get("ANTHROPIC_API_KEY"):
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key-ci"

import sqlite3
import datetime
import pytest
from unittest.mock import patch

# ── Читаем схему из файла schema.sql ──────────────────────────────────────────
_SCHEMA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "db", "schema.sql"
)


def _create_in_memory_db() -> sqlite3.Connection:
    """
    Создаёт полностью инициализированную in-memory SQLite БД.
    Читает schema.sql и применяет все CREATE TABLE + CREATE INDEX.
    Также применяет миграционные ALTER TABLE (игнорируя ошибки дублирования).
    """
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_sql = f.read()
    conn.executescript(schema_sql)

    # Миграции — единый источник правды в db/migrations.py
    from db.migrations import MIGRATIONS
    for sql in MIGRATIONS:
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            pass  # колонка уже существует — норма

    conn.commit()
    return conn


@pytest.fixture
def db_conn():
    """In-memory SQLite соединение с полной схемой. Используется в тестах напрямую."""
    conn = _create_in_memory_db()
    yield conn
    conn.close()


@pytest.fixture
def patched_db(db_conn):
    """
    Патчит get_connection во ВСЕХ модулях проекта, которые его импортируют.

    Важно: каждый модуль делает 'from db.connection import get_connection',
    создавая ЛОКАЛЬНУЮ ссылку. Патч нужно применять именно к этим ссылкам,
    а не только к db.connection.
    """
    # Список соответствует модулям с `from db.connection import get_connection`
    # на уровне модуля. Lazy-импорты внутри функций патчить не нужно — они
    # резолвятся по `db.connection.get_connection` на каждом вызове.
    # При добавлении нового модуля с module-level импортом — добавить сюда.
    _targets = [
        "db.connection.get_connection",
        # bot/
        "bot.handlers.get_connection",
        # db/queries/
        "db.queries.context.get_connection",
        "db.queries.daily_summary.get_connection",
        "db.queries.episodic.get_connection",
        "db.queries.exercises.get_connection",
        "db.queries.fitness_metrics.get_connection",
        "db.queries.gamification.get_connection",
        "db.queries.memory.get_connection",
        "db.queries.monthly_summary.get_connection",
        "db.queries.nutrition.get_connection",
        "db.queries.periodization.get_connection",
        "db.queries.recovery.get_connection",
        "db.queries.stats.get_connection",
        "db.queries.training_plan.get_connection",
        "db.queries.usage.get_connection",
        "db.queries.user.get_connection",
        "db.queries.workouts.get_connection",
        # scheduler/
        "scheduler.nudges.get_connection",
        "scheduler.periodization.get_connection",
        "scheduler.personal_insights.get_connection",
        "scheduler.prediction.get_connection",
    ]
    active_patches = []
    for target in _targets:
        try:
            p = patch(target, return_value=db_conn)
            p.start()
            active_patches.append(p)
        except (AttributeError, ModuleNotFoundError):
            pass  # модуль ещё не импортирован или нет нужного атрибута

    yield db_conn

    for p in reversed(active_patches):
        try:
            p.stop()
        except RuntimeError:
            pass


# ── Вспомогательная функция для создания тестовых данных ─────────────────────

def insert_user(
    conn: sqlite3.Connection,
    telegram_id: int = 100001,
    name: str = "Test User",
    active: int = 1,
) -> int:
    """
    Вставляет пользователя в user_profile и возвращает его внутренний id (INTEGER PK).
    """
    conn.execute(
        "INSERT OR IGNORE INTO user_profile (telegram_id, name, active) VALUES (?, ?, ?)",
        (telegram_id, name, active),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM user_profile WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    return row["id"]
