-- schema.sql — SQLite, 4 уровня памяти
-- Уровень 1: Профиль (постоянный)
-- Уровень 2: Прогресс (долгосрочный)
-- Уровень 3: Рабочий контекст (недели)
-- Уровень 4: Сессия (часы)

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ─── Профиль пользователя ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_profile (
    id              INTEGER PRIMARY KEY,
    telegram_id     INTEGER UNIQUE NOT NULL,
    name            TEXT,
    goal            TEXT,           -- "похудеть", "набрать массу", "выносливость"
    fitness_level   TEXT DEFAULT 'beginner',  -- beginner / intermediate / advanced
    injuries        TEXT,           -- JSON список травм
    timezone        TEXT DEFAULT 'Europe/Warsaw',
    active          INTEGER DEFAULT 1,
    soft_start      INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now')),
    paused_at       TEXT,
    last_active     TEXT
);

-- ─── Уровень 2: Тренировки ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workouts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES user_profile(id),
    date            TEXT NOT NULL,          -- YYYY-MM-DD
    mode            TEXT NOT NULL,          -- MAX / LIGHT
    type            TEXT,                   -- cardio / strength / stretch / rest
    duration_min    INTEGER,
    intensity       INTEGER CHECK(intensity BETWEEN 1 AND 10),
    exercises       TEXT,                   -- JSON список
    notes           TEXT,
    completed       INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ─── Уровень 2: Физические метрики ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS metrics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES user_profile(id),
    date            TEXT NOT NULL,
    weight_kg       REAL,
    sleep_hours     REAL,
    energy          INTEGER CHECK(energy BETWEEN 1 AND 5),
    mood            INTEGER CHECK(mood BETWEEN 1 AND 5),
    water_liters    REAL,
    steps           INTEGER,
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ─── Уровень 3: Дневные чек-ины ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS checkins (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES user_profile(id),
    date            TEXT NOT NULL,
    time_slot       TEXT NOT NULL,  -- morning / afternoon / evening
    status          TEXT DEFAULT 'pending',  -- pending / done / skipped
    user_message    TEXT,
    ai_response     TEXT,
    reminder_count  INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ─── Уровень 3: Недельные агрегаты ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS weekly_summaries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES user_profile(id),
    week_start      TEXT NOT NULL,  -- YYYY-MM-DD понедельник
    workouts_done   INTEGER DEFAULT 0,
    workouts_total  INTEGER DEFAULT 0,
    avg_intensity   REAL,
    avg_sleep       REAL,
    avg_energy      REAL,
    total_steps     INTEGER,
    summary_text    TEXT,           -- сгенерировано AI
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ─── Уровень 4: Активная сессия разговора ────────────────────────────────
CREATE TABLE IF NOT EXISTS conversation_context (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES user_profile(id),
    role            TEXT NOT NULL,  -- user / assistant
    content         TEXT NOT NULL,
    checkin_id      INTEGER REFERENCES checkins(id),
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ─── Напоминания ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS reminders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES user_profile(id),
    checkin_id      INTEGER REFERENCES checkins(id),
    scheduled_at    TEXT NOT NULL,
    sent_at         TEXT,
    status          TEXT DEFAULT 'pending'  -- pending / sent / cancelled
);

-- ═══════════════════════════════════════════════════════════════════════════
-- 4-СЛОЙНАЯ ПАМЯТЬ (V1 Smart Card + V2 TTL)
-- ═══════════════════════════════════════════════════════════════════════════

-- ─── L0 + L1: Карточка атлета ────────────────────────────────────────────
-- L0 (поверхностный, ~150 tok): age, height, season, streak
-- L1 (глубокий, ~150 tok): injuries_detail, intolerances, supplement_reactions, records
CREATE TABLE IF NOT EXISTS memory_athlete (
    user_id             INTEGER PRIMARY KEY REFERENCES user_profile(id),
    -- L0 поля
    age                 INTEGER,
    height_cm           REAL,
    season              TEXT DEFAULT 'maintain',  -- bulk / cut / maintain / peak
    -- L1 поля (загружаются только при health-контексте)
    food_intolerances   TEXT DEFAULT '[]',        -- JSON: ["лактоза", "глютен"]
    supplement_reactions TEXT DEFAULT '{}',        -- JSON: {"креатин": "хорошо переносит"}
    personal_records    TEXT DEFAULT '{}',         -- JSON: {"bench_1rm": 100, "5k_min": 28}
    updated_at          TEXT DEFAULT (datetime('now'))
);

-- ─── L2: Питание ──────────────────────────────────────────────────────────
-- Brief (~120 tok) ВСЕГДА, deep (~200 tok) при food-контексте
CREATE TABLE IF NOT EXISTS memory_nutrition (
    user_id             INTEGER PRIMARY KEY REFERENCES user_profile(id),
    -- Brief (всегда)
    daily_calories      INTEGER,
    protein_g           INTEGER,
    fat_g               INTEGER,
    carbs_g             INTEGER,
    -- Deep (только при упоминании еды)
    meal_preferences    TEXT DEFAULT '{}',  -- JSON: {"breakfast": "овсянка", ...}
    supplements         TEXT DEFAULT '[]',  -- JSON: ["протеин 30г", "омега-3"]
    restrictions        TEXT DEFAULT '[]',  -- JSON: ["без сахара", "без алкоголя"]
    last_meal_notes     TEXT,               -- последние заметки о питании
    updated_at          TEXT DEFAULT (datetime('now'))
);

-- ─── L3: Тренировочный интеллект ─────────────────────────────────────────
-- Brief (~150 tok) ВСЕГДА, deep (~250 tok) при training-контексте
CREATE TABLE IF NOT EXISTS memory_training (
    user_id             INTEGER PRIMARY KEY REFERENCES user_profile(id),
    -- Brief (всегда)
    preferred_days      TEXT DEFAULT '[]',   -- JSON: ["вторник", "пятница"]
    preferred_time      TEXT DEFAULT 'flexible',  -- morning / evening / flexible
    avg_session_min     INTEGER DEFAULT 45,
    current_program     TEXT,                -- название текущей программы
    -- Deep (только при training-контексте)
    exercise_scores     TEXT DEFAULT '{}',   -- JSON: {"squat": {"score": 7.2, "pattern": "legs_compound"}}
    avoided_exercises   TEXT DEFAULT '[]',   -- JSON: ["выпады" (из-за колена)]
    training_notes      TEXT,                -- заметки по стилю тренировок
    updated_at          TEXT DEFAULT (datetime('now'))
);

-- ─── L4: AI Intelligence ──────────────────────────────────────────────────
-- ВСЕГДА (~200 tok): дайджест + наблюдения + тренды
CREATE TABLE IF NOT EXISTS memory_intelligence (
    user_id             INTEGER PRIMARY KEY REFERENCES user_profile(id),
    weekly_digest       TEXT,               -- AI-сгенерированный дайджест недели
    ai_observations     TEXT DEFAULT '[]',  -- JSON: ["Лучше тренируется вт/пт", ...]
    seasonal_context    TEXT,               -- что сейчас важно с учётом сезона
    motivation_level    TEXT DEFAULT 'normal',  -- low / normal / high
    trend_summary       TEXT,               -- краткий трендовый анализ
    bio_insights        TEXT,               -- AI-анализ биоданных: возраст/рост/вес → потенциал, прогрессия, TDEE-разрыв
    generated_at        TEXT DEFAULT (datetime('now'))
);

-- ═══════════════════════════════════════════════════════════════════════════
-- ФАЗА 7 — РАСШИРЕННАЯ АНАЛИТИКА
-- ═══════════════════════════════════════════════════════════════════════════

-- ─── Журнал питания (дневной) ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS nutrition_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES user_profile(id),
    date            TEXT NOT NULL,          -- YYYY-MM-DD
    calories        INTEGER,                -- реально съеденные ккал
    protein_g       REAL,
    fat_g           REAL,
    carbs_g         REAL,
    water_ml        INTEGER,
    meal_notes      TEXT,                   -- что ел (краткое)
    quality_score   INTEGER CHECK(quality_score BETWEEN 1 AND 10),
    junk_food       INTEGER DEFAULT 0,      -- 1 = был фастфуд/мусор
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ─── AI-рекомендации по питанию ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS nutrition_insights (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES user_profile(id),
    insight_type    TEXT,   -- deficiency / recommendation / warning
    nutrient        TEXT,   -- что конкретно (витамин D, белок и т.д.)
    description     TEXT,
    action          TEXT,   -- что делать
    detected_at     TEXT DEFAULT (datetime('now')),
    resolved        INTEGER DEFAULT 0
);

-- ─── Детальный лог упражнений ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS exercise_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES user_profile(id),
    workout_id      INTEGER REFERENCES workouts(id),
    date            TEXT NOT NULL,
    exercise_name   TEXT NOT NULL,
    sets            INTEGER,
    reps            INTEGER,
    duration_sec    INTEGER,        -- для планки, кардио
    weight_kg       REAL,           -- если с весом
    is_personal_record INTEGER DEFAULT 0,
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ─── Личные рекорды ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS personal_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES user_profile(id),
    exercise_name   TEXT NOT NULL,
    record_value    REAL NOT NULL,  -- число (повторы/секунды/кг)
    record_type     TEXT NOT NULL,  -- reps / time / weight
    set_at          TEXT NOT NULL,  -- YYYY-MM-DD
    previous_record REAL,           -- предыдущий рекорд для сравнения
    improvement_pct REAL,           -- прирост в %
    notes           TEXT
);

