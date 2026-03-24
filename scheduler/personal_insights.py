"""
scheduler/personal_insights.py — Персональные корреляции из твоих данных.

Раз в неделю (воскресенье, 20:45) анализирует последние 60 дней данных
пользователя и находит самую сильную личную закономерность:
  • Сон → интенсивность следующей тренировки
  • Белок → интенсивность тренировки того же дня
  • Дни отдыха перед тренировкой → интенсивность

Правила выбора инсайта:
  • Минимум 5 наблюдений в каждой группе (иначе нет смысла)
  • Разница не менее MIN_EFFECT_PCT (8%) — только значимые паттерны
  • Приоритет: сон > белок > отдых (по убыванию надёжности данных)

Ноль дополнительных API-вызовов. Строго rule-based.
"""
from __future__ import annotations

import logging
import datetime
from typing import Optional

from db.connection import get_connection
from db.queries.user import get_user

logger = logging.getLogger(__name__)

# ─── Константы ────────────────────────────────────────────────────────────────

ANALYSIS_DAYS = 60          # Окно анализа (дней)
MIN_GROUP_SIZE = 5          # Минимум наблюдений в каждой группе
MIN_EFFECT_PCT = 8.0        # Минимальная разница между группами (%)
SLEEP_THRESHOLD = 7.5       # Граница «хороший сон» (часов)
PROTEIN_HIT_RATIO = 0.90    # Белок: % от цели для «попадания»


# ─── SQL-запросы ──────────────────────────────────────────────────────────────

_SQL_SLEEP_INTENSITY = """
    SELECT m.sleep_hours, w.intensity
    FROM   metrics m
    JOIN   workouts w
           ON  w.user_id = m.user_id
           AND w.date    = DATE(m.date, '+1 day')
    WHERE  m.user_id     = :uid
      AND  w.user_id     = :uid
      AND  m.date        >= DATE('now', :since)
      AND  m.sleep_hours IS NOT NULL
      AND  w.intensity   IS NOT NULL
      AND  w.type        != 'rest'
    ORDER  BY m.date DESC
"""

_SQL_PROTEIN_INTENSITY = """
    SELECT n.protein_g, w.intensity
    FROM   nutrition_log n
    JOIN   workouts w
           ON  w.user_id = n.user_id
           AND w.date    = n.date
    WHERE  n.user_id     = :uid
      AND  w.user_id     = :uid
      AND  n.date        >= DATE('now', :since)
      AND  n.protein_g   IS NOT NULL
      AND  w.intensity   IS NOT NULL
      AND  w.type        != 'rest'
    ORDER  BY n.date DESC
"""

_SQL_WORKOUTS_DATES = """
    SELECT date, intensity, type
    FROM   workouts
    WHERE  user_id  = :uid
      AND  date    >= DATE('now', :since)
      AND  type    != 'rest'
      AND  intensity IS NOT NULL
    ORDER  BY date ASC
"""

_SQL_PROTEIN_GOAL = """
    SELECT protein_g
    FROM   memory_nutrition
    WHERE  user_id = :uid
"""


# ─── Сбор данных ──────────────────────────────────────────────────────────────

def _get_sleep_intensity_pairs(user_id: int, days: int = ANALYSIS_DAYS) -> list[tuple[float, int]]:
    """Возвращает [(sleep_hours, next_day_intensity), ...] за последние `days` дней."""
    since = f"-{days} days"
    try:
        conn = get_connection()
        rows = conn.execute(_SQL_SLEEP_INTENSITY, {"uid": user_id, "since": since}).fetchall()
        return [(float(r["sleep_hours"]), int(r["intensity"])) for r in rows]
    except Exception as e:
        logger.warning(f"[INSIGHTS] sleep_intensity query failed for uid={user_id}: {e}")
        return []


