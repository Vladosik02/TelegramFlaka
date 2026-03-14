"""
db/queries/periodization.py — Система периодизации (мезоциклы).

Фаза 12.2: Планирование нагрузки на 7-10 недель вперёд по классической схеме:
  Накопление → Интенсификация → Реализация → Deload

Каждая фаза имеет свои характеристики объёма и интенсивности.
AI получает информацию о текущей фазе и адаптирует план.
"""
import datetime
import logging
import json

from db.connection import get_connection

logger = logging.getLogger(__name__)


# ─── Конфигурация мезоцикла ────────────────────────────────────────────────

PHASE_CONFIG = {
    "accumulation": {
        "name":        "Накопление 📈",
        "name_short":  "Накопление",
        "description": "Высокий объём, умеренная интенсивность. Закладываем базу.",
        "weeks":       3,
        "intensity_target": "6-7/10",
        "volume_modifier":  1.0,      # норма
        "ai_note": (
            "Сейчас фаза НАКОПЛЕНИЯ: высокий объём, умеренная интенсивность (6-7/10). "
            "Приоритет — стабильность выполнения плана. Не гонись за рекордами."
        ),
    },
    "intensification": {
        "name":        "Интенсификация 🔥",
        "name_short":  "Интенсификация",
        "description": "Снижаем объём, повышаем интенсивность. Работаем тяжело.",
        "weeks":       2,
        "intensity_target": "8-9/10",
        "volume_modifier":  0.8,
        "ai_note": (
            "Сейчас фаза ИНТЕНСИФИКАЦИИ: меньший объём, высокая интенсивность (8-9/10). "
            "Можно пробовать личные рекорды. Следи за восстановлением."
        ),
    },
    "realization": {
        "name":        "Реализация 🏆",
        "name_short":  "Реализация",
        "description": "Пик формы. Тестируем максимальные результаты.",
        "weeks":       1,
        "intensity_target": "9-10/10",
        "volume_modifier":  0.6,
        "ai_note": (
            "Сейчас фаза РЕАЛИЗАЦИИ — ПИКОВАЯ НЕДЕЛЯ! "
            "Минимальный объём, максимальная интенсивность. "
            "Это момент для личных рекордов и фитнес-теста (/test)."
        ),
    },
    "deload": {
        "name":        "Deload 🧘",
        "name_short":  "Deload",
        "description": "Восстановление. Снижаем всё на 40%. Тело адаптируется.",
        "weeks":       1,
        "intensity_target": "4-5/10",
        "volume_modifier":  0.5,
        "ai_note": (
            "Сейчас DELOAD-неделя. Нагрузка снижена на 40%. "
            "Это обязательная часть прогресса, не лень. "
            "Фокус на технике и активном восстановлении."
        ),
    },
}

# Порядок фаз в цикле
PHASE_ORDER = ["accumulation", "accumulation", "accumulation",
               "intensification", "intensification",
               "realization",
               "deload"]


def get_or_create_mesocycle(user_id: int) -> dict:
    """
    Возвращает текущий мезоцикл пользователя.
    Если нет — создаёт новый с фазы Накопления.
    """
    conn = get_connection()

    row = conn.execute("""
        SELECT * FROM mesocycles
        WHERE user_id = ? AND completed_at IS NULL
        ORDER BY id DESC LIMIT 1
    """, (user_id,)).fetchone()

    if row:
        return dict(row)

    # Создаём первый мезоцикл
    return _create_mesocycle(user_id, phase_index=0)


def _create_mesocycle(user_id: int, phase_index: int = 0) -> dict:
    """Создаёт новый мезоцикл (или следующую фазу)."""
    conn = get_connection()
    phase = PHASE_ORDER[phase_index % len(PHASE_ORDER)]
    total_weeks = len(PHASE_ORDER)

    conn.execute("""
        INSERT INTO mesocycles (user_id, phase, phase_index, week_number, total_weeks, started_at)
        VALUES (?, ?, ?, 1, ?, ?)
    """, (user_id, phase, phase_index, total_weeks, datetime.date.today().isoformat()))
    conn.commit()

    row = conn.execute("""
        SELECT * FROM mesocycles
        WHERE user_id = ? AND completed_at IS NULL
        ORDER BY id DESC LIMIT 1
    """, (user_id,)).fetchone()
    return dict(row)


