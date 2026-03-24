"""
tests/test_plan_bugs.py — Тесты для двух багов планирования тренировок.

Bug 1 — Контекст оборудования:
  PB-1  equipment сохраняется через update_athlete_card (tool_executor)
  PB-2  equipment читается через get_l3_deep
  PB-3  equipment читается через get_l3_brief
  PB-4  update_athlete_card без equipment не затирает существующее
  PB-5  equipment=[] означает «только вес тела»
  PB-6  training_location сохраняется через update_athlete_card

Bug 2 — Сохранение плана:
  PB-7  save_training_plan tool валидирует пустой JSON
  PB-8  save_training_plan tool валидирует невалидный JSON
  PB-9  save_training_plan tool сохраняет план в БД
  PB-10 save_training_plan tool возвращает success=True и plan_id
  PB-11 save_training_plan tool считает workouts_planned правильно
  PB-12 save_training_plan tool принимает явный week_start
  PB-13 tools/executor consistency — save_training_plan в обоих списках

Smoke:
  PB-14 TOOL_SAVE_TRAINING_PLAN присутствует в ALL_TOOLS
  PB-15 save_training_plan присутствует в _DISPATCH
"""
import json
import datetime
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from tests.conftest import insert_user


# ─── Фикстура: патч get_connection для memory + training_plan запросов ────────

_PATCH_TARGETS = [
    "db.connection.get_connection",
    "db.queries.user.get_connection",
    "db.queries.memory.get_connection",
    "db.queries.training_plan.get_connection",
    "ai.tool_executor.get_user",          # мок get_user в executor
]


@pytest.fixture
def plan_db(patched_db):
    """patched_db + патч для training_plan запросов."""
    with patch("db.queries.training_plan.get_connection", return_value=patched_db):
        yield patched_db


# ─── Bug 1: оборудование ─────────────────────────────────────────────────────

def test_equipment_saved_to_memory_training(patched_db):
    """equipment сохраняется в memory_training через upsert_training_intel."""
    uid = insert_user(patched_db, telegram_id=60001)
    from db.queries.memory import upsert_training_intel, get_l3_deep

    upsert_training_intel(uid, equipment=json.dumps(["турник", "гири 16кг"]))

    result = get_l3_deep(uid)
    assert result["equipment"] == ["турник", "гири 16кг"]


def test_equipment_read_by_l3_deep(patched_db):
    """get_l3_deep возвращает equipment из БД."""
    uid = insert_user(patched_db, telegram_id=60002)
    from db.queries.memory import upsert_training_intel, get_l3_deep

    upsert_training_intel(uid, equipment=json.dumps(["штанга", "скакалка"]))

    l3 = get_l3_deep(uid)
    assert "equipment" in l3
    assert "штанга" in l3["equipment"]


def test_equipment_read_by_l3_brief(patched_db):
    """get_l3_brief тоже возвращает equipment."""
    uid = insert_user(patched_db, telegram_id=60003)
    from db.queries.memory import upsert_training_intel, get_l3_brief

    upsert_training_intel(uid, equipment=json.dumps(["гантели 20кг"]))

    l3 = get_l3_brief(uid)
    assert "equipment" in l3
    assert "гантели 20кг" in l3["equipment"]


def test_equipment_default_empty_list(patched_db):
    """Если equipment не задан в БД, get_l3_deep возвращает пустой список."""
    uid = insert_user(patched_db, telegram_id=60004)
    from db.queries.memory import upsert_training_intel, get_l3_deep

    # Вставляем строку без equipment — должна применяться дефолтная '[]'
    upsert_training_intel(uid, preferred_time="morning")

    l3 = get_l3_deep(uid)
    assert l3.get("equipment") == [], (
        "equipment должен быть пустым списком (дефолт '[]'), а не None"
    )


def test_update_athlete_card_without_equipment_preserves_existing(patched_db):
    """update_athlete_card без поля equipment не затирает сохранённое оборудование."""
    uid = insert_user(patched_db, telegram_id=60005)
    from db.queries.memory import upsert_training_intel, get_l3_deep

    # Сохраняем оборудование напрямую
    upsert_training_intel(uid, equipment=json.dumps(["турник"]))

    # Обновляем preferred_days — equipment не должен меняться
    upsert_training_intel(uid, preferred_days=json.dumps(["пн", "ср", "пт"]))

    l3 = get_l3_deep(uid)
    assert "турник" in l3["equipment"], "equipment не должен пропасть после обновления preferred_days"


