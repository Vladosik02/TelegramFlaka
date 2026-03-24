"""
scheduler/logic.py — Логика плановых сообщений (без APScheduler деталей).

V2 Чек-ины (без AI для шаблонных сообщений):
  09:00  Утро    — сон + самочувствие (кнопки)
  12:30  День    — еда (текст→AI→КБЖУ) + напоминание о тренировке
  16:00  Вечер   — тренировка (кнопки) + еда (текст→AI→КБЖУ, накопление)
  23:00  Ночь    — тренировка (если не было) + еда + мини-итог дня
"""
import logging
import datetime
import json
import random
from telegram import Bot
from telegram.ext import Application

from db.queries.user import get_user
from db.queries.context import get_or_create_checkin, update_checkin, get_pending_reminders, mark_reminder_sent
from db.queries.stats import save_weekly_summary
from db.queries.workouts import get_weekly_stats, get_streak, get_workouts_range, get_metrics_range, get_today_workout
from db.queries.nutrition import get_today_nutrition
from ai.context_builder import build_weekly_report_context
from ai.client import generate_scheduled_agent_message
from db.writer import save_ai_response
from db.queries.memory import upsert_intelligence, append_observation
from bot.keyboards import (
    kb_checkin_sleep, kb_checkin_wellbeing,
    kb_checkin_workout_done, kb_checkin_food_skip,
    kb_reminder,
)
from config import (
    SCHEDULE_LIGHT_MORNING_WINDOW, SCHEDULE_LIGHT_AFTERNOON_WINDOW,
    SILENCE_AFTER_DAYS, SOFT_START_DAYS,
    MORNING_FACTS, HABIT_FACTS,
)

logger = logging.getLogger(__name__)


def _get_all_active_users() -> list[dict]:
    from db.connection import get_connection
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM user_profile WHERE active = 1"
    ).fetchall()
    return [dict(r) for r in rows]


def _should_silence(user: dict) -> bool:
    """Молчать если пользователь игнорирует > SILENCE_AFTER_DAYS дней."""
    if not user.get("last_active"):
        return False
    last = datetime.datetime.fromisoformat(user["last_active"])
    delta = (datetime.datetime.now() - last).days
    return delta >= SILENCE_AFTER_DAYS


def _is_soft_start(user: dict) -> bool:
    """Мягкий старт после долгой паузы."""
    if not user.get("paused_at"):
        return False
    paused = datetime.datetime.fromisoformat(user["paused_at"])
    delta = (datetime.datetime.now() - paused).days
    return delta >= SOFT_START_DAYS


def _get_today_plan_workout(user_id: int) -> dict | None:
    """Возвращает тренировку из активного плана на сегодня или None."""
    from db.queries.training_plan import get_active_plan
    plan = get_active_plan(user_id)
    if not plan:
        return None
    today_str = datetime.date.today().isoformat()
    try:
        days = json.loads(plan["plan_json"])
        for day in days:
            if day.get("date") == today_str:
                return day
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════════════════════
# УТРЕННИЙ ЧЕК-ИН (09:00) — сон + самочувствие
# ═══════════════════════════════════════════════════════════════════════════

async def send_morning_checkin(bot: Bot, telegram_id: int) -> None:
    """Шаг 1: приветствие + факт + вопрос о сне (кнопки)."""
    user = get_user(telegram_id)
    if not user or not user["active"]:
        return
    if _should_silence(user):
        logger.info(f"Silencing {telegram_id} — inactive too long")
        return

    name = user.get("name") or "Атлет"
    streak = get_streak(user["id"])
    fact = random.choice(MORNING_FACTS)

    streak_text = f"  Стрик: {streak} дн." if streak > 0 else ""
    text = (
        f"Доброе утро, {name}!{streak_text}\n\n"
        f"💡 {fact}\n\n"
        f"Сколько часов спал сегодня?"
    )
    await bot.send_message(
        chat_id=telegram_id,
        text=text,
        reply_markup=kb_checkin_sleep(),
    )
    today = datetime.date.today().isoformat()
    get_or_create_checkin(user["id"], today, "morning")
    logger.info(f"[CHECKIN] Morning sent to {telegram_id}")


# ═══════════════════════════════════════════════════════════════════════════
# ДНЕВНОЙ ЧЕК-ИН (12:30) — еда + напоминание о тренировке
# ═══════════════════════════════════════════════════════════════════════════

async def send_afternoon_checkin(bot: Bot, telegram_id: int) -> None:
    """Вопрос о еде (свободный текст) + факт о привычках."""
    user = get_user(telegram_id)
    if not user or not user["active"]:
        return

    today = datetime.date.today()
    day_names = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    day_name = day_names[today.weekday()]
    date_str = today.strftime("%d.%m")
    fact = random.choice(HABIT_FACTS)

    text = (
        f"📅 {day_name}, {date_str}\n\n"
        f"Что ел сегодня? Напиши что было на завтрак/обед.\n\n"
        f"⚠️ {fact}"
    )
    await bot.send_message(
        chat_id=telegram_id,
        text=text,
        reply_markup=kb_checkin_food_skip(),
    )
    # Ставим флаг ожидания текста о еде
    from bot.handlers import _AWAITING_FOOD
    _AWAITING_FOOD[telegram_id] = "afternoon"
    get_or_create_checkin(user["id"], today.isoformat(), "afternoon")
    logger.info(f"[CHECKIN] Afternoon sent to {telegram_id}")


async def send_afternoon_workout_reminder(bot: Bot, telegram_id: int, user_id: int) -> None:
    """Отправляет напоминание о тренировке после записи еды (шаг 2 дневного чек-ина)."""
    plan_workout = _get_today_plan_workout(user_id)
    if not plan_workout:
        return
    wtype = plan_workout.get("type")
    if wtype in ("rest", "recovery", None):
        await bot.send_message(
            chat_id=telegram_id,
            text="🌿 Сегодня день отдыха по плану. Отдыхай!",
        )
        return
    label = plan_workout.get("label") or plan_workout.get("type") or "тренировка"
    exercises = plan_workout.get("exercises") or []
    ex_lines = []
    for ex in exercises[:5]:
        parts = [f"• {ex.get('name', '?')}"]
        if ex.get("sets") and ex.get("reps"):
            parts.append(f"{ex['sets']}×{ex['reps']}")
        if ex.get("weight_kg_target"):
            parts.append(f"@ {ex['weight_kg_target']} кг")
        ex_lines.append(" ".join(parts))
    ex_text = "\n".join(ex_lines) if ex_lines else ""
    text = f"🏋️ Сегодня по плану: {label}"
    if ex_text:
        text += f"\n\n{ex_text}"
    text += "\n\nУдачной тренировки!"
    await bot.send_message(chat_id=telegram_id, text=text)


# ═══════════════════════════════════════════════════════════════════════════
# ВЕЧЕРНИЙ ЧЕК-ИН (16:00) — тренировка + еда
# ═══════════════════════════════════════════════════════════════════════════

async def send_evening_checkin(bot: Bot, telegram_id: int) -> None:
    """Шаг 1: сделал тренировку? (кнопки)."""
    user = get_user(telegram_id)
    if not user or not user["active"]:
        return

    text = "Как прошёл день? Сделал тренировку? 💪"
    await bot.send_message(
        chat_id=telegram_id,
        text=text,
        reply_markup=kb_checkin_workout_done(),
    )
    from bot.handlers import _CHECKIN_SLOT
    _CHECKIN_SLOT[telegram_id] = "evening"
    today = datetime.date.today().isoformat()
    get_or_create_checkin(user["id"], today, "evening")
    logger.info(f"[CHECKIN] Evening sent to {telegram_id}")


