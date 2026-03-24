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
| **Фаза 17** | Tiered context (CRUD vs FULL), filtered tools, cost optimization ~40-50× на CRUD | ✅ Закрыта |
| **Сессия 2026-03-24** | Stale metrics fix, CLAUDE.md rewrite, deploy.yml syntax coverage | ✅ Закрыта |

→ Детали: memory/projects/

## Stack
- Python 3.11 + python-telegram-bot 20.7
- Anthropic API (Claude Sonnet 4) — MODEL: `claude-sonnet-4-20250514`
- MODEL_SCHEDULED: `claude-haiku-4-5-20251001` (scheduled jobs, 4× дешевле)
- SQLite WAL (`data/trainer.db`) — 26 таблиц, 4-layer memory
- APScheduler (AsyncIOScheduler) — запускается в `post_init`
- Docker (multi-stage, non-root botuser uid=1001, 256MB limit)
- Google Cloud VM (SSH, Linux) — продакшн, путь `/opt/trainer-bot`
- GitHub: github.com/Vladosik02/TelegramFlaka
- GitHub Actions CI/CD (Syntax → Tests → Deploy via SSH)

## Architecture — Ключевые файлы

| Файл | Назначение |
|------|------------|
| `main.py` | Точка входа. `post_init` запускает scheduler + set_my_commands + set_chat_menu_button |
| `config.py` | MODEL, MODEL_SCHEDULED, MAX_TOKENS=3000, MAX_TOKENS_SCHEDULED=1500, пути, расписание |
| `ai/client.py` | `generate_agent_response()` — агентный цикл (5 iter). `_cached_system()` — prompt caching. Tiered dispatch: CRUD vs FULL по тегам контекста |
| `ai/tools.py` | 15 tools: 9 write + 6 read. `ALL_TOOLS` и `CRUD_TOOLS` экспорт |
| `ai/tool_executor.py` | `execute_tool()` — dispatch, валидация, logging, notify при success=False |
| `ai/context_builder.py` | 4-слойный контекст (L0-L4), теги, action hints. CRUD tier: 3 history, FULL tier: 10 history. **Stale metrics fix**: "Статус сегодня" блок с явной давностью |
| `ai/prompts/system_max.txt` | Переписан: ХАРАКТЕР (прямой/с юмором), ФОРМАТ (2-3 предл, без markdown), НАУКА (гипертрофия, белок), АВТОЗАПИСЬ, анти-галлюцинация |
| `ai/prompts/system_light.txt` | Переписан: тот же каркас, тёплый тон |
| `bot/handlers.py` | `handle_message()`, `handle_callback()`. menu:home — fallback reply_text для фото-сообщений |
| `bot/commands.py` | cmd_start, cmd_menu, cmd_stats, cmd_profile, cmd_plan, cmd_today и др. |
| `bot/keyboards.py` | Все inline keyboards |
| `bot/debug.py` | notify_error, notify_tool_result, notify_api_error, notify_no_tools_called |
| `scheduler/jobs.py` | Регистрация всех APScheduler задач (17 jobs) |
| `scheduler/logic.py` | Утро/день/вечер чек-ины, weekly report, snooze, pre-workout reminders |
| `scheduler/nudges.py` | 6 типов мотивационных нуджей (без API) |
| `scheduler/prediction.py` | Workout Prediction: прогноз весов/повторов/RPE на основе exercise_results + recovery + мезоцикл |
| `scheduler/adaptation.py` | Adaptive Session Modifier: DELOAD/LIGHT/BOOST/NORMAL по recovery+sleep+energy+phase |
| `scheduler/periodization.py` | Еженедельное продвижение фаз мезоцикла |
| `scheduler/personal_insights.py` | Rule-based корреляции (сон→интенсивность, белок→интенсивность, отдых→интенсивность). Окно 60 дней, min 5 наблюдений, min эффект 8% |
| `scheduler/teach_moments.py` | Контекстные мини-уроки без API: 8+ категорий, ~3×/неделю, детерминированный выбор |
| `scheduler/nutrition_analysis.py` | 7 типов инсайтов питания с cooldown. Сохраняет в `nutrition_insights`, шлёт critical/warning |
| `db/queries/workouts.py` | `log_workout()` — upsert (SELECT-first, нет дублей) |
| `db/queries/nutrition.py` | `log_nutrition_day()` — upsert |
| `Dockerfile` | Multi-stage. pip install БЕЗ --user → глобальные пакеты. botuser uid=1001 |
| `.github/workflows/deploy.yml` | Syntax (20 файлов) → Tests (312 тестов) → SSH deploy → Telegram notify |

---

## Tool Use — 15 инструментов

