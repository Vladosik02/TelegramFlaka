"""tests/test_admin_broadcast.py — H1 broadcast confirmation flow.

Проверяет двухэтапный flow:
  1. handle_admin_broadcast(text) → НЕ шлёт, только показывает preview;
  2. callback adm:bcast:yes → реально вызывает send_message;
  3. callback adm:bcast:no → state очищен, send_message НЕ вызван.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def fake_users():
    return [
        {"telegram_id": 100001, "name": "A"},
        {"telegram_id": 100002, "name": "B"},
    ]


def _make_update_message(text: str = "Hello world"):
    update = MagicMock()
    update.message = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def _make_ctx():
    ctx = MagicMock()
    ctx.user_data = {"admin_broadcast_pending": "awaiting_text"}
    return ctx


def _make_callback_query(data: str, *, bot=None):
    query = MagicMock()
    query.data = data
    query.from_user = MagicMock()
    query.from_user.id = 99999  # подразумеваем admin
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message = MagicMock()
    query.message.reply_text = AsyncMock()
    query.message.get_bot = MagicMock(return_value=bot or MagicMock())
    return query


@pytest.mark.asyncio
async def test_text_input_shows_preview_without_sending(fake_users):
    from bot.admin import handle_admin_broadcast

    update = _make_update_message("Test broadcast text")
    ctx = _make_ctx()

    with patch("bot.admin.get_all_active_users", return_value=fake_users):
        await handle_admin_broadcast(update, ctx)

    update.message.reply_text.assert_called_once()
    args, kwargs = update.message.reply_text.call_args
    assert "Превью" in args[0] or "Превью" in str(kwargs.get("text", ""))
    assert "2" in args[0]  # 2 получателя
    assert "Test broadcast text" in args[0]
    assert ctx.user_data["admin_broadcast_pending"] == "awaiting_confirm"
    assert ctx.user_data["admin_broadcast_text"] == "Test broadcast text"


@pytest.mark.asyncio
async def test_empty_text_rejected(fake_users):
    from bot.admin import handle_admin_broadcast

    update = _make_update_message("   ")
    ctx = _make_ctx()

    with patch("bot.admin.get_all_active_users", return_value=fake_users):
        await handle_admin_broadcast(update, ctx)

    update.message.reply_text.assert_called_once()
    args, _ = update.message.reply_text.call_args
    assert "пустой" in args[0].lower()
    # state не должен переключаться в awaiting_confirm
    assert ctx.user_data["admin_broadcast_pending"] == "awaiting_text"


@pytest.mark.asyncio
async def test_cancel_clears_state():
    from bot.admin import handle_admin_broadcast

    update = _make_update_message("/cancel")
    ctx = _make_ctx()
    ctx.user_data["admin_broadcast_text"] = "old text"

    await handle_admin_broadcast(update, ctx)

    assert "admin_broadcast_pending" not in ctx.user_data
    assert "admin_broadcast_text" not in ctx.user_data
    update.message.reply_text.assert_called_once()
    args, _ = update.message.reply_text.call_args
    assert "отменена" in args[0].lower()


@pytest.mark.asyncio
async def test_confirm_yes_triggers_send(fake_users):
    from bot.admin import _broadcast_send_confirmed

    bot = MagicMock()
    bot.send_message = AsyncMock()
    query = _make_callback_query("adm:bcast:yes", bot=bot)
    ctx = MagicMock()
    ctx.user_data = {
        "admin_broadcast_pending": "awaiting_confirm",
        "admin_broadcast_text": "Final text",
    }

    with patch("bot.admin.get_all_active_users", return_value=fake_users):
        await _broadcast_send_confirmed(query, ctx)

    assert bot.send_message.await_count == 2
    sent_chat_ids = sorted(
        call.kwargs["chat_id"] for call in bot.send_message.call_args_list
    )
    assert sent_chat_ids == [100001, 100002]
    sent_texts = {call.kwargs["text"] for call in bot.send_message.call_args_list}
    assert sent_texts == {"Final text"}
    assert "admin_broadcast_pending" not in ctx.user_data
    assert "admin_broadcast_text" not in ctx.user_data


@pytest.mark.asyncio
async def test_confirm_yes_without_text_shows_error(fake_users):
    from bot.admin import _broadcast_send_confirmed

    bot = MagicMock()
    bot.send_message = AsyncMock()
    query = _make_callback_query("adm:bcast:yes", bot=bot)
    ctx = MagicMock()
    ctx.user_data = {"admin_broadcast_pending": "awaiting_confirm"}  # без текста

    with patch("bot.admin.get_all_active_users", return_value=fake_users):
        await _broadcast_send_confirmed(query, ctx)

    bot.send_message.assert_not_called()
    query.edit_message_text.assert_called_once()
    args, _ = query.edit_message_text.call_args
    assert "потерян" in args[0].lower()
