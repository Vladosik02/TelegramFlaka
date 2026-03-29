"""
scheduler/prediction.py — Прогноз тренировки (Workout Prediction).

Анализирует данные из exercise_results, metrics, periodization и training_plan,
чтобы предсказать оптимальные веса/повторения для следующей тренировки.

Принцип работы:
  1. Берём сегодняшний день из активного плана
  2. Для каждого упражнения находим последние результаты (exercise_results)
  3. Учитываем recovery score, фазу мезоцикла, сон/энергию
  4. Генерируем конкретные рекомендации: вес, повторения, RPE-потолок

Используется в:
  - send_pre_workout_reminder() → добавляет блок прогноза
  - tool_executor.py → get_next_workout_prediction (read-tool для Claude)
"""
import datetime
import json
import logging
from typing import Optional

from db.connection import get_connection

logger = logging.getLogger(__name__)


# ─── Константы прогрессии ────────────────────────────────────────────────────
WEIGHT_INCREMENT_KG = 2.5       # Стандартный шаг увеличения веса
REPS_INCREMENT = 1              # Шаг увеличения повторений
RPE_CEILING_DEFAULT = 8.5       # Потолок RPE по умолчанию
RPE_CEILING_DELOAD = 6.0        # Потолок RPE в deload
RPE_CEILING_LOW_RECOVERY = 7.0  # Потолок RPE при плохом восстановлении
MIN_HISTORY_DAYS = 90           # Глубина поиска истории упражнений


def get_today_plan_exercises(user_id: int) -> Optional[dict]:
    """
    Возвращает данные о сегодняшней тренировке из активного плана.

    Returns:
        dict с ключами: day_type, label, exercises (list), date
        или None если сегодня нет тренировки / нет плана.
    """
    from db.queries.training_plan import get_active_plan

    plan = get_active_plan(user_id)
    if not plan:
        return None

    try:
        days_list = json.loads(plan["plan_json"])
    except Exception:
        return None

    today_str = datetime.date.today().isoformat()
    for day in days_list:
        if day.get("date") == today_str:
            dtype = day.get("type", "rest")
            if dtype in ("rest", "recovery"):
                return None
            if day.get("completed"):
                return None
            return {
                "day_type": dtype,
                "label": day.get("label", dtype),
                "exercises": day.get("exercises") or [],
                "date": today_str,
                "ai_note": day.get("ai_note", ""),
            }

    return None


