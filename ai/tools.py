"""
ai/tools.py — Определения инструментов (Tool Use) для Claude API.

Фаза 10.1 — Intelligent Agent.
Claude получает набор инструментов и вызывает их вместо regex-парсинга.
Все инструменты используют strict=True для гарантированного соответствия схеме.

Инструменты:
  1. save_workout          — записать тренировку
  2. save_metrics          — записать метрики (вес, сон, энергия, настроение, вода, шаги)
  3. save_nutrition        — записать питание (КБЖУ за день)
  4. save_exercise_result  — записать результат конкретного упражнения
  5. set_personal_record   — установить личный рекорд
  6. update_athlete_card   — обновить карточку атлета (цель, уровень, дни, место)
  7. get_weekly_stats      — получить статистику за неделю
  8. save_episode          — сохранить эпизод в эпизодическую память
  9. award_xp              — начислить XP (только для внутреннего использования)
  14. get_workout_prediction — прогноз тренировки на сегодня (веса, повторы, RPE)
"""

from typing import List

# ───────────────────────────────────────────────────────────────────────────
# 1. save_workout
# ───────────────────────────────────────────────────────────────────────────
TOOL_SAVE_WORKOUT = {
    "name": "save_workout",
    "description": (
        "Сохраняет тренировку пользователя в базу данных. "
        "Вызывай когда пользователь сообщает о выполненной тренировке: "
        "силовая, кардио, растяжка, HIIT или любая другая активность. "
        "Если пользователь описывает только один тип активности — заполни type."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "workout_type": {
                "type": "string",
                "enum": ["strength", "cardio", "stretch", "hiit", "sport", "other"],
                "description": "Тип тренировки"
            },
            "duration_min": {
                "type": "integer",
                "minimum": 1,
                "maximum": 600,
                "description": "Длительность в минутах"
            },
            "intensity": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "description": "Субъективная интенсивность от 1 (лёгкая) до 10 (максимальная)"
            },
            "exercises": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Список упражнений. Пример: ['жим лёжа', 'приседания', 'планка']"
            },
            "notes": {
                "type": "string",
                "description": "Дополнительные заметки о тренировке (необязательно)"
            }
        },
        "required": ["workout_type"],
        "additionalProperties": False
    }
}

# ───────────────────────────────────────────────────────────────────────────
# 2. save_metrics
# ───────────────────────────────────────────────────────────────────────────
TOOL_SAVE_METRICS = {
    "name": "save_metrics",
    "description": (
        "Сохраняет физические метрики пользователя: вес, сон, энергия, настроение, вода, шаги. "
        "Вызывай когда пользователь сообщает о самочувствии, весе, сне или дневной активности. "
        "Передавай только те поля, которые явно упомянуты."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "weight_kg": {
                "type": "number",
                "minimum": 30.0,
                "maximum": 300.0,
                "description": "Вес в килограммах"
            },
            "sleep_hours": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 24.0,
                "description": "Часов сна прошлой ночью"
            },
            "energy": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5,
                "description": "Уровень энергии 1-5 (1=выжатый, 5=энергичный)"
            },
            "mood": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5,
                "description": "Настроение 1-5 (1=плохое, 5=отличное)"
            },
            "water_liters": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 20.0,
                "description": "Выпито воды в литрах"
            },
            "steps": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100000,
                "description": "Количество шагов за день"
            },
            "notes": {
                "type": "string",
                "description": "Дополнительные заметки о самочувствии"
            }
        },
        "required": [],
        "additionalProperties": False
    }
}

