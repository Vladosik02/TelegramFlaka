"""
bot/commands.py — Обработчики команд.

Фаза 11 — UI/UX: inline keyboards под всеми командами, /menu, улучшенное
форматирование карточек профиля/статистики/ачивок/истории.
"""
import io
import csv
import re
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
from db.writer import save_nutrition_from_parsed
from config import get_trainer_mode, TEST_COOLDOWN_DAYS, ADMIN_USER_ID
from bot.keyboards import (
    kb_goal, kb_fitness_level, kb_workout_time,
    kb_main_menu, kb_stats_quick, kb_profile_quick,
    kb_achievements_quick, kb_history_period, kb_plan_quick,
    kb_reset_confirm, kb_back_to_menu,
)
from lang import t

logger = logging.getLogger(__name__)


# ─── Текст помощи ─────────────────────────────────────────────────────────────
HELP_TEXT = t("help_text")
ADMIN_HELP_TEXT = "\n" + t("admin_help")


# ─── /menu — главное меню ─────────────────────────────────────────────────────

async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Главное меню — быстрый доступ ко всем функциям."""
    tg = update.effective_user
    user = get_user(tg.id)
    mode = get_trainer_mode()
    mode_emoji = "🔥" if mode == "MAX" else "🌿"
    name = (user.get("name") or tg.first_name) if user else tg.first_name

    try:
        from db.queries.gamification import get_user_level_info
        xp_info = get_user_level_info(user["id"]) if user else None
        level_str = f"  {xp_info['level_name']} · {xp_info['total_xp']} XP\n" if xp_info else ""
    except Exception:
        level_str = ""

    streak = get_streak(user["id"]) if user else 0
    streak_str = f"🔥 {streak} дней стрик\n" if streak else ""

    text = (
        t("menu_greeting", name=name)
        + t("menu_mode", mode_emoji=mode_emoji, mode=mode)
        + streak_str
        + level_str
        + t("menu_what_next")
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb_main_menu())


# ─── /start ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    tg = update.effective_user
    user = get_user(tg.id)

    # ── Сброс state machine при /start (Фаза 14.3) ───────────────────────────
    # Очищаем onboarding_step, test_step, workout_flow и прочие состояния
    for key in ("onboarding_step", "test_step", "test_data", "admin_broadcast_pending",
                "workout_flow", "awaiting_custom_duration"):
        ctx.user_data.pop(key, None)

    if user and user["active"]:
        mode = get_trainer_mode()
        mode_emoji = "🔥" if mode == "MAX" else "🌿"
        streak = get_streak(user["id"])
        streak_str = f"\n🔥 Стрик: *{streak} дней*" if streak else ""
        await update.message.reply_text(
            t("start_active", name=user['name'] or tg.first_name,
              mode_emoji=mode_emoji, mode=mode, streak_str=streak_str),
            parse_mode="Markdown",
            reply_markup=kb_main_menu(),
        )
        return

    if user:
        activate_user(tg.id)
        await update.message.reply_text(
            t("start_return", name=user['name'] or tg.first_name, mode=get_trainer_mode()),
            parse_mode="Markdown",
            reply_markup=kb_main_menu(),
        )
        return

    # Новый пользователь — онбординг
    create_user(tg.id, name=tg.first_name)
    await update.message.reply_text(
        t("start_new", name=tg.first_name),
        parse_mode="Markdown",
        reply_markup=kb_goal(),
    )


# ─── /stop ───────────────────────────────────────────────────────────────────

async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /stop          — показывает выбор паузы (inline кнопки)
    /stop 3        — пауза на 3 дня
    /stop 7d / 7д  — пауза на 7 дней
    """
    tg = update.effective_user
    user = get_user(tg.id)
    if not user:
        await update.message.reply_text("Тебя ещё нет в базе. Напиши /start")
        return

    args = ctx.args
    days = None
    if args:
        raw = args[0].lower().replace("д", "").replace("d", "").strip()
        try:
            days = int(raw)
            if not (1 <= days <= 365):
                days = None
        except ValueError:
            days = None

    if days:
        await _apply_stop(update, ctx, tg, days)
    else:
        # Показываем меню выбора паузы
        from bot.keyboards import kb_stop_quick
        await update.message.reply_text(
            t("stop_prompt"),
            parse_mode="Markdown",
            reply_markup=kb_stop_quick(),
        )