def test_training_location_in_user_profile(patched_db):
    """training_location сохраняется в user_profile через update_user."""
    uid = insert_user(patched_db, telegram_id=60006)
    from db.queries.user import update_user, get_user

    update_user(60006, training_location="home")

    user = get_user(60006)
    assert user["training_location"] == "home"


# ─── Bug 2: сохранение плана ──────────────────────────────────────────────────

def _make_plan_json(n_workouts: int = 3) -> str:
    """Создаёт минимальный валидный plan_json с n_workouts тренировочными днями."""
    today = datetime.date.today()
    days = []
    for i in range(7):
        d = today + datetime.timedelta(days=i)
        if i < n_workouts:
            days.append({
                "date": d.isoformat(),
                "weekday": ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][i],
                "type": "strength",
                "label": f"Тренировка {i+1}",
                "exercises": [{"name": "Отжимания", "sets": 3, "reps": 10, "rpe": 7}],
                "duration_min": 45,
                "completed": False,
                "ai_note": "",
            })
        else:
            days.append({
                "date": d.isoformat(),
                "weekday": ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][i],
                "type": "rest",
                "label": "Отдых",
                "exercises": [],
                "duration_min": 0,
                "completed": False,
                "ai_note": "",
            })
    return json.dumps(days, ensure_ascii=False)


@pytest.mark.asyncio
async def test_save_training_plan_tool_invalid_json(plan_db):
    """Возвращает error при невалидном JSON."""
    from ai.tool_executor import _tool_save_training_plan

    mock_user = {"id": 1, "active": 1}
    with patch("ai.tool_executor.get_user", return_value=mock_user):
        result = await _tool_save_training_plan(
            tg_id=70001,
            inp={"plan_json": "not-valid-json"},
        )
    assert result["success"] is False
    assert "Invalid" in result["error"]


@pytest.mark.asyncio
async def test_save_training_plan_tool_empty_array(plan_db):
    """Возвращает error при пустом массиве."""
    from ai.tool_executor import _tool_save_training_plan

    mock_user = {"id": 1, "active": 1}
    with patch("ai.tool_executor.get_user", return_value=mock_user):
        result = await _tool_save_training_plan(
            tg_id=70002,
            inp={"plan_json": "[]"},
        )
    assert result["success"] is False


@pytest.mark.asyncio
async def test_save_training_plan_tool_saves_to_db(plan_db):
    """Успешно сохраняет план в БД и возвращает success=True."""
    uid = insert_user(plan_db, telegram_id=70003)
    from ai.tool_executor import _tool_save_training_plan
    from db.queries.training_plan import get_active_plan

    mock_user = {"id": uid, "active": 1}
    plan_json = _make_plan_json(3)

    with patch("ai.tool_executor.get_user", return_value=mock_user):
        result = await _tool_save_training_plan(
            tg_id=70003,
            inp={"plan_json": plan_json, "rationale": "Тест план"},
        )

    assert result["success"] is True
    assert "plan_id" in result
    assert result["workouts_planned"] == 3

    # Проверяем что план действительно в БД
    saved = get_active_plan(uid)
    assert saved is not None
    assert saved["ai_rationale"] == "Тест план"


@pytest.mark.asyncio
async def test_save_training_plan_tool_returns_plan_id(plan_db):
    """Возвращает непустой plan_id."""
    uid = insert_user(plan_db, telegram_id=70004)
    from ai.tool_executor import _tool_save_training_plan

    mock_user = {"id": uid, "active": 1}

    with patch("ai.tool_executor.get_user", return_value=mock_user):
        result = await _tool_save_training_plan(
            tg_id=70004,
            inp={"plan_json": _make_plan_json(2)},
        )

    assert result["success"] is True
    assert result["plan_id"]
    assert result["week_start"]


@pytest.mark.asyncio
async def test_save_training_plan_counts_workouts_correctly(plan_db):
    """workouts_planned считает только НЕ-rest дни."""
    uid = insert_user(plan_db, telegram_id=70005)
    from ai.tool_executor import _tool_save_training_plan

    mock_user = {"id": uid, "active": 1}
    # 4 тренировки + 3 дня отдыха
    plan_json = _make_plan_json(4)

    with patch("ai.tool_executor.get_user", return_value=mock_user):
        result = await _tool_save_training_plan(
            tg_id=70005,
            inp={"plan_json": plan_json},
        )

    assert result["workouts_planned"] == 4


