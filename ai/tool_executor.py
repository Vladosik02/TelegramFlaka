"""
ai/tool_executor.py — Исполнитель инструментов Claude Tool Use.

Фаза 10.1 — Intelligent Agent.

Принимает tool_use блоки из ответа Claude и маршрутизирует их
к соответствующим функциям БД. Возвращает tool_result блоки
для следующего витка агентного цикла.

Архитектура:
  execute_tool(tg_id, tool_name, tool_input) -> dict (tool_result content)
  execute_tool_calls(tg_id, tool_uses)       -> list[dict] (все результаты)
"""

import json
import logging
import datetime
from typing import Any

from db.queries.user import get_user, update_user
from db.queries.workouts import log_workout, log_metrics
from db.queries.exercises import log_exercise_result, get_record_for_exercise
from db.queries.memory import upsert_athlete_card, upsert_training_intel
from db.queries.nutrition import log_nutrition_day
from db.writer import save_workout_from_parsed
from config import get_trainer_mode

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# ГЛАВНАЯ ТОЧКА ВХОДА
# ═══════════════════════════════════════════════════════════════════════════

async def execute_tool_calls(
    tg_id: int,
    tool_uses: list,
    bot=None,
    chat_id: int = None,
) -> list[dict]:
    """
    Принимает список ToolUseBlock из ответа Claude.
    Возвращает список tool_result-словарей для следующего сообщения.

    Каждый результат: {"type": "tool_result", "tool_use_id": ..., "content": ...}
    """
    results = []
    for tool_use in tool_uses:
        tool_name = tool_use.name
        tool_input = tool_use.input
        tool_use_id = tool_use.id

        logger.info(f"[TOOL] Executing '{tool_name}' for user={tg_id}: {tool_input}")

        try:
            result_content = await execute_tool(
                tg_id=tg_id,
                tool_name=tool_name,
                tool_input=tool_input,
                bot=bot,
                chat_id=chat_id,
            )
        except Exception as e:
            logger.error(f"[TOOL] Error in '{tool_name}' for {tg_id}: {e}")
            result_content = {"error": str(e), "success": False}

        results.append({
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": json.dumps(result_content, ensure_ascii=False),
        })

    return results


async def execute_tool(
    tg_id: int,
    tool_name: str,
    tool_input: dict,
    bot=None,
    chat_id: int = None,
) -> dict:
    """
    Маршрутизатор: имя инструмента → функция БД.
    Возвращает словарь с результатом (будет сериализован в JSON).
    """
    dispatch = {
        "save_workout":         _tool_save_workout,
        "save_metrics":         _tool_save_metrics,
        "save_nutrition":       _tool_save_nutrition,
        "save_exercise_result": _tool_save_exercise_result,
        "set_personal_record":  _tool_set_personal_record,
        "update_athlete_card":  _tool_update_athlete_card,
        "get_weekly_stats":     _tool_get_weekly_stats,
        "save_episode":         _tool_save_episode,
        "award_xp":             _tool_award_xp,
    }

    handler = dispatch.get(tool_name)
    if not handler:
        logger.warning(f"[TOOL] Unknown tool: '{tool_name}'")
        return {"error": f"Unknown tool: {tool_name}", "success": False}

    return await handler(tg_id, tool_input, bot=bot, chat_id=chat_id)


# ═══════════════════════════════════════════════════════════════════════════
# ОБРАБОТЧИКИ ИНСТРУМЕНТОВ
# ═══════════════════════════════════════════════════════════════════════════

async def _tool_save_workout(tg_id: int, inp: dict, **kwargs) -> dict:
    """Сохранить тренировку."""
    user = get_user(tg_id)
    if not user:
        return {"error": "User not found", "success": False}

    today = datetime.date.today().isoformat()
    mode = get_trainer_mode()

    exercises = inp.get("exercises", [])
    workout_id = log_workout(
        user_id=user["id"],
        date=today,
        mode=mode,
        workout_type=inp.get("workout_type"),
        duration_min=inp.get("duration_min"),
        intensity=inp.get("intensity"),
        exercises=json.dumps(exercises, ensure_ascii=False) if exercises else None,
        notes=inp.get("notes"),
        completed=True,
    )

    # Начисляем XP за тренировку автоматически
    xp_awarded = 0
    try:
        from db.queries.gamification import add_xp, check_and_unlock_achievements
        xp_awarded = add_xp(user["id"], 100, "workout", inp.get("workout_type"))
        await check_and_unlock_achievements(
            user["id"], tg_id, "workout",
            bot=kwargs.get("bot"), chat_id=kwargs.get("chat_id")
        )
    except Exception as e:
        logger.warning(f"[XP] award error: {e}")

    logger.info(f"[TOOL] save_workout: user={tg_id}, id={workout_id}, +{xp_awarded}XP")
    return {
        "success": True,
        "workout_id": workout_id,
        "xp_awarded": xp_awarded,
        "message": f"Тренировка сохранена ✅ +{xp_awarded} XP",
    }


