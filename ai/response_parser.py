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

    # ─── Сон ─────────────────────────────────────────────────────────────────
    # "спал 7ч", "спал 7 часов", "поспал 7.5", "проспала 8", "7 часов сна"
    sleep = (
        re.search(r'(?:спал|спала)\s*(\d+(?:[.,]\d+)?)\s*(?:ч|час|часов|часа)', text_lower)
        or re.search(r'(?:поспал|поспала|проспал|проспала)\s*(\d+(?:[.,]\d+)?)', text_lower)
        or re.search(r'(\d+(?:[.,]\d+)?)\s*(?:часов|часа)\s+сна', text_lower)
        or re.search(r'сон\s*[:\-]?\s*(\d+(?:[.,]\d+)?)', text_lower)
    )
    if sleep:
        val = float(sleep.group(1).replace(",", "."))
        if 2.0 <= val <= 24.0:
            result["sleep_hours"] = val

    # ─── Вес ─────────────────────────────────────────────────────────────────
    # "82 кг", "вес 82", "вешу 80.5", "весил 79"
    weight = (
        re.search(r'(\d+(?:[.,]\d+)?)\s*кг', text_lower)
        or re.search(r'(?:вес|вешу|весил|весила|весит)\s*[:\-]?\s*(\d{2,3}(?:[.,]\d+)?)', text_lower)
    )
    if weight:
        val = float(weight.group(1).replace(",", "."))
        if 30.0 <= val <= 250.0:
            result["weight_kg"] = val

    # ─── Вода ────────────────────────────────────────────────────────────────
    # "2л", "2 литра", "1.5 литров", "выпил 2 литра воды"
    water = (
        re.search(r'(\d+(?:[.,]\d+)?)\s*л(?:итр(?:а|ов)?)?(?=[\s\.,;!?]|$)', text_lower)
        or re.search(r'(?:выпил|выпила|пил|пила)[^\d]*(\d+(?:[.,]\d+)?)\s*л', text_lower)
    )
    if water:
        val = float(water.group(1).replace(",", "."))
        if 0.1 <= val <= 10.0:
            result["water_liters"] = val

    # ─── Шаги ────────────────────────────────────────────────────────────────
    # "8000 шагов", "прошёл 10000", "прошла 6500 шагов"
    steps = (
        re.search(r'(\d{4,6})\s*шаг(?:ов|и|а)?', text_lower)
        or re.search(r'(?:прошёл|прошла|пройдено|прошагал|прошагала)\s*(\d{4,6})', text_lower)
    )
    if steps:
        result["steps"] = int(steps.group(1))

    # ─── Энергия (числовая: "энергия 4", "энергия: 3") ───────────────────────
    energy_num = re.search(r'энерги[яю]\s*[:\-]?\s*(\d)', text_lower)
    if energy_num:
        val = int(energy_num.group(1))
        if 1 <= val <= 5:
            result["energy"] = val
    else:
        # Словесная шкала
        energy_map = {
            "совсем устал": 1, "совсем устала": 1, "плохо": 1,
            "устал": 2, "устала": 2,
            "нормально": 3,
            "хорошо": 4, "бодр": 4, "активен": 4, "активна": 4,
            "отлично": 5, "энергичен": 5, "энергична": 5,
        }
        for word, level in energy_map.items():
            if word in text_lower:
                result["energy"] = level
                break

    # ─── Настроение числовое: "настроение 4", "настроение: 3" ────────────────
    mood_num = re.search(r'настроени[еюя]\s*[:\-]?\s*(\d)', text_lower)
    if mood_num:
        val = int(mood_num.group(1))
        if 1 <= val <= 5:
            result["mood"] = val

    return result


def is_nutrition_report(text: str) -> bool:
    """Содержит ли сообщение данные о питании."""
    keywords = [
        "поел", "съел", "поела", "съела", "завтрак", "обед", "ужин", "перекус",
        "ккал", "калорий", "калориям", "г белка", "питание", "рацион",
        "голодал", "голодала", "не ел", "не ела",
        "покушал", "покушала", "пообедал", "поужинал",
    ]
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)


def parse_nutrition_from_message(text: str) -> dict:
    """
    Извлекает данные о питании из свободного текста.
    Возвращает dict с найденными полями для nutrition_log.
    """
    result = {}
    text_lower = text.lower()

    # ─── Калории ────────────────────────────────────────────────────────────
    cal = re.search(r'(\d{3,5})\s*(?:ккал|калор|kcal|cal)', text_lower)
    if cal:
        val = int(cal.group(1))
        if 300 <= val <= 10000:
            result["calories"] = val

    # ─── Белок ──────────────────────────────────────────────────────────────
    prot = re.search(
        r'(\d{1,3})\s*г\s*белка|белк(?:а|ов)?\s*(\d{1,3})\s*г', text_lower
    )
    if prot:
        val_str = prot.group(1) or prot.group(2)
        if val_str:
            result["protein_g"] = float(val_str)

    # ─── Жиры ───────────────────────────────────────────────────────────────
    fat = re.search(
        r'(\d{1,3})\s*г\s*жир|жир(?:ов|а)?\s*(\d{1,3})\s*г', text_lower
    )
    if fat:
        val_str = fat.group(1) or fat.group(2)
        if val_str:
            result["fat_g"] = float(val_str)

    # ─── Углеводы ───────────────────────────────────────────────────────────
    carb = re.search(
        r'(\d{1,3})\s*г\s*углевод|углевод(?:ов|а)?\s*(\d{1,3})\s*г', text_lower
    )
    if carb:
        val_str = carb.group(1) or carb.group(2)
        if val_str:
            result["carbs_g"] = float(val_str)

    # ─── Вода (в питании — в мл) ─────────────────────────────────────────
    water_l = re.search(r'(\d+(?:[.,]\d+)?)\s*л(?:итр)?', text_lower)
    if water_l:
        liters = float(water_l.group(1).replace(",", "."))
        if 0.1 <= liters <= 10:
            result["water_ml"] = int(liters * 1000)

    # ─── Фастфуд / нездоровое ───────────────────────────────────────────────
    junk_words = [
        "фастфуд", "макдак", "макдональд", "пицца", "бургер", "чипсы",
        "шаурма", "картошка фри", "кока-кола", "колу", "сникерс", "читмил",
    ]
    if any(w in text_lower for w in junk_words):
        result["junk_food"] = 1

    # ─── Заметки ─────────────────────────────────────────────────────────────
    result["meal_notes"] = text[:300]

    return result


