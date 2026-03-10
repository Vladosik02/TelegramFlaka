# Memory

## Me
Vladislav (Vlad), разработчик персонального Telegram-бота-тренера.

## Projects
| Name | What | Status |
|------|------|--------|
| **Trainer Bot** | Telegram-бот личный тренер (MAX/LIGHT режимы, AI на Anthropic API) | 🟢 Работает на VPS (Hetzner CX11) |
| **Фаза 7** | Beyond MVP: питание, exercise_results, онбординг, БД v2 | 🟡 В разработке поверх работающего бота |
| **Фаза 8** | Analytics, Plans & Proactive AI | ⏳ Планирование |

→ Детали: memory/projects/

## Terms
| Term | Meaning |
|------|---------|
| MAX / LIGHT | Два режима бота: MAX — активный/интенсивный, LIGHT — лёгкий/поддерживающий |
| Алекс | Имя персонажа бота (ещё не добавлено в промпты — баг) |
| L0–L4 | Слои памяти бота: L0=карточка атлета, L1=здоровье, L2=питание, L3=тренировки, L4=AI-аналитика |
| context_builder | Файл `ai/context_builder.py` — сборка контекста для AI |
| db_updates | JSON-ответ от AI с инструкциями что записать в БД |
| writer.py | Единая точка записи от AI в БД |
| PR | Personal Record (личный рекорд упражнения) |
| SCORE | Метрика упражнения: overload×0.4 + consistency×0.3 + alignment×0.3; порог замены < 4.0 |
| daily_summary | AI-сводка дня, генерируется ночью через APScheduler |
| L4 Intelligence | Еженедельный AI-дайджест (воскресенье 21:30) |
| нудж / nudge | Проактивное сообщение пользователю по паттернам поведения |
| /plan | Команда для показа плана тренировок на неделю (Фаза 8) |
| /test | Команда фитнес-тестирования (Фаза 8) |
| /admin | Команда для владельца бота |
| EatCount-Bot | GitHub-бот с FatSecret API — источник интеграции питания |
| fitness_score | Метрика формы: pushups×0.35 + squats×0.35 + plank×0.30 |

→ Полный глоссарий: memory/glossary.md

## Key Notion Pages
| Page | URL |
|------|-----|
| ROADMAP | https://www.notion.so/31c8fb7a86e3812a8e20d04186ebebe9 |
| Фаза 7 — Beyond MVP | https://www.notion.so/31d8fb7a86e381dd8b3ae60dc4f880d6 |
| Фаза 8 — Analytics & AI | https://www.notion.so/31e8fb7a86e38125af07c36c826cfbd3 |
| Аудит проекта | https://www.notion.so/31d8fb7a86e3818c82edee3833d48ab7 |

## Stack
- Python + python-telegram-bot 20.x
- Anthropic API (Claude) — MODEL: claude-sonnet-4-20250514
- SQLite (`data/flaka.db`) — 4-layer memory schema
- APScheduler (AsyncIOScheduler)
- Docker (multi-stage, non-root, 256MB limit)
- Google Cloud VM (SSH, Linux) — продакшн
- GitHub: github.com/Vladosik02/TelegramFlaka
- GitHub Actions CI/CD

## Current Blockers
- 🔴 Имя «Алекс» не добавлено в промпты
- 🔴 FatSecret API не интегрирован (отложено на Фазу 8+)
- 🔴 `/stop [N дней]` без параметра — команда работает, но параметр N не обрабатывается
- 🟡 Профильные данные из свободного диалога не парсятся в memory_training (только structured-парсеры)
