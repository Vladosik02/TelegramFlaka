# TelegramFlaka — Аудит кодовой базы
> Дата: 2026-03-22 | Тестов: 196 passed | Продакшн: стабилен
> Обновлено: 2026-03-22 (сессия 4) — все LOW приоритеты закрыты. Аудит завершён ✅

---

## ВЫСОКИЙ ПРИОРИТЕТ

- [x] **Prompt caching** — `ai/client.py`
  Добавлен `_cached_system(system)` — оборачивает system prompt в `cache_control: {"type":"ephemeral"}`. Применён во всех 4 местах вызова API. ~40% экономии на input-токенах системного промпта.

- [x] **Воскресный затор scheduler** — `scheduler/jobs.py`
  Раздвинуты интервалы: weekly_report 21:00 → mesocycle 21:30 → l4_intelligence 22:15. Было 15 мин, стало 30–45 мин между AI-задачами.

- [x] **Валидация tools ↔ executor** — `ai/tool_executor.py` + `main.py`
  Dispatch вынесен в module-level `_DISPATCH`. В `main()` добавлена startup-проверка: расхождение имён → RuntimeError, бот не запустится.

- [x] **Несовпадение имени параметра** — `ai/prompts/system_max.txt`, `system_light.txt`
  Исправлено 4 вхождения `meal_description=` → `meal_notes=`. Claude теперь вызывает инструмент с корректным именем параметра.

- [x] **Пропущенный индекс БД** — `db/schema.sql` + `db/connection.py`
  Добавлен `idx_exercise_results_user_ex ON exercise_results(user_id, exercise_name, date)`. Миграция v1.6 в `_run_migrations()` для продакшн-БД.

---

## СРЕДНИЙ ПРИОРИТЕТ

- [x] **Мёртвый код response_parser.py** — `ai/response_parser.py` + `tests/test_parsers.py`
  Удалены 6 мёртвых функций: `parse_workout_from_message`, `parse_metrics_from_message`, `is_nutrition_report`, `parse_nutrition_from_message`, `is_workout_report`, `is_metrics_report`. Также 3 lemma-set-а и импорт `ai.morph`. Оставлены только активные: `detect_health_alert`, `parse_exercises_from_message`. Из `test_parsers.py` удалены тесты мёртвых функций (~180 строк → ~70 строк).

- [x] **Дубль логики статистики** — `bot/commands.py` + `bot/handlers.py`
  Вынесен `_build_stats_text(user)` в `bot/commands.py`. Callback action='stats' в `bot/handlers.py` теперь вызывает его через `from bot.commands import _build_stats_text`. Также исправлено: handlers.py не содержал `alltime['total_minutes']` — теперь унифицировано.

- [x] **Дубль agent loop** — `ai/client.py`
  Извлечено ядро в `_run_agent_iterations(async_client, system, messages, tools, max_iterations, tg_id, bot, chat_id, *, log_prefix, on_tool_use)`. Оба цикла (`generate_agent_response` и `generate_scheduled_agent_message`) используют его. `on_tool_use` callback — для UI-статуса в chat loop.

- [x] **Тихие except без логирования** — `ai/context_builder.py`
  Добавлен `logger.warning(f"[CTX] ... failed for uid={uid}: {e}")` в 7 блоков: injuries JSON parse, recent_metrics load, nutrition 7-day summary, episodic memory, XP/level, recovery score, periodization.

- [x] **Workout flow state** — `bot/handlers.py`
  `ctx.user_data.pop("workout_flow", None)` перенесён в блок `finally` — гарантированная очистка состояния при любом исходе (успех, ошибка, или падение reply_text).

- [x] **Нет ON DELETE CASCADE** — `db/schema.sql` ⚠️ DEFERRED
  SQLite не поддерживает `ALTER TABLE ... ADD CONSTRAINT` с CASCADE. Добавление требует пересоздания таблиц — слишком рискованно для продакшн-БД. Отложено до планового обслуживания с миграцией.

- [x] **Неиспользуемые зависимости** — `requirements.txt`
  Выполнено в сессии 1: `pandas`, `numpy`, `aiohttp`, `aiosqlite` удалены. `openai` оставлен (используется Whisper в handlers.py:1660).

