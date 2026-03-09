import os
import datetime
from dotenv import load_dotenv

load_dotenv()

# ─── Токены ───────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")   # опционально — для Whisper

# ─── Модель ───────────────────────────────────────────────────────────────────
MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 1000

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
MONTHLY_BACKUP_TIME  = "03:00"

# ─── Безопасность ─────────────────────────────────────────────────────────────
HEALTH_KEYWORDS = [
    "боль в груди", "не могу дышать", "сломал", "травма",
    "давление", "голова кружится", "потерял сознание"
]

SILENCE_AFTER_DAYS  = 7   # молчим после N дней игнора
SOFT_START_DAYS     = 7   # мягкий старт после паузы > N дней