async def _tool_save_metrics(tg_id: int, inp: dict, **kwargs) -> dict:
    """Сохранить метрики здоровья."""
    user = get_user(tg_id)
    if not user:
        return {"error": "User not found", "success": False}

    today = datetime.date.today().isoformat()
    log_metrics(
        user_id=user["id"],
        date=today,
        weight_kg=inp.get("weight_kg"),
        sleep_hours=inp.get("sleep_hours"),
        energy=inp.get("energy"),
        mood=inp.get("mood"),
        water_liters=inp.get("water_liters"),
        steps=inp.get("steps"),
        notes=inp.get("notes"),
    )

    # Если сохранили вес — записываем эпизод в память
    if inp.get("weight_kg"):
        try:
            from db.queries.episodic import save_episode
            uid = user["id"]
            save_episode(
                user_id=uid,
                episode_type="insight",
                summary=f"Вес зафиксирован: {inp['weight_kg']} кг",
                tags=["metrics", "weight"],
                importance=4,
                ttl_days=60,
            )
        except Exception:
            pass

    saved_fields = [k for k, v in inp.items() if v is not None and k != "notes"]
    logger.info(f"[TOOL] save_metrics: user={tg_id}, fields={saved_fields}")
    return {
        "success": True,
        "saved_fields": saved_fields,
        "message": "Метрики записаны ✅",
    }


async def _tool_save_nutrition(tg_id: int, inp: dict, **kwargs) -> dict:
    """Сохранить данные о питании."""
    user = get_user(tg_id)
    if not user:
        return {"error": "User not found", "success": False}

    fields = {k: v for k, v in inp.items() if v is not None}
    # Конвертируем junk_food bool → int
    if "junk_food" in fields:
        fields["junk_food"] = 1 if fields["junk_food"] else 0

    if fields:
        log_nutrition_day(user["id"], **fields)

    logger.info(f"[TOOL] save_nutrition: user={tg_id}, cal={inp.get('calories')}")
    return {
        "success": True,
        "saved_fields": list(fields.keys()),
        "message": "Питание записано ✅",
    }


async def _tool_save_exercise_result(tg_id: int, inp: dict, **kwargs) -> dict:
    """Сохранить результат упражнения."""
    user = get_user(tg_id)
    if not user:
        return {"error": "User not found", "success": False}

    today = datetime.date.today().isoformat()
    result_id = log_exercise_result(
        user_id=user["id"],
        exercise_name=inp["exercise_name"],
        date=today,
        sets=inp.get("sets"),
        reps=inp.get("reps"),
        duration_sec=inp.get("duration_sec"),
        weight_kg=inp.get("weight_kg"),
        notes=inp.get("notes"),
    )

    logger.info(
        f"[TOOL] save_exercise_result: user={tg_id}, "
        f"exercise={inp['exercise_name']}, id={result_id}"
    )
    return {
        "success": True,
        "result_id": result_id,
        "message": f"Результат {inp['exercise_name']} сохранён ✅",
    }


