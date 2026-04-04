# Flaka — Coding Guide

Telegram-бот-тренер «Алекс». Этот файл — справочник для написания кода, не документация продукта.

## Stack
- Python 3.11 + python-telegram-bot 20.7
- Anthropic API — MODEL: `claude-sonnet-4-20250514`, MODEL_CRUD/SCHEDULED: `claude-haiku-4-5-20251001`
- MAX_TOKENS=3000, MAX_TOKENS_CRUD=1200, MAX_TOKENS_SCHEDULED=1500
- SQLite WAL (`data/trainer.db`) — 26 таблиц, 4-layer memory
- APScheduler (AsyncIOScheduler) — запускается в `post_init`
- Docker (multi-stage, botuser uid=1001), GCP VM (`/opt/trainer-bot`)
- GitHub Actions CI/CD (Syntax → Tests → Deploy via SSH)

## Architecture — Ключевые файлы

| Файл | Назначение |
|------|------------|
| `main.py` | Точка входа. `post_init` → scheduler. Startup tool validation (tools.py vs executor) |
| `config.py` | MODEL, токены, пути, расписание, QUICK_MEAL_PRESETS |
| `ai/client.py` | `generate_agent_response()` — agent loop (5 iter). `_cached_system()` — prompt caching |
| `ai/tools.py` | 15 tools (9 write + 6 read). `ALL_TOOLS`, `get_tools_for_tags()` |
| `ai/tool_executor.py` | `execute_tool()` — dispatch dict, валидация, logging |
| `ai/context_builder.py` | 4-слойный контекст (L0-L4), теги, CRUD/FULL tier dispatch |
| `ai/prompts/system_max.txt` | System prompt MAX-режим |
| `ai/prompts/system_light.txt` | System prompt LIGHT-режим |
| `bot/handlers.py` | `handle_message()`, `handle_callback()` — ~1600 строк, монолит |
| `bot/commands.py` | Все cmd_* функции (18 команд) |
| `bot/keyboards.py` | Все InlineKeyboardMarkup функции |
| `bot/debug.py` | `notify_error()`, `notify_tool_result()` — in-chat debug |
| `scheduler/jobs.py` | Регистрация 17 APScheduler задач |
| `scheduler/logic.py` | Чек-ины, weekly/daily/monthly reports |
| `scheduler/prediction.py` | Прогноз весов/повторов на тренировку |
| `scheduler/adaptation.py` | DELOAD/LIGHT/BOOST/NORMAL модификатор |
| `db/connection.py` | `get_connection()` singleton, `init_db()`, migrations |
| `db/queries/workouts.py` | `log_workout()` — upsert pattern |
| `tests/conftest.py` | `patched_db` fixture, in-memory SQLite |

## Tools — 15 инструментов

**WRITE (9):** save_workout, save_metrics, save_nutrition, save_exercise_result, set_personal_record, update_athlete_card, save_episode, award_xp, save_training_plan

**READ (6):** get_weekly_stats, get_nutrition_history, get_personal_records, get_current_plan, get_user_profile, get_workout_prediction

## Tiered Context

| Tier | Когда | Модель | История | Tools |
|------|-------|--------|---------|-------|
| **CRUD** | Теги food/training/metrics — запись | Haiku | 3 msg | 2-5 filtered |
| **FULL** | Теги analytics/plan/chat — диалог | Sonnet | 10 msg | ALL_TOOLS (15) |

Scheduled jobs всегда: Haiku + MAX_TOKENS_SCHEDULED=1500.

## 4-слойная память (L0-L4)

| Слой | Таблица | Всегда? | Содержимое |
|------|---------|---------|------------|
| **L0** | `memory_athlete` | да | Имя, цель, возраст, рост, вес, season, стрик |
| **L1** | `memory_athlete` | health | Травмы, непереносимости, добавки |
| **L2** | `memory_nutrition` | food | КБЖУ-цель, ограничения |
| **L3** | `memory_training` | training | Предпочтения, equipment, exercise_scores |
| **L4** | `memory_intelligence` | да | weekly_digest, observations (max 10), trend_summary |

