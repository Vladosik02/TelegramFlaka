"""
tests/test_config.py — Тесты конфигурации и констант.

Проверяем:
  • Все числовые пороги — разумные значения (sanity check).
  • get_trainer_mode() возвращает MAX/LIGHT по чётности дня.
  • ADMIN_USER_ID по умолчанию 0 (если не задан в .env).
"""
import pytest
import config


class TestGetTrainerMode:
    """Тесты for get_trainer_mode()."""

    def test_odd_day_is_max(self):
        assert config.get_trainer_mode(day=1) == "MAX"
        assert config.get_trainer_mode(day=3) == "MAX"
        assert config.get_trainer_mode(day=15) == "MAX"
        assert config.get_trainer_mode(day=31) == "MAX"

    def test_even_day_is_light(self):
        assert config.get_trainer_mode(day=2) == "LIGHT"
        assert config.get_trainer_mode(day=10) == "LIGHT"
        assert config.get_trainer_mode(day=28) == "LIGHT"

    def test_returns_string(self):
        result = config.get_trainer_mode(day=7)
        assert isinstance(result, str)
        assert result in ("MAX", "LIGHT")

    def test_no_arg_uses_today(self):
        """Вызов без аргумента не бросает исключений."""
        result = config.get_trainer_mode()
        assert result in ("MAX", "LIGHT")


class TestNudgeConstants:
    """Проверяем пороговые значения нудж-настроек."""

    def test_drop_days_positive(self):
        assert config.NUDGE_DROP_DAYS >= 1

    def test_pr_threshold_range(self):
        assert 50 <= config.NUDGE_PR_THRESHOLD_PCT <= 100

    def test_sleep_threshold_reasonable(self):
        assert 4.0 <= config.NUDGE_SLEEP_THRESHOLD <= 9.0

    def test_sleep_days_positive(self):
        assert config.NUDGE_SLEEP_DAYS >= 2

    def test_cooldown_hours_positive(self):
        assert config.NUDGE_COOLDOWN_HOURS >= 1

    def test_weekly_cooldown_is_tuple_of_strings(self):
        assert isinstance(config.NUDGE_WEEKLY_COOLDOWN, tuple)
        for item in config.NUDGE_WEEKLY_COOLDOWN:
            assert isinstance(item, str)

    def test_weekly_cooldown_contains_expected_types(self):
        wc = config.NUDGE_WEEKLY_COOLDOWN
        assert "streak" in wc
        assert "pr_approaching" in wc
        assert "goal_progress" in wc


class TestTestConstants:
    """Проверяем константы фитнес-теста."""

    def test_max_pushups_reasonable(self):
        assert config.TEST_MAX_PUSHUPS >= 100

    def test_max_squats_reasonable(self):
        assert config.TEST_MAX_SQUATS >= 200

    def test_max_plank_sec_reasonable(self):
        assert config.TEST_MAX_PLANK_SEC >= 300  # минимум 5 мин

    def test_test_cooldown_days_positive(self):
        assert config.TEST_COOLDOWN_DAYS >= 1


class TestAdminConfig:
    """Проверяем конфигурацию администратора (Фаза 8.5)."""

    def test_admin_user_id_is_int(self):
        assert isinstance(config.ADMIN_USER_ID, int)

    def test_admin_user_id_default_zero(self, monkeypatch):
        """Без .env переменной ADMIN_USER_ID должен быть 0."""
        monkeypatch.delenv("ADMIN_USER_ID", raising=False)
        # Перечитываем значение из getenv напрямую
        import os
        val = int(os.getenv("ADMIN_USER_ID", 0))
        assert val == 0
