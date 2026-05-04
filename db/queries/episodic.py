"""
db/queries/episodic.py — Эпизодическая память (A-MEM/MemGPT-inspired).

Фаза 10.5 — Episodic Memory.

Таблица: episodic_memory

TTL по типам:
  personal_record  → 90 дней
  insight          → 60 дней
  goal_update      → 365 дней
  conversation     → 30 дней
  milestone        → 180 дней

Принцип Zettelkasten: каждый эпизод — атомарный факт с тегами.
Claude получает N самых важных/свежих эпизодов в системный промпт.
"""

import json
import logging
import datetime
from db.connection import get_connection

logger = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────────────────────────
# ЗАПИСЬ
# ───────────────────────────────────────────────────────────────────────────

def save_episode(
    user_id: int,
    episode_type: str,
    summary: str,
    tags: list[str] = None,
    detail: str = None,
    importance: int = 5,
    ttl_days: int = 60,
) -> int:
    """
    Сохраняет эпизод в эпизодическую память.

    Возвращает id новой записи.
    ttl_days=0 означает «не истекает» (expires_at = NULL).
    """
    conn = get_connection()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    expires_at = None
    if ttl_days and ttl_days > 0:
        expires_at = (
            datetime.date.today() + datetime.timedelta(days=ttl_days)
        ).isoformat()

    tags_json = json.dumps(tags or [], ensure_ascii=False)

    cursor = conn.execute("""
        INSERT INTO episodic_memory
            (user_id, episode_type, tags, summary, detail, importance, expires_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, episode_type, tags_json, summary, detail, importance, expires_at, now))
    conn.commit()

    ep_id = cursor.lastrowid
    logger.info(
        f"[EPISODIC] saved id={ep_id} user={user_id} "
        f"type={episode_type} importance={importance} ttl={ttl_days}d"
    )
    return ep_id


# ───────────────────────────────────────────────────────────────────────────
# ЧТЕНИЕ
# ───────────────────────────────────────────────────────────────────────────

def get_recent_episodes(
    user_id: int,
    limit: int = 10,
    episode_type: str = None,
    min_importance: int = 1,
) -> list[dict]:
    """
    Возвращает N самых свежих и важных эпизодов пользователя.
    Не истёкшие автоматически (expires_at > today или NULL).

    Сортировка: importance DESC, created_at DESC.
    """
    conn = get_connection()
    today = datetime.date.today().isoformat()

    params = [user_id, today, today, min_importance]
    type_filter = ""
    if episode_type:
        type_filter = " AND episode_type = ?"
        params.append(episode_type)

    params.append(limit)

    rows = conn.execute(f"""
        SELECT * FROM episodic_memory
        WHERE user_id = ?
          AND (expires_at IS NULL OR expires_at > ?)
          AND created_at <= ?
          AND importance >= ?
          {type_filter}
        ORDER BY importance DESC, created_at DESC
        LIMIT ?
    """, params).fetchall()

    return [dict(r) for r in rows]


def get_episodes_by_tags(
    user_id: int,
    tags: list[str],
    limit: int = 5,
) -> list[dict]:
    """
    Поиск эпизодов по тегам (простой LIKE-поиск по JSON).
    Возвращает эпизоды содержащие хотя бы один из тегов.
    """
    if not tags:
        return []

    conn = get_connection()
    today = datetime.date.today().isoformat()

    # Строим условие: любой из тегов присутствует в JSON-строке
    tag_conditions = " OR ".join(["tags LIKE ?" for _ in tags])
    params = [user_id, today] + [f'%"{tag}"%' for tag in tags] + [limit]

    rows = conn.execute(f"""
        SELECT * FROM episodic_memory
        WHERE user_id = ?
          AND (expires_at IS NULL OR expires_at > ?)
          AND ({tag_conditions})
        ORDER BY importance DESC, created_at DESC
        LIMIT ?
    """, params).fetchall()

    return [dict(r) for r in rows]


def purge_expired_episodes(user_id: int = None) -> int:
    """
    Удаляет истёкшие эпизоды. Если user_id=None — глобальная очистка.
    Возвращает количество удалённых записей.
    """
    conn = get_connection()
    today = datetime.date.today().isoformat()

    if user_id:
        cursor = conn.execute("""
            DELETE FROM episodic_memory
            WHERE user_id = ? AND expires_at IS NOT NULL AND expires_at <= ?
        """, (user_id, today))
    else:
        cursor = conn.execute("""
            DELETE FROM episodic_memory
            WHERE expires_at IS NOT NULL AND expires_at <= ?
        """, (today,))

    conn.commit()
    deleted = cursor.rowcount
    if deleted:
        logger.info(f"[EPISODIC] purged {deleted} expired episodes")
    return deleted


# ───────────────────────────────────────────────────────────────────────────
# ФОРМАТИРОВАНИЕ ДЛЯ КОНТЕКСТА AI
# ───────────────────────────────────────────────────────────────────────────

def format_episodic_context(user_id: int, limit: int = 8) -> str:
    """
    Возвращает блок для системного промпта AI:
    краткий список ключевых эпизодов (самые важные / свежие).

    Используется в context_builder.py.
    """
    episodes = get_recent_episodes(user_id, limit=limit, min_importance=4)
    if not episodes:
        return ""

    lines = ["📖 Ключевые эпизоды (память):"]
    for ep in episodes:
        # Формат: [тип] дата: резюме
        ep_date = ep["created_at"][:10] if ep.get("created_at") else "?"
        type_labels = {
            "personal_record": "🏆 PR",
            "insight": "💡 Инсайт",
            "goal_update": "🎯 Цель",
            "conversation": "💬",
            "milestone": "🌟 Веха",
        }
        type_label = type_labels.get(ep["episode_type"], ep["episode_type"])
        # Sanitize-on-read against indirect prompt injection (см. C8 audit).
        # `summary` хранит user-attributable текст — оборачиваем в <user_text>.
        summary = ep["summary"] or ""
        if len(summary) > 300:
            summary = summary[:300] + "…"
        lines.append(f"  {type_label} [{ep_date}]: <user_text>{summary}</user_text>")

    return "\n".join(lines)