# ═══════════════════════════════════════════════════════════════════════════
# НОЧНОЙ ЧЕК-ИН (23:00) — итог дня
# ═══════════════════════════════════════════════════════════════════════════

async def send_night_checkin(bot: Bot, telegram_id: int) -> None:
    """
    Шаг 1: если тренировка не зафиксирована — спрашиваем.
    Если уже есть — сразу спрашиваем про еду.
    """
    user = get_user(telegram_id)
    if not user or not user["active"]:
        return
    if _should_silence(user):
        return

    today_workout = get_today_workout(user["id"])
    workout_done = bool(today_workout and today_workout.get("completed"))

    if not workout_done:
        # Спрашиваем про тренировку
        text = "🌙 Вечер! Тренировался сегодня?"
        await bot.send_message(
            chat_id=telegram_id,
            text=text,
            reply_markup=kb_checkin_workout_done(),
        )
        from bot.handlers import _CHECKIN_SLOT
        _CHECKIN_SLOT[telegram_id] = "night"
    else:
        # Тренировка уже записана — сразу про еду
        text = "🌙 Вечер! Что ел за ужин/вечер?"
        await bot.send_message(
            chat_id=telegram_id,
            text=text,
            reply_markup=kb_checkin_food_skip(),
        )
        from bot.handlers import _AWAITING_FOOD
        _AWAITING_FOOD[telegram_id] = "night"

    today = datetime.date.today().isoformat()
    get_or_create_checkin(user["id"], today, "night")
    logger.info(f"[CHECKIN] Night sent to {telegram_id}")


async def send_night_summary(bot: Bot, telegram_id: int, user_id: int) -> None:
    """Мини-итог дня (шаблон, без AI). Отправляется после ответов на ночной чек-ин."""
    today_workout = get_today_workout(user_id)
    nutrition = get_today_nutrition(user_id)
    metrics_list = get_metrics_range(user_id, days=1)
    metrics = metrics_list[0] if metrics_list else None

    parts = ["📊 Итог дня:"]
    if nutrition and nutrition.get("calories"):
        n = nutrition
        parts.append(
            f"🍽 {n['calories']} ккал"
            f" (Б{n.get('protein_g', 0)} Ж{n.get('fat_g', 0)} У{n.get('carbs_g', 0)})"
        )
    else:
        parts.append("🍽 Питание не записано")

    if today_workout and today_workout.get("completed"):
        parts.append("✅ Тренировка выполнена")
    else:
        parts.append("❌ Тренировка не выполнена")

    if metrics and metrics.get("sleep_hours"):
        parts.append(f"😴 Сон: {metrics['sleep_hours']}ч")

    # Контекстный мини-урок (teach moment)
    from scheduler.teach_moments import select_teach_moment
    from db.queries.memory import get_l2_brief
    l2 = get_l2_brief(user_id)
    teach = select_teach_moment(
        user_id=user_id,
        workout=today_workout,
        nutrition=nutrition,
        metrics=metrics,
        goal_calories=l2.get("daily_calories") if l2 else None,
        goal_protein=l2.get("protein_g") if l2 else None,
    )
    if teach:
        parts.append(f"\n💡 {teach}")

    parts.append("\nСпокойной ночи! 🌙")

    await bot.send_message(chat_id=telegram_id, text="\n".join(parts))


async def send_weekly_report(bot: Bot, telegram_id: int) -> None:
    user = get_user(telegram_id)
    if not user or not user["active"]:
        return

    context = build_weekly_report_context(telegram_id)
    if not context:
        return

    # Фаза 17 — передаём только 5 read-инструментов вместо ALL_TOOLS (13).
    # Weekly report только читает статистику и сохраняет инсайты, write-tools не нужны.
    # Экономия: ~2800 токенов input per call (3502 → ~700 tok на tool-описания).
    from ai.tools import _TOOLS_WEEKLY_REPORT
    text = await generate_scheduled_agent_message(
        bot, telegram_id, context, telegram_id,
        tools=_TOOLS_WEEKLY_REPORT,
    )
    await bot.send_message(chat_id=telegram_id, text=text)
    save_ai_response(telegram_id, text)

    # Сохранить агрегат
    weekly = get_weekly_stats(user["id"])
    today = datetime.date.today()
    mon = today - datetime.timedelta(days=today.weekday())
    save_weekly_summary(user["id"], mon.isoformat(), weekly, text)
    logger.info(f"Weekly report sent to {telegram_id}")


async def send_snooze_reminder(bot: Bot, telegram_id: int) -> None:
    """Одноразовое напоминание через 30 мин после нажатия snooze."""
    try:
        await bot.send_message(
            chat_id=telegram_id,
            text="⏰ Прошло 30 минут. Ещё не поздно потренироваться! 💪",
            reply_markup=kb_reminder(),
        )
        logger.info(f"Snooze reminder sent to {telegram_id}")
    except Exception as e:
        logger.error(f"Snooze reminder failed for {telegram_id}: {e}")


async def check_and_send_reminders(bot: Bot) -> None:
    """Отправить все просроченные напоминания."""
    users = _get_all_active_users()
    for user in users:
        if _should_silence(user):
            continue
        pending = get_pending_reminders(user["id"])
        for reminder in pending:
            try:
                await bot.send_message(
                    chat_id=user["telegram_id"],
                    text="⏰ Ещё не было тренировки. Как дела?",
                    reply_markup=kb_reminder()
                )
                mark_reminder_sent(reminder["id"])
            except Exception as e:
                logger.error(f"Reminder failed for {user['telegram_id']}: {e}")


async def broadcast_morning(bot: Bot) -> None:
    for user in _get_all_active_users():
        try:
            await send_morning_checkin(bot, user["telegram_id"])
        except Exception as e:
            logger.error(f"Morning broadcast failed for {user['telegram_id']}: {e}")


async def broadcast_afternoon(bot: Bot) -> None:
    for user in _get_all_active_users():
        try:
            await send_afternoon_checkin(bot, user["telegram_id"])
        except Exception as e:
            logger.error(f"Afternoon broadcast failed for {user['telegram_id']}: {e}")


async def broadcast_evening(bot: Bot) -> None:
    for user in _get_all_active_users():
        try:
            await send_evening_checkin(bot, user["telegram_id"])
        except Exception as e:
            logger.error(f"Evening broadcast failed for {user['telegram_id']}: {e}")


async def broadcast_night(bot: Bot) -> None:
    for user in _get_all_active_users():
        try:
            await send_night_checkin(bot, user["telegram_id"])
        except Exception as e:
            logger.error(f"Night broadcast failed for {user['telegram_id']}: {e}")


async def broadcast_weekly(bot: Bot) -> None:
    for user in _get_all_active_users():
        try:
            await send_weekly_report(bot, user["telegram_id"])
        except Exception as e:
            logger.error(f"Weekly broadcast failed for {user['telegram_id']}: {e}")


# ─── L4 Intelligence Update ───────────────────────────────────────────────

_L4_SYSTEM = (
    "Ты — аналитик данных личного тренера. "
    "Пиши коротко, фактически, без вступлений. Только по делу."
)

_L4_DIGEST_PROMPT = """\
Проанализируй данные атлета за последние 7 дней и напиши:
1. Дайджест недели (2–3 предложения): что было сделано, ключевые цифры
2. Главный тренд (1 предложение): что изменилось по сравнению с прошлой неделей
3. Одно AI-наблюдение (1 предложение): паттерн поведения или рекомендация

Данные:
Тренировок: {workouts_done}/{workouts_total}
Ср. интенсивность: {avg_intensity}/10
Ср. сон: {avg_sleep} ч
Ср. энергия: {avg_energy}/5
Стрик: {streak} дней
Цель: {goal}

Формат ответа (строго):
ДАЙДЖЕСТ: <текст>
ТРЕНД: <текст>
НАБЛЮДЕНИЕ: <текст>"""


