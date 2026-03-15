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
from db.queries.fitness_metrics import get_fitness_score, get_fitness_level
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
        if m.get("energy"):      parts.append(f"энергия {m['energy']}/5")
        if m.get("sleep_hours"): parts.append(f"сон {m['sleep_hours']}ч")
        if m.get("mood"):        parts.append(f"настроение {m['mood']}/5")
        if m.get("water_liters"): parts.append(f"вода {m['water_liters']}л")
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
_ANALYTICS_WORDS = (
    "прогресс", "динамик", "за месяц", "за год", "результат", "статистик",
    "аналитик", "сравн", "тренд", "итог", "достижен", "рекорд всех времён",
    "как я иду", "что изменилось", "чего добился", "сводк",
)

_PLAN_WORDS = (
    "план", "планир", "расписан", "schedule", "тренировк на неде",
    "на следующей неде", "на этой неде", "скорректируй план",
    "измени план", "подправь план", "покажи план", "какой план",
    "что тренир", "что делать сегодня", "что делать завтра",
)

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
    if any(w in t for w in _ANALYTICS_WORDS):
        tags.add("analytics")
    if any(w in t for w in _PLAN_WORDS):
        tags.add("plan")
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
    # fitness_score (Фаза 8.2) — загружается в L0 всегда (~8 tok)
    fs = get_fitness_score(uid)
    if fs:
        level = get_fitness_level(fs["score"])
        lines.append(
            f"Fitness Score: {fs['score']:.0f}/100 — {level} "
            f"(тест {fs['tested_at']})"
        )

    # ── Текущий вес + последние метрики из metrics (Agent Fix) ─────────────
    try:
        recent_metrics = get_metrics_range(uid, days=30)
        if recent_metrics:
            # Последний вес
            for m in recent_metrics:
                if m.get("weight_kg"):
                    lines.append(f"Текущий вес: {m['weight_kg']} кг (на {m['date']})")
                    break
            # Последние сон/энергия/настроение (самая свежая запись)
            latest = recent_metrics[0]
            parts = []
            if latest.get("sleep_hours"):
                parts.append(f"сон {latest['sleep_hours']}ч")
            if latest.get("energy"):
                parts.append(f"энергия {latest['energy']}/5")
            if latest.get("mood"):
                parts.append(f"настроение {latest['mood']}/5")
            if parts:
                lines.append(f"Последние метрики ({latest['date']}): {', '.join(parts)}")
    except Exception:
        pass

    # ── Место тренировок (Agent Fix) ──────────────────────────────────────
    location_map = {
        "home": "дома 🏠", "gym": "в зале 🏋️",
        "outdoor": "на улице 🌳", "flexible": "гибко 🔄",
    }
    loc = user.get("training_location", "flexible")
    lines.append(f"Место тренировок: {location_map.get(loc, loc)}")

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
    lines = ["## Питание (L2)"]
    if data and data.get("daily_calories"):
        lines.append(
            f"Цель КБЖУ: {data['daily_calories']} ккал / "
            f"Б{data.get('protein_g', '?')}г / "
            f"Ж{data.get('fat_g', '?')}г / "
            f"У{data.get('carbs_g', '?')}г"
        )
    if deep and data:
        if data.get("supplements"):
            lines.append(f"Добавки: {', '.join(data['supplements'])}")
        if data.get("restrictions"):
            lines.append(f"Ограничения: {', '.join(data['restrictions'])}")
        if data.get("last_meal_notes"):
            lines.append(f"Последние заметки о питании: {data['last_meal_notes']}")
    if deep:
        from db.queries.nutrition import get_nutrition_log, get_active_insights
        recent_log = get_nutrition_log(uid, days=3)
        if recent_log:
            log_lines = []
            for entry in recent_log[:3]:
                parts = []
                if entry.get("calories"):   parts.append(f"{entry['calories']} ккал")
                if entry.get("protein_g"):  parts.append(f"Б{entry['protein_g']}г")
                if entry.get("water_ml"):   parts.append(f"вода {entry['water_ml']}мл")
                if entry.get("junk_food"):  parts.append("🍔 читмил")
                if parts:
                    log_lines.append(f"  {entry['date']}: {', '.join(parts)}")
            if log_lines:
                lines.append("Журнал за 3 дня:\n" + "\n".join(log_lines))
        insights = get_active_insights(uid, limit=2)
        if insights:
            insight_lines = [f"  ⚠️ {i['description']}" for i in insights]
            lines.append("Рекомендации AI:\n" + "\n".join(insight_lines))
    return "\n".join(lines) if len(lines) > 1 else None


