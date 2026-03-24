"""
db/queries/training_plan.py — CRUD для таблицы training_plan (Фаза 8.3).

Жизненный цикл плана:
  draft   → создаётся AI
  active  → отправлен пользователю, идёт неделя
  archived → воскресенье 19:00, данные уходят в monthly_summary

plan_id = "PLN-{user_id}-{YYYYWW}"
"""
import datetime
import json
import logging
from db.connection import get_connection

logger = logging.getLogger(__name__)


# ─── Утилиты ──────────────────────────────────────────────────────────────────

def get_current_week_start() -> str:
    """Возвращает дату текущего понедельника (YYYY-MM-DD)."""
    today = datetime.date.today()
    mon = today - datetime.timedelta(days=today.weekday())
    return mon.isoformat()


def get_next_week_start() -> str:
    """Возвращает дату следующего понедельника (YYYY-MM-DD)."""
    today = datetime.date.today()
    mon = today - datetime.timedelta(days=today.weekday())
    nxt = mon + datetime.timedelta(days=7)
    return nxt.isoformat()


def make_plan_id(user_id: int, week_start: str) -> str:
    """
    Генерирует уникальный plan_id: PLN-{user_id}-{YYYYWW}.
    Например: PLN-1-202612 (пользователь 1, 12-я неделя 2026).
    """
    d = datetime.date.fromisoformat(week_start)
    iso = d.isocalendar()
    return f"PLN-{user_id}-{iso.year:04d}{iso.week:02d}"


# ─── Запись ────────────────────────────────────────────────────────────────────

def save_training_plan(
    user_id: int,
    week_start: str,
    plan_json_str: str,             # JSON-строка с массивом дней
    *,
    ai_rationale: str | None = None,
    fitness_score_snap: float | None = None,
    sleep_avg_snap: float | None = None,
    energy_avg_snap: float | None = None,
    calories_target: int | None = None,
    season: str | None = None,
    workouts_planned: int = 0,
    volume_total: int | None = None,
    intensity_avg: float | None = None,
    status: str = "active",
) -> str:
    """
    Сохраняет план (INSERT OR REPLACE). Возвращает plan_id.
    Существующий план той же недели заменяется (корректировка).
    """
    conn = get_connection()
    plan_id = make_plan_id(user_id, week_start)

    conn.execute(
        """INSERT OR REPLACE INTO training_plan
           (plan_id, user_id, week_start, status,
            fitness_score_snap, sleep_avg_snap, energy_avg_snap,
            calories_target, season,
            plan_json, ai_rationale,
            workouts_planned, workouts_completed,
            volume_total, intensity_avg,
            updated_at)
           VALUES (?,?,?,?, ?,?,?, ?,?, ?,?, ?,0, ?,?, datetime('now'))""",
        (
            plan_id, user_id, week_start, status,
            fitness_score_snap, sleep_avg_snap, energy_avg_snap,
            calories_target, season,
            plan_json_str, ai_rationale,
            workouts_planned,
            volume_total, intensity_avg,
        ),
    )
    conn.commit()
    logger.info(f"[PLAN] Saved plan_id={plan_id} user_id={user_id}")
    return plan_id


def update_plan_json(plan_id: str, plan_json_str: str, ai_rationale: str | None = None) -> None:
    """Обновляет JSON плана (AI-корректировка по запросу пользователя)."""
    conn = get_connection()
    if ai_rationale is not None:
        conn.execute(
            "UPDATE training_plan SET plan_json=?, ai_rationale=?, updated_at=datetime('now') WHERE plan_id=?",
            (plan_json_str, ai_rationale, plan_id),
        )
    else:
        conn.execute(
            "UPDATE training_plan SET plan_json=?, updated_at=datetime('now') WHERE plan_id=?",
            (plan_json_str, plan_id),
        )
    conn.commit()
    logger.info(f"[PLAN] Updated plan_json for plan_id={plan_id}")


def mark_plan_day_completed(user_id: int, date: str) -> bool:
    """
    Помечает день `date` как completed=True в plan_json активного плана.
    Одновременно инкрементирует workouts_completed счётчик.
    Возвращает True если день найден и обновлён, False иначе.
    """
    plan = get_active_plan(user_id)
    if not plan:
        return False

    try:
        days = json.loads(plan["plan_json"])
    except Exception:
        return False

    updated = False
    for day in days:
        if day.get("date") == date and day.get("type") not in ("rest", "recovery"):
            if not day.get("completed"):
                day["completed"] = True
                updated = True
            break

    if not updated:
        return False

    try:
        new_json = json.dumps(days, ensure_ascii=False)
        conn = get_connection()
        conn.execute(
            """UPDATE training_plan
               SET plan_json = ?,
                   workouts_completed = workouts_completed + 1,
                   updated_at = datetime('now')
               WHERE plan_id = ? AND status = 'active'""",
            (new_json, plan["plan_id"]),
        )
        conn.commit()
        logger.info(f"[PLAN] Day {date} marked completed for user_id={user_id}")
        return True
    except Exception as e:
        logger.warning(f"[PLAN] mark_plan_day_completed failed for user_id={user_id}: {e}")
        return False


