"""
tests/test_adaptation.py — Тесты для scheduler/adaptation.py (Adaptive Session Modifier).

Покрывает:
  - compute_session_adaptation: все 4 типа адаптации
  - apply_adaptation_to_prediction: модификация прогнозов
  - format_adaptation_block: форматирование сообщения
  - Граничные случаи: None-значения, пустые данные
"""
import pytest

from scheduler.adaptation import (
    compute_session_adaptation,
    apply_adaptation_to_prediction,
    format_adaptation_block,
    ADAPT_DELOAD,
    ADAPT_LIGHT,
    ADAPT_BOOST,
    ADAPT_NORMAL,
)


# ═══════════════════════════════════════════════════════════════════════════
# compute_session_adaptation
# ═══════════════════════════════════════════════════════════════════════════

class TestComputeSessionAdaptation:
    """Тесты вычисления типа адаптации."""

    def test_deload_low_recovery_and_bad_sleep(self):
        """Recovery < 40 + сон < 6 → DELOAD."""
        result = compute_session_adaptation(
            recovery_score=35, sleep=5.0, energy=2, meso_phase="accumulation",
        )
        assert result["type"] == ADAPT_DELOAD
        assert result["weight_factor"] == 0.6
        assert result["sets_delta"] == -1
        assert result["rpe_ceiling"] == 6.0
        assert "deload" in result["reason"].lower() or "организм" in result["reason"]

    def test_deload_very_low_recovery_and_very_bad_sleep(self):
        """Recovery 20 + сон 4ч → DELOAD."""
        result = compute_session_adaptation(
            recovery_score=20, sleep=4.0, energy=1, meso_phase="accumulation",
        )
        assert result["type"] == ADAPT_DELOAD

    def test_light_low_recovery(self):
        """Recovery < 50 (но сон нормальный) → LIGHT."""
        result = compute_session_adaptation(
            recovery_score=45, sleep=7.0, energy=3, meso_phase="accumulation",
        )
        assert result["type"] == ADAPT_LIGHT
        assert result["weight_factor"] == 1.0
        assert result["sets_delta"] == -1
        assert result["rpe_ceiling"] == 7.0

    def test_light_bad_sleep_and_low_energy(self):
        """Сон < 6 + энергия ≤ 2 → LIGHT."""
        result = compute_session_adaptation(
            recovery_score=60, sleep=5.5, energy=2, meso_phase="accumulation",
        )
        assert result["type"] == ADAPT_LIGHT

    def test_light_very_low_energy(self):
        """Энергия ≤ 2 при нормальном recovery → LIGHT."""
        result = compute_session_adaptation(
            recovery_score=65, sleep=7.0, energy=2, meso_phase="accumulation",
        )
        assert result["type"] == ADAPT_LIGHT

    def test_boost_high_recovery_realization(self):
        """Recovery ≥ 80 + энергия ≥ 4 + realization → BOOST."""
        result = compute_session_adaptation(
            recovery_score=85, sleep=8.0, energy=5, meso_phase="realization",
        )
        assert result["type"] == ADAPT_BOOST
        assert result["rpe_ceiling"] == 9.5
        assert result["sets_delta"] == 0

    def test_boost_intensification(self):
        """Recovery ≥ 80 + энергия ≥ 4 + intensification → BOOST."""
        result = compute_session_adaptation(
            recovery_score=90, sleep=8.0, energy=4, meso_phase="intensification",
        )
        assert result["type"] == ADAPT_BOOST

    def test_no_boost_in_accumulation(self):
        """Хорошее состояние, но accumulation → NORMAL (не boost)."""
        result = compute_session_adaptation(
            recovery_score=85, sleep=8.0, energy=5, meso_phase="accumulation",
        )
        assert result["type"] == ADAPT_NORMAL

    def test_normal_average_state(self):
        """Среднее состояние → NORMAL."""
        result = compute_session_adaptation(
            recovery_score=65, sleep=7.0, energy=3, meso_phase="accumulation",
        )
        assert result["type"] == ADAPT_NORMAL
        assert result["weight_factor"] == 1.0
        assert result["sets_delta"] == 0
        assert result["reason"] == ""

    def test_normal_good_state_no_realization(self):
        """Хорошее состояние, но обычная фаза → NORMAL."""
        result = compute_session_adaptation(
            recovery_score=75, sleep=7.5, energy=4, meso_phase="accumulation",
        )
        assert result["type"] == ADAPT_NORMAL

    def test_none_values_default_to_normal(self):
        """Все None → NORMAL (дефолты нейтральные)."""
        result = compute_session_adaptation(
            recovery_score=None, sleep=None, energy=None, meso_phase=None,
        )
        assert result["type"] == ADAPT_NORMAL

    def test_deload_requires_both_conditions(self):
        """Recovery < 40 но сон нормальный → LIGHT, не DELOAD."""
        result = compute_session_adaptation(
            recovery_score=35, sleep=7.0, energy=3, meso_phase="accumulation",
        )
        # recovery < 50 → LIGHT (не deload, т.к. сон >= 6)
        assert result["type"] == ADAPT_LIGHT


