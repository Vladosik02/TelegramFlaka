"""
db/queries/exercises.py — CRUD для детального лога упражнений и личных рекордов.

Таблицы:
  exercise_results — детальный лог каждого упражнения (sets/reps/weight)
  personal_records — история личных рекордов с прогрессией

Принцип:
  При каждом log_exercise_result() автоматически проверяется личный рекорд.
  Если превышен — запись уходит в personal_records, флаг is_personal_record=1.
"""
import logging
import datetime
from db.connection import get_connection

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# ЖУРНАЛ УПРАЖНЕНИЙ
# ═══════════════════════════════════════════════════════════════════════════

def log_exercise_result(
    user_id: int,
    exercise_name: str,
    date: str = None,
    workout_id: int = None,
    sets: int = None,
    reps: int = None,
    duration_sec: int = None,
    weight_kg: float = None,
    notes: str = None,
) -> int:
    """
    Сохраняет результат одного упражнения.
    Автоматически проверяет и устанавливает личный рекорд.
    Возвращает id созданной записи.
    """
    conn = get_connection()
    if not date:
        date = datetime.date.today().isoformat()

    cursor = conn.execute("""
        INSERT INTO exercise_results
            (user_id, workout_id, date, exercise_name, sets, reps,
             duration_sec, weight_kg, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, workout_id, date, exercise_name,
          sets, reps, duration_sec, weight_kg, notes))
    conn.commit()

    result_id = cursor.lastrowid
    # Проверка личного рекорда
    _check_and_set_record(
        user_id, exercise_name, reps, duration_sec, weight_kg, date, result_id
    )
    return result_id


def _check_and_set_record(
    user_id: int,
    exercise_name: str,
    reps, duration_sec, weight_kg,
    date: str,
    result_id: int,
) -> None:
    """
    Определяет тип рекорда по приоритету: weight > time > reps.
    Если результат лучше текущего рекорда — создаёт запись в personal_records.
    """
    conn = get_connection()

    if weight_kg and weight_kg > 0:
        record_type, new_value = "weight", weight_kg
    elif duration_sec and duration_sec > 0:
        record_type, new_value = "time", float(duration_sec)
    elif reps and reps > 0:
        record_type, new_value = "reps", float(reps)
    else:
        return   # нечего сравнивать

    existing = conn.execute("""
        SELECT id, record_value FROM personal_records
        WHERE user_id = ? AND exercise_name = ? AND record_type = ?
        ORDER BY record_value DESC LIMIT 1
    """, (user_id, exercise_name, record_type)).fetchone()

    if existing is None or new_value > existing["record_value"]:
        prev = float(existing["record_value"]) if existing else None
        improvement = None
        if prev and prev > 0:
            improvement = round((new_value - prev) / prev * 100, 1)

        conn.execute("""
            INSERT INTO personal_records
                (user_id, exercise_name, record_value, record_type, set_at,
                 previous_record, improvement_pct)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, exercise_name, new_value, record_type,
              date, prev, improvement))

        # Помечаем результат как рекордный
        conn.execute(
            "UPDATE exercise_results SET is_personal_record = 1 WHERE id = ?",
            (result_id,)
        )
        conn.commit()

        logger.info(
            f"[PR] New {record_type} record for user={user_id}: "
            f"{exercise_name} = {new_value}"
            + (f" (+{improvement}%)" if improvement else "")
        )


def get_exercise_history(
    user_id: int, exercise_name: str, days: int = 90
) -> list[dict]:
    """История конкретного упражнения за N дней (от свежего к старому)."""
    conn = get_connection()
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT * FROM exercise_results
        WHERE user_id = ? AND exercise_name = ? AND date >= ?
        ORDER BY date DESC
    """, (user_id, exercise_name, since)).fetchall()
    return [dict(r) for r in rows]


def get_recent_exercises(user_id: int, days: int = 30, limit: int = 20) -> list[dict]:
    """Все упражнения за N дней — для аналитики и контекста."""
    conn = get_connection()
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT * FROM exercise_results
        WHERE user_id = ? AND date >= ?
        ORDER BY date DESC LIMIT ?
    """, (user_id, since, limit)).fetchall()
    return [dict(r) for r in rows]


def get_exercise_last_result(user_id: int, exercise_name: str) -> dict | None:
    """Последний результат по конкретному упражнению (для сравнения прогрессии)."""
    conn = get_connection()
    row = conn.execute("""
        SELECT * FROM exercise_results
        WHERE user_id = ? AND exercise_name = ?
        ORDER BY date DESC, id DESC LIMIT 1
    """, (user_id, exercise_name)).fetchone()
    return dict(row) if row else None


# ═══════════════════════════════════════════════════════════════════════════
# ЛИЧНЫЕ РЕКОРДЫ
# ═══════════════════════════════════════════════════════════════════════════

def get_personal_records(user_id: int, limit: int = 10) -> list[dict]:
    """
    Лучший рекорд на каждое упражнение + тип.
    Возвращает до limit записей, сортировка по дате (свежие первые).
    """
    conn = get_connection()
    rows = conn.execute("""
        SELECT pr.*
        FROM personal_records pr
        INNER JOIN (
            SELECT exercise_name, record_type, MAX(record_value) AS max_val
            FROM personal_records WHERE user_id = ?
            GROUP BY exercise_name, record_type
        ) best
            ON pr.exercise_name = best.exercise_name
           AND pr.record_type   = best.record_type
           AND pr.record_value   = best.max_val
           AND pr.user_id        = ?
        ORDER BY pr.set_at DESC
        LIMIT ?
    """, (user_id, user_id, limit)).fetchall()
    return [dict(r) for r in rows]


def get_record_for_exercise(
    user_id: int, exercise_name: str, record_type: str = None
) -> dict | None:
    """
    Лучший рекорд для конкретного упражнения.
    record_type: 'weight' | 'reps' | 'time' — если None, берёт любой.
    """
    conn = get_connection()
    if record_type:
        row = conn.execute("""
            SELECT * FROM personal_records
            WHERE user_id = ? AND exercise_name = ? AND record_type = ?
            ORDER BY record_value DESC LIMIT 1
        """, (user_id, exercise_name, record_type)).fetchone()
    else:
        row = conn.execute("""
            SELECT * FROM personal_records
            WHERE user_id = ? AND exercise_name = ?
            ORDER BY record_value DESC LIMIT 1
        """, (user_id, exercise_name)).fetchone()
    return dict(row) if row else None


def get_recent_records(user_id: int, days: int = 30) -> list[dict]:
    """Рекорды установленные за последние N дней."""
    conn = get_connection()
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT * FROM personal_records
        WHERE user_id = ? AND set_at >= ?
        ORDER BY set_at DESC
    """, (user_id, since)).fetchall()
    return [dict(r) for r in rows]
