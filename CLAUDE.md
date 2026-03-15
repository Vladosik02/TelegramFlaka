# Memory

## Me
Vladislav (Vlad), 23 года, разработчик персонального Telegram-бота-тренера.
Цель: набрать массу. Тренируется дома. Рост 178 см.

## Projects
| Name | What | Status |
|------|------|--------|
| **Trainer Bot** | Telegram-бот личный тренер «Алекс» (MAX/LIGHT режимы, AI на Anthropic API) | 🟢 Продакшн на Google Cloud VM |
| **Фаза 7** | Beyond MVP: питание, exercise_results, онбординг, БД v2 | ✅ Закрыта |
| **Фаза 8** | Analytics, Plans & Proactive AI | ✅ Закрыта |
| **Фаза 9** | Post-MVP Polish: NLP-парсеры, онбординг, /meal, история планов | ✅ Закрыта |
| **Фаза 10** | Intelligent Agent & Gamification: Claude Tool Use, Vision, XP/ачивки, память | ✅ Закрыта |
| **Фаза 11** | UX/UI Polish: /menu, inline keyboards, callback routing | ✅ Закрыта |
| **Фаза 12** | Advanced Analytics: charts (12.1), periodization (12.2), recovery score (12.3) | ✅ Закрыта |
| **Agent Fix** | Починка Tool Use: system prompt, L0-контекст, read-tools, regex отключены | ✅ Выполнено |
| **Фаза 13** | Guided Workout Flow, UX-навигация, notification fix, in-chat debug | ✅ Закрыта |
| **Фаза 14** | Infrastructure & Bug Fixes: silent exceptions, input validation, upsert, cleanup | ✅ Закрыта |
| **Фаза 15** | Plan sync, progressive overload hints, /today dashboard, quick meal presets | ✅ Закрыта |
| **Фаза 16** | Smoke tests, chart buttons в /stats, weekly digest в чат, streak protection | ✅ Закрыта |

→ Детали: memory/projects/

## Stack
- Python 3.11 + python-telegram-bot 20.x
- Anthropic API (Claude Sonnet 4) — MODEL: claude-sonnet-4-20250514
- SQLite WAL (`data/flaka.db`) — 26 таблиц, 4-layer memory
- APScheduler (AsyncIOScheduler)
- Docker (multi-stage, non-root, 256MB limit)
- Google Cloud VM (SSH, Linux) — продакшн
- GitHub: github.com/Vladosik02/TelegramFlaka
- GitHub Actions CI/CD

## Architecture — Ключевые файлы
| Файл | Назначение |
|------|------------|
| `main.py` | Точка входа, регистрация всех handlers и commands |
| `config.py` | MODEL, MAX_TOKENS=1500, пути, расписание, режим MAX/LIGHT. Startup validation: ValueError если TOKEN/KEY не заданы |
| `ai/client.py` | `generate_agent_response()` — агентный цикл с Tool Use (5 итераций max). Детектирует пропущенные tool calls, уведомляет через bot/debug.py |
| `ai/tools.py` | 13 tools: 8 write + 5 read. `ALL_TOOLS` экспорт |
| `ai/tool_executor.py` | `execute_tool()` — dispatch по имени → handler → DB query. Валидация входных полей, structured logging, уведомление через `notify_tool_result()` при success=False |
| `ai/context_builder.py` | 4-слойный контекст (L0-L4), теги, `build_layered_context()`. Фаза 13.7: добавляет блок `⚡ ДЕЙСТВИЯ ДЛЯ ЭТОГО СООБЩЕНИЯ` на основе тегов |
| `ai/prompts/system_max.txt` | Промпт MAX-режима + Tool Use инструкции + ОБЯЗАТЕЛЬНЫЕ ПАТТЕРНЫ (еда/тренировка/метрики/эпизоды) |
| `ai/prompts/system_light.txt` | Промпт LIGHT-режима (аналогично MAX) |
| `bot/handlers.py` | `handle_message()`, `handle_callback()`. Callback prefixes: `wf:` (guided flow), `menu:`, `morning_ready`, `morning_later`, `workout_done`, `stop:`, `reset:`, `adm:`, онбординг, фитнес-тест |
| `bot/commands.py` | cmd_start (очищает user_data), cmd_menu, cmd_stats, cmd_profile, cmd_plan и т.д. |
| `bot/keyboards.py` | Все inline keyboards включая: kb_main_menu (9 кнопок + 🗓 Календарь), kb_workout_duration/rpe/feeling/comment (guided flow) |
| `bot/debug.py` | In-chat уведомления об ошибках: `notify_error()`, `notify_tool_result()`, `notify_api_error()`, `notify_no_tools_called()`. Контролируется `DEBUG_NOTIFY_ENABLED` |
| `scheduler/jobs.py` | Регистрация всех APScheduler задач |
| `scheduler/logic.py` | Логика scheduled messages + `send_pre_workout_reminder()` + `cleanup_old_checkins()` |
| `scheduler/nudges.py` | Проактивные нудж-сообщения по паттернам |
| `scheduler/periodization.py` | `advance_all_mesocycles()` — воскресенье 21:15 |
| `db/schema.sql` | 26 таблиц, 19+ индексов |
| `db/connection.py` | Singleton SQLite connection, WAL mode, timeout=10 |
| `db/queries/workouts.py` | `log_metrics()` — upsert (SELECT-first, не создаёт дубли при retry) |
| `db/queries/nutrition.py` | `log_nutrition_day()` — upsert (SELECT-first) |
| `db/queries/training_plan.py` | CRUD тренировочного плана (draft → active → archived) |
| `db/queries/*.py` | user, workouts, memory, exercises, gamification, episodic, recovery, periodization, training_plan и др. |
| `analytics/charts.py` | 6 типов matplotlib графиков (headless Agg) |

