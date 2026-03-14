"""
analytics/charts.py — Генерация графиков прогресса.

Фаза 12.1: matplotlib в headless-режиме → PNG → io.BytesIO → Telegram photo.

Доступные графики:
  weight      — динамика веса + скользящее среднее 7 дней
  strength    — прогресс личных рекордов по упражнениям
  intensity   — столбчатая диаграмма интенсивности по неделям
  sleep       — сон и энергия — двойной график
  fitness     — история Fitness Score по тестам
  xp          — рост XP и уровня по неделям
"""
import io
import datetime
import logging

logger = logging.getLogger(__name__)

# Инициализируем matplotlib в headless-режиме (без дисплея, для Docker/VPS)
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.ticker import MaxNLocator
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    logger.warning("[CHARTS] matplotlib не установлен — графики недоступны")


# ─── Тёмная тема ─────────────────────────────────────────────────────────────
DARK_BG      = "#1a1a2e"
DARK_AX      = "#16213e"
ACCENT_BLUE  = "#4fc3f7"
ACCENT_GREEN = "#66bb6a"
ACCENT_ORANGE= "#ffa726"
ACCENT_RED   = "#ef5350"
TEXT_COLOR   = "#e0e0e0"
GRID_COLOR   = "#2a2a4a"


def _setup_style(fig, ax, title: str):
    """Применяет единый тёмный стиль ко всем графикам."""
    fig.patch.set_facecolor(DARK_BG)
    ax.set_facecolor(DARK_AX)
    ax.set_title(title, color=TEXT_COLOR, fontsize=13, fontweight="bold", pad=12)
    ax.tick_params(colors=TEXT_COLOR, labelsize=9)
    ax.spines["bottom"].set_color(GRID_COLOR)
    ax.spines["left"].set_color(GRID_COLOR)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True, color=GRID_COLOR, linewidth=0.5, alpha=0.7)
    ax.xaxis.label.set_color(TEXT_COLOR)
    ax.yaxis.label.set_color(TEXT_COLOR)


def _fig_to_bytes(fig) -> io.BytesIO:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close(fig)
    return buf


def _moving_avg(values: list, window: int = 7) -> list:
    """Скользящее среднее."""
    result = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        chunk = [v for v in values[start:i+1] if v is not None]
        result.append(round(sum(chunk) / len(chunk), 2) if chunk else None)
    return result


# ─── График 1: вес ───────────────────────────────────────────────────────────

def chart_weight(user_id: int, days: int = 60) -> io.BytesIO | None:
    """Динамика веса + скользящее среднее 7 дней."""
    if not HAS_MATPLOTLIB:
        return None

    from db.connection import get_connection
    conn = get_connection()
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()

    rows = conn.execute("""
        SELECT date, weight_kg FROM metrics
        WHERE user_id = ? AND date >= ? AND weight_kg IS NOT NULL
        ORDER BY date ASC
    """, (user_id, since)).fetchall()

    if len(rows) < 2:
        return None

    dates  = [datetime.date.fromisoformat(r["date"]) for r in rows]
    values = [float(r["weight_kg"]) for r in rows]
    ma7    = _moving_avg(values, 7)

    fig, ax = plt.subplots(figsize=(8, 4))
    _setup_style(fig, ax, f"⚖️ Динамика веса — {days} дней")

    ax.scatter(dates, values, color=ACCENT_BLUE, s=30, zorder=3, alpha=0.7, label="Вес")
    ax.plot(dates, values, color=ACCENT_BLUE, linewidth=1, alpha=0.4)

    ma_dates  = [d for d, v in zip(dates, ma7) if v is not None]
    ma_values = [v for v in ma7 if v is not None]
    if len(ma_dates) > 1:
        ax.plot(ma_dates, ma_values, color=ACCENT_ORANGE, linewidth=2,
                label="Среднее 7д", zorder=4)

    ax.set_ylabel("кг", color=TEXT_COLOR)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
    plt.xticks(rotation=30)
    ax.legend(facecolor=DARK_AX, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=9)

    # Аннотация: первое и последнее значение
    if values:
        delta = values[-1] - values[0]
        sign = "+" if delta > 0 else ""
        ax.annotate(
            f"{sign}{delta:.1f} кг за период",
            xy=(dates[-1], values[-1]),
            xytext=(-60, 12),
            textcoords="offset points",
            color=ACCENT_GREEN if delta < 0 else ACCENT_ORANGE,
            fontsize=9, fontweight="bold",
        )

    fig.tight_layout()
    return _fig_to_bytes(fig)