# ═══════════════════════════════════════════════════════════════════════════
# apply_adaptation_to_prediction
# ═══════════════════════════════════════════════════════════════════════════

def _make_prediction(exercises=None):
    """Создаёт минимальный prediction dict для тестов."""
    if exercises is None:
        exercises = [
            {
                "exercise_name": "Жим лёжа",
                "prediction": {"sets": 4, "reps": 8, "weight_kg": 80.0},
                "last_result": {"sets": 4, "reps": 8, "weight_kg": 77.5, "date": "2026-03-20"},
                "rpe_ceiling": 8.5,
            },
            {
                "exercise_name": "Тяга в наклоне",
                "prediction": {"sets": 4, "reps": 10, "weight_kg": 60.0},
                "last_result": {"sets": 4, "reps": 10, "weight_kg": 57.5, "date": "2026-03-20"},
                "rpe_ceiling": 8.5,
            },
        ]
    return {
        "date": "2026-03-23",
        "label": "Верх",
        "day_type": "strength",
        "recovery": {"score": 70},
        "meso_phase": "accumulation",
        "sleep": 7.0,
        "energy": 3,
        "exercises": exercises,
        "rpe_ceiling": 8.5,
        "summary": "Восстановление в норме.",
    }


class TestApplyAdaptation:
    """Тесты применения адаптации к прогнозу."""

    def test_normal_no_changes(self):
        """NORMAL → прогноз не меняется."""
        pred = _make_prediction()
        adaptation = compute_session_adaptation(65, 7.0, 3, "accumulation")
        result = apply_adaptation_to_prediction(pred, adaptation)

        assert result["adapted"] is False
        assert result["adaptation_type"] == ADAPT_NORMAL
        assert result["exercises"][0]["prediction"]["weight_kg"] == 80.0

    def test_deload_reduces_weight(self):
        """DELOAD → вес × 0.6."""
        pred = _make_prediction()
        adaptation = {
            "type": ADAPT_DELOAD,
            "weight_factor": 0.6,
            "sets_delta": -1,
            "rpe_ceiling": 6.0,
            "reason": "test",
            "emoji": "🔴",
            "short_label": "Deload",
        }
        result = apply_adaptation_to_prediction(pred, adaptation)

        assert result["adapted"] is True
        assert result["adaptation_type"] == ADAPT_DELOAD
        # 80.0 × 0.6 = 48.0
        assert result["exercises"][0]["prediction"]["weight_kg"] == 48.0
        # 60.0 × 0.6 = 36.0
        assert result["exercises"][1]["prediction"]["weight_kg"] == 36.0
        # Подходы: 4 − 1 = 3
        assert result["exercises"][0]["prediction"]["sets"] == 3
        # RPE ceiling
        assert result["exercises"][0]["rpe_ceiling"] == 6.0

    def test_light_holds_last_weight(self):
        """LIGHT → вес = last_result (не повышаем)."""
        pred = _make_prediction()
        adaptation = {
            "type": ADAPT_LIGHT,
            "weight_factor": 1.0,
            "sets_delta": -1,
            "rpe_ceiling": 7.0,
            "reason": "test",
            "emoji": "⚠️",
            "short_label": "Облегчённая",
        }
        result = apply_adaptation_to_prediction(pred, adaptation)

        assert result["adapted"] is True
        # Должен взять last_result.weight_kg = 77.5 (не прогноз 80.0)
        assert result["exercises"][0]["prediction"]["weight_kg"] == 77.5
        assert result["exercises"][1]["prediction"]["weight_kg"] == 57.5
        # Подходы: 4 − 1 = 3
        assert result["exercises"][0]["prediction"]["sets"] == 3

    def test_boost_adds_weight(self):
        """BOOST → +2.5 кг к прогнозу."""
        pred = _make_prediction()
        adaptation = {
            "type": ADAPT_BOOST,
            "weight_factor": 1.0,
            "sets_delta": 0,
            "rpe_ceiling": 9.5,
            "reason": "test",
            "emoji": "🔥",
            "short_label": "Усиленная",
        }
        result = apply_adaptation_to_prediction(pred, adaptation)

        assert result["adapted"] is True
        # 80.0 + 2.5 = 82.5
        assert result["exercises"][0]["prediction"]["weight_kg"] == 82.5
        # 60.0 + 2.5 = 62.5
        assert result["exercises"][1]["prediction"]["weight_kg"] == 62.5
        # Подходы не меняются
        assert result["exercises"][0]["prediction"]["sets"] == 4

    def test_sets_never_below_one(self):
        """Минимум 1 подход даже при sets_delta = -1."""
        pred = _make_prediction([{
            "exercise_name": "Планка",
            "prediction": {"sets": 1, "reps": 1, "weight_kg": None},
            "last_result": None,
            "rpe_ceiling": 8.5,
        }])
        adaptation = {
            "type": ADAPT_LIGHT,
            "weight_factor": 1.0,
            "sets_delta": -1,
            "rpe_ceiling": 7.0,
            "reason": "test",
            "emoji": "⚠️",
            "short_label": "test",
        }
        result = apply_adaptation_to_prediction(pred, adaptation)
        assert result["exercises"][0]["prediction"]["sets"] == 1  # не 0

    def test_none_prediction_returns_as_is(self):
        """None prediction → возвращается None."""
        result = apply_adaptation_to_prediction(None, {"type": ADAPT_NORMAL})
        assert result is None

    def test_empty_exercises(self):
        """Пустые exercises → возвращается без изменений."""
        pred = {"exercises": []}
        adaptation = {"type": ADAPT_LIGHT, "weight_factor": 1.0, "sets_delta": -1,
                       "rpe_ceiling": 7.0, "reason": "x", "emoji": "x", "short_label": "x"}
        result = apply_adaptation_to_prediction(pred, adaptation)
        assert result == pred

    def test_original_exercises_preserved(self):
        """Оригинальные прогнозы сохраняются в original_exercises."""
        pred = _make_prediction()
        adaptation = {
            "type": ADAPT_DELOAD,
            "weight_factor": 0.6,
            "sets_delta": -1,
            "rpe_ceiling": 6.0,
            "reason": "test",
            "emoji": "🔴",
            "short_label": "Deload",
        }
        result = apply_adaptation_to_prediction(pred, adaptation)

        assert "original_exercises" in result
        # Оригинальный вес не модифицирован
        assert result["original_exercises"][0]["prediction"]["weight_kg"] == 80.0


