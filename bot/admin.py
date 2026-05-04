"""
bot/admin.py — Административная панель (Фаза 8.5).

Доступ: только ADMIN_USER_ID из .env.
Возможности:
  • Список активных пользователей со стриком и датой последней активности
  • Статус всех APScheduler задач (next_run_time)
  • Рассылка произвольного сообщения всем активным пользователям
  • Ручной запуск задач: morning/evening/daily/weekly/nudges/monthly
"""
import logging
import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from config import ADMIN_USER_ID
from db.queries.user import get_all_active_users
from db.queries.workouts import get_streak
from bot.keyboards import kb_admin_main, kb_admin_triggers, kb_admin_back

logger = logging.getLogger(__name__)

# Читаемые названия задач
_JOB_LABELS = {
    "morning_checkin":   "🌅 Утренний чек-ин",
    "afternoon_checkin": "☀️ Дневной чек-ин",
    "evening_checkin":   "🌙 Вечерний чек-ин",
    "reminder_checker":  "⏰ Напоминания",
    "daily_summary":     "📊 Дневная сводка",
    "weekly_report":     "📈 Недельный отчёт",
    "l4_intelligence":   "🧠 L4 Intelligence",
    "monthly_summary":   "📅 Месячный отчёт",
    "monthly_backup":    "💾 Бэкап",
    "plan_archive":      "📦 Архив плана",
    "plan_generate":     "🗓 Генерация плана",
    "nudge_checker":     "🔔 Нудж-проверка",
}


# ═══════════════════════════════════════════════════════════════════════════════
# ПРОВЕРКА ПРАВ
# ═══════════════════════════════════════════════════════════════════════════════

def _is_admin(telegram_id: int) -> bool:
    """Возвращает True, если пользователь является администратором."""
    return ADMIN_USER_ID != 0 and telegram_id == ADMIN_USER_ID


# ═══════════════════════════════════════════════════════════════════════════════
# ТЕКСТОВЫЕ БЛОКИ
# ═══════════════════════════════════════════════════════════════════════════════

def _build_overview_text() -> str:
    """Заголовок главного меню с быстрой статистикой."""
    users = get_all_active_users()
    active_count = len(users)
    today = datetime.date.today().isoformat()
    active_today = sum(1 for u in users if u.get("last_active") == today)

    # Суммарные расходы за сегодня
    cost_today_str = ""
    try:
        from db.queries.usage import get_global_usage_stats
        g = get_global_usage_stats(since_days=1)
        cost_today_str = f"💰 Расходы сегодня: *${g['total_cost']:.4f}*\n"
    except Exception:
        pass

    return (
        "🛠 *Панель администратора*\n\n"
        f"👥 Активных пользователей: *{active_count}*\n"
        f"🟢 Активны сегодня: *{active_today}*\n"
        f"{cost_today_str}"
        "\nВыбери действие:"
    )


def _build_costs_text() -> str:
    """Расходы AI по всем пользователям за 30 дней."""
    try:
        from db.queries.usage import get_all_users_usage, get_global_usage_stats

        global_30 = get_global_usage_stats(since_days=30)
        global_7  = get_global_usage_stats(since_days=7)
        global_1  = get_global_usage_stats(since_days=1)

        lines = [
            "💰 *Расходы Anthropic API*\n",
            f"Сегодня:    `${global_1['total_cost']:.4f}`  ({global_1['total_calls']} зап.)",
            f"7 дней:     `${global_7['total_cost']:.4f}`  ({global_7['total_calls']} зап.)",
            f"30 дней:    `${global_30['total_cost']:.4f}`  ({global_30['total_calls']} зап.)",
            "━━━━━━━━━━━━━━━━━",
            f"*По пользователям (30 дн.):*",
        ]

        users = get_all_users_usage(since_days=30)
        if users:
            for u in users[:15]:
                name  = u.get("name") or f"id{u.get('telegram_id', '?')}"
                cost  = u.get("total_cost", 0)
                calls = u.get("total_calls", 0)
                if calls == 0:
                    lines.append(f"  💤 {name}: —")
                else:
                    lines.append(f"  👤 *{name}*: `${cost:.4f}` ({calls} зап.)")
            if len(users) > 15:
                lines.append(f"\n_…и ещё {len(users) - 15}_")
        else:
            lines.append("_Данных пока нет_")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"[Admin] _build_costs_text error: {e}")
        return "💰 *Расходы*\n\nОшибка при загрузке данных."


def _build_users_text() -> str:
    """Список активных пользователей."""
    users = get_all_active_users()
    if not users:
        return "👥 *Пользователи*\n\nАктивных пользователей нет."

    lines = [f"👥 *Пользователи* ({len(users)} чел.)\n"]
    for u in users[:30]:  # Лимит 30 — иначе сообщение слишком длинное
        name    = u.get("name") or f"id{u['id']}"
        streak  = get_streak(u["id"])
        last    = u.get("last_active") or "—"
        fire    = "🔥" if streak >= 3 else ("✅" if streak > 0 else "💤")
        lines.append(f"{fire} *{name}* — стрик {streak} дн., был {last}")

    if len(users) > 30:
        lines.append(f"\n_…и ещё {len(users) - 30} пользователей_")
    return "\n".join(lines)


