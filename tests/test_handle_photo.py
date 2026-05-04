"""tests/test_handle_photo.py — H3 photo size guard.

Проверяет что handle_photo отклоняет фото больше MAX_PHOTO_SIZE_BYTES без
открытия Vision API (no Anthropic call, no temp file).
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config import MAX_PHOTO_SIZE_BYTES


def _make_update(photo_size: int, *, caption: str = ""):
    update = MagicMock()
    update.message = MagicMock()
    update.message.caption = caption

    photo = MagicMock()
    photo.file_size = photo_size
    photo.get_file = AsyncMock()
    update.message.photo = [photo]

    update.message.reply_text = AsyncMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 100001
    return update


@pytest.mark.asyncio
async def test_oversize_photo_rejected_without_api_call():
    from bot import handlers

    update = _make_update(photo_size=MAX_PHOTO_SIZE_BYTES + 1024)
    ctx = MagicMock()

    fake_user = {"id": 1, "telegram_id": 100001}
    with patch.object(handlers, "get_user", return_value=fake_user), \
         patch("ai.client.get_async_client") as get_client:
        await handlers.handle_photo(update, ctx)

    update.message.reply_text.assert_called_once()
    args, _ = update.message.reply_text.call_args
    assert "большое" in args[0].lower()
    update.message.photo[0].get_file.assert_not_called()
    get_client.assert_not_called()


@pytest.mark.asyncio
async def test_no_user_returns_early():
    from bot import handlers

    update = _make_update(photo_size=1024)
    ctx = MagicMock()

    with patch.object(handlers, "get_user", return_value=None):
        await handlers.handle_photo(update, ctx)

    update.message.reply_text.assert_called_once()
    args, _ = update.message.reply_text.call_args
    assert "/start" in args[0]
    update.message.photo[0].get_file.assert_not_called()


@pytest.mark.asyncio
async def test_size_at_limit_passes_guard():
    """Photo ровно равный лимиту — не отвергается (только > limit)."""
    from bot import handlers

    update = _make_update(photo_size=MAX_PHOTO_SIZE_BYTES)
    ctx = MagicMock()

    fake_user = {"id": 1, "telegram_id": 100001}
    # Падёт дальше на download (что нормально — мы только проверяем guard).
    update.message.photo[0].get_file = AsyncMock(side_effect=RuntimeError("stop here"))

    with patch.object(handlers, "get_user", return_value=fake_user):
        # Размер в лимите → guard молчит, идём дальше до download.
        # status_msg.reply_text вызывается ДО download → засекаем "Анализирую".
        await handlers.handle_photo(update, ctx)

    # Первый reply — "Анализирую фото..." (status), затем error edit.
    assert update.message.reply_text.await_count >= 1
    first_call_text = update.message.reply_text.call_args_list[0].args[0]
    assert "Анализирую" in first_call_text
