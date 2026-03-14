"""
tests/test_parsers.py — Тесты для NLP-парсеров метрик и тренировок.
"""
import pytest
from ai.response_parser import (
    parse_metrics_from_message,
    is_metrics_report,
    parse_workout_from_message,
    is_workout_report,
    parse_nutrition_from_message,
    is_nutrition_report,
    parse_exercises_from_message,
)


# ─── parse_metrics_from_message ─────────────────────────────────────────────

class TestSleepParsing:
    def test_sleep_classic(self):
        r = parse_metrics_from_message("спал 7ч")
        assert r["sleep_hours"] == 7.0

    def test_sleep_with_hours_word(self):
        r = parse_metrics_from_message("спал 8 часов")
        assert r["sleep_hours"] == 8.0

    def test_sleep_decimal(self):
        r = parse_metrics_from_message("спал 7.5 часов")
        assert r["sleep_hours"] == 7.5

    def test_sleep_decimal_comma(self):
        r = parse_metrics_from_message("спал 6,5 ч")
        assert r["sleep_hours"] == 6.5

    def test_sleep_pospyal(self):
        r = parse_metrics_from_message("поспал 6 часов, чувствую себя нормально")
        assert r["sleep_hours"] == 6.0

    def test_sleep_prospala(self):
        r = parse_metrics_from_message("проспала 9")
        assert r["sleep_hours"] == 9.0

    def test_sleep_chasov_sna(self):
        r = parse_metrics_from_message("8 часов сна сегодня")
        assert r["sleep_hours"] == 8.0

    def test_sleep_out_of_range(self):
        r = parse_metrics_from_message("спал 1 ч")
        assert "sleep_hours" not in r

    def test_sleep_too_large(self):
        r = parse_metrics_from_message("спал 25 часов")
        assert "sleep_hours" not in r


class TestWeightParsing:
    def test_weight_with_kg(self):
        r = parse_metrics_from_message("сегодня 82 кг")
        assert r["weight_kg"] == 82.0

    def test_weight_decimal_with_kg(self):
        r = parse_metrics_from_message("вес 79.5 кг")
        assert r["weight_kg"] == 79.5

    def test_weight_without_unit(self):
        r = parse_metrics_from_message("вес 82")
        assert r["weight_kg"] == 82.0

    def test_veshu(self):
        r = parse_metrics_from_message("вешу 80")
        assert r["weight_kg"] == 80.0

    def test_vesil(self):
        r = parse_metrics_from_message("весил 85 до диеты")
        assert r["weight_kg"] == 85.0

    def test_weight_out_of_range_low(self):
        r = parse_metrics_from_message("вес 20")
        assert "weight_kg" not in r

    def test_weight_out_of_range_high(self):
        r = parse_metrics_from_message("вес 300")
        assert "weight_kg" not in r


class TestWaterParsing:
    def test_water_liters(self):
        r = parse_metrics_from_message("выпил 2 литра воды")
        assert r["water_liters"] == 2.0

    def test_water_l_short(self):
        r = parse_metrics_from_message("1.5л воды сегодня")
        assert r["water_liters"] == 1.5

    def test_water_litrov(self):
        r = parse_metrics_from_message("3 литров воды")
        assert r["water_liters"] == 3.0

    def test_water_pil(self):
        r = parse_metrics_from_message("пил 2л сегодня")
        assert r["water_liters"] == 2.0

    def test_water_too_much(self):
        r = parse_metrics_from_message("15 литров")
        assert "water_liters" not in r


class TestStepsParsing:
    def test_steps_with_shagov(self):
        r = parse_metrics_from_message("сегодня 8000 шагов")
        assert r["steps"] == 8000

    def test_steps_shag_prefix(self):
        r = parse_metrics_from_message("пройдено 10000 шаги")
        assert r["steps"] == 10000

    def test_steps_proshjol(self):
        r = parse_metrics_from_message("прошёл 6500 сегодня")
        assert r["steps"] == 6500

    def test_steps_proshla(self):
        r = parse_metrics_from_message("прошла 12000 шагов")
        assert r["steps"] == 12000

    def test_steps_too_few_digits(self):
        r = parse_metrics_from_message("сделал 200 шагов")
        assert "steps" not in r


class TestEnergyParsing:
    def test_energy_word_otlichno(self):
        r = parse_metrics_from_message("чувствую себя отлично")
        assert r["energy"] == 5

    def test_energy_word_ustal(self):
        r = parse_metrics_from_message("устал после работы")
        assert r["energy"] == 2

    def test_energy_word_normalno(self):
        r = parse_metrics_from_message("нормально себя чувствую")
        assert r["energy"] == 3

    def test_energy_numeric(self):
        r = parse_metrics_from_message("энергия 4 сегодня")
        assert r["energy"] == 4

    def test_energy_numeric_with_colon(self):
        r = parse_metrics_from_message("энергия: 3")
        assert r["energy"] == 3

    def test_energy_out_of_range(self):
        r = parse_metrics_from_message("энергия 9")
        assert "energy" not in r


class TestMoodParsing:
    def test_mood_numeric(self):
        r = parse_metrics_from_message("настроение 4")
        assert r["mood"] == 4

    def test_mood_numeric_with_colon(self):
        r = parse_metrics_from_message("настроение: 2 сегодня")
        assert r["mood"] == 2

    def test_mood_out_of_range(self):
        r = parse_metrics_from_message("настроение 8")
        assert "mood" not in r


# ─── is_metrics_report ──────────────────────────────────────────────────────

