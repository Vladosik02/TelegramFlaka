"""
bot/commands.py — Обработчики команд /start /stop /stats /mode /help /reset /export
"""
import io
import csv
import logging
import datetime
from telegram import Update
from telegram.ext import ContextTypes

from db.queries.user import get_user, create_user, deactivate_user, activate_user
from db.queries.workouts import get_weekly_stats, get_streak, get_workouts_range, get_metrics_range
from db.queries.stats import get_all_time_stats
from config import get_trainer_mode
from bot.keyboards import kb_goal, kb_fitness_level

logger = logging.getLogger(__name__)

HELP_TEXT = """
🤖 *Персональный тренер*

Команды:
/start — начать или возобновить
/stop — поставить на паузу
/stats — статистика
/mode — текущий режим (MAX/LIGHT)
/export — скачать историю тренировок CSV
/help — эта справка
/reset — сбросить все данные ⚠️

Просто пиши мне — я отвечу как тренер.
Каждое утро, день и вечер я буду напоминать о тренировке.
"""


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    tg = update.effective_user
    user = get_user(tg.id)

    if user and user["active"]:
        await update.message.reply_text(
            f"Привет, {user['name'] or tg.first_name}! Ты уже активен. "
            f"Режим сегодня: *{get_trainer_mode()}*",
            parse_mode="Markdown"
        )
        return

    if user:
        activate_user(tg.id)
        await update.message.reply_text(
            f"С возвращением, {user['name'] or tg.first_name}! "
            f"Продолжаем. Режим: *{get_trainer_mode()}*",
            parse_mode="Markdown"
        )
        return

    # Новый пользователь — онбординг
    create_user(tg.id, name=tg.first_name)
    await update.message.reply_text(
        f"Привет, {tg.first_name}! 💪\n\n"
        "Я твой персональный тренер. Буду напоминать о тренировках, "
        "отслеживать прогресс и помогать не сдаваться.\n\n"
        "Для начала — какая у тебя *главная цель*?",
        parse_mode="Markdown",
        reply_markup=kb_goal()
    )


async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    tg = update.effective_user
    user = get_user(tg.id)
    if not user:
        await update.message.reply_text("Тебя ещё нет в базе. Напиши /start")
        return
    deactivate_user(tg.id)
    await update.message.reply_text(
        "Поставил на паузу. 🛑\n"
        "Напомнить не буду. Когда будешь готов — /start",
    )


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    tg = update.effective_user
    user = get_user(tg.id)
    if not user:
        await update.message.reply_text("Нет данных. Напиши /start")
        return

    weekly = get_weekly_stats(user["id"])
    alltime = get_all_time_stats(user["id"])
    streak = get_streak(user["id"])
    mode = get_trainer_mode()

    text = (
        f"📊 *Статистика {user['name'] or 'атлета'}*\n\n"
        f"*Эта неделя:*\n"
        f"• Тренировок: {weekly['workouts_done']}/{weekly['workouts_total']}\n"
        f"• Ср. интенсивность: {weekly['avg_intensity']}/10\n"
        f"• Всего минут: {weekly['total_minutes']}\n"
        f"• Ср. сон: {weekly['avg_sleep']} ч\n"
        f"• Ср. энергия: {weekly['avg_energy']}/5\n\n"
        f"*За всё время:*\n"
        f"• Всего тренировок: {alltime['done_workouts']}\n"
        f"• Всего минут: {alltime['total_minutes']}\n"
        f"• Стрик сейчас: 🔥 {streak} дней\n\n"
        f"Режим сегодня: *{mode}*"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    mode = get_trainer_mode()
    today = datetime.date.today()
    emoji = "🔥" if mode == "MAX" else "🌿"
    desc = (
        "Жёсткое расписание. Тренировка обязательна."
        if mode == "MAX"
        else "Мягкий режим. Активность по желанию."
    )
    await update.message.reply_text(
        f"{emoji} Сегодня *{mode}*-день ({today.strftime('%d.%m')})\n{desc}",
        parse_mode="Markdown"
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def cmd_export(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Экспорт истории тренировок и метрик в CSV."""
    tg = update.effective_user
    user = get_user(tg.id)
    if not user:
        await update.message.reply_text("Нет данных. Напиши /start")
        return

    uid = user["id"]
    workouts = get_workouts_range(uid, days=365)
    metrics  = get_metrics_range(uid, days=365)

    # ── Тренировки ────────────────────────────────────────────────────────────
    workout_buf = io.StringIO()
    w_writer = csv.writer(workout_buf)
    w_writer.writerow(["date", "type", "duration_min", "intensity", "notes"])
    for w in workouts:
        w_writer.writerow([
            w["date"] if "date" in w.keys() else "",
            w["workout_type"] if "workout_type" in w.keys() else "",
            w["duration_min"] if "duration_min" in w.keys() else "",
            w["intensity"] if "intensity" in w.keys() else "",
            (w["notes"] or "").replace("\n", " ") if "notes" in w.keys() else "",
        ])

    # ── Метрики ───────────────────────────────────────────────────────────────
    metrics_buf = io.StringIO()
    m_writer = csv.writer(metrics_buf)
    m_writer.writerow(["date", "weight_kg", "sleep_hours", "energy", "water_l", "steps"])
    for m in metrics:
        m_writer.writerow([
            m["date"] if "date" in m.keys() else "",
            m["weight_kg"] if "weight_kg" in m.keys() else "",
            m["sleep_hours"] if "sleep_hours" in m.keys() else "",
            m["energy"] if "energy" in m.keys() else "",
            m["water_l"] if "water_l" in m.keys() else "",
            m["steps"] if "steps" in m.keys() else "",
        ])

    today_str = datetime.date.today().strftime("%Y-%m-%d")
    name = (user["name"] or "user").replace(" ", "_")

    await update.message.reply_document(
        document=workout_buf.getvalue().encode("utf-8"),
        filename=f"workouts_{name}_{today_str}.csv",
        caption=f"💪 Тренировки за последний год — {len(workouts)} записей"
    )
    await update.message.reply_document(
        document=metrics_buf.getvalue().encode("utf-8"),
        filename=f"metrics_{name}_{today_str}.csv",
        caption=f"📊 Метрики за последний год — {len(metrics)} записей"
    )


async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Сброс данных — просит подтверждение."""
    await update.message.reply_text(
        "⚠️ Это удалит *все* твои данные (тренировки, статистику, историю).\n\n"
        "Напиши *УДАЛИТЬ* чтобы подтвердить, или /cancel чтобы отменить.",
        parse_mode="Markdown"
    )
    # Флаг для handler
    ctx.user_data["awaiting_reset_confirm"] = True