def _parse_l4_response(text: str) -> dict:
    """Парсит структурированный ответ AI для L4."""
    result = {"weekly_digest": None, "trend_summary": None, "observation": None}
    for line in text.splitlines():
        if line.startswith("ДАЙДЖЕСТ:"):
            result["weekly_digest"] = line[len("ДАЙДЖЕСТ:"):].strip()
        elif line.startswith("ТРЕНД:"):
            result["trend_summary"] = line[len("ТРЕНД:"):].strip()
        elif line.startswith("НАБЛЮДЕНИЕ:"):
            result["observation"] = line[len("НАБЛЮДЕНИЕ:"):].strip()
    return result


async def update_l4_for_user(uid: int, telegram_id: int) -> None:
    """Генерирует L4 Intelligence дайджест для одного пользователя."""
    from ai.client import get_client
    from config import MODEL_SCHEDULED as MODEL  # Haiku: простой структурированный вывод, Sonnet избыточен

    user = get_user(telegram_id)
    if not user:
        return

    weekly = get_weekly_stats(uid)
    streak = get_streak(uid)

    prompt = _L4_DIGEST_PROMPT.format(
        workouts_done=weekly.get("workouts_done", 0),
        workouts_total=weekly.get("workouts_total", 0),
        avg_intensity=weekly.get("avg_intensity") or "нет данных",
        avg_sleep=weekly.get("avg_sleep") or "нет данных",
        avg_energy=weekly.get("avg_energy") or "нет данных",
        streak=streak,
        goal=user.get("goal") or "улучшить форму",
    )

    try:
        client = get_client()
        response = client.messages.create(
            model=MODEL,
            max_tokens=300,
            system=_L4_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        parsed = _parse_l4_response(text)

        update_kwargs = {}
        if parsed["weekly_digest"]:
            update_kwargs["weekly_digest"] = parsed["weekly_digest"]
        if parsed["trend_summary"]:
            update_kwargs["trend_summary"] = parsed["trend_summary"]

        # Определяем мотивацию по данным
        avg_energy = weekly.get("avg_energy")
        if avg_energy is not None:
            if float(avg_energy) <= 2.0:
                update_kwargs["motivation_level"] = "low"
            elif float(avg_energy) >= 4.0:
                update_kwargs["motivation_level"] = "high"
            else:
                update_kwargs["motivation_level"] = "normal"

        if update_kwargs:
            upsert_intelligence(uid, **update_kwargs)

        if parsed["observation"]:
            append_observation(uid, parsed["observation"])

        logger.info(f"[L4] Intelligence updated for user_id={uid}")

    except Exception as e:
        logger.error(f"[L4] Failed to update intelligence for uid={uid}: {e}")


async def cleanup_old_checkins() -> None:
    """
    Удаляет записи из таблицы checkins старше 90 дней.
    Запускается еженедельно (воскресенье 22:00) — Фаза 14.7.
    """
    from db.connection import get_connection
    cutoff = (datetime.date.today() - datetime.timedelta(days=90)).isoformat()
    try:
        conn = get_connection()
        result = conn.execute(
            "DELETE FROM checkins WHERE date < ?", (cutoff,)
        )
        conn.commit()
        deleted = result.rowcount
        logger.info(f"[CLEANUP] Deleted {deleted} old checkin records (before {cutoff})")
    except Exception as e:
        logger.error(f"[CLEANUP] checkins cleanup failed: {e}")


async def broadcast_l4_intelligence(bot=None) -> None:
    """
    Еженедельное обновление L4 Intelligence для всех активных пользователей.
    Фаза 16.3: если передан bot — отправляет weekly_digest пользователю в чат.
    """
    from db.queries.memory import get_l4_intelligence

    users = _get_all_active_users()
    logger.info(f"[L4] Starting intelligence update for {len(users)} users")
    for user in users:
        try:
            await update_l4_for_user(user["id"], user["telegram_id"])

            # Фаза 16.3 — отправка дайджеста в чат после генерации
            if bot:
                try:
                    l4 = get_l4_intelligence(user["id"])
                    digest = l4.get("weekly_digest") if l4 else None
                    trend  = l4.get("trend_summary") if l4 else None
                    if digest:
                        lines = ["📊 *Недельный дайджест от Алекса*\n"]
                        lines.append(digest)
                        if trend:
                            lines.append(f"\n📈 _{trend}_")
                        lines.append("\n_Хорошей недели! 💪_")
                        await bot.send_message(
                            chat_id=user["telegram_id"],
                            text="\n".join(lines),
                            parse_mode="Markdown",
                        )
                        logger.info(f"[L4] Weekly digest sent to {user['telegram_id']}")
                except Exception as send_err:
                    logger.warning(f"[L4] Digest send failed for {user['telegram_id']}: {send_err}")

        except Exception as e:
            logger.error(f"[L4] Broadcast failed for {user['telegram_id']}: {e}")
    logger.info("[L4] Intelligence broadcast complete")


# ─── Daily Summary (Фаза 7) ───────────────────────────────────────────────

_DAILY_SYSTEM = (
    "Ты — аналитик личного тренера. Пиши кратко и фактически. "
    "Без приветствий и вступлений. Только по делу."
)

_DAILY_SUMMARY_PROMPT = """\
Составь краткое дневное резюме для атлета на основе данных за {date}.

Данные дня:
Тренировка: {workout_info}
Питание: {nutrition_info}
Метрики: {metrics_info}

Требования к ответу (строго):
РЕЗЮМЕ: <2–3 предложения о дне — что было, ключевые цифры, общий тон>
ИНСАЙТ: <одна конкретная рекомендация или наблюдение на завтра>

Пиши в прошедшем времени, без воды."""


def _format_workout_info(workout: dict | None) -> str:
    if not workout:
        return "не было"
    parts = []
    if workout.get("type"):
        parts.append(workout["type"])
    if workout.get("duration_min"):
        parts.append(f"{workout['duration_min']} мин")
    if workout.get("intensity"):
        parts.append(f"интенсивность {workout['intensity']}/10")
    if not workout.get("completed"):
        parts.append("(не завершена)")
    return ", ".join(parts) if parts else "была"


def _format_nutrition_info(nutrition: dict | None, goal_calories: int | None) -> str:
    if not nutrition:
        return "нет данных"
    parts = []
    if nutrition.get("calories"):
        cal = nutrition["calories"]
        parts.append(f"{cal} ккал")
        if goal_calories and goal_calories > 0:
            pct = round(cal / goal_calories * 100)
            parts.append(f"({pct}% от цели)")
    if nutrition.get("protein_g"):
        parts.append(f"Б{nutrition['protein_g']}г")
    if nutrition.get("water_ml"):
        parts.append(f"вода {nutrition['water_ml'] // 1000:.1f}л")
    if nutrition.get("junk_food"):
        parts.append("🍔 был читмил")
    return ", ".join(parts) if parts else "нет данных"


def _format_metrics_info(metrics: dict | None) -> str:
    if not metrics:
        return "нет данных"
    parts = []
    if metrics.get("energy"):
        parts.append(f"энергия {metrics['energy']}/5")
    if metrics.get("mood"):
        parts.append(f"настроение {metrics['mood']}/5")
    if metrics.get("sleep_hours"):
        parts.append(f"сон {metrics['sleep_hours']}ч")
    if metrics.get("steps"):
        parts.append(f"{metrics['steps']} шагов")
    return ", ".join(parts) if parts else "нет данных"


def _parse_daily_response(text: str) -> dict:
    """Парсит структурированный ответ AI для daily summary."""
    result = {"summary_text": None, "key_insight": None}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("РЕЗЮМЕ:"):
            result["summary_text"] = line[len("РЕЗЮМЕ:"):].strip()
        elif line.startswith("ИНСАЙТ:"):
            result["key_insight"] = line[len("ИНСАЙТ:"):].strip()
    # Fallback: если парсинг не сработал, берём весь текст
    if not result["summary_text"]:
        result["summary_text"] = text.strip()[:300]
    return result


async def generate_daily_summary_for_user(uid: int, telegram_id: int) -> None:
    """
    Генерирует AI-резюме дня и сохраняет в daily_summary.
    Вызывается из scheduler после вечернего чек-ина (~23:00).
    """
    from ai.client import get_client
    from config import MODEL_SCHEDULED as MODEL  # Haiku: вывод 2-3 предложения, Sonnet избыточен (4× дороже)
    from db.queries.workouts import get_today_workout, get_metrics_range
    from db.queries.nutrition import get_today_nutrition
    from db.queries.memory import get_l2_brief
    from db.queries.daily_summary import upsert_daily_summary

    user = get_user(telegram_id)
    if not user:
        return

    today = datetime.date.today().isoformat()

    # Собираем данные дня
    workout   = get_today_workout(uid)
    nutrition = get_today_nutrition(uid)
    metrics_list = get_metrics_range(uid, days=1)
    metrics   = metrics_list[0] if metrics_list else None
    l2        = get_l2_brief(uid)
    goal_cal  = l2.get("daily_calories") if l2 else None

    # Флаги для структурированных полей
    workout_done = bool(workout and workout.get("completed"))
    calories_met = False
    if nutrition and nutrition.get("calories") and goal_cal:
        ratio = nutrition["calories"] / goal_cal
        calories_met = (0.85 <= ratio <= 1.15)

    # Формируем промпт
    prompt = _DAILY_SUMMARY_PROMPT.format(
        date=today,
        workout_info=_format_workout_info(workout),
        nutrition_info=_format_nutrition_info(nutrition, goal_cal),
        metrics_info=_format_metrics_info(metrics),
    )

    try:
        client = get_client()
        response = client.messages.create(
            model=MODEL,
            max_tokens=200,
            system=_DAILY_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        parsed = _parse_daily_response(raw)

        upsert_daily_summary(
            user_id=uid,
            date=today,
            summary_text=parsed["summary_text"] or raw,
            workout_done=workout_done,
            calories_met=calories_met,
            mood_score=metrics.get("mood") if metrics else None,
            energy_score=metrics.get("energy") if metrics else None,
            sleep_hours=metrics.get("sleep_hours") if metrics else None,
            key_insight=parsed.get("key_insight"),
        )
        logger.info(f"[DAILY_SUMMARY] Generated for user_id={uid} date={today}")

    except Exception as e:
        logger.error(f"[DAILY_SUMMARY] Failed for uid={uid}: {e}")


async def broadcast_daily_summary() -> None:
    """Ежедневная генерация резюме для всех активных пользователей."""
    users = _get_all_active_users()
    logger.info(f"[DAILY_SUMMARY] Generating for {len(users)} users")
    for user in users:
        if _should_silence(user):
            continue
        try:
            await generate_daily_summary_for_user(user["id"], user["telegram_id"])
        except Exception as e:
            logger.error(f"[DAILY_SUMMARY] Broadcast failed for {user['telegram_id']}: {e}")
    logger.info("[DAILY_SUMMARY] Broadcast complete")


# ─── Monthly Summary (Фаза 8.1) ───────────────────────────────────────────

_MONTHLY_SUMMARY_SYSTEM = (
    "Ты — аналитик данных персонального тренера. "
    "Пиши коротко, конкретно, с цифрами. Без приветствий и вступлений. "
    "Только факты и выводы, которые помогут в следующем месяце."
)

_MONTHLY_SUMMARY_PROMPT = """\
Проанализируй данные атлета за {month_name} {year} и напиши отчёт.

Данные месяца:
Тренировок завершено: {workouts_done} (из {workouts_total} сессий)
Средняя интенсивность: {avg_intensity}
Средний сон: {avg_sleep}
Средняя энергия: {avg_energy}
Среднее питание: {avg_calories}
Лучший рекорд месяца: {best_pr}
Цель атлета: {goal}

{prev_context}

Формат ответа (строго, каждый тег с новой строки):
РЕЗЮМЕ: <2–3 предложения — что было сделано, ключевые цифры месяца>
ТРЕНД: <1 предложение — как этот месяц соотносится с предыдущим>
ИНСАЙТ: <1 конкретная рекомендация на следующий месяц>"""

_MONTH_NAMES_RU = {
    1: "январь", 2: "февраль", 3: "март", 4: "апрель",
    5: "май", 6: "июнь", 7: "июль", 8: "август",
    9: "сентябрь", 10: "октябрь", 11: "ноябрь", 12: "декабрь",
}


def _prev_month(year: int, month: int) -> tuple[int, int]:
    """Возвращает (year, month) предыдущего месяца."""
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _parse_monthly_response(text: str) -> dict:
    """Парсит структурированный ответ AI для monthly_summary."""
    result = {"summary_text": None, "trend_vs_prev": None, "key_insight": None}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("РЕЗЮМЕ:"):
            result["summary_text"] = line[len("РЕЗЮМЕ:"):].strip()
        elif line.startswith("ТРЕНД:"):
            result["trend_vs_prev"] = line[len("ТРЕНД:"):].strip()
        elif line.startswith("ИНСАЙТ:"):
            result["key_insight"] = line[len("ИНСАЙТ:"):].strip()
    # Fallback: если парсинг не сработал — весь текст как резюме
    if not result["summary_text"]:
        result["summary_text"] = text.strip()[:400]
    return result


async def generate_monthly_summary_for_user(uid: int, telegram_id: int) -> None:
    """
    Генерирует AI-резюме прошедшего месяца и сохраняет в monthly_summary.
    Вызывается из scheduler 1-го числа в 09:00.
    Если данных за месяц нет — пропускает без ошибки.
    """
    from ai.client import get_client
    from config import MODEL_SCHEDULED as MODEL  # Haiku: структурированный вывод 3-4 предложения, Sonnet избыточен
    from db.queries.stats import get_monthly_stats
    from db.queries.monthly_summary import upsert_monthly_summary, get_month_summary
    from db.queries.memory import get_l2_brief

    user = get_user(telegram_id)
    if not user:
        return

    # Прошедший месяц (вызов идёт 1-го числа — смотрим назад)
    today = datetime.date.today()
    prev_y, prev_m = _prev_month(today.year, today.month)
    month_str = f"{prev_y:04d}-{prev_m:02d}"
    month_name = _MONTH_NAMES_RU[prev_m]

    # Агрегаты за месяц
    stats = get_monthly_stats(uid, prev_y, prev_m)

    # Нет данных — пропускаем
    if stats["workouts_done"] == 0 and stats["avg_sleep"] is None:
        logger.info(f"[MONTHLY_SUMMARY] No data for uid={uid} month={month_str}, skipping")
        return

    # Цель питания для контекста
    l2 = get_l2_brief(uid)
    goal_calories = l2.get("daily_calories") if l2 else None

    # Контекст предыдущего месяца для сравнения
    pp_y, pp_m = _prev_month(prev_y, prev_m)
    prev_summary = get_month_summary(uid, f"{pp_y:04d}-{pp_m:02d}")
    prev_context = ""
    if prev_summary and prev_summary.get("summary_text"):
        prev_mn = _MONTH_NAMES_RU.get(pp_m, str(pp_m))
        prev_context = (
            f"Данные предыдущего месяца ({prev_mn}):\n"
            f"Тренировок: {prev_summary['workouts_done']}, "
            f"сон: {prev_summary.get('avg_sleep') or 'н/д'} ч, "
            f"энергия: {prev_summary.get('avg_energy') or 'н/д'}/5\n"
            f"Резюме: {prev_summary['summary_text'][:150]}"
        )

    def _fmt(val, suffix="", default="нет данных"):
        return f"{val}{suffix}" if val is not None else default

    avg_cal_str = (
        f"{stats['avg_calories']} ккал (цель: {goal_calories} ккал)"
        if stats["avg_calories"] and goal_calories
        else _fmt(stats["avg_calories"], " ккал")
    )

    prompt = _MONTHLY_SUMMARY_PROMPT.format(
        month_name=month_name,
        year=prev_y,
        workouts_done=stats["workouts_done"],
        workouts_total=stats["workouts_total"],
        avg_intensity=_fmt(stats["avg_intensity"], "/10"),
        avg_sleep=_fmt(stats["avg_sleep"], " ч"),
        avg_energy=_fmt(stats["avg_energy"], "/5"),
        avg_calories=avg_cal_str,
        best_pr=stats["best_pr"]["text"] if stats.get("best_pr") else "нет рекордов",
        goal=user.get("goal") or "улучшить форму",
        prev_context=prev_context,
    )

    try:
        client = get_client()
        response = client.messages.create(
            model=MODEL,
            max_tokens=300,
            system=_MONTHLY_SUMMARY_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        parsed = _parse_monthly_response(raw)

        upsert_monthly_summary(
            user_id=uid,
            month=month_str,
            workouts_done=stats["workouts_done"],
            workouts_total=stats["workouts_total"],
            avg_intensity=stats["avg_intensity"],
            avg_sleep=stats["avg_sleep"],
            avg_energy=stats["avg_energy"],
            avg_calories=stats["avg_calories"],
            best_exercise=stats["best_pr"]["exercise"] if stats.get("best_pr") else None,
            best_pr_text=stats["best_pr"]["text"] if stats.get("best_pr") else None,
            summary_text=parsed["summary_text"],
            trend_vs_prev=parsed["trend_vs_prev"],
            key_insight=parsed["key_insight"],
        )
        logger.info(f"[MONTHLY_SUMMARY] Generated for uid={uid} month={month_str}")

    except Exception as e:
        logger.error(f"[MONTHLY_SUMMARY] Failed for uid={uid} month={month_str}: {e}")


async def broadcast_monthly_summary() -> None:
    """Месячная генерация резюме для всех активных пользователей (1-е число, 09:00)."""
    users = _get_all_active_users()
    logger.info(f"[MONTHLY_SUMMARY] Generating for {len(users)} users")
    for user in users:
        try:
            await generate_monthly_summary_for_user(user["id"], user["telegram_id"])
        except Exception as e:
            logger.error(f"[MONTHLY_SUMMARY] Broadcast failed for {user['telegram_id']}: {e}")
    logger.info("[MONTHLY_SUMMARY] Broadcast complete")


# ─── Training Plan — Фаза 8.3 ─────────────────────────────────────────────

_PLAN_SYSTEM = (
    "Ты — Алекс, профессиональный тренер-коуч. "
    "Пиши строго по заданному формату. "
    "Только ПЛАН (JSON) и ОБОСНОВАНИЕ — никакого другого текста."
)

_WEEKDAYS_RU = {0: "Пн", 1: "Вт", 2: "Ср", 3: "Чт", 4: "Пт", 5: "Сб", 6: "Вс"}


def _parse_plan_response(text: str) -> tuple[str | None, str | None]:
    """
    Парсит ответ AI: возвращает (plan_json_str, rationale).
    Использует подсчёт скобок для корректного извлечения вложенного JSON
    (простая regex ломается на nested arrays в exercises).
    """
    import re
    plan_json_str = None
    rationale = None

    # ── Извлекаем JSON-массив с учётом вложенных скобок ──────────────────────
    plan_marker = text.find("ПЛАН:")
    if plan_marker != -1:
        bracket_start = text.find("[", plan_marker)
        if bracket_start != -1:
            depth = 0
            for i, ch in enumerate(text[bracket_start:], bracket_start):
                if ch == "[":
                    depth += 1
                elif ch == "]":
                    depth -= 1
                    if depth == 0:
                        plan_json_str = text[bracket_start:i + 1].strip()
                        break

    # ── Ищем блок ОБОСНОВАНИЕ: ───────────────────────────────────────────────
    rat_match = re.search(r"ОБОСНОВАНИЕ:\s*(.+?)(?:\Z)", text, re.DOTALL)
    if rat_match:
        rationale = rat_match.group(1).strip()

    return plan_json_str, rationale


def _format_plan_message(plan: dict) -> str:
    """
    Форматирует тренировочный план как Telegram-сообщение (MarkdownV2-safe).
    Вызывается при отправке плана пользователю и в /plan.
    """
    import json as _json
    try:
        days = _json.loads(plan["plan_json"])
    except Exception:
        return "❌ Ошибка чтения плана."

    week_start = plan.get("week_start", "")
    plan_id = plan.get("plan_id", "")
    workouts_done = plan.get("workouts_completed", 0)
    workouts_total = plan.get("workouts_planned", 0)
    rationale = plan.get("ai_rationale", "")

    try:
        d = datetime.date.fromisoformat(week_start)
        d_end = d + datetime.timedelta(days=6)
        week_label = f"{d.strftime('%d.%m')} – {d_end.strftime('%d.%m.%Y')}"
    except Exception:
        week_label = week_start

    type_icons = {
        "strength": "💪", "cardio": "🏃", "hiit": "⚡",
        "mobility": "🧘", "rest": "😴", "recovery": "🌿",
    }

    lines = [
        f"📋 *Тренировочный план* ({week_label})",
        f"ID: `{plan_id}`",
    ]
    if workouts_total > 0:
        progress_bar = "✅" * workouts_done + "⬜" * (workouts_total - workouts_done)
        lines.append(f"Прогресс: {progress_bar} {workouts_done}/{workouts_total}")
    lines.append("━━━━━━━━━━━━━━━━━")

    for day in days:
        dtype = day.get("type", "rest")
        icon = type_icons.get(dtype, "📅")
        weekday = day.get("weekday", "")
        label = day.get("label", dtype)
        date_str = day.get("date", "")
        try:
            date_fmt = datetime.date.fromisoformat(date_str).strftime("%d.%m")
        except Exception:
            date_fmt = date_str
        completed = day.get("completed", False)
        done_mark = "✅ " if completed else ""

        lines.append(f"\n{done_mark}*{weekday} {date_fmt}* — {icon} {label}")

        exercises = day.get("exercises") or []
        for ex in exercises:
            name = ex.get("name", "")
            sets = ex.get("sets")
            reps = ex.get("reps")
            weight = ex.get("weight_kg_target")
            note = ex.get("note", "")
            parts = [f"• {name}"]
            if sets and reps:
                parts.append(f"{sets}×{reps}")
            if weight:
                parts.append(f"@ {weight} кг")
            if note:
                parts.append(f"_{note}_")
            lines.append(" ".join(parts))

        ai_note = day.get("ai_note", "")
        if ai_note:
            lines.append(f"  💬 _{ai_note}_")

    if rationale:
        lines += ["━━━━━━━━━━━━━━━━━", f"💡 {rationale}"]

    return "\n".join(lines)


async def archive_weekly_plan_for_user(uid: int) -> None:
    """
    Архивирует активный план текущей недели для пользователя.
    Считает реально выполненные тренировки из таблицы workouts.
    Вызывается каждое воскресенье в 19:00 (до генерации нового плана).
    """
    from db.queries.training_plan import get_active_plan, archive_plan
    from db.connection import get_connection

    plan = get_active_plan(uid)
    if not plan:
        return

    plan_id = plan["plan_id"]
    workouts_planned = plan.get("workouts_planned") or 0
    week_start = plan["week_start"]

    # Считаем выполненные тренировки за эту неделю из таблицы workouts
    # (по полю plan_id если есть, иначе по дате)
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM workouts WHERE plan_id = ? AND completed = 1",
            (plan_id,),
        ).fetchone()
        workouts_completed = row["cnt"] if row else 0
    except Exception:
        # план_id колонки ещё нет — fallback по дате
        if workouts_planned > 0:
            week_end = (
                datetime.date.fromisoformat(week_start) + datetime.timedelta(days=6)
            ).isoformat()
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM workouts WHERE user_id = ? AND date >= ? AND date <= ? AND completed = 1",
                (uid, week_start, week_end),
            ).fetchone()
            workouts_completed = row["cnt"] if row else 0
        else:
            workouts_completed = 0

    completion_pct = (
        round(workouts_completed / workouts_planned * 100, 1)
        if workouts_planned > 0 else 0.0
    )

    archive_plan(plan_id, workouts_completed, completion_pct)
    logger.info(
        f"[PLAN] Archived for uid={uid} plan_id={plan_id} "
        f"done={workouts_completed}/{workouts_planned} pct={completion_pct:.0f}%"
    )


async def generate_weekly_plan_for_user(uid: int, telegram_id: int, bot) -> None:
    """
    Генерирует AI-план на следующую неделю и отправляет пользователю.
    Вызывается каждое воскресенье в 20:00 из scheduler.
    """
    from ai.client import get_client
    from config import MODEL
    from db.queries.training_plan import (
        save_training_plan, get_next_week_start, make_plan_id,
        get_archived_plans,
    )
    from db.queries.memory import (
        get_l0_surface, get_l1_deep_bio,
        get_l2_brief, get_l3_deep, get_l4_intelligence,
    )
    from db.queries.workouts import get_weekly_stats, get_streak, get_metrics_range
    from db.queries.exercises import get_recent_records
    from db.queries.fitness_metrics import get_fitness_score, get_fitness_level

    user = get_user(telegram_id)
    if not user or not user["active"]:
        return

    week_start = get_next_week_start()
    week_end = (
        datetime.date.fromisoformat(week_start) + datetime.timedelta(days=6)
    ).isoformat()

    # ── Собираем данные ────────────────────────────────────────────────────
    surface  = get_l0_surface(uid)  or {}
    bio      = get_l1_deep_bio(uid) or {}
    l2       = get_l2_brief(uid)    or {}
    l3       = get_l3_deep(uid)     or {}
    l4       = get_l4_intelligence(uid) or {}
    streak   = get_streak(uid)
    weekly   = get_weekly_stats(uid)
    metrics  = get_metrics_range(uid, days=7)

    fs = get_fitness_score(uid)
    fitness_score_str = (
        f"{fs['score']:.0f}/100 — {get_fitness_level(fs['score'])} (тест {fs['tested_at']})"
        if fs else "нет данных"
    )

    # Средние за 7 дней
    sleeps   = [m["sleep_hours"] for m in metrics if m.get("sleep_hours")]
    energies = [m["energy"]      for m in metrics if m.get("energy")]
    avg_sleep  = round(sum(sleeps)   / len(sleeps),   1) if sleeps   else None
    avg_energy = round(sum(energies) / len(energies), 1) if energies else None

    # Личные рекорды последних 30 дней
    recent_prs = get_recent_records(uid, days=30)
    prs_str = "нет новых рекордов"
    if recent_prs:
        pr_lines = []
        for pr in recent_prs[:5]:
            suffix_map = {"weight": " кг", "reps": " повт", "time": " сек"}
            suffix = suffix_map.get(pr.get("record_type", ""), "")
            improvement = f" (+{pr['improvement_pct']:.0f}%)" if pr.get("improvement_pct") else ""
            pr_lines.append(f"  🏆 {pr['exercise_name']}: {pr['record_value']}{suffix}{improvement}")
        prs_str = "\n".join(pr_lines)

    # Физические данные
    phys_parts = []
    if surface.get("age"):       phys_parts.append(f"Возраст: {surface['age']} лет")
    if surface.get("height_cm"): phys_parts.append(f"Рост: {surface['height_cm']} см")
    physical_data = "\n".join(phys_parts) if phys_parts else "нет данных"

    # Тренировочные предпочтения
    train_parts = []
    if l3.get("preferred_days"):  train_parts.append(f"Предпочтительные дни: {', '.join(l3['preferred_days'])}")
    if l3.get("preferred_time"):  train_parts.append(f"Время: {l3['preferred_time']}")
    if l3.get("avg_session_min"): train_parts.append(f"Длительность сессии: {l3['avg_session_min']} мин")
    if l3.get("current_program"): train_parts.append(f"Текущая программа: {l3['current_program']}")
    training_prefs = "\n".join(train_parts) if train_parts else "нет данных"

    # Место тренировок и оборудование
    loc_map = {"home": "дома", "gym": "в зале", "outdoor": "на улице", "flexible": "гибко"}
    training_location = loc_map.get(user.get("training_location", "flexible"), "гибко")
    equipment_list = l3.get("equipment") or []
    equipment_str = ", ".join(equipment_list) if equipment_list else "только вес тела"

    # Питание
    nut_parts = []
    if l2.get("daily_calories"): nut_parts.append(f"{l2['daily_calories']} ккал")
    if l2.get("protein_g"):      nut_parts.append(f"Б{l2['protein_g']}г")
    if l2.get("fat_g"):          nut_parts.append(f"Ж{l2['fat_g']}г")
    if l2.get("carbs_g"):        nut_parts.append(f"У{l2['carbs_g']}г")
    nutrition_data = " / ".join(nut_parts) if nut_parts else "нет данных"

    # Здоровье
    health_parts = []
    if user.get("injuries"):
        try:
            import json as _j
            inj = _j.loads(user["injuries"])
            if inj: health_parts.append(f"Травмы/ограничения: {', '.join(inj)}")
        except Exception:
            pass
    if bio.get("food_intolerances"):
        health_parts.append(f"Непереносимости: {', '.join(bio['food_intolerances'])}")
    health_data = "\n".join(health_parts) if health_parts else "нет ограничений"

    # Избегаемые упражнения
    avoided = ", ".join(l3.get("avoided_exercises") or []) or "нет"

    # История предыдущих планов (последние 3 архивных)
    past_plans = get_archived_plans(uid, limit=3)
    if past_plans:
        import json as _json_ph
        plan_history_lines = []
        for pp in past_plans:
            try:
                days_data = _json_ph.loads(pp["plan_json"])
                workout_labels = [
                    d.get("label", d.get("type", ""))
                    for d in days_data
                    if d.get("type") not in ("rest", "recovery") and d.get("label")
                ]
                labels_str = " | ".join(workout_labels[:4])
                if len(workout_labels) > 4:
                    labels_str += f" +{len(workout_labels) - 4} ещё"
            except Exception:
                labels_str = "данные недоступны"
            compl = (
                f"{pp['completion_pct']:.0f}%"
                if pp.get("completion_pct") is not None else "нет данных"
            )
            plan_history_lines.append(
                f"  Неделя {pp['week_start']}: [{labels_str}] — выполнено {compl}"
            )
        plan_history = "\n".join(plan_history_lines)
    else:
        plan_history = "нет архивных планов (первая неделя)"

    # Preferred days
    preferred_days = ", ".join(l3.get("preferred_days") or []) or "любые"
    session_min = l3.get("avg_session_min") or 60

    # Параметры плана — зависят от уровня
    level = user.get("fitness_level", "beginner")
    min_workouts, max_workouts = {"beginner": (3, 4), "intermediate": (4, 5), "advanced": (4, 6)}.get(level, (3, 5))

    # Сезон
    season_map = {"bulk": "набор массы", "cut": "сушка", "maintain": "поддержание", "peak": "пик формы"}
    season_str = season_map.get(surface.get("season", "maintain"), "поддержание")

    # L4 дайджест
    l4_digest = l4.get("weekly_digest") or "нет данных"
    obs = l4.get("ai_observations")
    if obs:
        l4_digest += f"\nНаблюдения: {'; '.join(obs[-2:])}"

    # ── Формируем промпт ───────────────────────────────────────────────────
    from config import PROMPTS_DIR
    import os
    prompt_path = os.path.join(PROMPTS_DIR, "training_plan.txt")
    with open(prompt_path, "r", encoding="utf-8") as f:
        template = f.read()

    prompt = template.format(
        week_start=week_start,
        week_end=week_end,
        name=user.get("name") or "атлет",
        goal=user.get("goal") or "улучшить форму",
        fitness_level=level,
        season=season_str,
        fitness_score=fitness_score_str,
        streak=streak,
        physical_data=physical_data,
        training_prefs=training_prefs,
        training_location=training_location,
        equipment=equipment_str,
        nutrition_data=nutrition_data,
        health_data=health_data,
        avg_sleep=f"{avg_sleep} ч" if avg_sleep else "нет данных",
        avg_energy=f"{avg_energy}/5" if avg_energy else "нет данных",
        recent_workouts_done=weekly.get("workouts_done", 0),
        recent_workouts_total=weekly.get("workouts_total", 0),
        recent_prs=prs_str,
        l4_digest=l4_digest,
        min_workouts=min_workouts,
        max_workouts=max_workouts,
        plan_history=plan_history,
        preferred_days=preferred_days,
        session_min=session_min,
        avoided_exercises=avoided,
    )

    try:
        client = get_client()
        response = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            system=_PLAN_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
    except Exception as e:
        logger.error(f"[PLAN] AI generation failed for uid={uid}: {e}")
        return

    plan_json_str, rationale = _parse_plan_response(raw)

    if not plan_json_str:
        logger.error(f"[PLAN] Failed to parse JSON from AI response for uid={uid}: {raw[:200]}")
        return

    # Считаем число тренировочных дней и объём
    import json as _json
    workouts_planned = 0
    volume_total = 0
    intensities = []
    try:
        days_list = _json.loads(plan_json_str)
        for day in days_list:
            if day.get("type") not in ("rest", "recovery"):
                workouts_planned += 1
                volume_total += day.get("duration_min") or 0
            for ex in (day.get("exercises") or []):
                if ex.get("rpe"):
                    intensities.append(ex["rpe"])
    except Exception:
        pass

    intensity_avg = round(sum(intensities) / len(intensities), 1) if intensities else None

    plan_id = save_training_plan(
        user_id=uid,
        week_start=week_start,
        plan_json_str=plan_json_str,
        ai_rationale=rationale,
        fitness_score_snap=fs["score"] if fs else None,
        sleep_avg_snap=avg_sleep,
        energy_avg_snap=avg_energy,
        calories_target=l2.get("daily_calories"),
        season=surface.get("season"),
        workouts_planned=workouts_planned,
        volume_total=volume_total or None,
        intensity_avg=intensity_avg,
    )

    # Отправляем план пользователю
    plan_record = {
        "plan_id": plan_id,
        "week_start": week_start,
        "plan_json": plan_json_str,
        "ai_rationale": rationale,
        "workouts_planned": workouts_planned,
        "workouts_completed": 0,
    }
    msg = _format_plan_message(plan_record)

    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=f"📅 Новый план тренировок на неделю!\n\n{msg}",
            parse_mode="Markdown",
        )
        logger.info(f"[PLAN] Sent plan_id={plan_id} to {telegram_id}")
    except Exception as e:
        logger.error(f"[PLAN] Failed to send plan to {telegram_id}: {e}")