**WRITE (9):**

| Инструмент | Что делает |
|-----------|-----------|
| `save_workout` | Записывает тренировку (тип, длительность, интенсивность, RPE, feel, комментарий) |
| `save_metrics` | Сохраняет метрики дня (сон, энергия, настроение, вес, пульс покоя) |
| `save_nutrition` | Дневной агрегат питания (калории, белок, жиры, углеводы, вода, junk_food) |
| `save_exercise_result` | Результат одного упражнения (подходы, повторы, вес, RPE, заметки) |
| `set_personal_record` | Фиксирует новый личный рекорд с датой и контекстом |
| `update_athlete_card` | Обновляет любое поле профиля пользователя (L0-L3 memory) |
| `save_episode` | Записывает значимый момент в эпизодическую память (importance 1-5) |
| `award_xp` | Начисляет XP за произвольное действие с описанием |
| `save_training_plan` | Сохраняет недельный план тренировок в JSON (exercises, sets, reps, weight_targets) |

**READ (6):**

| Инструмент | Что возвращает |
|-----------|---------------|
| `get_weekly_stats` | Статистика за неделю: тренировки, интенсивность, питание, метрики |
| `get_nutrition_history` | История питания за N дней |
| `get_personal_records` | Все личные рекорды пользователя |
| `get_current_plan` | Активный план тренировок на текущую неделю |
| `get_user_profile` | Полный профиль: L0-L4 память + последние данные |
| `get_workout_prediction` | Прогноз на сегодняшнюю тренировку (prediction.py) |

**При добавлении нового tool: обновить ВСЕ ТРИ места: `tools.py`, `tool_executor.py`, system prompts.**

---

## Tiered Context System (Фаза 17)

Каждое входящее сообщение классифицируется context_builder'ом по тегам:

| Tier | Когда | Модель | История | Tools | Токены |
|------|-------|--------|---------|-------|--------|
| **CRUD** | Тег `[WORKOUT]`, `[NUTRITION]`, `[METRICS]` — короткие CRUD-запросы | Haiku | 3 сообщения | 2-5 filtered tools | ~800-1200 |
| **FULL** | Тег `[CHAT]`, `[PLAN]`, `[ANALYSIS]` — диалог, сложные запросы | Sonnet | 10 сообщений | ALL_TOOLS (15) | ~3000-5000 |

**Scheduled jobs** всегда используют Haiku + MAX_TOKENS_SCHEDULED=1500.

Экономия: CRUD-запросы ~40-50× дешевле Sonnet+10hist baseline.

---

## 4-слойная память (L0-L4)

Загружается через `context_builder.py`, хранится в `db/queries/memory.py`.

| Слой | Таблица | Токены | Всегда? | Содержимое |
|------|---------|--------|---------|------------|
| **L0** Surface | `memory_athlete` | ~160 | ✅ | Имя, цель, возраст, рост, вес, season, стрик, active_days, timezone |
| **L1** Deep Bio | `memory_athlete` | ~150 | При health-контексте | Травмы, непереносимости, добавки, медзаметки |
| **L2** Nutrition | `memory_nutrition` | ~200 | При food-контексте | КБЖУ-цель, тайминг, ограничения, добавки |
| **L3** Training | `memory_training` | ~250 | При training-контексте | Предпочтения, preferred_days/time, equipment, **exercise_scores** (JSON per exercise) |
| **L4** AI Intelligence | `memory_intelligence` | ~200 | ✅ | weekly_digest (AI-текст), observations (последние 10), trend_summary |

**exercise_scores** в L3: `score = 0.4×overload + 0.3×consistency + 0.3×alignment`. Накапливается по каждому упражнению в плане.

**L4 observations**: `append_observation()` держит ровно 10 записей — старые вытесняются.

**Обновление L4**: еженедельно (вс 21:30) через `broadcast_l4_intelligence()` с Haiku.

### Stale Metrics Fix (2026-03-24)

`_build_l0_card()` в `context_builder.py` показывает метрики с явной давностью:
- `"Метрики сегодня (24.03): сон 7ч, энергия 4/5"` — если запись за сегодня
- `"Метрики вчера (23.03): ..."` — за вчера
- `"Метрики (3 дн. назад, 21.03): ..."` — за более ранние дни
- Блок `"Статус сегодня (24.03): не записано: сон, энергия"` — **всегда присутствует**, даёт AI сигнал что нужно спросить

Вес выводится отдельно с датой (медленный показатель). Сон/энергия/настроение — с явной давностью.

---

## Scheduler — 17 задач

