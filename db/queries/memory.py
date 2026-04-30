"""
db/queries/memory.py — CRUD для 4-слойной памяти (L0–L4).

Слои:
  L0 + L1  →  memory_athlete
  L2       →  memory_nutrition
  L3       →  memory_training
  L4       →  memory_intelligence
"""
import json
import logging
import datetime
from db.connection import get_connection

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ
# ═══════════════════════════════════════════════════════════════════════════

def _json_get(row: dict, field: str, default):
    """Безопасный парсинг JSON-поля из строки БД."""
    raw = row.get(field)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def _now() -> str:
    return datetime.datetime.now().isoformat()


# ═══════════════════════════════════════════════════════════════════════════
# L0 + L1: КАРТОЧКА АТЛЕТА
# ═══════════════════════════════════════════════════════════════════════════

def get_athlete_card(user_id: int) -> dict | None:
    """Возвращает всю карточку (L0 + L1) или None если нет записи."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM memory_athlete WHERE user_id = ?", (user_id,)
    ).fetchone()
    return dict(row) if row else None


def upsert_athlete_card(user_id: int, **fields) -> None:
    """
    Создаёт или обновляет карточку атлета.
    JSON-поля (food_intolerances, supplement_reactions, personal_records)
    можно передавать как list/dict — они будут сериализованы автоматически.
    """
    conn = get_connection()
    for key in ("food_intolerances", "supplement_reactions", "personal_records"):
        if key in fields and not isinstance(fields[key], str):
            fields[key] = json.dumps(fields[key], ensure_ascii=False)

    existing = conn.execute(
        "SELECT user_id FROM memory_athlete WHERE user_id = ?", (user_id,)
    ).fetchone()

    fields["updated_at"] = _now()

    if existing:
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(
            f"UPDATE memory_athlete SET {set_clause} WHERE user_id = ?",
            list(fields.values()) + [user_id]
        )
    else:
        fields["user_id"] = user_id
        placeholders = ", ".join("?" * len(fields))
        cols = ", ".join(fields.keys())
        conn.execute(
            f"INSERT INTO memory_athlete ({cols}) VALUES ({placeholders})",
            list(fields.values())
        )
    conn.commit()


def get_l0_surface(user_id: int) -> dict:
    """Возвращает только L0-поля (age, height_cm, season)."""
    row = get_athlete_card(user_id)
    if not row:
        return {}
    return {
        "age":       row.get("age"),
        "height_cm": row.get("height_cm"),
        "season":    row.get("season", "maintain"),
    }


def get_l1_deep_bio(user_id: int) -> dict:
    """Возвращает L1-поля (intolerances, reactions, records)."""
    row = get_athlete_card(user_id)
    if not row:
        return {}
    return {
        "food_intolerances":   _json_get(row, "food_intolerances", []),
        "supplement_reactions": _json_get(row, "supplement_reactions", {}),
        "personal_records":    _json_get(row, "personal_records", {}),
    }


# ═══════════════════════════════════════════════════════════════════════════
# L2: ПИТАНИЕ
# ═══════════════════════════════════════════════════════════════════════════

def get_nutrition(user_id: int) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM memory_nutrition WHERE user_id = ?", (user_id,)
    ).fetchone()
    return dict(row) if row else None


def upsert_nutrition(user_id: int, **fields) -> None:
    """JSON-поля: meal_preferences, supplements, restrictions — принимают list/dict."""
    conn = get_connection()
    for key in ("meal_preferences", "supplements", "restrictions"):
        if key in fields and not isinstance(fields[key], str):
            fields[key] = json.dumps(fields[key], ensure_ascii=False)

    existing = conn.execute(
        "SELECT user_id FROM memory_nutrition WHERE user_id = ?", (user_id,)
    ).fetchone()

    fields["updated_at"] = _now()

    if existing:
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(
            f"UPDATE memory_nutrition SET {set_clause} WHERE user_id = ?",
            list(fields.values()) + [user_id]
        )
    else:
        fields["user_id"] = user_id
        placeholders = ", ".join("?" * len(fields))
        cols = ", ".join(fields.keys())
        conn.execute(
            f"INSERT INTO memory_nutrition ({cols}) VALUES ({placeholders})",
            list(fields.values())
        )
    conn.commit()


def get_l2_brief(user_id: int) -> dict:
    """L2 brief: только макронутриенты и калории."""
    row = get_nutrition(user_id)
    if not row:
        return {}
    return {
        "daily_calories": row.get("daily_calories"),
        "protein_g":      row.get("protein_g"),
        "fat_g":          row.get("fat_g"),
        "carbs_g":        row.get("carbs_g"),
    }


def get_l2_deep(user_id: int) -> dict:
    """L2 deep: + предпочтения, добавки, ограничения."""
    row = get_nutrition(user_id)
    if not row:
        return {}
    return {
        "daily_calories":  row.get("daily_calories"),
        "protein_g":       row.get("protein_g"),
        "fat_g":           row.get("fat_g"),
        "carbs_g":         row.get("carbs_g"),
        "meal_preferences": _json_get(row, "meal_preferences", {}),
        "supplements":     _json_get(row, "supplements", []),
        "restrictions":    _json_get(row, "restrictions", []),
        "last_meal_notes": row.get("last_meal_notes"),
    }


# ═══════════════════════════════════════════════════════════════════════════
# L3: ТРЕНИРОВОЧНЫЙ ИНТЕЛЛЕКТ
# ═══════════════════════════════════════════════════════════════════════════

def get_training_intel(user_id: int) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM memory_training WHERE user_id = ?", (user_id,)
    ).fetchone()
    return dict(row) if row else None


def upsert_training_intel(user_id: int, **fields) -> None:
    """JSON-поля: preferred_days, exercise_scores, avoided_exercises."""
    conn = get_connection()
    for key in ("preferred_days", "exercise_scores", "avoided_exercises"):
        if key in fields and not isinstance(fields[key], str):
            fields[key] = json.dumps(fields[key], ensure_ascii=False)

    existing = conn.execute(
        "SELECT user_id FROM memory_training WHERE user_id = ?", (user_id,)
    ).fetchone()

    fields["updated_at"] = _now()

    if existing:
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(
            f"UPDATE memory_training SET {set_clause} WHERE user_id = ?",
            list(fields.values()) + [user_id]
        )
    else:
        fields["user_id"] = user_id
        placeholders = ", ".join("?" * len(fields))
        cols = ", ".join(fields.keys())
        conn.execute(
            f"INSERT INTO memory_training ({cols}) VALUES ({placeholders})",
            list(fields.values())
        )
    conn.commit()


def update_exercise_score(user_id: int, exercise: str, score: float,
                           pattern: str = "") -> None:
    """
    Обновляет SCORE конкретного упражнения.
    SCORE = overload×0.4 + consistency×0.3 + alignment×0.3
    Значение < 4.0 → упражнение кандидат на замену.
    """
    row = get_training_intel(user_id)
    if row:
        scores = _json_get(row, "exercise_scores", {})
    else:
        scores = {}
    scores[exercise] = {"score": round(score, 2), "pattern": pattern}
    upsert_training_intel(user_id, exercise_scores=scores)


def get_l3_brief(user_id: int) -> dict:
    """L3 brief: preferred_days, preferred_time, avg_session_min, current_program, equipment."""
    row = get_training_intel(user_id)
    if not row:
        return {}
    return {
        "preferred_days":  _json_get(row, "preferred_days", []),
        "preferred_time":  row.get("preferred_time", "flexible"),
        "avg_session_min": row.get("avg_session_min", 45),
        "current_program": row.get("current_program"),
        "equipment":       _json_get(row, "equipment", []),
    }


def get_l3_deep(user_id: int) -> dict:
    """L3 deep: + SCORE-таблица упражнений, avoided_exercises, notes, equipment."""
    row = get_training_intel(user_id)
    if not row:
        return {}
    scores = _json_get(row, "exercise_scores", {})
    # Показываем только упражнения со SCORE < 4 или > 7 (проблемы и лидеры)
    notable = {
        ex: data for ex, data in scores.items()
        if isinstance(data, dict) and (data.get("score", 5) < 4.0 or data.get("score", 5) > 7.0)
    }
    return {
        "preferred_days":   _json_get(row, "preferred_days", []),
        "preferred_time":   row.get("preferred_time", "flexible"),
        "avg_session_min":  row.get("avg_session_min", 45),
        "current_program":  row.get("current_program"),
        "notable_exercises": notable,   # только notable, экономим токены
        "avoided_exercises": _json_get(row, "avoided_exercises", []),
        "training_notes":   row.get("training_notes"),
        "equipment":        _json_get(row, "equipment", []),
    }


# ═══════════════════════════════════════════════════════════════════════════
# L4: AI INTELLIGENCE
# ═══════════════════════════════════════════════════════════════════════════

def get_intelligence(user_id: int) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM memory_intelligence WHERE user_id = ?", (user_id,)
    ).fetchone()
    return dict(row) if row else None


def upsert_intelligence(user_id: int, **fields) -> None:
    """JSON-поля: ai_observations."""
    conn = get_connection()
    if "ai_observations" in fields and not isinstance(fields["ai_observations"], str):
        fields["ai_observations"] = json.dumps(
            fields["ai_observations"], ensure_ascii=False
        )

    existing = conn.execute(
        "SELECT user_id FROM memory_intelligence WHERE user_id = ?", (user_id,)
    ).fetchone()

    fields["generated_at"] = _now()

    if existing:
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(
            f"UPDATE memory_intelligence SET {set_clause} WHERE user_id = ?",
            list(fields.values()) + [user_id]
        )
    else:
        fields["user_id"] = user_id
        placeholders = ", ".join("?" * len(fields))
        cols = ", ".join(fields.keys())
        conn.execute(
            f"INSERT INTO memory_intelligence ({cols}) VALUES ({placeholders})",
            list(fields.values())
        )
    conn.commit()


def get_l4_intelligence(user_id: int) -> dict:
    """Возвращает L4 данные для включения в контекст."""
    row = get_intelligence(user_id)
    if not row:
        return {}
    return {
        "weekly_digest":    row.get("weekly_digest"),
        "ai_observations":  _json_get(row, "ai_observations", []),
        "seasonal_context": row.get("seasonal_context"),
        "motivation_level": row.get("motivation_level", "normal"),
        "trend_summary":    row.get("trend_summary"),
        "bio_insights":     row.get("bio_insights"),
        "generated_at":     row.get("generated_at"),
    }




def append_observation(user_id: int, observation: str,
                        max_observations: int = 10,
                        replace_prefix: str = None) -> None:
    """Добавляет AI-наблюдение в список, сохраняя последние N штук.

    replace_prefix: если передан, удаляет все существующие наблюдения,
    начинающиеся с этого префикса, перед добавлением нового.
    Используется для accuracy-observations — обновляем «занижены на X кг»
    вместо накопления вариаций с разными числами.
    """
    row = get_intelligence(user_id)
    if row:
        obs = _json_get(row, "ai_observations", [])
    else:
        obs = []
    if replace_prefix:
        obs = [o for o in obs if not o.startswith(replace_prefix)]
    if observation not in obs:
        obs.append(observation)
    obs = obs[-max_observations:]  # сохраняем только последние N
    upsert_intelligence(user_id, ai_observations=obs)
