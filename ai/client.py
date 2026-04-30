"""
ai/client.py — Обёртка над Anthropic API (sync + async streaming + Tool Use).

Фаза 10.1 — добавлен агентный цикл generate_agent_response().
"""
import html
import json
import logging
import time
import anthropic
from config import (
    ANTHROPIC_API_KEY,
    MODEL, MAX_TOKENS,
    MODEL_FOOD_PARSE, MAX_TOKENS_FOOD_PARSE,
    MODEL_SCHEDULED, MAX_TOKENS_SCHEDULED,
)

logger = logging.getLogger(__name__)


def _cached_system(system: str) -> list[dict]:
    """
    Оборачивает system-prompt в формат с prompt caching.
    Anthropic кэширует блок на стороне сервера (~5 минут для ephemeral).
    Экономия: ~40% от стоимости input-токенов системного промпта.

    Использование: вместо system=system → system=_cached_system(system)
    """
    if not system:
        return []
    return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]


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
            system=_cached_system(system),
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


# ── Парсинг еды через Haiku (дёшево, ~0.001$) ────────────────────────────────

def parse_food_with_ai(user_text: str) -> dict | None:
    """
    Парсит текст о еде в КБЖУ через Haiku.
    Возвращает dict {calories, protein_g, fat_g, carbs_g, meal_notes} или None.
    """
    import os
    prompt_path = os.path.join(os.path.dirname(__file__), "prompts", "food_parse.txt")
    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt_template = f.read()

    prompt = prompt_template.replace("{user_text}", user_text)
    client = get_client()

    try:
        response = client.messages.create(
            model=MODEL_FOOD_PARSE,
            max_tokens=MAX_TOKENS_FOOD_PARSE,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()

        # Убираем возможные markdown-обёртки
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        parsed = json.loads(raw)

        # "ничего не ел"
        if parsed.get("empty"):
            return None

        # Валидация: хотя бы калории должны быть
        if not parsed.get("calories") or parsed["calories"] <= 0:
            return None

        return {
            "calories": int(parsed.get("calories", 0)),
            "protein_g": int(parsed.get("protein_g", 0)),
            "fat_g": int(parsed.get("fat_g", 0)),
            "carbs_g": int(parsed.get("carbs_g", 0)),
            "meal_notes": parsed.get("meal_notes", user_text[:100]),
        }
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning(f"[FOOD_PARSE] JSON parse failed: {e}, raw={raw[:200] if 'raw' in dir() else '?'}")
        return None
    except Exception as e:
        logger.error(f"[FOOD_PARSE] AI call failed: {e}")
        return None


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
            system=_cached_system(system),
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


# ── Общее ядро агентного цикла ───────────────────────────────────────────────

async def _run_agent_iterations(
    async_client,
    system: str,
    messages: list,
    tools: list,
    max_iterations: int,
    tg_id: int,
    bot,
    chat_id: int,
    *,
    model: str = MODEL,
    max_tokens: int = MAX_TOKENS,
    log_prefix: str = "AGENT",
    on_tool_use=None,
) -> tuple[str, dict]:
    """
    Общее ядро агентного цикла с Tool Use.
    Мутирует `messages` на месте (добавляет assistant + tool_result сообщения).
    Возвращает (final_text, usage_totals).

    Параметры:
        model       — модель для этого цикла (Sonnet / Haiku)
        max_tokens  — лимит выходных токенов
        log_prefix  — префикс для логов: "AGENT" или "SCHED-AGENT"
        on_tool_use — async callable(tool_name: str) для UI-индикаторов
                      (только в chat loop; None в scheduled loop)
    """
    from ai.tool_executor import execute_tool_calls

    usage_totals = {
        "input_tokens": 0, "output_tokens": 0,
        "cache_read": 0, "cache_write": 0,
    }
    final_text = ""

    for iteration in range(max_iterations):
        response = await async_client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=_cached_system(system),
            tools=tools,
            messages=messages,
        )

        text_blocks = [b for b in response.content if b.type == "text"]
        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

        if hasattr(response, "usage") and response.usage:
            usage_totals["input_tokens"]  += getattr(response.usage, "input_tokens", 0)
            usage_totals["output_tokens"] += getattr(response.usage, "output_tokens", 0)
            usage_totals["cache_read"]    += getattr(response.usage, "cache_read_input_tokens", 0)
            usage_totals["cache_write"]   += getattr(response.usage, "cache_creation_input_tokens", 0)

        if not tool_use_blocks or response.stop_reason == "end_turn":
            if text_blocks:
                final_text = "".join(b.text for b in text_blocks)
            break

        tool_names = [t.name for t in tool_use_blocks]
        logger.info(
            f"[{log_prefix}] iter={iteration+1} tools_called={tool_names} user={tg_id}"
        )

        if on_tool_use is not None:
            await on_tool_use(tool_names[0])

        messages.append({"role": "assistant", "content": response.content})

        tool_results = await execute_tool_calls(
            tg_id=tg_id,
            tool_uses=tool_use_blocks,
            bot=bot,
            chat_id=chat_id,
        )

        for tr in tool_results:
            if isinstance(tr, dict) and tr.get("type") == "tool_result":
                content_preview = str(tr.get("content", ""))[:200]
                logger.debug(
                    f"[{log_prefix}] tool_result id={tr.get('tool_use_id', '?')[:8]}… "
                    f"content={content_preview}"
                )

        messages.append({"role": "user", "content": tool_results})

    return final_text, usage_totals


