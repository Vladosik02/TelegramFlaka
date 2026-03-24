"""
db/queries/daily_summary.py — CRUD для AI-дневных резюме.

Таблица daily_summary:
  id, user_id, date, summary_text, workout_done, calories_met,
  mood_score, energy_score, sleep_hours, key_insight, generated_at

Дневное резюме генерируется APScheduler ночью (после вечернего чек-ина).
AI использует последние 3–7 дней как долгосрочную «персональную хронику».
"""
import logging
import datetime
from db.connection import get_connection

logger = logging.getLogger(__name__)


def upsert_daily_summary(
    user_id: int,
    date: str,
    summary_text: str,
    *,
    workout_done: bool = False,
    calories_met: bool = False,
    mood_score: int | None = None,
    energy_score: int | None = None,
    sleep_hours: float | None = None,
    key_insight: str | None = None,
) -> None:
    """
    Создаёт или обновляет дневное резюме (UNIQUE по user_id + date).
    Вызывается из scheduler после генерации AI-текста.
    """
    conn = get_connection()
    conn.execute("""
        INSERT INTO daily_summary
            (user_id, date, summary_text, workout_done, calories_met,
             mood_score, energy_score, sleep_hours, key_insight)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, date) DO UPDATE SET
            summary_text  = excluded.summary_text,
            workout_done  = excluded.workout_done,
            calories_met  = excluded.calories_met,
            mood_score    = excluded.mood_score,
            energy_score  = excluded.energy_score,
            sleep_hours   = excluded.sleep_hours,
            key_insight   = excluded.key_insight,
            generated_at  = datetime('now')
    """, (
        user_id, date, summary_text,
        1 if workout_done else 0,
        1 if calories_met else 0,
        mood_score, energy_score, sleep_hours, key_insight,
    ))
    conn.commit()
    logger.info(f"[DAILY_SUMMARY] upsert for user_id={user_id} date={date}")


def get_daily_summaries(user_id: int, days: int = 7) -> list[dict]:
    """
    Возвращает дневные резюме за последние N дней (от свежего к старому).
    Используется в context_builder для дополнения памяти AI.
    """
    conn = get_connection()
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT * FROM daily_summary
        WHERE user_id = ? AND date >= ?
        ORDER BY date DESC
    """, (user_id, since)).fetchall()
    return [dict(r) for r in rows]


def get_today_summary(user_id: int) -> dict | None:
    """Резюме за сегодня или None."""
    conn = get_connection()
    today = datetime.date.today().isoformat()
    row = conn.execute(
        "SELECT * FROM daily_summary WHERE user_id = ? AND date = ?",
        (user_id, today)
    ).fetchone()
    return dict(row) if row else None


def get_last_summary(user_id: int) -> dict | None:
    """Последнее доступное резюме (может быть не за сегодня)."""
    conn = get_connection()
    row = conn.execute("""
        SELECT * FROM daily_summary
        WHERE user_id = ?
        ORDER BY date DESC
        LIMIT 1
    """, (user_id,)).fetchone()
    return dict(row) if row else None


def count_summaries(user_id: int) -> int:
    """Сколько дневных резюме накоплено для данного пользователя."""
    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM daily_summary WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    return row["cnt"] if row else 0
