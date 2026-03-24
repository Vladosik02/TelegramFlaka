# Trainer Bot — Telegram Personal Trainer

**Codename:** Trainer Bot / Flaka Bot
**Notion ROADMAP:** https://www.notion.so/31c8fb7a86e3812a8e20d04186ebebe9
**Parent project:** 🏋️ Personal Trainer Telegram Bot — Project Plan

## Суть
Telegram-бот личный тренер с двумя режимами (MAX/LIGHT), AI на базе Anthropic Claude,
4-уровневой системой памяти и автоматическими напоминаниями/аналитикой.

## Архитектурная философия (MVP Economy)
**Принцип: максимум ценности за минимум токенов.**
- Контекст грузится **лениво** — только тот слой, который нужен прямо сейчас
- Контекст "еда" → AI включает роль нутрициолога, грузит L2 (nutrition deep) + nutrition_log
- Контекст "тренировка" → тренер, грузит L3 deep + exercise_results + personal_records
- Контекст "здоровье" → грузит L1 (травмы, реакции на добавки)
- L0 + L4 + daily_chronicle — **всегда**, остальное — **по требованию**
- AI знает контекст только когда он был явно загружен — это и экономия, и точность
- **Сильные зависимости**: monthly_summary → в контекст только при "аналитика/прогресс/месяц"
- Плановые тренировки (training_plan, Ф8.3) дадут боту **опорную точку** — сравнение план/факт
- Цель: бот работает эффективно за копейки, не перегружая API ненужным контекстом

## Персонаж
Имя: **Алекс** (ещё не добавлено в промпты — известный баг)
Режимы: MAX (интенсивный), LIGHT (поддерживающий)

## Архитектура файлов
```
config.py
db/schema.sql, connection.py, queries/*.py, writer.py
ai/prompts/*.txt, context_builder.py, client.py, response_parser.py
bot/keyboards.py, commands.py, handlers.py, admin.py
scheduler/logic.py, jobs.py, nudges.py
tests/__init__.py, conftest.py, test_config.py, test_fitness_metrics.py,
       test_nudges.py, test_training_plan.py
main.py, backup.py
Dockerfile, docker-compose.yml, deploy.sh, server-setup.sh
.github/workflows/deploy.yml
```

## 4-Layer Memory System
- **L0 Surface Card** (~160 tok, ВСЕГДА): name, goal, level, streak, age, height, season, **fitness_score** (Ф8.2)
- **L1 Deep Bio** (~150 tok, health context): injuries, intolerances, supplement reactions, PRs
- **L2 Nutrition** (brief ~120 / deep ~200 при food): macros, supplements, restrictions
- **L3 Training Intel** (brief ~150 / deep ~250 при training): preferred days, exercise SCORE, avoided
- **L4 AI Intelligence** (~200 tok, ВСЕГДА): weekly digest, observations, trends, motivation
- Бюджет: ~620 typ / ~950 max + ~600-900 диалог = max ~2200 tok ✅

## Статус фаз (обновлено 10.03.2026)
| Фаза | Статус |
|------|--------|
| Планирование | ✅ Завершено |
| Фаза 1 — Фундамент | ✅ Завершено |
| Фаза 2 — AI-слой | ✅ Завершено |
| Фаза 3 — Telegram | ✅ Завершено |
| Фаза 4 — Scheduler | ✅ Завершено |
| Фаза 5 — Деплой | ✅ Бот работает на Google Cloud VM (Ubuntu, SSH) |
| Фаза 6 — 4-Layer Memory | ✅ Завершено |
| Фаза 7 — Beyond MVP | 🟡 В разработке поверх работающего бота |
| Фаза 8.1 — Monthly Summary | ✅ Реализовано (monthly_summary, APScheduler, context_builder) |
| Фаза 8.2 — Fitness Metrics & /test | ✅ Реализовано (user_fitness_metrics, ACSM/NSCA нормализация) |
| Фаза 8.3 — AI Workout Plan | ✅ Реализовано (training_plan, /plan, AI-персонаж Алекс, архивация вс 19:00, генерация вс 20:00) |
| Фаза 8.4 — Proactive Nudges | ✅ Реализовано (scheduler/nudges.py, 5 типов, nudge_log anti-spam, 08:00 daily) |
| Фаза 8.5 — Admin Tools + Tests | ✅ Реализовано (/admin, ADMIN_USER_ID, broadcast, triggers, pytest 117 тестов) |
| **CI/CD деплой обновлён** | ✅ deploy.yml: check → test (pytest 117) → deploy; .dockerignore исключает tests/; .env.example + ADMIN_USER_ID |

