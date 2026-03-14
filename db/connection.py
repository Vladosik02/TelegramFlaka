"""
db/connection.py — Подключение к SQLite. Singleton.
"""
import sqlite3
import logging
import os
from config import DB_PATH, BASE_DIR

logger = logging.getLogger(__name__)
_conn: sqlite3.Connection | None = None


def get_connection() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
        logger.info(f"SQLite connected: {DB_PATH}")
    return _conn


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Безопасные инкрементальные миграции схемы.
    Каждый ALTER TABLE обёрнут в try/except — если колонка уже есть, ошибка игнорируется.
    """
    migrations = [
        # v1.1 — preferred_time для тренировочных предпочтений
        "ALTER TABLE memory_training ADD COLUMN preferred_time TEXT DEFAULT 'flexible'",
        # v1.2 — место тренировки в профиле
        "ALTER TABLE user_profile ADD COLUMN training_location TEXT DEFAULT 'flexible'",
        # v1.3 — стартовые физические показатели (базовая линия)
        "ALTER TABLE memory_athlete ADD COLUMN baseline_pushups INTEGER",
        "ALTER TABLE memory_athlete ADD COLUMN baseline_squats INTEGER",
        "ALTER TABLE memory_athlete ADD COLUMN baseline_plank_sec INTEGER",
        # v1.4 — привязка тренировок к плану (Фаза 8.3)
        "ALTER TABLE workouts ADD COLUMN plan_id TEXT REFERENCES training_plan(plan_id)",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
            conn.commit()
            logger.info(f"Migration applied: {sql[:60]}...")
        except Exception:
            pass  # колонка уже существует — норма


def init_db() -> None:
    """Создаёт таблицы из schema.sql если не существуют, затем запускает миграции."""
    conn = get_connection()
    schema_path = os.path.join(BASE_DIR, "db", "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        sql = f.read()
    conn.executescript(sql)
    conn.commit()
    _run_migrations(conn)
    logger.info("DB schema initialised")


def close_connection() -> None:
    global _conn
    if _conn:
        _conn.close()
        _conn = None
        logger.info("SQLite connection closed")
