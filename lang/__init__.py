"""
lang/ — Lightweight i18n for the trainer bot.
Switch language via LANG env var ("ru" | "uk").
"""
import importlib
from config import LANG

_module = importlib.import_module(f"lang.{LANG}")
STRINGS: dict = _module.STRINGS

def t(key: str, **kwargs) -> str:
    """Get translated string, with optional format args."""
    s = STRINGS.get(key, f"[missing:{key}]")
    return s.format(**kwargs) if kwargs else s


def t_list(key: str) -> list[str]:
    """Get translated list (e.g. fact pools)."""
    val = STRINGS.get(key)
    if isinstance(val, list):
        return val
    return []


def days_word(n: int) -> str:
    return _module.days_word(n)


def workouts_word(n: int) -> str:
    return _module.workouts_word(n)
