"""
tests/conftest.py — Общие фикстуры для всех тестов.

Стратегия изоляции:
  • Каждый тест работает с in-memory SQLite (не трогает data/trainer.db).
  • get_connection патчится в КАЖДОМ модуле, который его импортирует
    ('from db.connection import get_connection' создаёт локальную ссылку
     — патч db.connection не затрагивает её).
  • Вспомогательная функция insert_user создаёт тестового пользователя.
"""
import sqlite3
import datetime
import os
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

    # Миграции (копия из db/connection.py)
    migrations = [
        "ALTER TABLE memory_training ADD COLUMN preferred_time TEXT DEFAULT 'flexible'",
        "ALTER TABLE user_profile ADD COLUMN training_location TEXT DEFAULT 'flexible'",
        "ALTER TABLE memory_athlete ADD COLUMN baseline_pushups INTEGER",
        "ALTER TABLE memory_athlete ADD COLUMN baseline_squats INTEGER",
        "ALTER TABLE memory_athlete ADD COLUMN baseline_plank_sec INTEGER",
        "ALTER TABLE workouts ADD COLUMN plan_id TEXT REFERENCES training_plan(plan_id)",
    ]
    for sql in migrations:
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
    _targets = [
        "db.connection.get_connection",
        "db.queries.user.get_connection",
        "db.queries.workouts.get_connection",
        "db.queries.fitness_metrics.get_connection",
        "db.queries.training_plan.get_connection",
        "db.queries.exercises.get_connection",
        "scheduler.nudges.get_connection",
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