class TestIsMetricsReport:
    def test_detects_spal(self):
        assert is_metrics_report("спал 7 часов")

    def test_detects_pospyal(self):
        assert is_metrics_report("поспал наконец нормально")

    def test_detects_prospal(self):
        assert is_metrics_report("проспал 9 часов")

    def test_detects_ves(self):
        assert is_metrics_report("вес 82 сегодня")

    def test_detects_veshu(self):
        assert is_metrics_report("вешу 80")

    def test_detects_kg(self):
        assert is_metrics_report("82 кг")

    def test_detects_shagov(self):
        assert is_metrics_report("8000 шагов прошёл")

    def test_detects_proshyol(self):
        assert is_metrics_report("прошёл сегодня много")

    def test_detects_energiya(self):
        assert is_metrics_report("энергия 4")

    def test_detects_nastroenie(self):
        assert is_metrics_report("настроение хорошее")

    def test_detects_puls(self):
        assert is_metrics_report("пульс 65")

    def test_no_false_positive(self):
        assert not is_metrics_report("привет как дела")

    def test_no_false_positive_workout(self):
        # Тренировочный текст без метрик
        assert not is_metrics_report("сделал 3 подхода")


# ─── parse_workout_from_message ─────────────────────────────────────────────

class TestWorkoutParsing:
    def test_duration(self):
        r = parse_workout_from_message("тренировался 45 минут")
        assert r["duration_min"] == 45

    def test_type_cardio(self):
        r = parse_workout_from_message("бег 5 км, кайф")
        assert r["type"] == "cardio"

    def test_type_strength(self):
        r = parse_workout_from_message("жим лёжа 100 кг")
        assert r["type"] == "strength"

    def test_completed_true(self):
        r = parse_workout_from_message("сделал всё, доволен")
        assert r["completed"] is True

    def test_completed_false(self):
        r = parse_workout_from_message("не закончил, время вышло")
        assert r["completed"] is False

    def test_notes_saved(self):
        text = "потренировался час"
        r = parse_workout_from_message(text)
        assert r["notes"] == text


# ─── parse_exercises_from_message ───────────────────────────────────────────

class TestExerciseParsing:
    def test_setsxreps(self):
        exercises = parse_exercises_from_message("жим 3х10 80кг")
        assert len(exercises) == 1
        e = exercises[0]
        assert e["sets"] == 3
        assert e["reps"] == 10
        assert e["weight_kg"] == 80.0

    def test_multiple_exercises(self):
        exercises = parse_exercises_from_message("присед 4х8 60кг, планка 60 сек")
        assert len(exercises) == 2

    def test_duration_seconds(self):
        exercises = parse_exercises_from_message("планка 90 сек")
        assert exercises[0]["duration_sec"] == 90

    def test_empty_text(self):
        exercises = parse_exercises_from_message("привет как дела")
        assert exercises == []


# ─── parse_nutrition_from_message ───────────────────────────────────────────

class TestNutritionParsing:
    def test_calories(self):
        r = parse_nutrition_from_message("съел 2000 ккал")
        assert r["calories"] == 2000

    def test_protein(self):
        r = parse_nutrition_from_message("150 г белка")
        assert r["protein_g"] == 150.0

    def test_junk_food(self):
        r = parse_nutrition_from_message("поел бургер и чипсы")
        assert r["junk_food"] == 1

    def test_no_junk(self):
        r = parse_nutrition_from_message("гречка с курицей 400 ккал")
        assert r.get("junk_food") != 1


class TestIsNutritionReport:
    def test_poel(self):
        assert is_nutrition_report("поел нормально")

    def test_zavtrak(self):
        assert is_nutrition_report("завтрак был хороший")

    def test_kcal(self):
        assert is_nutrition_report("2000 ккал сегодня")

    def test_no_match(self):
        assert not is_nutrition_report("хорошо поспал")


# ─── _parse_meal_args ────────────────────────────────────────────────────────

class TestMealArgsParsing:
    """Tests for the /meal command parser."""

    def _parse(self, text):
        from bot.commands import _parse_meal_args
        return _parse_meal_args(text)

    def test_full_macro(self):
        r = self._parse("овсянка 350ккал Б12 Ж6 У60")
        assert r["calories"] == 350
        assert r["protein_g"] == 12.0
        assert r["fat_g"] == 6.0
        assert r["carbs_g"] == 60.0
        assert "овсянка" in r["meal_notes"]

    def test_only_calories(self):
        r = self._parse("500ккал")
        assert r["calories"] == 500
        assert "protein_g" not in r

    def test_calories_with_space(self):
        r = self._parse("2100 ккал Б150 Ж70 У210")
        assert r["calories"] == 2100
        assert r["protein_g"] == 150.0

    def test_decimal_macros(self):
        r = self._parse("300ккал Б12.5 Ж4,5 У40")
        assert r["protein_g"] == 12.5
        assert r["fat_g"] == 4.5

    def test_water_liters(self):
        r = self._parse("1.5л В1.5л")
        assert r.get("water_ml") == 1500

    def test_water_ml(self):
        r = self._parse("В500")
        assert r["water_ml"] == 500

    def test_no_macros_returns_empty(self):
        r = self._parse("просто текст без цифр")
        assert "calories" not in r
        assert "protein_g" not in r

    def test_calorie_out_of_range(self):
        r = self._parse("50ккал")   # below 50 threshold
        assert "calories" not in r

    def test_name_extraction(self):
        r = self._parse("гречка с курицей 400ккал Б35 Ж8 У50")
        assert "гречка с курицей" in r["meal_notes"]