def _build_l3_training(uid: int, deep: bool) -> str | None:
    """L3 Training Intelligence. Brief всегда, deep при training."""
    data = get_l3_deep(uid) if deep else get_l3_brief(uid)
    if not data:
        return None
    _time_labels = {"morning": "утром", "evening": "вечером", "flexible": "гибко"}
    lines = ["## Тренировочный профиль (L3)"]
    if data.get("preferred_time") and data["preferred_time"] != "flexible":
        lines.append(f"Предпочтительное время: {_time_labels.get(data['preferred_time'], data['preferred_time'])}")
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
        # ── Личные рекорды из exercise_results ──────────────────────────────
        from db.queries.exercises import get_recent_records, get_personal_records
        recent_prs = get_recent_records(uid, days=30)
        if recent_prs:
            pr_lines = []
            for pr in recent_prs[:3]:
                parts = [pr["exercise_name"]]
                if pr.get("record_type") == "weight":
                    parts.append(f"{pr['record_value']} кг")
                elif pr.get("record_type") == "reps":
                    parts.append(f"{pr['record_value']} повт")
                elif pr.get("record_type") == "time":
                    parts.append(f"{int(pr['record_value'])} сек")
                if pr.get("improvement_pct"):
                    parts.append(f"+{pr['improvement_pct']:.0f}%")
                pr_lines.append("  🏆 " + " — ".join(parts))
            lines.append("Рекорды (30 дней):\n" + "\n".join(pr_lines))
        all_prs = get_personal_records(uid, limit=5)
        if all_prs:
            pr_all_lines = []
            for pr in all_prs:
                val = pr["record_value"]
                rtype = pr.get("record_type", "")
                suffix = (" кг" if rtype == "weight"
                          else " повт" if rtype == "reps"
                          else " сек")
                pr_all_lines.append(f"  {pr['exercise_name']}: {val}{suffix}")
            lines.append("Личные рекорды (all-time):\n" + "\n".join(pr_all_lines))
    return "\n".join(lines) if len(lines) > 1 else None


def _build_daily_chronicle(uid: int, days: int = 5) -> str | None:
    """
    Хроника последних N дней (~150 tok).
    Включается всегда — даёт AI «память» о недавних событиях.
    Строит компактную таблицу: дата | тренировка | энергия | ключевое наблюдение.
    """
    from db.queries.daily_summary import get_daily_summaries
    summaries = get_daily_summaries(uid, days=days)
    if not summaries:
        return None
    lines = [f"## Хроника (последние {min(days, len(summaries))} дней)"]
    for s in summaries:
        date_short = s["date"][5:]  # MM-DD
        icons = []
        if s.get("workout_done"):  icons.append("💪")
        if s.get("calories_met"): icons.append("🥗")
        energy = f"⚡{s['energy_score']}/5" if s.get("energy_score") else ""
        mood   = f"😊{s['mood_score']}/5"  if s.get("mood_score")   else ""
        stats  = " ".join(filter(None, ["".join(icons), energy, mood]))
        line = f"{date_short}: {s['summary_text'][:100]}"
        if stats:
            line += f" [{stats}]"
        if s.get("key_insight"):
            line += f"\n  → {s['key_insight'][:80]}"
        lines.append(line)
    return "\n".join(lines)


