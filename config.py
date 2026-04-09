import os
import datetime
from dotenv import load_dotenv

load_dotenv()

# ─── Токены ───────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")   # опционально — для Whisper

# ─── Язык интерфейса ─────────────────────────────────────────────────────────
# BOT_LANG используется вместо LANG, чтобы не конфликтовать с системной
# переменной LANG (Linux: "C", "en_US.UTF-8" и т.п.)
_bot_lang = os.getenv("BOT_LANG", os.getenv("LANG", "ru"))
LANG = _bot_lang if _bot_lang in ("ru", "uk") else "ru"

# ─── Валидация обязательных переменных при старте (Фаза 14.4) ─────────────────
if not TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN не задан в .env — бот не может запуститься")
if not ANTHROPIC_API_KEY:
    raise ValueError("❌ ANTHROPIC_API_KEY не задан в .env — AI-функции недоступны")

# ─── Администратор (Фаза 8.5) ─────────────────────────────────────────────────
# Установи ADMIN_USER_ID в .env — Telegram user_id владельца бота
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", 0))

# ─── Модель ───────────────────────────────────────────────────────────────────
MODEL            = "claude-sonnet-4-20250514"
MODEL_FOOD_PARSE = "claude-haiku-4-5-20251001"  # Haiku для парсинга еды → КБЖУ (дёшево)
MAX_TOKENS            = 3000  # полный чат/аналитика/планирование
MAX_TOKENS_FOOD_PARSE = 300   # JSON-ответ парсинга еды

# ─── Token-оптимизация (Фаза 17) ──────────────────────────────────────────────
# CRUD-эшелон: запись еды / тренировок / метрик без вопросов и аналитики.
# Haiku в 20× дешевле Sonnet; вместе с фильтрацией tools и slim-контекстом
# итоговая экономия ~40-50× на рутинных операциях.
MODEL_CRUD      = "claude-haiku-4-5-20251001"  # тот же Haiku что и для food_parse
MAX_TOKENS_CRUD = 1200  # короткое подтверждение + tool use цепочка (vs 3000)

# Scheduled jobs тоже переключены на Haiku (меньше нагрузка на API, дешевле)
MODEL_SCHEDULED      = "claude-haiku-4-5-20251001"
MAX_TOKENS_SCHEDULED = 1500

# ─── Пути ─────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "trainer.db")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
PROMPTS_DIR = os.path.join(BASE_DIR, "ai", "prompts")

# ─── Режим дня ────────────────────────────────────────────────────────────────
def get_trainer_mode(day: int = None) -> str:
    """MAX — нечётные дни, LIGHT — чётные."""
    d = day if day is not None else datetime.date.today().day
    return "MAX" if d % 2 != 0 else "LIGHT"

# ─── Расписание MAX (жёсткое) ─────────────────────────────────────────────────
SCHEDULE_MAX_MORNING    = "09:00"
SCHEDULE_MAX_AFTERNOON  = "12:30"
SCHEDULE_MAX_EVENING    = "16:00"   # Вечерний чек-ин (тренировка + еда)
SCHEDULE_NIGHT_CHECKIN  = "23:00"   # Ночной чек-ин (итог дня)

# ─── Расписание LIGHT (окна) ──────────────────────────────────────────────────
SCHEDULE_LIGHT_MORNING_WINDOW   = (8, 10)    # случайно внутри окна
SCHEDULE_LIGHT_AFTERNOON_WINDOW = (12, 15)

# ─── Напоминания ──────────────────────────────────────────────────────────────
REMINDER_INTERVAL_MIN = 45
REMINDER_MAX_COUNT    = 3
STOP_MAX_DAYS         = 30

