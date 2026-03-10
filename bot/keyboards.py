"""
bot/keyboards.py — Inline и Reply клавиатуры.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup


# ─── Утренний чек-ин ─────────────────────────────────────────────────────────
def kb_morning_ready() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Готов", callback_data="morning_ready"),
        InlineKeyboardButton("😴 Дай время", callback_data="morning_later"),
    ]])


# ─── После тренировки ─────────────────────────────────────────────────────────
def kb_workout_done() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("💪 Сделал", callback_data="workout_done"),
        InlineKeyboardButton("⏳ Ещё не было", callback_data="workout_pending"),
        InlineKeyboardButton("❌ Пропустил", callback_data="workout_skipped"),
    ]])


# ─── Интенсивность 1–10 ───────────────────────────────────────────────────────
def kb_intensity() -> InlineKeyboardMarkup:
    row1 = [InlineKeyboardButton(str(i), callback_data=f"intensity_{i}") for i in range(1, 6)]
    row2 = [InlineKeyboardButton(str(i), callback_data=f"intensity_{i}") for i in range(6, 11)]
    return InlineKeyboardMarkup([row1, row2])


# ─── Энергия 1–5 ──────────────────────────────────────────────────────────────
def kb_energy() -> InlineKeyboardMarkup:
    labels = ["😴 1", "😐 2", "🙂 3", "😊 4", "⚡ 5"]
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(label, callback_data=f"energy_{i+1}")
        for i, label in enumerate(labels)
    ]])


# ─── Вечерний ─────────────────────────────────────────────────────────────────
def kb_evening_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("👍 Записано", callback_data="evening_ack"),
    ]])


# ─── Напоминание ──────────────────────────────────────────────────────────────
def kb_reminder() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Иду", callback_data="reminder_go"),
        InlineKeyboardButton("⏰ Ещё 30 мин", callback_data="reminder_snooze"),
        InlineKeyboardButton("❌ Не сегодня", callback_data="reminder_skip"),
    ]])


# ─── Онбординг — цель ────────────────────────────────────────────────────────
def kb_goal() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥 Похудеть", callback_data="goal_lose"),
         InlineKeyboardButton("💪 Набрать массу", callback_data="goal_gain")],
        [InlineKeyboardButton("🏃 Выносливость", callback_data="goal_endurance"),
         InlineKeyboardButton("🧘 Общая форма", callback_data="goal_general")],
    ])


# ─── Онбординг — уровень ─────────────────────────────────────────────────────
def kb_fitness_level() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🌱 Начинающий", callback_data="level_beginner"),
        InlineKeyboardButton("🏋️ Средний", callback_data="level_intermediate"),
        InlineKeyboardButton("🔥 Продвинутый", callback_data="level_advanced"),
    ]])


# ─── Онбординг — время тренировки ────────────────────────────────────────────
def kb_workout_time() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🌅 Утром", callback_data="time_morning"),
        InlineKeyboardButton("🌙 Вечером", callback_data="time_evening"),
        InlineKeyboardButton("⏰ Гибко", callback_data="time_flexible"),
    ]])


# ─── Онбординг — состояние здоровья ──────────────────────────────────────────
def kb_health_check() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Всё в порядке", callback_data="health_ok"),
        InlineKeyboardButton("⚠️ Есть ограничения", callback_data="health_issues"),
    ]])


# ─── Онбординг — место тренировки ────────────────────────────────────────────
def kb_training_location() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Дома", callback_data="location_home"),
         InlineKeyboardButton("🏋️ Зал", callback_data="location_gym")],
        [InlineKeyboardButton("🌳 На улице", callback_data="location_outdoor"),
         InlineKeyboardButton("🔄 По-разному", callback_data="location_flexible")],
    ])
