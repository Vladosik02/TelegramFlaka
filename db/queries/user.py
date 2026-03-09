"""
db/queries/user.py — CRUD для user_profile.
"""
import logging
from db.connection import get_connection

logger = logging.getLogger(__name__)


def get_user(telegram_id: int) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM user_profile WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    return dict(row) if row else None


def create_user(telegram_id: int, name: str = None) -> dict:
    conn = get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO user_profile (telegram_id, name) VALUES (?, ?)",
        (telegram_id, name)
    )
    conn.commit()
    return get_user(telegram_id)


def update_user(telegram_id: int, **fields) -> None:
    if not fields:
        return
    conn = get_connection()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [telegram_id]
    conn.execute(
        f"UPDATE user_profile SET {set_clause} WHERE telegram_id = ?", values
    )
    conn.commit()


def deactivate_user(telegram_id: int) -> None:
    import datetime
    conn = get_connection()
    conn.execute(
        "UPDATE user_profile SET active = 0, paused_at = ? WHERE telegram_id = ?",
        (datetime.datetime.now().isoformat(), telegram_id)
    )
    conn.commit()


def activate_user(telegram_id: int) -> None:
    import datetime
    conn = get_connection()
    now = datetime.datetime.now().isoformat()
    conn.execute(
        "UPDATE user_profile SET active = 1, paused_at = NULL, last_active = ? WHERE telegram_id = ?",
        (now, telegram_id)
    )
    conn.commit()


def touch_last_active(telegram_id: int) -> None:
    import datetime
    conn = get_connection()
    conn.execute(
        "UPDATE user_profile SET last_active = ? WHERE telegram_id = ?",
        (datetime.datetime.now().isoformat(), telegram_id)
    )
    conn.commit()
