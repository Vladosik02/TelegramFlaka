"""
scheduler/logic.py — Логика плановых сообщений (без APScheduler деталей).
"""
import logging
import datetime
import random
from telegram import Bot
from telegram.ext import Application

from db.queries.user import get_user
from db.queries.context import get_or_create_checkin, update_checkin, get_pending_reminders, mark_reminder_sent
from db.queries.stats import save_weekly_summary
from db.queries.workouts import get_weekly_stats, get_streak, get_workouts_range, get_metrics_range
from ai.context_builder import (
    build_morning_context, build_afternoon_context,
    build_evening_context, build_weekly_report_context
)
from ai.client import generate_scheduled_message
from db.writer import save_ai_response
from db.queries.memory import upsert_intelligence, append_observation
from bot.keyboards import kb_morning_ready, kb_workout_done, kb_evening_confirm, kb_reminder
from config import (
    SCHEDULE_LIGHT_MORNING_WINDOW, SCHEDULE_LIGHT_AFTERNOON_WINDOW,
    SILENCE_AFTER_DAYS, SOFT_START_DAYS
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


async def send_morning_checkin(bot: Bot, telegram_id: int) -> None:
    user = get_user(telegram_id)
    if not user or not user["active"]:
        return
    if _should_silence(user):
        logger.info(f"Silencing {telegram_id} — inactive too long")
        return

    context = build_morning_context(telegram_id)
    if not context:
        return

    text = generate_scheduled_message(context)
    await bot.send_message(
        chat_id=telegram_id,
        text=text,
        reply_markup=kb_morning_ready()
    )
    save_ai_response(telegram_id, text)

    # Создать запись чек-ина
    today = datetime.date.today().isoformat()
    get_or_create_checkin(user["id"], today, "morning")
    logger.info(f"Morning checkin sent to {telegram_id}")


async def send_afternoon_checkin(bot: Bot, telegram_id: int) -> None:
    user = get_user(telegram_id)
    if not user or not user["active"]:
        return

    context = build_afternoon_context(telegram_id)
    if not context:
        return

    text = generate_scheduled_message(context)
    await bot.send_message(
        chat_id=telegram_id,
        text=text,
        reply_markup=kb_workout_done()
    )
    save_ai_response(telegram_id, text)

    today = datetime.date.today().isoformat()
    get_or_create_checkin(user["id"], today, "afternoon")
    logger.info(f"Afternoon checkin sent to {telegram_id}")


async def send_evening_checkin(bot: Bot, telegram_id: int) -> None:
    user = get_user(telegram_id)
    if not user or not user["active"]:
        return

    context = build_evening_context(telegram_id)
    if not context:
        return

    text = generate_scheduled_message(context)
    await bot.send_message(
        chat_id=telegram_id,
        text=text,
        reply_markup=kb_evening_confirm()
    )
    save_ai_response(telegram_id, text)

    today = datetime.date.today().isoformat()
    get_or_create_checkin(user["id"], today, "evening")
    logger.info(f"Evening checkin sent to {telegram_id}")


async def send_weekly_report(bot: Bot, telegram_id: int) -> None:
    user = get_user(telegram_id)
    if not user or not user["active"]:
        return

    context = build_weekly_report_context(telegram_id)
    if not context:
        return

    text = generate_scheduled_message(context)
    await bot.send_message(chat_id=telegram_id, text=text)
    save_ai_response(telegram_id, text)

    # Сохранить агрегат
    weekly = get_weekly_stats(user["id"])
    today = datetime.date.today()
    mon = today - datetime.timedelta(days=today.weekday())
    save_weekly_summary(user["id"], mon.isoformat(), weekly, text)
    logger.info(f"Weekly report sent to {telegram_id}")


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
    from config import MODEL

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


async def broadcast_l4_intelligence() -> None:
    """Еженедельное обновление L4 Intelligence для всех активных пользователей."""
    users = _get_all_active_users()
    logger.info(f"[L4] Starting intelligence update for {len(users)} users")
    for user in users:
        try:
            await update_l4_for_user(user["id"], user["telegram_id"])
        except Exception as e:
            logger.error(f"[L4] Broadcast failed for {user['telegram_id']}: {e}")
    logger.info("[L4] Intelligence broadcast complete")