# ───────────────────────────────────────────────────────────────────────────
# 3. save_nutrition
# ───────────────────────────────────────────────────────────────────────────
TOOL_SAVE_NUTRITION = {
    "name": "save_nutrition",
    "description": (
        "Сохраняет данные о питании за день: калории, белки, жиры, углеводы, вода. "
        "Вызывай когда пользователь сообщает что ел, сколько калорий съел, "
        "или называет КБЖУ. Используй только явно указанные значения."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "calories": {
                "type": "integer",
                "minimum": 0,
                "maximum": 15000,
                "description": "Калории (ккал) за день"
            },
            "protein_g": {
                "type": "number",
                "minimum": 0.0,
                "description": "Белки в граммах"
            },
            "fat_g": {
                "type": "number",
                "minimum": 0.0,
                "description": "Жиры в граммах"
            },
            "carbs_g": {
                "type": "number",
                "minimum": 0.0,
                "description": "Углеводы в граммах"
            },
            "water_ml": {
                "type": "integer",
                "minimum": 0,
                "description": "Вода в миллилитрах"
            },
            "meal_notes": {
                "type": "string",
                "description": "Краткое описание еды (что ел)"
            },
            "junk_food": {
                "type": "boolean",
                "description": "True если было нездоровое питание (фастфуд, сладкое и т.д.)"
            }
        },
        "required": [],
        "additionalProperties": False
    }
}

# ───────────────────────────────────────────────────────────────────────────
# 4. save_exercise_result
# ───────────────────────────────────────────────────────────────────────────
TOOL_SAVE_EXERCISE_RESULT = {
    "name": "save_exercise_result",
    "description": (
        "Сохраняет результат конкретного упражнения: подходы, повторения, вес, время. "
        "Вызывай когда пользователь называет конкретные параметры упражнения. "
        "Например: 'сделал 3x10 жим лёжа 80кг' или 'планка 2 минуты'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "exercise_name": {
                "type": "string",
                "description": "Название упражнения. Пример: 'жим лёжа', 'приседания со штангой'"
            },
            "sets": {
                "type": "integer",
                "minimum": 1,
                "maximum": 50,
                "description": "Количество подходов"
            },
            "reps": {
                "type": "integer",
                "minimum": 1,
                "maximum": 1000,
                "description": "Количество повторений (в одном подходе или суммарно)"
            },
            "weight_kg": {
                "type": "number",
                "minimum": 0.0,
                "description": "Вес отягощения в кг"
            },
            "duration_sec": {
                "type": "integer",
                "minimum": 1,
                "description": "Длительность в секундах (для планки, кардио)"
            },
            "notes": {
                "type": "string",
                "description": "Заметки (необязательно)"
            }
        },
        "required": ["exercise_name"],
        "additionalProperties": False
    }
}

# ───────────────────────────────────────────────────────────────────────────
# 5. set_personal_record
# ───────────────────────────────────────────────────────────────────────────
TOOL_SET_PERSONAL_RECORD = {
    "name": "set_personal_record",
    "description": (
        "Устанавливает личный рекорд (PR) для упражнения. "
        "Вызывай ТОЛЬКО когда пользователь явно упоминает новый рекорд, "
        "слова 'новый рекорд', 'PR', 'личный лучший', 'побил', или "
        "когда новый результат явно превышает предыдущий в разговоре."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "exercise_name": {
                "type": "string",
                "description": "Название упражнения"
            },
            "record_value": {
                "type": "number",
                "description": "Значение рекорда (повторы, секунды, или кг)"
            },
            "record_type": {
                "type": "string",
                "enum": ["reps", "time", "weight"],
                "description": "Тип рекорда: reps=повторения, time=время(сек), weight=вес(кг)"
            },
            "notes": {
                "type": "string",
                "description": "Контекст рекорда (необязательно)"
            }
        },
        "required": ["exercise_name", "record_value", "record_type"],
        "additionalProperties": False
    }
}

