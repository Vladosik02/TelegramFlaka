"""
ai/morph.py — Синглтон MorphAnalyzer для лемматизации русскоязычных текстов.

Используется в:
  - ai/context_builder.py (_classify_message)
  - ai/response_parser.py (is_nutrition_report, is_workout_report, is_metrics_report)

Стратегия:
  1. Токенизация по границам слов (re.findall, только кириллица/латиница).
  2. Лемматизация каждого токена через pymorphy3 (берём first parse — лучший score).
  3. Совпадение лемм пользовательского текста с предвычисленными лемма-сетами триггеров.

  Ключевое свойство: build_lemma_set() лемматизирует ТРИГГЕРНЫЕ слова тем же анализатором,
  что и пользовательский ввод. Поэтому даже «нестандартные» леммы (кроссфит→кроссфита,
  кето→кеть) остаются консистентными: одно и то же слово даёт одну и ту же лемму
  с обеих сторон сравнения.

Fallback: если pymorphy3 не установлен, lemmatize_text() возвращает frozenset токенов
  без лемматизации — функциональность деградирует до простого поиска подстрок-слов,
  но код не падает.
"""
import re
import logging

logger = logging.getLogger(__name__)

_morph = None          # Синглтон MorphAnalyzer
_morph_available = None  # None = не проверяли, True/False = результат


def get_morph():
    """Возвращает синглтон MorphAnalyzer. Создаёт при первом вызове."""
    global _morph, _morph_available
    if _morph_available is None:
        try:
            import pymorphy3
            _morph = pymorphy3.MorphAnalyzer()
            _morph_available = True
            logger.info("pymorphy3 MorphAnalyzer инициализирован")
        except ImportError:
            _morph_available = False
            logger.warning(
                "pymorphy3 не установлен — классификатор работает в fallback-режиме "
                "(возможны ложные срабатывания при подстроковом поиске). "
                "Установите: pip install pymorphy3"
            )
    return _morph


def lemmatize_text(text: str) -> frozenset:
    """
    Токенизирует текст по границам слов и лемматизирует каждый токен.
    Возвращает frozenset лемм в нижнем регистре.

    Fallback (pymorphy3 недоступен): возвращает frozenset токенов без лемматизации.

    Args:
        text: входной текст (любой регистр).

    Returns:
        frozenset строк — нормализованные формы всех слов из текста.
    """
    # Только кириллица и латиница, без цифр и пунктуации
    tokens = re.findall(r'[а-яёa-z]+', text.lower())
    morph = get_morph()
    if morph is None:
        return frozenset(tokens)
    return frozenset(morph.parse(tok)[0].normal_form for tok in tokens)


def build_lemma_set(words: tuple | list | set) -> frozenset:
    """
    Принимает список человекочитаемых слов-триггеров, лемматизирует каждый
    и возвращает frozenset лемм. Вызывается один раз при загрузке модуля.

    Многословные фразы ("г белка", "на следующей неделе") разбиваются на токены —
    каждый токен добавляется в множество отдельно.

    Fallback (pymorphy3 недоступен): возвращает frozenset самих слов в нижнем регистре.

    Args:
        words: список/кортеж слов и коротких фраз.

    Returns:
        frozenset лемм, готовых для сравнения с результатом lemmatize_text().
    """
    morph = get_morph()
    result = set()
    for word in words:
        tokens = re.findall(r'[а-яёa-z]+', word.lower())
        for tok in tokens:
            if morph is None:
                result.add(tok)
            else:
                result.add(morph.parse(tok)[0].normal_form)
    return frozenset(result)