| Job ID | Время | Функция | API? |
|--------|-------|---------|------|
| `morning_checkin` | 09:00 (MAX) | Утренний чек-ин + Haiku Tool Use | Haiku |
| `afternoon_checkin` | 12:30 (MAX) | Дневной чек-ин + Haiku Tool Use | Haiku |
| `evening_checkin` | 20:00 (MAX) | Вечерний чек-ин + Haiku Tool Use | Haiku |
| `pre_workout_morning` | 08:30 | Pre-workout reminder + prediction + adaptation | нет |
| `pre_workout_evening` | 19:30 | Pre-workout reminder + prediction + adaptation | нет |
| `reminder_checker` | каждые 15 мин | Проверка scheduled reminders | нет |
| `nudge_checker` | 08:00 | 6 типов нуджей (drop, sleep, streak_risk и др.) | нет |
| `daily_summary` | 23:00 | AI-сводка дня + teach_moment | Haiku |
| `weekly_report` | вс 21:00 | Недельный отчёт с графиками | Haiku |
| `mesocycle_advance` | вс 21:15 | Продвижение фаз мезоцикла | нет |
| `l4_intelligence` | вс 21:30 | L4 AI-дайджест + observations | Haiku |
| `personal_insights` | вс 20:45 | Rule-based корреляции (сон/белок/отдых→интенсивность) | нет |
| `plan_archive` | вс 19:00 | Архивация завершённого плана | нет |
| `plan_generate` | вс 20:00 | AI-генерация плана на неделю | Haiku |
| `monthly_summary` | 1-е число 09:00 | AI-резюме месяца | Haiku |
| `checkins_cleanup` | вс 22:00 | Удаление чек-инов старше 90 дней | нет |
| `streak_protection` | 20:00 ежедн | Напоминание если стрик под угрозой | нет |
| `nutrition_analysis` | 21:45 ежедн | 7 типов инсайтов питания → `nutrition_insights` | нет |

---

## AI-модули планировщика (без API-вызовов)

### `scheduler/prediction.py` — Workout Prediction
Вычисляет прогноз на текущую тренировку для каждого упражнения в плане.
- Читает `exercise_results` за последние 90 дней
- Анализирует тренд весов (growing/stable/declining по последним 3 результатам)
- Учитывает recovery score, фазу мезоцикла, сон/энергию
- Результат: конкретные sets/reps/weight_kg + reasoning + RPE-потолок
- Используется: в pre-workout reminder и через tool `get_workout_prediction`
- **Точность растёт с данными**: к месяцу уже 3-4 результата на каждое упражнение

### `scheduler/adaptation.py` — Adaptive Session Modifier
Модифицирует прогноз до начала тренировки на основе состояния дня:
- `DELOAD`: recovery < 40 **и** сон < 6ч → вес×0.6, −1 подход, RPE ≤ 6
- `LIGHT`: recovery < 50 **или** энергия ≤ 2 → держим вес, −1 подход, RPE ≤ 7
- `BOOST`: recovery ≥ 80 + энергия ≥ 4 + realization/intensification → +2.5 кг
- `NORMAL`: всё остальное → без изменений
- Кнопки в pre-workout сообщении: принять/отклонить адаптацию (`adapt:*` callbacks)

### `scheduler/personal_insights.py` — Rule-Based Correlations
Ищет самый сильный личный паттерн раз в неделю (воскресенье 20:45):
1. Сон ≥ 7.5ч → интенсивность следующей тренировки (JOIN metrics + workouts +1 day)
2. Белок ≥ 90% цели → интенсивность того же дня (JOIN nutrition_log + workouts)
3. 2+ дня отдыха → интенсивность выше чем 0-1 дня
- Порог: min 5 наблюдений в каждой группе, эффект ≥ 8%, приоритет: сон > белок > отдых
- **Не хранится в БД** — вычисляется заново каждую неделю и отправляется в чат

### `scheduler/teach_moments.py` — Contextual Mini-Lessons
8 категорий, выбор по контексту дня, без API, без хранения:
`AFTER_STRENGTH` / `AFTER_CARDIO` / `NO_WORKOUT` / `LOW_PROTEIN` / `LOW_CALORIES` / `LOW_SLEEP` / `GOOD_SLEEP` / `HIGH_ENERGY` / `LOW_ENERGY` / `HYPERTROPHY_GENERAL`
- Частота: ~3×/неделю (пн+ср+пт + всегда после завершённой тренировки)
- Детерминированный выбор: `md5(user_id:date:salt)` — стабильный в течение дня
- **Не хранится** — нет защиты от повторов через несколько недель

### `scheduler/nutrition_analysis.py` — Nutrition Pattern Detector
7 типов инсайтов, анализ за 7 дней, cooldown на каждый тип:

