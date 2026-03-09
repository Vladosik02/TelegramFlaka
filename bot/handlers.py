"""
bot/handlers.py — Обработчики текстовых сообщений, голосовых и callback'ов.
"""
import os
import logging
import tempfile
from telegram import Update
from telegram.ext import ContextTypes

from db.queries.user import get_user, create_user, update_user
from db.connection import get_connection
from ai.context_builder import build_layered_context, maybe_compress_context
from ai.client import generate_chat_response_streaming
from ai.response_parser import (
    detect_health_alert, is_workout_report, is_metrics_report,
    parse_workout_from_message, parse_metrics_from_message
)
from db.writer import (
    save_user_message, save_ai_response,
    save_workout_from_parsed, save_metrics_from_parsed
)
from bot.keyboards import kb_fitness_level, kb_goal
from config import HEALTH_KEYWORDS, OPENAI_API_KEY

logger = logging.getLogger(__name__)

GOAL_MAP = {
    "goal_lose": "похудеть",
    "goal_gain": "набрать массу",
    "goal_endurance": "выносливость",
    "goal_general": "общая форма",
}
LEVEL_MAP = {
    "level_beginner": "beginner",
    "level_intermediate": "intermediate",
    "level_advanced": "advanced",
}


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Основной обработчик текстовых сообщений."""
    tg = update.effective_user
    text = update.message.text.strip()

    # ── Подтверждение сброса ─────────────────────────────────────────────────
    if ctx.user_data.get("awaiting_reset_confirm"):
        ctx.user_data.pop("awaiting_reset_confirm")
        if text.upper() == "УДАЛИТЬ":
            await _handle_reset_confirmed(update, tg.id)
        else:
            await update.message.reply_text("Отмена. Данные не тронуты.")
        return

    # ── Проверка пользователя ─────────────────────────────────────────────────
    user = get_user(tg.id)
    if not user:
        await update.message.reply_text(
            "Привет! Напиши /start чтобы начать."
        )
        return

    # ── Health check ──────────────────────────────────────────────────────────
    if detect_health_alert(text, HEALTH_KEYWORDS):
        await update.message.reply_text(
            "⚠️ Звучит серьёзно. Если есть боль или дискомфорт — "
            "остановись и при необходимости обратись к врачу. "
            "Тренировку пропустить — не страшно. Расскажи подробнее что случилось?"
        )
        save_user_message(tg.id, text)
        return

    # ── Сохранить сообщение ───────────────────────────────────────────────────
    save_user_message(tg.id, text)

    # ── Попытка разобрать отчёт о тренировке ─────────────────────────────────
    if is_workout_report(text):
        parsed_workout = parse_workout_from_message(text)
        if parsed_workout:
            save_workout_from_parsed(tg.id, parsed_workout)

    if is_metrics_report(text):
        parsed_metrics = parse_metrics_from_message(text)
        if parsed_metrics:
            save_metrics_from_parsed(tg.id, parsed_metrics)

    # ── Авто-суммаризация / inactivity reset ─────────────────────────────────
    compress_result = await maybe_compress_context(tg.id)
    if compress_result == "reset":
        logger.info(f"[CTX] Inactivity reset applied for {tg.id}")
    elif compress_result == "compress":
        logger.info(f"[CTX] Token budget compression applied for {tg.id}")

    # ── Генерация ответа (стриминг) ───────────────────────────────────────────
    try:
        await update.message.chat.send_action("typing")
        context = build_layered_context(tg.id, text)
        bot = update.message.get_bot()
        response = await generate_chat_response_streaming(
            bot, update.message.chat_id, context, text
        )
        if response:
            save_ai_response(tg.id, response)
    except Exception as e:
        logger.error(f"Handler error for {tg.id}: {e}")
        await update.message.reply_text(
            "Что-то пошло не так. Попробуй ещё раз."
        )


async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик inline-кнопок."""
    query = update.callback_query
    await query.answer()
    data = query.data
    tg = query.from_user

    # ── Онбординг: цель ──────────────────────────────────────────────────────
    if data in GOAL_MAP:
        goal = GOAL_MAP[data]
        update_user(tg.id, goal=goal)
        await query.edit_message_text(
            f"Отлично! Цель: *{goal}*\n\nТеперь скажи — какой у тебя уровень подготовки?",
            parse_mode="Markdown",
            reply_markup=kb_fitness_level()
        )
        return

    # ── Онбординг: уровень ───────────────────────────────────────────────────
    if data in LEVEL_MAP:
        level = LEVEL_MAP[data]
        update_user(tg.id, fitness_level=level)
        level_names = {"beginner": "начинающий", "intermediate": "средний", "advanced": "продвинутый"}
        await query.edit_message_text(
            f"Записал. Уровень: *{level_names[level]}*\n\n"
            "Настройка завершена. 💪\n"
            "Буду присылать чек-ины утром, днём и вечером. "
            "Просто отвечай как привык.\n\n"
            "Режим на сегодня: /mode",
            parse_mode="Markdown"
        )
        return

    # ── Тренировка ────────────────────────────────────────────────────────────
    if data == "workout_done":
        await query.edit_message_text(
            "💪 Отлично! Расскажи как прошло — что делал, сколько времени, "
            "как ощущения?"
        )
        return

    if data == "workout_skipped":
        await query.edit_message_text(
            "Окей, записал. Что помешало? Завтра наверстаем."
        )
        return

    if data == "workout_pending":
        await query.edit_message_text(
            "Хорошо, ещё успеешь. Когда планируешь?"
        )
        return

    # ── Напоминание ───────────────────────────────────────────────────────────
    if data == "reminder_go":
        await query.edit_message_text("Отлично, иди! 🔥")
        return

    if data == "reminder_snooze":
        await query.edit_message_text("Напомню через 30 минут. ⏰")
        # TODO: реально запланировать повторное напоминание через 30 мин
        return

    if data == "reminder_skip":
        await query.edit_message_text(
            "Окей. Расскажи потом — почему не получилось."
        )
        return

    # ── Интенсивность ─────────────────────────────────────────────────────────
    if data.startswith("intensity_"):
        val = int(data.split("_")[1])
        await query.edit_message_text(
            f"Интенсивность {val}/10. Записал. 📝"
        )
        return

    # ── Энергия ───────────────────────────────────────────────────────────────
    if data.startswith("energy_"):
        val = int(data.split("_")[1])
        save_metrics_from_parsed = None  # lazy import
        from db.writer import save_metrics_from_parsed as smp
        smp(tg.id, {"energy": val})
        await query.edit_message_text(
            f"Энергия {val}/5. Записал."
        )
        return

    # ── Прочие ───────────────────────────────────────────────────────────────
    await query.edit_message_text("Принято.")


