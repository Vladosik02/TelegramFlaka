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
# ДИСПЕТЧЕР ИНСТРУМЕНТОВ (module-level для валидации при старте)
# ═══════════════════════════════════════════════════════════════════════════
# Определяется после объявления всех _tool_* функций в конце файла,
# но Python позволяет ссылаться на них здесь — заполнится при импорте модуля.
# Используется в execute_tool() и для startup-валидации в main.py.
_DISPATCH: dict = {}   # заполняется в _init_dispatch() в конце файла


def _init_dispatch() -> None:
    """Инициализирует глобальный диспетчер после определения всех функций."""
    global _DISPATCH
    _DISPATCH = {
        # WRITE (9)
        "save_workout":           _tool_save_workout,
        "save_metrics":           _tool_save_metrics,
        "save_nutrition":         _tool_save_nutrition,
        "save_exercise_result":   _tool_save_exercise_result,
        "set_personal_record":    _tool_set_personal_record,
        "update_athlete_card":    _tool_update_athlete_card,
        "save_episode":           _tool_save_episode,
        "award_xp":               _tool_award_xp,
        "save_training_plan":     _tool_save_training_plan,
        # READ (6)
        "get_weekly_stats":       _tool_get_weekly_stats,
        "get_nutrition_history":  _tool_get_nutrition_history,
        "get_personal_records":   _tool_get_personal_records,
        "get_current_plan":       _tool_get_current_plan,
        "get_user_profile":       _tool_get_user_profile,
        "get_workout_prediction": _tool_get_workout_prediction,
    }


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
            input_preview = str(tool_input)[:200] if tool_input is not None else "None"
            logger.error(
                f"[TOOL] Error in '{tool_name}' for {tg_id}: {e} "
                f"| input_type={type(tool_input).__name__} | input={input_preview}"
            )
            result_content = {"error": str(e), "success": False}

        # Уведомляем пользователя если инструмент не сработал (Фаза 14)
        if isinstance(result_content, dict) and result_content.get("success") is False:
            try:
                from bot.debug import notify_tool_result
                await notify_tool_result(bot, chat_id, tool_name, result_content)
            except Exception as de:
                logger.warning(f"[TOOL] debug notify failed: {de}")

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
    handler = _DISPATCH.get(tool_name)
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
        except Exception as e:
            logger.warning(f"[TOOL] save_metrics: episodic save failed for {tg_id}: {e}")

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

    # Валидация обязательных полей (Фаза 14.2)
    if not inp.get("exercise_name"):
        logger.warning(f"[TOOL] save_exercise_result: missing exercise_name for {tg_id}")
        return {"error": "Missing required field: exercise_name", "success": False}

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

    # Валидация обязательных полей (Фаза 14.2)
    for field in ("exercise_name", "record_value", "record_type"):
        if field not in inp or inp[field] is None:
            logger.warning(f"[TOOL] set_personal_record: missing '{field}' for {tg_id}")
            return {"error": f"Missing required field: {field}", "success": False}
    valid_types = ("weight", "reps", "time")
    if inp["record_type"] not in valid_types:
        logger.warning(f"[TOOL] set_personal_record: invalid record_type '{inp['record_type']}' for {tg_id}")
        return {"error": f"record_type must be one of: {valid_types}", "success": False}

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
    except Exception as e:
        logger.warning(f"[TOOL] set_personal_record: episodic save failed for {tg_id}: {e}")

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
    if "equipment" in inp:
        import json as _json
        training_fields["equipment"] = _json.dumps(
            inp["equipment"], ensure_ascii=False
        )
        updated.append("equipment")

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
        "success": True,
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


# ═══════════════════════════════════════════════════════════════════════════
# READ-ИНСТРУМЕНТЫ (Agent Fix)
# ═══════════════════════════════════════════════════════════════════════════