| Тип | Условие | Cooldown |
|-----|---------|----------|
| `protein_deficit` | Белок < 80% цели ≥3 дней | 3 дня |
| `calorie_deficit` | Калории < 75% цели ≥3 дней | 3 дня |
| `calorie_surplus` | Калории > 120% цели ≥4 дней | 5 дней |
| `dehydration` | Вода < 1500 мл ≥3 дней | 4 дня |
| `junk_food_streak` | Читмил 3+ дней подряд | 3 дня |
| `no_logging` | 0 записей за 7 дней | 4 дня |
| `low_protein_today` | Сегодня белок < 70% цели | 2 дня |

Сохраняет в `nutrition_insights` (таблица). Отправляет только critical/warning.

---

## Cost Optimization

| Что | Эффект |
|-----|--------|
| Prompt caching (`_cached_system()`) | ~40% экономии на input токенах |
| Haiku для scheduled jobs (8 из 17) | ~30% экономии (4× дешевле Sonnet) |
| CRUD tier: Haiku + 3 history + 2-5 filtered tools | ~40-50× дешевле baseline на рутинных запросах |
| FULL tier: Sonnet + 10 history + ALL_TOOLS | Только для диалога, планирования, анализа |
| Nutrition analysis + teach_moments + personal_insights: 0 API-вызовов | ~30% задач полностью без AI |
| **Итого CRUD vs baseline** | **~40-50×** |

---

## CI/CD — GitHub Actions

```
push → Syntax Check (20 файлов) → Run Tests (312 тестов) → Deploy to VPS → Telegram notify
```

**Syntax check покрывает:**
`main.py`, `config.py`, `bot/handlers.py`, `bot/commands.py`, `bot/keyboards.py`, `bot/admin.py`,
`ai/client.py`, `ai/tool_executor.py`, `ai/tools.py`, `ai/morph.py`,
`scheduler/logic.py`, `scheduler/jobs.py`, `scheduler/personal_insights.py`, `scheduler/adaptation.py`,
`scheduler/prediction.py`, `scheduler/periodization.py`, `scheduler/teach_moments.py`,
`db/queries/gamification.py`, `db/queries/episodic.py`

**Secrets:** SERVER_HOST, SERVER_USER (mrvald19), SSH_PRIVATE_KEY, SERVER_PORT (22)

**Deploy:** `git fetch origin && git reset --hard origin/main` → backup DB → `docker compose build --no-cache` → `down || true` → `up -d`

---

## Docker — важные детали
- `botuser` uid=1001, нет домашней папки
- Пакеты в `/usr/local/lib/python3.11/site-packages` (НЕ --user)
- Volumes: `./data:/app/data`, `./backups:/app/backups`
- Права на data/: `sudo chown -R 1001:1001 /opt/trainer-bot/data`
- Права на backups/: `sudo chown -R 1001:1001 /opt/trainer-bot/backups`

---

## Scheduler — запуск
AsyncIOScheduler запускается в `post_init(application)` — после старта event loop.
`app.bot_data["scheduler"]` — доступ из handlers (snooze).
`scheduler.shutdown()` — в finally блоке main().

---

## Multi-user
Все 26 таблиц БД изолированы по `user_id` (Telegram ID). Новый пользователь → /start → онбординг. `QUICK_MEAL_PRESETS` — глобальные (одинаковые для всех).

---

## Цепочка daily → weekly → monthly

**НЕ pipeline с передачей данных.** Все три уровня независимо читают сырые таблицы:
- `daily_summary` (23:00) → читает `workouts`, `metrics`, `nutrition_log` за сегодня → сохраняет AI-текст
- `weekly_report` (вс 21:00) → читает те же сырые таблицы за 7 дней + `daily_summary` как хронику
- `monthly_summary` (1-е число) → читает те же сырые таблицы за 30 дней

Сырые данные **никогда не очищаются** (кроме `checkins` старше 90 дней). Сводки — архивы для хроники, не pipeline.

---

## CI/CD — Известные грабли (выучено болью)

### SSH-ключ на GCP VM
**Проблема:** `google-guest-agent` периодически перезаписывает `~/.ssh/authorized_keys` из instance metadata.
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

---

## Известные подводные камни (код)

- **Двойное XP:** `tool_executor.py` автоматически начисляет 100 XP при `save_workout`. Если Claude ещё вызовет `award_xp` — дублирование. При работе с геймификацией помни об этом
- **handlers.py = 1600 строк:** монолитный файл. Ищи функции по имени, не пытайся «просмотреть весь файл»
- **response_parser.py:** может быть частично мёртвым кодом после внедрения Agent Tool Use. Не удаляй без проверки — возможно используется как fallback
- **SQLite concurrency:** scheduler и обработчики Telegram могут одновременно писать. Если видишь «database is locked» — это причина
- **Стрик около полуночи:** логика `get_streak()` может давать неправильный результат на границе дней

