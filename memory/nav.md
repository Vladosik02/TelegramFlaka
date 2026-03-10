# 🗺️ Навигация по проекту TelegramFlaka

> GitHub: github.com/Vladosik02/TelegramFlaka
> Прод: Google Cloud VM (SSH, Linux)
> БД: data/flaka.db (SQLite)

---

## Структура директорий

```
TelegramFlaka/
├── main.py                     ← точка входа, регистрация handlers + scheduler
├── config.py                   ← все константы: токены, расписание, пути, MODEL
│
├── ai/
│   ├── client.py               ← Anthropic API: generate_chat_response_streaming, generate_scheduled_message
│   ├── context_builder.py      ← 4-слойный контекст (L0–L4) + _build_daily_chronicle()
│   ├── response_parser.py      ← парсеры: parse_workout, parse_metrics, parse_nutrition, parse_exercises
│   └── prompts/
│       ├── system_max.txt      ← системный промпт MAX-режима
│       ├── system_light.txt    ← системный промпт LIGHT-режима
│       ├── morning_checkin.txt
│       ├── afternoon_checkin.txt
│       └── evening_checkin.txt
│
├── bot/
│   ├── commands.py             ← /start, /stop, /stats, /mode, /help, /reset, /profile, /export
│   ├── handlers.py             ← handle_message (диалог + онбординг state machine), handle_callback
│   └── keyboards.py            ← inline-кнопки (утро/день/вечер/snooze)
│
├── db/
│   ├── connection.py           ← get_connection() — singleton SQLite
│   ├── schema.sql              ← CREATE TABLE IF NOT EXISTS (все таблицы)
│   ├── writer.py               ← единая точка записи AI-ответов в БД
│   └── queries/
│       ├── user.py             ← get_user, create_user, update_user
│       ├── workouts.py         ← log_workout, get_streak, get_weekly_stats, log_metrics, get_metrics_range
│       ├── context.py          ← get/update checkin, conversation history, get_last_message_time
│       ├── stats.py            ← save_weekly_summary, get_last_n_weeks, get_all_time_stats
│       ├── memory.py           ← L0–L4 CRUD: get_l0_surface, upsert_athlete, get_l4_intelligence...
│       ├── nutrition.py        ← log_nutrition_day, get_nutrition_log, add_nutrition_insight
│       ├── exercises.py        ← log_exercise_result, get_exercise_history, personal_records
│       └── daily_summary.py    ← upsert_daily_summary, get_daily_summaries, get_last_summary
│
├── scheduler/
│   ├── jobs.py                 ← setup_scheduler() — регистрирует все cron-задачи в APScheduler
│   └── logic.py                ← broadcast_morning/afternoon/evening/weekly/l4/daily_summary
│                                  + generate_daily_summary_for_user, update_l4_for_user
│
├── data/
│   └── flaka.db                ← продакшн БД
│
├── backups/                    ← авто-бэкапы (1-е число месяца, 03:00)
│
└── deploy/
    ├── Dockerfile
    ├── docker-compose.yml
    ├── deploy.sh
    ├── server-setup.sh
    ├── flaka-bot.service       ← systemd unit
    ├── DEPLOY.md
    └── GCP_SYSTEMD_DEPLOY.md
```

---

## Где что менять — быстрая шпаргалка

| Задача | Файл(ы) |
|--------|---------|
| Добавить команду бота | `bot/commands.py` + зарегистрировать в `main.py` |
| Добавить обработчик кнопки | `bot/handlers.py` → `handle_callback`, `bot/keyboards.py` |
| Добавить новую таблицу | `db/schema.sql` + `db/queries/<module>.py` |
| Добавить AI-слой в контекст | `ai/context_builder.py` → `build_layered_context()` |
| Добавить scheduled job | `scheduler/logic.py` (логика) → `scheduler/jobs.py` (регистрация) + `config.py` (время) |
| Изменить промпт | `ai/prompts/*.txt` |
| Изменить расписание чек-инов | `config.py` → SCHEDULE_MAX_* |
| Изменить AI-модель | `config.py` → MODEL |
| Добавить новый парсер | `ai/response_parser.py` |
| Добавить запись от AI в БД | `db/writer.py` |

---

## Scheduler jobs — все задачи

| Job ID | Когда | Функция | Файл |
|--------|-------|---------|------|
| `morning_checkin` | 09:00 ежедн. | `broadcast_morning` | logic.py |
| `afternoon_checkin` | 12:30 ежедн. | `broadcast_afternoon` | logic.py |
| `evening_checkin` | 20:00 ежедн. | `broadcast_evening` | logic.py |
| `reminder_checker` | каждые 15 мин | `check_and_send_reminders` | logic.py |
| `weekly_report` | вс 21:00 | `broadcast_weekly` | logic.py |
| `l4_intelligence` | вс 21:30 | `broadcast_l4_intelligence` | logic.py |
| `daily_summary` | 23:00 ежедн. | `broadcast_daily_summary` | logic.py |
| `monthly_backup` | 1-е число 03:00 | `run_backup` | backup.py |
| `monthly_summary` *(Ф8.1)* | 1-е число 09:00 | `broadcast_monthly_summary` | logic.py |

---

## Паттерн добавления нового scheduled job

```
1. config.py           → добавить MONTHLY_XXX_TIME = "09:00"
2. db/schema.sql       → CREATE TABLE IF NOT EXISTS xxx (...)
3. db/queries/xxx.py   → CRUD (upsert, get, get_last)
4. scheduler/logic.py  → _SYSTEM, _PROMPT, _parse_response()
                          generate_xxx_for_user(uid, telegram_id)
                          broadcast_xxx()
5. scheduler/jobs.py   → import broadcast_xxx, MONTHLY_XXX_TIME
                          scheduler.add_job(broadcast_xxx, "cron", day=1, ...)
6. ai/context_builder.py → (опц.) _build_xxx_chronicle() + подключить в build_layered_context()
```

---

## Поток данных AI-диалога

```
Пользователь → handlers.py
  → build_layered_context(telegram_id, text)   [context_builder.py]
  → Anthropic API                              [client.py]
  → response_parser.py                         (parse_workout / metrics / nutrition / exercises)
  → writer.py                                  (save в БД)
  → ответ пользователю
```

---

## config.py — ключевые константы

| Константа | Значение | Назначение |
|-----------|----------|-----------|
| `MODEL` | `claude-sonnet-4-20250514` | AI модель |
| `MAX_TOKENS` | 1000 | лимит ответа AI |
| `DB_PATH` | `data/trainer.db` | путь к БД |
| `DAILY_SUMMARY_TIME` | `"23:00"` | ночное резюме |
| `WEEKLY_SUMMARY_DAY` | 6 | воскресенье |
| `MONTHLY_BACKUP_TIME` | `"03:00"` | бэкап |
| `SILENCE_AFTER_DAYS` | 7 | молчать если игнор |
| `STOP_MAX_DAYS` | 30 | макс. пауза /stop |

---

## Онбординг state machine (handlers.py)

```
/start → кнопка цели → кнопка уровня
  → awaiting_age     → awaiting_weight → awaiting_height → awaiting_workout_time
  → upsert_athlete_card() в memory_athlete
```

---

*Обновлено: 10.03.2026*
