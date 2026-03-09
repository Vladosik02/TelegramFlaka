"""
db/queries/stats.py — Статистика и агрегаты.
"""
import datetime
import logging
from db.connection import get_connection

logger = logging.getLogger(__name__)


def save_weekly_summary(user_id: int, week_start: str, stats: dict,
                         summary_text: str = None) -> None:
    conn = get_connection()
    conn.execute(
        """INSERT OR REPLACE INTO weekly_summaries
           (user_id, week_start, workouts_done, workouts_total,
            avg_intensity, avg_sleep, avg_energy, total_steps, summary_text)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (user_id, week_start,
         stats.get("workouts_done", 0), stats.get("workouts_total", 0),
         stats.get("avg_intensity"), stats.get("avg_sleep"),
         stats.get("avg_energy"), stats.get("total_steps"),
         summary_text)
    )
    conn.commit()


def get_last_n_weeks(user_id: int, n: int = 4) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM weekly_summaries WHERE user_id = ? ORDER BY week_start DESC LIMIT ?",
        (user_id, n)
    ).fetchall()
    return [dict(r) for r in rows]


def get_all_time_stats(user_id: int) -> dict:
    conn = get_connection()
    row = conn.execute(
        """SELECT
               COUNT(*) as total_workouts,
               SUM(completed) as done_workouts,
               SUM(duration_min) as total_minutes,
               AVG(intensity) as avg_intensity
           FROM workouts WHERE user_id = ?""",
        (user_id,)
    ).fetchone()
    first = conn.execute(
        "SELECT MIN(date) as first_date FROM workouts WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    return {
        "total_workouts": row["total_workouts"] or 0,
        "done_workouts": row["done_workouts"] or 0,
        "total_minutes": row["total_minutes"] or 0,
        "avg_intensity": round(row["avg_intensity"] or 0, 1),
        "first_date": first["first_date"],
    }


def get_days_since_last_active(user_id: int) -> int | None:
    """Сколько дней с последней активности. None если никогда."""
    conn = get_connection()
    row = conn.execute(
        "SELECT last_active FROM user_profile WHERE id = ?",
        (user_id,)
    ).fetchone()
    if not row or not row["last_active"]:
        return None
    last = datetime.datetime.fromisoformat(row["last_active"])
    delta = datetime.datetime.now() - last
    return delta.days
