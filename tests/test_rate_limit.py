"""tests/test_rate_limit.py — C4 per-user rate-limit на handle_message.

Проверяет:
  • первые 10 сообщений → "ok";
  • 11-е → "warn";
  • 12-15-е → "drop" (silent);
  • после освобождения окна → снова "ok" + reset warn-state.
"""
import time
import pytest

from bot.handlers import (
    _check_rate_limit,
    _RATE_LIMIT_WINDOW,
    _RATE_LIMIT_WARNED,
    _RATE_LIMIT_MAX,
    _RATE_LIMIT_WINDOW_SEC,
)


@pytest.fixture(autouse=True)
def _clean_state():
    _RATE_LIMIT_WINDOW.clear()
    _RATE_LIMIT_WARNED.clear()
    yield
    _RATE_LIMIT_WINDOW.clear()
    _RATE_LIMIT_WARNED.clear()


def test_first_n_messages_ok():
    user_id = 555
    for _ in range(_RATE_LIMIT_MAX):
        assert _check_rate_limit(user_id) == "ok"


def test_overflow_emits_warn_then_drop():
    user_id = 556
    for _ in range(_RATE_LIMIT_MAX):
        assert _check_rate_limit(user_id) == "ok"
    assert _check_rate_limit(user_id) == "warn"
    for _ in range(5):
        assert _check_rate_limit(user_id) == "drop"


def test_warn_fires_only_once_per_window():
    user_id = 557
    for _ in range(_RATE_LIMIT_MAX):
        _check_rate_limit(user_id)
    statuses = [_check_rate_limit(user_id) for _ in range(10)]
    assert statuses.count("warn") == 1
    assert statuses.count("drop") == 9


def test_window_release_resets_state(monkeypatch):
    user_id = 558
    base = time.monotonic()
    fake_now = {"t": base}

    def _fake_monotonic():
        return fake_now["t"]

    monkeypatch.setattr("bot.handlers.time.monotonic", _fake_monotonic)
    for _ in range(_RATE_LIMIT_MAX):
        assert _check_rate_limit(user_id) == "ok"
    assert _check_rate_limit(user_id) == "warn"
    assert _check_rate_limit(user_id) == "drop"

    fake_now["t"] = base + _RATE_LIMIT_WINDOW_SEC + 1
    assert _check_rate_limit(user_id) == "ok"
    assert user_id not in _RATE_LIMIT_WARNED


def test_per_user_isolation():
    a, b = 559, 560
    for _ in range(_RATE_LIMIT_MAX + 1):
        _check_rate_limit(a)
    assert _check_rate_limit(b) == "ok"