async def _apply_stop(update, ctx, tg, days: int) -> None:
    """Применяет паузу на N дней с авто-возобновлением."""
    deactivate_user(tg.id)
    resume_at = datetime.datetime.now() + datetime.timedelta(days=days)
    scheduler = ctx.bot_data.get("scheduler")

    if scheduler:
        from db.queries.user import activate_user as _activate

        async def _resume_user(bot, telegram_id: int) -> None:
            _activate(telegram_id)
            try:
                await bot.send_message(
                    chat_id=telegram_id,
                    text=t("stop_resumed"),
                )
            except Exception:
                pass

        scheduler.add_job(
            _resume_user, "date",
            run_date=resume_at,
            args=[update.message.get_bot(), tg.id],
            id=f"resume_{tg.id}",
            replace_existing=True,
        )
        resume_str = resume_at.strftime("%d.%m.%Y")
        await update.message.reply_text(
            t("stop_confirmed", days=days, resume_str=resume_str),
            parse_mode="Markdown",
            reply_markup=kb_back_to_menu(),
        )
    else:
        await update.message.reply_text(
            t("stop_confirmed_forever", days=days),
            parse_mode="Markdown",
            reply_markup=kb_back_to_menu(),
        )


# ─── /stats ──────────────────────────────────────────────────────────────────

def _build_stats_text(user: dict) -> str:
    """Собирает текст статистики для /stats и callback action='stats'.

    Вынесено в отдельную функцию чтобы не дублировать логику между
    cmd_stats (bot/commands.py) и handle_callback action='stats' (bot/handlers.py).
    """
    weekly = get_weekly_stats(user["id"])
    alltime = get_all_time_stats(user["id"])
    streak = get_streak(user["id"])
    mode = get_trainer_mode()
    mode_emoji = "🔥" if mode == "MAX" else "🌿"

    done = weekly['workouts_done']
    total = max(weekly['workouts_total'], 1)
    filled = min(10, round(done / total * 10))
    bar = "█" * filled + "░" * (10 - filled)

    return (
        t("stats_header", name=user['name'] or 'атлет')
        + "━━━━━━━━━━━━━━━━━\n"
        + t("stats_week")
        + t("stats_bar", bar=bar, done=done, total=total)
        + t("stats_intensity", val=weekly['avg_intensity'])
        + t("stats_minutes", val=weekly['total_minutes'])
        + t("stats_sleep", val=weekly['avg_sleep'])
        + t("stats_energy", val=weekly['avg_energy'])
        + "━━━━━━━━━━━━━━━━━\n"
        + t("stats_alltime")
        + t("stats_total_workouts", val=alltime['done_workouts'])
        + t("stats_total_minutes", val=alltime['total_minutes'])
        + t("stats_streak", val=streak)
        + "━━━━━━━━━━━━━━━━━\n"
        + t("stats_mode", mode_emoji=mode_emoji, mode=mode)
    )


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    tg = update.effective_user
    user = get_user(tg.id)
    if not user:
        await update.message.reply_text(t("plan_no_profile"))
        return
    text = _build_stats_text(user)
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb_stats_quick())


# ─── /mode ───────────────────────────────────────────────────────────────────

async def cmd_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    mode = get_trainer_mode()
    today = datetime.date.today()
    emoji = "🔥" if mode == "MAX" else "🌿"
    desc = t("mode_max_desc") if mode == "MAX" else t("mode_light_desc")
    next_day = today + datetime.timedelta(days=1)
    next_mode = get_trainer_mode(next_day.day)
    next_emoji = "🔥" if next_mode == "MAX" else "🌿"

    await update.message.reply_text(
        t("mode_today", emoji=emoji, mode=mode, date=today.strftime('%d.%m'))
        + f"{desc}\n\n"
        + t("mode_tomorrow", emoji=next_emoji, mode=next_mode),
        parse_mode="Markdown",
        reply_markup=kb_back_to_menu(),
    )