# ─── График 2: сила (личные рекорды) ─────────────────────────────────────────

def chart_strength(user_id: int, exercise: str | None = None) -> io.BytesIO | None:
    """Прогресс личных рекордов. Если exercise=None — топ-3 упражнения."""
    if not HAS_MATPLOTLIB:
        return None

    from db.connection import get_connection
    conn = get_connection()

    if exercise:
        rows = conn.execute("""
            SELECT set_at, record_value, record_type, exercise_name
            FROM personal_records
            WHERE user_id = ? AND exercise_name LIKE ?
            ORDER BY set_at ASC
        """, (user_id, f"%{exercise}%")).fetchall()
        exercises = {exercise: rows} if rows else {}
    else:
        # Топ-3 упражнения по количеству рекордов
        top = conn.execute("""
            SELECT exercise_name, COUNT(*) cnt
            FROM personal_records
            WHERE user_id = ?
            GROUP BY exercise_name
            ORDER BY cnt DESC
            LIMIT 3
        """, (user_id,)).fetchall()

        exercises = {}
        for t in top:
            ex_rows = conn.execute("""
                SELECT set_at, record_value, record_type
                FROM personal_records
                WHERE user_id = ? AND exercise_name = ?
                ORDER BY set_at ASC
            """, (user_id, t["exercise_name"])).fetchall()
            if ex_rows:
                exercises[t["exercise_name"]] = ex_rows

    if not exercises:
        return None

    colors = [ACCENT_BLUE, ACCENT_GREEN, ACCENT_ORANGE]
    fig, ax = plt.subplots(figsize=(8, 4))
    _setup_style(fig, ax, "💪 Прогресс личных рекордов")

    for i, (ex_name, ex_rows) in enumerate(exercises.items()):
        dates  = [datetime.date.fromisoformat(r["set_at"][:10]) for r in ex_rows]
        values = [float(r["record_value"]) for r in ex_rows]
        unit   = {"weight": "кг", "reps": "пов", "time": "сек"}.get(ex_rows[0]["record_type"], "")
        color  = colors[i % len(colors)]
        ax.plot(dates, values, "o-", color=color, linewidth=2, markersize=6,
                label=f"{ex_name} ({unit})", zorder=3)
        if values:
            ax.annotate(f"{values[-1]}{unit}", xy=(dates[-1], values[-1]),
                        xytext=(5, 5), textcoords="offset points",
                        color=color, fontsize=8, fontweight="bold")

    ax.set_ylabel("Результат", color=TEXT_COLOR)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    plt.xticks(rotation=30)
    ax.legend(facecolor=DARK_AX, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=9)
    fig.tight_layout()
    return _fig_to_bytes(fig)


# ─── График 3: интенсивность по неделям ───────────────────────────────────────

def chart_intensity(user_id: int, weeks: int = 8) -> io.BytesIO | None:
    """Столбчатая диаграмма средней интенсивности по неделям."""
    if not HAS_MATPLOTLIB:
        return None

    from db.connection import get_connection
    conn = get_connection()
    since = (datetime.date.today() - datetime.timedelta(weeks=weeks)).isoformat()

    rows = conn.execute("""
        SELECT strftime('%Y-%W', date) week, AVG(intensity) avg_int, COUNT(*) cnt
        FROM workouts
        WHERE user_id = ? AND date >= ? AND completed = 1 AND intensity IS NOT NULL
        GROUP BY week
        ORDER BY week ASC
    """, (user_id, since)).fetchall()

    if not rows:
        return None

    labels = [f"Нед.{r['week'].split('-')[1]}" for r in rows]
    values = [round(float(r["avg_int"]), 1) for r in rows]
    counts = [r["cnt"] for r in rows]

    fig, ax = plt.subplots(figsize=(8, 4))
    _setup_style(fig, ax, f"⚡ Интенсивность тренировок — {weeks} недель")

    bar_colors = [ACCENT_GREEN if v < 6 else ACCENT_ORANGE if v < 8 else ACCENT_RED
                  for v in values]
    bars = ax.bar(labels, values, color=bar_colors, alpha=0.85, zorder=3)

    for bar, val, cnt in zip(bars, values, counts):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1,
                f"{val}\n({cnt}тр)", ha="center", va="bottom",
                fontsize=8, color=TEXT_COLOR)

    ax.set_ylim(0, 11)
    ax.set_ylabel("Ср. интенсивность /10", color=TEXT_COLOR)
    ax.axhline(y=7, color=ACCENT_ORANGE, linewidth=1, linestyle="--", alpha=0.5)
    plt.xticks(rotation=30)
    fig.tight_layout()
    return _fig_to_bytes(fig)