def _build_active_plan(uid: int) -> str | None:
    """
    Активный план тренировок (~150 tok).
    Загружается ТОЛЬКО при "plan" теге — экономия токенов.
    Даёт AI полную картину текущего недельного расписания для корректировок.
    """
    import json as _json
    from db.queries.training_plan import get_active_plan
    import datetime as _dt

    plan = get_active_plan(uid)
    if not plan:
        return None

    try:
        days_list = _json.loads(plan["plan_json"])
    except Exception:
        return None

    week_start = plan.get("week_start", "")
    plan_id = plan.get("plan_id", "")
    workouts_done = plan.get("workouts_completed", 0)
    workouts_total = plan.get("workouts_planned", 0)

    type_icons = {
        "strength": "💪", "cardio": "🏃", "hiit": "⚡",
        "mobility": "🧘", "rest": "😴", "recovery": "🌿",
    }

    lines = [
        f"## Текущий план недели (L3-plan)",
        f"plan_id: {plan_id}  |  неделя: {week_start}",
        f"Прогресс: {workouts_done}/{workouts_total} тренировок",
    ]

    for day in days_list:
        dtype = day.get("type", "rest")
        icon = type_icons.get(dtype, "📅")
        date_str = day.get("date", "")
        weekday = day.get("weekday", "")
        label = day.get("label", dtype)
        completed = day.get("completed", False)
        mark = "✅" if completed else "⬜"

        try:
            date_fmt = _dt.date.fromisoformat(date_str).strftime("%d.%m")
        except Exception:
            date_fmt = date_str

        line = f"{mark} {weekday} {date_fmt}: {icon} {label}"

        exercises = day.get("exercises") or []
        if exercises:
            ex_parts = []
            for ex in exercises[:3]:  # первые 3 упражнения для краткости
                name = ex.get("name", "")
                sets = ex.get("sets")
                reps = ex.get("reps")
                weight = ex.get("weight_kg_target")
                detail = name
                if sets and reps:
                    detail += f" {sets}×{reps}"
                if weight:
                    detail += f" @{weight}кг"
                ex_parts.append(detail)
            if len(exercises) > 3:
                ex_parts.append(f"... ещё {len(exercises)-3}")
            line += f" | {', '.join(ex_parts)}"

        ai_note = day.get("ai_note", "")
        if ai_note:
            line += f"\n  → {ai_note[:80]}"

        lines.append(line)

    if plan.get("ai_rationale"):
        lines.append(f"Обоснование плана: {plan['ai_rationale'][:150]}")

    return "\n".join(lines) if len(lines) > 3 else None


