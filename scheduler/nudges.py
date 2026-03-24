"""
scheduler/nudges.py — Проактивные AI-нудж-сообщения (Фазы 8.4 + 10.8).

6 типов нудж-сообщений (правило-ориентированные, без доп. API-вызовов):
  📉 drop           — 3+ дней без тренировки
  😴 recovery       — сон < 6ч, 3 дня подряд
  💪 pr_approaching — последний результат ≥ 90% от личного рекорда
  🔥 streak         — текущий стрик в N днях от рекорда
  🎯 goal_progress  — 40–65% недельного плана выполнено (≈ полпути)
  ⚖️ weight_trend   — вес растёт/падает >3% за 14 дней (Фаза 10.8)

Ключевые свойства:
  • Не более ОДНОГО нуджа на пользователя за запуск (приоритет: drop > recovery > pr > streak > goal).
  • Anti-spam через таблицу nudge_log (кулдаун 24ч или 7 дней по типу).
  • Сообщения без AI — быстро, без затрат на API.
  • Запуск ежедневно в 08:00 (до утреннего чек-ина в 09:00).
"""
import logging
import datetime
from telegram import Bot

from db.connection import get_connection
from config import (
    NUDGE_DROP_DAYS,
    NUDGE_STREAK_GAP,
    NUDGE_PR_THRESHOLD_PCT,
    NUDGE_SLEEP_THRESHOLD,
    NUDGE_SLEEP_DAYS,
    NUDGE_COOLDOWN_HOURS,
    NUDGE_WEEKLY_COOLDOWN,
)

logger = logging.getLogger(__name__)

# ─── Вспомогательные функции для склонения числительных ───────────────────────

def _days_word(n: int) -> str:
    """Склонение: 1 день / 2 дня / 5 дней."""
    n = abs(n) % 100
    if 11 <= n <= 19:
        return "дней"
    r = n % 10
    if r == 1:
        return "день"
    if 2 <= r <= 4:
        return "дня"
    return "дней"


def _workouts_word(n: int) -> str:
    """Склонение: 1 тренировка / 2 тренировки / 5 тренировок."""
    n = abs(n) % 100
    if 11 <= n <= 19:
        return "тренировок"
    r = n % 10
    if r == 1:
        return "тренировка"
    if 2 <= r <= 4:
        return "тренировки"
    return "тренировок"


# ─── Anti-spam: nudge_log ─────────────────────────────────────────────────────

def _was_nudge_sent_recently(user_id: int, nudge_type: str) -> bool:
    """
    Возвращает True, если нудж этого типа уже был отправлен в течение кулдауна.
    Еженедельный кулдаун для streak / pr_approaching / goal_progress.
    Суточный кулдаун для drop / recovery.
    """
    conn = get_connection()
    _FMT = "%Y-%m-%d %H:%M:%S"  # SQLite datetime('now') format — space, not T
    if nudge_type in NUDGE_WEEKLY_COOLDOWN:
        cutoff = (
            datetime.datetime.now() - datetime.timedelta(days=7)
        ).strftime(_FMT)
    else:
        cutoff = (
            datetime.datetime.now() - datetime.timedelta(hours=NUDGE_COOLDOWN_HOURS)
        ).strftime(_FMT)

    row = conn.execute(
        "SELECT id FROM nudge_log WHERE user_id = ? AND nudge_type = ? AND sent_at > ?",
        (user_id, nudge_type, cutoff),
    ).fetchone()
    return row is not None