`exercise_scores`: `score = 0.4×overload + 0.3×consistency + 0.3×alignment` per exercise.

---

## Code Patterns

### 1. Command Handler

```python
# bot/commands.py
async def cmd_example(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    tg = update.effective_user
    user = get_user(tg.id)
    if not user or not user["active"]:
        return
    streak = get_streak(user["id"])
    text = f"Привет, *{user.get('name')}*! Стрик: {streak}"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb_main_menu())
```

### 2. Tool Definition

```python
# ai/tools.py
TOOL_EXAMPLE = {
    "name": "example_tool",
    "description": "Что делает. Когда вызывать.",
    "input_schema": {
        "type": "object",
        "properties": {
            "field_name": {
                "type": "string",
                "description": "Описание поля"
            },
            "optional_field": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "description": "Описание (optional)"
            },
        },
        "required": ["field_name"],
        "additionalProperties": False
    }
}
# Добавить в ALL_TOOLS list и в _TOOLS_BY_TAG если CRUD
```

### 3. Tool Executor

```python
# ai/tool_executor.py
async def _tool_example(tg_id: int, inp: dict, **kwargs) -> dict:
    user = get_user(tg_id)
    if not user:
        return {"error": "User not found", "success": False}
    today = datetime.date.today().isoformat()
    result_id = some_db_function(user["id"], today, inp.get("field_name"))
    return {"success": True, "message": "Saved", "id": result_id}

# Добавить в _DISPATCH dict внутри _init_dispatch():
#   "example_tool": _tool_example,
```

### 4. DB Query (upsert pattern)

```python
# db/queries/example.py
def upsert_example(user_id: int, date: str, value: str = None) -> int:
    conn = get_connection()
    existing = conn.execute(
        "SELECT id FROM table_name WHERE user_id = ? AND date = ?",
        (user_id, date)
    ).fetchone()
    if existing:
        if value is not None:
            conn.execute("UPDATE table_name SET value = ? WHERE id = ?", (value, existing["id"]))
        conn.commit()
        return existing["id"]
    else:
        cur = conn.execute(
            "INSERT INTO table_name (user_id, date, value) VALUES (?, ?, ?)",
            (user_id, date, value)
        )
        conn.commit()
        return cur.lastrowid
```

### 5. Keyboard

```python
# bot/keyboards.py
def kb_example() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Action A", callback_data="prefix:action_a"),
            InlineKeyboardButton("Action B", callback_data="prefix:action_b"),
        ],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="menu:home")],
    ])
```

### 6. Callback Routing

```python
# bot/handlers.py :: handle_callback()
if data.startswith("prefix:"):
    action = data.split(":")[1]
    if action == "action_a":
        # ...
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb_next())
    elif action == "action_b":
        # ...
    return
```

Существующие prefixes: `menu:`, `chart:`, `wf:`, `reset:`, `stop:`, `adapt:`, `meal:`, `ci:`, `energy_`, `adm:`

### 7. Scheduler Job

```python
# scheduler/jobs.py
scheduler.add_job(
    broadcast_function, "cron",
    hour=9, minute=0,
    args=[bot],
    id="job_name",
    replace_existing=True,
)
```

---

## Checklists

### Новый tool (3 файла)
1. `ai/tools.py` — определение `TOOL_X` + добавить в `ALL_TOOLS` + в `_TOOLS_BY_TAG` если CRUD
2. `ai/tool_executor.py` — handler `_tool_x()` + добавить в `_DISPATCH` внутри `_init_dispatch()`
3. `ai/prompts/system_max.txt` + `system_light.txt` — описать tool для AI

Startup validation в `main.py:74-95` автоматически поймает рассинхрон tools↔executor.

