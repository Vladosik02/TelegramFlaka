# Glossary — Trainer Bot Project

## Режимы и персонаж
| Term | Meaning |
|------|---------|
| MAX | Режим бота — активный/интенсивный трекинг |
| LIGHT | Режим бота — лёгкий/поддерживающий трекинг |
| Алекс | Имя AI-персонажа бота (не реализовано в промптах) |
| system_max.txt | Системный промпт MAX-режима |
| system_light.txt | Системный промпт LIGHT-режима |

## Архитектурные термины
| Term | Meaning |
|------|---------|
| context_builder | `ai/context_builder.py` — сборщик минимального контекста для AI |
| db_updates | JSON-блок в ответе AI с инструкциями для записи в БД |
| writer.py | `db/writer.py` — единая точка записи от AI |
| response_parser | `ai/response_parser.py` — разбор JSON из ответа AI |
| CONTEXT_PROFILES | Профили контекста в context_builder |
| build_layered_context | Функция сборки 4-слойного контекста |
| token budget | Лимит токенов на контекст (3500 tok) |
| inactivity reset | Сброс контекста после 180 мин неактивности |

## 4-Layer Memory
| Term | Meaning |
|------|---------|
| L0 | Surface Card (~150 tok): name, goal, level, streak, age, height, season — ВСЕГДА |
| L1 | Deep Bio (~150 tok): injuries, intolerances, supplement reactions, PRs — при health-контексте |
| L2 | Nutrition: brief ~120 tok (всегда) / deep ~200 tok (при food-контексте) |
| L3 | Training Intel: brief ~150 tok (всегда) / deep ~250 tok (при training-контексте) |
| L4 | AI Intelligence (~200 tok): weekly digest, observations, trends — ВСЕГДА |
| L4 Intelligence | Еженедельный AI-дайджест, обновляется воскресенье в 21:30 |

## Классификатор сообщений
| Keyword group | Words |
|---------------|-------|
| health | боль, болит, травм, добавк, витамин… |
| food | поел, съел, питание, калор, белок… |
| training | тренировк, упражнен, жим, приседан… |

## Метрики
| Term | Meaning |
|------|---------|
| PR | Personal Record (личный рекорд) |
| SCORE | Exercise score = overload×0.4 + consistency×0.3 + alignment×0.3; замена при < 4.0 |
| fitness_score | Общая физическая форма = pushups×0.35 + squats×0.35 + plank×0.30 (0-100) |
| streak | Серия дней активности |

## Таблицы БД
| Table | What |
|-------|------|
| user_profile | Основной профиль (объединяет user_fitness_metrics и user_health) |
| workouts | Тренировки пользователя |
| exercise_results | Результаты по упражнениям с is_personal_record |
| personal_records | Рекорды (weight > time > reps, авто-определение) |
| nutrition_log | Журнал питания (upsert по user_id+date) |
| nutrition_insights | AI-рекомендации по питанию |
| daily_summary | AI-сводка дня (генерируется ночью) |
| memory_athlete | L0 память |
| memory_nutrition | L2 память |
| memory_training | L3 память |
| memory_intelligence | L4 память |
| reminders | Напоминания (заменила notification_state) |
| training_plan | (Фаза 8) Персонализированный план тренировок |
| user_fitness_metrics | (Фаза 8) endurance/strength/flexibility scores, max_pushups, etc. |
| monthly_summary | (Фаза 8) Месячная аналитика |

## Команды бота
| Command | Meaning |
|---------|---------|
| /start | Запуск / онбординг |
| /stop [N] | Пауза напоминаний на N дней (параметр пока не реализован) |
| /stats | Статистика |
| /mode | Смена режима MAX/LIGHT |
| /help | Помощь |
| /reset | Сброс данных |
| /profile | Показ профиля (травмы, локация, КБЖУ-цель) |
| /export | Экспорт CSV (тренировки + метрики за год, 2 файла) |
| /plan | (Фаза 8) План тренировок на неделю |
| /test | (Фаза 8) Фитнес-тестирование |
| /admin | (Фаза 8) Только для ADMIN_USER_ID |

## Scheduler jobs
| Job | When |
|-----|------|
| L4 Intelligence | Воскресенье 21:30 |
| daily_summary | Каждую ночь (DAILY_SUMMARY_TIME) |
| monthly_summary | 1-го числа в 09:00 (Фаза 8) |
| weekly_plan | Воскресенье на следующую неделю (Фаза 8) |
| nudges | Ежедневно утром (Фаза 8) |

## Фаза 8 — Proactive Nudges (типы)
| Nudge | Trigger |
|-------|---------|
| 🔥 Streak alert | «3 дня до рекорда стрика» |
| 📉 Drop alert | «3 дня без тренировки, обычно тренируешься по вторникам» |
| 💪 PR approaching | «В прошлый раз жал 80кг. Попробуй 82.5?» |
| 😴 Recovery nudge | «Сон < 6ч последние 3 дня — снижаю интенсивность» |
| 🎯 Goal progress | «50% пути до цели» |

## Внешние ресурсы
| Resource | URL |
|----------|-----|
| EatCount-Bot | https://github.com/GopkoDev/EatCount-Bot (FatSecret API) |
| Notion ROADMAP | https://www.notion.so/31c8fb7a86e3812a8e20d04186ebebe9 |
| Фаза 7 | https://www.notion.so/31d8fb7a86e381dd8b3ae60dc4f880d6 |
| Фаза 8 | https://www.notion.so/31e8fb7a86e38125af07c36c826cfbd3 |
| Аудит | https://www.notion.so/31d8fb7a86e3818c82edee3833d48ab7 |