-- ─── AI-дневное резюме ────────────────────────────────────────────────────
-- Генерируется ночью (после вечернего чек-ина).
-- Используется как долгосрочная память: AI видит последние 3–7 дней.
CREATE TABLE IF NOT EXISTS daily_summary (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES user_profile(id),
    date            TEXT NOT NULL,          -- YYYY-MM-DD
    summary_text    TEXT NOT NULL,          -- AI-сгенерированный текст (2–4 предложения)
    workout_done    INTEGER DEFAULT 0,      -- 1 = тренировка была
    calories_met    INTEGER DEFAULT 0,      -- 1 = план КБЖУ выполнен (±15%)
    mood_score      INTEGER,                -- 1–5 (из metrics)
    energy_score    INTEGER,                -- 1–5 (из metrics)
    sleep_hours     REAL,                   -- из metrics
    key_insight     TEXT,                   -- одно ключевое AI-наблюдение
    generated_at    TEXT DEFAULT (datetime('now')),
    UNIQUE(user_id, date)
);

-- ═══════════════════════════════════════════════════════════════════════════
-- ФАЗА 8 — АНАЛИТИКА
-- ═══════════════════════════════════════════════════════════════════════════

-- ─── AI-месячное резюме ────────────────────────────────────────────────────
-- Генерируется 1-го числа каждого месяца в 09:00.
-- Даёт AI долгосрочную «хронику» — последние 3 месяца как контекст.
-- Грузится ТОЛЬКО при analytics-контексте (экономия токенов).
CREATE TABLE IF NOT EXISTS monthly_summary (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES user_profile(id),
    month           TEXT NOT NULL,          -- YYYY-MM (за прошедший месяц)
    workouts_done   INTEGER DEFAULT 0,
    workouts_total  INTEGER DEFAULT 0,      -- рабочих дней в месяце (из weekly_summaries)
    avg_intensity   REAL,
    avg_sleep       REAL,
    avg_energy      REAL,
    avg_calories    INTEGER,                -- среднее ккал/день (из nutrition_log)
    best_exercise   TEXT,                   -- название упражнения с лучшим PR
    best_pr_text    TEXT,                   -- человекочитаемо: "жим 90кг"
    summary_text    TEXT,                   -- AI: 2–3 предложения о месяце
    trend_vs_prev   TEXT,                   -- AI: сравнение с предыдущим месяцем
    key_insight     TEXT,                   -- AI: 1 рекомендация на следующий месяц
    generated_at    TEXT DEFAULT (datetime('now')),
    UNIQUE(user_id, month)
);

