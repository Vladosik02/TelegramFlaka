"""
db/queries/fitness_metrics.py — CRUD фитнес-тестирования (Фаза 8.2).

Нормализация по piecewise-linear таблицам, основанным на:
  - ACSM Guidelines for Exercise Testing and Prescription (11th ed.)
  - Cooper Institute / YMCA Physical Fitness Assessment
  - NSCA Essentials of Strength Training and Conditioning (4th ed.)

Формула итогового fitness_score:
  fitness_score = pushups_score × 0.35 + squats_score × 0.35 + plank_score × 0.30

Веса отражают соотношение push/pull силы (верхняя и нижняя) + core stability.
"""
import datetime
import logging
from db.connection import get_connection

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# НОРМАЛИЗАЦИОННЫЕ ТАБЛИЦЫ (piecewise-linear breakpoints)
#
# Каждая таблица: список (raw_value, score) пар.
# Между точками — линейная интерполяция.
# За последней точкой — clamp к 100.
#
# Источники:
#   Pushups: ACSM norms (male 20-39), Cooper Institute percentiles
#     - Poor (<15), Below Avg (15-24), Avg (25-34), Good (35-49), Excellent (50+)
#     - Элитные атлеты (боксёры, гимнасты): 70-100+
#
#   Squats (bodyweight, max reps): NSCA endurance norms
#     - Базовый уровень: 20-30, тренированный: 50-70, продвинутый: 80-100+
#     - Элитные атлеты (пловцы, гимнасты): 100-150+
#
#   Plank: Cooper Institute, McGill standards
#     - Poor (<30s), Below Avg (30-60s), Avg (60-90s), Good (90-120s)
#     - Excellent (120-180s), Elite (180s+)
#     - Stuart McGill рекомендует 120s как порог «функциональной стабильности»
# ═══════════════════════════════════════════════════════════════════════════

_PUSHUPS_TABLE = [
    (0, 0),
    (10, 18),     # Poor → только начало
    (20, 35),     # Below Average
    (30, 52),     # Average (ACSM 50th percentile ≈25-30)
    (40, 68),     # Above Average
    (50, 80),     # Good (ACSM «Excellent» starts ~44-49)
    (65, 90),     # Very Good (уровень боксёров, борцов)
    (80, 96),     # Elite (гимнасты, кроссфитеры)
    (100, 100),   # World-class
]

_SQUATS_TABLE = [
    (0, 0),
    (15, 18),     # Beginner
    (30, 35),     # Below Average
    (45, 52),     # Average
    (60, 67),     # Above Average
    (80, 80),     # Good (тренированный атлет)
    (100, 89),    # Very Good (пловцы, велосипедисты)
    (130, 96),    # Elite
    (160, 100),   # World-class
]

_PLANK_TABLE = [
    (0, 0),
    (15, 8),      # Minimal
    (30, 20),     # Poor (ACSM)
    (60, 40),     # Below Average
    (90, 58),     # Average (McGill baseline)
    (120, 73),    # Good (McGill «functional stability» threshold)
    (180, 88),    # Excellent (3 min — уровень военных стандартов)
    (240, 95),    # Elite (4 min)
    (300, 100),   # World-class (5 min+)
]

# Уровни для отображения пользователю
_LEVEL_BRACKETS = [
    (0, "Начальный"),
    (25, "Ниже среднего"),
    (40, "Средний"),
    (60, "Хорошо"),
    (75, "Отлично"),
    (90, "Элитный"),
]


# ═══════════════════════════════════════════════════════════════════════════
# НОРМАЛИЗАЦИЯ
# ═══════════════════════════════════════════════════════════════════════════

def _piecewise_score(raw: int, table: list[tuple[int, int]]) -> float:
    """
    Piecewise-linear интерполяция по таблице breakpoints.
    Если raw >= последней точки, возвращает 100.
    """
    if raw <= 0:
        return 0.0
    if raw >= table[-1][0]:
        return 100.0

    # Находим сегмент
    for i in range(len(table) - 1):
        x0, y0 = table[i]
        x1, y1 = table[i + 1]
        if x0 <= raw <= x1:
            # Линейная интерполяция
            t = (raw - x0) / (x1 - x0) if x1 != x0 else 0
            return round(y0 + t * (y1 - y0), 1)

    return 100.0  # fallback


