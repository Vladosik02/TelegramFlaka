"""
scheduler/nutrition_analysis.py — Автоматический анализ паттернов питания.

Запускается ежедневно в 21:45 (после daily_summary, до streak_protection).

Что анализирует (за последние 7 дней):
  1. protein_deficit    — средний белок < 80% цели ≥3 дня подряд
  2. calorie_deficit    — средние калории < 75% цели ≥3 дня подряд
  3. calorie_surplus    — средние калории > 120% цели ≥4 дня (только предупреждение)
  4. dehydration        — средняя вода < 1500мл ≥3 дня
  5. junk_food_streak   — читмил 3+ дней подряд
  6. no_logging         — 0 записей питания за 4+ дней при активном боте
  7. low_protein_today  — сегодня белок < 70% цели (если данные уже есть)

Алгоритм:
  - Проверяет каждого активного пользователя
  - Использует cooldown: один тип инсайта не повторяется чаще 1 раза в 3 дня
  - Сохраняет инсайт в nutrition_insights (таблица)
  - Отправляет пользователю умное сообщение через бота
  - Использует Haiku для генерации текста сообщения (дёшево)
"""
import datetime
import logging

logger = logging.getLogger(__name__)

# ─── Cooldown: один тип инсайта не чаще N дней ────────────────────────────────
_INSIGHT_COOLDOWN_DAYS = {
    "protein_deficit":   3,
    "calorie_deficit":   3,
    "calorie_surplus":   5,
    "dehydration":       4,
    "junk_food_streak":  3,
    "no_logging":        4,
    "low_protein_today": 2,
}
_DEFAULT_COOLDOWN = 3


def _get_last_insight_date(conn, user_id: int, insight_type: str) -> datetime.date | None:
    """Дата последнего инсайта данного типа (resolved или нет)."""
    row = conn.execute("""
        SELECT detected_at FROM nutrition_insights
        WHERE user_id = ? AND insight_type = ?
        ORDER BY detected_at DESC LIMIT 1
    """, (user_id, insight_type)).fetchone()
    if not row:
        return None
    try:
        return datetime.date.fromisoformat(row["detected_at"][:10])
    except Exception:
        return None


def _is_on_cooldown(conn, user_id: int, insight_type: str) -> bool:
    """True если инсайт такого типа был недавно (в пределах cooldown)."""
    last = _get_last_insight_date(conn, user_id, insight_type)
    if last is None:
        return False
    cooldown = _INSIGHT_COOLDOWN_DAYS.get(insight_type, _DEFAULT_COOLDOWN)
    return (datetime.date.today() - last).days < cooldown


# ─── Анализ паттернов для одного пользователя ─────────────────────────────────

