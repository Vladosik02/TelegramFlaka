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
| **Сессия 2026-03-17** | CI/CD, bug fixes, prompts rewrite, cost optimization, nutrition A/B/C, SSH fix | ✅ Закрыта |

→ Детали: memory/projects/

## Stack
- Python 3.11 + python-telegram-bot 20.7
- Anthropic API (Claude Sonnet 4) — MODEL: claude-sonnet-4-20250514
- MODEL_SCHEDULED: claude-haiku-4-5-20251001 (scheduled jobs, 4x дешевле)
- SQLite WAL (`data/trainer.db`) — 26 таблиц, 4-layer memory
- APScheduler (AsyncIOScheduler) — запускается в post_init
- Docker (multi-stage, non-root botuser uid=1001, 256MB limit)
- Google Cloud VM (SSH, Linux) — продакшн, путь /opt/trainer-bot
- GitHub: github.com/Vladosik02/TelegramFlaka
- GitHub Actions CI/CD (Syntax → Tests → Deploy via SSH)

## Architecture — Ключевые файлы
| Файл | Назначение |
|------|------------|
| `main.py` | Точка входа. `post_init` запускает scheduler + set_my_commands + set_chat_menu_button |
| `config.py` | MODEL, MODEL_SCHEDULED, MAX_TOKENS=3000, MAX_TOKENS_SCHEDULED=1500, пути, расписание |
| `ai/client.py` | `generate_agent_response()` — агентный цикл (5 iter). `_cached_system()` — prompt caching. Scheduled jobs используют MODEL_SCHEDULED + MAX_TOKENS_SCHEDULED |
| `ai/tools.py` | 13 tools: 8 write + 5 read. `ALL_TOOLS` экспорт |
| `ai/tool_executor.py` | `execute_tool()` — dispatch, валидация, logging, notify при success=False |
| `ai/context_builder.py` | 4-слойный контекст (L0-L4), теги, action hints. История: limit=5 |
| `ai/prompts/system_max.txt` | Переписан: ХАРАКТЕР (прямой/с юмором), ФОРМАТ (2-3 предл, без markdown), НАУКА (гипертрофия, белок), АВТОЗАПИСЬ, анти-галлюцинация |
| `ai/prompts/system_light.txt` | Переписан: тот же каркас, тёплый тон |
| `bot/handlers.py` | `handle_message()`, `handle_callback()`. menu:home — fallback reply_text для фото-сообщений |
| `bot/commands.py` | cmd_start, cmd_menu, cmd_stats, cmd_profile, cmd_plan, cmd_today и др. |
| `bot/keyboards.py` | Все inline keyboards |
| `bot/debug.py` | notify_error, notify_tool_result, notify_api_error, notify_no_tools_called |
| `scheduler/jobs.py` | Регистрация всех APScheduler задач |
| `db/queries/workouts.py` | `log_workout()` — upsert (SELECT-first, нет дублей) |
| `db/queries/nutrition.py` | `log_nutrition_day()` — upsert |
| `Dockerfile` | Multi-stage. pip install БЕЗ --user → глобальные пакеты. botuser uid=1001 |
| `.github/workflows/deploy.yml` | Syntax → Tests (dummy env vars) → SSH deploy → Telegram notify |

## Tool Use — 13 инструментов
**WRITE (8):** save_workout, save_metrics, save_nutrition, save_exercise_result, set_personal_record, update_athlete_card, save_episode, award_xp
**READ (5):** get_weekly_stats, get_nutrition_history, get_personal_records, get_current_plan, get_user_profile

## Cost Optimization
| Что | Эффект |
|-----|--------|
| Prompt caching (`_cached_system()`) | ~40% экономии на input токенах |
| Haiku для scheduled jobs | ~30% экономии (4x дешевле Sonnet) |
| История переписки limit=5 (было 10) | Меньше токенов на контекст |
| Итого | ~2-2.5x дешевле vs baseline |

## CI/CD — GitHub Actions
```
push → Syntax Check → Run Tests (201 тест) → Deploy to VPS
```
- Secrets: SERVER_HOST, SERVER_USER (mrvald19), SSH_PRIVATE_KEY, SERVER_PORT (22)
- Deploy: git pull → backup DB → docker compose build --no-cache → down → up -d
- После деплоя: Telegram уведомление из .env на сервере
- Pytest использует dummy env vars (TELEGRAM_TOKEN=test_token_ci)

## Docker — важные детали
- `botuser` uid=1001, нет домашней папки
- Пакеты в `/usr/local/lib/python3.11/site-packages` (НЕ --user)
- Volumes: `./data:/app/data`, `./backups:/app/backups`
- Права на data/: `sudo chown -R 1001:1001 /opt/trainer-bot/data`
- Права на backups/: `sudo chown -R 1001:1001 /opt/trainer-bot/backups`

## Scheduler — запуск
AsyncIOScheduler запускается в `post_init(application)` — после старта event loop.
`app.bot_data["scheduler"]` — доступ из handlers (snooze).
`scheduler.shutdown()` — в finally блоке main().

