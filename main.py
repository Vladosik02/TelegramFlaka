"""
main.py — Точка входа. Запуск Telegram-бота + APScheduler.

Порядок:
1. Инициализация БД
2. Создание Application (python-telegram-bot)
3. Регистрация handlers
4. Запуск scheduler
5. Polling
"""
import logging
import asyncio
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import TELEGRAM_TOKEN
from db.connection import init_db, close_connection
from bot.commands import cmd_start, cmd_stop, cmd_stats, cmd_mode, cmd_help, cmd_reset, cmd_export
from bot.handlers import handle_message, handle_callback, handle_voice
from scheduler.jobs import setup_scheduler

# ─── Логирование ─────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("trainer.log", encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)


def main() -> None:
    # ── 1. Инициализация БД ───────────────────────────────────────────────────
    init_db()
    logger.info("Database ready")

    # ── 2. Создаём Application ────────────────────────────────────────────────
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # ── 3. Команды ────────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stop",  cmd_stop))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("mode",  cmd_mode))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CommandHandler("reset",  cmd_reset))
    app.add_handler(CommandHandler("export", cmd_export))

    # ── 4. Текстовые сообщения ────────────────────────────────────────────────
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # ── 4b. Голосовые сообщения (Whisper) ─────────────────────────────────────
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    # ── 5. Inline callback'и ──────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(handle_callback))

    # ── 6. Scheduler ─────────────────────────────────────────────────────────
    scheduler = AsyncIOScheduler()
    bot = app.bot
    setup_scheduler(scheduler, bot)
    scheduler.start()
    logger.info("Scheduler started")

    # ── 7. Запуск ─────────────────────────────────────────────────────────────
    logger.info("Bot starting...")
    try:
        app.run_polling(drop_pending_updates=True)
    finally:
        scheduler.shutdown()
        close_connection()
        logger.info("Bot stopped")


if __name__ == "__main__":
    main()