## Tool Use — 13 инструментов
**WRITE (8):** save_workout, save_metrics, save_nutrition, save_exercise_result, set_personal_record, update_athlete_card, save_episode, award_xp
**READ (5):** get_weekly_stats, get_nutrition_history, get_personal_records, get_current_plan, get_user_profile

Все write-инструменты имеют:
- Валидацию обязательных полей (возвращают `{"error": "...", "success": False}` при отсутствии)
- Structured logging через `logger.info/warning`
- Уведомление пользователя в чат при `success: False` (через `bot/debug.py`)

## Callback Routing — handle_callback()
Порядок обработки в `bot/handlers.py`:
1. **Онбординг:** `goal_*`, `level_*`, `health_*`, `time_*`, `location_*`, `days_*`
2. **Утренний flow:** `morning_ready` → показывает тренировку дня из плана; `morning_later` → отклонение
3. **Workout flow:** `workout_done` → инициализирует guided flow; `workout_pending/skipped`; `wf:*` (dur/rpe/feel/comment)
4. **Напоминания:** `reminder_go`, `reminder_snooze` (snooze +30 мин), `reminder_skip`
5. **Метрики:** `intensity_*`, `energy_*`, `evening_ack`
6. **Меню:** `menu:*` → `_handle_menu_callback()` (stats/plan/calendar/history/achievements/profile/test/setup/export/home)
7. **Система:** `reset:*`, `stop:*`, `adm:*`

## Guided Workout Flow (Фаза 13.2)
State machine через `ctx.user_data["workout_flow"]`. Запускается при `workout_done`.
```
workout_done → инициализация wf{type, label, exercises из плана}
  → wf:dur:{20/30/45/60/75/90/custom} — длительность
  → wf:rpe:{1-10}                     — интенсивность (RPE)
  → wf:feel:{great/ok/hard/pain}      — ощущения
  → wf:comment:{skip/текст}           — комментарий
  → _save_workout_from_flow() → log_workout() + award_xp(100) + save_episode()
```
`awaiting_custom_duration` — флаг ожидания числового ввода в `handle_message()`.

## Scheduler — расписание
| Job ID | Время | Функция |
|--------|-------|---------|
| morning_checkin | config (MAX_MORNING) | `send_morning_checkin()` + agent Tool Use |
| afternoon_checkin | config (MAX_AFTERNOON) | `send_afternoon_checkin()` + agent Tool Use |
| evening_checkin | config (MAX_EVENING) | `send_evening_checkin()` + agent Tool Use |
| pre_workout_morning | 08:30 | `broadcast_pre_workout_morning()` — morning+flexible тренеры |
| pre_workout_evening | 19:30 | `broadcast_pre_workout_evening()` — evening тренеры |
| reminder_checker | каждые 15 мин | `check_and_send_reminders()` |
| nudge_checker | 08:00 | `check_and_send_nudges()` |
| daily_summary | 23:00 | AI-сводка дня |
| weekly_report | вс 21:00 | `send_weekly_report()` |
| mesocycle_advance | вс 21:15 | `advance_all_mesocycles()` |
| l4_intelligence | вс 21:30 | L4 дайджест (только запись в БД, без отправки) |
| plan_archive | вс 19:00 | Архивация активного плана |
| plan_generate | вс 20:00 | Генерация нового плана AI + отправка пользователю |
| monthly_summary | 1-е число 09:00 | AI-резюме прошедшего месяца |
| monthly_backup | 1-е число | `run_backup()` (если backup.py есть) |
| checkins_cleanup | вс 22:00 | `cleanup_old_checkins()` — удаление записей > 90 дней |
| streak_protection | 20:00 ежедн | `broadcast_streak_protection()` — предупреждение если стрик ≥3 и нет тренировки сегодня |

