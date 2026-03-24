"""
tests/test_personal_insights.py — Тесты модуля персональных корреляций.

Покрывает:
  PI-1  _group_avg — корректное разбиение на группы
  PI-2  _group_avg — возвращает None при нехватке данных (меньше MIN_GROUP_SIZE)
  PI-3  _group_avg — возвращает None если одна из групп пустая
  PI-4  _effect_pct — корректный расчёт процентной разницы
  PI-5  _effect_pct — zero division guard (lower=0)
  PI-6  _insight_sleep — возвращает текст при значимой корреляции
  PI-7  _insight_sleep — возвращает None при слабой разнице (<8%)
  PI-8  _insight_sleep — возвращает None при обратной зависимости
  PI-9  _insight_sleep — возвращает None при нехватке данных
  PI-10 _insight_protein — возвращает текст при значимой корреляции
  PI-11 _insight_protein — возвращает None если нет цели по белку
  PI-12 _insight_rest — возвращает текст при значимой корреляции
  PI-13 _insight_rest — возвращает None при обратной зависимости
  PI-14 compute_personal_insight — приоритет сон > белок > отдых
  PI-15 compute_personal_insight — None если нет значимых паттернов
  PI-16 format_insight_message — содержит ключевые маркеры
  PI-17 _get_rest_days_intensity_pairs — корректный подсчёт дней отдыха
"""
import datetime
import pytest
from unittest.mock import patch, MagicMock

from scheduler.personal_insights import (
    _group_avg,
    _effect_pct,
    _insight_sleep,
    _insight_protein,
    _insight_rest,
    _get_rest_days_intensity_pairs,
    compute_personal_insight,
    format_insight_message,
    MIN_GROUP_SIZE,
    MIN_EFFECT_PCT,
    SLEEP_THRESHOLD,
)


# ─── PI-1: _group_avg — нормальное разбиение ─────────────────────────────────

def test_group_avg_splits_correctly():
    """Пары разбиваются по threshold, avg считается правильно."""
    # 6 выше threshold=8.0 (avg=9), 6 ниже (avg=5)
    pairs = [(8.0, 9), (8.5, 9), (9.0, 9), (8.0, 9), (8.5, 9), (9.0, 9),
             (7.9, 5), (7.0, 5), (6.5, 5), (7.9, 5), (7.0, 5), (6.5, 5)]
    result = _group_avg(pairs, threshold=8.0)
    assert result is not None
    avg_hi, n_hi, avg_lo, n_lo = result
    assert abs(avg_hi - 9.0) < 0.01
    assert abs(avg_lo - 5.0) < 0.01
    assert n_hi == 6
    assert n_lo == 6


# ─── PI-2: _group_avg — мало данных в одной группе ───────────────────────────

def test_group_avg_returns_none_if_insufficient():
    """Возвращает None если одна из групп меньше MIN_GROUP_SIZE."""
    # Только 3 «выше» — меньше MIN_GROUP_SIZE=5
    pairs = [(8.0, 9), (8.5, 8), (9.0, 8),             # 3 выше
             (7.0, 5), (6.5, 5), (7.5, 4), (7.2, 4), (7.1, 5)]  # 5 ниже
    result = _group_avg(pairs, threshold=8.0)
    assert result is None


# ─── PI-3: _group_avg — пустая группа ────────────────────────────────────────

def test_group_avg_returns_none_if_group_empty():
    """Возвращает None если все пары в одной группе."""
    pairs = [(8.0, 7)] * 10  # все выше threshold
    result = _group_avg(pairs, threshold=5.0)
    assert result is None


# ─── PI-4: _effect_pct — корректный расчёт ───────────────────────────────────

def test_effect_pct_correct():
    assert abs(_effect_pct(8.0, 7.0) - 14.28) < 0.1
    assert abs(_effect_pct(9.0, 7.5) - 20.0) < 0.01


def test_effect_pct_zero_when_equal():
    assert _effect_pct(5.0, 5.0) == 0.0


# ─── PI-5: _effect_pct — защита от деления на ноль ───────────────────────────

def test_effect_pct_zero_division_guard():
    assert _effect_pct(5.0, 0.0) == 0.0


# ─── Вспомогательный builder ─────────────────────────────────────────────────

def _make_pairs(hi_value: float, hi_intensity: int,
                lo_value: float, lo_intensity: int,
                n: int = 6) -> list[tuple[float, int]]:
    """Создаёт n пар «выше threshold» с hi_intensity и n пар «ниже» с lo_intensity."""
    return ([(hi_value, hi_intensity)] * n +
            [(lo_value, lo_intensity)] * n)


# ─── PI-6: _insight_sleep — значимая корреляция ───────────────────────────────