def increment_workouts_completed(user_id: int, week_start: str) -> None:
    """
    Увеличивает счётчик завершённых тренировок активного плана.
    Вызывается из writer.py когда AI отмечает тренировку как completed.
    """
    conn = get_connection()
    plan_id = make_plan_id(user_id, week_start)
    conn.execute(
        """UPDATE training_plan
           SET workouts_completed = workouts_completed + 1,
               updated_at = datetime('now')
           WHERE plan_id = ? AND status = 'active'""",
        (plan_id,),
    )
    conn.commit()


# ─── Чтение ────────────────────────────────────────────────────────────────────

def get_active_plan(user_id: int) -> dict | None:
    """Возвращает текущий активный план пользователя или None."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM training_plan WHERE user_id = ? AND status = 'active' ORDER BY week_start DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


def get_plan_by_id(plan_id: str) -> dict | None:
    """Возвращает план по plan_id."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM training_plan WHERE plan_id = ?",
        (plan_id,),
    ).fetchone()
    return dict(row) if row else None


def get_last_plan(user_id: int) -> dict | None:
    """Возвращает последний план (активный или архивный)."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM training_plan WHERE user_id = ? ORDER BY week_start DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


def get_archived_plans(user_id: int, limit: int = 4) -> list[dict]:
    """Последние N архивных планов — используются в monthly_summary."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM training_plan
           WHERE user_id = ? AND status = 'archived'
           ORDER BY week_start DESC LIMIT ?""",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ─── Архивация ─────────────────────────────────────────────────────────────────

def archive_plan(
    plan_id: str,
    workouts_completed: int,
    completion_pct: float,
) -> None:
    """
    Архивирует план: status → 'archived', заполняет статистику выполнения.
    Вызывается каждое воскресенье в 19:00 из scheduler.
    """
    conn = get_connection()
    conn.execute(
        """UPDATE training_plan
           SET status = 'archived',
               workouts_completed = ?,
               completion_pct = ?,
               archived_at = datetime('now'),
               updated_at = datetime('now')
           WHERE plan_id = ?""",
        (workouts_completed, completion_pct, plan_id),
    )
    conn.commit()
    logger.info(
        f"[PLAN] Archived plan_id={plan_id} "
        f"completed={workouts_completed} pct={completion_pct:.0f}%"
    )


# ─── Агрегаты для monthly_summary ─────────────────────────────────────────────

def get_monthly_plan_stats(user_id: int, year: int, month: int) -> dict:
    """
    Агрегирует данные архивных планов за календарный месяц.
    Вызывается из db/queries/stats.py → get_monthly_stats() вставляет plan_stats
    в monthly_summary для обогащения контекста.

    Возвращает:
      plans_count       — кол-во архивных планов за месяц
      avg_completion    — среднее % выполнения планов
      volume_trend      — суммарный объём (мин) по архивным планам
      best_plan_pct     — лучший план месяца (% выполнения)
    """
    conn = get_connection()
    month_start = f"{year:04d}-{month:02d}-01"
    if month == 12:
        month_end = f"{year + 1:04d}-01-01"
    else:
        month_end = f"{year:04d}-{month + 1:02d}-01"

    rows = conn.execute(
        """SELECT completion_pct, workouts_completed, workouts_planned, volume_total
           FROM training_plan
           WHERE user_id = ? AND status = 'archived'
             AND week_start >= ? AND week_start < ?""",
        (user_id, month_start, month_end),
    ).fetchall()

    if not rows:
        return {
            "plans_count": 0,
            "avg_completion": None,
            "volume_trend": None,
            "best_plan_pct": None,
        }

    pcts = [r["completion_pct"] for r in rows if r["completion_pct"] is not None]
    vols = [r["volume_total"] for r in rows if r["volume_total"] is not None]

    return {
        "plans_count": len(rows),
        "avg_completion": round(sum(pcts) / len(pcts), 1) if pcts else None,
        "volume_trend": sum(vols) if vols else None,
        "best_plan_pct": round(max(pcts), 1) if pcts else None,
    }
