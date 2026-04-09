"""
bot/keyboards.py — Inline и Reply клавиатуры.

Фаза 11 — UI/UX: добавлено главное меню, quick-action кнопки под командами,
кнопки периода истории, подтверждение сброса inline.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup


# ═══════════════════════════════════════════════════════════════════════════
# ФАЗА 11 — ГЛАВНОЕ МЕНЮ И QUICK ACTIONS
# ═══════════════════════════════════════════════════════════════════════════

def kb_main_menu() -> InlineKeyboardMarkup:
    """Главное меню бота — доступно через /menu или кнопкой."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Статистика",    callback_data="menu:stats"),
            InlineKeyboardButton("📋 План",          callback_data="menu:plan"),
        ],
        [
            InlineKeyboardButton("🗓 Календарь",     callback_data="menu:calendar"),
            InlineKeyboardButton("📅 Хроника",       callback_data="menu:history"),
        ],
        [
            InlineKeyboardButton("🏆 Ачивки",        callback_data="menu:achievements"),
            InlineKeyboardButton("👤 Профиль",       callback_data="menu:profile"),
        ],
        [
            InlineKeyboardButton("🏋️ Фитнес-тест",  callback_data="menu:test"),
            InlineKeyboardButton("🔧 Настройки",     callback_data="menu:setup"),
        ],
        [
            InlineKeyboardButton("📤 Экспорт CSV",   callback_data="menu:export"),
        ],
    ])


def kb_stats_quick() -> InlineKeyboardMarkup:
    """Быстрые действия под /stats."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📅 7 дней",        callback_data="menu:history_7"),
            InlineKeyboardButton("📅 30 дней",       callback_data="menu:history_30"),
        ],
        [
            InlineKeyboardButton("⚖️ График веса",   callback_data="chart:weight"),
            InlineKeyboardButton("💪 Рекорды",       callback_data="chart:strength"),
        ],
        [
            InlineKeyboardButton("🏋️ Фитнес-тест",  callback_data="menu:test"),
            InlineKeyboardButton("📤 Экспорт",       callback_data="menu:export"),
        ],
        [InlineKeyboardButton("🏠 Главное меню",     callback_data="menu:home")],
    ])


def kb_profile_quick() -> InlineKeyboardMarkup:
    """Быстрые действия под /profile."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Обновить настройки", callback_data="menu:setup"),
            InlineKeyboardButton("📊 Статистика",          callback_data="menu:stats"),
        ],
        [
            InlineKeyboardButton("🏆 Мои ачивки",   callback_data="menu:achievements"),
            InlineKeyboardButton("📤 Экспорт",       callback_data="menu:export"),
        ],
        [InlineKeyboardButton("🏠 Главное меню",     callback_data="menu:home")],
    ])


def kb_achievements_quick() -> InlineKeyboardMarkup:
    """Быстрые действия под /achievements."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📅 Хроника 30 дней", callback_data="menu:history_30"),
            InlineKeyboardButton("🏋️ Фитнес-тест",    callback_data="menu:test"),
        ],
        [InlineKeyboardButton("🏠 Главное меню",        callback_data="menu:home")],
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
        [InlineKeyboardButton("🏠 Главное меню", callback_data="menu:home")],
    ])


def kb_plan_quick() -> InlineKeyboardMarkup:
    """Быстрые действия под /plan."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Статистика",   callback_data="menu:stats"),
            InlineKeyboardButton("🏋️ Фитнес-тест", callback_data="menu:test"),
        ],
        [InlineKeyboardButton("🏠 Главное меню",    callback_data="menu:home")],
    ])


def kb_reset_confirm() -> InlineKeyboardMarkup:
    """Подтверждение сброса данных — inline кнопки вместо ввода текста."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да, удалить всё", callback_data="reset:confirm"),
            InlineKeyboardButton("❌ Отмена",          callback_data="reset:cancel"),
        ],
    ])


def kb_stop_quick() -> InlineKeyboardMarkup:
    """Быстрый выбор паузы после /stop."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("3 дня",   callback_data="stop:3"),
            InlineKeyboardButton("7 дней",  callback_data="stop:7"),
            InlineKeyboardButton("14 дней", callback_data="stop:14"),
        ],
        [InlineKeyboardButton("Бессрочно", callback_data="stop:indefinite")],
    ])