# ───────────────────────────────────────────────────────────────────────────
# 6. update_athlete_card
# ───────────────────────────────────────────────────────────────────────────
TOOL_UPDATE_ATHLETE_CARD = {
    "name": "update_athlete_card",
    "description": (
        "Обновляет карточку атлета: цель, уровень подготовки, предпочитаемые дни тренировок, "
        "место тренировок, травмы/ограничения. "
        "Вызывай когда пользователь меняет свои предпочтения в свободном диалоге. "
        "Например: 'хочу тренироваться по вторникам и пятницам', "
        "'начинаю работать на массу', 'у меня болит колено'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "goal": {
                "type": "string",
                "enum": ["похудеть", "набрать массу", "выносливость", "общая форма", "пик формы"],
                "description": "Тренировочная цель"
            },
            "fitness_level": {
                "type": "string",
                "enum": ["beginner", "intermediate", "advanced"],
                "description": "Уровень подготовки"
            },
            "preferred_days": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
                },
                "description": "Предпочитаемые дни тренировок (список сокращений)"
            },
            "training_location": {
                "type": "string",
                "enum": ["home", "gym", "outdoor", "flexible"],
                "description": "Место тренировок"
            },
            "injuries": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Список травм или ограничений. Пример: ['боль в колене', 'спина']"
            },
            "season": {
                "type": "string",
                "enum": ["bulk", "cut", "maintain", "peak"],
                "description": "Текущий тренировочный сезон/фаза"
            },
            "equipment": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Список доступного оборудования. Примеры: "
                    "['турник', 'гантели 20кг', 'штанга', 'гири 16кг', 'резинки', 'скакалка']. "
                    "Пустой список [] = только вес тела. "
                    "Вызывай когда пользователь говорит что у него есть/нет оборудования."
                )
            }
        },
        "required": [],
        "additionalProperties": False
    }
}

# ───────────────────────────────────────────────────────────────────────────
# 7. get_weekly_stats
# ───────────────────────────────────────────────────────────────────────────
TOOL_GET_WEEKLY_STATS = {
    "name": "get_weekly_stats",
    "description": (
        "Получает статистику пользователя за последние N дней из базы данных. "
        "Вызывай когда пользователь спрашивает о своём прогрессе, статистике, "
        "'как я тренировался', 'сколько тренировок за неделю', 'мои результаты'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "minimum": 1,
                "maximum": 90,
                "description": "Количество дней назад. По умолчанию 7.",
                "default": 7
            },
            "include_nutrition": {
                "type": "boolean",
                "description": "Включать ли данные о питании. По умолчанию False.",
                "default": False
            }
        },
        "required": [],
        "additionalProperties": False
    }
}

# ───────────────────────────────────────────────────────────────────────────
# 8. save_episode
# ───────────────────────────────────────────────────────────────────────────
TOOL_SAVE_EPISODE = {
    "name": "save_episode",
    "description": (
        "Сохраняет важный эпизод в долгосрочную эпизодическую память бота. "
        "Вызывай для ключевых моментов: личные рекорды, важные инсайты пользователя, "
        "изменения целей, достижения, эмоциональные моменты. "
        "Не вызывай для рутинных сообщений."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "episode_type": {
                "type": "string",
                "enum": [
                    "personal_record",
                    "insight",
                    "goal_update",
                    "conversation",
                    "milestone"
                ],
                "description": "Тип эпизода"
            },
            "summary": {
                "type": "string",
                "description": "Краткое описание (1-2 предложения). Будет использоваться в контексте AI."
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Теги для поиска. Пример: ['strength', 'squat', 'pr', 'motivation']"
            },
            "importance": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "description": "Важность эпизода 1-10 (10=критично важно)"
            }
        },
        "required": ["episode_type", "summary"],
        "additionalProperties": False
    }
}

# ───────────────────────────────────────────────────────────────────────────
# 9. award_xp  (внутренний — Claude вызывает явно)
# ───────────────────────────────────────────────────────────────────────────
TOOL_AWARD_XP = {
    "name": "award_xp",
    "description": (
        "Начисляет XP-очки пользователю за достижение. "
        "Вызывай ТОЛЬКО в связке с другими инструментами (save_workout, set_personal_record). "
        "Стандартные значения: тренировка=100 XP, личный рекорд=200 XP, "
        "серия 7 дней=150 XP, 30 дней=500 XP."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "xp_amount": {
                "type": "integer",
                "minimum": 1,
                "maximum": 1000,
                "description": "Количество XP для начисления"
            },
            "reason": {
                "type": "string",
                "enum": [
                    "workout",
                    "personal_record",
                    "streak_7",
                    "streak_30",
                    "nutrition_perfect",
                    "fitness_test",
                    "milestone",
                    "bonus"
                ],
                "description": "Причина начисления XP"
            },
            "detail": {
                "type": "string",
                "description": "Описание (необязательно). Пример: 'жим лёжа 90кг'"
            }
        },
        "required": ["xp_amount", "reason"],
        "additionalProperties": False
    }
}


