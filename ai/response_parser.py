"""
ai/response_parser.py — Извлечение структурированных данных из AI-ответов.
Парсит то, что пользователь написал, а не то, что ответил AI.
"""
import re
import logging

logger = logging.getLogger(__name__)


def parse_workout_from_message(text: str) -> dict:
    """
    Пытается извлечь данные тренировки из свободного текста.
    Возвращает dict с найденными полями.
    """
    result = {}
    text_lower = text.lower()

    # Продолжительность
    dur = re.search(r'(\d+)\s*(?:мин|минут|min)', text_lower)
    if dur:
        result["duration_min"] = int(dur.group(1))

    # Интенсивность (если сказал сам)
    intensity = re.search(r'интенсивность\s*[:\-]?\s*(\d+)', text_lower)
    if intensity:
        val = int(intensity.group(1))
        if 1 <= val <= 10:
            result["intensity"] = val

    # Тип тренировки
    type_map = {
        "бег": "cardio", "кардио": "cardio", "велосипед": "cardio",
        "силов": "strength", "жим": "strength", "присед": "strength",
        "тяга": "strength", "турник": "strength",
        "растяжка": "stretch", "йога": "stretch", "стретч": "stretch",
        "отдых": "rest", "не трениров": "rest", "выходной": "rest",
    }
    for keyword, wtype in type_map.items():
        if keyword in text_lower:
            result["type"] = wtype
            break

    # Завершённость
    if any(w in text_lower for w in ["не успел", "не дотренировал", "бросил", "не закончил"]):
        result["completed"] = False
    elif any(w in text_lower for w in ["сделал", "закончил", "потренировался", "выполнил", "завершил"]):
        result["completed"] = True

    result["notes"] = text[:500]  # Сохраняем оригинал
    return result


def parse_metrics_from_message(text: str) -> dict:
    """Извлекает метрики здоровья из текста."""
    result = {}
    text_lower = text.lower()

    # Сон
    sleep = re.search(r'спал\s*(\d+(?:[.,]\d+)?)\s*(?:ч|час)', text_lower)
    if sleep:
        result["sleep_hours"] = float(sleep.group(1).replace(",", "."))

    # Вес
    weight = re.search(r'(\d+(?:[.,]\d+)?)\s*кг', text_lower)
    if weight:
        result["weight_kg"] = float(weight.group(1).replace(",", "."))

    # Вода
    water = re.search(r'(\d+(?:[.,]\d+)?)\s*л(?:итр)', text_lower)
    if water:
        result["water_liters"] = float(water.group(1).replace(",", "."))

    # Шаги
    steps = re.search(r'(\d{4,6})\s*шаг', text_lower)
    if steps:
        result["steps"] = int(steps.group(1))

    # Энергия (слова)
    energy_map = {
        "отлично": 5, "хорошо": 4, "нормально": 3,
        "устал": 2, "совсем устал": 1, "плохо": 1,
        "бодр": 5, "активен": 4,
    }
    for word, level in energy_map.items():
        if word in text_lower:
            result["energy"] = level
            break

    return result


def detect_health_alert(text: str, keywords: list[str]) -> bool:
    """Проверяет ключевые слова безопасности."""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def is_workout_report(text: str) -> bool:
    """Содержит ли сообщение отчёт о тренировке."""
    keywords = [
        "потренировался", "сделал", "пробежал", "поднял", "жим",
        "присел", "турник", "км", "минут", "тренировка", "workout",
        "кардио", "бег", "велик", "плавал"
    ]
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)


def is_metrics_report(text: str) -> bool:
    """Содержит ли данные о здоровье."""
    keywords = ["спал", "вес", "кг", "ккал", "вода", "шагов", "шаги", "пульс"]
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)