-- ─── Фитнес-тест (Фаза 8.2) ─────────────────────────────────────────────
-- Периодическое тестирование: отжимания, приседания, планка.
-- Нормализация по ACSM/NSCA/Cooper Institute.
-- fitness_score = pushups×0.35 + squats×0.35 + plank×0.30
CREATE TABLE IF NOT EXISTS user_fitness_metrics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES user_profile(id),
    tested_at       TEXT NOT NULL,          -- YYYY-MM-DD
    max_pushups     INTEGER,                -- повт, без остановки
    max_squats      INTEGER,                -- повт, без остановки
    plank_sec       INTEGER,                -- секунды
    resting_hr      INTEGER,                -- ЧСС покоя (уд/мин, опц.)
    pushups_score   REAL,                   -- 0-100 (piecewise ACSM)
    squats_score    REAL,                   -- 0-100
    plank_score     REAL,                   -- 0-100
    fitness_score   REAL,                   -- итоговый 0-100
    strength_score  REAL,                   -- (pushups+squats)/2
    endurance_score REAL,                   -- NULL (зарезервировано)
    flexibility_score REAL,                 -- NULL (зарезервировано)
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ═══════════════════════════════════════════════════════════════════════════
-- ФАЗА 8.3 — AI PLAN
-- ═══════════════════════════════════════════════════════════════════════════