async def _tool_get_nutrition_history(tg_id: int, inp: dict, **kwargs) -> dict:
    """Получить историю питания за N дней."""
    from db.queries.nutrition import get_nutrition_log

    user = get_user(tg_id)
    if not user:
        return {"error": "User not found", "success": False}

    days = inp.get("days", 7)
    entries = get_nutrition_log(user["id"], days=days)

    if not entries:
        return {
            "success": True,
            "days": days,
            "entries": [],
            "message": f"Нет данных о питании за последние {days} дней",
        }

    result_entries = []
    total_cal, total_p, total_f, total_c = 0, 0, 0, 0
    count = 0
    for e in entries:
        entry = {"date": e["date"]}
        if e.get("calories"):
            entry["calories"] = e["calories"]
            total_cal += e["calories"]
            count += 1
        if e.get("protein_g"):
            entry["protein_g"] = e["protein_g"]
            total_p += e["protein_g"]
        if e.get("fat_g"):
            entry["fat_g"] = e["fat_g"]
            total_f += e["fat_g"]
        if e.get("carbs_g"):
            entry["carbs_g"] = e["carbs_g"]
            total_c += e["carbs_g"]
        if e.get("meal_notes"):
            entry["meal_notes"] = e["meal_notes"][:100]
        if e.get("junk_food"):
            entry["junk_food"] = True
        result_entries.append(entry)

    avg = {}
    if count > 0:
        avg = {
            "avg_calories": round(total_cal / count),
            "avg_protein": round(total_p / count, 1),
            "avg_fat": round(total_f / count, 1),
            "avg_carbs": round(total_c / count, 1),
        }

    logger.info(f"[TOOL] get_nutrition_history: user={tg_id}, days={days}, entries={len(result_entries)}")
    return {
        "success": True,
        "days": days,
        "entries": result_entries,
        "averages": avg,
    }


async def _tool_get_personal_records(tg_id: int, inp: dict, **kwargs) -> dict:
    """Получить все личные рекорды."""
    from db.queries.exercises import get_personal_records

    user = get_user(tg_id)
    if not user:
        return {"error": "User not found", "success": False}

    limit = inp.get("limit", 10)
    records = get_personal_records(user["id"], limit=limit)

    if not records:
        return {
            "success": True,
            "records": [],
            "message": "Пока нет личных рекордов",
        }

    result_records = []
    exercise_filter = inp.get("exercise_name", "").lower()
    for r in records:
        if exercise_filter and exercise_filter not in r["exercise_name"].lower():
            continue
        rec = {
            "exercise": r["exercise_name"],
            "value": r["record_value"],
            "type": r.get("record_type", ""),
            "date": r.get("set_at", ""),
        }
        if r.get("improvement_pct"):
            rec["improvement_pct"] = r["improvement_pct"]
        result_records.append(rec)

    logger.info(f"[TOOL] get_personal_records: user={tg_id}, count={len(result_records)}")
    return {
        "success": True,
        "records": result_records,
    }


async def _tool_get_current_plan(tg_id: int, inp: dict, **kwargs) -> dict:
    """Получить текущий план тренировок."""
    from db.queries.training_plan import get_active_plan

    user = get_user(tg_id)
    if not user:
        return {"error": "User not found", "success": False}

    plan = get_active_plan(user["id"])
    if not plan:
        return {
            "success": True,
            "plan": None,
            "message": "Нет активного плана тренировок",
        }

    try:
        days_list = json.loads(plan["plan_json"])
    except Exception:
        days_list = []

    result = {
        "success": True,
        "plan_id": plan.get("plan_id"),
        "week_start": plan.get("week_start"),
        "workouts_planned": plan.get("workouts_planned", 0),
        "workouts_completed": plan.get("workouts_completed", 0),
        "ai_rationale": plan.get("ai_rationale", "")[:200],
        "days": [],
    }

    for day in days_list:
        d = {
            "weekday": day.get("weekday", ""),
            "date": day.get("date", ""),
            "type": day.get("type", "rest"),
            "label": day.get("label", ""),
            "completed": day.get("completed", False),
        }
        exercises = day.get("exercises") or []
        if exercises:
            d["exercises"] = [
                {
                    "name": ex.get("name", ""),
                    "sets": ex.get("sets"),
                    "reps": ex.get("reps"),
                    "weight_kg_target": ex.get("weight_kg_target"),
                }
                for ex in exercises[:5]
            ]
        result["days"].append(d)

    logger.info(f"[TOOL] get_current_plan: user={tg_id}, plan_id={result['plan_id']}")
    return result


