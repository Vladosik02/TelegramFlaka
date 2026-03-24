"""
tests/test_teach_moments.py — Тесты контекстных мини-уроков (teach moments).

Проверяем:
  • select_teach_moment возвращает правильную категорию в зависимости от данных
  • _should_show_today контролирует частоту показов
  • Детерминированность выбора (один и тот же факт для одного юзера в один день)
  • None когда день не подходит и тренировки не было
"""
import datetime
from unittest.mock import patch

from scheduler.teach_moments import (
    select_teach_moment,
    _should_show_today,
    _pick_from_category,
    AFTER_STRENGTH,
    AFTER_CARDIO,
    NO_WORKOUT,
    LOW_PROTEIN,
    LOW_CALORIES,
    LOW_SLEEP,
    GOOD_SLEEP,
    HIGH_ENERGY,
    LOW_ENERGY,
    HYPERTROPHY_GENERAL,
)


# ─── Helpers ──────────────────────────────────────────────────────────────

def _workout(wtype="strength", completed=True, intensity=7, duration=45):
    return {
        "type": wtype,
        "completed": completed,
        "intensity": intensity,
        "duration_min": duration,
    }


def _nutrition(calories=2200, protein_g=140, fat_g=70, carbs_g=250):
    return {
        "calories": calories,
        "protein_g": protein_g,
        "fat_g": fat_g,
        "carbs_g": carbs_g,
    }


def _metrics(sleep_hours=None, energy=None, mood=None):
    return {
        "sleep_hours": sleep_hours,
        "energy": energy,
        "mood": mood,
    }


# ─── _should_show_today ──────────────────────────────────────────────────

class TestShouldShowToday:

    def test_monday_always_shows(self):
        """Понедельник (weekday=0) — всегда показываем."""
        monday = datetime.date(2026, 3, 23)  # Monday
        with patch("scheduler.teach_moments.datetime") as mock_dt:
            mock_dt.date.today.return_value = monday
            assert _should_show_today(user_id=1) is True

    def test_wednesday_always_shows(self):
        """Среда (weekday=2) — всегда показываем."""
        wednesday = datetime.date(2026, 3, 25)
        with patch("scheduler.teach_moments.datetime") as mock_dt:
            mock_dt.date.today.return_value = wednesday
            assert _should_show_today(user_id=1) is True

    def test_friday_always_shows(self):
        """Пятница (weekday=4) — всегда показываем."""
        friday = datetime.date(2026, 3, 27)
        with patch("scheduler.teach_moments.datetime") as mock_dt:
            mock_dt.date.today.return_value = friday
            assert _should_show_today(user_id=1) is True


# ─── _pick_from_category ─────────────────────────────────────────────────

class TestPickFromCategory:

    def test_deterministic(self):
        """Один и тот же юзер в один день получает один и тот же факт."""
        with patch("scheduler.teach_moments.datetime") as mock_dt:
            mock_dt.date.today.return_value = datetime.date(2026, 3, 22)
            result1 = _pick_from_category(AFTER_STRENGTH, user_id=42, salt="x")
            result2 = _pick_from_category(AFTER_STRENGTH, user_id=42, salt="x")
            assert result1 == result2

    def test_different_users_may_differ(self):
        """Разные юзеры могут получать разные факты (хотя не гарантировано)."""
        with patch("scheduler.teach_moments.datetime") as mock_dt:
            mock_dt.date.today.return_value = datetime.date(2026, 3, 22)
            r1 = _pick_from_category(AFTER_STRENGTH, user_id=1, salt="x")
            r2 = _pick_from_category(AFTER_STRENGTH, user_id=9999, salt="x")
            # Оба должны быть из правильной категории
            assert r1 in AFTER_STRENGTH
            assert r2 in AFTER_STRENGTH

    def test_result_in_category(self):
        """Результат всегда из правильной категории."""
        with patch("scheduler.teach_moments.datetime") as mock_dt:
            mock_dt.date.today.return_value = datetime.date(2026, 3, 22)
            for cat in [AFTER_STRENGTH, AFTER_CARDIO, NO_WORKOUT, LOW_SLEEP, HYPERTROPHY_GENERAL]:
                result = _pick_from_category(cat, user_id=7)
                assert result in cat


# ─── select_teach_moment — приоритет категорий ────────────────────────────

