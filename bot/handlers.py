"""
bot/handlers.py — Обработчики текстовых сообщений, голосовых и callback'ов.
"""
import os
import logging
import tempfile
from telegram import Update
from telegram.ext import ContextTypes

import datetime
from db.queries.user import get_user, create_user, update_user
from db.queries.memory import upsert_athlete_card, upsert_training_intel
from db.queries.fitness_metrics import (
    save_fitness_test, get_last_fitness_test,
    normalize_pushups, normalize_squats, normalize_plank,
    compute_fitness_score, get_fitness_level,
)
from db.connection import get_connection
from ai.context_builder import build_layered_context, maybe_compress_context
from ai.client import generate_chat_response_streaming
from ai.response_parser import (
    detect_health_alert, is_workout_report, is_metrics_report, is_nutrition_report,
    parse_workout_from_message, parse_metrics_from_message, parse_nutrition_from_message
)
from db.writer import (
    save_user_message, save_ai_response,
    save_workout_from_parsed, save_metrics_from_parsed, save_nutrition_from_parsed
)
from bot.keyboards import (
    kb_fitness_level, kb_goal, kb_workout_time, kb_reminder,
    kb_health_check, kb_training_location,
)
from config import (
    HEALTH_KEYWORDS, OPENAI_API_KEY,
    TEST_MAX_PUSHUPS, TEST_MAX_SQUATS, TEST_MAX_PLANK_SEC,
)

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
TIME_MAP = {
    "time_morning":  "morning",
    "time_evening":  "evening",
    "time_flexible": "flexible",
}
TIME_LABELS = {
    "morning":  "утром 🌅",
    "evening":  "вечером 🌙",
    "flexible": "гибко ⏰",
}
LOCATION_MAP = {
    "location_home":     "home",
    "location_gym":      "gym",
    "location_outdoor":  "outdoor",
    "location_flexible": "flexible",
}
LOCATION_LABELS = {
    "home":     "дома 🏠",
    "gym":      "в зале 🏋️",
    "outdoor":  "на улице 🌳",
    "flexible": "по-разному 🔄",
}


# ═══════════════════════════════════════════════════════════════════════════
# ОНБОРДИНГ — state machine (age → weight → height → workout_time)
# Состояние хранится в ctx.user_data["onboarding_step"]
# ═══════════════════════════════════════════════════════════════════════════

async def _handle_onboarding_step(
    update, ctx, tg, step: str, text: str
) -> None:
    """Обрабатывает ввод во время расширенного онбординга."""
    user = get_user(tg.id)
    if not user:
        ctx.user_data.pop("onboarding_step", None)
        return
    uid = user["id"]
    skip = text.strip().lower() in ("/skip", "skip", "пропустить", "-")

    # ── Шаг 1: возраст ────────────────────────────────────────────────────
    if step == "awaiting_age":
        if not skip:
            try:
                age = int(text.strip())
                if not (10 <= age <= 100):
                    raise ValueError
            except ValueError:
                await update.message.reply_text(
                    "Введи целое число от 10 до 100. Например: 25\n"
                    "Или напиши /skip чтобы пропустить."
                )
                return
            upsert_athlete_card(uid, age=age)
            ack = f"Записал — {age} лет ✅\n\n"
        else:
            ack = ""

        ctx.user_data["onboarding_step"] = "awaiting_weight"
        await update.message.reply_text(
            ack + "*Текущий вес* в кг? (например: 75 или 75.5)\n"
            "Или /skip",
            parse_mode="Markdown"
        )

    # ── Шаг 2: вес ────────────────────────────────────────────────────────
    elif step == "awaiting_weight":
        if not skip:
            try:
                weight = float(text.strip().replace(",", "."))
                if not (30.0 <= weight <= 300.0):
                    raise ValueError
            except ValueError:
                await update.message.reply_text(
                    "Введи число от 30 до 300. Например: 75 или 75.5\n"
                    "Или /skip"
                )
                return
            save_metrics_from_parsed(tg.id, {"weight_kg": weight})
            ack = f"Записал — {weight} кг ✅\n\n"
        else:
            ack = ""

        ctx.user_data["onboarding_step"] = "awaiting_height"
        await update.message.reply_text(
            ack + "*Рост* в см? (например: 180)\n"
            "Или /skip",
            parse_mode="Markdown"
        )

    # ── Шаг 3: рост ───────────────────────────────────────────────────────
    elif step == "awaiting_height":
        if not skip:
            try:
                height = float(text.strip().replace(",", "."))
                if not (100.0 <= height <= 250.0):
                    raise ValueError
            except ValueError:
                await update.message.reply_text(
                    "Введи число от 100 до 250. Например: 180\n"
                    "Или /skip"
                )
                return
            upsert_athlete_card(uid, height_cm=height)
            ack = f"Записал — {int(height)} см ✅\n\n"
        else:
            ack = ""

        ctx.user_data.pop("onboarding_step", None)
        await update.message.reply_text(
            ack + "Есть ли у тебя травмы или ограничения по здоровью,\n"
            "которые нужно учитывать при тренировках?",
            reply_markup=kb_health_check()
        )

    # ── Шаг 4: текстовое описание ограничений ─────────────────────────────
    elif step == "awaiting_health_text":
        if not skip:
            import json
            # Сохраняем как JSON-список из одной строки
            injuries = json.dumps([text.strip()[:200]], ensure_ascii=False)
            update_user(tg.id, injuries=injuries)
            ack = "Записал ✅\n\n"
        else:
            ack = ""

        ctx.user_data.pop("onboarding_step", None)
        await update.message.reply_text(
            ack + "Когда тебе удобнее тренироваться?",
            reply_markup=kb_workout_time()
        )


