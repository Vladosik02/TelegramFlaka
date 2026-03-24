# 🗄️ Карта Базы Данных — Trainer Bot

> **Для кого:** разработчик, AI-ревью, система промптов.
> **Принцип:** бот никогда не обращается к БД напрямую. Вся логика — через `db/queries/*.py`.
> AI-бот видит данные только через `context_builder.py` (слои L0–L4 + хроника).

---

## Полный путь к БД

```
data/flaka.db          (production)
data/test_flaka.db     (тесты)
```

---

## Архитектура памяти: 4 слоя

```
L0  Surface Card    ~150 tok   ВСЕГДА   → имя, цель, стрик, возраст, рост, сезон
L1  Deep Bio        ~150 tok   health?  → травмы, непереносимости, реакции на добавки
L2  Nutrition       ~120/200   food?    → КБЖУ-цель, добавки, журнал 3 дня, AI-инсайты
L3  Training Intel  ~150/250   train?   → предпочтения, упражнения, рекорды, программа
L4  AI Intelligence ~200 tok   ВСЕГДА   → дайджест недели, наблюдения, тренд, мотивация
📅  Daily Chronicle ~150 tok   ВСЕГДА   → последние 5 дней: резюме + инсайт
```

---

## Таблицы: подробный справочник

### 👤 user_profile
**Назначение:** базовый профиль пользователя. Уровень 1 памяти.

| Поле | Тип | Что хранит |
|------|-----|-----------|
| id | INTEGER PK | внутренний ID |
| telegram_id | INTEGER UNIQUE | Telegram user ID |
| name | TEXT | имя пользователя |
| goal | TEXT | «похудеть» / «набрать массу» / «выносливость» |
| fitness_level | TEXT | beginner / intermediate / advanced |
| injuries | TEXT | JSON: список травм ["колено", "спина"] |
| training_location | TEXT | home / gym / outdoor / flexible |
| timezone | TEXT | Europe/Warsaw (default) |
| active | INTEGER | 1 = активен, 0 = пауза |
| soft_start | INTEGER | 1 = режим мягкого старта |
| paused_at | TEXT | дата паузы (/stop) |
| last_active | TEXT | последняя активность |

**Файл:** `db/queries/user.py`
**Методы:** `get_user(telegram_id)`, `create_user(...)`, `update_user(...)`

---

### 🏋️ workouts
**Назначение:** журнал тренировок. Уровень 2.

| Поле | Тип | Что хранит |
|------|-----|-----------|
| id | INTEGER PK | — |
| user_id | INTEGER FK | → user_profile.id |
| date | TEXT | YYYY-MM-DD |
| mode | TEXT | MAX / LIGHT |
| type | TEXT | cardio / strength / stretch / rest |
| duration_min | INTEGER | длительность в минутах |
| intensity | INTEGER 1–10 | субъективная нагрузка |
| exercises | TEXT | JSON список упражнений |
| notes | TEXT | свободный текст (из него парсятся результаты) |
| completed | INTEGER | 1 = завершена |

**Файл:** `db/queries/workouts.py`
**Методы:** `log_workout(...)`, `get_today_workout(uid)`, `get_workouts_range(uid, days)`, `get_streak(uid)`, `get_weekly_stats(uid)`, `get_metrics_range(uid, days)`

---

### 📊 metrics
**Назначение:** ежедневные физические метрики (вес, сон, энергия).

| Поле | Тип | Что хранит |
|------|-----|-----------|
| user_id | INTEGER FK | — |
| date | TEXT | YYYY-MM-DD |
| weight_kg | REAL | вес в кг |
| sleep_hours | REAL | часов сна |
| energy | INTEGER 1–5 | уровень энергии |
| mood | INTEGER 1–5 | настроение |
| water_liters | REAL | вода (л) |
| steps | INTEGER | шаги |
| notes | TEXT | заметки |

**Файл:** `db/queries/workouts.py` (вместе с workouts)
**Методы:** `log_metrics(...)`, `get_metrics_range(uid, days=7)`