async def _tool_set_personal_record(tg_id: int, inp: dict, **kwargs) -> dict:
    """Установить личный рекорд явно (по команде Claude)."""
    from db.connection import get_connection

    user = get_user(tg_id)
    if not user:
        return {"error": "User not found", "success": False}

    uid = user["id"]
    today = datetime.date.today().isoformat()
    exercise = inp["exercise_name"]
    new_value = float(inp["record_value"])
    record_type = inp["record_type"]

    conn = get_connection()

    # Проверяем предыдущий рекорд
    existing = conn.execute("""
        SELECT record_value FROM personal_records
        WHERE user_id = ? AND exercise_name = ? AND record_type = ?
        ORDER BY record_value DESC LIMIT 1
    """, (uid, exercise, record_type)).fetchone()

    prev = float(existing["record_value"]) if existing else None
    improvement = None
    if prev and prev > 0:
        improvement = round((new_value - prev) / prev * 100, 1)

    conn.execute("""
        INSERT INTO personal_records
            (user_id, exercise_name, record_value, record_type,
             set_at, previous_record, improvement_pct, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (uid, exercise, new_value, record_type,
          today, prev, improvement, inp.get("notes")))
    conn.commit()

    # Начисляем XP за PR
    xp_awarded = 0
    try:
        from db.queries.gamification import add_xp, check_and_unlock_achievements
        xp_awarded = add_xp(uid, 200, "personal_record", exercise)
        await check_and_unlock_achievements(
            uid, tg_id, "personal_record",
            bot=kwargs.get("bot"), chat_id=kwargs.get("chat_id")
        )
    except Exception as e:
        logger.warning(f"[XP] PR award error: {e}")

    # Сохраняем в эпизодическую память
    try:
        from db.queries.episodic import save_episode
        improvement_str = f" (+{improvement}%)" if improvement else ""
        suffix = {"weight": "кг", "time": "сек", "reps": "пов"}.get(record_type, "")
        save_episode(
            user_id=uid,
            episode_type="personal_record",
            summary=f"Новый PR: {exercise} = {new_value}{suffix}{improvement_str}",
            tags=["pr", "achievement", exercise.lower()],
            importance=8,
            ttl_days=90,
        )
    except Exception:
        pass

    logger.info(f"[TOOL] set_personal_record: {exercise}={new_value}{record_type} +{xp_awarded}XP")
    return {
        "success": True,
        "exercise": exercise,
        "new_value": new_value,
        "previous": prev,
        "improvement_pct": improvement,
        "xp_awarded": xp_awarded,
        "message": f"🏆 Новый рекорд {exercise}! +{xp_awarded} XP",
    }


async def _tool_update_athlete_card(tg_id: int, inp: dict, **kwargs) -> dict:
    """Обновить карточку атлета."""
    user = get_user(tg_id)
    if not user:
        return {"error": "User not found", "success": False}

    uid = user["id"]
    updated = []

    # user_profile поля
    profile_fields = {}
    if "goal" in inp:
        profile_fields["goal"] = inp["goal"]
        updated.append("goal")
    if "fitness_level" in inp:
        profile_fields["fitness_level"] = inp["fitness_level"]
        updated.append("fitness_level")
    if "training_location" in inp:
        profile_fields["training_location"] = inp["training_location"]
        updated.append("training_location")
    if "injuries" in inp:
        import json as _json
        profile_fields["injuries"] = _json.dumps(inp["injuries"], ensure_ascii=False)
        updated.append("injuries")

    if profile_fields:
        update_user(tg_id, **profile_fields)

    # memory_training поля
    training_fields = {}
    if "preferred_days" in inp:
        import json as _json
        training_fields["preferred_days"] = _json.dumps(
            inp["preferred_days"], ensure_ascii=False
        )
        updated.append("preferred_days")

    if training_fields:
        upsert_training_intel(uid, **training_fields)

    # memory_athlete
    athlete_fields = {}
    if "season" in inp:
        athlete_fields["season"] = inp["season"]
        updated.append("season")

    if athlete_fields:
        upsert_athlete_card(uid, **athlete_fields)

    logger.info(f"[TOOL] update_athlete_card: user={tg_id}, updated={updated}")
    return {
        "success": True,
        "updated_fields": updated,
        "message": "Профиль обновлён ✅",
    }


async def _tool_get_weekly_stats(tg_id: int, inp: dict, **kwargs) -> dict:
    """Получить статистику за N дней."""
    from db.connection import get_connection

    user = get_user(tg_id)
    if not user:
        return {"error": "User not found", "success": False}

    uid = user["id"]
    days = inp.get("days", 7)
    include_nutrition = inp.get("include_nutrition", False)

    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    conn = get_connection()

    # Тренировки
    workouts = conn.execute("""
        SELECT COUNT(*) as total,
               SUM(completed) as done,
               AVG(intensity) as avg_intensity,
               SUM(duration_min) as total_min
        FROM workouts
        WHERE user_id = ? AND date >= ?
    """, (uid, since)).fetchone()

    # Метрики
    metrics = conn.execute("""
        SELECT AVG(weight_kg) as avg_weight,
               AVG(sleep_hours) as avg_sleep,
               AVG(energy) as avg_energy,
               AVG(steps) as avg_steps
        FROM metrics
        WHERE user_id = ? AND date >= ?
    """, (uid, since)).fetchone()

    result = {
        "period_days": days,
        "workouts_total": workouts["total"] or 0,
        "workouts_done": int(workouts["done"] or 0),
        "avg_intensity": round(workouts["avg_intensity"], 1) if workouts["avg_intensity"] else None,
        "total_minutes": workouts["total_min"] or 0,
        "avg_weight_kg": round(metrics["avg_weight"], 1) if metrics["avg_weight"] else None,
        "avg_sleep_h": round(metrics["avg_sleep"], 1) if metrics["avg_sleep"] else None,
        "avg_energy": round(metrics["avg_energy"], 1) if metrics["avg_energy"] else None,
        "avg_steps": int(metrics["avg_steps"]) if metrics["avg_steps"] else None,
    }

    if include_nutrition:
        nut = conn.execute("""
            SELECT AVG(calories) as avg_cal,
                   AVG(protein_g) as avg_prot
            FROM nutrition_log
            WHERE user_id = ? AND date >= ?
        """, (uid, since)).fetchone()
        result["avg_calories"] = int(nut["avg_cal"]) if nut["avg_cal"] else None
        result["avg_protein_g"] = round(nut["avg_prot"], 1) if nut["avg_prot"] else None

    logger.info(f"[TOOL] get_weekly_stats: user={tg_id}, days={days}")
    return result


async def _tool_save_episode(tg_id: int, inp: dict, **kwargs) -> dict:
    """Сохранить эпизод в эпизодическую память."""
    from db.queries.episodic import save_episode

    user = get_user(tg_id)
    if not user:
        return {"error": "User not found", "success": False}

    ttl_map = {
        "personal_record": 90,
        "insight": 60,
        "goal_update": 365,
        "conversation": 30,
        "milestone": 180,
    }
    episode_type = inp["episode_type"]
    ttl = ttl_map.get(episode_type, 60)

    ep_id = save_episode(
        user_id=user["id"],
        episode_type=episode_type,
        summary=inp["summary"],
        tags=inp.get("tags", []),
        importance=inp.get("importance", 5),
        ttl_days=ttl,
    )

    logger.info(f"[TOOL] save_episode: user={tg_id}, type={episode_type}, id={ep_id}")
    return {
        "success": True,
        "episode_id": ep_id,
        "message": "Эпизод сохранён в память ✅",
    }


async def _tool_award_xp(tg_id: int, inp: dict, **kwargs) -> dict:
    """Начислить XP."""
    from db.queries.gamification import add_xp, get_user_level_info, check_and_unlock_achievements

    user = get_user(tg_id)
    if not user:
        return {"error": "User not found", "success": False}

    uid = user["id"]
    xp_before = get_user_level_info(uid)
    new_total = add_xp(uid, inp["xp_amount"], inp["reason"], inp.get("detail"))

    await check_and_unlock_achievements(
        uid, tg_id, inp["reason"],
        bot=kwargs.get("bot"), chat_id=kwargs.get("chat_id")
    )

    level_info = get_user_level_info(uid)

    # Уведомление об уровне — если изменился
    leveled_up = False
    if xp_before and level_info:
        if level_info.get("current_level", 1) > xp_before.get("current_level", 1):
            leveled_up = True
            bot = kwargs.get("bot")
            cid = kwargs.get("chat_id")
            if bot and cid:
                try:
                    await bot.send_message(
                        chat_id=cid,
                        text=(
                            f"🎉 *Новый уровень!* Уровень {level_info['current_level']} — "
                            f"*{level_info['level_name']}*\n"
                            f"Всего XP: {new_total} ⚡"
                        ),
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass

    logger.info(
        f"[TOOL] award_xp: user={tg_id}, +{inp['xp_amount']}XP, "
        f"total={new_total}, leveled_up={leveled_up}"
    )
    return {
        "success": True,
        "xp_awarded": inp["xp_amount"],
        "total_xp": new_total,
        "current_level": level_info.get("current_level") if level_info else None,
        "level_name": level_info.get("level_name") if level_info else None,
        "leveled_up": leveled_up,
    }
