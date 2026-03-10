"""
bot/commands.py — Обработчики команд /start /stop /stats /mode /help /reset /export /test
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
from db.queries.memory import get_l0_surface, get_l2_brief, get_l3_brief
from db.queries.fitness_metrics import (
    get_last_fitness_test, days_since_last_test, get_fitness_level,
)
from db.queries.training_plan import get_active_plan, get_last_plan
from config import get_trainer_mode, TEST_COOLDOWN_DAYS
from bot.keyboards import kb_goal, kb_fitness_level

logger = logging.getLogger(__name__)

HELP_TEXT = """
🤖 *Персональный тренер*

Команды:
/start — начать или возобновить
/stop — поставить на паузу
/profile — твой профиль и данные
/stats — статистика за неделю
/test — фитнес-тест (отжимания, приседания, планка)
/plan — план тренировок на эту неделю
/mode — текущий режим (MAX/LIGHT)
/export — скачать историю тренировок CSV
/help — эта справка
/reset — сбросить все данные ⚠️

Просто пиши мне — я отвечу как тренер.
Каждое утро, день и вечер я буду напоминать о тренировке.
Новый план генерируется каждое воскресенье в 20:00.
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
    """
    /stop          — пауза бессрочно
    /stop 3        — пауза на 3 дня, автовозобновление через APScheduler
    /stop 7d / 7д  — пауза на 7 дней
    """
    tg = update.effective_user
    user = get_user(tg.id)
    if not user:
        await update.message.reply_text("Тебя ещё нет в базе. Напиши /start")
        return

    # ── Парсим аргумент (кол-во дней) ────────────────────────────────────────
    args = ctx.args  # список аргументов после /stop
    days = None
    if args:
        raw = args[0].lower().replace("д", "").replace("d", "").strip()
        try:
            days = int(raw)
            if not (1 <= days <= 365):
                days = None
        except ValueError:
            days = None

    deactivate_user(tg.id)

    if days:
        # ── Ставим задачу на автовозобновление ───────────────────────────────
        resume_at = datetime.datetime.now() + datetime.timedelta(days=days)
        scheduler = ctx.bot_data.get("scheduler")
        if scheduler:
            from db.queries.user import activate_user as _activate
            async def _resume_user(bot, telegram_id: int) -> None:
                _activate(telegram_id)
                try:
                    await bot.send_message(
                        chat_id=telegram_id,
                        text=f"⏰ Пауза закончилась! Возобновляю работу.\n"
                             f"Как ты? Готов продолжать? /start",
                    )
                except Exception:
                    pass

            scheduler.add_job(
                _resume_user,
                "date",
                run_date=resume_at,
                args=[update.message.get_bot(), tg.id],
                id=f"resume_{tg.id}",
                replace_existing=True,
            )
            resume_str = resume_at.strftime("%d.%m.%Y")
            await update.message.reply_text(
                f"Поставил на паузу на {days} дн. 🛑\n"
                f"Автоматически вернусь {resume_str}.\n"
                f"Если раньше — /start"
            )
        else:
            # scheduler недоступен — просто ставим паузу бессрочно
            await update.message.reply_text(
                f"Поставил на паузу. 🛑 (авто-возврат через {days} дн. недоступен)\n"
                "Когда будешь готов — /start"
            )
    else:
        await update.message.reply_text(
            "Поставил на паузу. 🛑\n"
            "Напомнить не буду. Когда будешь готов — /start\n\n"
            "_Совет: /stop 7 — пауза на 7 дней с авто-возобновлением_",
            parse_mode="Markdown"
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


async def cmd_profile(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает профиль пользователя со всеми известными данными."""
    tg = update.effective_user
    user = get_user(tg.id)
    if not user:
        await update.message.reply_text("Нет данных. Напиши /start")
        return

    surface   = get_l0_surface(user["id"])
    training  = get_l3_brief(user["id"])
    nutrition = get_l2_brief(user["id"])
    streak    = get_streak(user["id"])

    # Последний известный вес из метрик
    metrics = get_metrics_range(user["id"], days=90)
    latest_weight = latest_weight_date = None
    for m in metrics:
        if m.get("weight_kg"):
            latest_weight      = m["weight_kg"]
            latest_weight_date = m["date"]
            break

    goal_map = {
        "похудеть":     "🔥 Похудеть",
        "набрать массу": "💪 Набрать массу",
        "выносливость": "🏃 Выносливость",
        "общая форма":  "🧘 Общая форма",
    }
    level_map = {
        "beginner":     "Начинающий 🌱",
        "intermediate": "Средний 🏋️",
        "advanced":     "Продвинутый 🔥",
    }
    season_map = {
        "bulk":     "Набор массы 💪",
        "cut":      "Сушка 🔥",
        "maintain": "Поддержание ⚖️",
        "peak":     "Пик формы 🏆",
    }
    time_map = {
        "morning":  "Утром 🌅",
        "evening":  "Вечером 🌙",
        "flexible": "Гибко ⏰",
    }
    location_map = {
        "home":     "Дома 🏠",
        "gym":      "В зале 🏋️",
        "outdoor":  "На улице 🌳",
        "flexible": "По-разному 🔄",
    }

    goal_label  = goal_map.get(user.get("goal", ""), user.get("goal") or "не указана")
    level_label = level_map.get(user.get("fitness_level", "beginner"), "Начинающий 🌱")
    streak_icon = "🔥" if streak > 0 else "💤"

    lines = [
        f"👤 *Профиль {user.get('name') or tg.first_name}*",
        "━━━━━━━━━━━━━━━━━",
        f"🎯 Цель: {goal_label}",
        f"📊 Уровень: {level_label}",
        f"{streak_icon} Стрик: {streak} дн.",
        "━━━━━━━━━━━━━━━━━",
        "📋 *Физические данные:*",
    ]

    lines.append(f"• Возраст: {surface['age']} лет"       if surface.get("age")       else "• Возраст: не указан")
    lines.append(f"• Рост: {int(surface['height_cm'])} см" if surface.get("height_cm") else "• Рост: не указан")
    if latest_weight:
        lines.append(f"• Вес: {latest_weight} кг  _{latest_weight_date}_")
    else:
        lines.append("• Вес: не указан")

    # ── Травмы / ограничения ──────────────────────────────────────────────────
    if user.get("injuries"):
        try:
            import json
            inj_list = json.loads(user["injuries"])
            if inj_list:
                lines.append(f"• Ограничения: {', '.join(inj_list)}")
        except Exception:
            pass

    lines += [
        "━━━━━━━━━━━━━━━━━",
        "🏋️ *Тренировки:*",
        f"• Время: {time_map.get(training.get('preferred_time', 'flexible'), 'Гибко ⏰')}",
        f"• Место: {location_map.get(user.get('training_location', 'flexible'), 'По-разному 🔄')}",
        f"• Сезон: {season_map.get(surface.get('season', 'maintain'), 'Поддержание ⚖️')}",
    ]
    if training.get("current_program"):
        lines.append(f"• Программа: {training['current_program']}")

    # ── Питание ───────────────────────────────────────────────────────────────
    if nutrition and nutrition.get("daily_calories"):
        lines += [
            "━━━━━━━━━━━━━━━━━",
            "🥗 *Питание (цель КБЖУ):*",
            f"• {nutrition['daily_calories']} ккал / "
            f"Б{nutrition.get('protein_g', '?')}г / "
            f"Ж{nutrition.get('fat_g', '?')}г / "
            f"У{nutrition.get('carbs_g', '?')}г",
        ]

    lines += [
        "━━━━━━━━━━━━━━━━━",
        "✏️ _Обнови данные — просто напиши мне._",
    ]

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_test(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /test — запуск пошагового фитнес-теста.
    Протокол: отжимания → приседания → планка → ЧСС (опц.)
    Нормализация по ACSM / NSCA / Cooper Institute.
    """
    tg = update.effective_user
    user = get_user(tg.id)
    if not user:
        await update.message.reply_text("Напиши /start чтобы начать.")
        return
    if not user["active"]:
        await update.message.reply_text("Ты на паузе. Напиши /start чтобы вернуться.")
        return

    # ── Cooldown: предупреждение, не блокировка ──────────────────────────────
    days = days_since_last_test(user["id"])
    if days is not None and days < TEST_COOLDOWN_DAYS:
        last = get_last_fitness_test(user["id"])
        last_score = last["fitness_score"] if last else "?"
        await update.message.reply_text(
            f"⚠️ Последний тест был {days} дн. назад "
            f"(score: {last_score}/100).\n"
            f"Рекомендуется тестироваться не чаще раза в {TEST_COOLDOWN_DAYS} дней "
            f"для объективной оценки прогресса.\n\n"
            f"Всё равно пройти тест? Напиши число отжиманий ниже, "
            f"или /cancel для отмены."
        )

    # ── Запускаем state machine ──────────────────────────────────────────────
    ctx.user_data["test_step"] = "pushups"
    ctx.user_data["test_data"] = {}

    if days is None or days >= TEST_COOLDOWN_DAYS:
        await update.message.reply_text(
            "🏋️ *Фитнес-тест — Протокол оценки формы*\n\n"
            "Тест из 3 упражнений, оценка по стандартам ACSM.\n"
            "Каждое упражнение — до полного отказа, без пауз.\n\n"
            "━━━━━━━━━━━━━━━━━\n"
            "*Тест 1/3 — Отжимания*\n"
            "Выполни максимальное количество отжиманий\n"
            "в одном подходе без остановки.\n\n"
            "_Напиши результат числом._",
            parse_mode="Markdown",
        )


async def cmd_plan(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /plan — показывает активный тренировочный план на текущую неделю.
    Если активного нет — показывает последний архивный или сообщение об отсутствии.
    """
    tg = update.effective_user
    user = get_user(tg.id)
    if not user:
        await update.message.reply_text("Нет данных. Напиши /start")
        return

    # Ищем активный план
    plan = get_active_plan(user["id"])
    if plan is None:
        plan = get_last_plan(user["id"])

    if plan is None:
        await update.message.reply_text(
            "📋 Плана пока нет.\n\n"
            "Новый план генерируется каждое *воскресенье в 20:00* автоматически.\n"
            "Хочешь — попроси меня составить план прямо сейчас: "
            "напиши «составь план тренировок на неделю».",
            parse_mode="Markdown",
        )
        return

    from scheduler.logic import _format_plan_message
    msg = _format_plan_message(plan)
    status = plan.get("status", "active")
    prefix = "" if status == "active" else "📦 _Архивный план_\n\n"

    await update.message.reply_text(
        f"{prefix}{msg}",
        parse_mode="Markdown",
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