async def _tool_get_user_profile(tg_id: int, inp: dict, **kwargs) -> dict:
    """Получить полный профиль пользователя."""
    from db.queries.memory import get_l0_surface
    from db.queries.gamification import get_user_level_info
    from db.queries.workouts import get_metrics_range, get_streak

    user = get_user(tg_id)
    if not user:
        return {"error": "User not found", "success": False}

    uid = user["id"]
    surface = get_l0_surface(uid)
    xp_info = get_user_level_info(uid)
    streak = get_streak(uid)
    recent_metrics = get_metrics_range(uid, days=7)

    profile = {
        "success": True,
        "name": user.get("name"),
        "goal": user.get("goal"),
        "fitness_level": user.get("fitness_level"),
        "training_location": user.get("training_location", "flexible"),
        "active": bool(user.get("active", 1)),
        "streak_days": streak,
    }

    if surface:
        profile["age"] = surface.get("age")
        profile["height_cm"] = surface.get("height_cm")
        profile["season"] = surface.get("season", "maintain")

    if user.get("injuries"):
        try:
            profile["injuries"] = json.loads(user["injuries"])
        except Exception:
            profile["injuries"] = []

    if xp_info:
        profile["total_xp"] = xp_info.get("total_xp", 0)
        profile["current_level"] = xp_info.get("current_level", 1)
        profile["level_name"] = xp_info.get("level_name", "Новичок")

    # Последний вес
    if recent_metrics:
        for m in recent_metrics:
            if m.get("weight_kg"):
                profile["current_weight_kg"] = m["weight_kg"]
                profile["weight_date"] = m["date"]
                break
        latest = recent_metrics[0]
        profile["latest_sleep"] = latest.get("sleep_hours")
        profile["latest_energy"] = latest.get("energy")
        profile["latest_mood"] = latest.get("mood")

    logger.info(f"[TOOL] get_user_profile: user={tg_id}")
    return profile


async def _tool_get_workout_prediction(tg_id: int, inp: dict, **kwargs) -> dict:
    """Получить прогноз тренировки на сегодня."""
    from scheduler.prediction import build_workout_prediction

    user = get_user(tg_id)
    if not user:
        return {"error": "User not found", "success": False}

    prediction = build_workout_prediction(user["id"])
    if not prediction:
        return {
            "success": True,
            "prediction": None,
            "message": "Сегодня нет тренировки по плану (отдых или план не создан).",
        }

    # Формируем компактный результат для Claude
    exercises_compact = []
    for ep in prediction.get("exercises", []):
        ex_data = {
            "name": ep["exercise_name"],
            "prediction": ep.get("prediction", {}),
            "reasoning": ep.get("reasoning", ""),
        }
        if ep.get("last_result"):
            ex_data["last_result"] = ep["last_result"]
        exercises_compact.append(ex_data)

    result = {
        "success": True,
        "date": prediction["date"],
        "label": prediction["label"],
        "day_type": prediction["day_type"],
        "rpe_ceiling": prediction.get("rpe_ceiling"),
        "summary": prediction.get("summary", ""),
        "exercises": exercises_compact,
    }

    # Добавляем контекст recovery и мезоцикла
    if prediction.get("recovery"):
        r = prediction["recovery"]
        result["recovery_score"] = r.get("score")
        result["recovery_label"] = r.get("label")
    if prediction.get("meso_phase"):
        result["meso_phase"] = prediction["meso_phase"]
        result["meso_week"] = prediction.get("meso_week")
    if prediction.get("sleep"):
        result["last_sleep"] = prediction["sleep"]
    if prediction.get("energy"):
        result["last_energy"] = prediction["energy"]

    logger.info(
        f"[TOOL] get_workout_prediction: user={tg_id}, "
        f"exercises={len(exercises_compact)}, rpe_ceiling={result.get('rpe_ceiling')}"
    )
    return result


