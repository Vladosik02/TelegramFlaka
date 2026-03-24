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


def get_monthly_stats(user_id: int, year: int, month: int) -> dict:
    """
    Агрегация данных за конкретный календарный месяц.
    Используется generate_monthly_summary_for_user в scheduler/logic.py.

    Возвращает:
      workouts_done   — завершённых тренировок
      workouts_total  — всего записей (попыток)
      avg_intensity   — средняя интенсивность (только по завершённым)
      avg_sleep       — средний сон
      avg_energy      — средняя энергия
      avg_calories    — средние ккал/день (из nutrition_log, если есть)
      best_pr         — лучший PR за месяц: {"exercise": str, "text": str} | None
    """
    conn = get_connection()

    # Границы месяца
    month_start = f"{year:04d}-{month:02d}-01"
    if month == 12:
        month_end = f"{year + 1:04d}-01-01"
    else:
        month_end = f"{year:04d}-{month + 1:02d}-01"

    # Тренировки
    w = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(completed) as done,
            AVG(CASE WHEN completed = 1 THEN intensity END) as avg_intensity
        FROM workouts
        WHERE user_id = ? AND date >= ? AND date < ?
    """, (user_id, month_start, month_end)).fetchone()

    # Метрики (сон / энергия)
    m = conn.execute("""
        SELECT
            AVG(sleep_hours) as avg_sleep,
            AVG(energy) as avg_energy
        FROM metrics
        WHERE user_id = ? AND date >= ? AND date < ?
    """, (user_id, month_start, month_end)).fetchone()

    # Среднее питание (nutrition_log может быть пустым — обрабатываем тихо)
    avg_calories = None
    try:
        n = conn.execute("""
            SELECT AVG(calories) as avg_cal
            FROM nutrition_log
            WHERE user_id = ? AND date >= ? AND date < ?
              AND calories IS NOT NULL AND calories > 0
        """, (user_id, month_start, month_end)).fetchone()
        if n and n["avg_cal"]:
            avg_calories = round(n["avg_cal"])
    except Exception:
        pass

    # Лучший PR за месяц (по improvement_pct — самый впечатляющий прирост)
    best_pr = None
    try:
        pr_row = conn.execute("""
            SELECT exercise_name, record_value, record_type, improvement_pct
            FROM personal_records
            WHERE user_id = ? AND set_at >= ? AND set_at < ?
            ORDER BY improvement_pct DESC
            LIMIT 1
        """, (user_id, month_start, month_end)).fetchone()
        if pr_row:
            suffix_map = {"weight": "кг", "time": "сек", "reps": "пов"}
            suffix = suffix_map.get(pr_row["record_type"], "")
            pr_text = f"{pr_row['exercise_name']} {pr_row['record_value']}{suffix}"
            if pr_row["improvement_pct"]:
                pr_text += f" (+{pr_row['improvement_pct']:.1f}%)"
            best_pr = {"exercise": pr_row["exercise_name"], "text": pr_text}
    except Exception:
        pass

    return {
        "workouts_total": w["total"] or 0,
        "workouts_done": int(w["done"] or 0),
        "avg_intensity": round(w["avg_intensity"], 1) if w["avg_intensity"] else None,
        "avg_sleep": round(m["avg_sleep"], 1) if m["avg_sleep"] else None,
        "avg_energy": round(m["avg_energy"], 1) if m["avg_energy"] else None,
        "avg_calories": avg_calories,
        "best_pr": best_pr,
    }


def get_monthly_plan_stats(user_id: int, year: int, month: int) -> dict:
    """
    Агрегирует данные архивных тренировочных планов за календарный месяц.
    Используется generate_monthly_summary_for_user для обогащения AI-контекста.

    Возвращает:
      plans_count    — кол-во архивных планов за месяц
      avg_completion — среднее % выполнения (float | None)
      volume_trend   — суммарный объём минут (int | None)
      best_plan_pct  — % лучшего плана (float | None)
    """
    from db.queries.training_plan import get_monthly_plan_stats as _plan_stats
    return _plan_stats(user_id, year, month)


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
