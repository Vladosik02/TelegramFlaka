"""
ai/client.py — Обёртка над Anthropic API (sync + async streaming + Tool Use).

Фаза 10.1 — добавлен агентный цикл generate_agent_response().
"""
import json
import logging
import anthropic
from config import ANTHROPIC_API_KEY, MODEL, MAX_TOKENS

logger = logging.getLogger(__name__)

# Sync client — для scheduler (плановые сообщения)
_client: anthropic.Anthropic | None = None
# Async client — для стриминга в Telegram-хендлерах
_async_client: anthropic.AsyncAnthropic | None = None

# Обновлять сообщение каждые N символов (баланс частоты и плавности)
STREAM_UPDATE_EVERY = 70


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def get_async_client() -> anthropic.AsyncAnthropic:
    global _async_client
    if _async_client is None:
        _async_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    return _async_client


# ── Синхронный запрос (scheduler, checkins) ──────────────────────────────────

def ask(system: str, messages: list[dict],
        max_tokens: int = MAX_TOKENS) -> str:
    """
    messages = [{"role": "user"/"assistant", "content": "..."}]
    Возвращает текст ответа.
    """
    client = get_client()
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        return response.content[0].text
    except anthropic.APIStatusError as e:
        logger.error(f"Anthropic API error {e.status_code}: {e.message}")
        return "⚠️ Ошибка API. Попробуй позже."
    except anthropic.APIConnectionError:
        logger.error("Anthropic connection error")
        return "⚠️ Нет связи с AI. Проверь интернет."
    except Exception as e:
        logger.error(f"Unexpected AI error: {e}")
        return "⚠️ Что-то пошло не так. Попробуй ещё раз."


# ── Асинхронный стриминг (обычный чат) ───────────────────────────────────────

async def ask_streaming(bot, chat_id: int,
                        system: str, messages: list[dict],
                        max_tokens: int = MAX_TOKENS) -> str:
    """
    Стримит ответ прямо в Telegram:
    - Отправляет placeholder «✍️»
    - Обновляет сообщение каждые STREAM_UPDATE_EVERY символов
    - Возвращает полный текст ответа
    """
    async_client = get_async_client()
    sent_msg = await bot.send_message(chat_id=chat_id, text="✍️")
    full_text = ""
    last_edit_len = 0

    try:
        async with async_client.messages.stream(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        ) as stream:
            async for chunk in stream.text_stream:
                full_text += chunk
                # Обновляем сообщение с курсором каждые N символов
                if len(full_text) - last_edit_len >= STREAM_UPDATE_EVERY:
                    try:
                        await sent_msg.edit_text(full_text + " ▍")
                        last_edit_len = len(full_text)
                    except Exception:
                        pass  # Telegram иногда отклоняет правки (rate limit)

        # Финальное обновление — убираем курсор
        if full_text:
            try:
                await sent_msg.edit_text(full_text)
            except Exception:
                pass

    except anthropic.APIStatusError as e:
        logger.error(f"Streaming API error {e.status_code}: {e.message}")
        await sent_msg.edit_text("⚠️ Ошибка API. Попробуй позже.")
        return ""
    except anthropic.APIConnectionError:
        logger.error("Streaming connection error")
        await sent_msg.edit_text("⚠️ Нет связи с AI.")
        return ""
    except Exception as e:
        logger.error(f"Unexpected streaming error: {e}")
        await sent_msg.edit_text("⚠️ Что-то пошло не так.")
        return ""

    return full_text


# ── Хелперы для разных контекстов ────────────────────────────────────────────

def generate_checkin_response(context: dict, user_message: str = None) -> str:
    """Генерация ответа на чек-ин (sync, scheduler)."""
    system = context.get("system", "")
    prompt = context.get("prompt", "")
    messages = [{"role": "user", "content": prompt}]
    if user_message:
        messages.append({"role": "user", "content": user_message})
    return ask(system, messages)


async def generate_chat_response_streaming(
        bot, chat_id: int, context: dict, user_message: str) -> str:
    """Стримящий ответ для обычного чата (async, Telegram handler)."""
    system = context.get("system", "")
    history = context.get("history", [])
    messages = list(history) + [{"role": "user", "content": user_message}]
    return await ask_streaming(bot, chat_id, system, messages)


def generate_chat_response(context: dict, user_message: str) -> str:
    """Sync-вариант — оставлен для обратной совместимости."""
    system = context.get("system", "")
    history = context.get("history", [])
    messages = list(history) + [{"role": "user", "content": user_message}]
    return ask(system, messages)


def generate_scheduled_message(context: dict) -> str:
    """Для плановых сообщений (утро/день/вечер/неделя) без user_message (sync, без Tool Use)."""
    system = context.get("system", "")
    prompt = context.get("prompt", "")
    messages = [{"role": "user", "content": prompt}]
    return ask(system, messages)


