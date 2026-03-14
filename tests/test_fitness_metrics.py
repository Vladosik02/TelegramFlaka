"""
tests/test_fitness_metrics.py — Тесты нормализации фитнес-метрик и вычисления скора.

Проверяем:
  • normalize_pushups / normalize_squats / normalize_plank — piecewise-linear интерполяцию.
  • compute_fitness_score — формулу с весами 0.35 / 0.35 / 0.30.
  • get_fitness_level — присвоение уровней по скору.
  • save_fitness_test — корректное сохранение в БД с автоматическим расчётом.
  • days_since_last_test — подсчёт дней с последнего теста.
"""
import pytest
import datetime
from db.queries.fitness_metrics import (
    normalize_pushups,
    normalize_squats,
    normalize_plank,
    compute_fitness_score,
    get_fitness_level,
    save_fitness_test,
    get_last_fitness_test,
    days_since_last_test,
)
from tests.conftest import insert_user


# ─── normalize_pushups ────────────────────────────────────────────────────────

class TestNormalizePushups:

    def test_zero_returns_zero(self):
        assert normalize_pushups(0) == 0.0

    def test_negative_returns_zero(self):
        assert normalize_pushups(-5) == 0.0

    def test_world_class_cap_at_100(self):
        assert normalize_pushups(100) == 100.0
        assert normalize_pushups(200) == 100.0

    def test_known_breakpoint_10(self):
        # Таблица: (10, 18)
        assert normalize_pushups(10) == pytest.approx(18.0)

    def test_known_breakpoint_50(self):
        # Таблица: (50, 80)
        assert normalize_pushups(50) == pytest.approx(80.0)

    def test_interpolation_between_breakpoints(self):
        # Между (20, 35) и (30, 52): при raw=25 → 35 + 5/10*(52-35) = 35 + 8.5 = 43.5
        result = normalize_pushups(25)
        assert result == pytest.approx(43.5, abs=0.2)

    def test_returns_float(self):
        assert isinstance(normalize_pushups(30), float)

    def test_monotone_increasing(self):
        """Больше отжиманий → выше скор."""
        scores = [normalize_pushups(n) for n in range(0, 101, 10)]
        for i in range(1, len(scores)):
            assert scores[i] >= scores[i - 1]


# ─── normalize_squats ────────────────────────────────────────────────────────

class TestNormalizeSquats:

    def test_zero_returns_zero(self):
        assert normalize_squats(0) == 0.0

    def test_world_class_cap_at_100(self):
        assert normalize_squats(160) == 100.0
        assert normalize_squats(300) == 100.0

    def test_known_breakpoint_30(self):
        # Таблица: (30, 35)
        assert normalize_squats(30) == pytest.approx(35.0)

    def test_monotone_increasing(self):
        scores = [normalize_squats(n) for n in range(0, 161, 20)]
        for i in range(1, len(scores)):
            assert scores[i] >= scores[i - 1]


# ─── normalize_plank ────────────────────────────────────────────────────────

class TestNormalizePlank:

    def test_zero_returns_zero(self):
        assert normalize_plank(0) == 0.0

    def test_world_class_cap_at_100(self):
        assert normalize_plank(300) == 100.0
        assert normalize_plank(600) == 100.0

    def test_known_breakpoint_60(self):
        # Таблица: (60, 40)
        assert normalize_plank(60) == pytest.approx(40.0)

    def test_known_breakpoint_120(self):
        # McGill threshold: (120, 73)
        assert normalize_plank(120) == pytest.approx(73.0)

    def test_monotone_increasing(self):
        scores = [normalize_plank(n) for n in range(0, 301, 30)]
        for i in range(1, len(scores)):
            assert scores[i] >= scores[i - 1]

    def test_30_seconds_below_average(self):
        # Ниже среднего (таблица: (30, 20))
        assert normalize_plank(30) == pytest.approx(20.0)


# ─── compute_fitness_score ───────────────────────────────────────────────────