def analyze_user_nutrition(user_id: int, goal_cal: int, goal_prot: int,
                            goal_water_ml: int = 2000) -> list[dict]:
    """
    Анализирует паттерны питания за последние 7 дней.
    Возвращает список triggered инсайтов:
    [{"type": str, "description": str, "action": str, "severity": str}]
    """
    from db.connection import get_connection

    conn = get_connection()
    today = datetime.date.today()
    since = (today - datetime.timedelta(days=7)).isoformat()

    rows = conn.execute("""
        SELECT date, calories, protein_g, fat_g, carbs_g, water_ml, junk_food
        FROM nutrition_log
        WHERE user_id = ? AND date >= ?
        ORDER BY date DESC
    """, (user_id, since)).fetchall()

    log_by_date = {r["date"]: dict(r) for r in rows}
    log_days = len(log_by_date)
    triggered = []

    # ── 1. Нет логирования ────────────────────────────────────────────────────
    if log_days == 0:
        if not _is_on_cooldown(conn, user_id, "no_logging"):
            triggered.append({
                "type": "no_logging",
                "description": "0 записей питания за последние 7 дней",
                "action": "Начни записывать питание — это ключ к набору массы",
                "severity": "warning",
            })
        return triggered  # дальше анализировать нечего

    # ── 2. Белковый дефицит (3+ дней < 80% цели) ─────────────────────────────
    if goal_prot and not _is_on_cooldown(conn, user_id, "protein_deficit"):
        prot_deficit_days = sum(
            1 for d in log_by_date.values()
            if d.get("protein_g") and d["protein_g"] < goal_prot * 0.80
        )
        days_with_prot = sum(1 for d in log_by_date.values() if d.get("protein_g"))
        if days_with_prot >= 3 and prot_deficit_days >= 3:
            avg_prot = sum(
                d["protein_g"] for d in log_by_date.values() if d.get("protein_g")
            ) / days_with_prot
            gap = goal_prot - avg_prot
            triggered.append({
                "type": "protein_deficit",
                "description": (
                    f"Средний белок {avg_prot:.0f}г/день при цели {goal_prot}г "
                    f"— дефицит {gap:.0f}г ({prot_deficit_days} из {days_with_prot} дней)"
                ),
                "action": f"Добавь {gap:.0f}г белка — творог, яйца, курица или шейк",
                "severity": "warning" if avg_prot / goal_prot > 0.65 else "critical",
            })

    # ── 3. Калорийный дефицит (3+ дней < 75% цели) ───────────────────────────
    if goal_cal and not _is_on_cooldown(conn, user_id, "calorie_deficit"):
        cal_deficit_days = sum(
            1 for d in log_by_date.values()
            if d.get("calories") and d["calories"] < goal_cal * 0.75
        )
        days_with_cal = sum(1 for d in log_by_date.values() if d.get("calories"))
        if days_with_cal >= 3 and cal_deficit_days >= 3:
            avg_cal = sum(
                d["calories"] for d in log_by_date.values() if d.get("calories")
            ) / days_with_cal
            triggered.append({
                "type": "calorie_deficit",
                "description": (
                    f"Средняя калорийность {avg_cal:.0f} ккал при цели {goal_cal} ккал "
                    f"— дефицит {goal_cal - avg_cal:.0f} ккал ({cal_deficit_days} дней)"
                ),
                "action": "Набор массы невозможен в дефиците — добавь калорийный приём пищи",
                "severity": "critical",
            })

    # ── 4. Профицит (4+ дней > 120% цели) ────────────────────────────────────
    if goal_cal and not _is_on_cooldown(conn, user_id, "calorie_surplus"):
        surplus_days = sum(
            1 for d in log_by_date.values()
            if d.get("calories") and d["calories"] > goal_cal * 1.20
        )
        if surplus_days >= 4:
            avg_cal = sum(
                d["calories"] for d in log_by_date.values() if d.get("calories")
            ) / max(1, sum(1 for d in log_by_date.values() if d.get("calories")))
            triggered.append({
                "type": "calorie_surplus",
                "description": (
                    f"Калорийность {avg_cal:.0f} ккал — превышение цели на "
                    f"{avg_cal - goal_cal:.0f} ккал ({surplus_days} дней)"
                ),
                "action": "Следи за лишним жиром — чистый булк лучше грязного",
                "severity": "info",
            })

    # ── 5. Обезвоживание (3+ дней < 1500мл) ──────────────────────────────────
    if not _is_on_cooldown(conn, user_id, "dehydration"):
        days_with_water = sum(1 for d in log_by_date.values() if d.get("water_ml"))
        if days_with_water >= 3:
            dehydration_days = sum(
                1 for d in log_by_date.values()
                if d.get("water_ml") and d["water_ml"] < 1500
            )
            if dehydration_days >= 3:
                avg_water = sum(
                    d["water_ml"] for d in log_by_date.values() if d.get("water_ml")
                ) / days_with_water
                triggered.append({
                    "type": "dehydration",
                    "description": (
                        f"Среднее потребление воды {avg_water:.0f}мл/день "
                        f"— ниже нормы ({dehydration_days} из {days_with_water} дней)"
                    ),
                    "action": "Носи бутылку воды — дегидратация снижает силу на 10-15%",
                    "severity": "warning",
                })

    # ── 6. Читмил 3+ дней подряд ──────────────────────────────────────────────
    if not _is_on_cooldown(conn, user_id, "junk_food_streak"):
        sorted_dates = sorted(log_by_date.keys(), reverse=True)
        junk_streak = 0
        for d in sorted_dates:
            if log_by_date[d].get("junk_food"):
                junk_streak += 1
            else:
                break
        if junk_streak >= 3:
            triggered.append({
                "type": "junk_food_streak",
                "description": f"Читмил {junk_streak} дней подряд",
                "action": "Сбрось инерцию — один правильный приём пищи сейчас",
                "severity": "warning",
            })

    # ── 7. Сегодня низкий белок (если данные уже есть) ────────────────────────
    if goal_prot and not _is_on_cooldown(conn, user_id, "low_protein_today"):
        today_str = today.isoformat()
        today_data = log_by_date.get(today_str)
        if today_data and today_data.get("protein_g"):
            if today_data["protein_g"] < goal_prot * 0.70:
                remaining = goal_prot - today_data["protein_g"]
                triggered.append({
                    "type": "low_protein_today",
                    "description": (
                        f"Сегодня белок: {today_data['protein_g']:.0f}г / {goal_prot}г — "
                        f"нужно ещё {remaining:.0f}г"
                    ),
                    "action": "Добери белок сегодня до сна",
                    "severity": "info",
                })

    return triggered


