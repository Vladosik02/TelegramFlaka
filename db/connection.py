"""
db/connection.py — Подключение к SQLite. Singleton.
"""
import sqlite3
import logging
import os
import threading
from config import DB_PATH, BASE_DIR

logger = logging.getLogger(__name__)
_conn: sqlite3.Connection | None = None
_init_lock = threading.Lock()


def get_connection() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        with _init_lock:
            # Повторная проверка под локом — если другой поток уже создал.
            if _conn is None:
                os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
                conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")
                _conn = conn
                logger.info(f"SQLite connected: {DB_PATH}")
    return _conn


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Безопасные инкрементальные миграции схемы.
    Каждый ALTER TABLE обёрнут в try/except — если колонка уже есть, ошибка игнорируется.
    Список миграций — в db/migrations.py (общий с тестами).
    """
    from db.migrations import MIGRATIONS
    for sql in MIGRATIONS:
        try:
            conn.execute(sql)
            conn.commit()
            logger.info("Migration applied: %s...", sql[:60])
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if "duplicate column" in msg or "already exists" in msg:
                logger.debug("Migration skipped (already applied): %s...", sql[:60])
                continue
            logger.error("Migration FAILED: %s — %s", sql[:60], e)
            raise


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
