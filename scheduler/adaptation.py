"""
scheduler/adaptation.py — Adaptive Session Modifier.

Анализирует данные утреннего чек-ина (сон, энергия) + recovery score + мезоцикл
и генерирует рекомендацию по модификации тренировки ДО её начала.

Принцип:
  - Recovery < 40 + сон < 6ч → DELOAD-день (−40% вес, −1 подход)
  - Recovery < 50 или энергия ≤ 2 → ОБЛЕГЧЁННЫЙ (удержать вес, −1 подход)
  - Recovery ≥ 80 + энергия ≥ 4 + realization → УСИЛЕННЫЙ (+2.5 кг)
  - Остальное → без изменений (NORMAL)

Используется в:
  - scheduler/logic.py → send_pre_workout_reminder() — формирует блок адаптации
  - bot/handlers.py → adapt:* callbacks — пользователь принимает/отклоняет
"""
import datetime
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ─── Типы модификаций ──────────────────────────────────────────────────────
ADAPT_DELOAD = "deload"       # Критически плохое состояние → deload-день
ADAPT_LIGHT = "light"         # Ниже нормы → облегчённая тренировка
ADAPT_BOOST = "boost"         # Отличное состояние + пиковая фаза → усиление
ADAPT_NORMAL = "normal"       # Без изменений


def compute_session_adaptation(
    recovery_score: Optional[int],
    sleep: Optional[float],
    energy: Optional[int],
    meso_phase: Optional[str],
) -> dict:
    """
    Вычисляет рекомендацию по адаптации сегодняшней тренировки.

    Args:
        recovery_score: 0-100 (из compute_recovery_score)
        sleep:          часы сна (из последнего чек-ина)
        energy:         1-5 (из последнего чек-ина)
        meso_phase:     accumulation / realization / intensification / deload

    Returns:
        dict: {
            type:          str — ADAPT_DELOAD / ADAPT_LIGHT / ADAPT_BOOST / ADAPT_NORMAL
            weight_factor: float — множитель веса (0.6 = −40%, 1.0 = без изменений, etc.)
            sets_delta:    int — изменение подходов (−1, 0, +1)
            rpe_ceiling:   float — рекомендуемый RPE-потолок
            reason:        str — человекочитаемое объяснение
            emoji:         str — иконка для сообщения
            short_label:   str — краткий ярлык для кнопки
        }
    """
    rec = recovery_score if recovery_score is not None else 65  # нет данных = нейтрально
    slp = sleep if sleep is not None else 7.0
    nrg = energy if energy is not None else 3

    # ── DELOAD-день: критическое состояние ────────────────────────────────
    if rec < 40 and slp < 6.0:
        return {
            "type": ADAPT_DELOAD,
            "weight_factor": 0.6,
            "sets_delta": -1,
            "rpe_ceiling": 6.0,
            "reason": (
                f"Recovery {rec}/100 + сон {slp}ч — организм на пределе. "
                "Рекомендую deload-день: −40% вес, −1 подход, фокус на технике."
            ),
            "emoji": "🔴",
            "short_label": "Deload-день",
        }

    # ── Облегчённая тренировка: ниже нормы ────────────────────────────────
    if rec < 50 or (slp < 6.0 and nrg <= 2) or nrg <= 2:
        reason_parts = []
        if rec < 50:
            reason_parts.append(f"recovery {rec}/100")
        if slp < 6.0:
            reason_parts.append(f"сон {slp}ч")
        if nrg <= 2:
            reason_parts.append(f"энергия {nrg}/5")

        return {
            "type": ADAPT_LIGHT,
            "weight_factor": 1.0,    # Держим вес, не повышаем
            "sets_delta": -1,
            "rpe_ceiling": 7.0,
            "reason": (
                f"Сегодня не лучший день ({', '.join(reason_parts)}). "
                "Держим рабочие веса, −1 подход, RPE до 7. Лучше недоработать, чем травмироваться."
            ),
            "emoji": "⚠️",
            "short_label": "Облегчённая",
        }

    # ── Усиленная тренировка: отличное состояние + пиковая фаза ──────────
    if rec >= 80 and nrg >= 4 and meso_phase in ("realization", "intensification"):
        return {
            "type": ADAPT_BOOST,
            "weight_factor": 1.0,    # +2.5 кг будет добавлено к каждому прогнозу
            "sets_delta": 0,
            "rpe_ceiling": 9.5,
            "reason": (
                f"Recovery {rec}/100, энергия {nrg}/5, пиковая неделя — "
                "отличный день! Попробуй +2.5 кг на базовых упражнениях."
            ),
            "emoji": "🔥",
            "short_label": "Усиленная",
        }

    # ── Нормальная тренировка: без изменений ──────────────────────────────
    return {
        "type": ADAPT_NORMAL,
        "weight_factor": 1.0,
        "sets_delta": 0,
        "rpe_ceiling": 8.5,
        "reason": "",
        "emoji": "",
        "short_label": "",
    }


