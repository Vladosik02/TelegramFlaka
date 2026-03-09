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