def _log_nudge(user_id: int, nudge_type: str, message: str) -> None:
    """Записывает отправленный нудж в журнал для anti-spam."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO nudge_log (user_id, nudge_type, message_preview) VALUES (?, ?, ?)",
        (user_id, nudge_type, message[:100]),
    )
    conn.commit()


# ─── Тип 1: 📉 Drop Alert ────────────────────────────────────────────────────

def _check_drop_nudge(uid: int) -> str | None:
    """
    Триггер: нет завершённой тренировки NUDGE_DROP_DAYS+ дней.
    Дополнительно: если сегодня обычный тренировочный день → подсказка.
    """
    conn = get_connection()

    row = conn.execute(
        "SELECT date FROM workouts WHERE user_id = ? AND completed = 1 "
        "ORDER BY date DESC LIMIT 1",
        (uid,),
    ).fetchone()

    if not row:
        return None

    last_date = datetime.date.fromisoformat(row["date"])
    today = datetime.date.today()
    days_since = (today - last_date).days

    if days_since < NUDGE_DROP_DAYS:
        return None

    # Проверяем, тренируется ли пользователь обычно в этот день недели
    # (за последние 4 недели минимум 2 раза)
    weekday_ru = {
        0: "понедельникам", 1: "вторникам", 2: "средам",
        3: "четвергам",    4: "пятницам",  5: "субботам",
        6: "воскресеньям",
    }
    four_weeks_ago = (today - datetime.timedelta(weeks=4)).isoformat()
    recent_rows = conn.execute(
        "SELECT date FROM workouts WHERE user_id = ? AND completed = 1 AND date >= ?",
        (uid, four_weeks_ago),
    ).fetchall()

    weekday_counts: dict[int, int] = {i: 0 for i in range(7)}
    for r in recent_rows:
        d = datetime.date.fromisoformat(r["date"])
        weekday_counts[d.weekday()] += 1

    usual_hint = ""
    if weekday_counts.get(today.weekday(), 0) >= 2:
        usual_hint = (
            f"\nТы обычно тренируешься по {weekday_ru[today.weekday()]}. "
            f"Ещё не поздно! 💪"
        )

    return (
        f"📉 *Привет, всё ок?*\n\n"
        f"Прошло уже *{days_since} {_days_word(days_since)}* без тренировки "
        f"(последняя: {last_date.strftime('%d.%m')}).{usual_hint}"
    )


# ─── Тип 2: 😴 Recovery Nudge ────────────────────────────────────────────────

def _check_recovery_nudge(uid: int) -> str | None:
    """
    Триггер: средний сон < NUDGE_SLEEP_THRESHOLD часов за NUDGE_SLEEP_DAYS дней.
    Рекомендует снизить интенсивность на сегодня.
    """
    conn = get_connection()
    cutoff = (
        datetime.date.today() - datetime.timedelta(days=NUDGE_SLEEP_DAYS)
    ).isoformat()

    rows = conn.execute(
        "SELECT sleep_hours FROM metrics "
        "WHERE user_id = ? AND date >= ? AND sleep_hours IS NOT NULL "
        "ORDER BY date DESC",
        (uid, cutoff),
    ).fetchall()

    if len(rows) < NUDGE_SLEEP_DAYS:
        return None  # не хватает данных для уверенного вывода

    sleeps = [r["sleep_hours"] for r in rows]
    avg_sleep = sum(sleeps) / len(sleeps)

    if avg_sleep >= NUDGE_SLEEP_THRESHOLD:
        return None

    return (
        f"😴 *Внимание: недосып*\n\n"
        f"Средний сон за последние {NUDGE_SLEEP_DAYS} дня — "
        f"*{avg_sleep:.1f} ч* (норма: {NUDGE_SLEEP_THRESHOLD:.0f}+ ч).\n\n"
        f"Сегодня снизь интенсивность тренировки или сделай лёгкую растяжку. "
        f"Восстановление — это тоже тренинг. 🌿"
    )


# ─── Тип 3: 💪 PR Approaching ────────────────────────────────────────────────

def _get_max_streak_ever(uid: int) -> int:
    """
    Вспомогательная функция для streak nudge.
    Находит наибольший исторический стрик по всем тренировкам.
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT DISTINCT date FROM workouts WHERE user_id = ? AND completed = 1 "
        "ORDER BY date ASC",
        (uid,),
    ).fetchall()

    if not rows:
        return 0

    dates = [datetime.date.fromisoformat(r["date"]) for r in rows]
    max_s = cur_s = 1
    for i in range(1, len(dates)):
        if (dates[i] - dates[i - 1]).days == 1:
            cur_s += 1
            if cur_s > max_s:
                max_s = cur_s
        else:
            cur_s = 1
    return max_s