-- ─── Недельный AI-план тренировок ─────────────────────────────────────────
-- plan_id = "PLN-{user_id}-{YYYYWW}" — уникален, сортируемый, человекочитаемый.
-- Цикл: draft → active (воскресенье 20:00) → archived (следующее воскресенье 19:00).
-- После архивации данные интегрируются в monthly_summary как 1/4 месяца.
CREATE TABLE IF NOT EXISTS training_plan (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id             TEXT NOT NULL UNIQUE,   -- "PLN-{user_id}-{YYYYWW}"
    user_id             INTEGER NOT NULL REFERENCES user_profile(id),
    week_start          TEXT NOT NULL,          -- YYYY-MM-DD (понедельник)
    status              TEXT DEFAULT 'active',  -- draft | active | archived
    -- Снимок состояния атлета на момент генерации
    fitness_score_snap  REAL,
    sleep_avg_snap      REAL,                   -- средний сон за последние 7 дней
    energy_avg_snap     REAL,                   -- средняя энергия за последние 7 дней
    calories_target     INTEGER,                -- цель КБЖУ на неделю
    season              TEXT,                   -- сезон на момент генерации
    -- Контент плана
    plan_json           TEXT NOT NULL,          -- JSON-массив объектов дней
    ai_rationale        TEXT,                   -- AI-обоснование плана
    -- Статистика выполнения (обновляется при архивации)
    workouts_planned    INTEGER DEFAULT 0,
    workouts_completed  INTEGER DEFAULT 0,
    completion_pct      REAL,                   -- % выполнения
    volume_total        INTEGER,                -- суммарные минуты тренировок
    intensity_avg       REAL,                   -- средняя целевая интенсивность
    -- Временные метки
    generated_at        TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now')),
    archived_at         TEXT,
    UNIQUE(user_id, week_start)
);

-- ═══════════════════════════════════════════════════════════════════════════
-- ФАЗА 8.4 — ПРОАКТИВНЫЕ НУДЖ-СООБЩЕНИЯ
-- ═══════════════════════════════════════════════════════════════════════════

-- ─── Журнал отправленных нудж-сообщений ───────────────────────────────────
-- Используется для anti-spam логики:
--   • drop / recovery: кулдаун 24 ч
--   • streak / pr_approaching / goal_progress: кулдаун 7 дней
CREATE TABLE IF NOT EXISTS nudge_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES user_profile(id),
    nudge_type      TEXT NOT NULL,  -- drop | streak | pr_approaching | recovery | goal_progress
    sent_at         TEXT DEFAULT (datetime('now')),
    message_preview TEXT            -- первые 100 символов отправленного сообщения
);

-- ═══════════════════════════════════════════════════════════════════════════
-- ФАЗА 10 — INTELLIGENT AGENT & GAMIFICATION
-- ═══════════════════════════════════════════════════════════════════════════

-- ─── Геймификация: XP и уровни ────────────────────────────────────────────
-- Уровни: 1=Новичок(0), 2=Стартер(500), 3=Атлет(1500), 4=Боец(3000),
--         5=Чемпион(5500), 6=Элита(9000), 7=Мастер(14000), 8=Легенда(21000)
CREATE TABLE IF NOT EXISTS user_xp (
    user_id         INTEGER PRIMARY KEY REFERENCES user_profile(id),
    total_xp        INTEGER DEFAULT 0,
    current_level   INTEGER DEFAULT 1,
    level_name      TEXT DEFAULT 'Новичок',
    last_xp_at      TEXT,
    streak_days     INTEGER DEFAULT 0,      -- текущий streak тренировок
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- ─── Ачивки ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS achievements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES user_profile(id),
    achievement_key TEXT NOT NULL,          -- "first_workout", "streak_7", "pr_beast", etc.
    achievement_name TEXT NOT NULL,         -- "Первая тренировка 🏋️"
    description     TEXT,                   -- описание ачивки
    xp_reward       INTEGER DEFAULT 0,      -- сколько XP давала при разблокировке
    unlocked_at     TEXT DEFAULT (datetime('now')),
    UNIQUE(user_id, achievement_key)
);