---

### 💬 checkins
**Назначение:** записи утреннего/дневного/вечернего чек-инов.

| Поле | Тип | Что хранит |
|------|-----|-----------|
| user_id | FK | — |
| date | TEXT | YYYY-MM-DD |
| time_slot | TEXT | morning / afternoon / evening |
| status | TEXT | pending / done / skipped |
| user_message | TEXT | что написал пользователь |
| ai_response | TEXT | ответ AI |
| reminder_count | INTEGER | сколько раз напоминали |

**Файл:** `db/queries/context.py`
**Методы:** `get_or_create_checkin(uid, date, slot)`, `update_checkin(...)`, `get_today_checkins(uid)`

---

### 📝 conversation_context
**Назначение:** история диалога (сессия). Уровень 4. Сжимается при 99% заполнении (~3500 tok).

| Поле | Тип | Что хранит |
|------|-----|-----------|
| user_id | FK | — |
| role | TEXT | user / assistant |
| content | TEXT | текст сообщения |
| checkin_id | FK | привязка к чек-ину (необязательно) |

**Файл:** `db/queries/context.py`
**Методы:** `add_conversation_message(uid, role, content)`, `get_recent_conversation(uid, limit)`, `clear_conversation(uid)`, `save_context_summary(uid, summary)`

---

### 📅 weekly_summaries
**Назначение:** агрегат недели (статистика). Генерируется воскресеньем.

| Поле | Тип | Что хранит |
|------|-----|-----------|
| user_id | FK | — |
| week_start | TEXT | YYYY-MM-DD (понедельник) |
| workouts_done | INTEGER | выполнено тренировок |
| workouts_total | INTEGER | запланировано |
| avg_intensity | REAL | средняя интенсивность |
| avg_sleep | REAL | средний сон |
| avg_energy | REAL | средняя энергия |
| total_steps | INTEGER | шаги за неделю |
| summary_text | TEXT | AI-сгенерированный текст |

**Файл:** `db/queries/stats.py`
**Методы:** `save_weekly_summary(uid, week, stats, text)`, `get_last_n_weeks(uid, n)`

---

## 4-СЛОЙНАЯ ПАМЯТЬ (memory_*)

### 🧠 memory_athlete (L0 + L1)

| Поле | Слой | Что хранит |
|------|------|-----------|
| age | L0 | возраст |
| height_cm | L0 | рост |
| season | L0 | bulk / cut / maintain / peak |
| baseline_pushups | L0 | базовые отжимания (тест) |
| baseline_squats | L0 | базовые приседания (тест) |
| baseline_plank_sec | L0 | базовая планка (сек) |
| food_intolerances | L1 | JSON: ["лактоза"] |
| supplement_reactions | L1 | JSON: {"креатин": "хорошо"} |
| personal_records | L1 | JSON: {"bench_1rm": 100} |

**Файл:** `db/queries/memory.py`
**Методы:** `get_l0_surface(uid)`, `get_l1_deep_bio(uid)`, `upsert_athlete(uid, **fields)`

---

### 🥗 memory_nutrition (L2)

| Поле | Слой | Что хранит |
|------|------|-----------|
| daily_calories | brief | целевые ккал/день |
| protein_g | brief | целевой белок (г) |
| fat_g | brief | целевые жиры (г) |
| carbs_g | brief | целевые углеводы (г) |
| meal_preferences | deep | JSON: {"breakfast": "овсянка"} |
| supplements | deep | JSON: ["протеин 30г", "омега-3"] |
| restrictions | deep | JSON: ["без сахара"] |
| last_meal_notes | deep | последние заметки о питании |

**Файл:** `db/queries/memory.py`
**Методы:** `get_l2_brief(uid)`, `get_l2_deep(uid)`, `upsert_nutrition(uid, **fields)`

---

### 🏃 memory_training (L3)

