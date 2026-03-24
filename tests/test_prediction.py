"""
tests/test_prediction.py — Тесты для scheduler/prediction.py (Workout Prediction).

Покрывает:
  - get_today_plan_exercises: извлечение сегодняшних упражнений из плана
  - get_exercise_prediction: прогноз для одного упражнения (прогрессия, deload, low recovery)
  - build_workout_prediction: полный прогноз со всеми компонентами
  - format_prediction_block: форматирование для Telegram
  - _analyze_weight_trend: определение тренда веса
  - tool registration: get_workout_prediction зарегистрирован в tools.py и tool_executor.py
"""
import datetime
import json
import pytest
from unittest.mock import patch, MagicMock

from tests.conftest import insert_user


# ═══════════════════════════════════════════════════════════════════════════
# Хелперы для создания тестовых данных
# ═══════════════════════════════════════════════════════════════════════════

def _insert_plan_with_exercises(conn, user_id: int, exercises: list, day_type: str = "strength"):
    """Создаёт активный план с тренировкой на сегодня."""
    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())
    week_start = monday.isoformat()
    iso = monday.isocalendar()
    plan_id = f"PLN-{user_id}-{iso.year:04d}{iso.week:02d}"

    days = []
    for i in range(7):
        d = monday + datetime.timedelta(days=i)
        day = {
            "weekday": ["пн", "вт", "ср", "чт", "пт", "сб", "вс"][i],
            "date": d.isoformat(),
            "type": "rest",
            "label": "Отдых",
            "completed": False,
        }
        if d == today:
            day["type"] = day_type
            day["label"] = "Силовая — верх"
            day["exercises"] = exercises
        days.append(day)

    conn.execute("""
        INSERT OR REPLACE INTO training_plan
        (plan_id, user_id, week_start, status, plan_json, workouts_planned, workouts_completed)
        VALUES (?, ?, ?, 'active', ?, 3, 0)
    """, (plan_id, user_id, week_start, json.dumps(days, ensure_ascii=False)))
    conn.commit()
    return plan_id