async def handle_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Голосовое сообщение → Whisper → текст → обрабатываем как обычное сообщение.
    Требует OPENAI_API_KEY в .env.
    """
    tg = update.effective_user

    if not OPENAI_API_KEY:
        await update.message.reply_text(
            "🎤 Голосовые сообщения пока не настроены. "
            "Добавь OPENAI_API_KEY в .env чтобы включить расшифровку."
        )
        return

    user = get_user(tg.id)
    if not user:
        await update.message.reply_text("Напиши /start чтобы начать.")
        return

    # ── Скачиваем голосовой файл ──────────────────────────────────────────────
    await update.message.reply_text("🎤 Слушаю...")
    voice_file = await update.message.voice.get_file()

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        await voice_file.download_to_drive(tmp_path)

        # ── Whisper транскрипция ──────────────────────────────────────────────
        import openai
        oai_client = openai.OpenAI(api_key=OPENAI_API_KEY)
        with open(tmp_path, "rb") as audio_f:
            transcript = oai_client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_f,
                language="ru",
            )
        text = transcript.text.strip()
        if not text:
            await update.message.reply_text("Не удалось распознать. Попробуй ещё раз.")
            return

        # ── Показываем что расслышали ─────────────────────────────────────────
        await update.message.reply_text(f"🎤 _«{text}»_", parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Whisper error for {tg.id}: {e}")
        await update.message.reply_text("⚠️ Ошибка распознавания голоса.")
        return
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    # ── Дальше обрабатываем точно как текстовое сообщение ────────────────────
    save_user_message(tg.id, text)

    if is_workout_report(text):
        parsed_workout = parse_workout_from_message(text)
        if parsed_workout:
            save_workout_from_parsed(tg.id, parsed_workout)

    if is_metrics_report(text):
        parsed_metrics = parse_metrics_from_message(text)
        if parsed_metrics:
            save_metrics_from_parsed(tg.id, parsed_metrics)

    await maybe_compress_context(tg.id)   # token budget / inactivity check

    try:
        await update.message.chat.send_action("typing")
        context = build_layered_context(tg.id, text)
        bot = update.message.get_bot()
        response = await generate_chat_response_streaming(
            bot, update.message.chat_id, context, text
        )
        if response:
            save_ai_response(tg.id, response)
    except Exception as e:
        logger.error(f"Voice handler AI error for {tg.id}: {e}")
        await update.message.reply_text("Что-то пошло не так.")


async def _handle_reset_confirmed(update: Update, telegram_id: int) -> None:
    """Полный сброс данных пользователя."""
    conn = get_connection()
    user = get_user(telegram_id)
    if not user:
        return
    uid = user["id"]
    tables = [
        "conversation_context", "reminders", "checkins",
        "weekly_summaries", "metrics", "workouts",
        "memory_athlete", "memory_nutrition", "memory_training", "memory_intelligence",
        "user_profile",
    ]
    for table in tables:
        conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (uid,))
    conn.execute("DELETE FROM user_profile WHERE telegram_id = ?", (telegram_id,))
    conn.commit()
    await update.message.reply_text(
        "✅ Все данные удалены. Напиши /start чтобы начать заново."
    )