## Фаза 7 — Beyond MVP (деталь)
Notion: https://www.notion.so/31d8fb7a86e381dd8b3ae60dc4f880d6

| Пункт | Статус |
|-------|--------|
| 7.1 Nutrition (базовый) | ✅ Выполнено (nutrition_log, nutrition_insights, парсер, L2-контекст) |
| 7.1 FatSecret API | ❌ Отложено |
| 7.2 exercise_results + personal_records | ✅ Выполнено |
| 7.3 Онбординг-промпт, /stop [N дней], health_check, /profile | ✅ Выполнено |
| 7.4 daily_summary + хроника | ✅ Выполнено |
| 7.4 user_fitness_metrics, user_health, user_preferences, monthly_summary | → Фаза 8 ✅ |

## Фаза 8 — Analytics, Plans & Proactive AI (деталь)
Notion: https://www.notion.so/31e8fb7a86e38125af07c36c826cfbd3

| Пункт | Статус |
|-------|--------|
| **8.1 Monthly Summary** | ✅ Реализовано — monthly_summary, APScheduler 1-го в 09:00, context analytics |
| **8.2 Fitness Metrics & /test** | ✅ Реализовано — user_fitness_metrics, piecewise ACSM/NSCA, L0 fitness_score |
| **8.3 AI Workout Plan** | ✅ Реализовано — training_plan, /plan, Алекс-персонаж, вс 19:00/20:00, workouts.plan_id, monthly_summary интеграция |
| **8.4 Proactive Nudges** | ✅ Реализовано — scheduler/nudges.py, 5 типов нудж, nudge_log, ежедневно 08:00 |
| **8.5 Admin Tools + Tests** | ✅ Реализовано — /admin, bot/admin.py, ADMIN_USER_ID, broadcast, triggers (6 задач), pytest 117 тестов |

### 8.5 — Детали реализации
- **`bot/admin.py`** (новый файл): вся логика панели отделена от commands.py
- **`/admin`** — доступен только ADMIN_USER_ID из .env; остальным: «⛔ Доступ запрещён»
- **Inline-меню**: Пользователи (список + стрик + last_active) → Задачи (APScheduler + next_run_time) → Рассылка (broadcast state machine) → Триггер (6 ручных запусков: morning/evening/daily/weekly/nudges/monthly)
- **Callback-prefix**: `adm:home`, `adm:users`, `adm:jobs`, `adm:broadcast`, `adm:trigger`, `adm:trigger:{task}`
- **`db.queries.user.get_all_active_users()`** — новая функция (список всех активных)
- **`/help`** — показывает `/admin` только администратору (скрыт от обычных пользователей)
- **`pytest>=7.0.0`** добавлен в requirements.txt

### 8.5 — Тестовое покрытие (117 тестов, все GREEN)
| Файл | Тестов | Покрытие |
|------|--------|----------|
| test_config.py | 17 | get_trainer_mode, все пороги, ADMIN_USER_ID |
| test_fitness_metrics.py | 37 | normalize_*, compute_fitness_score, get_fitness_level, CRUD |
| test_nudges.py | 40 | _days_word, _workouts_word, anti-spam, 5 чекеров, приоритет |
| test_training_plan.py | 23 | make_plan_id, week_start, CRUD, архивация |