# ─── Pre-workout Reminder (Фаза 13.5) ─────────────────────────────────────────

async def send_pre_workout_reminder(bot: Bot, telegram_id: int) -> None:
    """
    Напоминание перед тренировкой: показывает упражнения на сегодня из активного плана.
    Отправляется только если:
    1. У пользователя есть активный план с тренировкой на сегодня
    2. Тренировка ещё не отмечена как завершённая
    """
    import json as _json
    from db.queries.training_plan import get_active_plan

    user = get_user(telegram_id)
    if not user or not user["active"]:
        return
    if _should_silence(user):
        return

    plan = get_active_plan(user["id"])
    if not plan:
        return

    try:
        days_list = _json.loads(plan["plan_json"])
    except Exception:
        return

    today_str = datetime.date.today().isoformat()
    today_day = None
    for day in days_list:
        if day.get("date") == today_str:
            today_day = day
            break

    if not today_day:
        return

    # Только тренировочные дни (не rest/recovery)
    dtype = today_day.get("type", "rest")
    if dtype in ("rest", "recovery"):
        return

    # Не отправляем если уже выполнена
    if today_day.get("completed"):
        return

    label = today_day.get("label", dtype)
    exercises = today_day.get("exercises") or []

    type_icons = {
        "strength": "💪", "cardio": "🏃", "hiit": "⚡",
        "mobility": "🧘",
    }
    icon = type_icons.get(dtype, "🏋️")

    lines = [f"⏰ *Сегодня тренировка!*\n{icon} *{label}*\n"]

    if exercises:
        for ex in exercises[:5]:
            name = ex.get("name", "")
            sets = ex.get("sets")
            reps = ex.get("reps")
            weight = ex.get("weight_kg_target")
            note = ex.get("note", "")
            parts = [f"• {name}"]
            if sets and reps:
                parts.append(f"{sets}×{reps}")
            if weight:
                parts.append(f"@ {weight} кг")
            if note:
                parts.append(f"_{note}_")
            lines.append(" ".join(parts))
        if len(exercises) > 5:
            lines.append(f"• … ещё {len(exercises) - 5} упражнений")

    ai_note = today_day.get("ai_note", "")
    if ai_note:
        lines.append(f"\n💬 _{ai_note}_")

    # Прогноз тренировки + адаптивная модификация
    adaptation = None
    use_adapt_keyboard = False
    try:
        from scheduler.prediction import build_workout_prediction, format_prediction_block
        from scheduler.adaptation import (
            compute_session_adaptation,
            apply_adaptation_to_prediction,
            format_adaptation_block,
            ADAPT_NORMAL,
        )

        prediction = build_workout_prediction(user["id"])
        if prediction and prediction.get("exercises"):
            # Вычисляем адаптацию на основе recovery + сон + энергия + мезоцикл
            recovery_score = None
            if prediction.get("recovery"):
                recovery_score = prediction["recovery"].get("score")

            adaptation = compute_session_adaptation(
                recovery_score=recovery_score,
                sleep=prediction.get("sleep"),
                energy=prediction.get("energy"),
                meso_phase=prediction.get("meso_phase"),
            )

            if adaptation["type"] != ADAPT_NORMAL:
                # Применяем адаптацию к прогнозу
                adapted = apply_adaptation_to_prediction(prediction, adaptation)
                adapt_block = format_adaptation_block(adapted)
                if adapt_block:
                    lines.append(adapt_block)
                    use_adapt_keyboard = True
                    logger.info(
                        f"[ADAPT] Suggested {adaptation['type']} for {telegram_id}: "
                        f"recovery={recovery_score}, sleep={prediction.get('sleep')}, "
                        f"energy={prediction.get('energy')}"
                    )
            else:
                # Без адаптации — показываем стандартный прогноз
                pred_block = format_prediction_block(prediction)
                if pred_block:
                    lines.append(pred_block)
    except Exception as pe:
        logger.debug(f"[PRE_WORKOUT] prediction/adaptation failed: {pe}")
        # Fallback: старая логика прогрессии
        try:
            from db.queries.exercises import get_exercise_last_result
            overload_lines = []
            for ex in exercises[:3]:
                name = ex.get("name", "")
                if not name:
                    continue
                target_w = ex.get("weight_kg_target")
                last = get_exercise_last_result(user["id"], name)
                if not last:
                    continue
                lw = last.get("weight_kg")
                lr = last.get("reps")
                ls = last.get("sets")
                last_str_parts = []
                if ls and lr:
                    last_str_parts.append(f"{ls}×{lr}")
                if lw:
                    last_str_parts.append(f"@ {lw} кг")
                if not last_str_parts:
                    continue
                hint = ""
                if lw and target_w and lw >= float(target_w):
                    hint = f" → {round(lw + 2.5, 1)} кг 💪"
                elif lw and target_w:
                    hint = f" → цель {target_w} кг"
                elif lr:
                    hint = f" → +1 повтор"
                if hint:
                    overload_lines.append(f"  _{name}: {' '.join(last_str_parts)}{hint}_")
            if overload_lines:
                lines.append("\n📈 *Прогрессия:*\n" + "\n".join(overload_lines))
        except Exception as oe:
            logger.debug(f"[PRE_WORKOUT] overload hints fallback failed: {oe}")

    lines.append("\nНапиши мне когда закончишь 💪")
    text = "\n".join(lines)

    try:
        if use_adapt_keyboard and adaptation:
            from bot.keyboards import kb_session_adapt
            reply_markup = kb_session_adapt(adaptation["type"])
        else:
            from bot.keyboards import kb_workout_done as kb_wf_done
            reply_markup = kb_wf_done()

        await bot.send_message(
            chat_id=telegram_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )
        logger.info(f"[PRE_WORKOUT] Reminder sent to {telegram_id} for {label}")
    except Exception as e:
        logger.error(f"[PRE_WORKOUT] Failed for {telegram_id}: {e}")