---

## Известные ограничения / Слепые зоны

Это фундаментальные ограничения текущей архитектуры — не баги, а точки роста:

| Ограничение | Причина | Влияние |
|------------|---------|---------|
| **Personal insights не накапливаются** | `broadcast_personal_insights()` вычисляет и шлёт, но не сохраняет результат в БД | Бот каждую неделю «открывает» паттерн заново, не знает что уже сообщал |
| **L4 observations лимитированы до 10** | `append_observation()` держит последние 10, старые вытесняются | Долгосрочные AI-наблюдения теряются через 10+ недель |
| **Teach moments не хранятся** | Только детерминированный хеш дня, нет истории показов | Возможны повторы через несколько недель |
| **Нет состава тела** | Только `weight_kg` в metrics | Нельзя разделить набор массы на мышцы и жир |
| **Питание — только дневной агрегат** | `nutrition_log` хранит сводку дня, не приёмы пищи | Нет тайминга белка (важен для синтеза мышц) |
| **Онбординговые данные статичны** | Фитнес-тест не запускается повторно автоматически | После реального прогресса за месяцы — starting values устаревают |
| **Нет внешних источников данных** | Нет интеграций с wearables (HRV, sleep trackers) | Recovery score считается только по subjective self-report |

---

## Вектор развития (Roadmap)

### 🟢 Быстрые победы (1-2 часа)
- **Хранить показанные personal insights** — поле в `memory_intelligence` или таблица `personal_insight_history`. Бот будет знать «я уже говорил тебе об этом паттерне — он усиливается»
- **Anti-repeat для teach_moments** — хранить массив хешей показанных фактов в БД, фильтровать при следующем показе

### 🟡 Средние улучшения (день работы)
- **Расширить L4 observations > 10** — добавить `observations_archive` (JSON без лимита). Текущий `observations` остаётся оперативным буфером
- **Автозапрос при стухших метриках** — если сон/энергия не записывались 2+ дня, добавлять в action hints утреннего чек-ина «давно не отслеживал сон — как спал?»
- **Детализация питания (meal-level)** — таблица `meal_entries` (time, food_item, protein_g, calories). Tool `save_meal`

### 🔵 Большие фичи (несколько дней)
- **Замеры тела** — таблица `body_measurements` (chest_cm, waist_cm, arms_cm, body_fat_pct). Tool `save_measurements`. В `/profile` и monthly summary
- **Повторный фитнес-тест** — команда `/retest` + автоматическое предложение раз в 2-3 месяца. Пересчитывает training_1rm, обновляет L0
- **Накопление personal insights в L3** — лучшие статистически значимые паттерны сохранять в `memory_training.personal_patterns` (JSON), читать в контексте как достоверный факт о пользователе

---

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
| CRUD tier | Haiku + 3 hist + filtered tools — для простых записей |
| FULL tier | Sonnet + 10 hist + ALL_TOOLS — для диалога и планирования |
| exercise_scores | L3: score=0.4×overload+0.3×consistency+0.3×alignment per exercise |
| stale metrics fix | Явная давность метрик + "Статус сегодня" блок в L0 (2026-03-24) |
| adaptation | DELOAD/LIGHT/BOOST/NORMAL модификатор тренировки (scheduler/adaptation.py) |
| personal insight | Rule-based корреляция из 60 дней данных (scheduler/personal_insights.py) |
| teach moment | Контекстный мини-урок без API (scheduler/teach_moments.py) |
| hallucination detector | Детектирует «записал» в тексте без реального tool_use вызова |
| AUTORECORD | Бот автоматически записывает ответы на свои вопросы (energy/sleep) |

---

## Key Notion Pages
| Page | URL |
|------|-----|
| ROADMAP | https://www.notion.so/31c8fb7a86e3812a8e20d04186ebebe9 |

---

## Current Issues
Нет открытых известных багов. Бот работает на продакшне.
Последний деплой: сессия 2026-03-24 (stale metrics fix + CLAUDE.md rewrite + deploy.yml syntax coverage).

## UX
- Кнопка меню в чате: MenuButtonCommands() + 10 команд через set_my_commands()
- Запись тренировки: guided flow (4 шага, кнопки)
- Pre-workout: prediction + adaptation с кнопками принять/отклонить
- Ошибки: in-chat через bot/debug.py
- Деплой: Telegram уведомление автоматически
