"""
scheduler/periodization.py — Еженедельное продвижение мезоциклов.

Фаза 12.2: Вызывается каждое воскресенье в 21:15 (через APScheduler).
Для каждого активного пользователя:
  1. Продвигает мезоцикл (advance_mesocycle) — переключает фазу/неделю.
  2. Отправляет уведомление о новой фазе (если фаза сменилась).
"""
import logging
from telegram import Bot

from db.connection import get_connection
from db.queries.periodization import advance_mesocycle, PHASE_CONFIG, format_period_message

logger = logging.getLogger(__name__)


async def advance_all_mesocycles(bot: Bot) -> None:
    """
    Продвигает мезоциклы для всех активных пользователей.
    Отправляет уведомление если произошёл переход в новую фазу.
    """
    conn = get_connection()

    # Все активные пользователи
    rows = conn.execute("""
        SELECT id, telegram_id, name
        FROM user_profile
        WHERE active = 1 AND telegram_id IS NOT NULL
    """).fetchall()

    logger.info(f"[PERIOD] Advancing mesocycles for {len(rows)} active users")

    for row in rows:
        user_id = row["id"]
        telegram_id = row["telegram_id"]
        name = row["name"] or "атлет"

        try:
            # Получаем состояние ДО продвижения
            before = conn.execute("""
                SELECT phase, week_number FROM mesocycles
                WHERE user_id = ? AND completed_at IS NULL
                ORDER BY id DESC LIMIT 1
            """, (user_id,)).fetchone()

            phase_before = before["phase"] if before else None

            # Продвигаем
            new_mc = advance_mesocycle(user_id)
            if not new_mc:
                continue

            phase_after = new_mc["phase"]
            phase_changed = (phase_before != phase_after)

            if phase_changed:
                # Фаза сменилась — отправляем уведомление
                cfg = PHASE_CONFIG.get(phase_after, {})
                phase_name = cfg.get("name", phase_after)

                notify_text = (
                    f"🔄 *Новая фаза мезоцикла!*\n\n"
                    f"Начинается *{phase_name}*\n\n"
                )
                notify_text += format_period_message(user_id)

                await bot.send_message(
                    chat_id=telegram_id,
                    text=notify_text,
                    parse_mode="Markdown",
                )
                logger.info(
                    f"[PERIOD] user {user_id}: {phase_before} → {phase_after} "
                    f"(notified)"
                )
            else:
                # Та же фаза, просто новая неделя — тихое продвижение
                logger.debug(
                    f"[PERIOD] user {user_id}: {phase_after} "
                    f"week {new_mc['week_number']} (silent advance)"
                )

        except Exception as e:
            logger.error(
                f"[PERIOD] Failed to advance mesocycle for user {user_id}: {e}",
                exc_info=True,
            )