def apply_adaptation_to_prediction(prediction: dict, adaptation: dict) -> dict:
    """
    Применяет адаптацию к прогнозу из build_workout_prediction().

    Не мутирует оригинальные данные — возвращает новый dict с
    оригинальными и модифицированными значениями.

    Returns:
        dict с дополнительными ключами:
          - adapted: True/False
          - adaptation_type: str
          - adaptation_reason: str
          - original_exercises: list (оригинальные прогнозы)
          - exercises: list (модифицированные прогнозы)
    """
    if not prediction or not prediction.get("exercises"):
        return prediction

    adapt_type = adaptation.get("type", ADAPT_NORMAL)

    if adapt_type == ADAPT_NORMAL:
        return {
            **prediction,
            "adapted": False,
            "adaptation_type": ADAPT_NORMAL,
            "adaptation_reason": "",
        }

    weight_factor = adaptation["weight_factor"]
    sets_delta = adaptation["sets_delta"]
    rpe_ceiling = adaptation["rpe_ceiling"]

    original_exercises = []
    modified_exercises = []

    for ep in prediction["exercises"]:
        original_exercises.append(ep.copy())

        modified = ep.copy()
        pred = dict(ep.get("prediction", {}))

        # Модифицируем вес
        if pred.get("weight_kg") and pred["weight_kg"] > 0:
            original_w = pred["weight_kg"]

            if adapt_type == ADAPT_DELOAD:
                pred["weight_kg"] = round(original_w * weight_factor, 1)
            elif adapt_type == ADAPT_LIGHT:
                # Для light: не повышаем вес, берём последний результат
                last = ep.get("last_result")
                if last and last.get("weight_kg"):
                    pred["weight_kg"] = last["weight_kg"]
                # Иначе оставляем прогноз как есть
            elif adapt_type == ADAPT_BOOST:
                # +2.5 кг к прогнозу
                pred["weight_kg"] = round(original_w + 2.5, 1)

        # Модифицируем подходы
        if pred.get("sets") and sets_delta != 0:
            pred["sets"] = max(1, pred["sets"] + sets_delta)

        # RPE ceiling
        modified["rpe_ceiling"] = min(
            modified.get("rpe_ceiling", 8.5),
            rpe_ceiling,
        )

        modified["prediction"] = pred
        modified_exercises.append(modified)

    return {
        **prediction,
        "adapted": True,
        "adaptation_type": adapt_type,
        "adaptation_reason": adaptation["reason"],
        "adaptation_emoji": adaptation["emoji"],
        "adaptation_label": adaptation["short_label"],
        "original_exercises": original_exercises,
        "exercises": modified_exercises,
        "rpe_ceiling": rpe_ceiling,
    }


def format_adaptation_block(adapted_prediction: dict) -> str:
    """
    Форматирует блок адаптации для pre-workout сообщения (Markdown).

    Показывает:
      - Тип адаптации + причина
      - Модифицированные упражнения vs оригинальные

    Returns:
        Строка для вставки в сообщение или "" если нет адаптации.
    """
    if not adapted_prediction or not adapted_prediction.get("adapted"):
        return ""

    adapt_type = adapted_prediction["adaptation_type"]
    emoji = adapted_prediction.get("adaptation_emoji", "")
    label = adapted_prediction.get("adaptation_label", "")
    reason = adapted_prediction.get("adaptation_reason", "")

    lines = [f"\n{emoji} *Адаптация: {label}*"]

    if reason:
        lines.append(f"_{reason}_")

    lines.append("")

    # Показываем изменения по упражнениям
    originals = adapted_prediction.get("original_exercises", [])
    modified = adapted_prediction.get("exercises", [])

    for i, ep in enumerate(modified[:5]):
        pred = ep.get("prediction", {})
        name = ep["exercise_name"]

        mod_parts = []
        if pred.get("sets") and pred.get("reps"):
            mod_parts.append(f"{pred['sets']}×{pred['reps']}")
        if pred.get("weight_kg"):
            mod_parts.append(f"@ {pred['weight_kg']} кг")

        line = f"  • {name}"
        if mod_parts:
            line += f" → {' '.join(mod_parts)}"

        # Показываем что было в оригинальном прогнозе
        if i < len(originals):
            orig = originals[i].get("prediction", {})
            orig_parts = []
            if orig.get("sets") and orig.get("reps"):
                orig_parts.append(f"{orig['sets']}×{orig['reps']}")
            if orig.get("weight_kg"):
                orig_parts.append(f"@ {orig['weight_kg']} кг")
            if orig_parts and orig_parts != mod_parts:
                line += f"  _(план: {' '.join(orig_parts)})_"

        lines.append(line)

    rpe = adapted_prediction.get("rpe_ceiling", 8.5)
    if rpe < 8.5:
        lines.append(f"\n⚠️ RPE-потолок: {rpe}/10")

    return "\n".join(lines)