def _insert_exercise_result(conn, user_id: int, name: str, sets: int, reps: int,
                            weight_kg: float = None, days_ago: int = 3):
    """Вставляет результат упражнения N дней назад."""
    date = (datetime.date.today() - datetime.timedelta(days=days_ago)).isoformat()
    conn.execute("""
        INSERT INTO exercise_results (user_id, date, exercise_name, sets, reps, weight_kg)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, date, name, sets, reps, weight_kg))
    conn.commit()


def _insert_metrics(conn, user_id: int, sleep: float = 7.5, energy: int = 4, days_ago: int = 0):
    """Вставляет метрики за указанный день."""
    date = (datetime.date.today() - datetime.timedelta(days=days_ago)).isoformat()
    conn.execute("""
        INSERT OR REPLACE INTO metrics (user_id, date, sleep_hours, energy)
        VALUES (?, ?, ?, ?)
    """, (user_id, date, sleep, energy))
    conn.commit()


# ═══════════════════════════════════════════════════════════════════════════
# Тесты: get_today_plan_exercises
# ═══════════════════════════════════════════════════════════════════════════

class TestGetTodayPlanExercises:
    """Тесты извлечения упражнений из плана на сегодня."""

    def test_returns_exercises_when_plan_exists(self, patched_db):
        uid = insert_user(patched_db)
        exercises = [
            {"name": "Жим лёжа", "sets": 4, "reps": 8, "weight_kg_target": 60},
            {"name": "Тяга в наклоне", "sets": 3, "reps": 10, "weight_kg_target": 50},
        ]
        _insert_plan_with_exercises(patched_db, uid, exercises)

        from scheduler.prediction import get_today_plan_exercises
        result = get_today_plan_exercises(uid)

        assert result is not None
        assert result["day_type"] == "strength"
        assert len(result["exercises"]) == 2
        assert result["exercises"][0]["name"] == "Жим лёжа"

    def test_returns_none_when_rest_day(self, patched_db):
        uid = insert_user(patched_db)
        _insert_plan_with_exercises(patched_db, uid, [], day_type="rest")

        from scheduler.prediction import get_today_plan_exercises
        result = get_today_plan_exercises(uid)

        assert result is None

    def test_returns_none_when_no_plan(self, patched_db):
        uid = insert_user(patched_db)

        from scheduler.prediction import get_today_plan_exercises
        result = get_today_plan_exercises(uid)

        assert result is None

    def test_returns_none_when_already_completed(self, patched_db):
        uid = insert_user(patched_db)
        exercises = [{"name": "Приседания", "sets": 4, "reps": 8}]
        plan_id = _insert_plan_with_exercises(patched_db, uid, exercises)

        # Помечаем сегодняшний день как completed
        row = patched_db.execute(
            "SELECT plan_json FROM training_plan WHERE plan_id = ?", (plan_id,)
        ).fetchone()
        days = json.loads(row["plan_json"])
        today_str = datetime.date.today().isoformat()
        for d in days:
            if d["date"] == today_str:
                d["completed"] = True
        patched_db.execute(
            "UPDATE training_plan SET plan_json = ? WHERE plan_id = ?",
            (json.dumps(days), plan_id)
        )
        patched_db.commit()

        from scheduler.prediction import get_today_plan_exercises
        result = get_today_plan_exercises(uid)

        assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# Тесты: get_exercise_prediction
# ═══════════════════════════════════════════════════════════════════════════

class TestGetExercisePrediction:
    """Тесты прогноза для одного упражнения."""

    def test_first_time_exercise(self, patched_db):
        """Нет истории → возвращает план."""
        uid = insert_user(patched_db)

        from scheduler.prediction import get_exercise_prediction
        pred = get_exercise_prediction(
            uid, "Жим лёжа",
            plan_sets=4, plan_reps=8, plan_weight_target=60.0,
        )

        assert pred["exercise_name"] == "Жим лёжа"
        assert pred["last_result"] is None
        assert pred["prediction"]["weight_kg"] == 60.0
        assert "Первый раз" in pred["reasoning"]

    def test_weight_progression(self, patched_db):
        """Последний результат >= плановому → повышаем вес на 2.5 кг."""
        uid = insert_user(patched_db)
        _insert_exercise_result(patched_db, uid, "Жим лёжа", sets=4, reps=8, weight_kg=60.0, days_ago=3)

        from scheduler.prediction import get_exercise_prediction
        pred = get_exercise_prediction(
            uid, "Жим лёжа",
            plan_sets=4, plan_reps=8, plan_weight_target=60.0,
        )

        assert pred["last_result"]["weight_kg"] == 60.0
        assert pred["prediction"]["weight_kg"] == 62.5
        assert "62.5" in pred["reasoning"]

    def test_catching_up_to_plan(self, patched_db):
        """Последний результат < планового → показываем цель из плана."""
        uid = insert_user(patched_db)
        _insert_exercise_result(patched_db, uid, "Жим лёжа", sets=4, reps=8, weight_kg=55.0, days_ago=3)

        from scheduler.prediction import get_exercise_prediction
        pred = get_exercise_prediction(
            uid, "Жим лёжа",
            plan_sets=4, plan_reps=8, plan_weight_target=60.0,
        )

        assert pred["prediction"]["weight_kg"] == 60.0
        assert "цель" in pred["reasoning"].lower() or "догоняй" in pred["reasoning"].lower()

    def test_deload_phase(self, patched_db):
        """Deload → снижаем вес до 60%."""
        uid = insert_user(patched_db)
        _insert_exercise_result(patched_db, uid, "Жим лёжа", sets=4, reps=8, weight_kg=60.0, days_ago=3)

        from scheduler.prediction import get_exercise_prediction
        pred = get_exercise_prediction(
            uid, "Жим лёжа",
            plan_sets=4, plan_reps=8,
            meso_phase="deload",
        )

        assert pred["prediction"]["weight_kg"] == 36.0  # 60 * 0.6
        assert pred["rpe_ceiling"] == 6.0
        assert "deload" in pred["reasoning"].lower()

    def test_low_recovery(self, patched_db):
        """Плохое восстановление → не повышаем вес."""
        uid = insert_user(patched_db)
        _insert_exercise_result(patched_db, uid, "Жим лёжа", sets=4, reps=8, weight_kg=60.0, days_ago=3)

        from scheduler.prediction import get_exercise_prediction
        pred = get_exercise_prediction(
            uid, "Жим лёжа",
            plan_sets=4, plan_reps=8, plan_weight_target=60.0,
            recovery_score=35,
        )

        # Не повышаем — остаёмся на 60
        assert pred["prediction"]["weight_kg"] == 60.0
        assert pred["rpe_ceiling"] == 7.0
        assert "recovery" in pred["reasoning"].lower()

    def test_bodyweight_exercise_progression(self, patched_db):
        """Упражнение без веса → повышаем повторения."""
        uid = insert_user(patched_db)
        _insert_exercise_result(patched_db, uid, "Отжимания", sets=3, reps=15, weight_kg=None, days_ago=3)

        from scheduler.prediction import get_exercise_prediction
        pred = get_exercise_prediction(
            uid, "Отжимания",
            plan_sets=3, plan_reps=15,
        )

        assert pred["prediction"]["reps"] == 16
        assert "16" in pred["reasoning"]


# ═══════════════════════════════════════════════════════════════════════════
# Тесты: _analyze_weight_trend
# ═══════════════════════════════════════════════════════════════════════════

class TestAnalyzeWeightTrend:
    """Тесты анализа тренда веса через реальные данные в БД."""

    def test_growing_trend(self, patched_db):
        uid = insert_user(patched_db)
        # Вставляем результаты с растущим весом (старый → новый)
        _insert_exercise_result(patched_db, uid, "Жим лёжа", 4, 8, 55.0, days_ago=10)
        _insert_exercise_result(patched_db, uid, "Жим лёжа", 4, 8, 60.0, days_ago=5)
        _insert_exercise_result(patched_db, uid, "Жим лёжа", 4, 8, 65.0, days_ago=1)

        from scheduler.prediction import _analyze_weight_trend
        # Берём историю через реальный SQL
        rows = patched_db.execute("""
            SELECT sets, reps, weight_kg, date FROM exercise_results
            WHERE user_id = ? AND exercise_name = ?
            ORDER BY date DESC, id DESC LIMIT 3
        """, (uid, "Жим лёжа")).fetchall()

        assert _analyze_weight_trend(rows) == "growing"

    def test_stable_trend(self, patched_db):
        uid = insert_user(patched_db)
        _insert_exercise_result(patched_db, uid, "Жим лёжа", 4, 8, 60.0, days_ago=5)
        _insert_exercise_result(patched_db, uid, "Жим лёжа", 4, 8, 60.0, days_ago=1)

        from scheduler.prediction import _analyze_weight_trend
        rows = patched_db.execute("""
            SELECT sets, reps, weight_kg, date FROM exercise_results
            WHERE user_id = ? AND exercise_name = ?
            ORDER BY date DESC, id DESC LIMIT 3
        """, (uid, "Жим лёжа")).fetchall()

        assert _analyze_weight_trend(rows) == "stable"

    def test_unknown_with_single_entry(self, patched_db):
        uid = insert_user(patched_db)
        _insert_exercise_result(patched_db, uid, "Жим лёжа", 4, 8, 60.0, days_ago=1)

        from scheduler.prediction import _analyze_weight_trend
        rows = patched_db.execute("""
            SELECT sets, reps, weight_kg, date FROM exercise_results
            WHERE user_id = ? AND exercise_name = ?
            ORDER BY date DESC, id DESC LIMIT 3
        """, (uid, "Жим лёжа")).fetchall()

        assert _analyze_weight_trend(rows) == "unknown"

    def test_unknown_with_no_weights(self, patched_db):
        uid = insert_user(patched_db)
        # Упражнения без веса
        patched_db.execute(
            "INSERT INTO exercise_results (user_id, date, exercise_name, sets, reps) VALUES (?, ?, ?, ?, ?)",
            (uid, datetime.date.today().isoformat(), "Планка", 3, 0)
        )
        patched_db.execute(
            "INSERT INTO exercise_results (user_id, date, exercise_name, sets, reps) VALUES (?, ?, ?, ?, ?)",
            (uid, (datetime.date.today() - datetime.timedelta(days=3)).isoformat(), "Планка", 3, 0)
        )
        patched_db.commit()

        from scheduler.prediction import _analyze_weight_trend
        rows = patched_db.execute("""
            SELECT sets, reps, weight_kg, date FROM exercise_results
            WHERE user_id = ? AND exercise_name = ?
            ORDER BY date DESC, id DESC LIMIT 3
        """, (uid, "Планка")).fetchall()

        assert _analyze_weight_trend(rows) == "unknown"


# ═══════════════════════════════════════════════════════════════════════════
# Тесты: build_workout_prediction (интеграция)
# ═══════════════════════════════════════════════════════════════════════════

class TestBuildWorkoutPrediction:
    """Интеграционные тесты полного прогноза."""

    def test_returns_none_when_no_plan(self, patched_db):
        uid = insert_user(patched_db)

        from scheduler.prediction import build_workout_prediction
        result = build_workout_prediction(uid)

        assert result is None

    def test_full_prediction_with_data(self, patched_db):
        uid = insert_user(patched_db)
        exercises = [
            {"name": "Жим лёжа", "sets": 4, "reps": 8, "weight_kg_target": 60},
        ]
        _insert_plan_with_exercises(patched_db, uid, exercises)
        _insert_exercise_result(patched_db, uid, "Жим лёжа", sets=4, reps=8, weight_kg=57.5, days_ago=3)
        _insert_metrics(patched_db, uid, sleep=7.5, energy=4)

        from scheduler.prediction import build_workout_prediction

        # Патчим mesocycle и recovery которые делают свои запросы
        with patch("scheduler.prediction.get_connection", return_value=patched_db):
            result = build_workout_prediction(uid)

        assert result is not None
        assert result["label"] == "Силовая — верх"
        assert len(result["exercises"]) == 1

        ex_pred = result["exercises"][0]
        assert ex_pred["exercise_name"] == "Жим лёжа"
        assert ex_pred["prediction"]["weight_kg"] == 60.0  # catching up to plan target


# ═══════════════════════════════════════════════════════════════════════════
# Тесты: format_prediction_block
# ═══════════════════════════════════════════════════════════════════════════

class TestFormatPredictionBlock:
    """Тесты форматирования прогноза для Telegram."""

    def test_formats_exercises_with_predictions(self):
        from scheduler.prediction import format_prediction_block

        prediction = {
            "exercises": [
                {
                    "exercise_name": "Жим лёжа",
                    "prediction": {"sets": 4, "reps": 8, "weight_kg": 62.5},
                    "last_result": {"sets": 4, "reps": 8, "weight_kg": 60.0, "date": "2026-03-19"},
                    "rpe_ceiling": 8.5,
                },
            ],
            "rpe_ceiling": 8.5,
            "summary": "Восстановление отличное — можно жать!",
        }

        text = format_prediction_block(prediction)

        assert "Прогноз" in text
        assert "Жим лёжа" in text
        assert "62.5" in text
        assert "было:" in text
        assert "60.0" in text
        assert "можно жать" in text

    def test_empty_prediction_returns_empty(self):
        from scheduler.prediction import format_prediction_block

        assert format_prediction_block(None) == ""
        assert format_prediction_block({}) == ""
        assert format_prediction_block({"exercises": []}) == ""

    def test_shows_rpe_warning_when_low(self):
        from scheduler.prediction import format_prediction_block

        prediction = {
            "exercises": [
                {
                    "exercise_name": "Приседания",
                    "prediction": {"sets": 3, "reps": 8, "weight_kg": 36.0},
                    "last_result": None,
                    "rpe_ceiling": 6.0,
                },
            ],
            "rpe_ceiling": 6.0,
            "summary": "Deload-неделя.",
        }

        text = format_prediction_block(prediction)
        assert "RPE-потолок" in text
        assert "6.0" in text


# ═══════════════════════════════════════════════════════════════════════════
# Тесты: Tool registration
# ═══════════════════════════════════════════════════════════════════════════

class TestToolRegistration:
    """Проверяем что инструмент зарегистрирован корректно."""

    def test_tool_in_all_tools(self):
        from ai.tools import ALL_TOOLS, TOOL_BY_NAME
        names = [t["name"] for t in ALL_TOOLS]
        assert "get_workout_prediction" in names
        assert "get_workout_prediction" in TOOL_BY_NAME

    def test_tool_schema_valid(self):
        from ai.tools import TOOL_BY_NAME
        tool = TOOL_BY_NAME["get_workout_prediction"]
        assert tool["name"] == "get_workout_prediction"
        assert "input_schema" in tool
        assert tool["input_schema"]["type"] == "object"

    def test_tool_executor_dispatch(self):
        """Проверяем что tool_executor знает о get_workout_prediction."""
        from ai.tool_executor import _DISPATCH
        # Диспетчер — module-level dict; проверяем ключ напрямую
        assert "get_workout_prediction" in _DISPATCH