---

## НИЗКИЙ ПРИОРИТЕТ

- [x] **Монолитная функция** — `ai/client.py: generate_agent_response()`
  Извлечены 3 подфункции: `_stream_response()`, `_log_usage_footnote()`, `_detect_hallucination()`. Константа `_STATUS_RU` вынесена на module-level. `generate_agent_response` стала компактнее за счёт делегирования.

- [x] **Непоследовательный контракт read-tools** — `ai/tool_executor.py`
  Добавлен `"success": True` в `_tool_get_weekly_stats()` — теперь все read-tools возвращают `success` наравне с write-tools.

- [x] **Лишний контекст для scheduled** — `ai/context_builder.py`
  Episodic memory теперь загружается только при тегах `{"training", "health", "goals", "analytics"}`. Экономия ~100–150 токенов на простых чатах без этих тегов.

- [x] **print() в backup.py** — строка 46. Заменено на `logger.info()`.

- [x] **ai_usage_log не читается** — `bot/commands.py`
  `cmd_costs` уже реализован (строка 828). `get_usage_stats()` + `get_daily_breakdown()` вызываются из `/costs`. Команда зарегистрирована в `main.py`.

- [x] **Нет тестов на handlers и commands** — добавлен `tests/test_smoke_imports.py` (15 тестов):
  Import smoke для 10 модулей; `_build_stats_text()` (нормальные/нулевые данные, длина прогресс-бара); tools ↔ executor consistency (ALL_TOOLS ↔ _DISPATCH двусторонняя проверка).

---

## ВЫПОЛНЕНО

### Сессия 1 (2026-03-22)
- [x] **3 async ResourceWarning** — `tests/conftest.py` + `tests/test_phase16.py` + `pytest.ini`
  Убран `asyncio.run()`, добавлена cleanup-фикстура, `filterwarnings = error::ResourceWarning`. 243 passed, 0 warnings.

- [x] **Лемматизация классификатора** — `ai/morph.py` + `ai/context_builder.py` + `ai/response_parser.py`
  Заменён подстроковый поиск на pymorphy3-лемматизацию. Новый модуль `ai/morph.py`, обновлены `_classify_message()` и `is_*_report()`.

### Сессия 2 (2026-03-22) — все 5 HIGH приоритетов
- [x] **Prompt caching** — см. HIGH выше
- [x] **Scheduler Sunday congestion** — см. HIGH выше
- [x] **Tool validation at startup** — см. HIGH выше
- [x] **meal_description → meal_notes** — см. HIGH выше
- [x] **Missing DB index** — см. HIGH выше

### Сессия 4 (2026-03-22) — все LOW приоритеты. Аудит завершён ✅
- [x] **Монолитная функция** — 3 подфункции + _STATUS_RU константа выделены из generate_agent_response
- [x] **read-tools success** — _tool_get_weekly_stats возвращает "success": True
- [x] **Episodic gating** — загрузка только при тегах training/health/goals/analytics
- [x] **print() → logger** — backup.py строка 46
- [x] **ai_usage_log** — cmd_costs уже был готов, подтверждён и задокументирован
- [x] **Smoke tests** — tests/test_smoke_imports.py: 15 тестов (импорты, _build_stats_text, tools↔executor)
- Итого тестов: 196 passed (было 181 в сессии 3: +15 новых smoke)

### Сессия 3 (2026-03-22) — все MEDIUM приоритеты
- [x] **Dead code cleanup** — response_parser.py: -6 функций, -3 lemma-set-а, -1 import; test_parsers.py: -180 строк
- [x] **Stats DRY** — `_build_stats_text()` в commands.py, импортируется в handlers.py
- [x] **Agent loop DRY** — `_run_agent_iterations()` shared core; оба цикла используют
- [x] **Context_builder warnings** — 7 silent except → logger.warning() с uid и ошибкой
- [x] **Workout flow finally** — `ctx.user_data.pop()` в finally-блоке
- [x] **ON DELETE CASCADE** — DEFERRED (SQLite limitation)
- [x] **Unused deps** — выполнено в сессии 1