async def _tool_save_training_plan(tg_id: int, inp: dict, **kwargs) -> dict:
    """
    Сохраняет или обновляет тренировочный план в БД.
    Вызывается когда пользователь просит составить/скорректировать план.

    Логика:
      - Если план на эту неделю ещё не существует — INSERT (workouts_completed=0).
      - Если план существует И workouts_completed > 0 — UPDATE через update_plan_json()
        чтобы сохранить уже засчитанные тренировки (пользователь переделывает план
        в середине недели — нельзя обнулять прогресс).
      - Если план существует И workouts_completed == 0 — INSERT OR REPLACE (безопасно).
    """
    import json as _json
    from db.queries.training_plan import (
        save_training_plan, get_current_week_start, get_next_week_start,
        make_plan_id, get_plan_by_id, update_plan_json,
    )

    user = get_user(tg_id)
    if not user:
        return {"error": "User not found", "success": False}

    uid = user["id"]
    plan_json_raw = inp.get("plan_json", "")
    rationale     = inp.get("rationale", "")
    week_start    = inp.get("week_start")

    # Нормализация: Claude может прислать список вместо JSON-строки (игнорирует type:string в схеме)
    if isinstance(plan_json_raw, list):
        days = plan_json_raw
        plan_json_str = _json.dumps(days, ensure_ascii=False)
    elif isinstance(plan_json_raw, str):
        try:
            days = _json.loads(plan_json_raw)
        except Exception as e:
            return {"error": f"Invalid plan_json: {e}", "success": False}
        plan_json_str = plan_json_raw
    else:
        return {
            "error": f"plan_json must be JSON string or array, got {type(plan_json_raw).__name__}",
            "success": False,
        }

    if not isinstance(days, list) or len(days) == 0:
        return {"error": "plan_json must be a non-empty JSON array", "success": False}

    # Защита от double-encoding: элементы могут быть строками вместо объектов
    normalized_days = []
    for item in days:
        if isinstance(item, str):
            try:
                parsed = _json.loads(item)
                if not isinstance(parsed, dict):
                    return {"error": "plan_json day entry must be an object", "success": False}
                normalized_days.append(parsed)
            except Exception:
                return {"error": "plan_json contains invalid day string entry", "success": False}
        elif isinstance(item, dict):
            normalized_days.append(item)
        else:
            return {"error": f"plan_json: unexpected day type {type(item).__name__}", "success": False}
    days = normalized_days
    plan_json_str = _json.dumps(days, ensure_ascii=False)

    # Определяем неделю: если не задана — текущая неделя (или следующая, если сегодня воскресенье)
    if not week_start:
        today = datetime.date.today()
        if today.weekday() == 6:  # воскресенье — план на следующую неделю
            week_start = get_next_week_start()
        else:
            week_start = get_current_week_start()

    # Считаем метрики плана
    workouts_planned = 0
    volume_total = 0
    intensities = []
    for day in days:
        if day.get("type") not in ("rest", "recovery"):
            workouts_planned += 1
            volume_total += day.get("duration_min") or 0
        for ex in (day.get("exercises") or []):
            if ex.get("rpe"):
                intensities.append(float(ex["rpe"]))

    intensity_avg = round(sum(intensities) / len(intensities), 1) if intensities else None

    # Проверяем: есть ли уже план на эту неделю с выполненными тренировками?
    # Если да — нельзя делать INSERT OR REPLACE (он обнулит workouts_completed).
    # Используем update_plan_json() — обновляет только JSON+rationale, сохраняет прогресс.
    plan_id = make_plan_id(uid, week_start)
    existing = get_plan_by_id(plan_id)

    if existing and existing.get("workouts_completed", 0) > 0:
        update_plan_json(plan_id, plan_json_str, rationale or None)
        completed = existing["workouts_completed"]
        logger.info(
            f"[TOOL] save_training_plan: UPDATE (preserved workouts_completed={completed}) "
            f"user={tg_id}, plan_id={plan_id}, week={week_start}"
        )
    else:
        plan_id = save_training_plan(
            user_id=uid,
            week_start=week_start,
            plan_json_str=plan_json_str,
            ai_rationale=rationale,
            workouts_planned=workouts_planned,
            volume_total=volume_total,
            intensity_avg=intensity_avg,
            status="active",
        )
        logger.info(
            f"[TOOL] save_training_plan: INSERT user={tg_id}, plan_id={plan_id}, "
            f"week={week_start}, workouts={workouts_planned}"
        )

    return {
        "success": True,
        "plan_id": plan_id,
        "week_start": week_start,
        "workouts_planned": workouts_planned,
        "message": f"Plan saved ✅ (plan_id={plan_id}, week={week_start})",
    }


# ═══════════════════════════════════════════════════════════════════════════
# Инициализация диспетчера (вызывается после определения всех _tool_* функций)
# ═══════════════════════════════════════════════════════════════════════════
_init_dispatch()
