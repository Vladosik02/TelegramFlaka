import os
import datetime
from dotenv import load_dotenv

load_dotenv()

# ─── Токены ───────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")   # опционально — для Whisper

# ─── Валидация обязательных переменных при старте (Фаза 14.4) ─────────────────
if not TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN не задан в .env — бот не может запуститься")
if not ANTHROPIC_API_KEY:
    raise ValueError("❌ ANTHROPIC_API_KEY не задан в .env — AI-функции недоступны")

# ─── Администратор (Фаза 8.5) ─────────────────────────────────────────────────
# Установи ADMIN_USER_ID в .env — Telegram user_id владельца бота
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", 0))

# ─── Модель ───────────────────────────────────────────────────────────────────
MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 3000  # 1500 → 3000: больше пространства для tool use цепочек, меньше срезаний

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
SCHEDULE_MAX_EVENING    = "20:00"

# ─── Расписание LIGHT (окна) ──────────────────────────────────────────────────
SCHEDULE_LIGHT_MORNING_WINDOW   = (8, 10)    # случайно внутри окна
SCHEDULE_LIGHT_AFTERNOON_WINDOW = (12, 15)

# ─── Напоминания ──────────────────────────────────────────────────────────────
REMINDER_INTERVAL_MIN = 45
REMINDER_MAX_COUNT    = 3
STOP_MAX_DAYS         = 30

# ─── Агрегация ────────────────────────────────────────────────────────────────
DAILY_SUMMARY_TIME   = "23:00"
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
    "grechka":  {"label": "Гречка + курица",  "calories": 550, "protein_g": 45, "fat_g": 12, "carbs_g": 65},
    "ovsyanka": {"label": "Овсянка",           "calories": 350, "protein_g": 12, "fat_g":  8, "carbs_g": 55},
    "tvorog":   {"label": "Творог 5%",         "calories": 200, "protein_g": 28, "fat_g":  5, "carbs_g":  8},
    "eggs":     {"label": "Яйца ×3",           "calories": 250, "protein_g": 21, "fat_g": 18, "carbs_g":  2},
    "protein":  {"label": "Протеин (шейк)",    "calories": 150, "protein_g": 25, "fat_g":  3, "carbs_g":  5},
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
