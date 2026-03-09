"""
ai/context_builder.py — Собирает минимальный контекст для каждого типа запроса.
Никогда не загружает всю БД — только нужные поля.

4-слойная система памяти (V1 Smart Card + V2 TTL):
  L0  Surface Card   ~150 tok  ВСЕГДА
  L1  Deep Bio       ~150 tok  только при health-контексте
  L2  Nutrition      ~120 brief / ~200 deep  brief всегда, deep при food
  L3  Training       ~150 brief / ~250 deep  brief всегда, deep при training
  L4  Intelligence   ~200 tok  ВСЕГДА  (AI-дайджест недели)
"""
import logging
import datetime
import os
from db.queries.user import get_user
from db.queries.workouts import (
    get_workouts_range, get_metrics_range,
    get_today_workout, get_streak, get_weekly_stats
)
from db.queries.context import (
    get_today_checkins, get_recent_conversation,
    count_conversation_messages, clear_conversation, save_context_summary,
    get_last_message_time, get_all_conversation_messages,
    add_conversation_message,
)
from db.queries.stats import get_last_n_weeks
from db.queries.memory import (
    get_l0_surface, get_l1_deep_bio,
    get_l2_brief, get_l2_deep,
    get_l3_brief, get_l3_deep,
    get_l4_intelligence,
)
from config import get_trainer_mode, PROMPTS_DIR

logger = logging.getLogger(__name__)


