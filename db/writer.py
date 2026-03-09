"""
db/writer.py — Высокоуровневые операции записи.
Разбирает ответы AI и сохраняет данные.
"""
import logging
import datetime
import json
from db.queries.user import get_user, update_user, touch_last_active
from db.queries.workouts import log_workout, log_metrics
from db.queries.context import (
    get_or_create_checkin, update_checkin,
    add_conversation_message, schedule_reminder
)
from config import get_trainer_mode, REMINDER_INTERVAL_MIN, REMINDER_MAX_COUNT

logger = logging.getLogger(__name__)


def save_user_message(telegram_id: int, text: str,
                       checkin_id: int = None) -> None:
    """Сохранить сообщение пользователя в историю."""
    user = get_user(telegram_id)
    if not user:
        return
    add_conversation_message(user["id"], "user", text, checkin_id)
    touch_last_active(telegram_id)


def save_ai_response(telegram_id: int, text: str,
                      checkin_id: int = None) -> None:
    """Сохранить ответ AI в историю."""
    user = get_user(telegram_id)
    if not user:
        return
    add_conversation_message(user["id"], "assistant", text, checkin_id)


def save_checkin_response(telegram_id: int, time_slot: str,
                           user_message: str, ai_response: str) -> int:
    """Записать завершённый чек-ин."""
    user = get_user(telegram_id)
    if not user:
        return None
    today = datetime.date.today().isoformat()
    checkin = get_or_create_checkin(user["id"], today, time_slot)
    update_checkin(checkin["id"],
                   status="done",
                   user_message=user_message,
                   ai_response=ai_response)
    return checkin["id"]


def schedule_checkin_reminders(telegram_id: int, time_slot: str) -> None:
    """Запланировать до REMINDER_MAX_COUNT напоминаний."""
    user = get_user(telegram_id)
    if not user:
        return
    today = datetime.date.today().isoformat()
    checkin = get_or_create_checkin(user["id"], today, time_slot)
    base = datetime.datetime.now()
    for i in range(1, REMINDER_MAX_COUNT + 1):
        remind_at = (base + datetime.timedelta(minutes=REMINDER_INTERVAL_MIN * i)).isoformat()
        schedule_reminder(user["id"], checkin["id"], remind_at)


def save_workout_from_parsed(telegram_id: int, parsed: dict) -> None:
    """Сохранить данные тренировки из разобранного AI-ответа."""
    user = get_user(telegram_id)
    if not user:
        return
    today = datetime.date.today().isoformat()
    mode = get_trainer_mode()
    log_workout(
        user_id=user["id"],
        date=today,
        mode=mode,
        workout_type=parsed.get("type"),
        duration_min=parsed.get("duration_min"),
        intensity=parsed.get("intensity"),
        exercises=json.dumps(parsed.get("exercises", []), ensure_ascii=False),
        notes=parsed.get("notes"),
        completed=parsed.get("completed", True)
    )


def save_metrics_from_parsed(telegram_id: int, parsed: dict) -> None:
    """Сохранить метрики здоровья."""
    user = get_user(telegram_id)
    if not user:
        return
    today = datetime.date.today().isoformat()
    log_metrics(
        user_id=user["id"],
        date=today,
        weight_kg=parsed.get("weight_kg"),
        sleep_hours=parsed.get("sleep_hours"),
        energy=parsed.get("energy"),
        mood=parsed.get("mood"),
        water_liters=parsed.get("water_liters"),
        steps=parsed.get("steps"),
        notes=parsed.get("notes")
    )
