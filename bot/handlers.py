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
from ai.response_parser import detect_health_alert
from db.writer import (
    save_user_message, save_ai_response,
    save_metrics_from_parsed,
)
from bot.keyboards import (
    kb_fitness_level, kb_goal, kb_workout_time, kb_reminder,
    kb_health_check, kb_training_location, kb_training_days,
    kb_main_menu, kb_back_to_menu,
    kb_workout_duration, kb_workout_rpe, kb_workout_feeling, kb_workout_comment,
    kb_workout_done,
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
    2. Сжатие / сброс контекста по бюджету токенов
    3. Генерация ответа через AI — агентный цикл (Tool Use)
    4. Сохранить ответ AI в БД

    NOTE: Regex-парсеры (is_workout_report, is_metrics_report, is_nutrition_report)
    были отключены — теперь Claude сам записывает данные через Tool Use (Фаза 10.1).
    Это устраняет проблему двойной записи и даёт более точный парсинг.
    """
    # 1. Сохраняем входящее сообщение
    save_user_message(tg_id, text)

    # 2. Авто-суммаризация / inactivity reset
    compress_result = await maybe_compress_context(tg_id)
    if compress_result == "reset":
        logger.info(f"[CTX] Inactivity reset applied for {tg_id}")
    elif compress_result == "compress":
        logger.info(f"[CTX] Token budget compression applied for {tg_id}")

    # 3. Генерация ответа AI — агентный цикл (Tool Use, Фаза 10.1)
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
        # 4. Сохраняем ответ
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

    # ── Guided Workout Flow: обработка custom duration или текстового комментария ─
    wf = ctx.user_data.get("workout_flow", {})
    if wf.get("awaiting_custom_duration"):
        try:
            dur = int(text.strip())
            if not (5 <= dur <= 300):
                raise ValueError
            wf["duration_min"] = dur
            wf.pop("awaiting_custom_duration", None)
            ctx.user_data["workout_flow"] = wf
            await update.message.reply_text(
                f"⏱ {dur} мин — записал.\n\n"
                "Оцени интенсивность (RPE 1-10):\n"
                "_1 = прогулка, 5 = обычная, 10 = максимум_",
                parse_mode="Markdown",
                reply_markup=kb_workout_rpe()
            )
        except (ValueError, TypeError):
            await update.message.reply_text(
                "Напиши число от 5 до 300 (минуты тренировки). Например: 45"
            )
        return

    # Если в flow на шаге комментария — ждём текстовый ввод
    if wf and wf.get("feeling") and "notes" not in wf:
        wf["notes"] = text
        ctx.user_data["workout_flow"] = wf
        # Используем заглушку объекта для вызова save
        class _FakeQuery:
            async def edit_message_text(self, *a, **kw): pass
        try:
            from db.queries.workouts import log_workout
            from db.queries.user import get_user as _get_user
            import datetime as _dt
            user2 = _get_user(tg.id)
            label = wf.get("label", "тренировка")
            notes_parts = []
            if wf.get("feeling"):
                notes_parts.append(f"Ощущения: {wf['feeling']}")
            notes_parts.append(text)
            log_workout(
                user_id=user2["id"],
                date=_dt.date.today().isoformat(),
                mode=None,
                workout_type=wf.get("workout_type", "strength"),
                duration_min=wf.get("duration_min"),
                intensity=wf.get("intensity"),
                exercises=None,
                notes="; ".join(notes_parts),
                completed=True,
            )
            xp = 0
            try:
                from db.queries.gamification import add_xp
                xp = add_xp(user2["id"], 100, "workout", wf.get("workout_type"))
            except Exception as xe:
                logger.warning(f"[WF] XP award failed: {xe}")
            try:
                from db.queries.episodic import save_episode
                save_episode(
                    user_id=user2["id"],
                    episode_type="training",
                    summary=f"Тренировка '{label}' {wf.get('duration_min','?')} мин, ощущения: {wf.get('feeling','?')}. Комментарий: {text[:100]}",
                    tags=["training", wf.get("workout_type", "strength")],
                    importance=5,
                    ttl_days=30,
                )
            except Exception as ee:
                logger.warning(f"[WF] save_episode failed: {ee}")
            # Синхронизируем план (Фаза 15.1)
            try:
                from db.queries.training_plan import mark_plan_day_completed
                mark_plan_day_completed(user2["id"], _dt.date.today().isoformat())
            except Exception as pe:
                logger.warning(f"[WF] mark_plan_day_completed failed: {pe}")
            await update.message.reply_text(
                f"✅ Тренировка записана! +{xp} XP 🎉\n\n"
                f"📝 *{label}* · ощущения: {wf.get('feeling', '—')}\n"
                f"Комментарий: {text}\n\nХорошая работа! 💪",
                parse_mode="Markdown",
                reply_markup=kb_back_to_menu()
            )
        except Exception as e:
            logger.error(f"[WF] save from text failed for {tg.id}: {e}")
            await update.message.reply_text("❌ Не удалось сохранить. Попробуй ещё раз.")
        ctx.user_data.pop("workout_flow", None)
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

    # ── Утренний чек-ин: Готов / Дай время — Фаза 13.1 ──────────────────────
    if data == "morning_ready":
        user = get_user(tg.id)
        if not user:
            await query.edit_message_text("Напиши /start чтобы начать.")
            return
        from db.queries.training_plan import get_active_plan
        import json as _json
        plan = get_active_plan(user["id"])
        today_str = datetime.date.today().isoformat()
        today_workout = None
        if plan:
            try:
                days = _json.loads(plan["plan_json"])
                for day in days:
                    if day.get("date") == today_str:
                        today_workout = day
                        break
            except Exception as e:
                logger.warning(f"[MORNING_READY] Plan parse error for {tg.id}: {e}")

        if today_workout and today_workout.get("type") not in ("rest", "recovery", None):
            exercises = today_workout.get("exercises") or []
            ex_lines = []
            for ex in exercises:
                parts = [f"• {ex.get('name', '?')}"]
                if ex.get("sets") and ex.get("reps"):
                    parts.append(f"{ex['sets']}×{ex['reps']}")
                if ex.get("weight_kg_target"):
                    parts.append(f"@ {ex['weight_kg_target']} кг")
                if ex.get("note"):
                    parts.append(f"_{ex['note']}_")
                ex_lines.append(" ".join(parts))
            ex_text = "\n".join(ex_lines) if ex_lines else "_Без детализации_"
            label = today_workout.get("label") or today_workout.get("type") or "тренировка"
            note = today_workout.get("ai_note", "")
            note_text = f"\n\n💬 _{note}_" if note else ""
            # Прогрессия (Фаза 15.2)
            overload_text = _build_overload_hints(user["id"], exercises)
            text = (
                f"💪 *Сегодня: {label}*\n\n"
                f"{ex_text}"
                f"{overload_text}"
                f"{note_text}\n\n"
                "Когда закончишь — нажми «Сделал» 👇"
            )
            await query.edit_message_text(
                text, parse_mode="Markdown", reply_markup=kb_workout_done()
            )
        elif today_workout and today_workout.get("type") in ("rest", "recovery"):
            await query.edit_message_text(
                "🌿 Сегодня *день отдыха* по плану.\n"
                "Лёгкая прогулка или растяжка — идеально. Восстанавливайся! 💤",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text(
                "📋 Плана на сегодня пока нет.\n"
                "Новый план генерируется каждое *воскресенье в 20:00*.\n"
                "Хочешь составить прямо сейчас — напиши мне: _«составь план»_",
                parse_mode="Markdown",
                reply_markup=kb_back_to_menu()
            )
        return

    if data == "morning_later":
        await query.edit_message_text(
            "😴 Хорошо, отдохни. Напомню позже.\n"
            "Когда будешь готов — /plan покажет сегодняшнюю тренировку."
        )
        return

    # ── Тренировка ────────────────────────────────────────────────────────────
    if data == "workout_done":
        user = get_user(tg.id)
        # Берём тренировку дня из активного плана
        from db.queries.training_plan import get_active_plan
        import json as _json
        plan = get_active_plan(user["id"]) if user else None
        today_str = datetime.date.today().isoformat()
        today_workout = None
        if plan:
            try:
                days_list = _json.loads(plan["plan_json"])
                for d in days_list:
                    if d.get("date") == today_str:
                        today_workout = d
                        break
            except Exception as e:
                logger.warning(f"[WF] Plan parse error for {tg.id}: {e}")
        # Инициализируем Guided Flow
        ctx.user_data["workout_flow"] = {
            "workout_type": (today_workout.get("type") or "strength") if today_workout else "strength",
            "label": (today_workout.get("label") or today_workout.get("type") or "тренировка") if today_workout else "тренировка",
            "exercises": (today_workout.get("exercises") or []) if today_workout else [],
        }
        label = ctx.user_data["workout_flow"]["label"]
        await query.edit_message_text(
            f"💪 *{label}*\n\nСколько времени заняла тренировка?",
            parse_mode="Markdown",
            reply_markup=kb_workout_duration()
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

    # ── Guided Workout Flow (wf:*) — Фаза 13.2 ───────────────────────────────
    if data.startswith("wf:"):
        await _handle_workout_flow(query, ctx, tg, data)
        return

    # ── Quick Meal Presets (meal:*) — Фаза 15.4 ──────────────────────────────
    if data.startswith("meal:"):
        await _handle_meal_callback(query, ctx, tg, data[5:])
        return

    # ── Графики (chart:*) — Фаза 16.2 ────────────────────────────────────────
    if data.startswith("chart:"):
        await _handle_chart_callback(query, ctx, tg, data[6:])
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


# ═══════════════════════════════════════════════════════════════════════════
# PROGRESSIVE OVERLOAD HINTS — Фаза 15.2
# ═══════════════════════════════════════════════════════════════════════════

def _build_overload_hints(user_id: int, exercises: list) -> str:
    """
    Для каждого упражнения из плана смотрит последний результат.
    Возвращает строку-подсказку для прогрессии (или пустую строку).
    Показывает макс. 3 упражнения чтобы не засорять сообщение.
    """
    from db.queries.exercises import get_exercise_last_result
    lines = []
    checked = 0
    for ex in exercises:
        name = ex.get("name", "")
        if not name or checked >= 3:
            break
        target_weight = ex.get("weight_kg_target")
        last = get_exercise_last_result(user_id, name)
        if not last:
            continue
        checked += 1
        last_sets = last.get("sets")
        last_reps = last.get("reps")
        last_weight = last.get("weight_kg")
        # Форматируем прошлый результат
        last_str = name
        parts = []
        if last_sets and last_reps:
            parts.append(f"{last_sets}×{last_reps}")
        if last_weight:
            parts.append(f"@ {last_weight} кг")
        if parts:
            last_str = " ".join(parts)
        # Подсказка по прогрессии
        hint = ""
        if last_weight and target_weight and last_weight >= float(target_weight):
            next_w = round(last_weight + 2.5, 1)
            hint = f" → попробуй {next_w} кг 💪"
        elif last_weight and target_weight and last_weight < float(target_weight):
            hint = f" → цель {target_weight} кг"
        elif last_reps:
            hint = f" → добавь 1 повтор"
        if hint:
            lines.append(f"  _{name}: {last_str}{hint}_")
    if not lines:
        return ""
    return "\n📈 *Прогрессия:*\n" + "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# GUIDED WORKOUT FLOW — Фаза 13.2
# ═══════════════════════════════════════════════════════════════════════════

async def _handle_workout_flow(query, ctx, tg, data: str) -> None:
    """Пошаговая запись тренировки через кнопки."""
    parts = data.split(":")
    if len(parts) < 2:
        return
    step = parts[1]
    value = parts[2] if len(parts) > 2 else None

    wf = ctx.user_data.get("workout_flow", {})

    # ── Шаг 1: длительность ───────────────────────────────────────────────
    if step == "dur":
        if value == "custom":
            wf["awaiting_custom_duration"] = True
            ctx.user_data["workout_flow"] = wf
            await query.edit_message_text(
                "⏱ Напиши длительность в минутах (например: 50):"
            )
            return
        wf["duration_min"] = int(value)
        wf.pop("awaiting_custom_duration", None)
        ctx.user_data["workout_flow"] = wf
        await query.edit_message_text(
            f"⏱ {value} мин — записал.\n\n"
            "Оцени интенсивность (RPE 1-10):\n"
            "_1 = прогулка, 5 = обычная, 10 = максимум_",
            parse_mode="Markdown",
            reply_markup=kb_workout_rpe()
        )

    # ── Шаг 2: интенсивность (RPE) ────────────────────────────────────────
    elif step == "rpe":
        wf["intensity"] = int(value)
        ctx.user_data["workout_flow"] = wf
        await query.edit_message_text(
            f"💥 RPE {value}/10.\n\nКак ощущения?",
            reply_markup=kb_workout_feeling()
        )

    # ── Шаг 3: ощущения ───────────────────────────────────────────────────
    elif step == "feel":
        feeling_map = {
            "great": "отлично 💪",
            "ok":    "нормально 😐",
            "hard":  "тяжело 😓",
            "pain":  "боль/дискомфорт 🤕",
        }
        wf["feeling"] = feeling_map.get(value, value)
        wf["feeling_key"] = value
        ctx.user_data["workout_flow"] = wf
        await query.edit_message_text(
            f"Ощущения: {wf['feeling']}.\n\n"
            "Хочешь добавить комментарий? Напиши или нажми кнопку:",
            reply_markup=kb_workout_comment()
        )

    # ── Шаг 4: комментарий → сохранение ──────────────────────────────────
    elif step == "comment":
        wf["notes"] = "" if value == "skip" else value
        ctx.user_data["workout_flow"] = wf
        await _save_workout_from_flow(query, ctx, tg, wf)
        ctx.user_data.pop("workout_flow", None)


async def _save_workout_from_flow(query, ctx, tg, wf: dict) -> None:
    """Сохраняет тренировку из guided flow в БД."""
    import datetime as _dt
    from db.queries.user import get_user as _get_user
    from db.queries.workouts import log_workout

    user = _get_user(tg.id)
    if not user:
        await query.edit_message_text("❌ Профиль не найден. Напиши /start")
        return

    today = _dt.date.today().isoformat()
    label = wf.get("label", "тренировка")
    workout_type = wf.get("workout_type", "strength")
    duration_min = wf.get("duration_min")
    intensity = wf.get("intensity")

    notes_parts = []
    if wf.get("feeling"):
        notes_parts.append(f"Ощущения: {wf['feeling']}")
    if wf.get("notes"):
        notes_parts.append(wf["notes"])
    notes = "; ".join(notes_parts) if notes_parts else None

    try:
        log_workout(
            user_id=user["id"],
            date=today,
            mode=None,
            workout_type=workout_type,
            duration_min=duration_min,
            intensity=intensity,
            exercises=None,
            notes=notes,
            completed=True,
        )
    except Exception as e:
        logger.error(f"[WF] log_workout failed for {tg.id}: {e}")
        await query.edit_message_text("❌ Не удалось записать тренировку. Попробуй ещё раз.")
        return

    # Синхронизируем план — помечаем день как выполненный (Фаза 15.1)
    try:
        from db.queries.training_plan import mark_plan_day_completed
        mark_plan_day_completed(user["id"], today)
    except Exception as e:
        logger.warning(f"[WF] mark_plan_day_completed failed for {tg.id}: {e}")

    # XP за тренировку
    xp_awarded = 0
    try:
        from db.queries.gamification import add_xp
        xp_awarded = add_xp(user["id"], 100, "workout", workout_type)
    except Exception as e:
        logger.warning(f"[WF] XP award failed for {tg.id}: {e}")

    # Сохраняем эпизод в память
    try:
        from db.queries.episodic import save_episode
        save_episode(
            user_id=user["id"],
            episode_type="training",
            summary=f"Тренировка '{label}' {duration_min or '?'} мин, RPE {intensity or '?'}/10, ощущения: {wf.get('feeling', '?')}",
            tags=["training", workout_type],
            importance=5,
            ttl_days=30,
        )
    except Exception as e:
        logger.warning(f"[WF] save_episode failed for {tg.id}: {e}")

    # Если боль — запросить подробности
    if wf.get("feeling_key") == "pain":
        await query.edit_message_text(
            f"✅ Тренировка записана! +{xp_awarded} XP\n\n"
            "⚠️ Ты отметил боль/дискомфорт.\n"
            "Расскажи подробнее — что и где болит?\n"
            "_Важно для корректировки плана._",
            parse_mode="Markdown"
        )
        return

    summary = f"📝 *{label}*"
    if duration_min:
        summary += f" · {duration_min} мин"
    if intensity:
        summary += f" · RPE {intensity}/10"

    await query.edit_message_text(
        f"✅ Тренировка записана! +{xp_awarded} XP 🎉\n\n"
        f"{summary}\n"
        f"Ощущения: {wf.get('feeling', '—')}\n\n"
        "Хорошая работа! 💪",
        parse_mode="Markdown",
        reply_markup=kb_back_to_menu()
    )


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

    # ── Календарь тренировок (Фаза 13.6) ────────────────────────────────────
    if action == "calendar":
        if not user:
            await query.answer("Нет данных. Напиши /start", show_alert=True)
            return
        import json as _cj
        from db.queries.training_plan import get_active_plan
        plan = get_active_plan(user["id"])
        if not plan:
            await query.edit_message_text(
                "📅 *Календарь тренировок*\n\n"
                "На эту неделю план не сгенерирован.\n"
                "Воскресным вечером Алекс составит расписание 📋",
                parse_mode="Markdown",
                reply_markup=kb_back_to_menu(),
            )
            return
        try:
            days_list = _cj.loads(plan["plan_json"])
        except Exception:
            await query.answer("Ошибка чтения плана", show_alert=True)
            return

        today_str = datetime.date.today().isoformat()
        type_icons = {
            "strength": "💪", "cardio": "🏃", "hiit": "⚡",
            "mobility": "🧘", "rest": "😴", "recovery": "🌿",
        }
        workouts_done = plan.get("workouts_completed", 0)
        workouts_total = plan.get("workouts_planned", 0)

        try:
            week_d = datetime.date.fromisoformat(plan["week_start"])
            week_end = week_d + datetime.timedelta(days=6)
            week_label = f"{week_d.strftime('%d.%m')}–{week_end.strftime('%d.%m')}"
        except Exception:
            week_label = plan.get("week_start", "")

        lines = [
            f"🗓 *Календарь недели* ({week_label})",
            f"Прогресс: {workouts_done}/{workouts_total} тренировок\n",
        ]
        for day in days_list:
            dtype = day.get("type", "rest")
            icon = type_icons.get(dtype, "📅")
            weekday = day.get("weekday", "")
            label = day.get("label", dtype)
            date_str = day.get("date", "")
            completed = day.get("completed", False)

            try:
                date_fmt = datetime.date.fromisoformat(date_str).strftime("%d.%m")
            except Exception:
                date_fmt = date_str

            # Сегодня — выделяем
            is_today = date_str == today_str
            if completed:
                mark = "✅"
            elif is_today and dtype not in ("rest", "recovery"):
                mark = "➡️"
            else:
                mark = "⬜"

            line = f"{mark} *{weekday}* {date_fmt} — {icon} {label}"
            if is_today and dtype not in ("rest", "recovery") and not completed:
                line += " ← сегодня"
            lines.append(line)

            # Показываем упражнения только для сегодняшнего дня
            if is_today and dtype not in ("rest", "recovery"):
                exercises = day.get("exercises") or []
                for ex in exercises[:4]:
                    name = ex.get("name", "")
                    sets = ex.get("sets")
                    reps = ex.get("reps")
                    weight = ex.get("weight_kg_target")
                    parts = [f"  • {name}"]
                    if sets and reps:
                        parts.append(f"{sets}×{reps}")
                    if weight:
                        parts.append(f"@{weight}кг")
                    lines.append(" ".join(parts))
                if len(exercises) > 4:
                    lines.append(f"  • … ещё {len(exercises) - 4}")

        from bot.keyboards import kb_plan_quick
        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=kb_plan_quick(),
        )
        return

    await query.answer("Неизвестное действие", show_alert=True)


async def _handle_meal_callback(query, ctx, tg, action: str) -> None:
    """
    Быстрое логирование приёма пищи по пресету (meal:*) — Фаза 15.4.
    action: preset_id (grechka/ovsyanka/tvorog/eggs/protein) или 'quick' (показать меню).
    """
    from config import QUICK_MEAL_PRESETS
    from bot.keyboards import kb_quick_meals, kb_today_quick

    # meal:quick — показываем меню пресетов
    if action == "quick":
        await query.edit_message_text(
            "🍽 *Быстрый приём пищи*\n\nВыбери что ел — записываю сразу:",
            parse_mode="Markdown",
            reply_markup=kb_quick_meals(),
        )
        return

    preset = QUICK_MEAL_PRESETS.get(action)
    if not preset:
        await query.answer("Неизвестный пресет", show_alert=True)
        return

    user = get_user(tg.id)
    if not user:
        await query.answer("Напиши /start", show_alert=True)
        return

    try:
        from db.queries.nutrition import log_nutrition_day, get_today_nutrition
        import datetime as _dt

        today = _dt.date.today().isoformat()
        existing = get_today_nutrition(user["id"])

        # Если запись уже есть — добавляем к существующему (накопительный учёт)
        if existing:
            new_cal  = (existing.get("calories")  or 0) + preset["calories"]
            new_prot = (existing.get("protein_g") or 0) + preset["protein_g"]
            new_fat  = (existing.get("fat_g")     or 0) + preset["fat_g"]
            new_carb = (existing.get("carbs_g")   or 0) + preset["carbs_g"]
            # Обновляем meal_notes — добавляем к списку
            prev_notes = existing.get("meal_notes") or ""
            new_notes = f"{prev_notes}, {preset['label']}" if prev_notes else preset["label"]
            log_nutrition_day(
                user["id"], date=today,
                calories=new_cal, protein_g=new_prot, fat_g=new_fat, carbs_g=new_carb,
                meal_notes=new_notes,
            )
            await query.edit_message_text(
                f"✅ *{preset['label']}* добавлен!\n\n"
                f"Сегодня итого: *{new_cal} ккал* · Б{new_prot}г · Ж{new_fat}г · У{new_carb}г\n\n"
                "Добавить ещё один приём?",
                parse_mode="Markdown",
                reply_markup=kb_quick_meals(),
            )
        else:
            log_nutrition_day(
                user["id"], date=today,
                calories=preset["calories"],
                protein_g=preset["protein_g"],
                fat_g=preset["fat_g"],
                carbs_g=preset["carbs_g"],
                meal_notes=preset["label"],
            )
            await query.edit_message_text(
                f"✅ *{preset['label']}* записан!\n\n"
                f"*{preset['calories']} ккал* · Б{preset['protein_g']}г · Ж{preset['fat_g']}г · У{preset['carbs_g']}г\n\n"
                "Добавить ещё один приём?",
                parse_mode="Markdown",
                reply_markup=kb_quick_meals(),
            )
        logger.info(f"[MEAL] Preset '{action}' logged for {tg.id}")
    except Exception as e:
        logger.error(f"[MEAL] Failed to log preset '{action}' for {tg.id}: {e}")
        await query.answer("Ошибка записи. Попробуй ещё раз.", show_alert=True)


async def _handle_chart_callback(query, ctx, tg, chart_type: str) -> None:
    """
    Генерирует и отправляет график (chart:*) — Фаза 16.2.

    chart_type: weight | strength | intensity | sleep | fitness | xp
    """
    from analytics.charts import build_chart, CHART_REGISTRY
    from bot.keyboards import kb_stats_quick

    user = get_user(tg.id)
    if not user:
        await query.answer("Напиши /start", show_alert=True)
        return

    entry = CHART_REGISTRY.get(chart_type)
    label = entry[0] if entry else chart_type

    await query.answer(f"Строю {label}…")

    try:
        buf = build_chart(chart_type, user["id"])
    except Exception as e:
        logger.error(f"[CHART] build_chart({chart_type}) for {tg.id}: {e}")
        buf = None

    if buf is None:
        await query.message.reply_text(
            f"📊 Недостаточно данных для графика «{label}».\n"
            "Продолжай тренироваться — данные накопятся! 💪",
            reply_markup=kb_stats_quick(),
        )
        return

    caption = f"📊 *{label}*"
    await query.message.reply_photo(
        photo=buf,
        caption=caption,
        parse_mode="Markdown",
        reply_markup=kb_stats_quick(),
    )
    logger.info(f"[CHART] {chart_type} sent to {tg.id}")


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