def get_exercise_prediction(
    user_id: int,
    exercise_name: str,
    plan_sets: int = None,
    plan_reps: int = None,
    plan_weight_target: float = None,
    recovery_score: int = None,
    meso_phase: str = None,
) -> dict:
    """
    Генерирует прогноз для одного упражнения.

    Логика:
      - Берём последний результат из exercise_results
      - Сравниваем с планом (plan_weight_target)
      - Учитываем recovery_score и фазу мезоцикла
      - Решаем: повышать вес, добавить повтор, или остаться

    Returns:
        dict: {
            exercise_name, last_result, prediction,
            reasoning, rpe_ceiling
        }
    """
    conn = get_connection()

    # Находим последний результат по этому упражнению
    since = (datetime.date.today() - datetime.timedelta(days=MIN_HISTORY_DAYS)).isoformat()
    last = conn.execute("""
        SELECT sets, reps, weight_kg, duration_sec, date, notes
        FROM exercise_results
        WHERE user_id = ? AND exercise_name = ? AND date >= ?
        ORDER BY date DESC, id DESC
        LIMIT 1
    """, (user_id, exercise_name, since)).fetchone()

    # Берём последние 3 для анализа тренда
    history = conn.execute("""
        SELECT sets, reps, weight_kg, date
        FROM exercise_results
        WHERE user_id = ? AND exercise_name = ? AND date >= ?
        ORDER BY date DESC, id DESC
        LIMIT 3
    """, (user_id, exercise_name, since)).fetchall()

    result = {
        "exercise_name": exercise_name,
        "last_result": None,
        "prediction": {},
        "reasoning": "",
        "rpe_ceiling": RPE_CEILING_DEFAULT,
    }

    # ── Определяем RPE потолок на основе контекста ──────────────────────
    if meso_phase == "deload":
        result["rpe_ceiling"] = RPE_CEILING_DELOAD
    elif recovery_score is not None and recovery_score < 50:
        result["rpe_ceiling"] = RPE_CEILING_LOW_RECOVERY
    elif meso_phase in ("realization", "intensification"):
        result["rpe_ceiling"] = 9.0

    # ── Нет истории — возвращаем план как есть ──────────────────────────
    if not last:
        result["prediction"] = {
            "sets": plan_sets,
            "reps": plan_reps,
            "weight_kg": plan_weight_target,
        }
        result["reasoning"] = "Первый раз — начни по плану, почувствуй вес."
        return result

    # ── Формируем last_result ───────────────────────────────────────────
    last_dict = dict(last)
    result["last_result"] = {
        "sets": last_dict.get("sets"),
        "reps": last_dict.get("reps"),
        "weight_kg": last_dict.get("weight_kg"),
        "date": last_dict.get("date"),
    }

    last_w = last_dict.get("weight_kg") or 0
    last_r = last_dict.get("reps") or 0
    last_s = last_dict.get("sets") or 0

    # ── Deload: снижаем нагрузку ────────────────────────────────────────
    if meso_phase == "deload":
        pred_w = round(last_w * 0.6, 1) if last_w else plan_weight_target
        result["prediction"] = {
            "sets": plan_sets or last_s,
            "reps": plan_reps or last_r,
            "weight_kg": pred_w,
        }
        result["reasoning"] = "Deload — 60% от рабочего веса. Фокус на технике."
        return result

    # ── Плохое восстановление: не повышаем ──────────────────────────────
    if recovery_score is not None and recovery_score < 50:
        result["prediction"] = {
            "sets": plan_sets or last_s,
            "reps": plan_reps or last_r,
            "weight_kg": last_w if last_w else plan_weight_target,
        }
        result["reasoning"] = (
            f"Recovery {recovery_score}/100 — повторяем прошлый вес, "
            f"не повышаем. Если RPE > {result['rpe_ceiling']} — снижай."
        )
        return result

    # ── Нормальная прогрессия ───────────────────────────────────────────
    # Анализ тренда: вес растёт / стоит / падает
    trend = _analyze_weight_trend(history)

    pred_w = last_w
    pred_r = plan_reps or last_r
    pred_s = plan_sets or last_s
    reasoning_parts = []

    if last_w > 0:
        # Если предыдущий вес >= плановому — пора повышать
        if plan_weight_target and last_w >= float(plan_weight_target):
            pred_w = round(last_w + WEIGHT_INCREMENT_KG, 1)
            reasoning_parts.append(
                f"В прошлый раз {last_w} кг — план выполнен, пробуй {pred_w} кг."
            )
        elif plan_weight_target and last_w < float(plan_weight_target):
            pred_w = float(plan_weight_target)
            reasoning_parts.append(
                f"Прошлый раз {last_w} кг — цель {plan_weight_target} кг, догоняй."
            )
        else:
            # Нет плановой цели — двигаемся от последнего результата
            if trend == "stable" and last_r >= (plan_reps or 8):
                # Стабильно выполняет все повторения — повышаем вес
                pred_w = round(last_w + WEIGHT_INCREMENT_KG, 1)
                reasoning_parts.append(
                    f"Стабильно {last_s}×{last_r} @ {last_w} кг — пора +{WEIGHT_INCREMENT_KG} кг."
                )
            elif trend == "growing":
                pred_w = round(last_w + WEIGHT_INCREMENT_KG, 1)
                reasoning_parts.append(
                    f"Прогресс идёт! Был {last_w} кг — давай {pred_w} кг."
                )
            else:
                # Тренд нестабильный — остаёмся
                reasoning_parts.append(
                    f"Закрепляем {last_w} кг — в прошлый раз {last_s}×{last_r}."
                )
    elif last_r > 0:
        # Упражнение без веса (планка, отжимания)
        pred_r = last_r + REPS_INCREMENT
        reasoning_parts.append(
            f"Прошлый раз {last_r} повторений — целься на {pred_r}."
        )

    # Усиливаем мотивацию в фазе реализации
    if meso_phase == "realization":
        reasoning_parts.append("Пиковая неделя — можно жать на максимум!")

    result["prediction"] = {
        "sets": pred_s,
        "reps": pred_r,
        "weight_kg": pred_w if pred_w > 0 else None,
    }
    result["reasoning"] = " ".join(reasoning_parts)

    return result