# ───────────────────────────────────────────────────────────────────────────
# 10. get_nutrition_history (Agent Fix — READ)
# ───────────────────────────────────────────────────────────────────────────
TOOL_GET_NUTRITION_HISTORY = {
    "name": "get_nutrition_history",
    "description": (
        "Получает историю питания пользователя за последние N дней. "
        "Вызывай когда пользователь спрашивает про питание, КБЖУ, "
        "что ел вчера/на неделе/за месяц, средние калории."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "minimum": 1,
                "maximum": 90,
                "description": "Количество дней назад. По умолчанию 7."
            }
        },
        "required": [],
        "additionalProperties": False
    }
}

# ───────────────────────────────────────────────────────────────────────────
# 11. get_personal_records (Agent Fix — READ)
# ───────────────────────────────────────────────────────────────────────────
TOOL_GET_PERSONAL_RECORDS = {
    "name": "get_personal_records",
    "description": (
        "Получает все личные рекорды пользователя из базы данных. "
        "Вызывай при вопросах типа 'какие у меня рекорды', "
        "'сколько я жму максимум', 'мои лучшие результаты', 'мои PR'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "exercise_name": {
                "type": "string",
                "description": "Фильтр по названию упражнения (необязательно)"
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 20,
                "description": "Максимум записей. По умолчанию 10."
            }
        },
        "required": [],
        "additionalProperties": False
    }
}

# ───────────────────────────────────────────────────────────────────────────
# 12. get_current_plan (Agent Fix — READ)
# ───────────────────────────────────────────────────────────────────────────
TOOL_GET_CURRENT_PLAN = {
    "name": "get_current_plan",
    "description": (
        "Получает текущий активный план тренировок на неделю из базы данных. "
        "Вызывай когда пользователь спрашивает 'что делать сегодня', "
        "'какой план на неделю', 'покажи тренировку на среду', 'мой план'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False
    }
}

# ───────────────────────────────────────────────────────────────────────────
# 13. get_user_profile (Agent Fix — READ)
# ───────────────────────────────────────────────────────────────────────────
TOOL_GET_USER_PROFILE = {
    "name": "get_user_profile",
    "description": (
        "Получает полный профиль пользователя из базы данных: "
        "цель, уровень, вес, рост, возраст, место тренировок, "
        "предпочитаемые дни, сезон, травмы, XP, уровень, стрик. "
        "Вызывай когда нужны точные актуальные данные профиля."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False
    }
}


# ───────────────────────────────────────────────────────────────────────────
# 14. get_workout_prediction (Workout Prediction — предиктивный брифинг)
# ───────────────────────────────────────────────────────────────────────────
TOOL_GET_WORKOUT_PREDICTION = {
    "name": "get_workout_prediction",
    "description": (
        "Получает AI-прогноз тренировки на сегодня: рекомендуемые веса, "
        "повторения, RPE-потолок для каждого упражнения из активного плана. "
        "Учитывает Recovery Score, фазу мезоцикла, последние результаты и сон. "
        "Вызывай когда пользователь спрашивает 'что делать сегодня', "
        "'какие веса брать', 'мой прогноз', 'подскажи нагрузку', "
        "'с каким весом работать', или перед тренировкой."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False
    }
}