# ─── /help ───────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    tg = update.effective_user
    extra = ADMIN_HELP_TEXT if (ADMIN_USER_ID != 0 and tg.id == ADMIN_USER_ID) else ""
    await update.message.reply_text(
        HELP_TEXT + extra,
        parse_mode="Markdown",
        reply_markup=kb_main_menu(),
    )


# ─── /setup ──────────────────────────────────────────────────────────────────

async def cmd_setup(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Повторная настройка предпочтений."""
    tg = update.effective_user
    user = get_user(tg.id)
    if not user:
        await update.message.reply_text(t("test_no_profile"))
        return
    await update.message.reply_text(
        t("setup_prompt"),
        parse_mode="Markdown",
        reply_markup=kb_workout_time(),
    )


# ─── /meal ───────────────────────────────────────────────────────────────────

_MEAL_USAGE = t("meal_usage")


def _parse_meal_args(args_text: str) -> dict:
    result = {}
    txt = args_text.strip()

    cal = re.search(r'(\d{3,5})\s*ккал', txt, re.IGNORECASE)
    if cal:
        val = int(cal.group(1))
        if 50 <= val <= 10000:
            result["calories"] = val

    prot = re.search(r'[Бб]\s*(\d+(?:[.,]\d+)?)', txt)
    if prot:
        val = float(prot.group(1).replace(",", "."))
        if 0 <= val <= 500:
            result["protein_g"] = val

    fat = re.search(r'[Жж]\s*(\d+(?:[.,]\d+)?)', txt)
    if fat:
        val = float(fat.group(1).replace(",", "."))
        if 0 <= val <= 500:
            result["fat_g"] = val

    carbs = re.search(r'[Уу]\s*(\d+(?:[.,]\d+)?)', txt)
    if carbs:
        val = float(carbs.group(1).replace(",", "."))
        if 0 <= val <= 1000:
            result["carbs_g"] = val

    water = re.search(r'[Вв]\s*(\d+(?:[.,]\d+)?)\s*(л|мл)?', txt)
    if water:
        amount = float(water.group(1).replace(",", "."))
        unit = (water.group(2) or "мл").lower()
        ml = int(amount * 1000) if unit == "л" else int(amount)
        if 50 <= ml <= 10000:
            result["water_ml"] = ml

    name_text = re.sub(
        r'\d{3,5}\s*ккал|[БбЖжУуВв]\s*\d+(?:[.,]\d+)?(?:\s*(?:л|мл))?'
        r'|\d+\s*(?:г|кг|мл|л)',
        '', txt, flags=re.IGNORECASE
    ).strip(" /")
    name_text = re.sub(r'\s{2,}', ' ', name_text).strip()
    if name_text:
        result["meal_notes"] = name_text[:200]

    return result


async def cmd_meal(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    tg = update.effective_user
    user = get_user(tg.id)
    if not user:
        await update.message.reply_text(t("meal_no_profile"))
        return

    args_text = " ".join(ctx.args) if ctx.args else ""
    if not args_text:
        await update.message.reply_text(_MEAL_USAGE, parse_mode="Markdown")
        return

    parsed = _parse_meal_args(args_text)
    if not any(k in parsed for k in ("calories", "protein_g", "fat_g", "carbs_g")):
        await update.message.reply_text(t("meal_not_parsed") + _MEAL_USAGE, parse_mode="Markdown")
        return

    save_nutrition_from_parsed(tg.id, parsed)

    parts = []
    if "calories" in parsed:   parts.append(t("meal_kcal", val=parsed['calories']))
    if "protein_g" in parsed:  parts.append(t("meal_protein", val=int(parsed['protein_g'])))
    if "fat_g" in parsed:      parts.append(t("meal_fat", val=int(parsed['fat_g'])))
    if "carbs_g" in parsed:    parts.append(t("meal_carbs", val=int(parsed['carbs_g'])))
    if "water_ml" in parsed:   parts.append(t("meal_water", val=parsed['water_ml']))

    name_prefix = f"_{parsed['meal_notes']}_ — " if "meal_notes" in parsed else ""
    await update.message.reply_text(
        t("meal_saved", parts=name_prefix + ', '.join(parts)),
        parse_mode="Markdown",
        reply_markup=kb_back_to_menu(),
    )


# ─── /export ─────────────────────────────────────────────────────────────────

async def cmd_export(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Экспорт истории тренировок и метрик в CSV."""
    tg = update.effective_user
    user = get_user(tg.id)
    if not user:
        await update.message.reply_text(t("plan_no_profile"))
        return

    uid = user["id"]
    workouts = get_workouts_range(uid, days=365)
    metrics  = get_metrics_range(uid, days=365)

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
        caption=f"💪 Тренировки за последний год — {len(workouts)} записей",
    )
    await update.message.reply_document(
        document=metrics_buf.getvalue().encode("utf-8"),
        filename=f"metrics_{name}_{today_str}.csv",
        caption=f"📊 Метрики за последний год — {len(metrics)} записей",
    )