### Новая команда (3 файла)
1. `bot/commands.py` — добавить `cmd_x()`
2. `main.py:101-118` — `app.add_handler(CommandHandler("x", cmd_x))` + import
3. `main.py` — добавить в `set_my_commands()` если нужна в меню

### Новая scheduled job (3 файла)
1. `scheduler/logic.py` (или отдельный модуль `scheduler/`) — async function
2. `scheduler/jobs.py` — `scheduler.add_job()`
3. `config.py` — time constant если нужно (pattern: `SCHEDULE_X_TIME = "HH:MM"`)

---

## Code Conventions

**Imports** — абсолютные, сгруппированные:
```python
import logging
import datetime
from telegram import Update
from telegram.ext import ContextTypes
from db.queries.user import get_user
from config import MODEL, MAX_TOKENS

logger = logging.getLogger(__name__)
```

**Logging** — `[PREFIX]` в скобках: `[TOOL]`, `[CHECKIN]`, `[AGENT]`, `[FOOD_PARSE]`
```python
logger.info(f"[CHECKIN] Morning sent to {telegram_id}")
logger.error(f"[TOOL] Error in '{tool_name}' for {tg_id}: {e}")
```

**Tool errors** — всегда dict:
```python
return {"error": "описание", "success": False}
return {"success": True, "message": "что сделано", "id": result_id}
```

**DB** — singleton `get_connection()`, WAL mode, `conn.execute()` + `conn.commit()`, `conn.row_factory = sqlite3.Row`

**Tests** — `patched_db` fixture патчит `get_connection` во всех модулях (список `_targets` в `conftest.py`). При добавлении нового DB-модуля — добавить его путь в `_targets`.

**Docker** — botuser uid=1001, пакеты глобальные (не --user), UTF-8 env.

---

## Известные ловушки

- **Двойное XP:** `tool_executor.py` автоматически начисляет 100 XP при `save_workout`. Если Claude вызовет ещё и `award_xp` — дублирование
- **handlers.py = 1600 строк:** монолит. Ищи функции по имени, не читай целиком
- **response_parser.py:** может быть dead code после Agent Tool Use. Не удаляй без проверки
- **SQLite concurrency:** scheduler + telegram handlers пишут одновременно → возможен `database is locked`
- **Стрик около полуночи:** `get_streak()` может давать неверный результат на границе дней

## Известные ограничения

- Personal insights не накапливаются — вычисляются заново каждую неделю, бот не помнит что уже сообщал
- L4 observations — max 10, старые вытесняются, долгосрочные наблюдения теряются
- Teach moments не хранятся — возможны повторы через несколько недель
- Нет состава тела (только weight_kg) — нельзя разделить массу на мышцы/жир
- Питание — дневной агрегат, нет тайминга приёмов пищи
- Онбординговые данные статичны — фитнес-тест не перезапускается автоматически
- Нет интеграций с wearables — recovery = subjective self-report

## Roadmap

**Быстрые победы:**
- Хранить показанные personal insights в БД → бот знает «я уже сообщал об этом паттерне»
- Anti-repeat для teach_moments → хранить хеши показанных фактов

**Средние:**
- Расширить L4 observations > 10 (archive + buffer)
- Автозапрос при стухших метриках (2+ дня без записи → подсказка в чек-ине)
- Детализация питания (meal-level: таблица `meal_entries`, tool `save_meal`)

**Большие:**
- Замеры тела (таблица `body_measurements`, tool `save_measurements`)
- Повторный фитнес-тест (`/retest` + auto-предложение раз в 2-3 месяца)
- Накопление personal insights в L3 как достоверные факты о пользователе

## CI/CD

```
push → Syntax (20 файлов) → Tests (312) → SSH Deploy → Telegram notify
Deploy: git fetch && git reset --hard origin/main → backup DB → docker compose build --no-cache → down || true → up -d
SSH-ключ: хранить в instance metadata GCP (не project metadata) — google-guest-agent перезаписывает authorized_keys
```
