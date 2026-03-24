"""
db/queries/gamification.py — XP, уровни и ачивки.

Фаза 10.4 — Gamification.

Таблицы: user_xp, achievements, xp_log

Уровневая система (8 уровней):
  1  Новичок      0 XP
  2  Стартер      500 XP
  3  Атлет        1 500 XP
  4  Боец         3 000 XP
  5  Чемпион      5 500 XP
  6  Элита        9 000 XP
  7  Мастер       14 000 XP
  8  Легенда      21 000 XP
"""

import logging
import datetime
from db.connection import get_connection

logger = logging.getLogger(__name__)

# ───────────────────────────────────────────────────────────────────────────
# КОНСТАНТЫ
# ───────────────────────────────────────────────────────────────────────────

LEVELS = [
    (1,  "Новичок",   0),
    (2,  "Стартер",   500),
    (3,  "Атлет",     1_500),
    (4,  "Боец",      3_000),
    (5,  "Чемпион",   5_500),
    (6,  "Элита",     9_000),
    (7,  "Мастер",    14_000),
    (8,  "Легенда",   21_000),
]

# Определения ачивок: ключ → (название, описание, XP-награда, тип-условие)
ACHIEVEMENT_CATALOG = {
    "first_workout":    ("Первый шаг 🏃", "Первая тренировка записана", 50, "workout"),
    "workout_10":       ("На разогреве 🔥", "10 тренировок суммарно", 100, "workout"),
    "workout_50":       ("Полтинник 💪", "50 тренировок суммарно", 250, "workout"),
    "workout_100":      ("Сотка 🏆", "100 тренировок суммарно", 500, "workout"),
    "streak_3":         ("3 дня подряд ⚡", "3 тренировки три дня подряд", 75, "streak"),
    "streak_7":         ("Неделя без выходных 🗓", "7 дней тренировок подряд", 150, "streak"),
    "streak_30":        ("Месяц-монстр 🦁", "30 дней тренировок подряд", 500, "streak"),
    "first_pr":         ("Рекордсмен 🎯", "Первый личный рекорд", 100, "personal_record"),
    "pr_5":             ("PR-машина 🚀", "5 личных рекордов суммарно", 200, "personal_record"),
    "level_up_3":       ("Развитие 📈", "Достиг уровня 3 (Атлет)", 0, "level"),
    "level_up_5":       ("Элита начинается 🌟", "Достиг уровня 5 (Чемпион)", 0, "level"),
    "level_up_8":       ("Легенда 👑", "Достиг максимального уровня", 0, "level"),
    "nutrition_week":   ("Чистое питание 🥗", "7 дней подряд записывал КБЖУ", 100, "nutrition"),
    "fitness_test":     ("Проверил себя 📊", "Прошёл фитнес-тест", 75, "fitness_test"),
}


# ───────────────────────────────────────────────────────────────────────────
# XP
# ───────────────────────────────────────────────────────────────────────────

def _ensure_xp_row(user_id: int) -> None:
    """Создаёт строку в user_xp если не существует."""
    conn = get_connection()
    conn.execute("""
        INSERT OR IGNORE INTO user_xp (user_id, total_xp, current_level, level_name)
        VALUES (?, 0, 1, 'Новичок')
    """, (user_id,))
    conn.commit()