# ─── /profile ────────────────────────────────────────────────────────────────

async def cmd_profile(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает профиль пользователя со всеми известными данными."""
    tg = update.effective_user
    user = get_user(tg.id)
    if not user:
        await update.message.reply_text(t("plan_no_profile"))
        return

    surface   = get_l0_surface(user["id"])
    training  = get_l3_brief(user["id"])
    nutrition = get_l2_brief(user["id"])
    streak    = get_streak(user["id"])

    metrics = get_metrics_range(user["id"], days=90)
    latest_weight = latest_weight_date = None
    for m in metrics:
        if m.get("weight_kg"):
            latest_weight      = m["weight_kg"]
            latest_weight_date = m["date"]
            break

    # XP и уровень (Фаза 10.4)
    xp_line = ""
    try:
        from db.queries.gamification import get_user_level_info
        xp_info = get_user_level_info(user["id"])
        if xp_info:
            xp_line = (
                f"\n⚡ *Уровень:* {xp_info['level_name']} "
                f"({xp_info['total_xp']} XP)"
            )
    except Exception:
        pass

    goal_map = {
        "lose_weight":      t("goal_lose_weight"),
        "gain_mass":        t("goal_gain_mass"),
        "endurance":        t("goal_endurance"),
        "general_fitness":  t("goal_general_fitness"),
        "peak_performance": t("goal_peak_performance"),
    }
    level_map = {
        "beginner":     t("level_beginner"),
        "intermediate": t("level_intermediate"),
        "advanced":     t("level_advanced"),
    }
    season_map = {
        "bulk":     t("season_bulk"),
        "cut":      t("season_cut"),
        "maintain": t("season_maintain"),
        "peak":     t("season_peak"),
    }
    time_map = {
        "morning":  t("time_morning"),
        "evening":  t("time_evening"),
        "flexible": t("time_flexible"),
    }
    location_map = {
        "home":     t("location_home"),
        "gym":      t("location_gym"),
        "outdoor":  t("location_outdoor"),
        "flexible": t("location_flexible"),
    }

    goal_label  = goal_map.get(user.get("goal", ""), user.get("goal") or t("goal_default"))
    level_label = level_map.get(user.get("fitness_level", "beginner"), t("level_beginner"))
    streak_icon = "🔥" if streak > 0 else "💤"

    lines = [
        t("profile_header", name=user.get('name') or tg.first_name),
        "━━━━━━━━━━━━━━━━━",
        t("profile_goal", val=goal_label),
        t("profile_level", val=level_label),
        t("profile_streak", icon=streak_icon, val=streak),
    ]
    if xp_line:
        lines.append(xp_line)

    lines += [
        "━━━━━━━━━━━━━━━━━",
        t("profile_physical"),
    ]

    lines.append(t("profile_age", val=surface['age'])     if surface.get("age")       else t("profile_age_none"))
    lines.append(t("profile_height", val=int(surface['height_cm'])) if surface.get("height_cm") else t("profile_height_none"))
    if latest_weight:
        lines.append(t("profile_weight", val=latest_weight, date=latest_weight_date))
    else:
        lines.append(t("profile_weight_none"))

    if user.get("injuries"):
        try:
            import json
            inj_list = json.loads(user["injuries"])
            if inj_list:
                lines.append(t("profile_injuries", val=', '.join(inj_list)))
        except Exception:
            pass

    lines += [
        "━━━━━━━━━━━━━━━━━",
        t("profile_training"),
        t("profile_training_time", val=time_map.get(training.get('preferred_time', 'flexible'), t("time_flexible"))),
        t("profile_training_location", val=location_map.get(user.get('training_location', 'flexible'), t("location_flexible"))),
        t("profile_training_season", val=season_map.get(surface.get('season', 'maintain'), t("season_maintain"))),
    ]
    if training.get("current_program"):
        lines.append(t("profile_training_program", val=training['current_program']))

    if nutrition and nutrition.get("daily_calories"):
        lines += [
            "━━━━━━━━━━━━━━━━━",
            t("profile_nutrition"),
            t("profile_nutrition_values",
              cal=nutrition['daily_calories'],
              p=nutrition.get('protein_g', '?'),
              f=nutrition.get('fat_g', '?'),
              c=nutrition.get('carbs_g', '?')),
        ]

    lines += [
        "━━━━━━━━━━━━━━━━━",
        t("profile_edit_hint"),
    ]

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=kb_profile_quick(),
    )


# ─── /test ───────────────────────────────────────────────────────────────────

async def cmd_test(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    tg = update.effective_user
    user = get_user(tg.id)
    if not user:
        await update.message.reply_text(t("test_no_profile"))
        return
    if not user["active"]:
        await update.message.reply_text(t("test_paused"))
        return

    days = days_since_last_test(user["id"])
    if days is not None and days < TEST_COOLDOWN_DAYS:
        last = get_last_fitness_test(user["id"])
        last_score = last["fitness_score"] if last else "?"
        await update.message.reply_text(
            t("test_cooldown", days=days, cooldown=TEST_COOLDOWN_DAYS),
            parse_mode="Markdown",
        )

    ctx.user_data["test_step"] = "pushups"
    ctx.user_data["test_data"] = {}

    if days is None or days >= TEST_COOLDOWN_DAYS:
        await update.message.reply_text(
            t("test_start"),
            parse_mode="Markdown",
        )


# ─── /plan ───────────────────────────────────────────────────────────────────

async def cmd_plan(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    tg = update.effective_user
    user = get_user(tg.id)
    if not user:
        await update.message.reply_text(t("plan_no_profile"))
        return

    plan = get_active_plan(user["id"])
    if plan is None:
        plan = get_last_plan(user["id"])

    if plan is None:
        await update.message.reply_text(
            t("plan_empty"),
            parse_mode="Markdown",
            reply_markup=kb_back_to_menu(),
        )
        return

    from scheduler.logic import _format_plan_message
    msg = _format_plan_message(plan)
    status = plan.get("status", "active")
    prefix = "" if status == "active" else t("plan_archived")

    await update.message.reply_text(
        f"{prefix}{msg}",
        parse_mode="Markdown",
        reply_markup=kb_plan_quick(),
    )


# ─── /achievements ───────────────────────────────────────────────────────────

async def cmd_achievements(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    tg = update.effective_user
    user = get_user(tg.id)
    if not user:
        await update.message.reply_text(t("achievements_no_profile"))
        return

    try:
        from db.queries.gamification import format_achievements_message
        msg = format_achievements_message(user["id"])
    except Exception as e:
        logger.error(f"[CMD] /achievements error for {tg.id}: {e}")
        msg = t("achievements_error")

    await update.message.reply_text(
        msg,
        parse_mode="Markdown",
        reply_markup=kb_achievements_quick(),
    )


# ─── /history ────────────────────────────────────────────────────────────────

async def cmd_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /history [N] — хроника активности за последние N дней (по умолчанию 7).
    """
    tg = update.effective_user
    user = get_user(tg.id)
    if not user:
        await update.message.reply_text(t("history_no_profile"))
        return

    days = 7
    args = ctx.args
    if args:
        try:
            days = max(1, min(90, int(args[0].strip("dдDД"))))
        except ValueError:
            pass

    await _send_history(update.message, user, days)


async def _send_history(message, user: dict, days: int) -> None:
    """Формирует и отправляет хронику за N дней. Используется командой и callback."""
    uid = user["id"]
    today = datetime.date.today()
    since = (today - datetime.timedelta(days=days)).isoformat()

    from db.connection import get_connection
    conn = get_connection()

    workouts_raw = conn.execute("""
        SELECT date, type, duration_min, intensity, completed, exercises
        FROM workouts
        WHERE user_id = ? AND date >= ?
        ORDER BY date DESC
    """, (uid, since)).fetchall()

    metrics_raw = conn.execute("""
        SELECT date, weight_kg, sleep_hours, energy, mood, steps
        FROM metrics
        WHERE user_id = ? AND date >= ?
        ORDER BY date DESC
    """, (uid, since)).fetchall()

    prs_raw = conn.execute("""
        SELECT exercise_name, record_value, record_type, set_at, improvement_pct
        FROM personal_records
        WHERE user_id = ? AND set_at >= ?
        ORDER BY set_at DESC
    """, (uid, since)).fetchall()

    lines = [t("history_header", days=days, date=today.strftime('%d.%m'))]

    if not workouts_raw and not metrics_raw:
        lines.append(t("history_empty"))
    else:
        if workouts_raw:
            type_icons = {
                "strength": "💪", "cardio": "🏃", "hiit": "⚡",
                "stretch": "🧘", "sport": "⚽", "other": "🏋️",
            }
            lines.append(t("history_workouts"))
            for w in workouts_raw[:10]:
                icon = type_icons.get(w["type"], "🏋️")
                dur = f" {w['duration_min']}мин" if w["duration_min"] else ""
                intensity = f" [{w['intensity']}/10]" if w["intensity"] else ""
                done = "✅" if w["completed"] else "⬜"
                date_fmt = w["date"][5:] if w["date"] else "?"
                lines.append(f"  {done} {date_fmt}: {icon} {w['type'] or t('history_workout_default')}{dur}{intensity}")
            if len(workouts_raw) > 10:
                lines.append(t("history_more", n=len(workouts_raw) - 10))

        if metrics_raw:
            lines.append("\n" + t("history_metrics"))
            for m in metrics_raw[:7]:
                parts = []
                if m["weight_kg"]:  parts.append(f"⚖️{m['weight_kg']}кг")
                if m["sleep_hours"]: parts.append(f"😴{m['sleep_hours']}ч")
                if m["energy"]:     parts.append(f"⚡{m['energy']}/5")
                if m["steps"]:      parts.append(f"👟{m['steps']}")
                date_fmt = m["date"][5:] if m["date"] else "?"
                if parts:
                    lines.append(f"  {date_fmt}: {' '.join(parts)}")

    if prs_raw:
        lines.append("\n" + t("history_records"))
        suffix_map = {"weight": t("history_unit_kg"), "time": t("history_unit_sec"), "reps": t("history_unit_reps")}
        for pr in prs_raw[:5]:
            suffix = suffix_map.get(pr["record_type"], "")
            improve = f" (+{pr['improvement_pct']:.0f}%)" if pr.get("improvement_pct") else ""
            date_fmt = pr["set_at"][5:] if pr["set_at"] else "?"
            lines.append(
                f"  🎯 {pr['exercise_name']}: "
                f"{pr['record_value']}{suffix}{improve} [{date_fmt}]"
            )

    done_count = sum(1 for w in workouts_raw if w["completed"])
    total_count = len(workouts_raw)
    if total_count > 0:
        bar_filled = min(10, done_count)
        bar = "█" * bar_filled + "░" * (10 - bar_filled)
        lines.append("\n" + t("history_bar", bar=bar, done=done_count, total=total_count))

    await message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=kb_history_period(days),
    )


