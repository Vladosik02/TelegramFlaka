"""
db/queries/monthly_summary.py — CRUD для AI-месячных резюме.

Таблица monthly_summary:
  id, user_id, month (YYYY-MM), workouts_done, workouts_total,
  avg_intensity, avg_sleep, avg_energy, avg_calories,
  best_exercise, best_pr_text, summary_text, trend_vs_prev,
  key_insight, generated_at

Месячное резюме генерируется APScheduler 1-го числа в 09:00
за ПРОШЕДШИЙ месяц. AI использует последние 3 месяца как
долгосрочную «хронику» — грузится только при analytics-контексте.
"""
import logging
import datetime
from db.connection import get_connection

logger = logging.getLogger(__name__)


def upsert_monthly_summary(
    user_id: int,
    month: str,
    *,
    workouts_done: int = 0,
    workouts_total: int = 0,
    avg_intensity: float | None = None,
    avg_sleep: float | None = None,
    avg_energy: float | None = None,
    avg_calories: int | None = None,
    best_exercise: str | None = None,
    best_pr_text: str | None = None,
    summary_text: str | None = None,
    trend_vs_prev: str | None = None,
    key_insight: str | None = None,
) -> None:
    """
    Создаёт или обновляет месячное резюме (UNIQUE по user_id + month).
    Вызывается из scheduler после генерации AI-текста.
    """
    conn = get_connection()
    conn.execute("""
        INSERT INTO monthly_summary
            (user_id, month, workouts_done, workouts_total,
             avg_intensity, avg_sleep, avg_energy, avg_calories,
             best_exercise, best_pr_text, summary_text,
             trend_vs_prev, key_insight)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, month) DO UPDATE SET
            workouts_done  = excluded.workouts_done,
            workouts_total = excluded.workouts_total,
            avg_intensity  = excluded.avg_intensity,
            avg_sleep      = excluded.avg_sleep,
            avg_energy     = excluded.avg_energy,
            avg_calories   = excluded.avg_calories,
            best_exercise  = excluded.best_exercise,
            best_pr_text   = excluded.best_pr_text,
            summary_text   = excluded.summary_text,
            trend_vs_prev  = excluded.trend_vs_prev,
            key_insight    = excluded.key_insight,
            generated_at   = datetime('now')
    """, (
        user_id, month,
        workouts_done, workouts_total,
        avg_intensity, avg_sleep, avg_energy, avg_calories,
        best_exercise, best_pr_text,
        summary_text, trend_vs_prev, key_insight,
    ))
    conn.commit()
    logger.info(f"[MONTHLY_SUMMARY] upsert for user_id={user_id} month={month}")


def get_monthly_summaries(user_id: int, months: int = 3) -> list[dict]:
    """
    Возвращает месячные резюме за последние N месяцев (от свежего к старому).
    Используется в context_builder для analytics-контекста.
    """
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM monthly_summary
        WHERE user_id = ?
        ORDER BY month DESC
        LIMIT ?
    """, (user_id, months)).fetchall()
    return [dict(r) for r in rows]


def get_last_monthly_summary(user_id: int) -> dict | None:
    """Последнее доступное месячное резюме или None."""
    conn = get_connection()
    row = conn.execute("""
        SELECT * FROM monthly_summary
        WHERE user_id = ?
        ORDER BY month DESC
        LIMIT 1
    """, (user_id,)).fetchone()
    return dict(row) if row else None


def get_month_summary(user_id: int, month: str) -> dict | None:
    """Резюме за конкретный месяц (YYYY-MM) или None."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM monthly_summary WHERE user_id = ? AND month = ?",
        (user_id, month)
    ).fetchone()
    return dict(row) if row else None


def count_monthly_summaries(user_id: int) -> int:
    """Сколько месячных резюме накоплено для данного пользователя."""
    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM monthly_summary WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    return row["cnt"] if row else 0