def _check_pr_nudge(uid: int) -> str | None:
    """
    Триггер: последний результат упражнения >= NUDGE_PR_THRESHOLD_PCT% от рекорда,
    но сам рекорд не побит. Результат должен быть не старше 14 дней.
    Предлагает конкретное значение для следующей попытки.
    """
    from db.queries.exercises import get_personal_records, get_exercise_last_result

    prs = get_personal_records(uid, limit=20)
    if not prs:
        return None

    cutoff_date = (datetime.date.today() - datetime.timedelta(days=14)).isoformat()

    for pr in prs:
        ex_name = pr["exercise_name"]
        record_type = pr["record_type"]
        pr_val = float(pr["record_value"])

        if pr_val <= 0:
            continue

        last = get_exercise_last_result(uid, ex_name)
        if not last:
            continue

        # Игнорируем устаревшие результаты (старше 14 дней)
        if last.get("date", "") < cutoff_date:
            continue

        # Не показываем нудж если последний результат сам является рекордом
        if last.get("is_personal_record"):
            continue

        # Получаем измеряемое значение по типу рекорда
        if record_type == "weight":
            last_val = last.get("weight_kg")
        elif record_type == "reps":
            last_val = float(last["reps"]) if last.get("reps") else None
        else:  # time
            last_val = float(last["duration_sec"]) if last.get("duration_sec") else None

        if last_val is None or last_val <= 0:
            continue

        ratio = last_val / pr_val * 100
        if ratio < NUDGE_PR_THRESHOLD_PCT or ratio >= 100:
            continue

        # Рассчитываем рекомендуемое следующее значение
        last_date = datetime.date.fromisoformat(last["date"])
        if record_type == "weight":
            suggestion = last_val + 2.5
            unit = "кг"
            last_str = f"{last_val:.1f} кг"
            pr_str = f"{pr_val:.1f} кг"
            sug_str = f"{suggestion:.1f} кг"
        elif record_type == "reps":
            suggestion = int(last_val) + 1
            unit = "повт"
            last_str = f"{int(last_val)} повт"
            pr_str = f"{int(pr_val)} повт"
            sug_str = f"{suggestion} повт"
        else:  # time
            suggestion = int(last_val) + 5
            unit = "сек"
            last_str = f"{int(last_val)} сек"
            pr_str = f"{int(pr_val)} сек"
            sug_str = f"{suggestion} сек"

        return (
            f"💪 *Рекорд близко!*\n\n"
            f"В прошлый раз ({last_date.strftime('%d.%m')}) "
            f"на *{ex_name}* ты показал *{last_str}*.\n"
            f"Твой личный рекорд: {pr_str}.\n\n"
            f"Попробуй сегодня *{sug_str}* — ты на {ratio:.0f}% формы! 🚀"
        )

    return None


# ─── Тип 4: 🔥 Streak Alert ──────────────────────────────────────────────────

def _check_streak_nudge(uid: int) -> str | None:
    """
    Триггер: текущий стрик в пределах NUDGE_STREAK_GAP дней от исторического рекорда.
    Мотивирует продолжать серию.
    Не срабатывает если текущий стрик уже ЯВЛЯЕТСЯ рекордом (gap = 0).
    """
    from db.queries.workouts import get_streak

    current = get_streak(uid)
    if current < 3:
        return None  # короткие стрики — без нуджа

    max_ever = _get_max_streak_ever(uid)
    gap = max_ever - current

    if not (0 < gap <= NUDGE_STREAK_GAP):
        return None

    return (
        f"🔥 *Стрик-алерт!*\n\n"
        f"Ты на активном стрике — *{current} {_days_word(current)} подряд*! "
        f"Всего *{gap} {_days_word(gap)}* до твоего рекорда "
        f"({max_ever} дней подряд). Держись! 💪"
    )


# ─── Тип 5: 🎯 Goal Progress ─────────────────────────────────────────────────