# ─── График 4: сон и энергия ──────────────────────────────────────────────────

def chart_sleep(user_id: int, days: int = 30) -> io.BytesIO | None:
    """Двойной график: сон (столбцы) + энергия (линия)."""
    if not HAS_MATPLOTLIB:
        return None

    from db.connection import get_connection
    conn = get_connection()
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()

    rows = conn.execute("""
        SELECT date, sleep_hours, energy FROM metrics
        WHERE user_id = ? AND date >= ?
          AND (sleep_hours IS NOT NULL OR energy IS NOT NULL)
        ORDER BY date ASC
    """, (user_id, since)).fetchall()

    if len(rows) < 3:
        return None

    dates  = [datetime.date.fromisoformat(r["date"]) for r in rows]
    sleep  = [float(r["sleep_hours"]) if r["sleep_hours"] else None for r in rows]
    energy = [float(r["energy"]) if r["energy"] else None for r in rows]

    fig, ax1 = plt.subplots(figsize=(8, 4))
    _setup_style(fig, ax1, f"😴 Сон и энергия — {days} дней")

    # Сон — столбцы (левая ось)
    sleep_vals = [v if v else 0 for v in sleep]
    ax1.bar(dates, sleep_vals, color=ACCENT_BLUE, alpha=0.5, label="Сон (ч)", zorder=2)
    ax1.set_ylabel("Сон, часов", color=ACCENT_BLUE)
    ax1.set_ylim(0, 12)
    ax1.axhline(y=7, color=ACCENT_BLUE, linewidth=1, linestyle="--", alpha=0.4)

    # Энергия — линия (правая ось)
    ax2 = ax1.twinx()
    ax2.set_facecolor(DARK_AX)
    en_dates = [d for d, v in zip(dates, energy) if v is not None]
    en_vals  = [v for v in energy if v is not None]
    if len(en_dates) > 1:
        ax2.plot(en_dates, en_vals, "o-", color=ACCENT_GREEN, linewidth=2,
                 markersize=5, label="Энергия /5", zorder=4)
    ax2.set_ylabel("Энергия /5", color=ACCENT_GREEN)
    ax2.set_ylim(0, 5.5)
    ax2.tick_params(colors=TEXT_COLOR, labelsize=9)
    ax2.spines["right"].set_color(GRID_COLOR)
    ax2.spines["top"].set_visible(False)

    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    plt.xticks(rotation=30)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2,
               facecolor=DARK_AX, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=9)
    fig.tight_layout()
    return _fig_to_bytes(fig)


# ─── График 5: Fitness Score ──────────────────────────────────────────────────