| Поле | Слой | Что хранит |
|------|------|-----------|
| preferred_days | brief | JSON: ["вторник", "пятница"] |
| preferred_time | brief | morning / evening / flexible |
| avg_session_min | brief | средняя длительность (мин) |
| current_program | brief | название программы |
| exercise_scores | deep | JSON: {"squat": {"score": 7.2}} |
| avoided_exercises | deep | JSON: ["выпады"] |
| training_notes | deep | заметки по тренировкам |

**Файл:** `db/queries/memory.py`
**Методы:** `get_l3_brief(uid)`, `get_l3_deep(uid)`, `upsert_training(uid, **fields)`

---

### 🤖 memory_intelligence (L4)

| Поле | Тип | Что хранит |
|------|-----|-----------|
| weekly_digest | TEXT | AI-дайджест недели (2–3 предложения) |
| ai_observations | TEXT | JSON: ["Лучше тренируется вт/пт"] |
| seasonal_context | TEXT | что важно сейчас |
| motivation_level | TEXT | low / normal / high |
| trend_summary | TEXT | краткий трендовый анализ |

**Файл:** `db/queries/memory.py`
**Методы:** `get_l4_intelligence(uid)`, `upsert_intelligence(uid, **fields)`, `append_observation(uid, text)`
**Обновляется:** каждое воскресенье в 21:30 через `broadcast_l4_intelligence()`

---

## ФАЗА 7: Расширенная аналитика

### 🍽️ nutrition_log
**Назначение:** реальное питание за день (не цели, а факт).

| Поле | Тип | Что хранит |
|------|-----|-----------|
| user_id | FK | — |
| date | TEXT | YYYY-MM-DD |
| calories | INTEGER | реально съеденные ккал |
| protein_g / fat_g / carbs_g | REAL | БЖУ (граммы) |
| water_ml | INTEGER | вода (мл) |
| meal_notes | TEXT | что ел (краткое описание) |
| quality_score | INTEGER 1–10 | качество питания |
| junk_food | INTEGER | 1 = был фастфуд |

**Файл:** `db/queries/nutrition.py`
**Методы:** `log_nutrition_day(uid, date, **fields)`, `get_nutrition_log(uid, days)`, `get_today_nutrition(uid)`, `get_nutrition_summary(uid, days)`
**Заполняется:** авто-парсером из сообщений пользователя (`is_nutrition_report` → `parse_nutrition_from_message` → `save_nutrition_from_parsed`)

---

### 💡 nutrition_insights
**Назначение:** AI-рекомендации по питанию (дефициты, предупреждения).

| Поле | Тип | Что хранит |
|------|-----|-----------|
| insight_type | TEXT | deficiency / recommendation / warning |
| nutrient | TEXT | что конкретно (белок, витамин D) |
| description | TEXT | описание проблемы |
| action | TEXT | что делать |
| resolved | INTEGER | 0 = активно, 1 = решено |

**Файл:** `db/queries/nutrition.py`
**Методы:** `add_nutrition_insight(...)`, `get_active_insights(uid)`, `resolve_insight(id)`

---

### 🏋️ exercise_results
**Назначение:** детальные результаты каждого упражнения из тренировки.

| Поле | Тип | Что хранит |
|------|-----|-----------|
| user_id | FK | — |
| workout_id | FK | → workouts.id |
| date | TEXT | YYYY-MM-DD |
| exercise_name | TEXT | «жим лёжа», «планка» |
| sets | INTEGER | количество подходов |
| reps | INTEGER | повторения |
| duration_sec | INTEGER | длительность (для планки, кардио) |
| weight_kg | REAL | вес (если с отягощением) |
| is_personal_record | INTEGER | 1 = новый рекорд |

**Файл:** `db/queries/exercises.py`
**Методы:** `log_exercise_result(...)`, `get_exercise_history(uid, name)`, `get_recent_results(uid, days)`
**Заполняется:** авто-парсером из notes тренировки (`parse_exercises_from_message` → `_save_exercise_results`)

