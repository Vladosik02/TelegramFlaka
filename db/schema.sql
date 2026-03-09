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
    generated_at        TEXT DEFAULT (datetime('now'))
);

-- ─── Индексы ──────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_workouts_user_date    ON workouts(user_id, date);
CREATE INDEX IF NOT EXISTS idx_metrics_user_date     ON metrics(user_id, date);
CREATE INDEX IF NOT EXISTS idx_checkins_user_date    ON checkins(user_id, date, time_slot);
CREATE INDEX IF NOT EXISTS idx_context_user          ON conversation_context(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_reminders_user_status ON reminders(user_id, status, scheduled_at);