async def broadcast_pre_workout_morning(bot: Bot) -> None:
    """Утреннее напоминание: только morning + flexible тренеры."""
    from db.queries.memory import get_l3_brief
    users = _get_all_active_users()
    logger.info(f"[PRE_WORKOUT] Morning broadcast for {len(users)} users")
    for user in users:
        if _should_silence(user):
            continue
        try:
            l3 = get_l3_brief(user["id"]) or {}
            pref = l3.get("preferred_time", "flexible")
            if pref in ("morning", "flexible"):
                await send_pre_workout_reminder(bot, user["telegram_id"])
        except Exception as e:
            logger.error(f"[PRE_WORKOUT] Morning failed for {user['telegram_id']}: {e}")


async def broadcast_pre_workout_evening(bot: Bot) -> None:
    """Вечернее напоминание: только evening тренеры."""
    from db.queries.memory import get_l3_brief
    users = _get_all_active_users()
    logger.info(f"[PRE_WORKOUT] Evening broadcast for {len(users)} users")
    for user in users:
        if _should_silence(user):
            continue
        try:
            l3 = get_l3_brief(user["id"]) or {}
            pref = l3.get("preferred_time", "flexible")
            if pref == "evening":
                await send_pre_workout_reminder(bot, user["telegram_id"])
        except Exception as e:
            logger.error(f"[PRE_WORKOUT] Evening failed for {user['telegram_id']}: {e}")