def chart_fitness_score(user_id: int) -> io.BytesIO | None:
    """История Fitness Score по всем тестам."""
    if not HAS_MATPLOTLIB:
        return None

    from db.connection import get_connection
    conn = get_connection()

    rows = conn.execute("""
        SELECT tested_at, fitness_score FROM fitness_metrics
        WHERE user_id = ? AND fitness_score IS NOT NULL
        ORDER BY tested_at ASC
    """, (user_id,)).fetchall()

    if len(rows) < 2:
        return None

    dates  = [datetime.date.fromisoformat(r["tested_at"][:10]) for r in rows]
    scores = [float(r["fitness_score"]) for r in rows]

    fig, ax = plt.subplots(figsize=(8, 4))
    _setup_style(fig, ax, "⭐ Fitness Score — все тесты")

    ax.plot(dates, scores, "o-", color=ACCENT_GREEN, linewidth=2.5, markersize=8, zorder=3)
    ax.fill_between(dates, scores, alpha=0.15, color=ACCENT_GREEN)

    # Аннотируем каждую точку
    for d, s in zip(dates, scores):
        ax.annotate(f"{s:.0f}", xy=(d, s), xytext=(0, 8),
                    textcoords="offset points", ha="center",
                    color=ACCENT_GREEN, fontsize=9, fontweight="bold")

    ax.set_ylabel("Score /100", color=TEXT_COLOR)
    ax.set_ylim(0, 105)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m.%y"))
    plt.xticks(rotation=30)

    if len(scores) >= 2:
        delta = scores[-1] - scores[0]
        sign  = "+" if delta >= 0 else ""
        color = ACCENT_GREEN if delta >= 0 else ACCENT_RED
        ax.text(0.98, 0.05, f"Прогресс: {sign}{delta:.0f} очков",
                transform=ax.transAxes, ha="right", va="bottom",
                color=color, fontsize=10, fontweight="bold")

    fig.tight_layout()
    return _fig_to_bytes(fig)


# ─── График 6: XP рост ────────────────────────────────────────────────────────

def chart_xp(user_id: int, weeks: int = 8) -> io.BytesIO | None:
    """Рост XP по неделям."""
    if not HAS_MATPLOTLIB:
        return None

    from db.connection import get_connection
    conn = get_connection()
    since = (datetime.date.today() - datetime.timedelta(weeks=weeks)).isoformat()

    rows = conn.execute("""
        SELECT strftime('%Y-%W', created_at) week, SUM(xp_amount) total_xp
        FROM xp_log
        WHERE user_id = ? AND created_at >= ?
        GROUP BY week
        ORDER BY week ASC
    """, (user_id, since)).fetchall()

    if not rows:
        return None

    labels = [f"Нед.{r['week'].split('-')[1]}" for r in rows]
    values = [int(r["total_xp"]) for r in rows]

    fig, ax = plt.subplots(figsize=(8, 4))
    _setup_style(fig, ax, f"⚡ XP по неделям — {weeks} недель")

    ax.bar(labels, values, color=ACCENT_ORANGE, alpha=0.85, zorder=3)
    for i, (label, val) in enumerate(zip(labels, values)):
        ax.text(i, val + max(values) * 0.02, f"+{val} XP",
                ha="center", va="bottom", fontsize=9,
                color=ACCENT_ORANGE, fontweight="bold")

    ax.set_ylabel("XP за неделю", color=TEXT_COLOR)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    plt.xticks(rotation=30)
    total = sum(values)
    ax.text(0.98, 0.95, f"Всего: {total} XP",
            transform=ax.transAxes, ha="right", va="top",
            color=ACCENT_ORANGE, fontsize=11, fontweight="bold")
    fig.tight_layout()
    return _fig_to_bytes(fig)


# ─── Роутер ───────────────────────────────────────────────────────────────────

CHART_REGISTRY = {
    "weight":    ("⚖️ Динамика веса",          chart_weight),
    "strength":  ("💪 Личные рекорды",          chart_strength),
    "intensity": ("⚡ Интенсивность",            chart_intensity),
    "sleep":     ("😴 Сон и энергия",            chart_sleep),
    "fitness":   ("⭐ Fitness Score",            chart_fitness_score),
    "xp":        ("🏆 Рост XP",                 chart_xp),
}


def build_chart(chart_type: str, user_id: int, **kwargs) -> io.BytesIO | None:
    """
    Роутер: chart_type → функция → BytesIO | None.
    """
    if not HAS_MATPLOTLIB:
        return None
    entry = CHART_REGISTRY.get(chart_type)
    if not entry:
        return None
    _, fn = entry
    try:
        return fn(user_id, **kwargs)
    except Exception as e:
        logger.error(f"[CHARTS] build_chart({chart_type}) for {user_id}: {e}")
        return None
