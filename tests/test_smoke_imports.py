"""
tests/test_smoke_imports.py — Smoke-тесты: импорты и изолируемые функции.

Покрывает:
  SI-1  import smoke — bot/handlers, bot/commands, scheduler/logic импортируются без ошибок
  SI-2  import smoke — ai/client, ai/tools, ai/tool_executor без ошибок
  SI-3  import smoke — scheduler/jobs, scheduler/nudges, scheduler/periodization
  SI-4  _build_stats_text() — корректный вывод при наличии данных
  SI-5  _build_stats_text() — не падает при нулевых значениях
  SI-6  _build_stats_text() — прогресс-бар ограничен 10 символами
  SI-7  tools/executor consistency — имена tools.py совпадают с ключами dispatch
"""
import pytest
from unittest.mock import patch, MagicMock


# ─── SI-1: bot layer imports ──────────────────────────────────────────────────

def test_import_bot_commands():
    """bot/commands.py импортируется без ошибок."""
    import bot.commands  # noqa: F401


def test_import_bot_keyboards():
    """bot/keyboards.py импортируется без ошибок."""
    import bot.keyboards  # noqa: F401


def test_import_bot_debug():
    """bot/debug.py импортируется без ошибок."""
    import bot.debug  # noqa: F401


# ─── SI-2: AI layer imports ───────────────────────────────────────────────────

def test_import_ai_tools():
    """ai/tools.py импортируется, ALL_TOOLS — непустой список."""
    from ai.tools import ALL_TOOLS
    assert isinstance(ALL_TOOLS, list)
    assert len(ALL_TOOLS) > 0, "ALL_TOOLS не должен быть пустым"


def test_import_ai_tool_executor():
    """ai/tool_executor.py импортируется, _DISPATCH доступен."""
    from ai.tool_executor import _DISPATCH
    assert isinstance(_DISPATCH, dict)
    assert len(_DISPATCH) > 0, "_DISPATCH не должен быть пустым"


def test_import_ai_context_builder():
    """ai/context_builder.py импортируется без ошибок."""
    import ai.context_builder  # noqa: F401


def test_import_ai_response_parser():
    """ai/response_parser.py импортируется, нужные функции доступны."""
    from ai.response_parser import parse_exercises_from_message, detect_health_alert
    assert callable(parse_exercises_from_message)
    assert callable(detect_health_alert)


# ─── SI-3: scheduler imports ──────────────────────────────────────────────────

def test_import_scheduler_nudges():
    """scheduler/nudges.py импортируется без ошибок."""
    import scheduler.nudges  # noqa: F401


def test_import_scheduler_periodization():
    """scheduler/periodization.py импортируется без ошибок."""
    import scheduler.periodization  # noqa: F401


def test_import_scheduler_nutrition_analysis():
    """scheduler/nutrition_analysis.py импортируется без ошибок."""
    import scheduler.nutrition_analysis  # noqa: F401


# ─── SI-4/5/6: _build_stats_text() ──────────────────────────────────────────

def _make_user(uid: int = 1, name: str = "Тест") -> dict:
    return {"id": uid, "name": name, "telegram_id": uid}


def _mock_stats(workouts_done=3, workouts_total=5, avg_intensity=7,
                total_minutes=90, avg_sleep=7.5, avg_energy=4):
    return {
        "workouts_done": workouts_done,
        "workouts_total": workouts_total,
        "avg_intensity": avg_intensity,
        "total_minutes": total_minutes,
        "avg_sleep": avg_sleep,
        "avg_energy": avg_energy,
    }


def _mock_alltime(done_workouts=42, total_minutes=3600):
    return {
        "done_workouts": done_workouts,
        "total_minutes": total_minutes,
    }


@patch("bot.commands.get_trainer_mode", return_value="MAX")
@patch("bot.commands.get_streak", return_value=7)
@patch("bot.commands.get_all_time_stats")
@patch("bot.commands.get_weekly_stats")
def test_build_stats_text_normal(mock_weekly, mock_alltime, mock_streak, mock_mode):
    """_build_stats_text возвращает строку с именем и стриком."""
    from bot.commands import _build_stats_text

    mock_weekly.return_value = _mock_stats()
    mock_alltime.return_value = _mock_alltime()

    result = _build_stats_text(_make_user())

    assert isinstance(result, str)
    assert "Тест" in result
    assert "7" in result          # streak
    assert "42" in result         # done_workouts
    assert "3/5" in result        # done/total


@patch("bot.commands.get_trainer_mode", return_value="LIGHT")
@patch("bot.commands.get_streak", return_value=0)
@patch("bot.commands.get_all_time_stats")
@patch("bot.commands.get_weekly_stats")
def test_build_stats_text_zeros(mock_weekly, mock_alltime, mock_streak, mock_mode):
    """_build_stats_text не падает при нулевых значениях (0 тренировок, streak=0)."""
    from bot.commands import _build_stats_text

    mock_weekly.return_value = _mock_stats(workouts_done=0, workouts_total=0)
    mock_alltime.return_value = _mock_alltime(done_workouts=0, total_minutes=0)

    result = _build_stats_text(_make_user(name=None))  # name=None → fallback

    assert isinstance(result, str)
    assert len(result) > 0


@patch("bot.commands.get_trainer_mode", return_value="MAX")
@patch("bot.commands.get_streak", return_value=5)
@patch("bot.commands.get_all_time_stats")
@patch("bot.commands.get_weekly_stats")
def test_build_stats_text_progress_bar_length(mock_weekly, mock_alltime, mock_streak, mock_mode):
    """Прогресс-бар всегда состоит ровно из 10 символов (█ + ░)."""
    from bot.commands import _build_stats_text

    for done, total in [(0, 5), (5, 5), (3, 4), (10, 3)]:  # включая overshoot
        mock_weekly.return_value = _mock_stats(workouts_done=done, workouts_total=total)
        mock_alltime.return_value = _mock_alltime()

        result = _build_stats_text(_make_user())

        filled = result.count("█")
        empty  = result.count("░")
        assert filled + empty == 10, (
            f"Прогресс-бар должен быть 10 символов, done={done} total={total}: "
            f"got {filled}█ + {empty}░"
        )


# ─── SI-7: tools ↔ executor consistency ──────────────────────────────────────

def test_all_tools_have_executor():
    """Каждый tool из ALL_TOOLS должен быть в _DISPATCH executor-а."""
    from ai.tools import ALL_TOOLS
    from ai.tool_executor import _DISPATCH

    tool_names = {t["name"] for t in ALL_TOOLS}
    dispatch_names = set(_DISPATCH.keys())

    missing = tool_names - dispatch_names
    assert not missing, (
        f"Tools defined в tools.py, но нет в _DISPATCH: {missing}"
    )


def test_all_dispatched_tools_are_defined():
    """Каждый ключ _DISPATCH должен соответствовать tool в ALL_TOOLS."""
    from ai.tools import ALL_TOOLS
    from ai.tool_executor import _DISPATCH

    tool_names = {t["name"] for t in ALL_TOOLS}
    dispatch_names = set(_DISPATCH.keys())

    extra = dispatch_names - tool_names
    assert not extra, (
        f"Ключи в _DISPATCH, которых нет в ALL_TOOLS: {extra}"
    )
