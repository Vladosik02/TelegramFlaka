"""
db/queries/nutrition.py — CRUD для журнала питания и AI-рекомендаций.

Таблицы:
  nutrition_log       — ежедневный журнал реального питания
  nutrition_insights  — AI-рекомендации (дефициты, предупреждения)

Цели питания (макронутриенты) хранятся в memory_nutrition (L2).
"""
import logging
import datetime
from db.connection import get_connection

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# ЖУРНАЛ ПИТАНИЯ
# ═══════════════════════════════════════════════════════════════════════════

def log_nutrition_day(user_id: int, date: str = None, **fields) -> None:
    """
    Создаёт или обновляет запись питания за день (upsert по user_id + date).
    Поддерживаемые поля: calories, protein_g, fat_g, carbs_g, water_ml,
                         meal_notes, quality_score, junk_food
    """
    conn = get_connection()
    if not date:
        date = datetime.date.today().isoformat()

    existing = conn.execute(
        "SELECT id FROM nutrition_log WHERE user_id = ? AND date = ?",
        (user_id, date)
    ).fetchone()

    if existing:
        if fields:
            # Обновляем только переданные поля
            set_clause = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(
                f"UPDATE nutrition_log SET {set_clause} WHERE user_id = ? AND date = ?",
                list(fields.values()) + [user_id, date]
            )
    else:
        fields["user_id"] = user_id
        fields["date"] = date
        placeholders = ", ".join("?" * len(fields))
        cols = ", ".join(fields.keys())
        conn.execute(
            f"INSERT INTO nutrition_log ({cols}) VALUES ({placeholders})",
            list(fields.values())
        )
    conn.commit()


def add_nutrition_to_day(user_id: int, date: str = None, **fields) -> None:
    """
    Накапливает КБЖУ за день: прибавляет значения к существующим.
    Если записи за день нет — создаёт новую.
    Числовые поля (calories, protein_g, fat_g, carbs_g) суммируются.
    Текстовые поля (meal_notes) дописываются через '; '.
    """
    conn = get_connection()
    if not date:
        date = datetime.date.today().isoformat()

    ADDITIVE_FIELDS = {"calories", "protein_g", "fat_g", "carbs_g", "water_ml"}

    existing = conn.execute(
        "SELECT * FROM nutrition_log WHERE user_id = ? AND date = ?",
        (user_id, date)
    ).fetchone()

    if existing:
        existing = dict(existing)
        updates = {}
        for k, v in fields.items():
            if v is None:
                continue
            if k in ADDITIVE_FIELDS:
                old_val = existing.get(k) or 0
                updates[k] = old_val + v
            elif k == "meal_notes":
                old_notes = existing.get("meal_notes") or ""
                updates[k] = f"{old_notes}; {v}".strip("; ") if old_notes else v
            else:
                updates[k] = v
        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(
                f"UPDATE nutrition_log SET {set_clause} WHERE user_id = ? AND date = ?",
                list(updates.values()) + [user_id, date]
            )
    else:
        clean = {k: v for k, v in fields.items() if v is not None}
        clean["user_id"] = user_id
        clean["date"] = date
        placeholders = ", ".join("?" * len(clean))
        cols = ", ".join(clean.keys())
        conn.execute(
            f"INSERT INTO nutrition_log ({cols}) VALUES ({placeholders})",
            list(clean.values())
        )
    conn.commit()
    logger.info(f"[NUTRITION] add_to_day user_id={user_id} date={date}: "
                + ", ".join(f"{k}={v}" for k, v in fields.items() if v is not None))


def get_nutrition_log(user_id: int, days: int = 7) -> list[dict]:
    """Журнал питания за последние N дней, от свежего к старому."""
    conn = get_connection()
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT * FROM nutrition_log WHERE user_id = ? AND date >= ? ORDER BY date DESC",
        (user_id, since)
    ).fetchall()
    return [dict(r) for r in rows]


def get_today_nutrition(user_id: int) -> dict | None:
    """Запись питания за сегодня или None."""
    conn = get_connection()
    today = datetime.date.today().isoformat()
    row = conn.execute(
        "SELECT * FROM nutrition_log WHERE user_id = ? AND date = ?",
        (user_id, today)
    ).fetchone()
    return dict(row) if row else None


def get_nutrition_summary(user_id: int, days: int = 7) -> dict:
    """
    Агрегат по питанию за N дней.
    Возвращает: log_days, avg_calories, avg_protein, avg_fat, avg_carbs,
                avg_water_ml, junk_food_days.
    """
    conn = get_connection()
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    row = conn.execute("""
        SELECT
            COUNT(*) as log_days,
            ROUND(AVG(calories),   0) as avg_calories,
            ROUND(AVG(protein_g),  1) as avg_protein,
            ROUND(AVG(fat_g),      1) as avg_fat,
            ROUND(AVG(carbs_g),    1) as avg_carbs,
            ROUND(AVG(water_ml),   0) as avg_water_ml,
            SUM(junk_food)             as junk_food_days
        FROM nutrition_log
        WHERE user_id = ? AND date >= ?
    """, (user_id, since)).fetchone()
    return dict(row) if row else {}


# ═══════════════════════════════════════════════════════════════════════════
# AI-ИНСАЙТЫ ПО ПИТАНИЮ
# ═══════════════════════════════════════════════════════════════════════════

def add_nutrition_insight(user_id: int, insight_type: str, description: str,
                           nutrient: str = None, action: str = None) -> None:
    """
    Добавляет AI-рекомендацию по питанию.
    insight_type: 'deficiency' | 'recommendation' | 'warning'
    """
    conn = get_connection()
    conn.execute("""
        INSERT INTO nutrition_insights (user_id, insight_type, nutrient, description, action)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, insight_type, nutrient, description, action))
    conn.commit()
    logger.info(f"[NUTRITION] insight added for user_id={user_id}: {insight_type} — {description[:60]}")


def get_active_insights(user_id: int, limit: int = 3) -> list[dict]:
    """Активные (нерешённые) инсайты — от свежего к старому."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM nutrition_insights
        WHERE user_id = ? AND resolved = 0
        ORDER BY detected_at DESC
        LIMIT ?
    """, (user_id, limit)).fetchall()
    return [dict(r) for r in rows]


def resolve_insight(insight_id: int) -> None:
    """Помечает инсайт как решённый."""
    conn = get_connection()
    conn.execute(
        "UPDATE nutrition_insights SET resolved = 1 WHERE id = ?",
        (insight_id,)
    )
    conn.commit()


def get_all_insights(user_id: int, limit: int = 10) -> list[dict]:
    """Все инсайты (включая решённые) — для /profile и аналитики."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM nutrition_insights
        WHERE user_id = ?
        ORDER BY detected_at DESC
        LIMIT ?
    """, (user_id, limit)).fetchall()
    return [dict(r) for r in rows]