# ─── /admin ──────────────────────────────────────────────────────────────────

async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from bot.admin import cmd_admin as _admin_handler
    await _admin_handler(update, ctx)


# ─── /costs ──────────────────────────────────────────────────────────────────

async def cmd_costs(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /costs — личная статистика расходов на AI за разные периоды.
    Показывает стоимость в $ за сегодня / неделю / месяц / всё время.
    """
    tg = update.effective_user
    user = get_user(tg.id)
    if not user:
        await update.message.reply_text(t("costs_no_profile"))
        return

    try:
        from db.queries.usage import get_usage_stats, get_daily_breakdown
        from bot.keyboards import kb_costs_quick

        stats = get_usage_stats(user["id"])

        def _fmt(s: dict) -> str:
            cost   = s.get("cost", 0)
            calls  = s.get("calls", 0)
            avg_t  = s.get("avg_time", 0)
            if calls == 0:
                return t("costs_no_data")
            avg_str = f"  ·  ⏱ {avg_t:.1f}с" if avg_t else ""
            return f"`${cost:.4f}`  ({calls} запр.{avg_str})"

        # Разбивка по дням (последние 7 дней)
        daily = get_daily_breakdown(user["id"], days=7)
        day_lines = []
        for d in daily[-5:]:  # последние 5 дней
            day_str = d["day"][5:]  # "03-17"
            day_lines.append(f"  {day_str}: `${d['cost']:.4f}`  ({d['calls']} зап.)")

        day_section = ""
        if day_lines:
            day_section = "\n" + t("costs_by_day") + "\n".join(day_lines) + "\n"

        name = user.get("name") or tg.first_name
        text = (
            t("costs_header", name=name)
            + "━━━━━━━━━━━━━━━━━\n"
            + t("costs_today", val=_fmt(stats['today']))
            + t("costs_week",  val=_fmt(stats['week']))
            + t("costs_month", val=_fmt(stats['month']))
            + t("costs_all",   val=_fmt(stats['all']))
            + "━━━━━━━━━━━━━━━━━\n"
            + day_section
            + "\n" + t("costs_footer")
        )

        await update.message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=kb_costs_quick(),
        )

    except Exception as e:
        logger.error(f"[CMD] /costs error for {tg.id}: {e}")
        await update.message.reply_text(t("costs_error"))


# ─── /reset ──────────────────────────────────────────────────────────────────

async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Сброс данных — использует inline кнопки вместо ввода текста (Фаза 11)."""
    await update.message.reply_text(
        t("reset_warning"),
        parse_mode="Markdown",
        reply_markup=kb_reset_confirm(),
    )


async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /today — дашборд текущего дня: питание vs цели + тренировка.
    Фаза 15.3.
    """
    tg = update.effective_user
    user = get_user(tg.id)
    if not user:
        await update.message.reply_text(t("today_no_profile"))
        return

    from db.queries.nutrition import get_today_nutrition
    from db.queries.workouts import get_today_workout
    from bot.keyboards import kb_today_quick

    today = datetime.date.today()
    today_str = today.isoformat()
    today_fmt = today.strftime("%-d %B").lower()  # "15 марта"

    # Данные дня
    nutrition = get_today_nutrition(user["id"])
    workout = get_today_workout(user["id"])
    l2 = get_l2_brief(user["id"]) or {}

    # Цели из памяти
    goal_cal  = l2.get("daily_calories") or 2500
    goal_prot = l2.get("protein_g")      or 175
    goal_fat  = l2.get("fat_g")          or 80
    goal_carb = l2.get("carbs_g")        or 300
    goal_water = 3000  # мл = 3 литра по умолчанию

    def _bar(current, target, width=10) -> str:
        if not target or target <= 0:
            return "░" * width
        pct = min(current / target, 1.0)
        filled = round(pct * width)
        return "█" * filled + "░" * (width - filled)

    def _fmt(val, default=0):
        return val if val is not None else default

    lines = [t("today_header", date=today_fmt)]

    # Питание
    cal   = _fmt(nutrition.get("calories")  if nutrition else None)
    prot  = _fmt(nutrition.get("protein_g") if nutrition else None)
    fat   = _fmt(nutrition.get("fat_g")     if nutrition else None)
    carb  = _fmt(nutrition.get("carbs_g")   if nutrition else None)
    water = _fmt(nutrition.get("water_ml")  if nutrition else None)

    if nutrition:
        lines += [
            t("today_nutrition"),
            t("today_cal",  bar=_bar(cal,  goal_cal),  cur=cal,  goal=goal_cal),
            t("today_prot", bar=_bar(prot, goal_prot), cur=prot, goal=goal_prot),
            t("today_fat",  bar=_bar(fat,  goal_fat),  cur=fat,  goal=goal_fat),
            t("today_carb", bar=_bar(carb, goal_carb), cur=carb, goal=goal_carb),
            t("today_water",       bar=_bar(water, goal_water), cur=f"{water // 1000:.1f}", goal=f"{goal_water // 1000:.0f}") if water else t("today_water_empty", bar="░" * 10, goal=f"{goal_water // 1000:.0f}"),
        ]
    else:
        lines.append(t("today_nutrition_empty"))

    # Тренировка
    lines.append("")
    if workout and workout.get("completed"):
        dur  = workout.get("duration_min", "?")
        rpe  = workout.get("intensity", "?")
        wtype = workout.get("type") or t("history_workout_default")
        lines.append(t("today_workout_done", type=wtype, dur=dur, rpe=rpe))
    else:
        # Смотрим план на сегодня
        plan = get_active_plan(user["id"])
        today_workout_planned = None
        if plan:
            try:
                import json as _j
                for day in _j.loads(plan["plan_json"]):
                    if day.get("date") == today_str:
                        today_workout_planned = day
                        break
            except Exception:
                pass
        if today_workout_planned and today_workout_planned.get("type") not in ("rest", "recovery", None):
            label = today_workout_planned.get("label") or today_workout_planned.get("type")
            lines.append(t("today_workout_planned", label=label))
        elif today_workout_planned and today_workout_planned.get("type") in ("rest", "recovery"):
            lines.append(t("today_rest_day"))
        else:
            lines.append(t("today_workout_empty"))

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=kb_today_quick(),
    )


# ─── /workout — тренировка на сегодня ─────────────────────────────────────────

async def cmd_workout(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Генерирует тренировку на сегодня с учётом оборудования, уровня и истории."""
    import os
    from ai.context_builder import build_layered_context
    from ai.client import generate_agent_response
    from db.writer import save_user_message, save_ai_response
    from config import PROMPTS_DIR

    tg = update.effective_user
    user = get_user(tg.id)
    if not user or not user["active"]:
        return

    user_msg = "Составь мне тренировку на сегодня"
    save_user_message(tg.id, user_msg)

    context = build_layered_context(tg.id, user_msg)

    workout_prompt_path = os.path.join(PROMPTS_DIR, "workout_planning.txt")
    with open(workout_prompt_path, "r", encoding="utf-8") as f:
        context["system"] = context["system"] + "\n\n" + f.read()

    bot = update.message.get_bot()
    response = await generate_agent_response(
        bot=bot,
        chat_id=update.message.chat_id,
        context=context,
        user_message=user_msg,
        tg_id=tg.id,
    )
    if response:
        save_ai_response(tg.id, response)