# ───────────────────────────────────────────────────────────────────────────
# 15. save_training_plan (WRITE — сохранение/обновление плана по запросу)
# ───────────────────────────────────────────────────────────────────────────
TOOL_SAVE_TRAINING_PLAN = {
    "name": "save_training_plan",
    "description": (
        "Сохраняет или обновляет тренировочный план в базе данных. "
        "ОБЯЗАТЕЛЬНО вызывай этот инструмент ПОСЛЕ того как составил или скорректировал план: "
        "когда пользователь просит 'составь план', 'перестрой план', 'убери гантели из плана', "
        "'измени расписание', 'переделай план', 'скорректируй программу' и т.п. "
        "Без вызова этого инструмента план существует только в сообщении, но НЕ сохраняется в БД."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "plan_json": {
                "type": "string",
                "description": (
                    "JSON-строка с массивом из 7 дней. Каждый день: "
                    "{\"date\": \"YYYY-MM-DD\", \"weekday\": \"Пн\", \"type\": \"strength\", "
                    "\"label\": \"...\", \"exercises\": [...], \"duration_min\": 60, "
                    "\"completed\": false, \"ai_note\": \"...\"}. "
                    "Типы: strength | cardio | hiit | mobility | rest | recovery."
                )
            },
            "rationale": {
                "type": "string",
                "description": "Краткое обоснование плана (1-3 предложения): что учтено, почему такой набор."
            },
            "week_start": {
                "type": "string",
                "description": (
                    "Дата начала недели в формате YYYY-MM-DD (понедельник). "
                    "Если не указано — используется следующий понедельник."
                )
            }
        },
        "required": ["plan_json"],
        "additionalProperties": False
    }
}

# ───────────────────────────────────────────────────────────────────────────
# Экспорт: полный список инструментов для передачи в Anthropic API
# ───────────────────────────────────────────────────────────────────────────
ALL_TOOLS: List[dict] = [
    # WRITE (9)
    TOOL_SAVE_WORKOUT,
    TOOL_SAVE_METRICS,
    TOOL_SAVE_NUTRITION,
    TOOL_SAVE_EXERCISE_RESULT,
    TOOL_SET_PERSONAL_RECORD,
    TOOL_UPDATE_ATHLETE_CARD,
    TOOL_SAVE_EPISODE,
    TOOL_AWARD_XP,
    TOOL_SAVE_TRAINING_PLAN,
    # READ (6)
    TOOL_GET_WEEKLY_STATS,
    TOOL_GET_NUTRITION_HISTORY,
    TOOL_GET_PERSONAL_RECORDS,
    TOOL_GET_CURRENT_PLAN,
    TOOL_GET_USER_PROFILE,
    TOOL_GET_WORKOUT_PREDICTION,
]

# Словарь для быстрого lookup по имени
TOOL_BY_NAME: dict = {t["name"]: t for t in ALL_TOOLS}


# ═══════════════════════════════════════════════════════════════════════════════
# TOKEN OPTIMIZATION (Фаза 17) — умный выбор инструментов
# ═══════════════════════════════════════════════════════════════════════════════
#
# Проблема: ALL_TOOLS (15 инструментов) занимают ~3000 токенов на каждый запрос.
# Для записи еды нужны только save_nutrition + save_episode (~476 tok).
# Экономия: ~2500 токенов input per request только на tool definitions.
#
# Дополнительно: CRUD-запросы (запись данных без вопросов) переключаются на
# Haiku вместо Sonnet — 20× дешевле. Итого экономия ~40-50× на рутине.
# ─────────────────────────────────────────────────────────────────────────────

# Минимальные наборы по тегу
_TOOLS_FOOD: List[dict] = [
    TOOL_SAVE_NUTRITION,
    TOOL_SAVE_EPISODE,
]
_TOOLS_TRAINING: List[dict] = [
    TOOL_SAVE_WORKOUT,
    TOOL_SAVE_EXERCISE_RESULT,
    TOOL_SET_PERSONAL_RECORD,
    TOOL_AWARD_XP,
    TOOL_SAVE_EPISODE,
]
_TOOLS_METRICS: List[dict] = [
    TOOL_SAVE_METRICS,
]
_TOOLS_ANALYTICS: List[dict] = [
    TOOL_GET_WEEKLY_STATS,
    TOOL_GET_NUTRITION_HISTORY,
    TOOL_GET_PERSONAL_RECORDS,
    TOOL_GET_USER_PROFILE,
]
_TOOLS_PLAN: List[dict] = [
    TOOL_GET_CURRENT_PLAN,
    TOOL_GET_WORKOUT_PREDICTION,
    TOOL_SAVE_TRAINING_PLAN,
]
_TOOLS_HEALTH: List[dict] = [
    TOOL_UPDATE_ATHLETE_CARD,
    TOOL_SAVE_EPISODE,
]