def _build_jobs_text(ctx: ContextTypes.DEFAULT_TYPE) -> str:
    """Статус APScheduler задач."""
    scheduler = ctx.bot_data.get("scheduler")
    if not scheduler:
        return "⚙️ *Задачи*\n\nScheduler недоступен."

    jobs = scheduler.get_jobs()
    if not jobs:
        return "⚙️ *Задачи*\n\nЗадач нет."

    lines = [f"⚙️ *Задачи* ({len(jobs)} шт.)\n"]
    now = datetime.datetime.now()
    for job in sorted(jobs, key=lambda j: j.next_run_time or datetime.datetime.max):
        label = _JOB_LABELS.get(job.id, job.id)
        if job.next_run_time:
            delta = job.next_run_time.replace(tzinfo=None) - now
            total_secs = int(delta.total_seconds())
            if total_secs < 0:
                when = "запущена"
            elif total_secs < 3600:
                when = f"через {total_secs // 60} мин"
            elif total_secs < 86400:
                when = f"через {total_secs // 3600} ч"
            else:
                when = job.next_run_time.strftime("%d.%m %H:%M")
        else:
            when = "—"
        lines.append(f"• {label}: _{when}_")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# ОСНОВНОЙ ОБРАБОТЧИК
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Точка входа — команда /admin."""
    tg = update.effective_user
    if not _is_admin(tg.id):
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    text = _build_overview_text()
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb_admin_main())


async def handle_admin_callback(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE, data: str
) -> None:
    """
    Диспетчер admin callback'ов.
    data — строка после 'adm:' (например 'users', 'jobs', 'trigger:daily').
    """
    query = update.callback_query
    tg = query.from_user

    if not _is_admin(tg.id):
        await query.answer("⛔ Доступ запрещён.", show_alert=True)
        return

    # ── Главное меню ───────────────────────────────────────────────────────────
    if data == "home":
        text = _build_overview_text()
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb_admin_main())
        return

    # ── Расходы AI ────────────────────────────────────────────────────────────
    if data == "costs":
        text = _build_costs_text()
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb_admin_back())
        return

    # ── Список пользователей ───────────────────────────────────────────────────
    if data == "users":
        text = _build_users_text()
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb_admin_back())
        return

    # ── Статус задач ───────────────────────────────────────────────────────────
    if data == "jobs":
        text = _build_jobs_text(ctx)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb_admin_back())
        return

    # ── Рассылка — приглашение ввести текст ───────────────────────────────────
    if data == "broadcast":
        ctx.user_data["admin_broadcast_pending"] = "awaiting_text"
        await query.edit_message_text(
            "📢 *Рассылка*\n\n"
            "Напиши текст сообщения. После ввода покажу превью с кнопкой подтверждения.\n\n"
            "_Для отмены напиши /cancel_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✖ Отмена", callback_data="adm:home")
            ]])
        )
        return

    # ── Подтверждение рассылки (после preview) ───────────────────────────────
    if data == "bcast:yes":
        await _broadcast_send_confirmed(query, ctx)
        return

    if data == "bcast:no":
        ctx.user_data.pop("admin_broadcast_pending", None)
        ctx.user_data.pop("admin_broadcast_text", None)
        text = _build_overview_text()
        await query.edit_message_text(
            "Рассылка отменена.\n\n" + text,
            parse_mode="Markdown",
            reply_markup=kb_admin_main(),
        )
        return

    # ── Отмена рассылки через кнопку ──────────────────────────────────────────
    if data == "broadcast_cancel":
        ctx.user_data.pop("admin_broadcast_pending", None)
        ctx.user_data.pop("admin_broadcast_text", None)
        text = _build_overview_text()
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb_admin_main())
        return

    # ── Подменю триггеров ─────────────────────────────────────────────────────
    if data == "trigger":
        await query.edit_message_text(
            "⚡ *Ручной запуск задач*\n\nВыбери что запустить:",
            parse_mode="Markdown",
            reply_markup=kb_admin_triggers()
        )
        return

    # ── Запуск конкретной задачи ──────────────────────────────────────────────
    if data.startswith("trigger:"):
        task = data.split(":", 1)[1]
        await _run_trigger(query, ctx, task)
        return

    # Неизвестный callback
    await query.answer("Неизвестное действие.")


# ═══════════════════════════════════════════════════════════════════════════════
# РАССЫЛКА
# ═══════════════════════════════════════════════════════════════════════════════

async def handle_admin_broadcast(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> None:
    """Шаг 1: получили текст рассылки от админа → показать preview с подтверждением.

    Реальная рассылка идёт из _broadcast_send_confirmed() после клика [Отправить].
    """
    text = update.message.text.strip()

    if text.lower() in ("/cancel", "cancel", "отмена"):
        ctx.user_data.pop("admin_broadcast_pending", None)
        ctx.user_data.pop("admin_broadcast_text", None)
        await update.message.reply_text("Рассылка отменена.")
        return

    if not text:
        await update.message.reply_text(
            "Текст пустой. Напиши сообщение или /cancel."
        )
        return

    users = get_all_active_users()
    ctx.user_data["admin_broadcast_text"] = text
    ctx.user_data["admin_broadcast_pending"] = "awaiting_confirm"

    preview = (
        f"📢 *Превью рассылки*\n\n"
        f"Получателей: *{len(users)}*\n"
        f"━━━━━━━━━━━━━━━━━\n\n"
        f"{text}\n\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"Отправить?"
    )
    await update.message.reply_text(
        preview,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Отправить", callback_data="adm:bcast:yes"),
                InlineKeyboardButton("✖ Отмена",     callback_data="adm:bcast:no"),
            ]
        ]),
    )


async def _broadcast_send_confirmed(query, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Шаг 2: админ нажал [Отправить] — запустить реальную рассылку."""
    text = ctx.user_data.get("admin_broadcast_text")
    if not text:
        await query.edit_message_text(
            "Текст рассылки потерян. Начни заново через /admin → Рассылка.",
            reply_markup=kb_admin_main(),
        )
        ctx.user_data.pop("admin_broadcast_pending", None)
        return

    users = get_all_active_users()
    bot = query.message.get_bot()
    await query.edit_message_text(
        f"📢 Отправляю рассылку ({len(users)} получ.)…",
        parse_mode="Markdown",
    )

    sent = failed = 0
    for u in users:
        try:
            await bot.send_message(chat_id=u["telegram_id"], text=text)
            sent += 1
        except Exception as e:
            logger.warning(f"[Broadcast] Failed to send to {u['telegram_id']}: {e}")
            failed += 1

    ctx.user_data.pop("admin_broadcast_pending", None)
    ctx.user_data.pop("admin_broadcast_text", None)
    await query.message.reply_text(
        f"📢 Рассылка завершена.\n\n"
        f"✅ Отправлено: {sent}\n"
        f"❌ Ошибок: {failed}",
        reply_markup=kb_admin_main(),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# РУЧНОЙ ЗАПУСК ЗАДАЧ
# ═══════════════════════════════════════════════════════════════════════════════

_TRIGGER_LABELS = {
    "morning":            "🌅 Утренний чек-ин",
    "evening":            "🌙 Вечерний чек-ин",
    "daily":              "📊 Дневная сводка",
    "weekly":             "📈 Недельная сводка",
    "nudges":             "🔔 Нудж-проверка",
    "monthly":            "📅 Месячный отчёт",
    "nutrition_analysis": "🥗 Анализ питания",
    "plan_archive":       "📦 Архив плана",
    "plan_generate":      "🗓 Генерация плана",
}


async def _run_trigger(query, ctx: ContextTypes.DEFAULT_TYPE, task: str) -> None:
    """Запускает задачу вручную и отвечает результатом."""
    label = _TRIGGER_LABELS.get(task, task)
    bot = ctx.bot

    await query.answer(f"Запускаю: {label}…")

    try:
        if task == "morning":
            from scheduler.logic import broadcast_morning
            await broadcast_morning(bot)

        elif task == "evening":
            from scheduler.logic import broadcast_evening
            await broadcast_evening(bot)

        elif task == "daily":
            from scheduler.logic import broadcast_daily_summary
            await broadcast_daily_summary()

        elif task == "weekly":
            from scheduler.logic import broadcast_weekly
            await broadcast_weekly(bot)

        elif task == "nudges":
            from scheduler.nudges import check_and_send_nudges
            await check_and_send_nudges(bot)

        elif task == "monthly":
            from scheduler.logic import broadcast_monthly_summary
            await broadcast_monthly_summary()

        elif task == "nutrition_analysis":
            from scheduler.nutrition_analysis import run_nutrition_analysis
            await run_nutrition_analysis(bot)

        elif task == "plan_archive":
            from scheduler.logic import broadcast_plan_archive
            await broadcast_plan_archive(bot)

        elif task == "plan_generate":
            from scheduler.logic import broadcast_plan_generate
            await broadcast_plan_generate(bot)

        else:
            await query.edit_message_text(
                f"⚠️ Неизвестная задача: `{task}`",
                parse_mode="Markdown",
                reply_markup=kb_admin_back()
            )
            return

        await query.edit_message_text(
            f"✅ *{label}* — запущена успешно.\n\n"
            "_Результаты разосланы пользователям (если были получатели)._",
            parse_mode="Markdown",
            reply_markup=kb_admin_back()
        )
        logger.info(f"[Admin] Manual trigger '{task}' executed successfully.")

    except Exception as e:
        logger.error(f"[Admin] Trigger '{task}' failed: {e}")
        await query.edit_message_text(
            f"❌ Ошибка при запуске *{label}*:\n`{e}`",
            parse_mode="Markdown",
            reply_markup=kb_admin_back()
        )
