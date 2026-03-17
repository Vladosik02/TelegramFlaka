"""
tests/test_phase16.py — Smoke tests для критических путей Фазы 16.

Покрывает:
  16.1a  log_metrics upsert — нет дублей при повторном вызове
  16.1b  log_metrics upsert — обновляет поле, не затирает остальные
  16.1c  mark_plan_day_completed — патчит plan_json, инкрементирует счётчик
  16.1d  get_streak — корректный подсчёт streak
  16.1e  tool_executor dispatch — неизвестный tool возвращает error
  16.1f  mark_plan_day_completed — пропускает rest-день (не помечает)
"""
import asyncio
import json
import datetime
import pytest
from unittest.mock import patch


# ─── 16.1a/b: log_metrics upsert ──────────────────────────────────────────────

def test_log_metrics_no_duplicate(patched_db):
    """Повторный вызов log_metrics за один день не создаёт вторую строку."""
    from db.queries.workouts import log_metrics

    uid = 500
    patched_db.execute(
        "INSERT OR IGNORE INTO user_profile (id, telegram_id, name, active) VALUES (?,?,?,?)",
        (uid, uid, "Test", 1),
    )
    patched_db.commit()

    today = datetime.date.today().isoformat()

    log_metrics(uid, today, weight_kg=80.0, sleep_hours=8.0)
    log_metrics(uid, today, weight_kg=80.5)          # повторный вызов

    rows = patched_db.execute(
        "SELECT COUNT(*) as cnt FROM metrics WHERE user_id = ? AND date = ?",
        (uid, today),
    ).fetchone()

    assert rows["cnt"] == 1, "upsert должен обновить запись, а не создать дубль"


def test_log_metrics_upsert_preserves_existing(patched_db):
    """Upsert обновляет только переданные поля, не затирая уже сохранённые."""
    from db.queries.workouts import log_metrics

    uid = 501
    patched_db.execute(
        "INSERT OR IGNORE INTO user_profile (id, telegram_id, name, active) VALUES (?,?,?,?)",
        (uid, uid, "Test2", 1),
    )
    patched_db.commit()

    today = datetime.date.today().isoformat()

    log_metrics(uid, today, weight_kg=75.0, sleep_hours=7.5)
    log_metrics(uid, today, weight_kg=75.5)          # обновляем только вес

    row = patched_db.execute(
        "SELECT weight_kg, sleep_hours FROM metrics WHERE user_id = ? AND date = ?",
        (uid, today),
    ).fetchone()

    assert float(row["weight_kg"]) == 75.5,    "вес должен обновиться"
    assert float(row["sleep_hours"]) == 7.5,   "сон не должен обнулиться"


# ─── 16.1c/f: mark_plan_day_completed ─────────────────────────────────────────

def _make_plan(patched_db, uid: int, today_str: str, dtype: str = "strength") -> str:
    """Вспомогательная: создаёт активный план с одним днём."""
    plan_id = f"PLN-{uid}-TEST"
    days = [
        {"date": today_str, "type": dtype, "label": "Тест", "exercises": [], "completed": False},
    ]
    patched_db.execute(
        """INSERT OR REPLACE INTO training_plan
           (plan_id, user_id, week_start, status, plan_json, workouts_planned, workouts_completed)
           VALUES (?,?,?,?,?,?,?)""",
        (plan_id, uid, today_str, "active", json.dumps(days, ensure_ascii=False), 1, 0),
    )
    patched_db.commit()
    return plan_id


def test_mark_plan_day_completed_sets_flag(patched_db):
    """mark_plan_day_completed патчит completed=True и инкрементирует workouts_completed."""
    from db.queries.training_plan import mark_plan_day_completed, get_active_plan

    uid = 502
    patched_db.execute(
        "INSERT OR IGNORE INTO user_profile (id, telegram_id, name, active) VALUES (?,?,?,?)",
        (uid, uid, "Test3", 1),
    )
    patched_db.commit()
    today = datetime.date.today().isoformat()
    _make_plan(patched_db, uid, today, dtype="strength")

    result = mark_plan_day_completed(uid, today)

    assert result is True, "должен вернуть True если день найден и обновлён"

    plan = get_active_plan(uid)
    days = json.loads(plan["plan_json"])
    assert days[0]["completed"] is True, "день должен быть помечен completed=True"
    assert plan["workouts_completed"] == 1, "счётчик должен увеличиться"


