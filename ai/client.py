"""
ai/client.py — Обёртка над Anthropic API (sync + async streaming).
"""
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
    """Для плановых сообщений (утро/день/вечер/неделя) без user_message."""
    system = context.get("system", "")
    prompt = context.get("prompt", "")
    messages = [{"role": "user", "content": prompt}]
    return ask(system, messages)