# ═══════════════════════════════════════════════════════════════════════════
# format_adaptation_block
# ═══════════════════════════════════════════════════════════════════════════

class TestFormatAdaptationBlock:
    """Тесты форматирования блока адаптации."""

    def test_no_adaptation_returns_empty(self):
        """Без адаптации → пустая строка."""
        assert format_adaptation_block(None) == ""
        assert format_adaptation_block({"adapted": False}) == ""

    def test_deload_block_contains_info(self):
        """Deload-блок содержит нужную информацию."""
        pred = _make_prediction()
        adaptation = {
            "type": ADAPT_DELOAD,
            "weight_factor": 0.6,
            "sets_delta": -1,
            "rpe_ceiling": 6.0,
            "reason": "Тело просит отдыха",
            "emoji": "🔴",
            "short_label": "Deload-день",
        }
        adapted = apply_adaptation_to_prediction(pred, adaptation)
        block = format_adaptation_block(adapted)

        assert "Deload-день" in block
        assert "🔴" in block
        assert "Тело просит отдыха" in block
        assert "Жим лёжа" in block
        assert "48.0 кг" in block  # 80 × 0.6

    def test_boost_block_shows_increase(self):
        """Boost-блок показывает увеличение."""
        pred = _make_prediction()
        adaptation = {
            "type": ADAPT_BOOST,
            "weight_factor": 1.0,
            "sets_delta": 0,
            "rpe_ceiling": 9.5,
            "reason": "Отличный день!",
            "emoji": "🔥",
            "short_label": "Усиленная",
        }
        adapted = apply_adaptation_to_prediction(pred, adaptation)
        block = format_adaptation_block(adapted)

        assert "Усиленная" in block
        assert "🔥" in block
        assert "82.5 кг" in block  # 80 + 2.5

    def test_rpe_ceiling_shown_when_low(self):
        """RPE-потолок показывается когда < 8.5."""
        pred = _make_prediction()
        adaptation = {
            "type": ADAPT_LIGHT,
            "weight_factor": 1.0,
            "sets_delta": -1,
            "rpe_ceiling": 7.0,
            "reason": "Не лучший день",
            "emoji": "⚠️",
            "short_label": "Облегчённая",
        }
        adapted = apply_adaptation_to_prediction(pred, adaptation)
        block = format_adaptation_block(adapted)

        assert "RPE-потолок: 7.0/10" in block
