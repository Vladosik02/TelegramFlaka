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
from ai.client import generate_chat_response_streaming, generate_agent_response
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
    kb_health_check, kb_training_location, kb_training_days,
    kb_main_menu, kb_back_to_menu,
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
DAYS_MAP = {
    "days_3x":    ["пн", "ср", "пт"],
    "days_4x":    ["пн", "вт", "чт", "пт"],
    "days_5x":    ["пн", "вт", "ср", "чт", "пт"],
    "days_daily": ["пн", "вт", "ср", "чт", "пт", "сб", "вс"],
    "days_flex":  [],
}
DAYS_LABELS = {
    "days_3x":    "3 раза в неделю",
    "days_4x":    "4 раза в неделю",
    "days_5x":    "5 раз в неделю",
    "days_daily": "ежедневно",
    "days_flex":  "как получится",
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


async def _process_user_input(
    tg_id: int,
    text: str,
    update: Update,
) -> None:
    """
    Общая логика обработки любого пользовательского ввода (текст или голос).
    Вызывается как из handle_message, так и из handle_voice.

    Порядок:
    1. Сохранить сообщение в БД
    2. Regex-парсинг тренировки / метрик / питания (fallback, пока нет Tool Use)
    3. Сжатие / сброс контекста по бюджету токенов
    4. Генерация ответа через AI (стриминг)
    5. Сохранить ответ AI в БД
    """
    # 1. Сохраняем входящее сообщение
    save_user_message(tg_id, text)

    # 2. Regex-парсеры (fallback до Tool Use в 10.1)
    if is_workout_report(text):
        parsed_workout = parse_workout_from_message(text)
        if parsed_workout:
            save_workout_from_parsed(tg_id, parsed_workout)

    if is_metrics_report(text):
        parsed_metrics = parse_metrics_from_message(text)
        if parsed_metrics:
            save_metrics_from_parsed(tg_id, parsed_metrics)

    if is_nutrition_report(text):
        parsed_nutrition = parse_nutrition_from_message(text)
        if parsed_nutrition:
            save_nutrition_from_parsed(tg_id, parsed_nutrition)

    # 3. Авто-суммаризация / inactivity reset
    compress_result = await maybe_compress_context(tg_id)
    if compress_result == "reset":
        logger.info(f"[CTX] Inactivity reset applied for {tg_id}")
    elif compress_result == "compress":
        logger.info(f"[CTX] Token budget compression applied for {tg_id}")

    # 4. Генерация ответа AI — агентный цикл (Tool Use, Фаза 10.1)
    try:
        await update.message.chat.send_action("typing")
        context = build_layered_context(tg_id, text)
        bot = update.message.get_bot()
        response = await generate_agent_response(
            bot=bot,
            chat_id=update.message.chat_id,
            context=context,
            user_message=text,
            tg_id=tg_id,
        )
        # 5. Сохраняем ответ
        if response:
            save_ai_response(tg_id, response)
    except Exception as e:
        logger.error(f"AI processing error for {tg_id}: {e}")
        await update.message.reply_text(
            "Что-то пошло не так. Попробуй ещё раз."
        )


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Основной обработчик текстовых сообщений."""
    tg = update.effective_user
    text = update.message.text.strip()

    # ── Ожидание текста рассылки (admin) ─────────────────────────────────────
    if ctx.user_data.get("admin_broadcast_pending"):
        from bot.admin import handle_admin_broadcast
        await handle_admin_broadcast(update, ctx)
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

    # ── Обработка ввода (парсинг + AI-ответ) ─────────────────────────────────
    await _process_user_input(tg.id, text, update)


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

    # ── Онбординг: место тренировки → спрашиваем дни ─────────────────────────
    if data in LOCATION_MAP:
        location = LOCATION_MAP[data]
        user = get_user(tg.id)
        if user:
            update_user(tg.id, training_location=location)
        label = LOCATION_LABELS[location]
        await query.edit_message_text(
            f"Тренируешься {label} — записал ✅\n\n"
            "Сколько дней в неделю планируешь тренироваться?",
            reply_markup=kb_training_days()
        )
        return

    # ── Онбординг: дни недели → завершение ───────────────────────────────────
    if data in DAYS_MAP:
        import json
        days = DAYS_MAP[data]
        label = DAYS_LABELS[data]
        user = get_user(tg.id)
        if user:
            upsert_training_intel(user["id"], preferred_days=json.dumps(days, ensure_ascii=False))
        await query.edit_message_text(
            f"Тренировки {label} — записал ✅\n\n"
            "Настройка завершена! 💪\n"
            "Буду присылать чек-ины и следить за прогрессом.\n\n"
            "Посмотри свой профиль: /profile\n"
            "Режим на сегодня: /mode",
            parse_mode="Markdown",
            reply_markup=kb_main_menu(),
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

    # ── Главное меню (menu:*) — Фаза 11 ──────────────────────────────────────
    if data.startswith("menu:"):
        await _handle_menu_callback(query, ctx, tg, data[5:])
        return

    # ── Сброс данных (reset:*) — Фаза 11 ─────────────────────────────────────
    if data.startswith("reset:"):
        action = data[6:]
        if action == "confirm":
            await _handle_reset_confirmed_inline(query, tg.id)
        else:
            await query.edit_message_text("Отмена. Данные не тронуты. 👍")
        return

    # ── Пауза (stop:*) — Фаза 11 ─────────────────────────────────────────────
    if data.startswith("stop:"):
        await _handle_stop_callback(query, ctx, tg, data[5:])
        return

    # ── Админ-панель (adm:*) ──────────────────────────────────────────────────
    if data.startswith("adm:"):
        from bot.admin import handle_admin_callback
        await handle_admin_callback(update, ctx, data[4:])
        return

    # ── Прочие ───────────────────────────────────────────────────────────────
    await query.edit_message_text("Принято.")


async def _handle_menu_callback(
    query, ctx: ContextTypes.DEFAULT_TYPE, tg, action: str
) -> None:
    """
    Обрабатывает все callback из главного меню (menu:*) — Фаза 11.
    Переиспользует логику команд через повторный вызов с искусственным update.
    """
    user = get_user(tg.id)

    # ── Главная страница меню ────────────────────────────────────────────────
    if action == "home":
        from config import get_trainer_mode
        mode = get_trainer_mode()
        mode_emoji = "🔥" if mode == "MAX" else "🌿"
        name = (user.get("name") or tg.first_name) if user else tg.first_name
        streak = get_streak(user["id"]) if user else 0
        streak_str = f"🔥 {streak} дней стрик\n" if streak else ""
        xp_str = ""
        try:
            from db.queries.gamification import get_user_level_info
            xp_info = get_user_level_info(user["id"]) if user else None
            if xp_info:
                xp_str = f"  {xp_info['level_name']} · {xp_info['total_xp']} XP\n"
        except Exception:
            pass
        text = (
            f"👋 Привет, *{name}*!\n"
            f"{mode_emoji} Режим: *{mode}*\n"
            f"{streak_str}"
            f"{xp_str}"
            "\nЧто будем делать?"
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb_main_menu())
        return

    # ── Статистика ──────────────────────────────────────────────────────────
    if action == "stats":
        if not user:
            await query.answer("Нет данных. Напиши /start", show_alert=True)
            return
        from db.queries.workouts import get_weekly_stats, get_streak
        from db.queries.stats import get_all_time_stats
        from config import get_trainer_mode
        from bot.keyboards import kb_stats_quick
        weekly = get_weekly_stats(user["id"])
        alltime = get_all_time_stats(user["id"])
        streak = get_streak(user["id"])
        mode = get_trainer_mode()
        mode_emoji = "🔥" if mode == "MAX" else "🌿"
        done = weekly['workouts_done']
        total = max(weekly['workouts_total'], 1)
        filled = min(10, round(done / total * 10))
        bar = "█" * filled + "░" * (10 - filled)
        text = (
            f"📊 *Статистика {user['name'] or 'атлета'}*\n"
            "━━━━━━━━━━━━━━━━━\n"
            "*Эта неделя:*\n"
            f"`[{bar}]` {done}/{total} тренировок\n"
            f"• Ср. интенсивность: *{weekly['avg_intensity']}/10*\n"
            f"• Всего минут: *{weekly['total_minutes']}*\n"
            f"• Ср. сон: *{weekly['avg_sleep']} ч*\n"
            f"• Ср. энергия: *{weekly['avg_energy']}/5*\n"
            "━━━━━━━━━━━━━━━━━\n"
            "*За всё время:*\n"
            f"• Тренировок: *{alltime['done_workouts']}*\n"
            f"• Стрик: 🔥 *{streak} дней*\n"
            "━━━━━━━━━━━━━━━━━\n"
            f"{mode_emoji} Режим сегодня: *{mode}*"
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb_stats_quick())
        return

    # ── История (с выбором периода) ──────────────────────────────────────────
    if action in ("history", "history_7", "history_14", "history_30", "history_90"):
        if not user:
            await query.answer("Нет данных. Напиши /start", show_alert=True)
            return
        days_map = {"history": 7, "history_7": 7, "history_14": 14, "history_30": 30, "history_90": 90}
        days = days_map[action]
        from bot.commands import _send_history
        # Отвечаем на callback, затем отправляем новое сообщение
        await query.answer()
        await _send_history(query.message, user, days)
        return

    # ── Ачивки ──────────────────────────────────────────────────────────────
    if action == "achievements":
        if not user:
            await query.answer("Нет данных. Напиши /start", show_alert=True)
            return
        from db.queries.gamification import format_achievements_message
        from bot.keyboards import kb_achievements_quick
        try:
            msg = format_achievements_message(user["id"])
        except Exception as e:
            logger.error(f"[MENU] achievements error: {e}")
            msg = "⚠️ Не удалось загрузить данные. Попробуй позже."
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_achievements_quick())
        return

    # ── Профиль — редирект на команду ───────────────────────────────────────
    if action in ("profile", "test", "plan", "setup", "export"):
        cmd_map = {
            "profile": "/profile",
            "test":    "/test",
            "plan":    "/plan",
            "setup":   "/setup",
            "export":  "/export",
        }
        await query.answer(f"Открываю {cmd_map[action]}", show_alert=False)
        await query.message.reply_text(
            f"Использую {cmd_map[action]} — секунду...",
        )
        # Запускаем соответствующую команду через message
        from bot import commands as cmds
        handler_map = {
            "profile": cmds.cmd_profile,
            "test":    cmds.cmd_test,
            "plan":    cmds.cmd_plan,
            "setup":   cmds.cmd_setup,
            "export":  cmds.cmd_export,
        }
        # Создаём mock update для команды
        class _MockUpdate:
            effective_user = tg
            message = query.message
        class _MockCtx:
            args = []
            user_data = ctx.user_data
            bot_data = ctx.bot_data
        await handler_map[action](_MockUpdate(), _MockCtx())
        return

    await query.answer("Неизвестное действие", show_alert=True)


async def _handle_stop_callback(query, ctx, tg, action: str) -> None:
    """Обрабатывает callback выбора паузы (stop:*) — Фаза 11."""
    from db.queries.user import deactivate_user
    from bot.keyboards import kb_back_to_menu

    if action == "indefinite":
        deactivate_user(tg.id)
        await query.edit_message_text(
            "Поставил на паузу. 🛑\n"
            "Напоминать не буду. Когда будешь готов — /start",
            reply_markup=kb_back_to_menu(),
        )
        return

    try:
        days = int(action)
    except ValueError:
        await query.answer("Ошибка", show_alert=True)
        return

    deactivate_user(tg.id)
    resume_at = datetime.datetime.now() + datetime.timedelta(days=days)
    scheduler = ctx.bot_data.get("scheduler")

    if scheduler:
        from db.queries.user import activate_user as _activate

        async def _resume(bot, telegram_id: int) -> None:
            _activate(telegram_id)
            try:
                await bot.send_message(chat_id=telegram_id,
                                       text="⏰ Пауза закончилась! Возобновляю работу. /start")
            except Exception:
                pass

        scheduler.add_job(
            _resume, "date",
            run_date=resume_at,
            args=[query.message.get_bot(), tg.id],
            id=f"resume_{tg.id}",
            replace_existing=True,
        )

    resume_str = resume_at.strftime("%d.%m.%Y")
    await query.edit_message_text(
        f"Поставил на паузу на *{days} дн.* 🛑\n"
        f"Автоматически вернусь *{resume_str}*.\n"
        "Если раньше — /start",
        parse_mode="Markdown",
        reply_markup=kb_back_to_menu(),
    )


async def _handle_reset_confirmed_inline(query, telegram_id: int) -> None:
    """Полный сброс данных пользователя через inline кнопку (Фаза 11)."""
    conn = get_connection()
    user = get_user(telegram_id)
    if not user:
        await query.edit_message_text("Данных не найдено.")
        return
    uid = user["id"]
    tables = [
        "conversation_context", "reminders", "checkins",
        "weekly_summaries", "metrics", "workouts",
        "memory_athlete", "memory_nutrition", "memory_training", "memory_intelligence",
        "user_profile",
    ]
    for table in tables:
        try:
            conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (uid,))
        except Exception:
            pass
    try:
        conn.execute("DELETE FROM user_profile WHERE telegram_id = ?", (telegram_id,))
    except Exception:
        pass
    conn.commit()
    await query.edit_message_text(
        "✅ Все данные удалены.\nНапиши /start чтобы начать заново."
    )


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
    await _process_user_input(tg.id, text, update)


async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработчик фото — Claude Vision API (Фаза 10.3).

    Сценарии:
    1. Фото еды → Claude оценивает КБЖУ и сохраняет в nutrition_log
    2. Фото прогресса → Claude анализирует изменения тела
    3. Любое другое фото → Claude описывает и комментирует контекстно
    """
    import base64
    tg = update.effective_user

    user = get_user(tg.id)
    if not user:
        await update.message.reply_text("Напиши /start чтобы начать.")
        return

    # Берём самое большое фото из набора
    photo = update.message.photo[-1]
    caption = (update.message.caption or "").strip()

    status_msg = await update.message.reply_text("📸 Анализирую фото...")

    try:
        photo_file = await photo.get_file()
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name
        await photo_file.download_to_drive(tmp_path)

        with open(tmp_path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("utf-8")

        try:
            os.remove(tmp_path)
        except OSError:
            pass

        # Определяем тип фото по подписи
        cap_low = caption.lower()
        is_food = any(w in cap_low for w in [
            "еда", "ем", "поел", "обед", "ужин", "завтрак", "блюдо",
            "food", "meal", "eat", "калор", "кбжу",
        ])
        is_progress = any(w in cap_low for w in [
            "прогресс", "форм", "тело", "progress", "physique",
            "до", "после", "результат",
        ])

        if is_food:
            vision_prompt = (
                "Ты — спортивный диетолог. Проанализируй фото еды.\n"
                "Оцени примерное КБЖУ. Начни ответ строкой:\n"
                "'Ккал: ~[N], Б: ~[N]г, Ж: ~[N]г, У: ~[N]г'\n"
                "Затем 2-3 предложения о питательности и рекомендации тренера."
            )
            if caption:
                vision_prompt += f"\nПользователь написал: '{caption}'"
        elif is_progress:
            vision_prompt = (
                "Ты — персональный тренер Алекс. Проанализируй фото прогресса атлета.\n"
                "Опиши видимые изменения в форме и рельефе. "
                "Будь конкретным и мотивирующим. 3-5 предложений."
            )
            if caption:
                vision_prompt += f"\nКонтекст: '{caption}'"
        else:
            vision_prompt = (
                "Ты — персональный тренер Алекс. Пользователь прислал фото.\n"
                "Если связано с тренировками, едой или здоровьем — "
                "прокомментируй как тренер. Иначе ответь дружелюбно."
            )
            if caption:
                vision_prompt += f"\nПодпись: '{caption}'"

        from ai.client import get_async_client
        from config import MODEL
        async_client = get_async_client()

        response = await async_client.messages.create(
            model=MODEL,
            max_tokens=600,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_data,
                        },
                    },
                    {"type": "text", "text": vision_prompt},
                ],
            }]
        )

        reply_text = response.content[0].text.strip()

        # Авто-сохранение КБЖУ из фото еды
        if is_food:
            import re as _re
            cal_m  = _re.search(r"Ккал[:\s~]*(\d+)", reply_text, _re.IGNORECASE)
            prot_m = _re.search(r"Б[:\s~]*(\d+)\s*г",  reply_text, _re.IGNORECASE)
            fat_m  = _re.search(r"Ж[:\s~]*(\d+)\s*г",  reply_text, _re.IGNORECASE)
            carb_m = _re.search(r"У[:\s~]*(\d+)\s*г",  reply_text, _re.IGNORECASE)

            nut = {}
            if cal_m:  nut["calories"]  = int(cal_m.group(1))
            if prot_m: nut["protein_g"] = float(prot_m.group(1))
            if fat_m:  nut["fat_g"]     = float(fat_m.group(1))
            if carb_m: nut["carbs_g"]   = float(carb_m.group(1))

            if nut:
                save_nutrition_from_parsed(tg.id, nut)
                reply_text += "\n\n✅ _КБЖУ записаны в журнал_"
                logger.info(f"[VISION] food KBJU saved for {tg.id}: {nut}")

        await status_msg.edit_text(reply_text, parse_mode="Markdown")
        save_user_message(tg.id, f"[фото]{': ' + caption if caption else ''}")
        save_ai_response(tg.id, reply_text)

    except Exception as e:
        logger.error(f"[VISION] error for {tg.id}: {e}")
        await status_msg.edit_text(
            "⚠️ Не удалось проанализировать фото. Попробуй ещё раз."
        )


# _handle_reset_confirmed removed in Фаза 11 — replaced by _handle_reset_confirmed_inline
