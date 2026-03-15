# PLAN PHASE 16 — Quality & Engagement
_Статус: ✅ Закрыта (2026-03-15)_

---

## 16.1 — Smoke Tests (pytest)
**Проблема:** Критические пути (upsert, plan sync, tool dispatch) не покрыты тестами — регрессии могут проскочить незамеченными.

**Решение:** `tests/test_phase16.py` — 8 тестов:
- `test_log_metrics_no_duplicate` — upsert не создаёт дубль за один день
- `test_log_metrics_upsert_preserves_existing` — обновляет поле, не затирая остальные
- `test_mark_plan_day_completed_sets_flag` — план синкается после записи тренировки
- `test_mark_plan_day_completed_skips_rest` — rest-дни не помечаются completed
- `test_mark_plan_day_completed_no_double_count` — повторный вызов не инкрементирует счётчик
- `test_get_streak_consecutive` — стрик 3 дня подряд = 3
- `test_get_streak_broken` — разрыв вчера → стрик = 1
- `test_tool_executor_unknown_tool` — неизвестный tool → {"error": ..., "success": False}
- `test_tool_executor_save_workout_missing_fields` — отсутствие полей → error

**Файлы:** `tests/test_phase16.py`, `tests/conftest.py` (добавлены targets: memory, nutrition)

---

## 16.2 — График веса в /stats
**Проблема:** `analytics/charts.py` с 6 типами графиков существует с Фазы 12, но недоступен из интерфейса — нет кнопок нигде.

**Решение:**
- `kb_stats_quick()` — добавлены 2 новые кнопки: `⚖️ График веса` (chart:weight) и `💪 Рекорды` (chart:strength)
- `_handle_chart_callback()` — новый handler в `bot/handlers.py`: вызывает `build_chart(chart_type, user_id)` → отправляет фото в чат
- Dispatch `chart:*` добавлен в `handle_callback()` перед `menu:*`
- При недостаточном количестве данных → текстовый ответ вместо ошибки

**Файлы:** `bot/keyboards.py`, `bot/handlers.py`

---

## 16.3 — Weekly Digest в чат
**Проблема:** L4 Intelligence генерируется каждое воскресенье 21:30, но пишется только в БД. Пользователь о нём не знает.

**Решение:** `broadcast_l4_intelligence(bot=None)` — добавлен опциональный параметр `bot`.
- После `update_l4_for_user()` → читаем свежий `weekly_digest` и `trend_summary` из БД
- Отправляем красивое сообщение "📊 Недельный дайджест от Алекса" пользователю
- `scheduler/jobs.py` — передаёт `args=[bot]` в l4_intelligence job

**Файлы:** `scheduler/logic.py`, `scheduler/jobs.py`

---

## 16.4 — Streak Protection
**Проблема:** Пользователь может сломать стрик из-за забывчивости — не записал тренировку хотя тренировался.

**Решение:** `broadcast_streak_protection(bot)` — новая функция в `scheduler/logic.py`:
- Запускается ежедневно в 20:00
- Для каждого активного пользователя: если `get_streak() >= 3` И нет completed тренировки сегодня → отправляет предупреждение
- Сообщение: "🔥 Стрик N дней под угрозой!"
- Зарегистрирован в `scheduler/jobs.py` как job `streak_protection`

**Файлы:** `scheduler/logic.py`, `scheduler/jobs.py`

---

## Сводная таблица изменений

| Файл | Изменение |
|------|-----------|
| `tests/conftest.py` | +2 targets (memory, nutrition) |
| `tests/test_phase16.py` | Новый файл — 9 smoke tests |
| `bot/keyboards.py` | `kb_stats_quick()` — +2 кнопки (chart:weight, chart:strength) |
| `bot/handlers.py` | `_handle_chart_callback()` + dispatch `chart:*` |
| `scheduler/logic.py` | `broadcast_l4_intelligence(bot)` — digest delivery; `broadcast_streak_protection(bot)` |
| `scheduler/jobs.py` | +import `broadcast_streak_protection`; l4_intelligence +args[bot]; streak_protection job 20:00 |
