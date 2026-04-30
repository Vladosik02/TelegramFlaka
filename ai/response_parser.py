"""
ai/response_parser.py — Извлечение структурированных данных из AI-ответов.
Парсит то, что пользователь написал, а не то, что ответил AI.

Оставлены только функции, активно используемые в продакшне:
  - parse_exercises_from_message()  → db/writer.py
  - detect_health_alert()           → bot/handlers.py

Удалены в рамках очистки мёртвого кода (заменены Tool Use / Claude API):
  parse_workout_from_message, parse_metrics_from_message,
  is_nutrition_report, parse_nutrition_from_message,
  is_workout_report, is_metrics_report, 3 lemma-set-а.
"""
import re
import logging

logger = logging.getLogger(__name__)


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