## Terms
| Term | Meaning |
|------|---------|
| MAX / LIGHT | Два режима бота: MAX — нечётные дни, LIGHT — чётные дни |
| Алекс | Имя AI-персонажа бота |
| L0–L4 | Слои памяти: L0=карточка, L1=здоровье, L2=питание, L3=тренировки, L4=AI-аналитика |
| context_builder | `ai/context_builder.py` — сборка 4-слойного контекста + action hints по тегам |
| agent loop | Цикл: user msg → Claude → tool_use → execute → Claude → final response (max 5 iter) |
| tool use | Claude Tool Use API — 13 инструментов для read/write БД |
| guided_workout_flow | 4-шаговый flow записи тренировки через inline кнопки (wf: prefix) |
| action hints | Блок `⚡ ДЕЙСТВИЯ ДЛЯ ЭТОГО СООБЩЕНИЯ` в system prompt — конкретные tool-инструкции на основе тегов сообщения |
| in-chat debug | `bot/debug.py` — отправка технических ошибок прямо в Telegram-чат |
| XP | Experience Points: тренировка=100, PR=200, стрик 7д=150, 30д=500 |
| PR | Personal Record (личный рекорд упражнения) |
| SCORE | Метрика упражнения: overload×0.4 + consistency×0.3 + alignment×0.3 |
| daily_summary | AI-сводка дня, генерируется через APScheduler (~23:00) |
| L4 Intelligence | Еженедельный AI-дайджест (вс 21:30) — только запись в БД |
| nudge | Проактивное сообщение по паттернам поведения |
| fitness_score | pushups×0.35 + squats×0.35 + plank×0.30 |
| recovery_score | sleep×0.35 + energy×0.30 + load×0.20 + consistency×0.15 |
| mesocycle | 7-недельный цикл: accumulation(3) → intensification(2) → realization(1) → deload(1) |
| /menu | Главное меню с 9 кнопками: Статистика, План, 🗓 Календарь, Хроника, Ачивки, Профиль, Фитнес-тест, Настройки, Экспорт |
| /plan | Показ плана тренировок на неделю |
| /today | Дашборд текущего дня: питание vs цели (прогресс-бар) + статус тренировки + quick meal кнопки |
| upsert | `log_metrics` и `log_nutrition_day` — SELECT-first, UPDATE если запись за день есть, INSERT иначе |
| quick_meal | Пресеты частых приёмов пищи (callback `meal:*`) — накопительное логирование в 1 тап |
| overload_hints | `_build_overload_hints()` — сравнивает plan target с последним exercise_result, предлагает +2.5кг |
| mark_plan_day_completed | `db/queries/training_plan.py` — патчит plan_json (completed=true) после записи тренировки |
| streak_protection | `broadcast_streak_protection()` — ежедневно 20:00, предупреждает если стрик ≥3 и нет тренировки сегодня |
| chart callbacks | `chart:weight`, `chart:strength` — кнопки в kb_stats_quick(), обрабатываются `_handle_chart_callback()` |
| weekly_digest | L4 поле `memory_intelligence.weekly_digest` — теперь отправляется пользователю вс 21:30 вместе с L4 апдейтом |

## Key Notion Pages
| Page | URL |
|------|-----|
| ROADMAP | https://www.notion.so/31c8fb7a86e3812a8e20d04186ebebe9 |
| Фаза 10 — Intelligent Agent | https://www.notion.so/3228fb7a86e381508759f0e16e62b41e |

## Current Issues
Нет открытых известных багов. Последние исправления — Фаза 13+14 (2026-03-15).

Если появятся новые баги — бот сам уведомит в чат через `bot/debug.py` при:
- Ошибке любого tool call (`success: False`)
- Ошибке Anthropic API (4xx/5xx или connection error)
- Подозрении что AI пропустил обязательный tool call (паттерн в тексте без tool_use в истории)

## UX Preferences
- Запись тренировки: guided flow с кнопками (4 шага, минимум текста)
- Уведомления: утро (morning_ready → план дня) + перед тренировкой (08:30/19:30) + вечер
- Ошибки: все технические сбои видны прямо в чате, не нужно лезть в логи
