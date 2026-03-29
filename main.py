"""
main.py — Точка входа. Запуск Telegram-бота + APScheduler.
Обновлено: Асинхронный запуск планировщика внутри жизненного цикла бота.
"""
import logging
import asyncio
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters
)
from telegram import Update, BotCommand, MenuButtonCommands, BotCommandScopeDefault, BotCommandScopeChat
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import TELEGRAM_TOKEN, ADMIN_USER_ID
from db.connection import init_db, close_connection
from bot.commands import (
    cmd_start, cmd_stop, cmd_stats, cmd_mode, cmd_help, cmd_reset,
    cmd_export, cmd_profile, cmd_test, cmd_plan, cmd_admin, cmd_setup, cmd_meal,
    cmd_achievements, cmd_history, cmd_menu, cmd_today, cmd_costs
)
from bot.handlers import handle_message, handle_callback, handle_voice, handle_photo
from scheduler.jobs import setup_scheduler

# ─── Логирование ─────────────────────────────────────────────────────────────
import sys
import io as _io

# StreamHandler с явным UTF-8 — иначе в Docker без PYTHONIOENCODING
# Python открывает stderr в ASCII-режиме и падает на кириллице.
try:
    _utf8_stream = _io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", line_buffering=True
    )
except AttributeError:
    _utf8_stream = sys.stdout  # fallback: pytest, REPL и т.п.

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(_utf8_stream),
        logging.FileHandler("trainer.log", encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)

# ─── Асинхронная инициализация ──────────────────────────────────────────────
async def post_init(app: Application) -> None:
    """
    Эта функция вызывается библиотекой автоматически, когда цикл событий уже запущен,
    но бот еще не начал получать сообщения. Идеальное место для старта планировщика.
    """
    scheduler = AsyncIOScheduler()
    # Сохраняем планировщик в bot_data, чтобы к нему был доступ из обработчиков (например, для snooze)
    app.bot_data["scheduler"] = scheduler
    
    # Настраиваем задачи по расписанию
    setup_scheduler(scheduler, app.bot)
    
    # Теперь старт пройдет успешно, так как мы внутри event loop
    scheduler.start()
    logger.info("✅ APScheduler успешно запущен внутри цикла событий.")

    # Регистрация команд в Telegram — появятся в меню "/" у пользователя
    base_commands = [
        BotCommand("menu",         "Главное меню"),
        BotCommand("today",        "Дашборд дня"),
        BotCommand("stats",        "Статистика за неделю"),
        BotCommand("plan",         "План тренировок"),
        BotCommand("profile",      "Мой профиль"),
        BotCommand("achievements", "Уровень и ачивки"),
        BotCommand("history",      "Хроника тренировок"),
        BotCommand("costs",        "Расходы на AI"),
        BotCommand("help",         "Справка"),
        BotCommand("start",        "Начать или возобновить"),
    ]
    admin_commands = base_commands + [
        BotCommand("admin", "Панель администратора"),
    ]

    try:
        await app.bot.set_my_commands(base_commands, scope=BotCommandScopeDefault())
        if ADMIN_USER_ID != 0:
            await app.bot.set_my_commands(
                admin_commands, scope=BotCommandScopeChat(chat_id=ADMIN_USER_ID)
            )
        await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        logger.info("✅ set_my_commands и set_chat_menu_button выполнены.")
    except Exception as e:
        logger.warning(f"⚠️ Не удалось зарегистрировать команды в Telegram: {e}")

def main() -> None:
    # 1. Инициализация БД
    # Убедись, что на сервере выполнен: sudo chown -R 1001:1001 /opt/trainer-bot/data
    try:
        init_db()
        logger.info("Database ready")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка при инициализации БД: {e}")
        return

    # 1.5. Startup-валидация: все tools из ALL_TOOLS должны иметь обработчик в executor
    try:
        from ai.tools import ALL_TOOLS
        from ai.tool_executor import _DISPATCH
        schema_tools = {t["name"] for t in ALL_TOOLS}
        handled_tools = set(_DISPATCH.keys())
        missing_handlers = schema_tools - handled_tools
        unknown_handlers = handled_tools - schema_tools
        if missing_handlers or unknown_handlers:
            logger.error(
                f"❌ Tool mismatch! Нет обработчиков для: {missing_handlers}. "
                f"Лишние обработчики (нет в схеме): {unknown_handlers}"
            )
            raise RuntimeError(
                f"Tool executor mismatch: missing={missing_handlers}, extra={unknown_handlers}"
            )
        logger.info(f"✅ Tool validation passed: {len(schema_tools)} tools OK")
    except RuntimeError:
        return
    except Exception as e:
        logger.error(f"❌ Tool validation error: {e}")
        return

    # 2. Создаём Application с хуком post_init
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    # 3. Регистрация команд (Handlers)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stop",  cmd_stop))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("mode",  cmd_mode))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CommandHandler("reset",   cmd_reset))
    app.add_handler(CommandHandler("export",  cmd_export))
    app.add_handler(CommandHandler("profile", cmd_profile))
    app.add_handler(CommandHandler("test",    cmd_test))
    app.add_handler(CommandHandler("plan",    cmd_plan))
    app.add_handler(CommandHandler("setup",        cmd_setup))
    app.add_handler(CommandHandler("meal",         cmd_meal))
    app.add_handler(CommandHandler("admin",        cmd_admin))
    app.add_handler(CommandHandler("achievements", cmd_achievements))
    app.add_handler(CommandHandler("history",      cmd_history))
    app.add_handler(CommandHandler("menu",         cmd_menu))
    app.add_handler(CommandHandler("today",        cmd_today))
    app.add_handler(CommandHandler("costs",        cmd_costs))

    # 4. Обработка контента (Текст, Голос, Фото)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # 5. Интерактив (Кнопки)
    app.add_handler(CallbackQueryHandler(handle_callback))

    # 6. Запуск бота
    logger.info("🚀 Бот запускает polling...")
    try:
        app.run_polling(drop_pending_updates=True)
    except Exception as e:
        logger.error(f"❌ Ошибка во время работы бота: {e}")
    finally:
        # Корректное завершение
        if "scheduler" in app.bot_data:
            app.bot_data["scheduler"].shutdown()
            logger.info("Планировщик остановлен.")
        
        close_connection()
        logger.info("Бот полностью остановлен.")

if __name__ == "__main__":
    main()