async def generate_scheduled_agent_message(
    bot, chat_id: int, context: dict, tg_id: int,
    tools: list | None = None,
) -> str:
    """
    Агентный scheduled message с Tool Use (Agent Fix, Этап 7).
    Для утренних/дневных/вечерних чек-инов — Claude может записывать метрики
    из контекста и вызывать tools.

    Параметры:
        tools — явный список инструментов. Если None — используются ALL_TOOLS.
                Для weekly report передавай _TOOLS_WEEKLY_REPORT (~700 tok vs 3502).

    Fallback: если agent loop не доступен → обычный sync generate_scheduled_message().
    """
    system = context.get("system", "")
    prompt = context.get("prompt", "")

    try:
        from ai.tools import ALL_TOOLS
        tools_to_use = tools if tools is not None else ALL_TOOLS

        async_client = get_async_client()
        messages = [{"role": "user", "content": prompt}]

        final_text, _ = await _run_agent_iterations(
            async_client=async_client,
            system=system,
            messages=messages,
            tools=tools_to_use,
            max_iterations=3,
            tg_id=tg_id,
            bot=bot,
            chat_id=chat_id,
            model=MODEL_SCHEDULED,
            max_tokens=MAX_TOKENS_SCHEDULED,
            log_prefix="SCHED-AGENT",
        )
        if final_text:
            return final_text

    except Exception as e:
        logger.warning(f"[SCHED-AGENT] Fallback to sync for user={tg_id}: {e}")
        return generate_scheduled_message(context)

    # Fallback если ничего не вернулось
    return generate_scheduled_message(context)


# ── Агентный цикл с Tool Use (Фаза 10.1) ─────────────────────────────────

MAX_AGENT_ITERATIONS = 5  # защита от бесконечного цикла

# Статусы инструментов (используется в generate_agent_response и _on_tool_use)
_STATUS_RU: dict[str, str] = {
    "save_workout":         "💾 Записываю тренировку…",
    "save_metrics":         "💾 Сохраняю метрики…",
    "save_nutrition":       "💾 Записываю питание…",
    "save_exercise_result": "💾 Записываю упражнение…",
    "set_personal_record":  "🏆 Фиксирую рекорд…",
    "update_athlete_card":  "📝 Обновляю профиль…",
    "get_weekly_stats":     "📊 Загружаю статистику…",
    "get_nutrition_history":"🥗 Загружаю историю питания…",
    "get_personal_records": "🏆 Загружаю рекорды…",
    "get_current_plan":     "📋 Загружаю план…",
    "get_user_profile":     "👤 Загружаю профиль…",
    "award_xp":             "⚡ Начисляю XP…",
    "save_episode":         "🧠 Сохраняю в память…",
}


async def _stream_response(sent_msg, text: str) -> None:
    """Имитирует стриминг: обновляет сообщение чанками по STREAM_UPDATE_EVERY символов."""
    chunk_size = STREAM_UPDATE_EVERY
    displayed = 0
    while displayed < len(text):
        end = min(displayed + chunk_size, len(text))
        try:
            if end < len(text):
                await sent_msg.edit_text(text[:end] + " ▍")
            else:
                await sent_msg.edit_text(text)
        except Exception:
            pass
        displayed = end