def test_insight_sleep_returns_text_when_significant():
    """Возвращает строку если сон≥7.5ч коррелирует с высокой интенсивностью."""
    pairs = _make_pairs(hi_value=8.0, hi_intensity=9,
                        lo_value=6.5, lo_intensity=7)  # +28% разница

    with patch("scheduler.personal_insights._get_sleep_intensity_pairs", return_value=pairs):
        result = _insight_sleep(user_id=1)

    assert result is not None
    assert isinstance(result, str)
    assert "%" in result
    assert "сна" in result.lower() or "сон" in result.lower()


# ─── PI-7: _insight_sleep — слабая разница ────────────────────────────────────

def test_insight_sleep_none_if_weak_effect():
    """Возвращает None если разница <8%."""
    # avg_hi=7.7, avg_lo=7.5 → ~2.6%
    pairs = _make_pairs(hi_value=8.0, hi_intensity=8,
                        lo_value=6.5, lo_intensity=7)  # +14%? no — let me craft
    # 8 и 7.4 → ~8.1% — borderline. Use 8 and 8 for <8%
    pairs = _make_pairs(hi_value=8.0, hi_intensity=8,
                        lo_value=6.5, lo_intensity=8)  # 0% разница

    with patch("scheduler.personal_insights._get_sleep_intensity_pairs", return_value=pairs):
        result = _insight_sleep(user_id=1)

    assert result is None


# ─── PI-8: _insight_sleep — обратная зависимость ─────────────────────────────

def test_insight_sleep_none_if_reversed():
    """Возвращает None если плохой сон коррелирует с ЛУЧШЕЙ интенсивностью (обратная)."""
    pairs = _make_pairs(hi_value=8.0, hi_intensity=6,   # много сна → низкая инт.
                        lo_value=6.5, lo_intensity=9)   # мало сна → высокая инт.

    with patch("scheduler.personal_insights._get_sleep_intensity_pairs", return_value=pairs):
        result = _insight_sleep(user_id=1)

    assert result is None


# ─── PI-9: _insight_sleep — нет данных ────────────────────────────────────────

def test_insight_sleep_none_if_no_data():
    """Возвращает None при пустом списке."""
    with patch("scheduler.personal_insights._get_sleep_intensity_pairs", return_value=[]):
        result = _insight_sleep(user_id=1)
    assert result is None


# ─── PI-10: _insight_protein — значимая корреляция ───────────────────────────

def test_insight_protein_returns_text_when_significant():
    """Возвращает строку если попадание в цель по белку коррелирует с интенсивностью."""
    goal = 130
    # Выше порога (117г+): avg 8.5; ниже: avg 6.5 → +30%
    pairs = _make_pairs(hi_value=130.0, hi_intensity=9,
                        lo_value=80.0,  lo_intensity=6)

    with patch("scheduler.personal_insights._get_protein_goal", return_value=goal):
        with patch("scheduler.personal_insights._get_protein_intensity_pairs", return_value=pairs):
            result = _insight_protein(user_id=1)

    assert result is not None
    assert "белку" in result or "белок" in result or f"{goal}" in result


# ─── PI-11: _insight_protein — нет цели ──────────────────────────────────────

def test_insight_protein_none_if_no_goal():
    """Возвращает None если цель по белку не задана."""
    with patch("scheduler.personal_insights._get_protein_goal", return_value=None):
        result = _insight_protein(user_id=1)
    assert result is None


# ─── PI-12: _insight_rest — значимая корреляция ──────────────────────────────

def test_insight_rest_returns_text_when_significant():
    """Возвращает строку если 2+ дня отдыха коррелируют с высокой интенсивностью."""
    pairs = _make_pairs(hi_value=2.0, hi_intensity=9,   # 2+ дня отдыха → высокая
                        lo_value=0.0, lo_intensity=6)   # 0 дней → ниже

    with patch("scheduler.personal_insights._get_rest_days_intensity_pairs", return_value=pairs):
        result = _insight_rest(user_id=1)

    assert result is not None
    assert "отдыха" in result or "отдых" in result


# ─── PI-13: _insight_rest — обратная зависимость ─────────────────────────────

def test_insight_rest_none_if_reversed():
    """Возвращает None если меньше отдыха → лучше (не интересный инсайт)."""
    pairs = _make_pairs(hi_value=2.0, hi_intensity=6,
                        lo_value=0.0, lo_intensity=9)

    with patch("scheduler.personal_insights._get_rest_days_intensity_pairs", return_value=pairs):
        result = _insight_rest(user_id=1)

    assert result is None


# ─── PI-14: compute_personal_insight — приоритет ─────────────────────────────