async def generate_scheduled_agent_message(
    bot, chat_id: int, context: dict, tg_id: int,
) -> str:
    """
    Агентный scheduled message с Tool Use (Agent Fix, Этап 7).
    Для утренних/дневных/вечерних чек-инов — Claude может записывать метрики
    из контекста и вызывать tools.

    Fallback: если agent loop не доступен → обычный sync generate_scheduled_message().
    """
    system = context.get("system", "")
    prompt = context.get("prompt", "")

    try:
        from ai.tools import ALL_TOOLS
        from ai.tool_executor import execute_tool_calls

        async_client = get_async_client()
        messages = [{"role": "user", "content": prompt}]

        for iteration in range(3):  # макс 3 итерации для scheduled
            response = await async_client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=system,
                tools=ALL_TOOLS,
                messages=messages,
            )

            text_blocks = [b for b in response.content if b.type == "text"]
            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

            if not tool_use_blocks or response.stop_reason == "end_turn":
                if text_blocks:
                    return "".join(b.text for b in text_blocks)
                break

            logger.info(
                f"[SCHED-AGENT] iter={iteration+1} tools={[t.name for t in tool_use_blocks]} "
                f"user={tg_id}"
            )

            messages.append({"role": "assistant", "content": response.content})

            tool_results = await execute_tool_calls(
                tg_id=tg_id,
                tool_uses=tool_use_blocks,
                bot=bot,
                chat_id=chat_id,
            )

            messages.append({"role": "user", "content": tool_results})

    except Exception as e:
        logger.warning(f"[SCHED-AGENT] Fallback to sync for user={tg_id}: {e}")
        return generate_scheduled_message(context)

    # Fallback если ничего не вернулось
    return generate_scheduled_message(context)


# ── Агентный цикл с Tool Use (Фаза 10.1) ─────────────────────────────────

MAX_AGENT_ITERATIONS = 5  # защита от бесконечного цикла


