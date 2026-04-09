"""
tests/test_nudges.py — Тесты проактивных нудж-сообщений (Фаза 8.4).

Проверяем:
  • _days_word / _workouts_word — склонение числительных.
  • _was_nudge_sent_recently — anti-spam cooldown.
  • Каждый из 5 чекеров: условие сработало / не сработало.
  • Приоритет нуджей: не более одного за запуск.
"""
import pytest
import datetime
from unittest.mock import AsyncMock, patch

from lang import days_word as _days_word, workouts_word as _workouts_word
from scheduler.nudges import (
    _was_nudge_sent_recently,
    _log_nudge,
    _check_drop_nudge,
    _check_recovery_nudge,
    _check_streak_nudge,
    _check_goal_nudge,
    check_and_send_nudges_for_user,
)
from tests.conftest import insert_user


# ─── _days_word ──────────────────────────────────────────────────────────────

class TestDaysWord:

    def test_1(self):       assert _days_word(1) == "день"
    def test_2(self):       assert _days_word(2) == "дня"
    def test_3(self):       assert _days_word(3) == "дня"
    def test_4(self):       assert _days_word(4) == "дня"
    def test_5(self):       assert _days_word(5) == "дней"
    def test_11(self):      assert _days_word(11) == "дней"   # исключение
    def test_12(self):      assert _days_word(12) == "дней"
    def test_21(self):      assert _days_word(21) == "день"
    def test_22(self):      assert _days_word(22) == "дня"
    def test_100(self):     assert _days_word(100) == "дней"
    def test_101(self):     assert _days_word(101) == "день"
    def test_111(self):     assert _days_word(111) == "дней"  # исключение — подростковые


# ─── _workouts_word ──────────────────────────────────────────────────────────

class TestWorkoutsWord:

    def test_1(self):    assert _workouts_word(1) == "тренировка"
    def test_2(self):    assert _workouts_word(2) == "тренировки"
    def test_5(self):    assert _workouts_word(5) == "тренировок"
    def test_11(self):   assert _workouts_word(11) == "тренировок"
    def test_21(self):   assert _workouts_word(21) == "тренировка"


# ─── _was_nudge_sent_recently ────────────────────────────────────────────────

class TestWasNudgeSentRecently:

    def test_no_log_returns_false(self, patched_db):
        uid = insert_user(patched_db, telegram_id=300001)
        assert _was_nudge_sent_recently(uid, "drop") is False

    def test_recent_log_returns_true(self, patched_db):
        uid = insert_user(patched_db, telegram_id=300002)
        # Логируем нудж только что
        _log_nudge(uid, "drop", "Test message")
        assert _was_nudge_sent_recently(uid, "drop") is True

    def test_old_log_returns_false(self, patched_db):
        uid = insert_user(patched_db, telegram_id=300003)
        # Вставляем старую запись (2 дня назад — за пределами 24ч кулдауна)
        old_time = (datetime.datetime.now() - datetime.timedelta(hours=49)).isoformat()
        patched_db.execute(
            "INSERT INTO nudge_log (user_id, nudge_type, sent_at) VALUES (?, ?, ?)",
            (uid, "drop", old_time),
        )
        patched_db.commit()
        assert _was_nudge_sent_recently(uid, "drop") is False

    def test_weekly_cooldown_type(self, patched_db):
        uid = insert_user(patched_db, telegram_id=300004)
        # streak — входит в NUDGE_WEEKLY_COOLDOWN → кулдаун 7 дней
        _log_nudge(uid, "streak", "Test")
        assert _was_nudge_sent_recently(uid, "streak") is True

    def test_weekly_cooldown_expired(self, patched_db):
        uid = insert_user(patched_db, telegram_id=300005)
        # Вставляем запись 8 дней назад — должна истечь
        old_time = (datetime.datetime.now() - datetime.timedelta(days=8)).isoformat()
        patched_db.execute(
            "INSERT INTO nudge_log (user_id, nudge_type, sent_at) VALUES (?, ?, ?)",
            (uid, "streak", old_time),
        )
        patched_db.commit()
        assert _was_nudge_sent_recently(uid, "streak") is False

    def test_different_type_not_blocked(self, patched_db):
        uid = insert_user(patched_db, telegram_id=300006)
        _log_nudge(uid, "drop", "Test")
        # recovery — другой тип, не должен блокироваться
        assert _was_nudge_sent_recently(uid, "recovery") is False


# ─── _check_drop_nudge ───────────────────────────────────────────────────────