def advance_mesocycle(user_id: int) -> dict | None:
    """
    Продвигает мезоцикл на следующую неделю.
    Вызывается автоматически каждое воскресенье (scheduler).

    Возвращает:
        dict — новое состояние мезоцикла
        None — если нет активного цикла
    """
    conn = get_connection()
    mc = get_or_create_mesocycle(user_id)

    phase_cfg = PHASE_CONFIG[mc["phase"]]
    phase_weeks = phase_cfg["weeks"]
    current_week = mc["week_number"]

    if current_week < phase_weeks:
        # Следующая неделя той же фазы
        conn.execute("""
            UPDATE mesocycles SET week_number = ?
            WHERE id = ?
        """, (current_week + 1, mc["id"]))
        conn.commit()
        mc["week_number"] = current_week + 1
        return mc

    else:
        # Фаза завершена → переходим к следующей
        conn.execute("""
            UPDATE mesocycles SET completed_at = ?, week_number = ?
            WHERE id = ?
        """, (datetime.date.today().isoformat(), current_week, mc["id"]))
        conn.commit()

        next_index = (mc.get("phase_index", 0) + 1) % len(PHASE_ORDER)
        new_mc = _create_mesocycle(user_id, phase_index=next_index)

        logger.info(
            f"[PERIOD] user {user_id}: "
            f"{mc['phase']} → {new_mc['phase']}"
        )
        return new_mc


def get_current_phase_info(user_id: int) -> dict:
    """
    Возвращает полную информацию о текущей фазе для отображения и AI-контекста.
    """
    try:
        mc = get_or_create_mesocycle(user_id)
        phase = mc.get("phase", "accumulation")
        cfg = PHASE_CONFIG.get(phase, PHASE_CONFIG["accumulation"])
        week = mc.get("week_number", 1)
        total = cfg["weeks"]

        return {
            "phase":           phase,
            "phase_name":      cfg["name"],
            "phase_name_short":cfg["name_short"],
            "description":     cfg["description"],
            "week_in_phase":   week,
            "weeks_in_phase":  total,
            "intensity_target":cfg["intensity_target"],
            "volume_modifier": cfg["volume_modifier"],
            "ai_note":         cfg["ai_note"],
            "mesocycle_id":    mc.get("id"),
            "started_at":      mc.get("started_at"),
        }
    except Exception as e:
        logger.warning(f"[PERIOD] get_current_phase_info failed for {user_id}: {e}")
        return {
            "phase":       "accumulation",
            "phase_name":  "Накопление 📈",
            "description": "Базовая фаза.",
            "ai_note":     "",
        }


def format_period_block(user_id: int) -> str:
    """
    Форматирует блок периодизации для вставки в context_builder (~40 токенов).
    """
    try:
        info = get_current_phase_info(user_id)
        week_str = f"(неделя {info['week_in_phase']}/{info['weeks_in_phase']})"
        return (
            f"## Периодизация\n"
            f"{info['phase_name']} {week_str} — {info['description']} "
            f"Интенсивность: {info['intensity_target']}.\n"
            f"{info['ai_note']}"
        )
    except Exception as e:
        logger.warning(f"[PERIOD] format_period_block failed: {e}")
        return ""


def format_period_message(user_id: int) -> str:
    """
    Форматирует подробное сообщение о текущем мезоцикле для пользователя.
    """
    try:
        info = get_current_phase_info(user_id)
        total_weeks = len(PHASE_ORDER)

        # Общий прогресс цикла
        from db.connection import get_connection as _conn
        conn = _conn()
        completed = conn.execute("""
            SELECT COUNT(*) cnt FROM mesocycles
            WHERE user_id = ? AND completed_at IS NOT NULL
        """, (user_id,)).fetchone()
        cycle_num = (completed["cnt"] // total_weeks) + 1

        # Схема фаз
        phases_schema = " → ".join([
            PHASE_CONFIG[p]["name_short"]
            for p in ["accumulation", "intensification", "realization", "deload"]
        ])

        lines = [
            f"🔄 *Мезоцикл #{cycle_num} — {info['phase_name']}*",
            "━━━━━━━━━━━━━━━━━",
            f"📅 Неделя: *{info['week_in_phase']}/{info['weeks_in_phase']}* в фазе",
            f"⚡ Целевая интенсивность: *{info['intensity_target']}*",
            f"📋 {info['description']}",
            "━━━━━━━━━━━━━━━━━",
            f"*Схема цикла:*",
            f"`{phases_schema}`",
            "━━━━━━━━━━━━━━━━━",
            f"_{info['ai_note']}_",
        ]
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"[PERIOD] format_period_message failed: {e}")
        return "⚠️ Данные периодизации недоступны."