async def broadcast_plan_archive(bot) -> None:
    """
    Воскресенье 19:00 — архивация активных планов всех пользователей.
    Должна запускаться ДО генерации нового плана.
    """
    users = _get_all_active_users()
    logger.info(f"[PLAN] Archiving plans for {len(users)} users")
    for user in users:
        try:
            await archive_weekly_plan_for_user(user["id"])
        except Exception as e:
            logger.error(f"[PLAN] Archive failed for uid={user['id']}: {e}")
    logger.info("[PLAN] Archive broadcast complete")


async def broadcast_plan_generate(bot) -> None:
    """
    Воскресенье 20:00 — генерация нового плана для всех активных пользователей.
    Запускается через час после архивации.
    """
    users = _get_all_active_users()
    logger.info(f"[PLAN] Generating plans for {len(users)} users")
    for user in users:
        if _should_silence(user):
            continue
        try:
            await generate_weekly_plan_for_user(user["id"], user["telegram_id"], bot)
        except Exception as e:
            logger.error(f"[PLAN] Generate failed for {user['telegram_id']}: {e}")
    logger.info("[PLAN] Generate broadcast complete")


# ─── Streak Protection (Фаза 16.4) ────────────────────────────────────────────

async def broadcast_streak_protection(bot: Bot) -> None:
    """
    Ежедневно в 20:00: проверяет streak каждого активного пользователя.
    Если стрик >= 3 дней И сегодня тренировка не записана — отправляет предупреждение.
    Цель: не дать сломать стрик из-за забывчивости.
    """
    users = _get_all_active_users()
    today = datetime.date.today().isoformat()
    sent = 0

    for user in users:
        if _should_silence(user):
            continue
        try:
            uid = user["id"]
            streak = get_streak(uid)

            # Меньше 3 дней стрика — не беспокоим
            if streak < 3:
                continue

            # Проверяем: есть ли завершённая тренировка сегодня
            from db.connection import get_connection as _gc
            conn = _gc()
            done_today = conn.execute(
                "SELECT COUNT(*) as cnt FROM workouts WHERE user_id = ? AND date = ? AND completed = 1",
                (uid, today),
            ).fetchone()

            if done_today and done_today["cnt"] > 0:
                continue   # тренировка уже есть, всё хорошо

            msg = (
                f"🔥 *Стрик {streak} дней под угрозой!*\n\n"
                f"Ты тренировался {streak} дней подряд — не ломай цепочку сегодня!\n"
                f"Даже короткая тренировка засчитается. 💪\n\n"
                f"_Осталось несколько часов — успеешь!_"
            )
            await bot.send_message(
                chat_id=user["telegram_id"],
                text=msg,
                parse_mode="Markdown",
            )
            sent += 1
            logger.info(f"[STREAK] Protection alert sent to {user['telegram_id']} (streak={streak})")

        except Exception as e:
            logger.error(f"[STREAK] Failed for {user['telegram_id']}: {e}")

    logger.info(f"[STREAK] Protection broadcast complete, {sent} alerts sent")