class TestCheckDropNudge:

    def test_no_workouts_returns_none(self, patched_db):
        uid = insert_user(patched_db, telegram_id=301001)
        result = _check_drop_nudge(uid)
        assert result is None

    def test_recent_workout_returns_none(self, patched_db):
        uid = insert_user(patched_db, telegram_id=301002)
        today = datetime.date.today().isoformat()
        patched_db.execute(
            "INSERT INTO workouts (user_id, date, mode, completed) VALUES (?, ?, 'MAX', 1)",
            (uid, today),
        )
        patched_db.commit()
        assert _check_drop_nudge(uid) is None

    def test_3_days_ago_triggers(self, patched_db):
        uid = insert_user(patched_db, telegram_id=301003)
        old_date = (datetime.date.today() - datetime.timedelta(days=4)).isoformat()
        patched_db.execute(
            "INSERT INTO workouts (user_id, date, mode, completed) VALUES (?, ?, 'MAX', 1)",
            (uid, old_date),
        )
        patched_db.commit()
        result = _check_drop_nudge(uid)
        assert result is not None
        assert "📉" in result

    def test_2_days_ago_no_trigger(self, patched_db):
        """2 дня — меньше порога NUDGE_DROP_DAYS=3, нудж не срабатывает."""
        uid = insert_user(patched_db, telegram_id=301004)
        two_days_ago = (datetime.date.today() - datetime.timedelta(days=2)).isoformat()
        patched_db.execute(
            "INSERT INTO workouts (user_id, date, mode, completed) VALUES (?, ?, 'MAX', 1)",
            (uid, two_days_ago),
        )
        patched_db.commit()
        assert _check_drop_nudge(uid) is None

    def test_message_contains_days_count(self, patched_db):
        uid = insert_user(patched_db, telegram_id=301005)
        old_date = (datetime.date.today() - datetime.timedelta(days=5)).isoformat()
        patched_db.execute(
            "INSERT INTO workouts (user_id, date, mode, completed) VALUES (?, ?, 'MAX', 1)",
            (uid, old_date),
        )
        patched_db.commit()
        result = _check_drop_nudge(uid)
        assert result is not None
        assert "5" in result


# ─── _check_recovery_nudge ───────────────────────────────────────────────────

class TestCheckRecoveryNudge:

    def test_no_metrics_returns_none(self, patched_db):
        uid = insert_user(patched_db, telegram_id=302001)
        assert _check_recovery_nudge(uid) is None

    def test_good_sleep_returns_none(self, patched_db):
        uid = insert_user(patched_db, telegram_id=302002)
        today = datetime.date.today()
        for i in range(3):
            d = (today - datetime.timedelta(days=i)).isoformat()
            patched_db.execute(
                "INSERT INTO metrics (user_id, date, sleep_hours) VALUES (?, ?, ?)",
                (uid, d, 7.5),
            )
        patched_db.commit()
        assert _check_recovery_nudge(uid) is None

    def test_bad_sleep_triggers(self, patched_db):
        uid = insert_user(patched_db, telegram_id=302003)
        today = datetime.date.today()
        for i in range(3):
            d = (today - datetime.timedelta(days=i)).isoformat()
            patched_db.execute(
                "INSERT INTO metrics (user_id, date, sleep_hours) VALUES (?, ?, ?)",
                (uid, d, 4.5),  # < порога 6.0
            )
        patched_db.commit()
        result = _check_recovery_nudge(uid)
        assert result is not None
        assert "😴" in result

    def test_insufficient_data_returns_none(self, patched_db):
        """Меньше 3 дней данных — нудж не срабатывает."""
        uid = insert_user(patched_db, telegram_id=302004)
        today = datetime.date.today().isoformat()
        patched_db.execute(
            "INSERT INTO metrics (user_id, date, sleep_hours) VALUES (?, ?, ?)",
            (uid, today, 4.0),  # только 1 день
        )
        patched_db.commit()
        assert _check_recovery_nudge(uid) is None


# ─── _check_streak_nudge ─────────────────────────────────────────────────────

class TestCheckStreakNudge:

    def test_no_workouts_returns_none(self, patched_db):
        uid = insert_user(patched_db, telegram_id=303001)
        assert _check_streak_nudge(uid) is None

    def test_short_streak_returns_none(self, patched_db):
        """Стрик < 3 — нудж не срабатывает."""
        uid = insert_user(patched_db, telegram_id=303002)
        today = datetime.date.today()
        for i in range(2):
            d = (today - datetime.timedelta(days=i)).isoformat()
            patched_db.execute(
                "INSERT INTO workouts (user_id, date, mode, completed) VALUES (?, ?, 'MAX', 1)",
                (uid, d),
            )
        patched_db.commit()
        assert _check_streak_nudge(uid) is None

    def test_approaching_record_triggers(self, patched_db):
        """Текущий стрик в пределах NUDGE_STREAK_GAP от рекорда → нудж."""
        uid = insert_user(patched_db, telegram_id=303003)
        today = datetime.date.today()

        # Исторический рекорд: 10 дней подряд (давно)
        past_start = today - datetime.timedelta(days=30)
        for i in range(10):
            d = (past_start + datetime.timedelta(days=i)).isoformat()
            patched_db.execute(
                "INSERT INTO workouts (user_id, date, mode, completed) VALUES (?, ?, 'MAX', 1)",
                (uid, d),
            )

        # Текущий стрик: 8 дней (gap = 10-8 = 2 ≤ NUDGE_STREAK_GAP=3)
        for i in range(8):
            d = (today - datetime.timedelta(days=i)).isoformat()
            patched_db.execute(
                "INSERT OR IGNORE INTO workouts (user_id, date, mode, completed) VALUES (?, ?, 'MAX', 1)",
                (uid, d),
            )
        patched_db.commit()

        result = _check_streak_nudge(uid)
        assert result is not None
        assert "🔥" in result