def test_mark_plan_day_completed_skips_rest(patched_db):
    """mark_plan_day_completed не трогает rest-дни."""
    from db.queries.training_plan import mark_plan_day_completed, get_active_plan

    uid = 503
    patched_db.execute(
        "INSERT OR IGNORE INTO user_profile (id, telegram_id, name, active) VALUES (?,?,?,?)",
        (uid, uid, "Test4", 1),
    )
    patched_db.commit()
    today = datetime.date.today().isoformat()
    _make_plan(patched_db, uid, today, dtype="rest")

    result = mark_plan_day_completed(uid, today)

    assert result is False, "rest-день не должен помечаться completed"

    plan = get_active_plan(uid)
    days = json.loads(plan["plan_json"])
    assert days[0].get("completed") is not True


def test_mark_plan_day_completed_no_double_count(patched_db):
    """Повторный вызов mark_plan_day_completed не инкрементирует счётчик дважды."""
    from db.queries.training_plan import mark_plan_day_completed, get_active_plan

    uid = 504
    patched_db.execute(
        "INSERT OR IGNORE INTO user_profile (id, telegram_id, name, active) VALUES (?,?,?,?)",
        (uid, uid, "Test5", 1),
    )
    patched_db.commit()
    today = datetime.date.today().isoformat()
    _make_plan(patched_db, uid, today, dtype="strength")

    mark_plan_day_completed(uid, today)
    result2 = mark_plan_day_completed(uid, today)   # повторный вызов

    assert result2 is False, "повторный вызов должен вернуть False (уже completed)"

    plan = get_active_plan(uid)
    assert plan["workouts_completed"] == 1, "счётчик не должен вырасти выше 1"


# ─── 16.1d: get_streak ────────────────────────────────────────────────────────

def test_get_streak_consecutive(patched_db):
    """get_streak правильно считает подряд идущие дни."""
    from db.queries.workouts import get_streak

    uid = 505
    patched_db.execute(
        "INSERT OR IGNORE INTO user_profile (id, telegram_id, name, active) VALUES (?,?,?,?)",
        (uid, uid, "Streak", 1),
    )
    patched_db.commit()

    today = datetime.date.today()
    for delta in range(3):               # сегодня + 2 дня назад
        d = (today - datetime.timedelta(days=delta)).isoformat()
        patched_db.execute(
            "INSERT INTO workouts (user_id, date, mode, completed) VALUES (?,?,?,?)",
            (uid, d, "MAX", 1),
        )
    patched_db.commit()

    streak = get_streak(uid)
    assert streak == 3


def test_get_streak_broken(patched_db):
    """get_streak останавливается на разрыве."""
    from db.queries.workouts import get_streak

    uid = 506
    patched_db.execute(
        "INSERT OR IGNORE INTO user_profile (id, telegram_id, name, active) VALUES (?,?,?,?)",
        (uid, uid, "Gap", 1),
    )
    patched_db.commit()

    today = datetime.date.today()
    # Сегодня + 2 дня назад, пропуская вчера
    for delta in (0, 2):
        d = (today - datetime.timedelta(days=delta)).isoformat()
        patched_db.execute(
            "INSERT INTO workouts (user_id, date, mode, completed) VALUES (?,?,?,?)",
            (uid, d, "MAX", 1),
        )
    patched_db.commit()

    streak = get_streak(uid)
    assert streak == 1, "стрик должен прерваться на пропущенном вчера"


# ─── 16.1e: tool_executor dispatch ────────────────────────────────────────────

def test_tool_executor_unknown_tool():
    """execute_tool с неизвестным именем возвращает словарь с ключом 'error'."""
    from ai.tool_executor import execute_tool

    result = asyncio.run(execute_tool(tg_id=1, tool_name="nonexistent_tool_xyz", tool_input={}))

    assert isinstance(result, dict), "ожидается словарь"
    assert "error" in result, "должен содержать ключ 'error'"
    assert result.get("success") is not True


def test_tool_executor_save_workout_missing_fields(patched_db):
    """save_workout без обязательных полей возвращает error (валидация входных данных)."""
    from ai.tool_executor import execute_tool

    result = asyncio.run(execute_tool(tg_id=1, tool_name="save_workout", tool_input={}))

    assert isinstance(result, dict)
    assert "error" in result or result.get("success") is False