# ─── Агрегация ────────────────────────────────────────────────────────────────
DAILY_SUMMARY_TIME        = "23:30"  # после ночного чек-ина (23:00)
NUTRITION_ANALYSIS_TIME   = "21:45"  # анализ паттернов питания (после daily_summary)
PERSONAL_INSIGHTS_TIME    = "20:45"  # персональные корреляции (воскресенье, перед weekly 21:00)
WEEKLY_SUMMARY_DAY   = 6   # воскресенье (0=пн)
MONTHLY_SUMMARY_TIME = "09:00"  # 1-е число каждого месяца (Фаза 8.1)
MONTHLY_BACKUP_TIME  = "03:00"

# ─── Безопасность ─────────────────────────────────────────────────────────────
HEALTH_KEYWORDS = [
    "боль в груди", "не могу дышать", "сломал", "травма",
    "давление", "голова кружится", "потерял сознание"
]

# ─── Фитнес-тест (Фаза 8.2) ─────────────────────────────────────────────────
TEST_COOLDOWN_DAYS  = 7   # предупреждение если тест < 7 дней назад (не блокировка)
TEST_MAX_PUSHUPS    = 300  # валидация: максимум отжиманий
TEST_MAX_SQUATS     = 400  # валидация: максимум приседаний
TEST_MAX_PLANK_SEC  = 600  # валидация: максимум планки (10 мин)

SILENCE_AFTER_DAYS  = 7   # молчим после N дней игнора
SOFT_START_DAYS     = 7   # мягкий старт после паузы > N дней

# ─── Планирование тренировок (Фаза 8.3) ───────────────────────────────────────
TRAINING_PLAN_ARCHIVE_TIME  = "19:00"  # воскресенье — архивация прошлой недели
TRAINING_PLAN_GENERATE_TIME = "20:00"  # воскресенье — генерация плана на след. неделю

# ─── Напоминания перед тренировкой (Фаза 13.5) ────────────────────────────────
# Два окна: утреннее и вечернее. Каждое отправляется только нужным пользователям.
PRE_WORKOUT_MORNING_TIME = "08:30"  # для morning/flexible тренеров
PRE_WORKOUT_EVENING_TIME = "19:30"  # для evening тренеров

# ─── Quick Meal Presets (Фаза 15.4) ───────────────────────────────────────────
# Пресеты частых приёмов пищи: callback_id → {calories, protein_g, fat_g, carbs_g, label}
QUICK_MEAL_PRESETS: dict = {
    "grechka":  {"calories": 550, "protein_g": 45, "fat_g": 12, "carbs_g": 65},
    "ovsyanka": {"calories": 350, "protein_g": 12, "fat_g":  8, "carbs_g": 55},
    "tvorog":   {"calories": 200, "protein_g": 28, "fat_g":  5, "carbs_g":  8},
    "eggs":     {"calories": 250, "protein_g": 21, "fat_g": 18, "carbs_g":  2},
    "protein":  {"calories": 150, "protein_g": 25, "fat_g":  3, "carbs_g":  5},
}

# ─── Проактивные нудж-сообщения (Фаза 8.4) ────────────────────────────────────
NUDGE_CHECK_TIME         = "08:00"  # ежедневная проверка нудж-условий (до утреннего чек-ина)
NUDGE_DROP_DAYS          = 3        # дней без тренировки → 📉 drop alert
NUDGE_STREAK_GAP         = 3        # за N дней до рекорда стрика → 🔥 streak alert
NUDGE_PR_THRESHOLD_PCT   = 90       # последний результат >= N% рекорда → 💪 pr nudge
NUDGE_SLEEP_THRESHOLD    = 6.0      # часов сна — порог плохого сна
NUDGE_SLEEP_DAYS         = 3        # дней подряд с плохим сном → 😴 recovery nudge
NUDGE_COOLDOWN_HOURS     = 24       # кулдаун для drop/recovery (часы)
# Эти типы — не чаще раза в 7 дней (streak/PR/goal реже, т.к. менее срочные)
NUDGE_WEEKLY_COOLDOWN: tuple = ("streak", "pr_approaching", "goal_progress", "weight_trend")


# Fact pools moved to lang/ru.py and lang/uk.py (morning_facts, habit_facts)