def _check_goal_nudge(uid: int) -> str | None:
    """
    Триггер: выполнено 40–65% тренировок из активного недельного плана.
    Отправляется один раз — при прохождении отметки «полпути».
    Требует активный training_plan (Фаза 8.3).
    """
    try:
        from db.queries.training_plan import get_active_plan
    except ImportError:
        return None  # Фаза 8.3 не установлена

    plan = get_active_plan(uid)
    if not plan:
        return None

    planned = plan.get("workouts_planned") or 0
    if planned < 2:
        return None  # нет смысла нуджить на плане из 1 тренировки

    week_start = plan["week_start"]
    week_end = (
        datetime.date.fromisoformat(week_start) + datetime.timedelta(days=6)
    ).isoformat()

    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM workouts "
        "WHERE user_id = ? AND date >= ? AND date <= ? AND completed = 1",
        (uid, week_start, week_end),
    ).fetchone()
    completed = row["cnt"] if row else 0

    if planned == 0:
        return None

    pct = completed / planned * 100

    # Срабатывает в диапазоне 40–65% (около полпути)
    if not (40.0 <= pct <= 65.0):
        return None

    remaining = planned - completed
    return (
        f"🎯 *Половина пути!*\n\n"
        f"Из {planned} {_workouts_word(planned)} на этой неделе ты сделал "
        f"*{completed}* — это примерно половина. Ты на правильном треке! "
        f"Осталось ещё {remaining} {_workouts_word(remaining)}. "
        f"Финиш уже виден 🏆"
    )


# ─── Тип 6: ⚖️ Weight Trend Nudge (Фаза 10.8) ────────────────────────────────

_WEIGHT_TREND_CHANGE_PCT = 3.0   # % изменения за 14 дней для триггера
_WEIGHT_TREND_MIN_DAYS   = 5     # минимум 5 дней данных за 14 дней

def _check_weight_trend_nudge(uid: int) -> str | None:
    """
    Триггер: вес изменился более чем на WEIGHT_TREND_CHANGE_PCT% за 14 дней.

    Сравниваем средний вес первой половины периода со второй.
    Если растёт при цели «похудеть» → предупреждение.
    Если падает при цели «набрать массу» → предупреждение.
    Если сильно меняется при цели «поддержание» → информация.
    """

    conn = get_connection()
    today = datetime.date.today()
    since_14 = (today - datetime.timedelta(days=14)).isoformat()
    since_7  = (today - datetime.timedelta(days=7)).isoformat()

    # Веса за первую половину периода (8-14 дней назад)
    early_rows = conn.execute("""
        SELECT weight_kg FROM metrics
        WHERE user_id = ? AND date >= ? AND date < ?
          AND weight_kg IS NOT NULL AND weight_kg > 0
        ORDER BY date
    """, (uid, since_14, since_7)).fetchall()

    # Веса за вторую половину (последние 7 дней)
    recent_rows = conn.execute("""
        SELECT weight_kg FROM metrics
        WHERE user_id = ? AND date >= ?
          AND weight_kg IS NOT NULL AND weight_kg > 0
        ORDER BY date
    """, (uid, since_7)).fetchall()

    if len(early_rows) < 2 or len(recent_rows) < 2:
        return None  # недостаточно данных

    total_points = len(early_rows) + len(recent_rows)
    if total_points < _WEIGHT_TREND_MIN_DAYS:
        return None

    avg_early  = sum(r["weight_kg"] for r in early_rows)  / len(early_rows)
    avg_recent = sum(r["weight_kg"] for r in recent_rows) / len(recent_rows)

    if avg_early <= 0:
        return None

    change_pct = (avg_recent - avg_early) / avg_early * 100

    if abs(change_pct) < _WEIGHT_TREND_CHANGE_PCT:
        return None  # изменение в норме

    # Получаем цель пользователя
    goal_row = conn.execute(
        "SELECT goal FROM user_profile WHERE id = ?", (uid,)
    ).fetchone()
    goal = (goal_row["goal"] or "") if goal_row else ""

    direction = "вверх" if change_pct > 0 else "вниз"
    change_abs = abs(avg_recent - avg_early)
    arrow = "📈" if change_pct > 0 else "📉"

    # Оцениваем соответствие цели
    if change_pct > 0 and "похудеть" in goal:
        tone = (
            f"⚠️ Обрати внимание — вес идёт *вверх*, "
            f"а твоя цель — похудеть. Проверь питание и дефицит калорий."
        )
    elif change_pct < 0 and "набрать массу" in goal:
        tone = (
            f"⚠️ Вес снижается, а твоя цель — набор массы. "
            f"Возможно, нужно увеличить калорийность рациона."
        )
    elif abs(change_pct) > 5:
        tone = (
            f"Значительное изменение за короткий срок. "
            f"Убедись, что всё идёт по плану."
        )
    else:
        tone = f"Следи за динамикой и корректируй питание если нужно."

    return (
        f"{arrow} *Тренд веса*\n\n"
        f"За последние 14 дней вес идёт *{direction}*: "
        f"{avg_early:.1f} → {avg_recent:.1f} кг "
        f"({'+' if change_pct > 0 else ''}{change_pct:.1f}%, "
        f"{'+' if change_pct > 0 else ''}{change_abs:.1f} кг).\n\n"
        f"{tone}"
    )


