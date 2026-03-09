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
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
        logger.info(f"SQLite connected: {DB_PATH}")
    return _conn


def init_db() -> None:
    """Создаёт таблицы из schema.sql если не существуют."""
    conn = get_connection()
    schema_path = os.path.join(BASE_DIR, "db", "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        sql = f.read()
    conn.executescript(sql)
    conn.commit()
    logger.info("DB schema initialised")


def close_connection() -> None:
    global _conn
    if _conn:
        _conn.close()
        _conn = None
        logger.info("SQLite connection closed")