def _analyze_weight_trend(history: list) -> str:
    """
    Анализирует тренд веса по последним 3 результатам.
    Returns: 'growing' | 'stable' | 'declining' | 'unknown'
    """
    if len(history) < 2:
        return "unknown"

    weights = [dict(h).get("weight_kg") or 0 for h in history]
    weights = [w for w in weights if w > 0]

    if len(weights) < 2:
        return "unknown"

    # history отсортирована DESC — weights[0] = последний
    if weights[0] > weights[-1]:
        return "growing"
    elif weights[0] == weights[-1]:
        return "stable"
    else:
        return "declining"


def build_workout_prediction(user_id: int) -> Optional[dict]:
    """
    Полный прогноз на сегодняшнюю тренировку.

    Собирает:
      - Упражнения из плана
      - Recovery Score
      - Фазу мезоцикла
      - Метрики (сон, энергия)
      - Прогноз для каждого упражнения

    Returns:
        dict: {
            date, label, day_type, recovery, meso_phase,
            sleep, energy, exercises: [{prediction}],
            rpe_ceiling, summary
        }
        или None если нет тренировки сегодня.
    """
    # 1. Берём план на сегодня
    today_plan = get_today_plan_exercises(user_id)
    if not today_plan:
        return None

    # 2. Recovery Score
    recovery_score = None
    recovery_data = None
    try:
        from db.queries.recovery import compute_recovery_score
        recovery_data = compute_recovery_score(user_id)
        recovery_score = recovery_data.get("score")
    except Exception as e:
        logger.debug(f"[PREDICTION] recovery score failed for {user_id}: {e}")

    # 3. Фаза мезоцикла
    meso_phase = None
    meso_week = None
    try:
        from db.queries.periodization import get_or_create_mesocycle
        meso = get_or_create_mesocycle(user_id)
        meso_phase = meso.get("current_phase", "accumulation")
        meso_week = meso.get("current_week")
    except Exception as e:
        logger.debug(f"[PREDICTION] mesocycle failed for {user_id}: {e}")

    # 4. Последние метрики (сон, энергия)
    conn = get_connection()
    today = datetime.date.today()
    recent = conn.execute("""
        SELECT sleep_hours, energy FROM metrics
        WHERE user_id = ? AND date >= ?
        ORDER BY date DESC LIMIT 1
    """, (user_id, (today - datetime.timedelta(days=2)).isoformat())).fetchone()

    sleep = dict(recent).get("sleep_hours") if recent else None
    energy = dict(recent).get("energy") if recent else None

    # 5. Прогнозы для каждого упражнения
    exercise_predictions = []
    for ex in today_plan["exercises"]:
        if isinstance(ex, str):
            continue
        name = ex.get("name", "")
        if not name:
            continue

        pred = get_exercise_prediction(
            user_id=user_id,
            exercise_name=name,
            plan_sets=ex.get("sets"),
            plan_reps=ex.get("reps"),
            plan_weight_target=ex.get("weight_kg_target"),
            recovery_score=recovery_score,
            meso_phase=meso_phase,
        )
        exercise_predictions.append(pred)

    # 6. Итоговое RPE ceiling (минимальный из всех)
    rpe_ceilings = [ep["rpe_ceiling"] for ep in exercise_predictions if ep.get("rpe_ceiling")]
    overall_rpe = min(rpe_ceilings) if rpe_ceilings else RPE_CEILING_DEFAULT

    # 7. Генерируем summary
    summary = _build_summary(
        recovery_score=recovery_score,
        meso_phase=meso_phase,
        sleep=sleep,
        energy=energy,
        exercise_count=len(exercise_predictions),
    )

    return {
        "date": today_plan["date"],
        "label": today_plan["label"],
        "day_type": today_plan["day_type"],
        "recovery": recovery_data,
        "meso_phase": meso_phase,
        "meso_week": meso_week,
        "sleep": sleep,
        "energy": energy,
        "exercises": exercise_predictions,
        "rpe_ceiling": overall_rpe,
        "summary": summary,
    }