# ─── Диспетчер нудж-сообщений ─────────────────────────────────────────────────

# Приоритет: drop (срочность) > recovery (здоровье) > pr > streak > goal > weight
_NUDGE_CHECKERS: list[tuple[str, callable]] = [
    ("drop",           _check_drop_nudge),
    ("recovery",       _check_recovery_nudge),
    ("pr_approaching", _check_pr_nudge),
    ("streak",         _check_streak_nudge),
    ("goal_progress",  _check_goal_nudge),
    ("weight_trend",   _check_weight_trend_nudge),
]


async def check_and_send_nudges_for_user(
    uid: int, telegram_id: int, bot: Bot
) -> None:
    """
    Запускает все проверки нудж-условий для одного пользователя.
    Отправляет не более ОДНОГО нуджа за запуск (первый сработавший по приоритету).
    """
    for nudge_type, checker_fn in _NUDGE_CHECKERS:
        if _was_nudge_sent_recently(uid, nudge_type):
            logger.debug(
                f"[NUDGE] '{nudge_type}' on cooldown for uid={uid}, skipping"
            )
            continue

        try:
            msg = checker_fn(uid)
        except Exception as e:
            logger.error(
                f"[NUDGE] Checker '{nudge_type}' failed for uid={uid}: {e}"
            )
            continue

        if not msg:
            continue

        try:
            await bot.send_message(
                chat_id=telegram_id,
                text=msg,
                parse_mode="Markdown",
            )
            _log_nudge(uid, nudge_type, msg)
            logger.info(
                f"[NUDGE] Sent '{nudge_type}' nudge to telegram_id={telegram_id}"
            )
        except Exception as e:
            logger.error(
                f"[NUDGE] Failed to send '{nudge_type}' to {telegram_id}: {e}"
            )

        return  # только один нудж за раз, независимо от успеха/ошибки отправки

    logger.debug(f"[NUDGE] No nudge triggered for uid={uid}")


async def check_and_send_nudges(bot: Bot) -> None:
    """
    Ежедневная рассылка проверок нудж-условий для всех активных пользователей.
    Вызывается из scheduler в NUDGE_CHECK_TIME (08:00).
    Молчащие пользователи пропускаются.
    """
    from scheduler.logic import _get_all_active_users, _should_silence

    users = _get_all_active_users()
    logger.info(f"[NUDGE] Starting nudge check for {len(users)} users")

    for user in users:
        if _should_silence(user):
            logger.debug(
                f"[NUDGE] Skipping silenced user {user['telegram_id']}"
            )
            continue
        try:
            await check_and_send_nudges_for_user(
                user["id"], user["telegram_id"], bot
            )
        except Exception as e:
            logger.error(
                f"[NUDGE] Broadcast failed for {user['telegram_id']}: {e}"
            )

    logger.info("[NUDGE] Nudge check complete")
