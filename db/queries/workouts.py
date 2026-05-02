"""
db/queries/workouts.py — Тренировки и метрики.
"""
import logging
import datetime
import threading
from db.connection import get_connection

logger = logging.getLogger(__name__)

# Сериализация SELECT-then-INSERT/UPDATE между потоками. У нас singleton
# sqlite3-соединение с check_same_thread=False — Python-уровневая гонка
# возможна (handler в asyncio + APScheduler через to_thread). UNIQUE-
# индекс не подходит: workouts.id есть FK-источник для exercise_results,
# дедупликация существующих дубликатов под FK-каскадом — не one-shot SQL.
_upsert_lock = threading.Lock()


def log_workout(user_id: int, date: str, mode: str, workout_type: str = None,
                duration_min: int = None, intensity: int = None,
                exercises: str = None, notes: str = None, completed: bool = True) -> int:
    """
    Upsert тренировки по (user_id, date, type).
    Если запись за дату с тем же типом уже есть — обновляет переданные поля,
    не создавая дубликат. Защита от двойной записи: guided flow + агент.
    """
    with _upsert_lock:
        conn = get_connection()
        existing = conn.execute(
            "SELECT id FROM workouts WHERE user_id = ? AND date = ? AND type IS ?",
            (user_id, date, workout_type)
        ).fetchone()

        if existing:
            updates: dict = {"completed": int(completed), "mode": mode}
            if duration_min is not None: updates["duration_min"] = duration_min
            if intensity    is not None: updates["intensity"]    = intensity
            if exercises    is not None: updates["exercises"]    = exercises
            if notes        is not None: updates["notes"]        = notes
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(
                f"UPDATE workouts SET {set_clause} WHERE user_id = ? AND date = ? AND type IS ?",
                list(updates.values()) + [user_id, date, workout_type]
            )
            conn.commit()
            logger.info(f"[WORKOUT] Updated existing record user_id={user_id} date={date} type={workout_type}")
            return existing["id"]
        else:
            cur = conn.execute(
                """INSERT INTO workouts
                   (user_id, date, mode, type, duration_min, intensity, exercises, notes, completed)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (user_id, date, mode, workout_type, duration_min, intensity, exercises, notes, int(completed))
            )
            conn.commit()
            logger.info(f"[WORKOUT] Inserted new record user_id={user_id} date={date} type={workout_type}")
            return cur.lastrowid


def log_metrics(user_id: int, date: str, weight_kg: float = None,
                sleep_hours: float = None, energy: int = None,
                mood: int = None, water_liters: float = None,
                steps: int = None, notes: str = None) -> int:
    """
    Создаёт или обновляет запись метрик за день (upsert по user_id + date).
    Если запись за дату уже есть — обновляет только переданные (не-None) поля,
    не затирая существующие данные. Защита от дублей при retry.
    """
    with _upsert_lock:
        conn = get_connection()
        existing = conn.execute(
            "SELECT id FROM metrics WHERE user_id = ? AND date = ?",
            (user_id, date)
        ).fetchone()

        if existing:
            # Обновляем только поля, которые явно переданы (не None)
            updates: dict = {}
            if weight_kg   is not None: updates["weight_kg"]    = weight_kg
            if sleep_hours is not None: updates["sleep_hours"]  = sleep_hours
            if energy      is not None: updates["energy"]       = energy
            if mood        is not None: updates["mood"]         = mood
            if water_liters is not None: updates["water_liters"] = water_liters
            if steps       is not None: updates["steps"]        = steps
            if notes       is not None: updates["notes"]        = notes
            if updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE metrics SET {set_clause} WHERE user_id = ? AND date = ?",
                    list(updates.values()) + [user_id, date]
                )
                conn.commit()
            return existing["id"]
        else:
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
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    most_recent = datetime.date.fromisoformat(rows[0]["date"])
    # Стрик обрывается если последняя тренировка раньше вчера
    if most_recent < yesterday:
        return 0
    streak = 0
    check = most_recent
    for row in rows:
        d = datetime.date.fromisoformat(row["date"])
        if d == check:
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