def _build_summary(
    recovery_score: int = None,
    meso_phase: str = None,
    sleep: float = None,
    energy: int = None,
    exercise_count: int = 0,
) -> str:
    """Краткий текстовый прогноз для сообщения пользователю."""
    parts = []

    # Recovery
    if recovery_score is not None:
        if recovery_score >= 80:
            parts.append("Восстановление отличное — можно жать!")
        elif recovery_score >= 60:
            parts.append("Восстановление в норме — работай по плану.")
        elif recovery_score >= 40:
            parts.append("Восстановление среднее — не геройствуй.")
        else:
            parts.append("Восстановление низкое — бери лёгкие веса.")

    # Sleep
    if sleep is not None:
        if sleep < 6.0:
            parts.append(f"Сон {sleep}ч — мало, осторожнее с нагрузкой.")

    # Meso phase
    if meso_phase == "deload":
        parts.append("Deload-неделя: снижаем нагрузку, фокус на технике.")
    elif meso_phase == "realization":
        parts.append("Пиковая неделя — время для рекордов!")

    if not parts:
        parts.append(f"Готово {exercise_count} упражнений — вперёд!")

    return " ".join(parts)


def format_prediction_block(prediction: dict) -> str:
    """
    Форматирует прогноз для вставки в pre-workout reminder (Markdown).

    Returns:
        Строка ~200-400 символов с прогнозами по упражнениям.
    """
    if not prediction or not prediction.get("exercises"):
        return ""

    lines = ["\n🎯 *Прогноз на сегодня:*"]

    for ep in prediction["exercises"][:5]:
        pred = ep.get("prediction", {})
        last = ep.get("last_result")
        name = ep["exercise_name"]

        pred_parts = []
        if pred.get("sets") and pred.get("reps"):
            pred_parts.append(f"{pred['sets']}×{pred['reps']}")
        if pred.get("weight_kg"):
            pred_parts.append(f"@ {pred['weight_kg']} кг")

        line = f"  • {name}"
        if pred_parts:
            line += f" → {' '.join(pred_parts)}"

        # Показываем прошлый результат для контекста
        if last:
            last_parts = []
            if last.get("sets") and last.get("reps"):
                last_parts.append(f"{last['sets']}×{last['reps']}")
            if last.get("weight_kg"):
                last_parts.append(f"@ {last['weight_kg']} кг")
            if last_parts:
                line += f"  _(было: {' '.join(last_parts)})_"

        lines.append(line)

    # RPE ceiling
    rpe = prediction.get("rpe_ceiling", RPE_CEILING_DEFAULT)
    if rpe < RPE_CEILING_DEFAULT:
        lines.append(f"\n⚠️ RPE-потолок сегодня: {rpe}/10")

    # Summary
    summary = prediction.get("summary", "")
    if summary:
        lines.append(f"\n💡 _{summary}_")

    return "\n".join(lines)
