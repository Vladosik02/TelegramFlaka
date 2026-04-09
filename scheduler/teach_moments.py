"""
scheduler/teach_moments.py — Контекстные мини-уроки ("Coach's Knowledge Drop").

Выбирает одну научно-обоснованную рекомендацию на основе данных дня:
тренировка (тип, интенсивность), питание (белок, калории), метрики (сон, энергия).

Интегрируется в send_night_summary() — после итога дня,
без дополнительных API-вызовов.

Частота: ~3 раза в неделю (чтобы не надоедать).
"""
import datetime
import hashlib
import logging
from typing import Optional

from lang import t_list

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# ЛОГИКА ВЫБОРА
# ═══════════════════════════════════════════════════════════════════════════

def _should_show_today(user_id: int) -> bool:
    """
    Показывать мини-урок ~3 раза в неделю (не каждый день, чтобы не надоедать).
    Используем детерминированный хеш от user_id + даты для стабильного результата.
    Дни показа: пн, ср, пт + если была тренировка (обрабатывается в select_teach_moment).
    """
    today = datetime.date.today()
    # Пн=0, Ср=2, Пт=4 — базовые дни показа
    if today.weekday() in (0, 2, 4):
        return True
    # В остальные дни — 30% шанс (детерминированный по user+date)
    seed = hashlib.md5(f"{user_id}:{today.isoformat()}".encode()).hexdigest()
    return int(seed[:2], 16) < 77  # ~30% (77/256)


def _pick_from_category(category_key: str, user_id: int, salt: str = "") -> Optional[str]:
    """Детерминированный выбор из категории (один и тот же факт для юзера в один день)."""
    category = t_list(category_key)
    if not category:
        return None
    today = datetime.date.today().isoformat()
    seed = hashlib.md5(f"{user_id}:{today}:{salt}".encode()).hexdigest()
    idx = int(seed[:4], 16) % len(category)
    return category[idx]


def select_teach_moment(
    user_id: int,
    workout: Optional[dict] = None,
    nutrition: Optional[dict] = None,
    metrics: Optional[dict] = None,
    goal_calories: Optional[int] = None,
    goal_protein: Optional[int] = None,
) -> Optional[str]:
    """
    Выбирает контекстный мини-урок на основе данных дня.

    Приоритет:
    1. Критические: мало сна (<7ч) или мало белка (<80% цели)
    2. После тренировки: совет по восстановлению
    3. Позитивные: хороший сон / высокая энергия
    4. День отдыха: совет по восстановлению
    5. Fallback: общий факт о гипертрофии

    Returns: строка с мини-уроком или None (если сегодня не день показа).
    """
    # Проверка частоты: если была тренировка — всегда показываем,
    # иначе — по расписанию ~3 раза в неделю
    workout_done = bool(workout and workout.get("completed"))
    if not workout_done and not _should_show_today(user_id):
        return None

    sleep_hours = metrics.get("sleep_hours") if metrics else None
    energy = metrics.get("energy") if metrics else None
    protein = nutrition.get("protein_g") if nutrition else None
    calories = nutrition.get("calories") if nutrition else None

    # --- Приоритет 1: критические сигналы ---

    # Мало сна
    if sleep_hours and sleep_hours < 7:
        return _pick_from_category("teach_low_sleep", user_id, "sleep")

    # Мало белка
    if goal_protein and protein:
        if protein < goal_protein * 0.8:
            return _pick_from_category("teach_low_protein", user_id, "protein")

    # Мало калорий
    if goal_calories and calories:
        if calories < goal_calories * 0.8:
            return _pick_from_category("teach_low_calories", user_id, "calories")

    # --- Приоритет 2: пост-тренировочный совет ---

    if workout_done:
        wtype = (workout.get("type") or "").lower()
        if wtype in ("cardio", "stretch", "flexibility", "yoga"):
            return _pick_from_category("teach_after_cardio", user_id, "cardio")
        # Всё остальное — силовая
        return _pick_from_category("teach_after_strength", user_id, "strength")

    # --- Приоритет 3: позитивные сигналы ---

    if sleep_hours and sleep_hours >= 8:
        return _pick_from_category("teach_good_sleep", user_id, "goodsleep")

    if energy and energy >= 4:
        return _pick_from_category("teach_high_energy", user_id, "energy")

    # --- Приоритет 4: низкая энергия ---

    if energy and energy <= 2:
        return _pick_from_category("teach_low_energy", user_id, "lowenergy")

    # --- Приоритет 5: день отдыха ---

    if not workout_done:
        return _pick_from_category("teach_no_workout", user_id, "rest")

    # --- Fallback ---

    return _pick_from_category("teach_hypertrophy_general", user_id, "general")
