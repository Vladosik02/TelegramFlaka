"""
bot/debug.py — Отправка технических ошибок прямо в Telegram-чат.

Поскольку бот личный (один пользователь), все ошибки инструментов,
API-сбои и непойманные исключения уходят прямо в чат — не только в logs.
Это позволяет быстро выявлять проблемы без SSH и просмотра логов.

Формат сообщений:
    ⚠️ [tool/save_nutrition] Ошибка записи
    `Missing required field: calories`

    🔴 [AGENT] API Error 529
    `overloaded_error: Anthropic API overloaded`

    🔧 [HANDLER] Необработанное исключение
    `AttributeError: 'NoneType' object has no attribute 'id'`
"""
import logging

logger = logging.getLogger(__name__)

# Включить/выключить уведомления об ошибках в чат
# Для личного бота всегда True — меняй только если надоедает
DEBUG_NOTIFY_ENABLED = True


async def notify_error(
    bot,
    chat_id: int,
    title: str,
    detail: str = "",
    source: str = "",
    level: str = "warning",   # "warning" | "error" | "info"
) -> None:
    """
    Отправляет уведомление об ошибке в чат пользователя.

    Args:
        bot:      Telegram Bot object
        chat_id:  ID чата для отправки
        title:    Краткое описание ошибки
        detail:   Техническая деталь (будет показана моноширинным шрифтом)
        source:   Источник (например "tool/save_nutrition", "AGENT", "HANDLER")
        level:    Уровень: warning=⚠️, error=🔴, info=🔧
    """
    if not DEBUG_NOTIFY_ENABLED or not bot or not chat_id:
        return

    try:
        icons = {"warning": "⚠️", "error": "🔴", "info": "🔧"}
        icon = icons.get(level, "⚠️")
        source_tag = f"[{source}] " if source else ""
        detail_text = f"\n`{detail[:300]}`" if detail else ""
        text = f"{icon} {source_tag}*{title}*{detail_text}"
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
    except Exception as e:
        # Не позволяем debug-нотификации поломать основной поток
        logger.error(f"[DEBUG_NOTIFY] Failed to send error notification to chat {chat_id}: {e}")


async def notify_tool_result(
    bot,
    chat_id: int,
    tool_name: str,
    result: dict,
) -> None:
    """
    Если tool вернул success=False — уведомить пользователя в чат.
    Вызывается автоматически из execute_tool_calls().
    """
    if not isinstance(result, dict):
        return
    success = result.get("success", True)
    if success is False:
        error = result.get("error", "неизвестная ошибка")
        await notify_error(
            bot=bot,
            chat_id=chat_id,
            title=f"Инструмент не сработал",
            detail=f"{tool_name}: {error}",
            source=f"tool/{tool_name}",
            level="warning",
        )


async def notify_api_error(
    bot,
    chat_id: int,
    status_code: int,
    message: str,
    source: str = "AGENT",
) -> None:
    """Уведомление об ошибке Anthropic API."""
    await notify_error(
        bot=bot,
        chat_id=chat_id,
        title=f"API Error {status_code}",
        detail=message[:200],
        source=source,
        level="error",
    )


async def notify_no_tools_called(
    bot,
    chat_id: int,
    user_message: str,
    expected_tools: list[str],
) -> None:
    """
    Уведомление если AI не вызвал инструменты, хотя должен был.
    Например: пользователь написал о еде, но save_nutrition не вызван.
    """
    tools_str = ", ".join(expected_tools)
    await notify_error(
        bot=bot,
        chat_id=chat_id,
        title="AI не вызвал инструменты",
        detail=f"Ожидалось: {tools_str}\nСообщение: {user_message[:100]}",
        source="AGENT",
        level="info",
    )