def _parse_exercise_segment(seg: str) -> dict | None:
    """
    Пытается разобрать один сегмент текста как упражнение.
    Возвращает dict или None если ничего не нашёл.
    """
    seg_lower = seg.lower().strip()
    if len(seg_lower) < 3:
        return None

    result = {}

    # ─── Вес ────────────────────────────────────────────────────────────────
    weight_m = re.search(r'(\d+(?:[.,]\d+)?)\s*кг', seg_lower)
    if weight_m:
        result["weight_kg"] = float(weight_m.group(1).replace(",", "."))

    # ─── Подходы × Повторения: "3х10", "3x10", "3*10" ───────────────────────
    sx_m = re.search(r'(\d+)\s*[хxХX×*]\s*(\d+)', seg_lower)
    if sx_m:
        result["sets"] = int(sx_m.group(1))
        result["reps"] = int(sx_m.group(2))
    else:
        # "3 подхода по 10" или "3 подхода 10 повторений"
        sp_m = re.search(r'(\d+)\s*подход\w*\s+по\s+(\d+)', seg_lower)
        if sp_m:
            result["sets"] = int(sp_m.group(1))
            result["reps"] = int(sp_m.group(2))
        else:
            # просто "10 раз" / "10 повторений"
            reps_m = re.search(r'(\d+)\s*(?:раз|повтор)', seg_lower)
            if reps_m:
                result["reps"] = int(reps_m.group(1))

    # ─── Длительность: "60 сек", "3 мин" ────────────────────────────────────
    dur_m = re.search(r'(\d+)\s*(?:сек|секунд)', seg_lower)
    if dur_m:
        result["duration_sec"] = int(dur_m.group(1))
    else:
        dur_min = re.search(r'(\d+)\s*(?:мин|минут)', seg_lower)
        if dur_min:
            result["duration_sec"] = int(dur_min.group(1)) * 60

    # ─── Имя упражнения — убираем числовые паттерны, берём слова ────────────
    name_text = re.sub(
        r'\d+(?:[.,]\d+)?\s*кг|\d+\s*[хxХX×*]\s*\d+|\d+\s*подход\w*\s+по\s+\d+'
        r'|\d+\s*раз\w*|\d+\s*повтор\w*|\d+\s*(?:сек|секунд|мин|минут)',
        '', seg_lower
    ).strip(" ,.;-")
    name_text = re.sub(r'\s{2,}', ' ', name_text).strip()

    # Только если осталось хоть что-то похожее на название
    if len(name_text) < 2:
        return None

    # Нормализуем первую букву
    result["exercise_name"] = name_text.strip().capitalize()

    # Нужно хотя бы одно из: sets, reps, duration, weight
    if not any(k in result for k in ("sets", "reps", "duration_sec", "weight_kg")):
        return None

    return result


def parse_exercises_from_message(text: str) -> list[dict]:
    """
    Извлекает список упражнений из текста тренировки.
    Разбивает по разделителям, пробует распознать каждый сегмент.
    Каждый элемент: {exercise_name, sets?, reps?, weight_kg?, duration_sec?}
    """
    # Разбиваем по запятым, точкам с запятой, переносам, союзам, двоеточию
    segments = re.split(
        r'[,;:\n]|(?:\s+(?:потом|затем|после|далее|плюс|и ещё)\s+)',
        text, flags=re.IGNORECASE
    )
    # Слова-«обёртки» которые не являются упражнениями
    _SKIP_NAMES = {
        "потренировался", "потренировалась", "сделал", "сделала",
        "закончил", "закончила", "тренировка", "тренировался",
        "занимался", "занималась", "выполнил", "выполнила",
    }
    exercises = []
    for seg in segments:
        parsed = _parse_exercise_segment(seg.strip())
        if parsed:
            name_low = parsed.get("exercise_name", "").lower()
            if any(skip in name_low for skip in _SKIP_NAMES):
                continue
            exercises.append(parsed)
    return exercises


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
    keywords = [
        "спал", "спала", "поспал", "поспала", "проспал", "проспала",
        "вес", "кг", "вешу", "весил", "весила",
        "ккал", "вода", "шагов", "шаги", "шагал", "прошёл", "прошла",
        "пульс", "энергия", "настроение", "сон",
    ]
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)
