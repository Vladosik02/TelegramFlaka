"""
scheduler/jobs.py — Регистрация задач в APScheduler.
"""
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot

from scheduler.logic import (
    broadcast_morning, broadcast_afternoon,
    broadcast_evening, broadcast_weekly, check_and_send_reminders,
    broadcast_l4_intelligence,
)
from config import (
    SCHEDULE_MAX_MORNING, SCHEDULE_MAX_AFTERNOON, SCHEDULE_MAX_EVENING,
    DAILY_SUMMARY_TIME, WEEKLY_SUMMARY_DAY, MONTHLY_BACKUP_TIME
)

logger = logging.getLogger(__name__)


def _parse_time(t: str) -> tuple[int, int]:
    h, m = t.split(":")
    return int(h), int(m)


def setup_scheduler(scheduler: AsyncIOScheduler, bot: Bot) -> None:
    """Регистрирует все задачи."""

    mh, mm = _parse_time(SCHEDULE_MAX_MORNING)
    ah, am = _parse_time(SCHEDULE_MAX_AFTERNOON)
    eh, em = _parse_time(SCHEDULE_MAX_EVENING)
    dh, dm = _parse_time(DAILY_SUMMARY_TIME)

    # ── Утро ─────────────────────────────────────────────────────────────────
    scheduler.add_job(
        broadcast_morning, "cron",
        hour=mh, minute=mm,
        args=[bot],
        id="morning_checkin",
        replace_existing=True,
    )
    logger.info(f"Morning checkin scheduled: {SCHEDULE_MAX_MORNING}")

    # ── День ─────────────────────────────────────────────────────────────────
    scheduler.add_job(
        broadcast_afternoon, "cron",
        hour=ah, minute=am,
        args=[bot],
        id="afternoon_checkin",
        replace_existing=True,
    )
    logger.info(f"Afternoon checkin scheduled: {SCHEDULE_MAX_AFTERNOON}")

    # ── Вечер ─────────────────────────────────────────────────────────────────
    scheduler.add_job(
        broadcast_evening, "cron",
        hour=eh, minute=em,
        args=[bot],
        id="evening_checkin",
        replace_existing=True,
    )
    logger.info(f"Evening checkin scheduled: {SCHEDULE_MAX_EVENING}")

    # ── Напоминания каждые 15 мин ────────────────────────────────────────────
    scheduler.add_job(
        check_and_send_reminders, "interval",
        minutes=15,
        args=[bot],
        id="reminder_checker",
        replace_existing=True,
    )
    logger.info("Reminder checker: every 15 min")

    # ── Недельный отчёт (воскресенье, 21:00) ─────────────────────────────────
    scheduler.add_job(
        broadcast_weekly, "cron",
        day_of_week=WEEKLY_SUMMARY_DAY,
        hour=21, minute=0,
        args=[bot],
        id="weekly_report",
        replace_existing=True,
    )
    logger.info(f"Weekly report scheduled: Sunday 21:00")

    # ── L4 Intelligence — воскресенье 21:30 (после weekly report) ────────────
    scheduler.add_job(
        broadcast_l4_intelligence, "cron",
        day_of_week="sun",
        hour=21, minute=30,
        id="l4_intelligence",
        replace_existing=True,
    )
    logger.info("L4 Intelligence update scheduled: Sunday 21:30")

    # ── Ежемесячный бэкап ────────────────────────────────────────────────────
    bh, bm = _parse_time(MONTHLY_BACKUP_TIME)
    try:
        from backup import run_backup
        scheduler.add_job(
            run_backup, "cron",
            day=1, hour=bh, minute=bm,
            id="monthly_backup",
            replace_existing=True,
        )
        logger.info(f"Monthly backup scheduled: 1st of month {MONTHLY_BACKUP_TIME}")
    except ImportError:
        logger.warning("backup.py not found, skipping monthly backup job")

    logger.info("All scheduler jobs registered")
