"""
db/queries/workouts.py — Тренировки и метрики.
"""
import logging
import datetime
from db.connection import get_connection

logger = logging.getLogger(__name__)


def log_workout(user_id: int, date: str, mode: str, workout_type: str = None,
                duration_min: int = None, intensity: int = None,
                exercises: str = None, notes: str = None, completed: bool = True) -> int:
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO workouts
           (user_id, date, mode, type, duration_min, intensity, exercises, notes, completed)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (user_id, date, mode, workout_type, duration_min, intensity, exercises, notes, int(completed))
    )
    conn.commit()
    return cur.lastrowid


def log_metrics(user_id: int, date: str, weight_kg: float = None,
                sleep_hours: float = None, energy: int = None,
                mood: int = None, water_liters: float = None,
                steps: int = None, notes: str = None) -> int:
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO metrics
           (user_id, date, weight_kg, sleep_hours, energy, mood, water_liters, steps, notes)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (user_id, date, weight_kg, sleep_hours, energy, mood, water_liters, steps, notes)
    )
    conn.commit()
    return cur.lastrowid


def get_workouts_range(user_id: int, days: int = 7) -> list[dict]:
    conn = get_connection()
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT * FROM workouts WHERE user_id = ? AND date >= ? ORDER BY date DESC",
        (user_id, since)
    ).fetchall()
    return [dict(r) for r in rows]


def get_metrics_range(user_id: int, days: int = 7) -> list[dict]:
    conn = get_connection()
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT * FROM metrics WHERE user_id = ? AND date >= ? ORDER BY date DESC",
        (user_id, since)
    ).fetchall()
    return [dict(r) for r in rows]


def get_today_workout(user_id: int) -> dict | None:
    conn = get_connection()
    today = datetime.date.today().isoformat()
    row = conn.execute(
        "SELECT * FROM workouts WHERE user_id = ? AND date = ? ORDER BY id DESC LIMIT 1",
        (user_id, today)
    ).fetchone()
    return dict(row) if row else None


def get_streak(user_id: int) -> int:
    """Количество подряд дней с завершёнными тренировками."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT DISTINCT date FROM workouts WHERE user_id = ? AND completed = 1 ORDER BY date DESC",
        (user_id,)
    ).fetchall()
    if not rows:
        return 0
    streak = 0
    check = datetime.date.today()
    for row in rows:
        d = datetime.date.fromisoformat(row["date"])
        if d == check or d == check - datetime.timedelta(days=1):
            streak += 1
            check = d - datetime.timedelta(days=1)
        else:
            break
    return streak


def get_weekly_stats(user_id: int) -> dict:
    """Агрегация за последние 7 дней."""
    conn = get_connection()
    since = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    w = conn.execute(
        """SELECT COUNT(*) as total, SUM(completed) as done,
                  AVG(intensity) as avg_intensity, SUM(duration_min) as total_min
           FROM workouts WHERE user_id = ? AND date >= ?""",
        (user_id, since)
    ).fetchone()
    m = conn.execute(
        """SELECT AVG(sleep_hours) as avg_sleep, AVG(energy) as avg_energy,
                  AVG(mood) as avg_mood, SUM(steps) as total_steps
           FROM metrics WHERE user_id = ? AND date >= ?""",
        (user_id, since)
    ).fetchone()
    return {
        "workouts_total": w["total"] or 0,
        "workouts_done": w["done"] or 0,
        "avg_intensity": round(w["avg_intensity"] or 0, 1),
        "total_minutes": w["total_min"] or 0,
        "avg_sleep": round(m["avg_sleep"] or 0, 1),
        "avg_energy": round(m["avg_energy"] or 0, 1),
        "avg_mood": round(m["avg_mood"] or 0, 1),
        "total_steps": m["total_steps"] or 0,
    }