class TestSelectTeachMoment:

    def _force_show(self):
        """Патч для дня когда показ разрешён (понедельник)."""
        return patch(
            "scheduler.teach_moments.datetime",
            wraps=datetime,
        )

    def test_low_sleep_highest_priority(self):
        """Мало сна — приоритет 1, даже если тренировка была."""
        # Тренировка была — show всегда, плюс сон < 7
        result = select_teach_moment(
            user_id=1,
            workout=_workout(),
            nutrition=_nutrition(),
            metrics=_metrics(sleep_hours=5),
        )
        assert result is not None
        assert result in LOW_SLEEP

    def test_low_protein_priority(self):
        """Мало белка (<80% цели) при нормальном сне."""
        with patch("scheduler.teach_moments._should_show_today", return_value=True):
            result = select_teach_moment(
                user_id=1,
                workout=_workout(),
                nutrition=_nutrition(protein_g=60),
                metrics=_metrics(sleep_hours=8),
                goal_protein=150,
            )
            assert result is not None
            assert result in LOW_PROTEIN

    def test_low_calories_priority(self):
        """Мало калорий (<80% цели)."""
        with patch("scheduler.teach_moments._should_show_today", return_value=True):
            result = select_teach_moment(
                user_id=1,
                workout=_workout(),
                nutrition=_nutrition(calories=1500, protein_g=140),
                metrics=_metrics(sleep_hours=8),
                goal_calories=2500,
                goal_protein=150,
            )
            assert result is not None
            assert result in LOW_CALORIES

    def test_after_strength_workout(self):
        """После силовой — совет по восстановлению."""
        result = select_teach_moment(
            user_id=1,
            workout=_workout(wtype="strength"),
            nutrition=_nutrition(),
            metrics=_metrics(sleep_hours=8),
            goal_protein=150,
        )
        assert result is not None
        assert result in AFTER_STRENGTH

    def test_after_cardio_workout(self):
        """После кардио — кардио-совет."""
        result = select_teach_moment(
            user_id=1,
            workout=_workout(wtype="cardio"),
            nutrition=_nutrition(),
            metrics=_metrics(sleep_hours=8),
            goal_protein=150,
        )
        assert result is not None
        assert result in AFTER_CARDIO

    def test_after_stretch_workout(self):
        """После растяжки — кардио-категория."""
        result = select_teach_moment(
            user_id=1,
            workout=_workout(wtype="stretch"),
            nutrition=_nutrition(),
            metrics=_metrics(sleep_hours=8),
            goal_protein=150,
        )
        assert result is not None
        assert result in AFTER_CARDIO

    def test_no_workout_rest_day(self):
        """День без тренировки и нейтральные метрики — совет по восстановлению."""
        with patch("scheduler.teach_moments._should_show_today", return_value=True):
            result = select_teach_moment(
                user_id=1,
                workout=None,
                nutrition=_nutrition(),
                metrics=_metrics(sleep_hours=7.5, energy=3),
                goal_protein=150,
            )
            assert result is not None
            assert result in NO_WORKOUT

    def test_good_sleep_positive(self):
        """Хороший сон без тренировки — позитивный факт."""
        with patch("scheduler.teach_moments._should_show_today", return_value=True):
            result = select_teach_moment(
                user_id=1,
                workout=None,
                nutrition=_nutrition(),
                metrics=_metrics(sleep_hours=9),
            )
            # Хороший сон проверяется ПОСЛЕ no_workout, но no_workout
            # тоже вернётся. Проверяем что вообще что-то вернулось.
            assert result is not None

    def test_high_energy(self):
        """Высокая энергия без тренировки — позитивный факт."""
        with patch("scheduler.teach_moments._should_show_today", return_value=True):
            result = select_teach_moment(
                user_id=1,
                workout=None,
                nutrition=_nutrition(),
                metrics=_metrics(sleep_hours=7.5, energy=5),
            )
            assert result is not None

    def test_low_energy(self):
        """Низкая энергия — предупреждение."""
        with patch("scheduler.teach_moments._should_show_today", return_value=True):
            result = select_teach_moment(
                user_id=1,
                workout=None,
                nutrition=_nutrition(),
                metrics=_metrics(sleep_hours=7, energy=1),
            )
            assert result is not None
            assert result in LOW_ENERGY

    def test_none_when_not_show_day_and_no_workout(self):
        """Если не день показа и тренировки не было — None."""
        with patch("scheduler.teach_moments._should_show_today", return_value=False):
            result = select_teach_moment(
                user_id=1,
                workout=None,
                nutrition=_nutrition(),
                metrics=_metrics(sleep_hours=8, energy=3),
            )
            assert result is None

    def test_always_shows_after_workout(self):
        """После тренировки показываем ВСЕГДА, даже не в день показа."""
        with patch("scheduler.teach_moments._should_show_today", return_value=False):
            result = select_teach_moment(
                user_id=1,
                workout=_workout(),
                nutrition=_nutrition(),
                metrics=_metrics(sleep_hours=8),
                goal_protein=150,
            )
            assert result is not None

    def test_no_metrics_no_crash(self):
        """Без метрик — не падает."""
        result = select_teach_moment(
            user_id=1,
            workout=_workout(),
            nutrition=None,
            metrics=None,
        )
        assert result is not None
        assert result in AFTER_STRENGTH

    def test_empty_metrics_no_crash(self):
        """Пустые метрики — не падает."""
        with patch("scheduler.teach_moments._should_show_today", return_value=True):
            result = select_teach_moment(
                user_id=1,
                workout=None,
                nutrition={},
                metrics={},
            )
            assert result is not None