class TestComputeFitnessScore:

    def test_formula_weights(self):
        # pushups=100, squats=0, plank=0 → 100*0.35 = 35
        assert compute_fitness_score(100, 0, 0) == pytest.approx(35.0)

    def test_equal_scores(self):
        # 60*0.35 + 60*0.35 + 60*0.30 = 21 + 21 + 18 = 60
        assert compute_fitness_score(60, 60, 60) == pytest.approx(60.0)

    def test_max_score(self):
        assert compute_fitness_score(100, 100, 100) == pytest.approx(100.0)

    def test_zero_score(self):
        assert compute_fitness_score(0, 0, 0) == pytest.approx(0.0)

    def test_plank_weight_30pct(self):
        # Только планка: 0 + 0 + 100*0.30 = 30
        assert compute_fitness_score(0, 0, 100) == pytest.approx(30.0)

    def test_returns_rounded_float(self):
        result = compute_fitness_score(55.3, 62.7, 48.1)
        assert isinstance(result, float)
        # Проверяем что округлён до 1 знака
        assert result == round(result, 1)


# ─── get_fitness_level ───────────────────────────────────────────────────────

class TestGetFitnessLevel:

    def test_zero_score_is_lowest(self):
        level = get_fitness_level(0)
        assert isinstance(level, str)
        assert len(level) > 0

    def test_high_score_is_elite(self):
        assert get_fitness_level(95) == "Элитный"

    def test_score_75_is_excellent(self):
        assert get_fitness_level(75) == "Отлично"

    def test_score_60_is_good(self):
        assert get_fitness_level(60) == "Хорошо"

    def test_score_40_is_average(self):
        assert get_fitness_level(40) == "Средний"

    def test_score_25_is_below_average(self):
        assert get_fitness_level(25) == "Ниже среднего"

    def test_score_10_is_initial(self):
        assert get_fitness_level(10) == "Начальный"


# ─── save_fitness_test + get_last_fitness_test ───────────────────────────────

class TestSaveFitnessTest:

    def test_save_and_retrieve(self, patched_db):
        uid = insert_user(patched_db)
        today = datetime.date.today().isoformat()
        row_id = save_fitness_test(
            user_id=uid,
            tested_at=today,
            max_pushups=30,
            max_squats=50,
            plank_sec=90,
        )
        assert isinstance(row_id, int)
        assert row_id > 0

        last = get_last_fitness_test(uid)
        assert last is not None
        assert last["max_pushups"] == 30
        assert last["max_squats"] == 50
        assert last["plank_sec"] == 90
        assert last["fitness_score"] is not None
        assert 0 <= last["fitness_score"] <= 100

    def test_scores_auto_computed(self, patched_db):
        uid = insert_user(patched_db, telegram_id=100002)
        today = datetime.date.today().isoformat()
        save_fitness_test(uid, today, max_pushups=50, max_squats=80, plank_sec=180)

        last = get_last_fitness_test(uid)
        # pushups(50)=80, squats(80)=80, plank(180)=88
        # fitness = 80*0.35 + 80*0.35 + 88*0.30 = 28 + 28 + 26.4 = 82.4
        assert last["pushups_score"] == pytest.approx(80.0, abs=1)
        assert last["fitness_score"] == pytest.approx(82.4, abs=1)

    def test_no_test_returns_none(self, patched_db):
        uid = insert_user(patched_db, telegram_id=100003)
        assert get_last_fitness_test(uid) is None


# ─── days_since_last_test ────────────────────────────────────────────────────

class TestDaysSinceLastTest:

    def test_no_test_returns_none(self, patched_db):
        uid = insert_user(patched_db, telegram_id=100004)
        assert days_since_last_test(uid) is None

    def test_today_returns_zero(self, patched_db):
        uid = insert_user(patched_db, telegram_id=100005)
        today = datetime.date.today().isoformat()
        save_fitness_test(uid, today, max_pushups=20, max_squats=30, plank_sec=60)
        result = days_since_last_test(uid)
        assert result == 0

    def test_past_test_returns_correct_days(self, patched_db):
        uid = insert_user(patched_db, telegram_id=100006)
        past = (datetime.date.today() - datetime.timedelta(days=5)).isoformat()
        save_fitness_test(uid, past, max_pushups=20, max_squats=30, plank_sec=60)
        result = days_since_last_test(uid)
        assert result == 5