# ═══════════════════════════════════════════════════════════════════════════
# ФИТНЕС-ТЕСТ — state machine (pushups → squats → plank → hr → results)
# Состояние хранится в ctx.user_data["test_step"]
# ═══════════════════════════════════════════════════════════════════════════

async def _handle_test_step(
    update, ctx, tg, step: str, text: str
) -> None:
    """Обрабатывает ввод результатов фитнес-теста."""
    user = get_user(tg.id)
    if not user:
        ctx.user_data.pop("test_step", None)
        ctx.user_data.pop("test_data", None)
        return

    uid = user["id"]
    cancel = text.strip().lower() in ("/cancel", "cancel", "отмена")
    if cancel:
        ctx.user_data.pop("test_step", None)
        ctx.user_data.pop("test_data", None)
        await update.message.reply_text("Тест отменён.")
        return

    data = ctx.user_data.get("test_data", {})

    # ── Шаг 1: отжимания ────────────────────────────────────────────────────
    if step == "pushups":
        try:
            val = int(text.strip())
            if not (0 <= val <= TEST_MAX_PUSHUPS):
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                f"Введи целое число от 0 до {TEST_MAX_PUSHUPS}.\n"
                "Или /cancel для отмены."
            )
            return

        data["pushups"] = val
        score = normalize_pushups(val)
        data["pushups_score"] = score
        ctx.user_data["test_data"] = data
        ctx.user_data["test_step"] = "squats"

        await update.message.reply_text(
            f"Отжимания: *{val}* → {score:.0f}/100 ✅\n\n"
            "━━━━━━━━━━━━━━━━━\n"
            "*Тест 2/3 — Приседания*\n"
            "Максимальное количество приседаний\n"
            "без остановки, полная амплитуда.\n\n"
            "_Напиши результат числом._",
            parse_mode="Markdown",
        )

    # ── Шаг 2: приседания ────────────────────────────────────────────────────
    elif step == "squats":
        try:
            val = int(text.strip())
            if not (0 <= val <= TEST_MAX_SQUATS):
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                f"Введи целое число от 0 до {TEST_MAX_SQUATS}.\n"
                "Или /cancel для отмены."
            )
            return

        data["squats"] = val
        score = normalize_squats(val)
        data["squats_score"] = score
        ctx.user_data["test_data"] = data
        ctx.user_data["test_step"] = "plank"

        await update.message.reply_text(
            f"Приседания: *{val}* → {score:.0f}/100 ✅\n\n"
            "━━━━━━━━━━━━━━━━━\n"
            "*Тест 3/3 — Планка*\n"
            "Удерживай планку максимально долго.\n"
            "Засекай время сам или попроси кого-то.\n\n"
            "_Напиши результат в секундах._",
            parse_mode="Markdown",
        )

    # ── Шаг 3: планка ───────────────────────────────────────────────────────
    elif step == "plank":
        try:
            val = int(text.strip())
            if not (0 <= val <= TEST_MAX_PLANK_SEC):
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                f"Введи целое число от 0 до {TEST_MAX_PLANK_SEC} (секунд).\n"
                "Или /cancel для отмены."
            )
            return

        data["plank"] = val
        score = normalize_plank(val)
        data["plank_score"] = score
        ctx.user_data["test_data"] = data
        ctx.user_data["test_step"] = "hr"

        await update.message.reply_text(
            f"Планка: *{val} сек* → {score:.0f}/100 ✅\n\n"
            "━━━━━━━━━━━━━━━━━\n"
            "❤️ *ЧСС покоя* (опционально)\n"
            "Измерь пульс в покое (уд/мин).\n\n"
            "_Напиши число или /skip чтобы пропустить._",
            parse_mode="Markdown",
        )

    # ── Шаг 4: ЧСС покоя (опц.) → сохранение → результаты ──────────────────
    elif step == "hr":
        skip = text.strip().lower() in ("/skip", "skip", "пропустить", "-")
        resting_hr = None

        if not skip:
            try:
                resting_hr = int(text.strip())
                if not (30 <= resting_hr <= 220):
                    raise ValueError
            except ValueError:
                await update.message.reply_text(
                    "Введи число от 30 до 220 (уд/мин).\n"
                    "Или /skip чтобы пропустить."
                )
                return

        data["hr"] = resting_hr

        # ── Сохраняем результат ──────────────────────────────────────────────
        today = datetime.date.today().isoformat()
        row_id = save_fitness_test(
            user_id=uid,
            tested_at=today,
            max_pushups=data["pushups"],
            max_squats=data["squats"],
            plank_sec=data["plank"],
            resting_hr=resting_hr,
        )

        # ── Формируем результаты ─────────────────────────────────────────────
        f_score = compute_fitness_score(
            data["pushups_score"], data["squats_score"], data["plank_score"]
        )
        level = get_fitness_level(f_score)

        result_lines = [
            "✅ *Тест завершён!*",
            "",
            f"Отжимания: {data['pushups']} → *{data['pushups_score']:.0f}*/100",
            f"Приседания: {data['squats']} → *{data['squats_score']:.0f}*/100",
            f"Планка: {data['plank']}с → *{data['plank_score']:.0f}*/100",
        ]
        if resting_hr:
            result_lines.append(f"ЧСС покоя: {resting_hr} уд/мин")

        result_lines += [
            "",
            f"🏆 *Fitness Score: {f_score:.0f}/100*",
            f"Уровень: *{level}*",
        ]

        # ── Сравнение с предыдущим тестом ────────────────────────────────────
        history = get_last_fitness_test(uid)
        # history вернёт текущий тест, нам нужен предыдущий
        from db.queries.fitness_metrics import get_fitness_history
        all_tests = get_fitness_history(uid, limit=2)
        if len(all_tests) > 1:
            prev = all_tests[1]  # предыдущий (all_tests[0] = текущий)
            prev_score = prev["fitness_score"]
            delta = f_score - prev_score
            arrow = "📈" if delta > 0 else ("📉" if delta < 0 else "➡️")
            days_ago = (
                datetime.date.today()
                - datetime.date.fromisoformat(prev["tested_at"])
            ).days
            result_lines += [
                "",
                f"{arrow} Прошлый тест: {prev_score:.0f}/100 "
                f"({days_ago} дн. назад) → {'+' if delta > 0 else ''}{delta:.0f} очков",
            ]

        # ── Очищаем state machine ────────────────────────────────────────────
        ctx.user_data.pop("test_step", None)
        ctx.user_data.pop("test_data", None)

        await update.message.reply_text(
            "\n".join(result_lines),
            parse_mode="Markdown",
        )


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

    # ── Онбординг state machine ───────────────────────────────────────────────
    onboarding_step = ctx.user_data.get("onboarding_step")
    if onboarding_step:
        await _handle_onboarding_step(update, ctx, tg, onboarding_step, text)
        return

    # ── Фитнес-тест state machine ──────────────────────────────────────────────
    test_step = ctx.user_data.get("test_step")
    if test_step:
        await _handle_test_step(update, ctx, tg, test_step, text)
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

    if is_nutrition_report(text):
        parsed_nutrition = parse_nutrition_from_message(text)
        if parsed_nutrition:
            save_nutrition_from_parsed(tg.id, parsed_nutrition)

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

    # ── Онбординг: уровень → запускаем расширенный сбор данных ──────────────
    if data in LEVEL_MAP:
        level = LEVEL_MAP[data]
        update_user(tg.id, fitness_level=level)
        level_names = {"beginner": "начинающий", "intermediate": "средний", "advanced": "продвинутый"}
        ctx.user_data["onboarding_step"] = "awaiting_age"
        await query.edit_message_text(
            f"Уровень: *{level_names[level]}* ✅\n\n"
            "Теперь пара вопросов для персонализации — "
            "чтобы давать точные рекомендации по нагрузке и питанию.\n\n"
            "*Сколько тебе лет?*\n"
            "Или напиши /skip",
            parse_mode="Markdown"
        )
        return

    # ── Онбординг: здоровье — всё ок ─────────────────────────────────────────
    if data == "health_ok":
        await query.edit_message_text(
            "Отлично, без ограничений ✅\n\n"
            "Когда тебе удобнее тренироваться?",
            reply_markup=kb_workout_time()
        )
        return

    # ── Онбординг: здоровье — есть ограничения ───────────────────────────────
    if data == "health_issues":
        ctx.user_data["onboarding_step"] = "awaiting_health_text"
        await query.edit_message_text(
            "Опиши коротко — что болит или что нельзя делать?\n"
            "Например: _колено — нет приседаний, спина — без становой_\n\n"
            "Или напиши /skip чтобы пропустить.",
            parse_mode="Markdown"
        )
        return

    # ── Онбординг: время тренировки → место ──────────────────────────────────
    if data in TIME_MAP:
        preferred_time = TIME_MAP[data]
        user = get_user(tg.id)
        if user:
            upsert_training_intel(user["id"], preferred_time=preferred_time)
        label = TIME_LABELS[preferred_time]
        await query.edit_message_text(
            f"Тренировки {label} — записал ✅\n\n"
            "Где обычно тренируешься?",
            reply_markup=kb_training_location()
        )
        return

    # ── Онбординг: место тренировки ──────────────────────────────────────────
    if data in LOCATION_MAP:
        location = LOCATION_MAP[data]
        user = get_user(tg.id)
        if user:
            update_user(tg.id, training_location=location)
        label = LOCATION_LABELS[location]
        await query.edit_message_text(
            f"Тренируешься {label} — записал ✅\n\n"
            "Настройка завершена! 💪\n"
            "Буду присылать чек-ины и следить за прогрессом.\n\n"
            "Посмотри свой профиль: /profile\n"
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
        scheduler = ctx.bot_data.get("scheduler")
        if scheduler:
            from scheduler.logic import send_snooze_reminder
            run_time = datetime.datetime.now() + datetime.timedelta(minutes=30)
            scheduler.add_job(
                send_snooze_reminder,
                "date",
                run_date=run_time,
                args=[query.message.bot, tg.id],
                id=f"snooze_{tg.id}",
                replace_existing=True,
            )
            await query.edit_message_text("⏰ Напомню через 30 минут. Отдыхай.")
        else:
            await query.edit_message_text("⏰ Напомню через 30 минут.")
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

    if is_nutrition_report(text):
        parsed_nutrition = parse_nutrition_from_message(text)
        if parsed_nutrition:
            save_nutrition_from_parsed(tg.id, parsed_nutrition)

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