def add_xp(user_id: int, amount: int, reason: str, detail: str = None) -> int:
    """
    Начисляет XP пользователю.
    Автоматически повышает уровень если нужно.
    Возвращает новое суммарное количество XP.
    """
    _ensure_xp_row(user_id)
    conn = get_connection()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Записываем транзакцию
    conn.execute("""
        INSERT INTO xp_log (user_id, xp_amount, reason, detail, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, amount, reason, detail, now))

    # Обновляем total_xp
    conn.execute("""
        UPDATE user_xp
        SET total_xp = total_xp + ?,
            last_xp_at = ?,
            updated_at = ?
        WHERE user_id = ?
    """, (amount, now, now, user_id))
    conn.commit()

    # Получаем новый total
    row = conn.execute(
        "SELECT total_xp FROM user_xp WHERE user_id = ?", (user_id,)
    ).fetchone()
    new_total = row["total_xp"] if row else 0

    # Обновляем уровень
    level_num, level_name = _compute_level(new_total)
    conn.execute("""
        UPDATE user_xp
        SET current_level = ?, level_name = ?
        WHERE user_id = ?
    """, (level_num, level_name, user_id))
    conn.commit()

    # Обновляем streak если reason = workout
    if reason == "workout":
        _update_streak(user_id)

    logger.info(
        f"[XP] user={user_id} +{amount}XP reason={reason} "
        f"total={new_total} level={level_num}"
    )
    return new_total


def _compute_level(total_xp: int) -> tuple[int, str]:
    """Возвращает (номер_уровня, название) для заданного XP."""
    current = (1, "Новичок")
    for lvl_num, lvl_name, threshold in LEVELS:
        if total_xp >= threshold:
            current = (lvl_num, lvl_name)
        else:
            break
    return current


def _update_streak(user_id: int) -> None:
    """Обновляет streak_days — количество дней тренировок подряд."""
    from db.connection import get_connection
    conn = get_connection()
    today = datetime.date.today().isoformat()
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()

    # Была ли тренировка вчера?
    had_yesterday = conn.execute("""
        SELECT COUNT(*) as cnt FROM workouts
        WHERE user_id = ? AND date = ? AND completed = 1
    """, (user_id, yesterday)).fetchone()["cnt"]

    # Была ли тренировка сегодня?
    had_today = conn.execute("""
        SELECT COUNT(*) as cnt FROM workouts
        WHERE user_id = ? AND date = ? AND completed = 1
    """, (user_id, today)).fetchone()["cnt"]

    if had_today:
        if had_yesterday:
            conn.execute(
                "UPDATE user_xp SET streak_days = streak_days + 1 WHERE user_id = ?",
                (user_id,)
            )
        else:
            conn.execute(
                "UPDATE user_xp SET streak_days = 1 WHERE user_id = ?",
                (user_id,)
            )
        conn.commit()


def get_user_level_info(user_id: int) -> dict | None:
    """Возвращает текущий уровень, XP и streak пользователя."""
    _ensure_xp_row(user_id)
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM user_xp WHERE user_id = ?", (user_id,)
    ).fetchone()
    if not row:
        return None

    total = row["total_xp"]
    lvl_num, _ = _compute_level(total)

    # Прогресс до следующего уровня
    next_threshold = None
    for num, name, threshold in LEVELS:
        if num == lvl_num + 1:
            next_threshold = threshold
            break

    xp_for_next = (next_threshold - total) if next_threshold else 0

    return {
        "total_xp": total,
        "current_level": row["current_level"],
        "level_name": row["level_name"],
        "streak_days": row["streak_days"] or 0,
        "xp_to_next_level": max(0, xp_for_next),
        "next_threshold": next_threshold,
    }


def get_xp_history(user_id: int, limit: int = 20) -> list[dict]:
    """Последние N XP-транзакций."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM xp_log
        WHERE user_id = ?
        ORDER BY created_at DESC LIMIT ?
    """, (user_id, limit)).fetchall()
    return [dict(r) for r in rows]


# ───────────────────────────────────────────────────────────────────────────
# АЧИВКИ
# ───────────────────────────────────────────────────────────────────────────

def get_user_achievements(user_id: int) -> list[dict]:
    """Все разблокированные ачивки пользователя."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM achievements
        WHERE user_id = ?
        ORDER BY unlocked_at DESC
    """, (user_id,)).fetchall()
    return [dict(r) for r in rows]


def _unlock_achievement(user_id: int, key: str) -> bool:
    """
    Разблокирует ачивку. Возвращает True если только что разблокирована.
    Начисляет XP за ачивку.
    """
    if key not in ACHIEVEMENT_CATALOG:
        return False

    name, desc, xp_reward, _ = ACHIEVEMENT_CATALOG[key]
    conn = get_connection()

    try:
        conn.execute("""
            INSERT INTO achievements
                (user_id, achievement_key, achievement_name, description, xp_reward)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, key, name, desc, xp_reward))
        conn.commit()
    except Exception:
        return False  # Уже есть (UNIQUE constraint)

    # Начисляем XP за ачивку (если > 0)
    if xp_reward > 0:
        add_xp(user_id, xp_reward, "milestone", f"Ачивка: {name}")

    logger.info(f"[ACHIEVEMENT] user={user_id} unlocked='{key}' name='{name}'")
    return True


