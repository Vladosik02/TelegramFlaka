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
# Экспорт: полный список инструментов для передачи в Anthropic API
# ───────────────────────────────────────────────────────────────────────────
ALL_TOOLS: List[dict] = [
    TOOL_SAVE_WORKOUT,
    TOOL_SAVE_METRICS,
    TOOL_SAVE_NUTRITION,
    TOOL_SAVE_EXERCISE_RESULT,
    TOOL_SET_PERSONAL_RECORD,
    TOOL_UPDATE_ATHLETE_CARD,
    TOOL_GET_WEEKLY_STATS,
    TOOL_SAVE_EPISODE,
    TOOL_AWARD_XP,
]

# Словарь для быстрого lookup по имени
TOOL_BY_NAME: dict = {t["name"]: t for t in ALL_TOOLS}
