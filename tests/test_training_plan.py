"""
tests/test_training_plan.py — Тесты функций плана тренировок (Фаза 8.3).

Проверяем:
  • make_plan_id — формат PLN-{user_id}-{YYYYWW}, уникальность по неделям.
  • get_current_week_start — возвращает понедельник текущей недели.
  • get_next_week_start — возвращает понедельник следующей недели.
  • save_training_plan + get_active_plan — полный CRUD цикл.
  • archive_plan — переводит план в archived-статус.
"""
import pytest
import datetime
import json
from db.queries.training_plan import (
    make_plan_id,
    get_current_week_start,
    get_next_week_start,
    save_training_plan,
    get_active_plan,
    get_last_plan,
    archive_plan,
)
from tests.conftest import insert_user


# ─── make_plan_id ────────────────────────────────────────────────────────────

class TestMakePlanId:

    def test_format_starts_with_pln(self):
        pid = make_plan_id(1, "2026-01-05")  # понедельник
        assert pid.startswith("PLN-")

    def test_format_contains_user_id(self):
        pid = make_plan_id(42, "2026-01-05")
        assert "-42-" in pid

    def test_format_contains_year_and_week(self):
        # 2026-01-05 — это ISO неделя 2 года 2026
        pid = make_plan_id(1, "2026-01-05")
        assert "202602" in pid  # год=2026, неделя=02

    def test_full_format(self):
        pid = make_plan_id(7, "2026-03-09")  # неделя 11
        assert pid == "PLN-7-202611"

    def test_different_weeks_different_ids(self):
        pid1 = make_plan_id(1, "2026-01-05")
        pid2 = make_plan_id(1, "2026-01-12")
        assert pid1 != pid2

    def test_different_users_different_ids(self):
        pid1 = make_plan_id(1, "2026-01-05")
        pid2 = make_plan_id(2, "2026-01-05")
        assert pid1 != pid2

    def test_same_user_same_week_same_id(self):
        pid1 = make_plan_id(5, "2026-06-01")
        pid2 = make_plan_id(5, "2026-06-01")
        assert pid1 == pid2

    def test_returns_string(self):
        assert isinstance(make_plan_id(1, "2026-01-05"), str)


# ─── get_current_week_start ──────────────────────────────────────────────────

class TestGetCurrentWeekStart:

    def test_returns_string(self):
        result = get_current_week_start()
        assert isinstance(result, str)

    def test_is_valid_iso_date(self):
        result = get_current_week_start()
        parsed = datetime.date.fromisoformat(result)
        assert parsed is not None

    def test_is_monday(self):
        result = get_current_week_start()
        parsed = datetime.date.fromisoformat(result)
        assert parsed.weekday() == 0  # 0 = понедельник

    def test_is_within_current_week(self):
        result = get_current_week_start()
        parsed = datetime.date.fromisoformat(result)
        today = datetime.date.today()
        # Разница должна быть 0-6 дней (сегодня ≥ понедельник)
        delta = (today - parsed).days
        assert 0 <= delta <= 6


# ─── get_next_week_start ─────────────────────────────────────────────────────

class TestGetNextWeekStart:

    def test_returns_string(self):
        result = get_next_week_start()
        assert isinstance(result, str)

    def test_is_monday(self):
        result = get_next_week_start()
        parsed = datetime.date.fromisoformat(result)
        assert parsed.weekday() == 0

    def test_is_7_days_after_current(self):
        current = datetime.date.fromisoformat(get_current_week_start())
        nxt = datetime.date.fromisoformat(get_next_week_start())
        assert (nxt - current).days == 7

    def test_is_in_future(self):
        nxt = datetime.date.fromisoformat(get_next_week_start())
        today = datetime.date.today()
        assert nxt > today


# ─── save_training_plan + get_active_plan ───────────────────────────────────

class TestTrainingPlanCRUD:

    def _make_plan_json(self) -> str:
        """Минимальный валидный JSON плана."""
        return json.dumps([
            {"day": "Monday", "workout_type": "strength", "exercises": [], "duration_min": 45},
            {"day": "Wednesday", "workout_type": "cardio", "exercises": [], "duration_min": 30},
        ])

    def test_save_and_retrieve_active_plan(self, patched_db):
        uid = insert_user(patched_db)
        week_start = "2026-03-09"
        plan_json = self._make_plan_json()

        plan_id = save_training_plan(
            uid, week_start, plan_json, workouts_planned=2, status="active"
        )
        assert plan_id == f"PLN-{uid}-202611"

        plan = get_active_plan(uid)
        assert plan is not None
        assert plan["plan_id"] == plan_id
        assert plan["week_start"] == week_start
        assert plan["status"] == "active"
        assert plan["workouts_planned"] == 2

    def test_no_active_plan_returns_none(self, patched_db):
        uid = insert_user(patched_db, telegram_id=200001)
        assert get_active_plan(uid) is None

    def test_save_replaces_same_week(self, patched_db):
        uid = insert_user(patched_db, telegram_id=200002)
        week_start = "2026-03-09"
        plan_json = self._make_plan_json()

        # Первое сохранение
        save_training_plan(uid, week_start, plan_json, workouts_planned=3)
        # Перезапись (INSERT OR REPLACE)
        save_training_plan(uid, week_start, plan_json, workouts_planned=5)

        # Должен быть один план, с обновлённым значением
        plan = get_last_plan(uid)
        assert plan["workouts_planned"] == 5

    def test_get_last_plan_returns_most_recent(self, patched_db):
        uid = insert_user(patched_db, telegram_id=200003)
        plan_json = self._make_plan_json()

        save_training_plan(uid, "2026-03-02", plan_json)
        save_training_plan(uid, "2026-03-09", plan_json)

        last = get_last_plan(uid)
        assert last["week_start"] == "2026-03-09"


# ─── archive_plan ────────────────────────────────────────────────────────────

class TestArchivePlan:

    def test_archive_sets_status(self, patched_db):
        uid = insert_user(patched_db, telegram_id=200004)
        week_start = "2026-03-09"
        plan_json = json.dumps([])

        plan_id = save_training_plan(uid, week_start, plan_json, workouts_planned=4)
        archive_plan(plan_id, workouts_completed=3, completion_pct=75.0)

        plan = get_last_plan(uid)
        assert plan["status"] == "archived"
        assert plan["workouts_completed"] == 3
        assert plan["completion_pct"] == pytest.approx(75.0)

    def test_archived_plan_not_in_active(self, patched_db):
        uid = insert_user(patched_db, telegram_id=200005)
        week_start = "2026-03-09"
        plan_id = save_training_plan(uid, week_start, json.dumps([]))

        archive_plan(plan_id, workouts_completed=0, completion_pct=0.0)

        assert get_active_plan(uid) is None