async def check_and_unlock_achievements(
    user_id: int,
    tg_id: int,
    trigger: str,
    bot=None,
    chat_id: int = None,
) -> list[str]:
    """
    Проверяет и разблокирует ачивки по триггеру.
    Отправляет уведомление в чат если bot/chat_id переданы.
    Возвращает список новых ачивок.
    """
    conn = get_connection()
    new_achievements = []

    # ── Тренировки ──────────────────────────────────────────────────────────
    if trigger == "workout":
        total_workouts = conn.execute(
            "SELECT COUNT(*) as cnt FROM workouts WHERE user_id = ? AND completed = 1",
            (user_id,)
        ).fetchone()["cnt"]

        for key, threshold in [
            ("first_workout", 1), ("workout_10", 10),
            ("workout_50", 50), ("workout_100", 100)
        ]:
            if total_workouts >= threshold and _unlock_achievement(user_id, key):
                new_achievements.append(key)

        # Streak ачивки
        xp_row = conn.execute(
            "SELECT streak_days FROM user_xp WHERE user_id = ?", (user_id,)
        ).fetchone()
        streak = xp_row["streak_days"] if xp_row else 0

        for key, threshold in [("streak_3", 3), ("streak_7", 7), ("streak_30", 30)]:
            if streak >= threshold and _unlock_achievement(user_id, key):
                new_achievements.append(key)

    # ── Личные рекорды ───────────────────────────────────────────────────────
    elif trigger == "personal_record":
        total_prs = conn.execute(
            "SELECT COUNT(*) as cnt FROM personal_records WHERE user_id = ?",
            (user_id,)
        ).fetchone()["cnt"]

        for key, threshold in [("first_pr", 1), ("pr_5", 5)]:
            if total_prs >= threshold and _unlock_achievement(user_id, key):
                new_achievements.append(key)

    # ── Уровень ──────────────────────────────────────────────────────────────
    elif trigger == "level":
        level_info = get_user_level_info(user_id)
        if level_info:
            lvl = level_info["current_level"]
            for key, threshold in [
                ("level_up_3", 3), ("level_up_5", 5), ("level_up_8", 8)
            ]:
                if lvl >= threshold and _unlock_achievement(user_id, key):
                    new_achievements.append(key)

    # ── Фитнес-тест ──────────────────────────────────────────────────────────
    elif trigger == "fitness_test":
        if _unlock_achievement(user_id, "fitness_test"):
            new_achievements.append("fitness_test")

    # ── Отправляем уведомления ───────────────────────────────────────────────
    if new_achievements and bot and chat_id:
        for key in new_achievements:
            if key in ACHIEVEMENT_CATALOG:
                name, desc, xp, _ = ACHIEVEMENT_CATALOG[key]
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=(
                            f"🏅 *Новая ачивка!*\n"
                            f"*{name}*\n"
                            f"_{desc}_"
                            + (f"\n+{xp} XP" if xp > 0 else "")
                        ),
                        parse_mode="Markdown",
                    )
                except Exception as e:
                    logger.warning(f"[ACH] notify error: {e}")

    return new_achievements


def format_achievements_message(user_id: int) -> str:
    """
    Форматирует сообщение /achievements для пользователя.
    Показывает уровень, XP, прогресс и разблокированные ачивки.
    """
    level_info = get_user_level_info(user_id)
    achievements = get_user_achievements(user_id)

    if not level_info:
        return "Ещё нет данных. Начни первую тренировку! 💪"

    lvl = level_info["current_level"]
    total_xp = level_info["total_xp"]
    level_name = level_info["level_name"]
    streak = level_info["streak_days"]
    xp_to_next = level_info["xp_to_next_level"]
    next_thresh = level_info["next_threshold"]

    # Прогресс-бар (10 блоков)
    if next_thresh and next_thresh > 0:
        # XP внутри текущего уровня
        prev_threshold = 0
        for num, name, thr in LEVELS:
            if num == lvl:
                prev_threshold = thr
                break
        level_xp = total_xp - prev_threshold
        level_range = next_thresh - prev_threshold
        progress = min(10, int(level_xp / level_range * 10)) if level_range > 0 else 10
        bar = "█" * progress + "░" * (10 - progress)
        progress_line = f"\n`[{bar}]` {level_xp}/{level_range} XP"
    else:
        progress_line = "\n🏆 Максимальный уровень!"

    lines = [
        f"⚡ *Уровень {lvl} — {level_name}*",
        f"Всего XP: *{total_xp}*",
    ]
    if xp_to_next > 0:
        lines.append(f"До следующего уровня: {xp_to_next} XP")
    lines.append(progress_line)

    if streak > 0:
        lines.append(f"\n🔥 Стрик: *{streak} дн.* подряд")

    if achievements:
        lines.append(f"\n🏅 *Ачивки ({len(achievements)}):*")
        for ach in achievements[:10]:  # показываем последние 10
            lines.append(f"• {ach['achievement_name']}")
        if len(achievements) > 10:
            lines.append(f"_...и ещё {len(achievements) - 10}_")

    # Намекаем на следующую ачивку
    unlocked_keys = {a["achievement_key"] for a in achievements}
    for key, (name, desc, xp, trigger_type) in ACHIEVEMENT_CATALOG.items():
        if key not in unlocked_keys:
            lines.append(f"\n🔒 Следующая: *{name}* — _{desc}_")
            break

    return "\n".join(lines)
