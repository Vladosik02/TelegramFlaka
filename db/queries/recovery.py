"""
db/queries/recovery.py — Recovery Score.

Фаза 12.3: Композитная метрика готовности к тренировке (0–100).

Формула:
  sleep_score    (35%) — сон ≥7ч = 100%, меньше — линейно
  energy_score   (30%) — энергия 4-5/5 = 100%
  load_score     (20%) — отсутствие тяжёлых тренировок (≥8/10) 2+ дня
  consistency    (15%) — есть данные за 3+ дня (пользователь отчитывается)

Диапазоны:
  80-100 — ✅ Отлично. Готов к максимуму
  60-79  — 🟡 Хорошо. Умеренная нагрузка
  40-59  — ⚠️ Среднее. Лёгкая тренировка / активное восстановление
  0-39   — 🔴 Низко. Deload / только отдых
"""
import datetime
import logging

from db.connection import get_connection

logger = logging.getLogger(__name__)


def compute_recovery_score(user_id: int) -> dict:
    """
    Рассчитывает Recovery Score для пользователя на основе данных за последние 3 дня.

    Returns dict:
        score      (int 0-100)
        label      (str — текстовый ярлык)
        emoji      (str)
        breakdown  (dict — компоненты)
        advice     (str — краткая рекомендация)
    """
    conn = get_connection()
    today = datetime.date.today()
    since = (today - datetime.timedelta(days=3)).isoformat()

    # ── Метрики за последние 3 дня ────────────────────────────────────────────
    rows = conn.execute("""
        SELECT date, sleep_hours, energy
        FROM metrics
        WHERE user_id = ? AND date >= ?
        ORDER BY date DESC
        LIMIT 3
    """, (user_id, since)).fetchall()

    # ── Тренировки за последние 2 дня (нагрузка) ─────────────────────────────
    since_2d = (today - datetime.timedelta(days=2)).isoformat()
    workouts = conn.execute("""
        SELECT date, intensity, completed
        FROM workouts
        WHERE user_id = ? AND date >= ? AND completed = 1
        ORDER BY date DESC
    """, (user_id, since_2d)).fetchall()

    # ── 1. Sleep score ────────────────────────────────────────────────────────
    sleep_scores = []
    for row in rows:
        if row["sleep_hours"] and row["sleep_hours"] > 0:
            h = float(row["sleep_hours"])
            if h >= 7.0:
                sleep_scores.append(100.0)
            elif h >= 5.0:
                sleep_scores.append(round((h - 5.0) / 2.0 * 100.0))
            else:
                sleep_scores.append(0.0)

    sleep_score = round(sum(sleep_scores) / len(sleep_scores)) if sleep_scores else 50  # нет данных = нейтрально

    # ── 2. Energy score ───────────────────────────────────────────────────────
    energy_scores = []
    for row in rows:
        if row["energy"] and row["energy"] > 0:
            e = float(row["energy"])
            energy_scores.append(round((e - 1) / 4 * 100))

    energy_score = round(sum(energy_scores) / len(energy_scores)) if energy_scores else 50

    # ── 3. Load score (обратная нагрузка) ─────────────────────────────────────
    # Если были тяжёлые тренировки (≥8/10) за последние 2 дня — нагрузка высокая
    heavy_count = sum(1 for w in workouts if w["intensity"] and w["intensity"] >= 8)
    total_count = len(workouts)

    if total_count == 0:
        load_score = 80  # нет тренировок → хорошее восстановление (но не полное)
    elif heavy_count == 0:
        load_score = 100
    elif heavy_count == 1:
        load_score = 50
    else:
        load_score = 20  # 2+ тяжёлых за 2 дня → нужен отдых

    # ── 4. Consistency score ──────────────────────────────────────────────────
    # Насколько регулярно пользователь отчитывается (есть данные 3 дня)
    days_with_data = sum(
        1 for row in rows
        if (row["sleep_hours"] and row["sleep_hours"] > 0)
        or (row["energy"] and row["energy"] > 0)
    )
    consistency_score = min(100, round(days_with_data / 3 * 100))

    # ── Итоговый балл ─────────────────────────────────────────────────────────
    score = round(
        sleep_score    * 0.35
        + energy_score * 0.30
        + load_score   * 0.20
        + consistency_score * 0.15
    )
    score = max(0, min(100, score))

    # ── Интерпретация ─────────────────────────────────────────────────────────
    if score >= 80:
        label, emoji, advice = "Отлично", "✅", "Готов к максимальной нагрузке — жми на все!"
    elif score >= 60:
        label, emoji, advice = "Хорошо", "🟡", "Хороший день для тренировки в умеренном темпе."
    elif score >= 40:
        label, emoji, advice = "Среднее", "⚠️", "Лёгкая тренировка или активное восстановление."
    else:
        label, emoji, advice = "Низко", "🔴", "Тело просит отдыха. Приоритет — сон и питание."

    return {
        "score": score,
        "label": label,
        "emoji": emoji,
        "advice": advice,
        "breakdown": {
            "sleep":       sleep_score,
            "energy":      energy_score,
            "load":        load_score,
            "consistency": consistency_score,
        },
    }


def format_recovery_block(user_id: int) -> str:
    """
    Форматирует Recovery Score для вставки в context_builder (L0 Surface Card).
    Возвращает компактную строку ~30 токенов.
    """
    try:
        r = compute_recovery_score(user_id)
        return (
            f"Recovery Score: {r['score']}/100 {r['emoji']} ({r['label']}). "
            f"{r['advice']}"
        )
    except Exception as e:
        logger.warning(f"[RECOVERY] compute failed for {user_id}: {e}")
        return ""


def format_recovery_message(user_id: int) -> str:
    """
    Форматирует развёрнутое сообщение Recovery Score для отправки пользователю.
    """
    try:
        r = compute_recovery_score(user_id)
        b = r["breakdown"]

        # Визуальный бар
        filled = min(10, round(r["score"] / 10))
        bar = "█" * filled + "░" * (10 - filled)

        lines = [
            f"{r['emoji']} *Recovery Score: {r['score']}/100*",
            f"`[{bar}]` — {r['label']}",
            "",
            "*Компоненты:*",
            f"• 😴 Сон:          {b['sleep']}/100",
            f"• ⚡ Энергия:      {b['energy']}/100",
            f"• 🏋️ Нагрузка:     {b['load']}/100",
            f"• 📊 Регулярность: {b['consistency']}/100",
            "",
            f"_{r['advice']}_",
        ]
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"[RECOVERY] format failed for {user_id}: {e}")
        return "⚠️ Не удалось рассчитать Recovery Score."
