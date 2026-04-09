"""
bot/keyboards.py — Inline и Reply клавиатуры.

Фаза 11 — UI/UX: добавлено главное меню, quick-action кнопки под командами,
кнопки периода истории, подтверждение сброса inline.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from lang import t


# ═══════════════════════════════════════════════════════════════════════════
# ФАЗА 11 — ГЛАВНОЕ МЕНЮ И QUICK ACTIONS
# ═══════════════════════════════════════════════════════════════════════════

def kb_main_menu() -> InlineKeyboardMarkup:
    """Главное меню бота — доступно через /menu или кнопкой."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(t("kb_stats"),    callback_data="menu:stats"),
            InlineKeyboardButton(t("kb_plan"),     callback_data="menu:plan"),
        ],
        [
            InlineKeyboardButton(t("kb_calendar"), callback_data="menu:calendar"),
            InlineKeyboardButton(t("kb_chronicle"), callback_data="menu:history"),
        ],
        [
            InlineKeyboardButton(t("kb_achievements"), callback_data="menu:achievements"),
            InlineKeyboardButton(t("kb_profile"),      callback_data="menu:profile"),
        ],
        [
            InlineKeyboardButton(t("kb_fitness_test"), callback_data="menu:test"),
            InlineKeyboardButton(t("kb_settings"),     callback_data="menu:setup"),
        ],
        [
            InlineKeyboardButton(t("kb_export_csv"),   callback_data="menu:export"),
        ],
    ])


def kb_stats_quick() -> InlineKeyboardMarkup:
    """Быстрые действия под /stats."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(t("kb_7days"),        callback_data="menu:history_7"),
            InlineKeyboardButton(t("kb_30days"),       callback_data="menu:history_30"),
        ],
        [
            InlineKeyboardButton(t("kb_weight_chart"), callback_data="chart:weight"),
            InlineKeyboardButton(t("kb_records"),      callback_data="chart:strength"),
        ],
        [
            InlineKeyboardButton(t("kb_fitness_test"), callback_data="menu:test"),
            InlineKeyboardButton(t("kb_export"),       callback_data="menu:export"),
        ],
        [InlineKeyboardButton(t("kb_home"),            callback_data="menu:home")],
    ])


def kb_profile_quick() -> InlineKeyboardMarkup:
    """Быстрые действия под /profile."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(t("kb_update_settings"), callback_data="menu:setup"),
            InlineKeyboardButton(t("kb_stats"),           callback_data="menu:stats"),
        ],
        [
            InlineKeyboardButton(t("kb_my_achievements"), callback_data="menu:achievements"),
            InlineKeyboardButton(t("kb_export"),          callback_data="menu:export"),
        ],
        [InlineKeyboardButton(t("kb_home"),               callback_data="menu:home")],
    ])


def kb_achievements_quick() -> InlineKeyboardMarkup:
    """Быстрые действия под /achievements."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(t("kb_chronicle_30d"), callback_data="menu:history_30"),
            InlineKeyboardButton(t("kb_fitness_test"),  callback_data="menu:test"),
        ],
        [InlineKeyboardButton(t("kb_home"),             callback_data="menu:home")],
    ])


def kb_history_period(current_days: int = 7) -> InlineKeyboardMarkup:
    """Выбор периода для /history."""
    def mark(d: int) -> str:
        return f"✓ {d}д" if d == current_days else f"{d}д"

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(mark(7),  callback_data="menu:history_7"),
            InlineKeyboardButton(mark(14), callback_data="menu:history_14"),
            InlineKeyboardButton(mark(30), callback_data="menu:history_30"),
            InlineKeyboardButton(mark(90), callback_data="menu:history_90"),
        ],
        [InlineKeyboardButton(t("kb_home"), callback_data="menu:home")],
    ])


def kb_plan_quick() -> InlineKeyboardMarkup:
    """Быстрые действия под /plan."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(t("kb_stats"),        callback_data="menu:stats"),
            InlineKeyboardButton(t("kb_fitness_test"), callback_data="menu:test"),
        ],
        [InlineKeyboardButton(t("kb_home"),            callback_data="menu:home")],
    ])