async def _log_usage_footnote(
    sent_msg, tg_id: int, model: str, usage_total: dict, t_start: float,
    final_text: str,
) -> None:
    """Логирует расход токенов в БД и добавляет сноску ⏱ · $ под сообщением."""
    try:
        from db.queries.usage import log_usage
        from db.queries.user import get_user

        _elapsed = time.monotonic() - t_start
        _user_db = get_user(tg_id)
        _user_db_id = _user_db["id"] if _user_db else tg_id

        _cost = log_usage(
            user_id=_user_db_id,
            model=model,
            input_tokens=usage_total["input_tokens"],
            output_tokens=usage_total["output_tokens"],
            cache_read=usage_total["cache_read"],
            cache_write=usage_total["cache_write"],
            response_time_sec=_elapsed,
            call_type="agent",
        )
        _footnote = f"\n\n<blockquote>⏱ {_elapsed:.1f}с  ·  ${_cost:.4f}</blockquote>"
        try:
            _full_msg = html.escape(final_text) + _footnote
            await sent_msg.edit_text(_full_msg, parse_mode="HTML")
        except Exception:
            pass  # сообщение уже удалено или слишком длинное
    except Exception as _e:
        logger.debug(f"[USAGE] Footnote skipped: {_e}")


async def _detect_hallucination(
    bot, chat_id: int, user_message: str, final_text: str, messages: list
) -> None:
    """
    Детектирует случай «Claude написал 'записал', но tools не вызывал».
    Шлёт уведомление в debug-чат администратора.

    Покрытие: 7 из 9 write-tools (save_episode и award_xp намеренно не
    детектируются — см. `ai/hallucination_rules.py`). Правила
    data-driven — расширяются в том же модуле.
    """
    all_tools_called = any(
        (b.type == "tool_use")
        for msg in messages
        if isinstance(msg, dict) and msg.get("role") == "assistant"
        for b in (msg.get("content") if isinstance(msg.get("content"), list) else [])
    )
    if all_tools_called or not final_text:
        return

    from ai.hallucination_rules import detect_expected_tools
    expected = detect_expected_tools(user_message, final_text)

    if expected:
        try:
            from bot.debug import notify_no_tools_called
            await notify_no_tools_called(bot, chat_id, user_message, expected)
        except Exception:
            pass


async def generate_agent_response(
    bot,
    chat_id: int,
    context: dict,
    user_message: str,
    tg_id: int,
    tools: list[dict] = None,
    model: str = None,
    max_tokens: int = None,
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

    Параметры model/max_tokens/tools могут быть переданы явно или прочитаны
    из context (проставляется build_layered_context на основе tier/tags).
    """
    # ── Определяем tools, модель и лимит токенов ────────────────────────────
    if tools is None:
        # Контекст несёт уже отфильтрованный набор (tier-оптимизация)
        context_tools = context.get("tools")
        if context_tools is not None:
            tools = context_tools
        else:
            from ai.tools import ALL_TOOLS
            tools = ALL_TOOLS

    if model is None:
        model = context.get("model", MODEL)
    if max_tokens is None:
        max_tokens = context.get("max_tokens", MAX_TOKENS)

    async_client = get_async_client()
    system = context.get("system", "")
    history = context.get("history", [])

    # Начальные сообщения
    messages = list(history) + [{"role": "user", "content": user_message}]

    sent_msg = await bot.send_message(chat_id=chat_id, text="✍️")
    final_text = ""

    # ── Агентный цикл + пост-обработка ───────────────────────────────────────
    _t_start = time.monotonic()

    async def _on_tool_use(tool_name: str) -> None:
        try:
            await sent_msg.edit_text(_STATUS_RU.get(tool_name, "⚙️ Обрабатываю…"))
        except Exception:
            pass

    try:
        final_text, _usage_total = await _run_agent_iterations(
            async_client=async_client,
            system=system,
            messages=messages,
            tools=tools,
            max_iterations=MAX_AGENT_ITERATIONS,
            tg_id=tg_id,
            bot=bot,
            chat_id=chat_id,
            model=model,
            max_tokens=max_tokens,
            on_tool_use=_on_tool_use,
        )

        if final_text:
            await _stream_response(sent_msg, final_text)
        else:
            # Fallback: нет финального текста
            await sent_msg.edit_text("✅ Готово.")
            final_text = "✅ Готово."

        await _log_usage_footnote(sent_msg, tg_id, model, _usage_total, _t_start, final_text)
        await _detect_hallucination(bot, chat_id, user_message, final_text, messages)

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