def _get_protein_intensity_pairs(
    user_id: int,
    protein_goal: int,
    days: int = ANALYSIS_DAYS,
) -> list[tuple[float, int]]:
    """Возвращает [(protein_g, intensity), ...] за последние `days` дней."""
    since = f"-{days} days"
    try:
        conn = get_connection()
        rows = conn.execute(_SQL_PROTEIN_INTENSITY, {"uid": user_id, "since": since}).fetchall()
        return [(float(r["protein_g"]), int(r["intensity"])) for r in rows]
    except Exception as e:
        logger.warning(f"[INSIGHTS] protein_intensity query failed for uid={user_id}: {e}")
        return []


def _get_rest_days_intensity_pairs(user_id: int, days: int = ANALYSIS_DAYS) -> list[tuple[int, int]]:
    """
    Возвращает [(rest_days_before, intensity), ...].
    rest_days_before = кол-во дней без тренировки до данной тренировки (0, 1, 2+).
    """
    since = f"-{days} days"
    try:
        conn = get_connection()
        rows = conn.execute(_SQL_WORKOUTS_DATES, {"uid": user_id, "since": since}).fetchall()
    except Exception as e:
        logger.warning(f"[INSIGHTS] rest_days query failed for uid={user_id}: {e}")
        return []

    if len(rows) < 2:
        return []

    result: list[tuple[int, int]] = []
    for i, row in enumerate(rows[1:], start=1):
        curr_date = datetime.date.fromisoformat(row["date"])
        prev_date = datetime.date.fromisoformat(rows[i - 1]["date"])
        gap = (curr_date - prev_date).days - 1   # дней отдыха между тренировками
        gap = max(0, gap)                          # не бывает отрицательным
        result.append((gap, int(row["intensity"])))

    return result


def _get_protein_goal(user_id: int) -> Optional[int]:
    """Читает целевое кол-во белка из memory_nutrition. Возвращает None если не задано."""
    try:
        conn = get_connection()
        row = conn.execute(_SQL_PROTEIN_GOAL, {"uid": user_id}).fetchone()
        if row and row["protein_g"]:
            return int(row["protein_g"])
    except Exception as e:
        logger.warning(f"[INSIGHTS] protein_goal query failed for uid={user_id}: {e}")
    return None


# ─── Статистика ───────────────────────────────────────────────────────────────

def _group_avg(
    pairs: list[tuple[float, int]],
    threshold: float,
) -> Optional[tuple[float, int, float, int]]:
    """
    Делит пары на две группы по threshold (x >= threshold → «выше»).
    Возвращает (avg_above, n_above, avg_below, n_below) или None если мало данных.
    """
    above = [y for x, y in pairs if x >= threshold]
    below = [y for x, y in pairs if x < threshold]

    if len(above) < MIN_GROUP_SIZE or len(below) < MIN_GROUP_SIZE:
        return None

    avg_above = sum(above) / len(above)
    avg_below = sum(below) / len(below)
    return avg_above, len(above), avg_below, len(below)


def _effect_pct(higher: float, lower: float) -> float:
    """Возвращает процентную разницу higher относительно lower."""
    if lower == 0:
        return 0.0
    return (higher - lower) / lower * 100.0


# ─── Формирование инсайтов ────────────────────────────────────────────────────

def _insight_sleep(user_id: int) -> Optional[str]:
    """Инсайт 1: сон ≥ SLEEP_THRESHOLD → интенсивность следующего дня."""
    pairs = _get_sleep_intensity_pairs(user_id)
    if not pairs:
        return None

    stats = _group_avg(pairs, SLEEP_THRESHOLD)
    if stats is None:
        return None

    avg_hi, n_hi, avg_lo, n_lo = stats
    if avg_hi <= avg_lo:
        return None                   # обратная зависимость — не интересно

    pct = _effect_pct(avg_hi, avg_lo)
    if pct < MIN_EFFECT_PCT:
        return None

    return (
        f"После {SLEEP_THRESHOLD:.0f}+ ч сна твоя интенсивность *на {pct:.0f}% выше* "
        f"({avg_hi:.1f}/10 vs {avg_lo:.1f}/10 — {n_hi + n_lo} тренировок)."
    )