def kb_reset_confirm() -> InlineKeyboardMarkup:
    """Подтверждение сброса данных — inline кнопки вместо ввода текста."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(t("kb_confirm_delete"), callback_data="reset:confirm"),
            InlineKeyboardButton(t("kb_cancel"),         callback_data="reset:cancel"),
        ],
    ])


def kb_stop_quick() -> InlineKeyboardMarkup:
    """Быстрый выбор паузы после /stop."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(t("kb_3days"),   callback_data="stop:3"),
            InlineKeyboardButton(t("kb_7days_p"), callback_data="stop:7"),
            InlineKeyboardButton(t("kb_14days"),  callback_data="stop:14"),
        ],
        [InlineKeyboardButton(t("kb_forever"), callback_data="stop:indefinite")],
    ])


def kb_back_to_menu() -> InlineKeyboardMarkup:
    """Простая кнопка возврата в главное меню."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(t("kb_home"), callback_data="menu:home"),
    ]])


# ═══════════════════════════════════════════════════════════════════════════
# GUIDED WORKOUT FLOW — Фаза 13.2
# ═══════════════════════════════════════════════════════════════════════════

def kb_workout_duration() -> InlineKeyboardMarkup:
    """Выбор длительности тренировки (шаг 1 guided flow)."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(t("kb_20min"), callback_data="wf:dur:20"),
            InlineKeyboardButton(t("kb_30min"), callback_data="wf:dur:30"),
            InlineKeyboardButton(t("kb_45min"), callback_data="wf:dur:45"),
            InlineKeyboardButton(t("kb_60min"), callback_data="wf:dur:60"),
        ],
        [
            InlineKeyboardButton(t("kb_75min"), callback_data="wf:dur:75"),
            InlineKeyboardButton(t("kb_90min"), callback_data="wf:dur:90"),
            InlineKeyboardButton(t("kb_other"), callback_data="wf:dur:custom"),
        ],
    ])


def kb_workout_rpe() -> InlineKeyboardMarkup:
    """RPE 1-10 — оценка интенсивности (шаг 2 guided flow)."""
    row1 = [InlineKeyboardButton(str(i), callback_data=f"wf:rpe:{i}") for i in range(1, 6)]
    row2 = [InlineKeyboardButton(str(i), callback_data=f"wf:rpe:{i}") for i in range(6, 11)]
    return InlineKeyboardMarkup([row1, row2])


def kb_workout_feeling() -> InlineKeyboardMarkup:
    """Ощущения после тренировки (шаг 3 guided flow)."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(t("kb_great"),  callback_data="wf:feel:great"),
            InlineKeyboardButton(t("kb_normal"), callback_data="wf:feel:ok"),
        ],
        [
            InlineKeyboardButton(t("kb_hard"), callback_data="wf:feel:hard"),
            InlineKeyboardButton(t("kb_pain"), callback_data="wf:feel:pain"),
        ],
    ])


def kb_workout_comment() -> InlineKeyboardMarkup:
    """Комментарий — пропустить или ввести текстом (шаг 4 guided flow)."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(t("kb_no_comment"), callback_data="wf:comment:skip"),
    ]])


# ═══════════════════════════════════════════════════════════════════════════
# ЧЕК-ИНЫ V2 — кнопочный flow без AI
# ═══════════════════════════════════════════════════════════════════════════

def kb_checkin_sleep() -> InlineKeyboardMarkup:
    """Утренний чек-ин шаг 1: сколько часов сна."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("5", callback_data="ci:sleep:5"),
        InlineKeyboardButton("6", callback_data="ci:sleep:6"),
        InlineKeyboardButton("7", callback_data="ci:sleep:7"),
        InlineKeyboardButton("8", callback_data="ci:sleep:8"),
        InlineKeyboardButton("9", callback_data="ci:sleep:9"),
        InlineKeyboardButton("10", callback_data="ci:sleep:10"),
    ]])


def kb_checkin_wellbeing() -> InlineKeyboardMarkup:
    """Утренний чек-ин шаг 2: самочувствие 2-5."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("😓 2", callback_data="ci:well:2"),
        InlineKeyboardButton("😐 3", callback_data="ci:well:3"),
        InlineKeyboardButton("🙂 4", callback_data="ci:well:4"),
        InlineKeyboardButton("💪 5", callback_data="ci:well:5"),
    ]])


