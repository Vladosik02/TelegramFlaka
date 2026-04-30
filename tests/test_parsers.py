"""
tests/test_parsers.py — Тесты для активных парсеров.

Удалены тесты parse_metrics_from_message, is_metrics_report,
parse_workout_from_message, is_workout_report, parse_nutrition_from_message,
is_nutrition_report — функции удалены из response_parser.py (заменены Tool Use).
"""
import pytest
from ai.response_parser import parse_exercises_from_message


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