def _insight_protein(user_id: int) -> Optional[str]:
    """Инсайт 2: белок ≥ цель*PROTEIN_HIT_RATIO → интенсивность того же дня."""
    goal = _get_protein_goal(user_id)
    if not goal:
        return None

    threshold = goal * PROTEIN_HIT_RATIO
    pairs = _get_protein_intensity_pairs(user_id, protein_goal=goal)
    if not pairs:
        return None

    stats = _group_avg(pairs, threshold)
    if stats is None:
        return None

    avg_hi, n_hi, avg_lo, n_lo = stats
    if avg_hi <= avg_lo:
        return None

    pct = _effect_pct(avg_hi, avg_lo)
    if pct < MIN_EFFECT_PCT:
        return None

    return (
        f"В дни, когда попадаешь в цель по белку ({goal}г+), "
        f"интенсивность *на {pct:.0f}% выше* "
        f"({avg_hi:.1f}/10 vs {avg_lo:.1f}/10 — {n_hi + n_lo} тренировок)."
    )


def _insight_rest(user_id: int) -> Optional[str]:
    """Инсайт 3: 2+ дня отдыха → интенсивность выше, чем 0-1 день."""
    pairs = _get_rest_days_intensity_pairs(user_id)
    if not pairs:
        return None

    # «2+ дня отдыха» vs «0–1 день отдыха»
    stats = _group_avg(pairs, threshold=2.0)
    if stats is None:
        return None

    avg_hi, n_hi, avg_lo, n_lo = stats
    if avg_hi <= avg_lo:
        return None

    pct = _effect_pct(avg_hi, avg_lo)
    if pct < MIN_EFFECT_PCT:
        return None

    return (
        f"После 2+ дней отдыха интенсивность *на {pct:.0f}% выше*, "
        f"чем после 0–1 дня "
        f"({avg_hi:.1f}/10 vs {avg_lo:.1f}/10 — {n_hi + n_lo} тренировок)."
    )


# ─── Публичный интерфейс ──────────────────────────────────────────────────────

def compute_personal_insight(user_id: int) -> Optional[str]:
    """
    Возвращает текст самого значимого персонального инсайта
    или None если данных недостаточно / нет значимых паттернов.

    Порядок приоритета: сон > белок > отдых.
    """
    for fn in (_insight_sleep, _insight_protein, _insight_rest):
        try:
            insight = fn(user_id)
            if insight:
                return insight
        except Exception as e:
            logger.warning(f"[INSIGHTS] {fn.__name__} failed for uid={user_id}: {e}")
    return None


def format_insight_message(insight_text: str) -> str:
    """Оборачивает текст инсайта в готовое сообщение для Telegram."""
    return (
        "💡 *Паттерн из твоих данных*\n"
        "━━━━━━━━━━━━━━━\n"
        f"{insight_text}\n\n"
        "_Не общий факт — это именно твои цифры за последние 2 месяца._"
    )


async def send_personal_insight(bot, telegram_id: int) -> None:
    """
    Вычисляет и отправляет персональный инсайт одному пользователю.
    Ничего не делает если данных недостаточно.
    """
    user = get_user(telegram_id)
    if not user or not user.get("active"):
        return

    insight = compute_personal_insight(user["id"])
    if not insight:
        logger.debug(f"[INSIGHTS] No insight for uid={user['id']} (insufficient data)")
        return

    text = format_insight_message(insight)
    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=text,
            parse_mode="Markdown",
        )
        logger.info(f"[INSIGHTS] Sent to tg_id={telegram_id}")
    except Exception as e:
        logger.error(f"[INSIGHTS] Send failed for tg_id={telegram_id}: {e}")


async def broadcast_personal_insights(bot) -> None:
    """Рассылает персональные инсайты всем активным пользователям."""
    from scheduler.logic import _get_all_active_users, _should_silence

    users = _get_all_active_users()
    sent = 0
    for user in users:
        if _should_silence(user):
            continue
        try:
            await send_personal_insight(bot, user["telegram_id"])
            sent += 1
        except Exception as e:
            logger.error(f"[INSIGHTS] Broadcast failed for {user['telegram_id']}: {e}")

    logger.info(f"[INSIGHTS] Broadcast done: {sent}/{len(users)} users processed")