def kb_checkin_workout_done() -> InlineKeyboardMarkup:
    """Вечерний/ночной чек-ин: сделал тренировку?"""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(t("kb_workout_done"),    callback_data="ci:wk:done"),
        InlineKeyboardButton(t("kb_workout_no"),      callback_data="ci:wk:no"),
        InlineKeyboardButton(t("kb_workout_skipped"), callback_data="ci:wk:skip"),
    ]])


def kb_checkin_food_skip() -> InlineKeyboardMarkup:
    """Кнопка «Ничего не ел» для пропуска ответа о еде."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(t("kb_food_nothing"), callback_data="ci:food:skip"),
    ]])


# ── Обратная совместимость — старые клавиатуры, которые используются в других местах ──

def kb_workout_done() -> InlineKeyboardMarkup:
    """Кнопки записи тренировки (guided flow, /today, etc.)."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(t("kb_checkin_done"),    callback_data="workout_done"),
        InlineKeyboardButton(t("kb_checkin_pending"), callback_data="workout_pending"),
        InlineKeyboardButton(t("kb_checkin_skipped"), callback_data="workout_skipped"),
    ]])


def kb_energy() -> InlineKeyboardMarkup:
    labels = ["😴 1", "😐 2", "🙂 3", "😊 4", "⚡ 5"]
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(label, callback_data=f"energy_{i+1}")
        for i, label in enumerate(labels)
    ]])


def kb_reminder() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(t("kb_preworkout_go"),    callback_data="reminder_go"),
        InlineKeyboardButton(t("kb_preworkout_30min"), callback_data="reminder_snooze"),
        InlineKeyboardButton(t("kb_preworkout_skip"),  callback_data="reminder_skip"),
    ]])


# ═══════════════════════════════════════════════════════════════════════════
# ОНБОРДИНГ
# ═══════════════════════════════════════════════════════════════════════════

def kb_goal() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_goal_lose"),      callback_data="goal_lose"),
         InlineKeyboardButton(t("kb_goal_gain"),      callback_data="goal_gain")],
        [InlineKeyboardButton(t("kb_goal_endurance"), callback_data="goal_endurance"),
         InlineKeyboardButton(t("kb_goal_general"),   callback_data="goal_general")],
    ])


def kb_fitness_level() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(t("kb_level_beginner"),     callback_data="level_beginner"),
        InlineKeyboardButton(t("kb_level_intermediate"), callback_data="level_intermediate"),
        InlineKeyboardButton(t("kb_level_advanced"),     callback_data="level_advanced"),
    ]])


def kb_workout_time() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(t("kb_time_morning"),  callback_data="time_morning"),
        InlineKeyboardButton(t("kb_time_evening"),  callback_data="time_evening"),
        InlineKeyboardButton(t("kb_time_flexible"), callback_data="time_flexible"),
    ]])


def kb_health_check() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(t("kb_health_ok"),      callback_data="health_ok"),
        InlineKeyboardButton(t("kb_health_limited"), callback_data="health_issues"),
    ]])


def kb_training_location() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_loc_home"),     callback_data="location_home"),
         InlineKeyboardButton(t("kb_loc_gym"),      callback_data="location_gym")],
        [InlineKeyboardButton(t("kb_loc_outdoor"),  callback_data="location_outdoor"),
         InlineKeyboardButton(t("kb_loc_flexible"), callback_data="location_flexible")],
    ])


def kb_training_days() -> InlineKeyboardMarkup:
    """Выбор расписания тренировок по дням недели (пресеты)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_days_3x"),    callback_data="days_3x")],
        [InlineKeyboardButton(t("kb_days_4x"),    callback_data="days_4x")],
        [InlineKeyboardButton(t("kb_days_5x"),    callback_data="days_5x")],
        [InlineKeyboardButton(t("kb_days_daily"), callback_data="days_daily"),
         InlineKeyboardButton(t("kb_days_flex"),  callback_data="days_flex")],
    ])


# ═══════════════════════════════════════════════════════════════════════════
# АДМИН-ПАНЕЛЬ
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
# /TODAY DASHBOARD — Фаза 15.3 / QUICK MEALS — Фаза 15.4
# ═══════════════════════════════════════════════════════════════════════════

def kb_today_quick() -> InlineKeyboardMarkup:
    """Кнопки под /today: быстрый приём пищи и меню."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(t("kb_quick_meal"),    callback_data="meal:quick"),
            InlineKeyboardButton(t("kb_quick_workout"), callback_data="workout_done"),
        ],
        [InlineKeyboardButton(t("kb_home"), callback_data="menu:home")],
    ])