-- ─── Лог XP-транзакций ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS xp_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES user_profile(id),
    xp_amount       INTEGER NOT NULL,       -- может быть отрицательным
    reason          TEXT NOT NULL,          -- "workout", "pr", "streak_bonus", etc.
    detail          TEXT,                   -- доп. описание (название упражнения и т.д.)
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ─── Эпизодическая память (A-MEM/MemGPT-inspired) ────────────────────────
-- TTL: personal_record=90д, insight=60д, goal_update=365д, conversation=30д
CREATE TABLE IF NOT EXISTS episodic_memory (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES user_profile(id),
    episode_type    TEXT NOT NULL,   -- personal_record | insight | goal_update | conversation | milestone
    tags            TEXT DEFAULT '[]',  -- JSON: ["strength", "squat", "pr"]
    summary         TEXT NOT NULL,      -- краткое описание (1-2 предложения для контекста)
    detail          TEXT,               -- полные данные если нужны
    importance      INTEGER DEFAULT 5 CHECK(importance BETWEEN 1 AND 10),
    expires_at      TEXT,               -- NULL = не истекает
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ═══════════════════════════════════════════════════════════════════════════
-- ФАЗА 12 — ADVANCED ANALYTICS & PERIODIZATION
-- ═══════════════════════════════════════════════════════════════════════════

-- ─── Мезоциклы (Фаза 12.2) ────────────────────────────────────────────────
-- Схема: Накопление (3 нед) → Интенсификация (2 нед) → Реализация (1 нед) → Deload (1 нед)
-- Автоматически переключается каждое воскресенье через advance_mesocycle().
CREATE TABLE IF NOT EXISTS mesocycles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES user_profile(id),
    phase           TEXT NOT NULL,          -- accumulation | intensification | realization | deload
    phase_index     INTEGER DEFAULT 0,      -- позиция в PHASE_ORDER (0..6 для 7-недельного цикла)
    week_number     INTEGER NOT NULL,       -- неделя внутри фазы (начинается с 1)
    total_weeks     INTEGER NOT NULL,       -- общая длина цикла (7 недель по умолчанию)
    started_at      TEXT,                   -- YYYY-MM-DD начала цикла
    completed_at    TEXT                    -- YYYY-MM-DD завершения (NULL = активный)
);

-- ─── Индексы ──────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_workouts_user_date       ON workouts(user_id, date);
CREATE INDEX IF NOT EXISTS idx_metrics_user_date        ON metrics(user_id, date);
CREATE INDEX IF NOT EXISTS idx_checkins_user_date       ON checkins(user_id, date, time_slot);
CREATE INDEX IF NOT EXISTS idx_context_user             ON conversation_context(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_reminders_user_status    ON reminders(user_id, status, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_nutrition_log_user_date  ON nutrition_log(user_id, date);
CREATE INDEX IF NOT EXISTS idx_exercise_results_user    ON exercise_results(user_id, date);
CREATE INDEX IF NOT EXISTS idx_exercise_results_user_ex ON exercise_results(user_id, exercise_name, date);
CREATE INDEX IF NOT EXISTS idx_personal_records_user    ON personal_records(user_id, exercise_name);
CREATE INDEX IF NOT EXISTS idx_daily_summary_user_date  ON daily_summary(user_id, date);
CREATE INDEX IF NOT EXISTS idx_monthly_summary_user     ON monthly_summary(user_id, month);
CREATE INDEX IF NOT EXISTS idx_fitness_metrics_user     ON user_fitness_metrics(user_id, tested_at);
CREATE INDEX IF NOT EXISTS idx_training_plan_user       ON training_plan(user_id, week_start);
CREATE INDEX IF NOT EXISTS idx_training_plan_status     ON training_plan(user_id, status);
CREATE INDEX IF NOT EXISTS idx_nudge_log_user           ON nudge_log(user_id, nudge_type, sent_at);
CREATE INDEX IF NOT EXISTS idx_achievements_user        ON achievements(user_id, achievement_key);
CREATE INDEX IF NOT EXISTS idx_xp_log_user              ON xp_log(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_episodic_user_type       ON episodic_memory(user_id, episode_type, created_at);
CREATE INDEX IF NOT EXISTS idx_episodic_expires         ON episodic_memory(user_id, expires_at);
CREATE INDEX IF NOT EXISTS idx_mesocycles_user          ON mesocycles(user_id, completed_at);

-- ═══════════════════════════════════════════════════════════════════════════
-- AI USAGE LOG — отслеживание расходов Anthropic API
-- ═══════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS ai_usage_log (
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
    call_type           TEXT    DEFAULT 'chat'   -- chat | scheduled | agent
);

CREATE INDEX IF NOT EXISTS idx_usage_log_user_ts  ON ai_usage_log(user_id, timestamp);