# ─── _check_goal_nudge ───────────────────────────────────────────────────────

class TestCheckGoalNudge:

    def test_no_plan_returns_none(self, patched_db):
        uid = insert_user(patched_db, telegram_id=304001)
        assert _check_goal_nudge(uid) is None

    def test_halfway_done_triggers(self, patched_db):
        uid = insert_user(patched_db, telegram_id=304002)
        import json as _json
        # Создаём активный план на текущую неделю с 4 тренировками
        week_start = datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday())
        week_start_str = week_start.isoformat()

        from db.queries.training_plan import make_plan_id
        plan_id = make_plan_id(uid, week_start_str)
        patched_db.execute(
            """INSERT INTO training_plan
               (plan_id, user_id, week_start, status, plan_json, workouts_planned)
               VALUES (?, ?, ?, 'active', '[]', 4)""",
            (plan_id, uid, week_start_str),
        )
        # Добавляем 2 выполненные тренировки (50% — попадает в 40–65%)
        for i in range(2):
            d = (week_start + datetime.timedelta(days=i)).isoformat()
            patched_db.execute(
                "INSERT INTO workouts (user_id, date, mode, completed) VALUES (?, ?, 'MAX', 1)",
                (uid, d),
            )
        patched_db.commit()

        result = _check_goal_nudge(uid)
        assert result is not None
        assert "🎯" in result

    def test_too_early_returns_none(self, patched_db):
        """Если выполнено < 40% — нудж не срабатывает."""
        uid = insert_user(patched_db, telegram_id=304003)
        week_start = datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday())
        week_start_str = week_start.isoformat()

        from db.queries.training_plan import make_plan_id
        plan_id = make_plan_id(uid, week_start_str)
        patched_db.execute(
            """INSERT INTO training_plan
               (plan_id, user_id, week_start, status, plan_json, workouts_planned)
               VALUES (?, ?, ?, 'active', '[]', 5)""",
            (plan_id, uid, week_start_str),
        )
        # 1 из 5 = 20% — ниже порога 40%
        patched_db.execute(
            "INSERT INTO workouts (user_id, date, mode, completed) VALUES (?, ?, 'MAX', 1)",
            (uid, week_start_str),
        )
        patched_db.commit()
        assert _check_goal_nudge(uid) is None


# ─── Приоритет нуджей (только один за раз) ───────────────────────────────────

class TestNudgePriority:
    """
    Проверяем что check_and_send_nudges_for_user отправляет не более 1 нуджа.
    Мокируем bot.send_message.
    """

    @pytest.mark.asyncio
    async def test_only_one_nudge_sent(self, patched_db):
        uid = insert_user(patched_db, telegram_id=305001)
        today = datetime.date.today()

        # Создаём условия для drop nudge (5 дней без тренировки)
        old_date = (today - datetime.timedelta(days=5)).isoformat()
        patched_db.execute(
            "INSERT INTO workouts (user_id, date, mode, completed) VALUES (?, ?, 'MAX', 1)",
            (uid, old_date),
        )
        # Создаём условия для recovery nudge (плохой сон 3 дня)
        for i in range(3):
            d = (today - datetime.timedelta(days=i)).isoformat()
            patched_db.execute(
                "INSERT INTO metrics (user_id, date, sleep_hours) VALUES (?, ?, ?)",
                (uid, d, 4.0),
            )
        patched_db.commit()

        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock()

        await check_and_send_nudges_for_user(uid, 305001, mock_bot)

        # Должен быть ровно 1 вызов (приоритет: drop > recovery)
        assert mock_bot.send_message.call_count == 1
        # Первый нудж — drop (по приоритету)
        call_args = mock_bot.send_message.call_args
        assert "📉" in call_args.kwargs.get("text", "") or "📉" in str(call_args)

    @pytest.mark.asyncio
    async def test_no_nudge_when_no_conditions(self, patched_db):
        uid = insert_user(patched_db, telegram_id=305002)
        # Нет данных → нет нуджей
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock()

        await check_and_send_nudges_for_user(uid, 305002, mock_bot)

        assert mock_bot.send_message.call_count == 0

    @pytest.mark.asyncio
    async def test_no_nudge_if_on_cooldown(self, patched_db):
        uid = insert_user(patched_db, telegram_id=305003)
        # Условие drop выполнено
        old_date = (datetime.date.today() - datetime.timedelta(days=5)).isoformat()
        patched_db.execute(
            "INSERT INTO workouts (user_id, date, mode, completed) VALUES (?, ?, 'MAX', 1)",
            (uid, old_date),
        )
        # Но нудж уже был отправлен только что (кулдаун)
        _log_nudge(uid, "drop", "Already sent")
        patched_db.commit()

        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock()

        await check_and_send_nudges_for_user(uid, 305003, mock_bot)

        assert mock_bot.send_message.call_count == 0