def kb_quick_meals() -> InlineKeyboardMarkup:
    """Пресеты частых приёмов пищи — 1 тап = записать."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(t("kb_meal_grechka"),  callback_data="meal:grechka"),
            InlineKeyboardButton(t("kb_meal_ovsyanka"), callback_data="meal:ovsyanka"),
        ],
        [
            InlineKeyboardButton(t("kb_meal_tvorog"),   callback_data="meal:tvorog"),
            InlineKeyboardButton(t("kb_meal_eggs"),     callback_data="meal:eggs"),
        ],
        [
            InlineKeyboardButton(t("kb_meal_protein"),  callback_data="meal:protein"),
        ],
        [InlineKeyboardButton(t("kb_back"),             callback_data="menu:home")],
    ])


def kb_admin_main() -> InlineKeyboardMarkup:
    """Главное меню администратора."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_admin_users"),     callback_data="adm:users"),
         InlineKeyboardButton(t("kb_admin_jobs"),      callback_data="adm:jobs")],
        [InlineKeyboardButton(t("kb_admin_broadcast"), callback_data="adm:broadcast"),
         InlineKeyboardButton(t("kb_admin_trigger"),   callback_data="adm:trigger")],
        [InlineKeyboardButton(t("kb_admin_costs"),     callback_data="adm:costs")],
    ])


def kb_costs_quick() -> InlineKeyboardMarkup:
    """Быстрые действия под /costs."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_stats"),  callback_data="menu:stats"),
         InlineKeyboardButton(t("kb_home"),   callback_data="menu:home")],
    ])


def kb_admin_triggers() -> InlineKeyboardMarkup:
    """Подменю ручного запуска задач."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌅 Утренний чек-ин",  callback_data="adm:trigger:morning"),
         InlineKeyboardButton("🌙 Вечерний чек-ин",  callback_data="adm:trigger:evening")],
        [InlineKeyboardButton("📊 Дневная сводка",   callback_data="adm:trigger:daily"),
         InlineKeyboardButton("📈 Недельная сводка", callback_data="adm:trigger:weekly")],
        [InlineKeyboardButton("🔔 Нудж-проверка",   callback_data="adm:trigger:nudges"),
         InlineKeyboardButton("📅 Месячный отчёт",  callback_data="adm:trigger:monthly")],
        [InlineKeyboardButton("🥗 Анализ питания",  callback_data="adm:trigger:nutrition_analysis")],
        [InlineKeyboardButton(t("kb_back"), callback_data="adm:home")],
    ])


def kb_admin_back() -> InlineKeyboardMarkup:
    """Кнопка возврата в главное меню."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("« Главное меню", callback_data="adm:home"),
    ]])


# ═══════════════════════════════════════════════════════════════════════════
# ADAPTIVE SESSION MODIFIER — авто-подстройка тренировки
# ═══════════════════════════════════════════════════════════════════════════

def kb_session_adapt(adapt_type: str) -> InlineKeyboardMarkup:
    """
    Кнопки принятия/отклонения адаптации тренировки.

    adapt_type: 'deload' | 'light' | 'boost'
    """
    if adapt_type == "boost":
        accept_text = t("kb_adapt_boost")
    elif adapt_type == "deload":
        accept_text = t("kb_adapt_deload")
    else:
        accept_text = t("kb_adapt_light")

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(accept_text, callback_data=f"adapt:accept:{adapt_type}"),
            InlineKeyboardButton(t("kb_adapt_normal"), callback_data="adapt:skip"),
        ],
        [
            InlineKeyboardButton(t("kb_adapt_workout"), callback_data="workout_done"),
        ],
    ])
