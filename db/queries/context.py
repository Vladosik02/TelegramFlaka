"""
db/queries/context.py — Чек-ины и история разговора.
"""
import logging
import datetime
from db.connection import get_connection

logger = logging.getLogger(__name__)


def get_or_create_checkin(user_id: int, date: str, time_slot: str) -> dict:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM checkins WHERE user_id = ? AND date = ? AND time_slot = ?",
        (user_id, date, time_slot)
    ).fetchone()
    if row:
        return dict(row)
    cur = conn.execute(
        "INSERT INTO checkins (user_id, date, time_slot) VALUES (?,?,?)",
        (user_id, date, time_slot)
    )
    conn.commit()
    return get_or_create_checkin(user_id, date, time_slot)


def update_checkin(checkin_id: int, **fields) -> None:
    if not fields:
        return
    conn = get_connection()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [checkin_id]
    conn.execute(f"UPDATE checkins SET {set_clause} WHERE id = ?", values)
    conn.commit()


def add_conversation_message(user_id: int, role: str, content: str,
                              checkin_id: int = None) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT INTO conversation_context (user_id, role, content, checkin_id) VALUES (?,?,?,?)",
        (user_id, role, content, checkin_id)
    )
    conn.commit()


def get_recent_conversation(user_id: int, limit: int = 10) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        """SELECT role, content FROM conversation_context
           WHERE user_id = ?
           ORDER BY created_at DESC LIMIT ?""",
        (user_id, limit)
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def count_conversation_messages(user_id: int) -> int:
    """Считает сколько сообщений накоплено в текущем контексте."""
    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM conversation_context WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    return row["cnt"] if row else 0


def get_last_message_time(user_id: int) -> datetime.datetime | None:
    """Возвращает время последнего сообщения пользователя (роль user)."""
    conn = get_connection()
    row = conn.execute(
        """SELECT created_at FROM conversation_context
           WHERE user_id = ? AND role = 'user'
           ORDER BY created_at DESC LIMIT 1""",
        (user_id,)
    ).fetchone()
    if not row:
        return None
    try:
        return datetime.datetime.fromisoformat(row["created_at"])
    except (ValueError, TypeError):
        return None


def get_all_conversation_messages(user_id: int) -> list[dict]:
    """Возвращает все сообщения без лимита (для подсчёта токенов)."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT role, content FROM conversation_context
           WHERE user_id = ?
           ORDER BY created_at ASC""",
        (user_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def clear_conversation(user_id: int) -> None:
    """Полная очистка контекста разговора (после суммаризации)."""
    conn = get_connection()
    conn.execute(
        "DELETE FROM conversation_context WHERE user_id = ?",
        (user_id,)
    )
    conn.commit()


def save_context_summary(user_id: int, summary: str) -> None:
    """Сохраняет сжатый контекст как первое сообщение новой сессии."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO conversation_context (user_id, role, content)
           VALUES (?, 'assistant', ?)""",
        (user_id, f"[SUMMARY] {summary}")
    )
    conn.commit()


def clear_old_context(user_id: int, keep_hours: int = 24) -> None:
    conn = get_connection()
    cutoff = (datetime.datetime.now() - datetime.timedelta(hours=keep_hours)).isoformat()
    conn.execute(
        "DELETE FROM conversation_context WHERE user_id = ? AND created_at < ?",
        (user_id, cutoff)
    )
    conn.commit()


def get_today_checkins(user_id: int) -> list[dict]:
    today = datetime.date.today().isoformat()
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM checkins WHERE user_id = ? AND date = ?",
        (user_id, today)
    ).fetchall()
    return [dict(r) for r in rows]


def get_pending_reminders(user_id: int) -> list[dict]:
    now = datetime.datetime.now().isoformat()
    conn = get_connection()
    rows = conn.execute(
        """SELECT r.*, c.time_slot FROM reminders r
           LEFT JOIN checkins c ON c.id = r.checkin_id
           WHERE r.user_id = ? AND r.status = 'pending' AND r.scheduled_at <= ?""",
        (user_id, now)
    ).fetchall()
    return [dict(r) for r in rows]


def mark_reminder_sent(reminder_id: int) -> None:
    conn = get_connection()
    now = datetime.datetime.now().isoformat()
    conn.execute(
        "UPDATE reminders SET status = 'sent', sent_at = ? WHERE id = ?",
        (now, reminder_id)
    )
    conn.commit()


def schedule_reminder(user_id: int, checkin_id: int, scheduled_at: str) -> int:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO reminders (user_id, checkin_id, scheduled_at) VALUES (?,?,?)",
        (user_id, checkin_id, scheduled_at)
    )
    conn.commit()
    return cur.lastrowid