def _load_prompt(filename: str) -> str:
    path = os.path.join(PROMPTS_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def get_system_prompt(mode: str) -> str:
    fname = "system_max.txt" if mode == "MAX" else "system_light.txt"
    return _load_prompt(fname)


def build_morning_context(telegram_id: int) -> dict:
    """23 поля для утреннего чек-ина."""
    user = get_user(telegram_id)
    if not user:
        return {}
    workouts = get_workouts_range(user["id"], days=2)
    metrics = get_metrics_range(user["id"], days=7)
    streak = get_streak(user["id"])
    mode = get_trainer_mode()

    last_workout = "не было" if not workouts else (
        f"{workouts[0]['type'] or 'тренировка'}, "
        f"интенсивность {workouts[0]['intensity']}/10"
        if workouts[0]['completed'] else "не завершена"
    )
    last_sleep = "неизвестен"
    avg_energy = "нет данных"
    if metrics:
        if metrics[0].get("sleep_hours"):
            last_sleep = f"{metrics[0]['sleep_hours']} ч"
        energies = [m["energy"] for m in metrics if m.get("energy")]
        if energies:
            avg_energy = f"{sum(energies)/len(energies):.1f}/5"

    prompt_template = _load_prompt("morning_checkin.txt")
    prompt = prompt_template.format(
        name=user.get("name") or "атлет",
        mode=mode,
        goal=user.get("goal") or "улучшить форму",
        fitness_level=user.get("fitness_level") or "beginner",
        streak=streak,
        last_workout=last_workout,
        last_sleep=last_sleep,
        avg_energy=avg_energy,
    )
    return {
        "system": get_system_prompt(mode),
        "prompt": prompt,
        "mode": mode,
        "user": user,
    }


def build_afternoon_context(telegram_id: int) -> dict:
    user = get_user(telegram_id)
    if not user:
        return {}
    today = datetime.date.today().isoformat()
    checkins = get_today_checkins(user["id"])
    mode = get_trainer_mode()
    morning = next((c for c in checkins if c["time_slot"] == "morning"), None)
    today_workout = get_today_workout(user["id"])

    morning_status = "не отвечал" if not morning else (
        "ответил утром" if morning["status"] == "done" else "пропустил"
    )
    workout_planned = "да" if mode == "MAX" else "опционально"

    prompt_template = _load_prompt("afternoon_checkin.txt")
    prompt = prompt_template.format(
        name=user.get("name") or "атлет",
        mode=mode,
        morning_status=morning_status,
        workout_planned=workout_planned,
        current_time=datetime.datetime.now().strftime("%H:%M"),
    )
    return {
        "system": get_system_prompt(mode),
        "prompt": prompt,
        "mode": mode,
        "user": user,
    }


def build_evening_context(telegram_id: int) -> dict:
    user = get_user(telegram_id)
    if not user:
        return {}
    today_workout = get_today_workout(user["id"])
    metrics_today = get_metrics_range(user["id"], days=1)
    weekly = get_weekly_stats(user["id"])
    streak = get_streak(user["id"])
    mode = get_trainer_mode()

    workout_summary = "не было"
    if today_workout:
        w = today_workout
        workout_summary = (
            f"{w['type'] or 'тренировка'} {w['duration_min'] or '?'} мин, "
            f"интенсивность {w['intensity'] or '?'}/10"
        )

    daily_metrics = "нет данных"
    if metrics_today:
        m = metrics_today[0]
        parts = []
        if m.get("energy"): parts.append(f"энергия {m['energy']}/5")
        if m.get("sleep_hours"): parts.append(f"сон {m['sleep_hours']}ч")
        if m.get("mood"): parts.append(f"настроение {m['mood']}/5")
        if parts: daily_metrics = ", ".join(parts)

    weekly_progress = (
        f"{weekly['workouts_done']}/{weekly['workouts_total']} тренировок, "
        f"ср. интенсивность {weekly['avg_intensity']}"
    )

    prompt_template = _load_prompt("evening_summary.txt")
    prompt = prompt_template.format(
        name=user.get("name") or "атлет",
        mode=mode,
        workout_summary=workout_summary,
        daily_metrics=daily_metrics,
        streak=streak,
        weekly_progress=weekly_progress,
    )
    return {
        "system": get_system_prompt(mode),
        "prompt": prompt,
        "mode": mode,
        "user": user,
    }


def build_weekly_report_context(telegram_id: int) -> dict:
    user = get_user(telegram_id)
    if not user:
        return {}
    weekly = get_weekly_stats(user["id"])
    prev_weeks = get_last_n_weeks(user["id"], n=2)
    streak = get_streak(user["id"])
    mode = get_trainer_mode()

    today = datetime.date.today()
    mon = today - datetime.timedelta(days=today.weekday())
    week_range = f"{mon.strftime('%d.%m')} – {(mon + datetime.timedelta(6)).strftime('%d.%m.%Y')}"

    prev_week = "нет данных"
    if len(prev_weeks) > 1:
        pw = prev_weeks[1]
        prev_week = (
            f"{pw['workouts_done']}/{pw['workouts_total']} тренировок, "
            f"энергия {pw['avg_energy'] or '?'}/5"
        )

    prompt_template = _load_prompt("weekly_report.txt")
    prompt = prompt_template.format(
        name=user.get("name") or "атлет",
        week_range=week_range,
        workouts_done=weekly["workouts_done"],
        workouts_total=weekly["workouts_total"],
        avg_intensity=weekly["avg_intensity"],
        total_minutes=weekly["total_minutes"],
        avg_sleep=weekly["avg_sleep"],
        avg_energy=weekly["avg_energy"],
        total_steps=weekly["total_steps"],
        streak=streak,
        prev_week=prev_week,
    )
    return {
        "system": get_system_prompt(mode),
        "prompt": prompt,
        "mode": mode,
        "user": user,
    }


def build_chat_context(telegram_id: int) -> dict:
    """
    Для свободного диалога — история + профиль.
    Устаревший метод: используй build_layered_context() для новой логики.
    """
    user = get_user(telegram_id)
    if not user:
        return {}
    mode = get_trainer_mode()
    history = get_recent_conversation(user["id"], limit=10)
    return {
        "system": get_system_prompt(mode),
        "history": history,
        "mode": mode,
        "user": user,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 4-СЛОЙНЫЙ КОНТЕКСТ (V1 Smart Card + V2 TTL)
# ═══════════════════════════════════════════════════════════════════════════

# ─── Классификатор сообщений ──────────────────────────────────────────────
_HEALTH_WORDS = (
    "боль", "болит", "травм", "ноет", "растяжен", "ушиб", "врач", "доктор",
    "добавк", "витамин", "протеин", "принима", "дозировк", "аллерг",
    "непереносим", "реакц", "побочн", "суставы", "мышца", "связк",
)
_FOOD_WORDS = (
    "поел", "съел", "поедал", "питание", "еду", "едой", "калор", "белок",
    "углевод", "жир", "завтрак", "обед", "ужин", "перекус", "голод",
    "диет", "рацион", "продукт", "готовлю", "приготов", "макро", "ккал",
    "г белка", "кето",
)
_TRAINING_WORDS = (
    "тренировк", "упражнен", "подход", "повтор", "вес", "жим", "приседан",
    "подтягива", "пробеж", "кардио", "силов", "качаться", "качал",
    "тренился", "трениров", "дедлайн", "становая", "выпады", "планк",
    "гантел", "штанг", "кроссфит", "спортзал", "зал", "пробежк",
)


def _classify_message(text: str) -> frozenset:
    """
    Возвращает frozenset тегов: {"health", "food", "training"}.
    Используется для выбора слоёв памяти.
    """
    t = text.lower()
    tags = set()
    if any(w in t for w in _HEALTH_WORDS):
        tags.add("health")
    if any(w in t for w in _FOOD_WORDS):
        tags.add("food")
    if any(w in t for w in _TRAINING_WORDS):
        tags.add("training")
    return frozenset(tags)


# ─── Сборщики текстовых блоков для каждого слоя ───────────────────────────

def _build_l0_card(user: dict, uid: int, streak: int) -> str:
    """L0 Surface Card (~150 tok). Всегда включается."""
    surface = get_l0_surface(uid)
    lines = [
        "## Карточка атлета (L0)",
        f"Имя: {user.get('name') or 'атлет'}",
        f"Цель: {user.get('goal') or 'улучшить форму'}",
        f"Уровень: {user.get('fitness_level', 'beginner')}",
        f"Стрик: {streak} дней",
    ]
    if surface.get("age"):
        lines.append(f"Возраст: {surface['age']} лет")
    if surface.get("height_cm"):
        lines.append(f"Рост: {surface['height_cm']} см")
    season_map = {
        "bulk": "набор массы", "cut": "сушка",
        "maintain": "поддержание", "peak": "пик формы",
    }
    lines.append(f"Сезон: {season_map.get(surface.get('season', 'maintain'), 'поддержание')}")
    if user.get("injuries"):
        try:
            import json
            inj = json.loads(user["injuries"])
            if inj:
                lines.append(f"Активные травмы: {', '.join(inj)}")
        except Exception:
            pass
    return "\n".join(lines)


def _build_l1_deep_bio(uid: int) -> str | None:
    """L1 Deep Bio (~150 tok). Только при health-контексте."""
    bio = get_l1_deep_bio(uid)
    if not any(bio.values()):
        return None
    lines = ["## Биомедицинская история (L1)"]
    if bio.get("food_intolerances"):
        lines.append(f"Непереносимости: {', '.join(bio['food_intolerances'])}")
    if bio.get("supplement_reactions"):
        sr = bio["supplement_reactions"]
        notes = [f"{k}: {v}" for k, v in sr.items()]
        lines.append(f"Добавки/реакции: {'; '.join(notes)}")
    if bio.get("personal_records"):
        pr = bio["personal_records"]
        records = [f"{k}={v}" for k, v in list(pr.items())[:5]]
        lines.append(f"Личные рекорды: {', '.join(records)}")
    return "\n".join(lines) if len(lines) > 1 else None


def _build_l2_nutrition(uid: int, deep: bool) -> str | None:
    """L2 Nutrition. Brief (~120 tok) всегда, deep (~200 tok) при food."""
    data = get_l2_deep(uid) if deep else get_l2_brief(uid)
    if not data:
        return None
    lines = ["## Питание (L2)"]
    if data.get("daily_calories"):
        lines.append(
            f"Цель КБЖУ: {data['daily_calories']} ккал / "
            f"Б{data.get('protein_g', '?')}г / "
            f"Ж{data.get('fat_g', '?')}г / "
            f"У{data.get('carbs_g', '?')}г"
        )
    if deep:
        if data.get("supplements"):
            lines.append(f"Добавки: {', '.join(data['supplements'])}")
        if data.get("restrictions"):
            lines.append(f"Ограничения: {', '.join(data['restrictions'])}")
        if data.get("last_meal_notes"):
            lines.append(f"Последние заметки: {data['last_meal_notes']}")
    return "\n".join(lines) if len(lines) > 1 else None


def _build_l3_training(uid: int, deep: bool) -> str | None:
    """L3 Training Intelligence. Brief всегда, deep при training."""
    data = get_l3_deep(uid) if deep else get_l3_brief(uid)
    if not data:
        return None
    lines = ["## Тренировочный профиль (L3)"]
    if data.get("preferred_days"):
        lines.append(f"Тренировочные дни: {', '.join(data['preferred_days'])}")
    if data.get("avg_session_min"):
        lines.append(f"Средняя длительность: {data['avg_session_min']} мин")
    if data.get("current_program"):
        lines.append(f"Программа: {data['current_program']}")
    if deep:
        if data.get("notable_exercises"):
            weak = [ex for ex, d in data["notable_exercises"].items()
                    if isinstance(d, dict) and d.get("score", 5) < 4.0]
            strong = [ex for ex, d in data["notable_exercises"].items()
                      if isinstance(d, dict) and d.get("score", 5) > 7.0]
            if weak:
                lines.append(f"Слабые упражнения (заменить): {', '.join(weak)}")
            if strong:
                lines.append(f"Сильные паттерны: {', '.join(strong)}")
        if data.get("avoided_exercises"):
            lines.append(f"Исключить: {', '.join(data['avoided_exercises'])}")
        if data.get("training_notes"):
            lines.append(f"Заметки: {data['training_notes']}")
    return "\n".join(lines) if len(lines) > 1 else None


def _build_l4_intelligence(uid: int) -> str | None:
    """L4 AI Intelligence (~200 tok). Всегда включается."""
    intel = get_l4_intelligence(uid)
    if not intel:
        return None
    has_data = any([
        intel.get("weekly_digest"),
        intel.get("ai_observations"),
        intel.get("trend_summary"),
    ])
    if not has_data:
        return None
    lines = ["## AI-дайджест (L4)"]
    if intel.get("weekly_digest"):
        lines.append(f"Неделя: {intel['weekly_digest']}")
    if intel.get("ai_observations"):
        obs = intel["ai_observations"]
        if obs:
            lines.append(f"Наблюдения: {'; '.join(obs[-3:])}")  # только последние 3
    if intel.get("trend_summary"):
        lines.append(f"Тренд: {intel['trend_summary']}")
    if intel.get("motivation_level") and intel["motivation_level"] != "normal":
        level_map = {"low": "низкая ⚠️", "high": "высокая 🔥"}
        lines.append(f"Мотивация: {level_map.get(intel['motivation_level'], '')}")
    return "\n".join(lines) if len(lines) > 1 else None


# ─── Главная функция ──────────────────────────────────────────────────────

def build_layered_context(telegram_id: int, user_text: str = "") -> dict:
    """
    4-слойный контекст для свободного диалога.
    Классифицирует сообщение и загружает только нужные слои памяти.

    Бюджет токенов:
      L0 всегда         ~150
      L1 при health     ~150
      L2 brief всегда   ~120  /  deep при food   ~200
      L3 brief всегда   ~150  /  deep при train  ~250
      L4 всегда         ~200
      ──────────────────────────────
      Типовой запрос    ~620 (L0+L2b+L3b+L4)
      Максимум          ~950 (все слои deep)
      Плюс история      ~600–900
      Итого max         ~1870–2200 tok  ✅ < 3000
    """
    user = get_user(telegram_id)
    if not user:
        return {}

    mode = get_trainer_mode()
    uid = user["id"]
    tags = _classify_message(user_text)
    streak = get_streak(uid)

    # ── Собираем блоки памяти ────────────────────────────────────────────
    memory_blocks: list[str] = []

    # L0: всегда
    l0 = _build_l0_card(user, uid, streak)
    if l0:
        memory_blocks.append(l0)

    # L1: только при health
    if "health" in tags:
        l1 = _build_l1_deep_bio(uid)
        if l1:
            memory_blocks.append(l1)

    # L2: brief всегда, deep при food
    l2 = _build_l2_nutrition(uid, deep="food" in tags)
    if l2:
        memory_blocks.append(l2)

    # L3: brief всегда, deep при training
    l3 = _build_l3_training(uid, deep="training" in tags)
    if l3:
        memory_blocks.append(l3)

    # L4: всегда
    l4 = _build_l4_intelligence(uid)
    if l4:
        memory_blocks.append(l4)

    # ── Компонуем system prompt ──────────────────────────────────────────
    base_system = get_system_prompt(mode)
    if memory_blocks:
        memory_section = "\n\n".join(memory_blocks)
        full_system = (
            f"{base_system}\n\n"
            f"{'─' * 50}\n"
            f"ПАМЯТЬ О ПОЛЬЗОВАТЕЛЕ (используй как фундамент):\n"
            f"{'─' * 50}\n"
            f"{memory_section}"
        )
    else:
        full_system = base_system

    history = get_recent_conversation(uid, limit=10)

    logger.debug(
        f"[LAYERS] user={telegram_id} tags={set(tags)} "
        f"blocks={len(memory_blocks)} history={len(history)}"
    )

    return {
        "system":  full_system,
        "history": history,
        "mode":    mode,
        "user":    user,
        "tags":    set(tags),   # для отладки
    }


# ── Авто-суммаризация контекста (n3d1117 approach + token budget) ─────────────
#
# Два независимых триггера:
#   1. INACTIVITY  — если молчание > 180 мин → полный сброс (новая сессия)
#   2. TOKEN BUDGET — если накоплено > MAX_CONTEXT_TOKENS*(1-TOLERANCE) токенов
#                     → сжатие через AI, хвост сохраняется
#
# TOLERANCE = 0.01 означает: сжимаем когда заполнено 99% бюджета

# ─── Параметры ────────────────────────────────────────────────────────────────
MAX_CONTEXT_TOKENS  = 3500    # максимальный токен-бюджет для истории
TOLERANCE           = 0.01    # сжатие при достижении (1 - 0.01) = 99% бюджета
COMPRESS_THRESHOLD  = int(MAX_CONTEXT_TOKENS * (1.0 - TOLERANCE))  # 3465
INACTIVITY_MINUTES  = 180     # сброс после N минут молчания (как у n3d1117)
TAIL_KEEP_TOKENS    = 600     # сколько токенов хвоста сохранить после сжатия
# ─────────────────────────────────────────────────────────────────────────────

SUMMARY_SYSTEM = (
    "Ты — ассистент, сжимающий переписку тренера с атлетом. "
    "Отвечай ТОЛЬКО готовым резюме — без вступлений, без заголовков."
)
SUMMARY_PROMPT_TPL = """\
Сожми переписку в 5–7 предложений.
Обязательно сохрани:
- цель и уровень подготовки атлета
- последние тренировки: тип, длительность, интенсивность
- ключевые метрики: вес, сон, энергия, вода, шаги (с числами и датами)
- эмоциональный тон и мотивацию
- незакрытые вопросы или договорённости

Переписка:
{history}"""

CHARS_PER_TOKEN = 3.5   # эмпирика для смешанного рус/англ текста


def _estimate_tokens(messages: list[dict]) -> int:
    """Приблизительный подсчёт токенов по символам."""
    total = sum(len(m.get("content", "")) for m in messages)
    return max(1, int(total / CHARS_PER_TOKEN))


def _split_by_token_budget(messages: list[dict],
                            tail_budget: int) -> tuple[list[dict], list[dict]]:
    """
    Делит список сообщений на (сжать, оставить).
    Хвост отбирается с конца жадно — пока не превысим tail_budget токенов.
    """
    tail: list[dict] = []
    used = 0
    for msg in reversed(messages):
        cost = int(len(msg.get("content", "")) / CHARS_PER_TOKEN)
        if used + cost > tail_budget:
            break
        tail.insert(0, msg)
        used += cost
    head = messages[:len(messages) - len(tail)]
    return head, tail


async def maybe_compress_context(telegram_id: int) -> str:
    """
    Проверяет два условия и при необходимости очищает / сжимает контекст.

    Возвращает:
      'reset'    — контекст очищен по таймауту неактивности
      'compress' — контекст сжат через AI (превышен token budget)
      'ok'       — ничего не делалось
    """
    from ai.client import get_async_client
    from config import MODEL

    user = get_user(telegram_id)
    if not user:
        return "ok"

    uid = user["id"]
    all_msgs = get_all_conversation_messages(uid)
    if not all_msgs:
        return "ok"

    # ── 1. Inactivity reset (n3d1117: 180 min silence → new session) ──────────
    last_time = get_last_message_time(uid)
    if last_time is not None:
        silence = (datetime.datetime.now() - last_time).total_seconds() / 60
        if silence > INACTIVITY_MINUTES:
            clear_conversation(uid)
            logger.info(
                f"[CTX] user={telegram_id} inactivity reset "
                f"after {silence:.0f} min silence"
            )
            return "reset"

    # ── 2. Token budget check (tolerance = 0.01) ──────────────────────────────
    total_tokens = _estimate_tokens(all_msgs)
    if total_tokens < COMPRESS_THRESHOLD:
        return "ok"   # ещё есть место

    logger.info(
        f"[CTX] user={telegram_id} token budget hit: "
        f"{total_tokens}/{MAX_CONTEXT_TOKENS} "
        f"(threshold={COMPRESS_THRESHOLD}, tol={TOLERANCE})"
    )

    # ── Разбиваем: head → сжимаем, tail → сохраняем ───────────────────────────
    head, tail = _split_by_token_budget(all_msgs, tail_budget=TAIL_KEEP_TOKENS)

    if not head:
        # Всё сообщение — хвост, нечего сжимать
        return "ok"

    history_text = "\n".join(
        f"[{m['role'].upper()}]: {m['content']}" for m in head
    )
    prompt = SUMMARY_PROMPT_TPL.format(history=history_text)

    try:
        async_client = get_async_client()
        response = await async_client.messages.create(
            model=MODEL,
            max_tokens=700,
            system=SUMMARY_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        summary = response.content[0].text.strip()
    except Exception as e:
        logger.error(f"[CTX] compression failed for {telegram_id}: {e}")
        return "ok"   # не сжали — не страшно, продолжаем

    # Перезаписываем контекст: [summary] + tail
    clear_conversation(uid)
    save_context_summary(uid, summary)
    for msg in tail:
        add_conversation_message(uid, msg["role"], msg["content"])

    compressed_tokens = _estimate_tokens(tail) + int(len(summary) / CHARS_PER_TOKEN)
    logger.info(
        f"[CTX] user={telegram_id} compressed: "
        f"{total_tokens} → ~{compressed_tokens} tokens "
        f"({len(head)} msgs → summary + {len(tail)} tail)"
    )
    return "compress"