def kb_back_to_menu() -> InlineKeyboardMarkup:
    """Простая кнопка возврата в главное меню."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🏠 Главное меню", callback_data="menu:home"),
    ]])


# ═══════════════════════════════════════════════════════════════════════════
# GUIDED WORKOUT FLOW — Фаза 13.2
# ═══════════════════════════════════════════════════════════════════════════

def kb_workout_duration() -> InlineKeyboardMarkup:
    """Выбор длительности тренировки (шаг 1 guided flow)."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("20 мин", callback_data="wf:dur:20"),
            InlineKeyboardButton("30 мин", callback_data="wf:dur:30"),
            InlineKeyboardButton("45 мин", callback_data="wf:dur:45"),
            InlineKeyboardButton("60 мин", callback_data="wf:dur:60"),
        ],
        [
            InlineKeyboardButton("75 мин", callback_data="wf:dur:75"),
            InlineKeyboardButton("90 мин", callback_data="wf:dur:90"),
            InlineKeyboardButton("⌨️ Другое", callback_data="wf:dur:custom"),
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
            InlineKeyboardButton("💪 Отлично",   callback_data="wf:feel:great"),
            InlineKeyboardButton("😐 Нормально", callback_data="wf:feel:ok"),
        ],
        [
            InlineKeyboardButton("😓 Тяжело",  callback_data="wf:feel:hard"),
            InlineKeyboardButton("🤕 Боль",    callback_data="wf:feel:pain"),
        ],
    ])


def kb_workout_comment() -> InlineKeyboardMarkup:
    """Комментарий — пропустить или ввести текстом (шаг 4 guided flow)."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Нет, всё ок", callback_data="wf:comment:skip"),
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
        InlineKeyboardButton("✅ Сделал",    callback_data="ci:wk:done"),
        InlineKeyboardButton("❌ Нет",       callback_data="ci:wk:no"),
        InlineKeyboardButton("⏭ Пропустил", callback_data="ci:wk:skip"),
    ]])


def kb_checkin_food_skip() -> InlineKeyboardMarkup:
    """Кнопка «Ничего не ел» для пропуска ответа о еде."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🚫 Ничего не ел", callback_data="ci:food:skip"),
    ]])


# ── Обратная совместимость — старые клавиатуры, которые используются в других местах ──