# Weekly report: только чтение + сохранение эпизода (no write tools)
# Экономия: 13 tools (3502 tok) → 5 tools (~700 tok) = ~2800 tok/запрос
_TOOLS_WEEKLY_REPORT: List[dict] = [
    TOOL_GET_WEEKLY_STATS,
    TOOL_GET_NUTRITION_HISTORY,
    TOOL_GET_PERSONAL_RECORDS,
    TOOL_GET_USER_PROFILE,
    TOOL_SAVE_EPISODE,   # для сохранения недельных инсайтов в долгосрочную память
]

_TOOLS_BY_TAG: dict[str, List[dict]] = {
    "food":      _TOOLS_FOOD,
    "training":  _TOOLS_TRAINING,
    "metrics":   _TOOLS_METRICS,
    "analytics": _TOOLS_ANALYTICS,
    "plan":      _TOOLS_PLAN,
    "health":    _TOOLS_HEALTH,
}

# Маркеры вопроса / сложного запроса — форсируют полный пайплайн
_QUESTION_MARKERS: tuple[str, ...] = (
    "?",
    "как ", "почему", "что ", "когда", "сколько",
    "расскажи", "объясни", "покажи", "помоги",
    "посоветуй", "сравни", "анализ", "составь",
    "придумай", "предложи", "порекомендуй",
    "хочу знать",
)

# Теги «чистой» записи данных — без аналитики, плана, здоровья
_CRUD_ONLY_TAGS: frozenset = frozenset({"food", "training", "metrics"})


def get_tools_for_tags(tags: frozenset) -> List[dict]:
    """
    Возвращает минимальный набор tools для текущего контекста.

    Примеры экономии (tokens per request):
      food only:     save_nutrition + save_episode       → 476 tok  (было 3064)
      training only: 5 tools                             → 1142 tok (было 3064)
      metrics only:  save_metrics                        → 278 tok  (было 3064)
      analytics:     4 read-tools                        → 557 tok  (было 3064)

    Если теги неизвестны или пусты → возвращаем ALL_TOOLS (безопасный fallback).
    """
    if not tags:
        return ALL_TOOLS
    seen: set[str] = set()
    result: List[dict] = []
    # Обходим теги в фиксированном порядке для воспроизводимости
    for tag in ("food", "training", "metrics", "analytics", "plan", "health"):
        if tag not in tags:
            continue
        for tool in _TOOLS_BY_TAG.get(tag, []):
            if tool["name"] not in seen:
                seen.add(tool["name"])
                result.append(tool)
    return result if result else ALL_TOOLS


def classify_request_tier(tags: frozenset, text: str) -> str:
    """
    Классифицирует запрос по сложности:

    'crud' — простая запись данных:
      • Только food/training/metrics теги (без analytics/plan/health)
      • Нет вопросительных маркеров
      • Текст ≤ 200 символов
      → Haiku + slim context + filtered tools (~40-50× дешевле Sonnet + ALL_TOOLS)

    'full' — полный пайплайн:
      • analytics/plan/health теги присутствуют
      • Вопрос или сложный запрос
      • Длинный текст (> 200 символов)
      → Sonnet + полный контекст + ALL_TOOLS
    """
    if not tags:
        return "full"
    if tags - _CRUD_ONLY_TAGS:          # есть analytics/plan/health → full
        return "full"
    t = text.lower()
    if any(m in t for m in _QUESTION_MARKERS):
        return "full"
    if len(text) > 200:
        return "full"
    return "crud"