### 8.4 — Детали реализации
- **5 типов нудж**: drop (3+ дня без тренировки) → recovery (сон < 6ч × 3 дня) → pr_approaching (≥ 90% от рекорда) → streak (до рекорда ≤ 3 дней) → goal_progress (40–65% плана)
- **Приоритет при запуске**: drop > recovery > pr_approaching > streak > goal_progress; отправляется ОДИН нудж за запуск
- **Anti-spam**: таблица `nudge_log` — кулдаун 24ч для drop/recovery, 7 дней для остальных
- **Запуск**: APScheduler cron ежедневно в 08:00 (до утреннего чек-ина в 09:00); молчащие пользователи пропускаются
- **API**: без дополнительных вызовов к Anthropic — сообщения формируются правилами
- **goal_progress**: опирается на активный `training_plan` (Ф8.3); если плана нет — пропускается
- **streak_nudge**: считает исторический максимум стрика через `_get_max_streak_ever()`
- **pr_approaching**: берёт только результаты ≤ 14 дней; предлагает конкретное целевое значение (+2.5кг / +1повт / +5сек)
- **Склонение**: корректное склонение числительных (день/дня/дней, тренировка/тренировки/тренировок)
- **Файлы**: config.py (7 констант), db/schema.sql (nudge_log + index), scheduler/nudges.py (новый), scheduler/jobs.py

### 8.3 — Детали реализации
- **AI-персонаж**: Алекс — прямой, по делу, ACSM/NSCA-база, принципы прогрессивной нагрузки
- **plan_id**: `PLN-{user_id}-{YYYYWW}` — уникальный, сортируемый, ISO-неделя
- **Scheduler**: воскресенье 19:00 архивация → воскресенье 20:00 генерация + отправка
- **workouts.plan_id**: миграция v1.4 в `db/connection.py` — точная привязка тренировок к плану
- **plan_json**: JSON-массив 7 дней с exercises, rpe, weight_kg_target, ai_note
- **Корректировка**: AI re-generation при "plan" теге в диалоге (+1 API вызов)
- **Context**: `_PLAN_WORDS` → "plan" тег → `_build_active_plan()` загружается в L3 (~150 tok)
- **monthly_summary**: `get_monthly_plan_stats()` → plans_count, avg_completion, volume_trend, best_plan_pct
- **Prompt**: `ai/prompts/training_plan.txt` — шаблон с 25+ переменными данных атлета
- **Файлы**: db/schema.sql, db/queries/training_plan.py, db/connection.py, ai/prompts/training_plan.txt, config.py, db/queries/stats.py, scheduler/logic.py, scheduler/jobs.py, bot/commands.py, ai/context_builder.py, main.py

### 8.2 — Детали реализации
- **Нормализация**: piecewise-linear по ACSM (Guidelines 11th ed.) + NSCA + Cooper Institute
- **Breakpoints отжимания**: 0→0, 10→18, 20→35, 30→52, 40→68, 50→80, 65→90, 80→96, 100→100
- **Breakpoints приседания**: 0→0, 15→18, 30→35, 45→52, 60→67, 80→80, 100→89, 130→96, 160→100
- **Breakpoints планка (сек)**: 0→0, 30→20, 60→40, 90→58, 120→73, 180→88, 240→95, 300→100
- **fitness_score** = pushups×0.35 + squats×0.35 + plank×0.30 (Notion-spec)
- **strength_score** = (pushups + squats) / 2 (для Notion-совместимости)
- **endurance_score / flexibility_score** = NULL (зарезервировано, будущие тесты)
- **Cooldown**: предупреждение при тесте < 7 дней, не блокировка
- **State machine**: pushups → squats → plank → hr(/skip) → результаты + дельта
- **L0 всегда**: `Fitness Score: 71/100 — Хорошо (тест 2026-03-10)` (~8 tok)

## Известные расхождения (баги/отложено)
- ❌ Имя «Алекс» не добавлено в промпты (бот безымянный)
- ❌ `/stop [N дней]` — параметр не обрабатывается
- ❌ Свободный текст с профильными данными не парсится в memory_training (только structured-парсеры)
- ❌ FatSecret API (EatCount-Bot: https://github.com/GopkoDev/EatCount-Bot) — отложено Ф8+

## Команды бота
/start, /stop [N], /stats, /mode, /help, /reset, /profile, /export, **/test** (Ф8.2)
(Фаза 8: /plan, /admin — pending)

## Деплой
- Сервер: Google Cloud VM, SSH, Linux
- Docker multi-stage, non-root, 256MB RAM limit
- CI/CD: GitHub Actions → SSH deploy
- DEPLOY.md, GCP_SYSTEMD_DEPLOY.md — инструкции по деплою
- ✅ Бот работает на проде (Фаза 6 завершена)
- GitHub: github.com/Vladosik02/TelegramFlaka