def kb_workout_done() -> InlineKeyboardMarkup:
    """Кнопки записи тренировки (guided flow, /today, etc.)."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("💪 Сделал",       callback_data="workout_done"),
        InlineKeyboardButton("⏳ Ещё не было",  callback_data="workout_pending"),
        InlineKeyboardButton("❌ Пропустил",    callback_data="workout_skipped"),
    ]])


def kb_energy() -> InlineKeyboardMarkup:
    labels = ["😴 1", "😐 2", "🙂 3", "😊 4", "⚡ 5"]
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(label, callback_data=f"energy_{i+1}")
        for i, label in enumerate(labels)
    ]])


def kb_reminder() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Иду",          callback_data="reminder_go"),
        InlineKeyboardButton("⏰ Ещё 30 мин",  callback_data="reminder_snooze"),
        InlineKeyboardButton("❌ Не сегодня",  callback_data="reminder_skip"),
    ]])


# ═══════════════════════════════════════════════════════════════════════════
# ОНБОРДИНГ
# ═══════════════════════════════════════════════════════════════════════════

def kb_goal() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥 Похудеть",      callback_data="goal_lose"),
         InlineKeyboardButton("💪 Набрать массу", callback_data="goal_gain")],
        [InlineKeyboardButton("🏃 Выносливость",  callback_data="goal_endurance"),
         InlineKeyboardButton("🧘 Общая форма",   callback_data="goal_general")],
    ])


def kb_fitness_level() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🌱 Начинающий",   callback_data="level_beginner"),
        InlineKeyboardButton("🏋️ Средний",     callback_data="level_intermediate"),
        InlineKeyboardButton("🔥 Продвинутый", callback_data="level_advanced"),
    ]])


def kb_workout_time() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🌅 Утром",   callback_data="time_morning"),
        InlineKeyboardButton("🌙 Вечером", callback_data="time_evening"),
        InlineKeyboardButton("⏰ Гибко",   callback_data="time_flexible"),
    ]])


def kb_health_check() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Всё в порядке",     callback_data="health_ok"),
        InlineKeyboardButton("⚠️ Есть ограничения", callback_data="health_issues"),
    ]])


def kb_training_location() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Дома",       callback_data="location_home"),
         InlineKeyboardButton("🏋️ Зал",        callback_data="location_gym")],
        [InlineKeyboardButton("🌳 На улице",   callback_data="location_outdoor"),
         InlineKeyboardButton("🔄 По-разному", callback_data="location_flexible")],
    ])


def kb_training_days() -> InlineKeyboardMarkup:
    """Выбор расписания тренировок по дням недели (пресеты)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("3 раза (Пн, Ср, Пт)",     callback_data="days_3x")],
        [InlineKeyboardButton("4 раза (Пн, Вт, Чт, Пт)", callback_data="days_4x")],
        [InlineKeyboardButton("5 раз (Пн–Пт)",           callback_data="days_5x")],
        [InlineKeyboardButton("Ежедневно",  callback_data="days_daily"),
         InlineKeyboardButton("Как получится", callback_data="days_flex")],
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
            InlineKeyboardButton("🍽 Быстрый приём", callback_data="meal:quick"),
            InlineKeyboardButton("💪 Записать тренировку", callback_data="workout_done"),
        ],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="menu:home")],
    ])


def kb_quick_meals() -> InlineKeyboardMarkup:
    """Пресеты частых приёмов пищи — 1 тап = записать."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🍚 Гречка + курица",  callback_data="meal:grechka"),
            InlineKeyboardButton("🥣 Овсянка",          callback_data="meal:ovsyanka"),
        ],
        [
            InlineKeyboardButton("🥛 Творог",           callback_data="meal:tvorog"),
            InlineKeyboardButton("🥚 Яйца ×3",         callback_data="meal:eggs"),
        ],
        [
            InlineKeyboardButton("🥤 Протеин (шейк)",   callback_data="meal:protein"),
        ],
        [InlineKeyboardButton("« Назад",               callback_data="menu:home")],
    ])


def kb_admin_main() -> InlineKeyboardMarkup:
    """Главное меню администратора."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Пользователи", callback_data="adm:users"),
         InlineKeyboardButton("⚙️ Задачи",       callback_data="adm:jobs")],
        [InlineKeyboardButton("📢 Рассылка",     callback_data="adm:broadcast"),
         InlineKeyboardButton("⚡ Триггер",      callback_data="adm:trigger")],
        [InlineKeyboardButton("💰 Расходы AI",   callback_data="adm:costs")],
    ])


def kb_costs_quick() -> InlineKeyboardMarkup:
    """Быстрые действия под /costs."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статистика",   callback_data="menu:stats"),
         InlineKeyboardButton("🏠 Главное меню", callback_data="menu:home")],
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
        [InlineKeyboardButton("« Назад", callback_data="adm:home")],
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
        accept_text = "🔥 Усилить"
    elif adapt_type == "deload":
        accept_text = "✅ Deload-день"
    else:
        accept_text = "✅ Облегчить"

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(accept_text, callback_data=f"adapt:accept:{adapt_type}"),
            InlineKeyboardButton("💪 По плану", callback_data="adapt:skip"),
        ],
        [
            InlineKeyboardButton("💬 Записать тренировку", callback_data="workout_done"),
        ],
    ])
