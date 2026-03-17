"""
scheduler/jobs.py — Регистрация задач в APScheduler.
"""
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot

from scheduler.logic import (
    broadcast_morning, broadcast_afternoon,
    broadcast_evening, broadcast_weekly, check_and_send_reminders,
    broadcast_l4_intelligence, broadcast_daily_summary,
    broadcast_monthly_summary,
    broadcast_plan_archive, broadcast_plan_generate,
    broadcast_pre_workout_morning, broadcast_pre_workout_evening,
    cleanup_old_checkins,
    broadcast_streak_protection,
)
from scheduler.nudges import check_and_send_nudges
from scheduler.periodization import advance_all_mesocycles  # Фаза 12.2
from scheduler.nutrition_analysis import run_nutrition_analysis  # Фаза 16: паттерны питания
from config import (
    SCHEDULE_MAX_MORNING, SCHEDULE_MAX_AFTERNOON, SCHEDULE_MAX_EVENING,
    DAILY_SUMMARY_TIME, WEEKLY_SUMMARY_DAY,
    MONTHLY_SUMMARY_TIME, MONTHLY_BACKUP_TIME,
    TRAINING_PLAN_ARCHIVE_TIME, TRAINING_PLAN_GENERATE_TIME,
    NUDGE_CHECK_TIME,
    PRE_WORKOUT_MORNING_TIME, PRE_WORKOUT_EVENING_TIME,
    NUTRITION_ANALYSIS_TIME,
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

    # ── Мезоцикл — воскресенье 21:15 (между weekly report и L4) ─────────────
    scheduler.add_job(
        advance_all_mesocycles, "cron",
        day_of_week="sun",
        hour=21, minute=15,
        args=[bot],
        id="mesocycle_advance",
        replace_existing=True,
    )
    logger.info("Mesocycle advance scheduled: Sunday 21:15")

    # ── L4 Intelligence — воскресенье 21:30 (после weekly report) ────────────
    # Фаза 16.3: передаём bot чтобы дайджест отправлялся пользователю в чат
    scheduler.add_job(
        broadcast_l4_intelligence, "cron",
        day_of_week="sun",
        hour=21, minute=30,
        args=[bot],
        id="l4_intelligence",
        replace_existing=True,
    )
    logger.info("L4 Intelligence update scheduled: Sunday 21:30 (with digest delivery)")

    # ── Daily Summary — каждый день по DAILY_SUMMARY_TIME (по умолчанию 23:00) ─
    scheduler.add_job(
        broadcast_daily_summary, "cron",
        hour=dh, minute=dm,
        id="daily_summary",
        replace_existing=True,
    )
    logger.info(f"Daily summary scheduled: {DAILY_SUMMARY_TIME}")

    # ── Monthly Summary — 1-е число в MONTHLY_SUMMARY_TIME (09:00) ────────────
    msh, msm = _parse_time(MONTHLY_SUMMARY_TIME)
    scheduler.add_job(
        broadcast_monthly_summary, "cron",
        day=1, hour=msh, minute=msm,
        id="monthly_summary",
        replace_existing=True,
    )
    logger.info(f"Monthly summary scheduled: 1st of month {MONTHLY_SUMMARY_TIME}")

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

    # ── Тренировочный план — воскресенье 19:00 архивация ──────────────────────
    ph, pm = _parse_time(TRAINING_PLAN_ARCHIVE_TIME)
    scheduler.add_job(
        broadcast_plan_archive, "cron",
        day_of_week="sun",
        hour=ph, minute=pm,
        args=[bot],
        id="plan_archive",
        replace_existing=True,
    )
    logger.info(f"Plan archive scheduled: Sunday {TRAINING_PLAN_ARCHIVE_TIME}")

    # ── Тренировочный план — воскресенье 20:00 генерация ──────────────────────
    gh, gm = _parse_time(TRAINING_PLAN_GENERATE_TIME)
    scheduler.add_job(
        broadcast_plan_generate, "cron",
        day_of_week="sun",
        hour=gh, minute=gm,
        args=[bot],
        id="plan_generate",
        replace_existing=True,
    )
    logger.info(f"Plan generate scheduled: Sunday {TRAINING_PLAN_GENERATE_TIME}")

    # ── Проактивные нудж-сообщения — ежедневно в NUDGE_CHECK_TIME (08:00) ────
    nh, nm = _parse_time(NUDGE_CHECK_TIME)
    scheduler.add_job(
        check_and_send_nudges, "cron",
        hour=nh, minute=nm,
        args=[bot],
        id="nudge_checker",
        replace_existing=True,
    )
    logger.info(f"Nudge checker scheduled: {NUDGE_CHECK_TIME}")

    # ── Напоминание перед тренировкой — утро (08:30) ──────────────────────────
    pwmh, pwmm = _parse_time(PRE_WORKOUT_MORNING_TIME)
    scheduler.add_job(
        broadcast_pre_workout_morning, "cron",
        hour=pwmh, minute=pwmm,
        args=[bot],
        id="pre_workout_morning",
        replace_existing=True,
    )
    logger.info(f"Pre-workout morning reminder scheduled: {PRE_WORKOUT_MORNING_TIME}")

    # ── Напоминание перед тренировкой — вечер (19:30) ─────────────────────────
    pweh, pwem = _parse_time(PRE_WORKOUT_EVENING_TIME)
    scheduler.add_job(
        broadcast_pre_workout_evening, "cron",
        hour=pweh, minute=pwem,
        args=[bot],
        id="pre_workout_evening",
        replace_existing=True,
    )
    logger.info(f"Pre-workout evening reminder scheduled: {PRE_WORKOUT_EVENING_TIME}")

    # ── Еженедельная очистка старых checkins (воскресенье 22:00) — Фаза 14.7 ─
    scheduler.add_job(
        cleanup_old_checkins, "cron",
        day_of_week="sun",
        hour=22, minute=0,
        id="checkins_cleanup",
        replace_existing=True,
    )
    logger.info("Checkins cleanup scheduled: Sunday 22:00")

    # ── Streak Protection — ежедневно 20:00 — Фаза 16.4 ─────────────────────
    scheduler.add_job(
        broadcast_streak_protection, "cron",
        hour=20, minute=0,
        args=[bot],
        id="streak_protection",
        replace_existing=True,
    )
    logger.info("Streak protection scheduled: daily 20:00")

    # ── Анализ паттернов питания — ежедневно 21:45 ───────────────────────────
    nah, nam = _parse_time(NUTRITION_ANALYSIS_TIME)
    scheduler.add_job(
        run_nutrition_analysis, "cron",
        hour=nah, minute=nam,
        args=[bot],
        id="nutrition_analysis",
        replace_existing=True,
    )
    logger.info(f"Nutrition analysis scheduled: {NUTRITION_ANALYSIS_TIME}")

    logger.info("All scheduler jobs registered")