async def generate_agent_response(
    bot,
    chat_id: int,
    context: dict,
    user_message: str,
    tg_id: int,
    tools: list[dict] = None,
) -> str:
    """
    Агентный цикл с Claude Tool Use:
    user msg → Claude → [tool_use] → execute → Claude → [final text]

    Алгоритм:
    1. Отправляем placeholder «✍️»
    2. Первый запрос к Claude с инструментами
    3. Если Claude возвращает tool_use — выполняем инструменты, добавляем результаты
    4. Повторяем до получения end_turn (только текст) или MAX_AGENT_ITERATIONS
    5. Стримим финальный текстовый ответ

    Graceful degradation: если ошибка Tool Use — fallback на обычный стриминг.
    """
    if tools is None:
        from ai.tools import ALL_TOOLS
        tools = ALL_TOOLS

    from ai.tool_executor import execute_tool_calls

    async_client = get_async_client()
    system = context.get("system", "")
    history = context.get("history", [])

    # Начальные сообщения
    messages = list(history) + [{"role": "user", "content": user_message}]

    sent_msg = await bot.send_message(chat_id=chat_id, text="✍️")
    final_text = ""

    try:
        for iteration in range(MAX_AGENT_ITERATIONS):
            response = await async_client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=system,
                tools=tools,
                messages=messages,
            )

            # Извлекаем текстовые блоки и tool_use блоки
            text_blocks = [b for b in response.content if b.type == "text"]
            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

            # Если нет tool_use — это финальный ответ
            if not tool_use_blocks or response.stop_reason == "end_turn":
                if text_blocks:
                    final_text = "".join(b.text for b in text_blocks)
                break

            # Есть tool_use → выполняем и продолжаем цикл
            tool_names = [t.name for t in tool_use_blocks]
            logger.info(
                f"[AGENT] iter={iteration+1} tools_called="
                f"{tool_names} user={tg_id}"
            )

            # Прогресс-индикатор: показываем что именно делает бот
            _STATUS_RU = {
                "save_workout": "💾 Записываю тренировку…",
                "save_metrics": "💾 Сохраняю метрики…",
                "save_nutrition": "💾 Записываю питание…",
                "save_exercise_result": "💾 Записываю упражнение…",
                "set_personal_record": "🏆 Фиксирую рекорд…",
                "update_athlete_card": "📝 Обновляю профиль…",
                "get_weekly_stats": "📊 Загружаю статистику…",
                "get_nutrition_history": "🥗 Загружаю историю питания…",
                "get_personal_records": "🏆 Загружаю рекорды…",
                "get_current_plan": "📋 Загружаю план…",
                "get_user_profile": "👤 Загружаю профиль…",
                "award_xp": "⚡ Начисляю XP…",
                "save_episode": "🧠 Сохраняю в память…",
            }
            status_text = _STATUS_RU.get(tool_names[0], "⚙️ Обрабатываю…")
            try:
                await sent_msg.edit_text(status_text)
            except Exception:
                pass

            # Добавляем ответ Claude с tool_use в историю
            messages.append({"role": "assistant", "content": response.content})

            # Выполняем инструменты
            tool_results = await execute_tool_calls(
                tg_id=tg_id,
                tool_uses=tool_use_blocks,
                bot=bot,
                chat_id=chat_id,
            )

            # Логируем результаты инструментов
            for tr in tool_results:
                if isinstance(tr, dict) and tr.get("type") == "tool_result":
                    content_preview = str(tr.get("content", ""))[:200]
                    logger.debug(
                        f"[AGENT] tool_result id={tr.get('tool_use_id', '?')[:8]}… "
                        f"content={content_preview}"
                    )

            # Добавляем результаты инструментов
            messages.append({
                "role": "user",
                "content": tool_results,
            })

        # Стримим/показываем финальный ответ
        if final_text:
            # Разбиваем на чанки для эффекта стриминга
            chunk_size = STREAM_UPDATE_EVERY
            displayed = 0
            while displayed < len(final_text):
                end = min(displayed + chunk_size, len(final_text))
                try:
                    if end < len(final_text):
                        await sent_msg.edit_text(final_text[:end] + " ▍")
                    else:
                        await sent_msg.edit_text(final_text)
                except Exception:
                    pass
                displayed = end

        elif not final_text:
            # Fallback: нет финального текста
            await sent_msg.edit_text("✅ Готово.")
            final_text = "✅ Готово."

        # Детектируем случай «сообщение о еде/тренировке, но tools не вызваны» (Фаза 14)
        _NUTRITION_KEYWORDS = ("съел", "поел", "обед", "завтрак", "ужин", "перекус",
                               "выпил", "ккал", "калори", "питание", "кбжу")
        _WORKOUT_KEYWORDS = ("потренировался", "тренировка", "занимался", "тренил",
                             "отжимания", "приседания", "подтягивания")
        _METRICS_KEYWORDS = ("поспал", "сон", "энергия", "вешу", "вес ")
        all_tools_called_in_session = any(
            (b.type == "tool_use")
            for msg in messages
            if isinstance(msg, dict) and msg.get("role") == "assistant"
            for b in (msg.get("content") if isinstance(msg.get("content"), list) else [])
        )
        if not all_tools_called_in_session and final_text:
            msg_lower = user_message.lower()
            expected: list[str] = []
            if any(kw in msg_lower for kw in _NUTRITION_KEYWORDS):
                expected.append("save_nutrition")
            if any(kw in msg_lower for kw in _WORKOUT_KEYWORDS):
                expected.append("save_workout")
            if any(kw in msg_lower for kw in _METRICS_KEYWORDS):
                expected.append("save_metrics")
            if expected:
                try:
                    from bot.debug import notify_no_tools_called
                    await notify_no_tools_called(bot, chat_id, user_message, expected)
                except Exception:
                    pass

    except anthropic.APIStatusError as e:
        logger.error(f"[AGENT] API error {e.status_code}: {e.message}")
        try:
            from bot.debug import notify_api_error
            await notify_api_error(bot, chat_id, e.status_code, e.message, "AGENT")
        except Exception:
            pass
        logger.info(f"[AGENT] Falling back to streaming for user={tg_id}")
        try:
            await sent_msg.delete()
        except Exception:
            pass
        return await ask_streaming(bot, chat_id, system, messages[:len(history)+1])

    except anthropic.APIConnectionError:
        logger.error(f"[AGENT] Connection error for user={tg_id}")
        try:
            from bot.debug import notify_error
            await notify_error(bot, chat_id, "Нет связи с Anthropic API",
                               "Проверь интернет или статус api.anthropic.com", "AGENT", "error")
        except Exception:
            pass
        await sent_msg.edit_text("⚠️ Нет связи с AI. Проверь интернет.")
        return ""

    except Exception as e:
        logger.error(f"[AGENT] Unexpected error for user={tg_id}: {e}")
        try:
            from bot.debug import notify_error
            await notify_error(bot, chat_id, "Необработанное исключение в агенте",
                               str(e)[:300], "AGENT", "error")
        except Exception:
            pass
        logger.info(f"[AGENT] Falling back to streaming for user={tg_id}")
        try:
            await sent_msg.delete()
        except Exception:
            pass
        return await ask_streaming(bot, chat_id, system, messages[:len(history)+1])

    return final_text
