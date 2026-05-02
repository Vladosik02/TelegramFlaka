"""
db/migrations.py — Список инкрементальных миграций схемы.

Единый источник правды для:
  • db/connection.py:_run_migrations() — применяет к prod-БД при старте
  • tests/conftest.py — применяет к in-memory БД при создании фикстуры

Каждый элемент — SQL-запрос (ALTER TABLE / CREATE TABLE / CREATE INDEX).
Применять с try/except — если объект уже существует, ошибка игнорируется.

При добавлении новой миграции — только сюда. Никогда не дублировать в conftest.
"""
from __future__ import annotations

MIGRATIONS: list[str] = [
    # v1.1 — preferred_time для тренировочных предпочтений
    "ALTER TABLE memory_training ADD COLUMN preferred_time TEXT DEFAULT 'flexible'",
    # v1.2 — место тренировки в профиле
    "ALTER TABLE user_profile ADD COLUMN training_location TEXT DEFAULT 'flexible'",
    # v1.3 — стартовые физические показатели (базовая линия)
    "ALTER TABLE memory_athlete ADD COLUMN baseline_pushups INTEGER",
    "ALTER TABLE memory_athlete ADD COLUMN baseline_squats INTEGER",
    "ALTER TABLE memory_athlete ADD COLUMN baseline_plank_sec INTEGER",
    # v1.4 — привязка тренировок к плану (Фаза 8.3)
    "ALTER TABLE workouts ADD COLUMN plan_id TEXT REFERENCES training_plan(plan_id)",
    # v1.5 — таблица логирования расходов Anthropic API
    """CREATE TABLE IF NOT EXISTS ai_usage_log (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id             INTEGER NOT NULL REFERENCES user_profile(id),
        timestamp           TEXT    NOT NULL,
        model               TEXT    NOT NULL,
        input_tokens        INTEGER NOT NULL DEFAULT 0,
        output_tokens       INTEGER NOT NULL DEFAULT 0,
        cache_read_tokens   INTEGER NOT NULL DEFAULT 0,
        cache_write_tokens  INTEGER NOT NULL DEFAULT 0,
        cost_usd            REAL    NOT NULL DEFAULT 0.0,
        response_time_sec   REAL,
        call_type           TEXT    DEFAULT 'chat'
    )""",
    "CREATE INDEX IF NOT EXISTS idx_usage_log_user_ts ON ai_usage_log(user_id, timestamp)",
    # v1.6 — составной индекс для get_exercise_history() по (user_id, exercise_name, date)
    "CREATE INDEX IF NOT EXISTS idx_exercise_results_user_ex ON exercise_results(user_id, exercise_name, date)",
    # v1.7 — доступное оборудование (JSON-список) в тренировочной карточке
    "ALTER TABLE memory_training ADD COLUMN equipment TEXT DEFAULT '[]'",
    # v1.8 — AI-анализ биоданных (возраст/рост/вес → потенциал, прогрессия, TDEE)
    "ALTER TABLE memory_intelligence ADD COLUMN bio_insights TEXT",
    # v1.9 — координаты и город для погодного контекста (scheduler/weather.py)
    "ALTER TABLE memory_athlete ADD COLUMN weather_lat REAL",
    "ALTER TABLE memory_athlete ADD COLUMN weather_lon REAL",
    "ALTER TABLE memory_athlete ADD COLUMN weather_city TEXT",
    # v2.0 — prediction feedback loop: хранение предсказаний рядом с фактом
    "ALTER TABLE exercise_results ADD COLUMN predicted_weight REAL",
    "ALTER TABLE exercise_results ADD COLUMN predicted_reps INTEGER",
    "ALTER TABLE exercise_results ADD COLUMN predicted_sets INTEGER",
]