# ─── Генерация текста сообщения через Haiku ───────────────────────────────────

def _build_insight_message(user_name: str, insights: list[dict]) -> str:
    """
    Формирует готовое Telegram-сообщение на основе инсайтов.
    Без вызова AI — простой шаблонный текст (fast + free).
    """
    if not insights:
        return ""

    # Сортируем по severity: critical > warning > info
    priority = {"critical": 0, "warning": 1, "info": 2}
    insights_sorted = sorted(insights, key=lambda x: priority.get(x["severity"], 3))
    top = insights_sorted[0]

    severity_emoji = {"critical": "🚨", "warning": "⚠️", "info": "💡"}
    emoji = severity_emoji.get(top["severity"], "📊")

    lines = [f"{emoji} *Питание — анализ паттернов*\n"]

    for ins in insights_sorted[:3]:  # максимум 3 в одном сообщении
        e = severity_emoji.get(ins["severity"], "•")
        lines.append(f"{e} {ins['description']}")
        lines.append(f"   → _{ins['action']}_\n")

    if len(insights) > 3:
        lines.append(f"_...и ещё {len(insights) - 3} наблюдения_\n")

    lines.append("Напиши что ел сегодня или спроси Алекса что добавить в рацион.")
    return "\n".join(lines)


# ─── Основная функция планировщика ────────────────────────────────────────────

async def run_nutrition_analysis(bot) -> None:
    """
    Проверяет всех активных пользователей, обнаруживает паттерны,
    сохраняет инсайты в БД и отправляет умные сообщения.
    Использует модель Haiku (дёшево — нет AI-генерации, только DB-анализ).
    """
    from db.queries.user import get_all_active_users
    from db.queries.nutrition import add_nutrition_insight
    from db.queries.memory import get_l2_brief
    from db.connection import get_connection

    logger.info("[NUTRITION-ANALYSIS] Starting daily nutrition pattern check")
    conn = get_connection()

    users = get_all_active_users()
    processed = sent = skipped = 0

    for u in users:
        try:
            uid     = u["id"]
            tg_id   = u["telegram_id"]
            name    = u.get("name") or "атлет"

            # Загружаем цели из L2
            l2 = get_l2_brief(uid) or {}
            goal_cal  = l2.get("daily_calories") or 0
            goal_prot = l2.get("protein_g")      or 0

            # Без целей анализ невозможен
            if not goal_cal and not goal_prot:
                skipped += 1
                continue

            # Анализируем паттерны
            insights = analyze_user_nutrition(
                user_id=uid,
                goal_cal=goal_cal,
                goal_prot=goal_prot,
            )

            processed += 1

            if not insights:
                continue

            # Сохраняем инсайты в БД
            for ins in insights:
                try:
                    add_nutrition_insight(
                        user_id=uid,
                        insight_type=ins["type"],
                        description=ins["description"],
                        action=ins.get("action"),
                    )
                except Exception as e:
                    logger.warning(f"[NUTRITION-ANALYSIS] Failed to save insight: {e}")

            # Только critical/warning -> отправляем сообщение
            actionable = [i for i in insights if i["severity"] in ("critical", "warning")]
            if not actionable:
                continue

            msg = _build_insight_message(name, actionable)
            if msg:
                try:
                    await bot.send_message(chat_id=tg_id, text=msg, parse_mode="Markdown")
                    sent += 1
                    logger.info(
                        f"[NUTRITION-ANALYSIS] Sent to user={tg_id} "
                        f"insights={[i['type'] for i in actionable]}"
                    )
                except Exception as e:
                    logger.warning(f"[NUTRITION-ANALYSIS] Send failed for {tg_id}: {e}")

        except Exception as e:
            logger.error(f"[NUTRITION-ANALYSIS] Error for user {u.get('id')}: {e}")

    logger.info(
        f"[NUTRITION-ANALYSIS] Done. users={len(users)} "
        f"processed={processed} sent={sent} skipped={skipped}"
    )