def normalize_pushups(raw: int) -> float:
    """Pushups → 0-100 score по ACSM/Cooper norms."""
    return _piecewise_score(raw, _PUSHUPS_TABLE)


def normalize_squats(raw: int) -> float:
    """Squats → 0-100 score по NSCA endurance norms."""
    return _piecewise_score(raw, _SQUATS_TABLE)


def normalize_plank(raw_sec: int) -> float:
    """Plank (seconds) → 0-100 score по Cooper/McGill standards."""
    return _piecewise_score(raw_sec, _PLANK_TABLE)


def compute_fitness_score(
    pushups_score: float,
    squats_score: float,
    plank_score: float,
) -> float:
    """
    Итоговый fitness_score (0-100).
    Веса: pushups=0.35, squats=0.35, plank=0.30.
    Push/pull balance + core stability.
    """
    return round(
        pushups_score * 0.35 + squats_score * 0.35 + plank_score * 0.30,
        1,
    )


def get_fitness_level(score: float) -> str:
    """Человекочитаемый уровень по fitness_score."""
    level = _LEVEL_BRACKETS[0][1]
    for threshold, name in _LEVEL_BRACKETS:
        if score >= threshold:
            level = name
    return level


# ═══════════════════════════════════════════════════════════════════════════
# CRUD
# ═══════════════════════════════════════════════════════════════════════════

def save_fitness_test(
    user_id: int,
    tested_at: str,
    max_pushups: int,
    max_squats: int,
    plank_sec: int,
    resting_hr: int | None = None,
) -> int:
    """
    Сохраняет результат фитнес-теста с автоматическим расчётом scores.
    Возвращает id новой записи.
    """
    p_score = normalize_pushups(max_pushups)
    s_score = normalize_squats(max_squats)
    pl_score = normalize_plank(plank_sec)
    f_score = compute_fitness_score(p_score, s_score, pl_score)
    strength = round((p_score + s_score) / 2, 1)

    conn = get_connection()
    cursor = conn.execute(
        """
        INSERT INTO user_fitness_metrics
            (user_id, tested_at, max_pushups, max_squats, plank_sec,
             resting_hr, pushups_score, squats_score, plank_score,
             fitness_score, strength_score, endurance_score, flexibility_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
        """,
        (
            user_id, tested_at, max_pushups, max_squats, plank_sec,
            resting_hr, p_score, s_score, pl_score, f_score, strength,
        ),
    )
    conn.commit()
    row_id = cursor.lastrowid
    logger.info(
        f"[FITNESS] user={user_id} test saved: "
        f"pushups={max_pushups}→{p_score} squats={max_squats}→{s_score} "
        f"plank={plank_sec}s→{pl_score} fitness={f_score}"
    )
    return row_id


def get_fitness_history(user_id: int, limit: int = 5) -> list[dict]:
    """Последние N тестов, от нового к старому."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT * FROM user_fitness_metrics
        WHERE user_id = ?
        ORDER BY tested_at DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_last_fitness_test(user_id: int) -> dict | None:
    """Последний тест или None."""
    conn = get_connection()
    row = conn.execute(
        """
        SELECT * FROM user_fitness_metrics
        WHERE user_id = ?
        ORDER BY tested_at DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


def get_fitness_score(user_id: int) -> dict | None:
    """
    Последний fitness_score для L0-контекста.
    Возвращает {score, tested_at} или None.
    """
    conn = get_connection()
    row = conn.execute(
        """
        SELECT fitness_score, tested_at
        FROM user_fitness_metrics
        WHERE user_id = ?
        ORDER BY tested_at DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    if not row:
        return None
    return {"score": row["fitness_score"], "tested_at": row["tested_at"]}


def days_since_last_test(user_id: int) -> int | None:
    """Дней с последнего теста, или None если тестов нет."""
    last = get_last_fitness_test(user_id)
    if not last:
        return None
    tested = datetime.date.fromisoformat(last["tested_at"])
    return (datetime.date.today() - tested).days
