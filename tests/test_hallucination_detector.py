"""
tests/test_hallucination_detector.py

Покрывает `ai/hallucination_rules.py:detect_expected_tools` — data-driven
движок детекции пропущенных write-tools (BC-1).

Архитектура: для каждого правила из TOOL_DETECTION_RULES — параметризованный
набор позитивных кейсов (триггер должен сработать) и негативных кейсов
(триггер НЕ должен сработать). Лишние срабатывания так же критичны как
пропущенные — false-positive шлёт спам в админ-чат.
"""
import pytest

from ai.hallucination_rules import (
    detect_expected_tools,
    TOOL_DETECTION_RULES,
    RESPONSE_ACKS,
)


# ─────────────────────────────────────────────────────────────────────────────
# Sanity: набор правил содержит ожидаемые 7 tools
# ─────────────────────────────────────────────────────────────────────────────

def test_rules_cover_seven_tools():
    expected = {
        "save_workout", "save_metrics", "save_nutrition",
        "save_exercise_result", "set_personal_record",
        "update_athlete_card", "save_training_plan",
    }
    actual = {r.tool for r in TOOL_DETECTION_RULES}
    assert actual == expected, f"Mismatch in rule coverage: {actual} != {expected}"


def test_save_episode_not_in_rules():
    """save_episode намеренно не детектируется — субъективно."""
    assert "save_episode" not in {r.tool for r in TOOL_DETECTION_RULES}


def test_award_xp_not_in_rules():
    """award_xp намеренно не детектируется — авто-начисляется в save_workout."""
    assert "award_xp" not in {r.tool for r in TOOL_DETECTION_RULES}


# ─────────────────────────────────────────────────────────────────────────────
# Robustness: пустые / None-входы не падают
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("user_msg, final_text", [
    ("", ""),
    ("", "что-то"),
    ("привет", ""),
    (None, "ответ"),
])
def test_empty_inputs_dont_crash(user_msg, final_text):
    result = detect_expected_tools(user_msg or "", final_text or "")
    assert isinstance(result, list)


# ─────────────────────────────────────────────────────────────────────────────
# Позитивные кейсы — каждое правило должно ловить характерные фразы
# ─────────────────────────────────────────────────────────────────────────────

# Формат: (user_msg, final_text, expected_tool)
POSITIVE_CASES = [
    # ─── save_nutrition ────────────────────────────────────────────────────
    ("Съел сегодня 200 г курицы и рис", "", "save_nutrition"),
    ("На обед была паста с курицей", "", "save_nutrition"),
    ("Выпил 2 литра воды и поел овсянки", "", "save_nutrition"),
    ("Я тут булку с сыром",
     "Записал твой завтрак, продолжай в том же духе",
     "save_nutrition"),  # косвенный матч через RESPONSE_ACKS + objects

    # ─── save_workout ──────────────────────────────────────────────────────
    ("Сегодня потренировался в зале час", "", "save_workout"),
    ("Только что закрыл тренировку, силовая на ноги", "", "save_workout"),
    ("Закончил тренировку, отжался 50 раз", "", "save_workout"),

    # ─── save_metrics ──────────────────────────────────────────────────────
    ("Поспал 7 часов", "", "save_metrics"),
    ("Сейчас 82 кг, вешу больше чем неделю назад", "", "save_metrics"),
    ("Вчера прошёл 12000 шагов", "", "save_metrics"),

    # ─── save_exercise_result ──────────────────────────────────────────────
    ("Жим лёжа 80 кг × 5", "", "save_exercise_result"),
    ("Присед 100 на 8", "", "save_exercise_result"),
    ("Сделал 4 подхода по 12 повторов на брусьях", "", "save_exercise_result"),

    # ─── set_personal_record ───────────────────────────────────────────────
    ("Новый рекорд в жиме!", "", "set_personal_record"),
    ("Это PR, никогда столько не поднимал", "", "set_personal_record"),
    ("Побил свой рекорд на становой", "", "set_personal_record"),

    # ─── update_athlete_card ───────────────────────────────────────────────
    ("Моя цель поменялась — хочу набрать массу", "", "update_athlete_card"),
    ("Теперь занимаюсь дома, в зал не хожу", "", "update_athlete_card"),
    ("Перешёл на домашний режим тренировок", "", "update_athlete_card"),

    # ─── save_training_plan ────────────────────────────────────────────────
    ("Составь мне план на следующую неделю", "", "save_training_plan"),
    ("Перестрой план — у меня нет времени по средам", "", "save_training_plan"),
    ("Убери приседания из плана, болит колено", "", "save_training_plan"),
]