def _build_monthly_chronicle(uid: int, months: int = 3) -> str | None:
    """
    Хроника последних N месяцев (~100 tok).
    Грузится ТОЛЬКО при analytics-контексте — экономия токенов.
    Даёт AI долгосрочную «память»: что было сделано за последние кварталы.
    """
    from db.queries.monthly_summary import get_monthly_summaries
    summaries = get_monthly_summaries(uid, months=months)
    if not summaries:
        return None
    lines = [f"## Хроника ({min(months, len(summaries))} мес.)"]
    for s in summaries:
        month_short = s["month"]  # YYYY-MM
        parts = [month_short]
        if s.get("workouts_done") is not None:
            parts.append(f"{s['workouts_done']} тр.")
        if s.get("avg_sleep"):
            parts.append(f"сон {s['avg_sleep']}ч")
        if s.get("avg_energy"):
            parts.append(f"⚡{s['avg_energy']}/5")
        if s.get("best_pr_text"):
            parts.append(f"🏆{s['best_pr_text']}")
        line = " | ".join(parts)
        if s.get("summary_text"):
            line += f"\n  {s['summary_text'][:120]}"
        if s.get("key_insight"):
            line += f"\n  → {s['key_insight'][:80]}"
        lines.append(line)
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

    # Daily chronicle: всегда (если есть накопленные резюме)
    chronicle = _build_daily_chronicle(uid, days=5)
    if chronicle:
        memory_blocks.append(chronicle)

    # Monthly chronicle: только при analytics-контексте (~100 tok)
    if "analytics" in tags:
        monthly = _build_monthly_chronicle(uid, months=3)
        if monthly:
            memory_blocks.append(monthly)

    # Active training plan: только при plan-контексте (~150 tok)
    if "plan" in tags:
        active_plan = _build_active_plan(uid)
        if active_plan:
            memory_blocks.append(active_plan)

    # Episodic memory (Фаза 10.5): важные эпизоды (~80-150 tok)
    try:
        from db.queries.episodic import format_episodic_context
        episodic = format_episodic_context(uid, limit=8)
        if episodic:
            memory_blocks.append(episodic)
    except Exception:
        pass  # эпизодическая память — некритична, не блокируем основной поток

    # XP/уровень (Фаза 10.4): для персонализации мотивации (~30 tok)
    try:
        from db.queries.gamification import get_user_level_info
        xp_info = get_user_level_info(uid)
        if xp_info and xp_info["total_xp"] > 0:
            xp_line = (
                f"## Прогресс атлета (XP)\n"
                f"Уровень {xp_info['current_level']} — {xp_info['level_name']} "
                f"| {xp_info['total_xp']} XP"
            )
            if xp_info.get("streak_days", 0) > 1:
                xp_line += f" | Стрик: {xp_info['streak_days']} дн. 🔥"
            if xp_info.get("xp_to_next_level", 0) > 0:
                xp_line += f" | До следующего уровня: {xp_info['xp_to_next_level']} XP"
            memory_blocks.append(xp_line)
    except Exception:
        pass

    # Recovery Score (Фаза 12.3): готовность к тренировке (~30 tok)
    try:
        from db.queries.recovery import format_recovery_block
        recovery_block = format_recovery_block(uid)
        if recovery_block:
            memory_blocks.append(f"## Состояние восстановления\n{recovery_block}")
    except Exception:
        pass

    # Периодизация (Фаза 12.2): текущая фаза мезоцикла (~40 tok)
    try:
        from db.queries.periodization import format_period_block
        period_block = format_period_block(uid)
        if period_block:
            memory_blocks.append(period_block)
    except Exception:
        pass

    # ── Контекстные подсказки действий (Фаза 13.7) ──────────────────────────
    # Усиливаем инструкции системного промпта конкретными хинтами для текущего сообщения
    action_hints: list[str] = []
    if "food" in tags:
        action_hints.append(
            "🍽 Сообщение о еде → НЕМЕДЛЕННО вызови save_nutrition "
            "(оцени КБЖУ сам если не указаны, не спрашивай)."
        )
    if "training" in tags:
        action_hints.append(
            "💪 Сообщение о тренировке → НЕМЕДЛЕННО вызови save_workout + "
            "save_exercise_result (по одному на упражнение) + award_xp(100, \"workout\") + "
            "save_episode(episode_type=\"training\", ...)."
        )
    if "health" in tags and "training" not in tags:
        action_hints.append(
            "⚠️ Упоминание самочувствия/здоровья → прочти L1 Deep Bio, "
            "если нужно обнови athlete_card (травмы/ограничения)."
        )
    if "analytics" in tags:
        action_hints.append(
            "📊 Запрос аналитики → вызови get_weekly_stats и/или get_personal_records "
            "для получения свежих данных из БД."
        )
    if "plan" in tags:
        action_hints.append(
            "📋 Запрос плана → вызови get_current_plan для получения актуального плана."
        )

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

    if action_hints:
        hints_block = (
            f"\n\n{'─' * 50}\n"
            f"⚡ ДЕЙСТВИЯ ДЛЯ ЭТОГО СООБЩЕНИЯ:\n"
            + "\n".join(f"• {h}" for h in action_hints)
        )
        full_system += hints_block

    history = get_recent_conversation(uid, limit=10)

    logger.debug(
        f"[LAYERS] user={telegram_id} tags={set(tags)} "
        f"blocks={len(memory_blocks)} history={len(history)} "
        f"plan={'yes' if 'plan' in tags else 'no'}"
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