---

### 🏆 personal_records
**Назначение:** личные рекорды (автообновляются при каждом новом результате).

| Поле | Тип | Что хранит |
|------|-----|-----------|
| user_id | FK | — |
| exercise_name | TEXT | название упражнения |
| record_value | REAL | значение (кг / повторы / сек) |
| record_type | TEXT | weight / reps / time |
| set_at | TEXT | дата рекорда |
| previous_record | REAL | предыдущий рекорд |
| improvement_pct | REAL | прирост в % |

**Файл:** `db/queries/exercises.py`
**Методы:** `get_personal_records(uid, limit)`, `get_recent_records(uid, days)`, `_check_and_set_record(uid, name, value, type, date)`
**Приоритет:** weight > time > reps

---

### 📅 daily_summary ✨ НОВОЕ
**Назначение:** AI-резюме каждого дня. Генерируется ночью (~23:00). Даёт AI «память» о последних 5 днях.

| Поле | Тип | Что хранит |
|------|-----|-----------|
| user_id | FK | — |
| date | TEXT | YYYY-MM-DD (UNIQUE) |
| summary_text | TEXT | AI-текст: 2–3 предложения о дне |
| workout_done | INTEGER | 1 = тренировка была |
| calories_met | INTEGER | 1 = план КБЖУ ±15% выполнен |
| mood_score | INTEGER 1–5 | настроение дня |
| energy_score | INTEGER 1–5 | энергия дня |
| sleep_hours | REAL | сон (часов) |
| key_insight | TEXT | одна рекомендация AI на завтра |

**Файл:** `db/queries/daily_summary.py`
**Методы:** `upsert_daily_summary(uid, date, ...)`, `get_daily_summaries(uid, days)`, `get_today_summary(uid)`, `get_last_summary(uid)`
**Генерируется:** `broadcast_daily_summary()` в scheduler каждую ночь

---

## Поток данных: как AI получает информацию

```
Пользователь пишет сообщение
    ↓
handlers.py → build_layered_context(telegram_id, text)
    ↓
context_builder.py:
  _classify_message(text)         → теги: {health, food, training}
  _build_l0_card()                → имя, цель, стрик, возраст
  _build_l1_deep_bio()   [health] → травмы, непереносимости
  _build_l2_nutrition()  [food]   → КБЖУ + журнал питания
  _build_l3_training()   [train]  → программа + рекорды
  _build_l4_intelligence()        → дайджест + наблюдения
  _build_daily_chronicle()        → последние 5 дней
    ↓
system_prompt + memory_blocks + conversation_history
    ↓
Anthropic API → ответ AI
    ↓
response_parser.py → parse_metrics / parse_workout / parse_exercises / parse_nutrition
    ↓
writer.py → log_metrics / log_workout / _save_exercise_results / save_nutrition
    ↓
БД сохраняется → следующий контекст будет богаче
```

---

## ❌ Запланировано, ещё не реализовано (Фаза 8+)

| Таблица | Приоритет | Фаза |
|---------|-----------|------|
| `monthly_summary` | Высокий | 8.1 |
| `training_plan` | Высокий | 8.3 |
| `user_fitness_metrics` | Средний | 8.2 |
| `user_health` (отд. таблица) | Низкий | 8.4 |
| `user_preferences` | Низкий | 8.4 |

---

## Правила записи (writer.py)

Весь AI-ответ → `writer.py` → единая точка входа:
- `save_metrics_from_parsed(telegram_id, parsed)` — сохраняет weight/sleep/energy/mood
- `save_workout_from_parsed(telegram_id, parsed)` — сохраняет тренировку + авто-парсит упражнения
- `save_nutrition_from_parsed(telegram_id, parsed)` — сохраняет КБЖУ дня
- `save_ai_response(telegram_id, text)` — сохраняет ответ AI в историю

---

*Обновлено: 09.03.2026. Текущее состояние: Фаза 7 (~80% выполнено).*