@pytest.mark.asyncio
async def test_save_training_plan_accepts_explicit_week_start(plan_db):
    """Принимает явный week_start и сохраняет с ним."""
    uid = insert_user(plan_db, telegram_id=70006)
    from ai.tool_executor import _tool_save_training_plan
    from db.queries.training_plan import get_active_plan

    mock_user = {"id": uid, "active": 1}
    week = "2026-04-07"  # конкретная неделя

    with patch("ai.tool_executor.get_user", return_value=mock_user):
        result = await _tool_save_training_plan(
            tg_id=70006,
            inp={"plan_json": _make_plan_json(3), "week_start": week},
        )

    assert result["success"] is True
    assert result["week_start"] == week


@pytest.mark.asyncio
async def test_save_training_plan_no_user(plan_db):
    """Возвращает error если пользователь не найден."""
    from ai.tool_executor import _tool_save_training_plan

    with patch("ai.tool_executor.get_user", return_value=None):
        result = await _tool_save_training_plan(
            tg_id=99999,
            inp={"plan_json": _make_plan_json(3)},
        )

    assert result["success"] is False
    assert "not found" in result["error"].lower()


@pytest.mark.asyncio
async def test_save_training_plan_preserves_workouts_completed(plan_db):
    """
    PB-17 — При переделке плана в середине недели workouts_completed НЕ обнуляется.

    Сценарий: пользователь выполнил 2 тренировки из 4 запланированных,
    затем попросил переделать план (убрать гантели). Старый прогресс
    (workouts_completed=2) должен сохраниться в БД.
    """
    uid = insert_user(plan_db, telegram_id=70007)
    from ai.tool_executor import _tool_save_training_plan
    from db.queries.training_plan import get_active_plan, make_plan_id, get_current_week_start
    from db.connection import get_connection

    mock_user = {"id": uid, "active": 1}
    plan_json = _make_plan_json(4)
    week = get_current_week_start()

    # 1. Создаём первоначальный план
    with patch("ai.tool_executor.get_user", return_value=mock_user):
        result = await _tool_save_training_plan(
            tg_id=70007,
            inp={"plan_json": plan_json, "rationale": "Исходный план"},
        )
    assert result["success"] is True

    # 2. Эмулируем 2 выполненные тренировки (прямая запись в БД)
    plan_id = make_plan_id(uid, week)
    conn = get_connection()
    conn.execute(
        "UPDATE training_plan SET workouts_completed = 2 WHERE plan_id = ?",
        (plan_id,),
    )
    conn.commit()

    # 3. Переделываем план (убрали гантели — новый JSON без них)
    new_plan_json = _make_plan_json(3)
    with patch("ai.tool_executor.get_user", return_value=mock_user):
        result2 = await _tool_save_training_plan(
            tg_id=70007,
            inp={"plan_json": new_plan_json, "rationale": "Без гантелей"},
        )
    assert result2["success"] is True

    # 4. Проверяем что workouts_completed НЕ сбросился
    updated = get_active_plan(uid)
    assert updated is not None
    assert updated["workouts_completed"] == 2, (
        f"workouts_completed должен быть 2, а не {updated['workouts_completed']} "
        "(план переделали, но прогресс должен сохраниться)"
    )
    # 5. Проверяем что новый JSON записался
    assert updated["ai_rationale"] == "Без гантелей"


# ─── Smoke: consistency ───────────────────────────────────────────────────────

def test_save_training_plan_in_all_tools():
    """TOOL_SAVE_TRAINING_PLAN присутствует в ALL_TOOLS."""
    from ai.tools import ALL_TOOLS
    names = {t["name"] for t in ALL_TOOLS}
    assert "save_training_plan" in names


def test_save_training_plan_in_dispatch():
    """save_training_plan присутствует в _DISPATCH executor-а."""
    from ai.tool_executor import _DISPATCH
    assert "save_training_plan" in _DISPATCH


def test_equipment_in_update_athlete_card_schema():
    """update_athlete_card содержит поле equipment в JSON-схеме."""
    from ai.tools import TOOL_UPDATE_ATHLETE_CARD
    props = TOOL_UPDATE_ATHLETE_CARD["input_schema"]["properties"]
    assert "equipment" in props
    assert props["equipment"]["type"] == "array"