## Scheduler — расписание
| Job ID | Время | Функция |
|--------|-------|---------|
| morning_checkin | config (MAX_MORNING=09:00) | `send_morning_checkin()` + Haiku Tool Use |
| afternoon_checkin | config (MAX_AFTERNOON=12:30) | `send_afternoon_checkin()` + Haiku Tool Use |
| evening_checkin | config (MAX_EVENING=20:00) | `send_evening_checkin()` + Haiku Tool Use |
| pre_workout_morning | 08:30 | `broadcast_pre_workout_morning()` |
| pre_workout_evening | 19:30 | `broadcast_pre_workout_evening()` |
| reminder_checker | каждые 15 мин | `check_and_send_reminders()` |
| nudge_checker | 08:00 | `check_and_send_nudges()` |
| daily_summary | 23:00 | AI-сводка дня |
| weekly_report | вс 21:00 | `send_weekly_report()` |
| mesocycle_advance | вс 21:15 | `advance_all_mesocycles()` |
| l4_intelligence | вс 21:30 | L4 дайджест |
| plan_archive | вс 19:00 | Архивация плана |
| plan_generate | вс 20:00 | Генерация плана AI |
| monthly_summary | 1-е число 09:00 | AI-резюме месяца |
| checkins_cleanup | вс 22:00 | `cleanup_old_checkins()` |
| streak_protection | 20:00 ежедн | `broadcast_streak_protection()` |
| nutrition_analysis | 21:45 ежедн | `run_nutrition_analysis()` — паттерны питания |

## Multi-user
Все 26 таблиц БД изолированы по `user_id` (Telegram ID). Новый пользователь → /start → онбординг. QUICK_MEAL_PRESETS — глобальные (одинаковые для всех, можно сделать персональными).

## Terms
| Term | Meaning |
|------|---------|
| MAX / LIGHT | Два режима: MAX — нечётные дни, LIGHT — чётные |
| Алекс | Имя AI-персонажа бота |
| L0–L4 | Слои памяти: L0=карточка, L1=здоровье, L2=питание, L3=тренировки, L4=AI-аналитика |
| agent loop | user msg → Claude → tool_use → execute → Claude → final (max 5 iter) |
| guided_workout_flow | 4-шаговый flow: wf:dur → wf:rpe → wf:feel → wf:comment |
| action hints | `⚡ ДЕЙСТВИЯ ДЛЯ ЭТОГО СООБЩЕНИЯ` — конкретные tool-инструкции по тегам |
| prompt caching | `_cached_system()` в client.py — system prompt за 10% цены |
| upsert | SELECT-first pattern: log_workout, log_metrics, log_nutrition_day |
| hallucination detector | Детектирует «записал» в тексте без реального tool_use вызова |
| AUTORECORD | Бот автоматически записывает ответы на свои вопросы (energy/sleep) |

## Key Notion Pages
| Page | URL |
|------|-----|
| ROADMAP | https://www.notion.so/31c8fb7a86e3812a8e20d04186ebebe9 |

## CI/CD — Известные грабли (выучено болью)

### SSH-ключ на GCP VM
**Проблема:** `google-guest-agent` периодически перезаписывает `~/.ssh/authorized_keys` из instance metadata. Ключ, добавленный напрямую в файл, пропадает после синхронизации.
**Постоянное решение:** ключ должен быть в **instance metadata** (не project metadata):
- GCP Console → Compute Engine → VM → Edit → SSH Keys → Add item
- ИЛИ: `gcloud compute instances add-metadata INSTANCE --metadata ssh-keys="mrvald19:KEY" --zone ZONE`
- `gcloud compute project-info add-metadata` — требует `roles/owner`, у нас нет. Не использовать.
- `gcloud auth login --enable-gdrive-access` — если gcloud ругается на scopes
**Текущий ключ в GitHub Secrets:** `deploy_key` (ed25519, создан 2026-03-17, комментарий `github-actions-deploy`)
**Публичный ключ:** `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILiwi9FQ26lou4YSF82VCzzDrfiittp+isV84N1gtSUj`

### deploy.yml — правильные параметры appleboy/ssh-action@v1.0.3
- ✅ `timeout:` — таймаут соединения (НЕ `connect_timeout:` — его нет в v1.0.3)
- ✅ `command_timeout:` — таймаут выполнения скрипта
- ✅ `git fetch origin && git reset --hard origin/main` — вместо `git pull` (не падает на divergent branches)
- ✅ `docker compose down || true` — не падает если контейнер уже остановлен
- ✅ `docker compose logs --tail=20 || true` — не убивает деплой в конце
- ✅ `continue-on-error: true` на notify-шагах — SSH-хик при уведомлении не ломает статус деплоя

### Права на backups/
`backups/` принадлежит `botuser` (uid=1001, Docker). Деплой-скрипт запускается от `mrvald19`.
Постоянный фикс: `sudo chown -R mrvald19:mrvald19 /opt/trainer-bot/backups` на сервере.
В deploy.yml: `sudo chown -R "$(id -u):$(id -g)" backups/ 2>/dev/null || true` перед cp.

### pytest без env vars
`config.py` падает при импорте если `TELEGRAM_TOKEN`/`ANTHROPIC_API_KEY` не заданы.
Фикс в `tests/conftest.py` — первые строки файла (до любых imports):
```python
import os
if not os.environ.get("TELEGRAM_TOKEN"): os.environ["TELEGRAM_TOKEN"] = "test_token_ci"
if not os.environ.get("ANTHROPIC_API_KEY"): os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
```
Используем `if not get()` а не `setdefault` — потому что переменная может быть в env как пустая строка.

## Current Issues
Нет открытых известных багов. Бот работает на продакшне (2026-03-17).

## UX
- Кнопка меню в чате: MenuButtonCommands() + 10 команд через set_my_commands()
- Запись тренировки: guided flow (4 шага, кнопки)
- Ошибки: in-chat через bot/debug.py
- Деплой: Telegram уведомление автоматически