def test_compute_personal_insight_priority_sleep_first():
    """Если и сон, и белок дают инсайт — приоритет у сна."""
    sleep_text  = "сон-инсайт (mock)"
    protein_text = "белок-инсайт (mock)"

    with patch("scheduler.personal_insights._insight_sleep", return_value=sleep_text):
        with patch("scheduler.personal_insights._insight_protein", return_value=protein_text):
            result = compute_personal_insight(user_id=1)

    assert result == sleep_text


def test_compute_personal_insight_falls_back_to_protein():
    """Если сон не даёт инсайт — берёт белок."""
    protein_text = "белок-инсайт (mock)"

    with patch("scheduler.personal_insights._insight_sleep", return_value=None):
        with patch("scheduler.personal_insights._insight_protein", return_value=protein_text):
            result = compute_personal_insight(user_id=1)

    assert result == protein_text


def test_compute_personal_insight_falls_back_to_rest():
    """Если сон и белок не дают инсайт — берёт отдых."""
    rest_text = "отдых-инсайт (mock)"

    with patch("scheduler.personal_insights._insight_sleep", return_value=None):
        with patch("scheduler.personal_insights._insight_protein", return_value=None):
            with patch("scheduler.personal_insights._insight_rest", return_value=rest_text):
                result = compute_personal_insight(user_id=1)

    assert result == rest_text


# ─── PI-15: compute_personal_insight — нет паттернов ─────────────────────────

def test_compute_personal_insight_none_if_all_fail():
    """Возвращает None если ни один инсайт не нашёлся."""
    with patch("scheduler.personal_insights._insight_sleep", return_value=None):
        with patch("scheduler.personal_insights._insight_protein", return_value=None):
            with patch("scheduler.personal_insights._insight_rest", return_value=None):
                result = compute_personal_insight(user_id=1)

    assert result is None


# ─── PI-16: format_insight_message ────────────────────────────────────────────

def test_format_insight_message_contains_markers():
    """Сообщение содержит заголовок, разделитель, текст инсайта и footer."""
    text = "После 7.5+ ч сна интенсивность на 15% выше"
    msg = format_insight_message(text)

    assert "💡" in msg
    assert "Паттерн" in msg
    assert text in msg
    assert "━" in msg
    assert "данных" in msg.lower()


def test_format_insight_message_is_string():
    """Всегда возвращает строку."""
    result = format_insight_message("test")
    assert isinstance(result, str)
    assert len(result) > 0


# ─── PI-17: _get_rest_days_intensity_pairs ────────────────────────────────────

def test_get_rest_days_pairs_correct_gap():
    """Правильно считает дни между тренировками из реальных строк БД."""
    # Мокаем возврат из БД: 3 тренировки с разными интервалами
    import sqlite3
    today = datetime.date.today()
    d0 = today - datetime.timedelta(days=10)
    d1 = today - datetime.timedelta(days=7)   # 2 дня отдыха (gap=2)
    d2 = today - datetime.timedelta(days=6)   # 0 дней отдыха (gap=0)

    mock_rows = [
        {"date": d0.isoformat(), "intensity": 7, "type": "strength"},
        {"date": d1.isoformat(), "intensity": 8, "type": "strength"},
        {"date": d2.isoformat(), "intensity": 6, "type": "strength"},
    ]

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = mock_rows

    with patch("scheduler.personal_insights.get_connection", return_value=mock_conn):
        pairs = _get_rest_days_intensity_pairs(user_id=1)

    assert len(pairs) == 2
    assert pairs[0] == (2, 8)   # gap=2 дня, intensity=8
    assert pairs[1] == (0, 6)   # gap=0 дней, intensity=6


def test_get_rest_days_pairs_empty_if_single_workout():
    """Возвращает пустой список если тренировка только одна."""
    mock_rows = [{"date": "2026-01-01", "intensity": 7, "type": "strength"}]

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = mock_rows

    with patch("scheduler.personal_insights.get_connection", return_value=mock_conn):
        pairs = _get_rest_days_intensity_pairs(user_id=1)

    assert pairs == []


def test_get_rest_days_pairs_no_negative_gap():
    """gap никогда не бывает отрицательным (дата назад — защита)."""
    # Одинаковая дата (gap должен быть 0, не -1)
    today = datetime.date.today().isoformat()
    mock_rows = [
        {"date": today, "intensity": 7, "type": "strength"},
        {"date": today, "intensity": 8, "type": "strength"},  # тот же день
    ]

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = mock_rows

    with patch("scheduler.personal_insights.get_connection", return_value=mock_conn):
        pairs = _get_rest_days_intensity_pairs(user_id=1)

    assert all(gap >= 0 for gap, _ in pairs)
