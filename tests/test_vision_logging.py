"""tests/test_vision_logging.py — H4 Vision call logged to ai_usage_log.

Проверяет что после Vision-вызова log_usage вызвана с call_type="vision"
и правильными tokens.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_update(*, caption: str = ""):
    update = MagicMock()
    update.message = MagicMock()
    update.message.caption = caption

    photo = MagicMock()
    photo.file_size = 1024
    file_obj = MagicMock()
    file_obj.download_to_drive = AsyncMock()
    photo.get_file = AsyncMock(return_value=file_obj)
    update.message.photo = [photo]

    status_msg = MagicMock()
    status_msg.edit_text = AsyncMock()
    update.message.reply_text = AsyncMock(return_value=status_msg)
    update.effective_user = MagicMock()
    update.effective_user.id = 100001
    return update


def _fake_response(input_tokens=120, output_tokens=80,
                    cache_read=0, cache_write=0, text="Ккал: ~500"):
    response = MagicMock()
    block = MagicMock()
    block.text = text
    response.content = [block]
    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    usage.cache_read_input_tokens = cache_read
    usage.cache_creation_input_tokens = cache_write
    response.usage = usage
    return response


def _seed_real_jpeg(tmp_path):
    """Создать реальный байтовый файл — handle_photo читает его через open()/f.read()."""
    p = tmp_path / "fake.jpg"
    p.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg-bytes")
    return p


@pytest.mark.asyncio
async def test_vision_logs_usage_with_call_type_vision(tmp_path):
    from bot import handlers

    real_path = _seed_real_jpeg(tmp_path)
    update = _make_update(caption="ужин")
    ctx = MagicMock()

    fake_user = {"id": 7, "telegram_id": 100001}
    fake_async_client = MagicMock()
    fake_async_client.messages.create = AsyncMock(
        return_value=_fake_response(input_tokens=200, output_tokens=150)
    )

    log_usage_mock = MagicMock(return_value=0.001)

    # NamedTemporaryFile.__enter__().name → real_path
    tmpfile_ctx = MagicMock()
    tmpfile_ctx.__enter__ = MagicMock(return_value=tmpfile_ctx)
    tmpfile_ctx.__exit__ = MagicMock(return_value=False)
    tmpfile_ctx.name = str(real_path)

    with patch.object(handlers, "get_user", return_value=fake_user), \
         patch("ai.client.get_async_client", return_value=fake_async_client), \
         patch("db.queries.usage.log_usage", log_usage_mock), \
         patch.object(handlers, "save_user_message"), \
         patch.object(handlers, "save_ai_response"), \
         patch("db.queries.nutrition.save_nutrition_from_parsed", create=True), \
         patch("tempfile.NamedTemporaryFile", return_value=tmpfile_ctx):
        await handlers.handle_photo(update, ctx)

    log_usage_mock.assert_called_once()
    kwargs = log_usage_mock.call_args.kwargs
    assert kwargs["call_type"] == "vision"
    assert kwargs["user_id"] == 7
    assert kwargs["input_tokens"] == 200
    assert kwargs["output_tokens"] == 150


@pytest.mark.asyncio
async def test_vision_logging_skipped_when_usage_missing(tmp_path):
    """Если response.usage None — log_usage НЕ вызывается, exception молчит."""
    from bot import handlers

    real_path = _seed_real_jpeg(tmp_path)
    update = _make_update(caption="фото")
    ctx = MagicMock()

    fake_user = {"id": 8, "telegram_id": 100001}
    response = _fake_response()
    response.usage = None

    fake_async_client = MagicMock()
    fake_async_client.messages.create = AsyncMock(return_value=response)
    log_usage_mock = MagicMock()

    tmpfile_ctx = MagicMock()
    tmpfile_ctx.__enter__ = MagicMock(return_value=tmpfile_ctx)
    tmpfile_ctx.__exit__ = MagicMock(return_value=False)
    tmpfile_ctx.name = str(real_path)

    with patch.object(handlers, "get_user", return_value=fake_user), \
         patch("ai.client.get_async_client", return_value=fake_async_client), \
         patch("db.queries.usage.log_usage", log_usage_mock), \
         patch.object(handlers, "save_user_message"), \
         patch.object(handlers, "save_ai_response"), \
         patch("tempfile.NamedTemporaryFile", return_value=tmpfile_ctx):
        await handlers.handle_photo(update, ctx)

    log_usage_mock.assert_not_called()
