"""
db/queries/usage.py — Логирование и статистика использования Anthropic API.

Хранит токены, стоимость и время ответа для каждого AI-вызова.
Используется для:
  • Сноски под каждым ответом бота (время + стоимость)
  • /costs — личная статистика расходов пользователя
  • /admin → Расходы — сводка по всем пользователям
"""
import datetime
import logging
from db.connection import get_connection

logger = logging.getLogger(__name__)

# ─── Цены Anthropic ($ за 1 млн токенов) ─────────────────────────────────────
_PRICING: dict[str, dict] = {
    "claude-sonnet-4-20250514": {
        "input":        3.00,
        "output":      15.00,
        "cache_read":   0.30,
        "cache_write":  3.75,
    },
    "claude-haiku-4-5-20251001": {
        "input":       0.80,
        "output":      4.00,
        "cache_read":  0.08,
        "cache_write": 1.00,
    },
}
# Fallback — Sonnet
_DEFAULT_PRICING = _PRICING["claude-sonnet-4-20250514"]


# ─── Расчёт стоимости ─────────────────────────────────────────────────────────

def calc_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read: int = 0,
    cache_write: int = 0,
) -> float:
    """Возвращает стоимость в USD."""
    p = _PRICING.get(model, _DEFAULT_PRICING)
    return (
        input_tokens  * p["input"]       / 1_000_000
        + output_tokens * p["output"]    / 1_000_000
        + cache_read    * p["cache_read"]  / 1_000_000
        + cache_write   * p["cache_write"] / 1_000_000
    )


# ─── Запись в БД ──────────────────────────────────────────────────────────────

def log_usage(
    user_id: int,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read: int = 0,
    cache_write: int = 0,
    response_time_sec: float | None = None,
    call_type: str = "chat",
) -> float:
    """
    Логирует один API-вызов в таблицу ai_usage_log.
    Возвращает стоимость в USD.
    """
    cost = calc_cost(model, input_tokens, output_tokens, cache_read, cache_write)
    try:
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO ai_usage_log
                (user_id, timestamp, model,
                 input_tokens, output_tokens,
                 cache_read_tokens, cache_write_tokens,
                 cost_usd, response_time_sec, call_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                datetime.datetime.now().isoformat(),
                model,
                input_tokens,
                output_tokens,
                cache_read,
                cache_write,
                cost,
                response_time_sec,
                call_type,
            ),
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"[USAGE] Failed to log usage for user={user_id}: {e}")
    return cost


# ─── Запросы статистики ───────────────────────────────────────────────────────

def _query_period(user_id: int, since: str) -> dict:
    """Агрегация расходов за период (since — ISO-дата)."""
    conn = get_connection()
    row = conn.execute(
        """
        SELECT
            COALESCE(SUM(cost_usd), 0)                          AS cost,
            COALESCE(SUM(input_tokens + output_tokens), 0)      AS tokens,
            COALESCE(SUM(input_tokens), 0)                      AS input_tokens,
            COALESCE(SUM(output_tokens), 0)                     AS output_tokens,
            COALESCE(SUM(cache_read_tokens), 0)                 AS cache_read,
            COUNT(*)                                            AS calls,
            COALESCE(AVG(response_time_sec), 0)                 AS avg_time
        FROM ai_usage_log
        WHERE user_id = ? AND timestamp >= ?
        """,
        (user_id, since),
    ).fetchone()
    return dict(row) if row else {
        "cost": 0, "tokens": 0, "input_tokens": 0,
        "output_tokens": 0, "cache_read": 0, "calls": 0, "avg_time": 0,
    }


def get_usage_stats(user_id: int) -> dict:
    """
    Возвращает статистику расходов пользователя по периодам:
    today, week (7 дн.), month (30 дн.), all (всё время).
    """
    today    = datetime.date.today().isoformat()
    week_ago = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    month_ago = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    return {
        "today": _query_period(user_id, today),
        "week":  _query_period(user_id, week_ago),
        "month": _query_period(user_id, month_ago),
        "all":   _query_period(user_id, "2000-01-01"),
    }


def get_daily_breakdown(user_id: int, days: int = 7) -> list[dict]:
    """Разбивка расходов по дням (для графика/таблицы)."""
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT
            DATE(timestamp) AS day,
            COALESCE(SUM(cost_usd), 0)   AS cost,
            COUNT(*)                      AS calls
        FROM ai_usage_log
        WHERE user_id = ? AND timestamp >= ?
        GROUP BY day
        ORDER BY day ASC
        """,
        (user_id, since),
    ).fetchall()
    return [dict(r) for r in rows]


# ─── Статистика для админа ────────────────────────────────────────────────────

def get_all_users_usage(since_days: int = 30) -> list[dict]:
    """
    Топ пользователей по расходам за последние N дней.
    Используется в /admin → Расходы.
    """
    since = (datetime.date.today() - datetime.timedelta(days=since_days)).isoformat()
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT
            u.name,
            u.telegram_id,
            COALESCE(SUM(l.cost_usd), 0)                     AS total_cost,
            COALESCE(SUM(l.input_tokens + l.output_tokens), 0) AS total_tokens,
            COUNT(l.id)                                        AS total_calls
        FROM user_profile u
        LEFT JOIN ai_usage_log l
            ON l.user_id = u.id AND l.timestamp >= ?
        WHERE u.active = 1
        GROUP BY u.id
        ORDER BY total_cost DESC
        """,
        (since,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_global_usage_stats(since_days: int = 30) -> dict:
    """Суммарная статистика всех пользователей (для admin overview)."""
    since = (datetime.date.today() - datetime.timedelta(days=since_days)).isoformat()
    conn = get_connection()
    row = conn.execute(
        """
        SELECT
            COALESCE(SUM(cost_usd), 0)                     AS total_cost,
            COALESCE(SUM(input_tokens + output_tokens), 0) AS total_tokens,
            COUNT(*)                                        AS total_calls,
            COUNT(DISTINCT user_id)                        AS unique_users
        FROM ai_usage_log
        WHERE timestamp >= ?
        """,
        (since,),
    ).fetchone()
    return dict(row) if row else {
        "total_cost": 0, "total_tokens": 0, "total_calls": 0, "unique_users": 0,
    }