@pytest.mark.parametrize("user_msg, final_text, expected_tool", POSITIVE_CASES)
def test_positive_cases(user_msg, final_text, expected_tool):
    """Триггер ДОЛЖЕН сработать."""
    result = detect_expected_tools(user_msg, final_text)
    assert expected_tool in result, (
        f"Expected '{expected_tool}' in {result} for message: {user_msg!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Негативные кейсы — нейтральные фразы НЕ должны триггерить
# ─────────────────────────────────────────────────────────────────────────────

# Формат: (user_msg, final_text, tool_that_must_NOT_trigger)
NEGATIVE_CASES = [
    # ─── save_nutrition не должен ловить ───────────────────────────────────
    ("Привет, как дела?", "", "save_nutrition"),
    ("Расскажи про белки и жиры в курице", "", "save_nutrition"),  # инфо-вопрос, не запись
    ("Что ел Шварценеггер на сушке?", "Информация про питание", "save_nutrition"),

    # ─── save_workout не должен ловить ─────────────────────────────────────
    ("Как правильно делать жим?", "", "save_workout"),
    ("Сколько калорий сжигает кардио?", "", "save_workout"),
    ("Завтра пойду тренироваться", "", "save_workout"),  # будущее, не запись факта

    # ─── save_metrics не должен ловить ─────────────────────────────────────
    ("Какой нормальный сон для взрослого?", "", "save_metrics"),
    ("У меня болит спина", "", "save_metrics"),

    # ─── save_exercise_result не должен ловить ─────────────────────────────
    ("Расскажи про правильную технику жима", "", "save_exercise_result"),
    ("Сколько подходов делать новичку?", "", "save_exercise_result"),

    # ─── set_personal_record не должен ловить ──────────────────────────────
    ("Какой мировой рекорд в становой?", "", "set_personal_record"),
    ("У Эдди Холла рекорд 500 кг", "", "set_personal_record"),

    # ─── update_athlete_card не должен ловить ──────────────────────────────
    ("Какие у меня цели по плану?", "Твоя цель — поддержание формы", "update_athlete_card"),
    ("Где лучше тренироваться — дома или в зале?", "", "update_athlete_card"),

    # ─── save_training_plan не должен ловить ───────────────────────────────
    ("Что в моём плане на сегодня?", "", "save_training_plan"),
    ("Расскажи как составляются хорошие программы тренировок", "", "save_training_plan"),
]


@pytest.mark.parametrize("user_msg, final_text, forbidden_tool", NEGATIVE_CASES)
def test_negative_cases(user_msg, final_text, forbidden_tool):
    """Триггер НЕ должен сработать (false-positive — это спам админ-чата)."""
    result = detect_expected_tools(user_msg, final_text)
    assert forbidden_tool not in result, (
        f"False positive: '{forbidden_tool}' triggered on: {user_msg!r} -> {result}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Гибридный матч: response_acks + user_objects
# ─────────────────────────────────────────────────────────────────────────────

def test_hybrid_match_requires_both():
    """
    Только ack без объекта или только объект без ack — не триггерит.
    Оба нужны вместе для гибридного матча save_nutrition.
    """
    # Только ack — не триггер (нет объекта еды в user_msg)
    assert "save_nutrition" not in detect_expected_tools(
        "привет, как дела?", "Записал!"
    )
    # Только объект, без ack — не триггер (бот не подтвердил)
    assert "save_nutrition" not in detect_expected_tools(
        "у меня дома есть пицца", "Хорошо, что сказал"
    )
    # Оба — триггер
    assert "save_nutrition" in detect_expected_tools(
        "съел пиццу", "Записал, не забывай про белок"
    )


def test_response_acks_pattern_set_nonempty():
    """RESPONSE_ACKS не должен быть пустым — иначе гибридный матч сломан."""
    assert len(RESPONSE_ACKS) >= 3


# ─────────────────────────────────────────────────────────────────────────────
# Множественный матч: одна фраза может триггерить несколько правил
# ─────────────────────────────────────────────────────────────────────────────

def test_multi_tool_message():
    """«Поел и потренировался» — должно сработать оба правила."""
    result = detect_expected_tools(
        "Сегодня поел овсянки и потренировался час", ""
    )
    assert "save_nutrition" in result
    assert "save_workout" in result
