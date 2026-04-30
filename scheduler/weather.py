"""
scheduler/weather.py — Погодный контекст для утренних чек-инов и pre-workout.

Использует Open-Meteo API (бесплатный, без ключа).
Один GET-запрос в день на пользователя — кешируется в памяти.

Данные:
  - temperature_2m (°C)
  - apparent_temperature (°C) — «ощущается как»
  - precipitation (mm)
  - weather_code (WMO)
  - surface_pressure (hPa)
  - wind_speed_10m (km/h)

Влияние на тренировки (заложено в format_weather_context):
  - Давление < 1005 hPa → возможна вялость, головная боль
  - Температура < 5°C или > 30°C → учитывать при outdoor-тренировках
  - Дождь/снег → лучше тренироваться дома
"""
import logging
import datetime
import json
from urllib.request import urlopen, Request
from urllib.error import URLError
from typing import Optional

logger = logging.getLogger(__name__)

# ─── In-memory кеш: {user_id: {"date": "YYYY-MM-DD", "data": dict}} ───────
_weather_cache: dict[int, dict] = {}

# ─── WMO Weather Codes → человекочитаемые описания ─────────────────────────
_WMO_CODES = {
    0: "ясно ☀️",
    1: "преимущественно ясно 🌤",
    2: "переменная облачность ⛅",
    3: "пасмурно ☁️",
    45: "туман 🌫",
    48: "изморозь 🌫",
    51: "лёгкая морось 🌦",
    53: "морось 🌧",
    55: "сильная морось 🌧",
    61: "небольшой дождь 🌦",
    63: "дождь 🌧",
    65: "сильный дождь 🌧",
    66: "ледяной дождь 🌧❄️",
    67: "сильный ледяной дождь 🌧❄️",
    71: "небольшой снег 🌨",
    73: "снег 🌨",
    75: "сильный снег ❄️",
    77: "снежная крупа ❄️",
    80: "ливень 🌧",
    81: "сильный ливень 🌧",
    82: "ливень с градом ⛈",
    85: "снегопад 🌨",
    86: "сильный снегопад ❄️",
    95: "гроза ⛈",
    96: "гроза с градом ⛈",
    99: "сильная гроза с градом ⛈",
}

# ─── Дефолтные координаты (Варшава) — используются если у пользователя нет своих
DEFAULT_LAT = 52.23
DEFAULT_LON = 21.01
DEFAULT_CITY = "Варшава"


def _geocode_city(city: str) -> tuple[float | None, float | None]:
    """
    Геокодинг города через Open-Meteo Geocoding API (бесплатный, без ключа).
    Возвращает (lat, lon) или (None, None) при ошибке.
    """
    from urllib.parse import quote
    url = (
        f"https://geocoding-api.open-meteo.com/v1/search?"
        f"name={quote(city)}&count=1&language=ru&format=json"
    )
    try:
        req = Request(url, headers={"User-Agent": "TelegramFlaka/1.0"})
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        results = data.get("results", [])
        if results:
            return results[0]["latitude"], results[0]["longitude"]
        logger.warning(f"[WEATHER] Geocode: no results for '{city}'")
        return None, None
    except (URLError, json.JSONDecodeError, KeyError, OSError) as e:
        logger.warning(f"[WEATHER] Geocode failed for '{city}': {e}")
        return None, None


def _fetch_weather(lat: float, lon: float) -> Optional[dict]:
    """
    Запрашивает текущую погоду с Open-Meteo.
    Возвращает dict с данными или None при ошибке.
    Таймаут: 5 секунд.
    """
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&current=temperature_2m,apparent_temperature,precipitation,"
        f"weather_code,surface_pressure,wind_speed_10m"
        f"&timezone=auto"
        f"&forecast_days=1"
    )
    try:
        req = Request(url, headers={"User-Agent": "TelegramFlaka/1.0"})
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        current = data.get("current", {})
        if not current:
            logger.warning("[WEATHER] Empty 'current' in API response")
            return None
        return current
    except (URLError, json.JSONDecodeError, KeyError, OSError) as e:
        logger.warning(f"[WEATHER] API fetch failed: {e}")
        return None


def get_weather_for_user(user_id: int, lat: float = None,
                          lon: float = None) -> Optional[dict]:
    """
    Возвращает текущую погоду для пользователя.
    Кеширует на 1 день (по дате).

    Args:
        user_id: внутренний ID пользователя (не telegram_id)
        lat, lon: координаты (из memory_athlete или дефолт)

    Returns:
        dict с полями: temperature, apparent_temp, precipitation,
              weather_code, pressure, wind_speed
        или None при ошибке.
    """
    today_str = datetime.date.today().isoformat()

    # Проверяем кеш
    cached = _weather_cache.get(user_id)
    if cached and cached.get("date") == today_str:
        return cached["data"]

    # Используем дефолтные координаты если не заданы
    _lat = lat or DEFAULT_LAT
    _lon = lon or DEFAULT_LON

    raw = _fetch_weather(_lat, _lon)
    if not raw:
        return None

    result = {
        "temperature": raw.get("temperature_2m"),
        "apparent_temp": raw.get("apparent_temperature"),
        "precipitation": raw.get("precipitation", 0),
        "weather_code": raw.get("weather_code", 0),
        "pressure": raw.get("surface_pressure"),
        "wind_speed": raw.get("wind_speed_10m"),
    }

    # Кешируем
    _weather_cache[user_id] = {"date": today_str, "data": result}
    logger.info(
        f"[WEATHER] Fetched for user={user_id}: "
        f"{result['temperature']}°C, code={result['weather_code']}, "
        f"pressure={result['pressure']}hPa"
    )
    return result


def format_weather_text(weather: dict, city: str = None) -> str:
    """
    Форматирует погоду для утреннего чек-ина (одна строка, без markdown).

    Пример: "🌤 Варшава: +8°C (ощущается +5°C), переменная облачность, давление 1002 hPa ↓"
    """
    if not weather:
        return ""

    city_name = city or DEFAULT_CITY
    temp = weather.get("temperature")
    apparent = weather.get("apparent_temp")
    code = weather.get("weather_code", 0)
    pressure = weather.get("pressure")
    wind = weather.get("wind_speed")
    precip = weather.get("precipitation", 0)

    # Описание погоды
    description = _WMO_CODES.get(code, "")

    # Температура
    temp_str = f"{temp:+.0f}°C" if temp is not None else "?"
    parts = [f"{city_name}: {temp_str}"]

    if apparent is not None and temp is not None and abs(apparent - temp) >= 2:
        parts.append(f"(ощущается {apparent:+.0f}°C)")

    # Описание погоды (без эмодзи — они уже в _WMO_CODES)
    if description:
        parts.append(description)

    # Давление с индикатором (низкое давление влияет на самочувствие)
    if pressure is not None:
        if pressure < 1005:
            parts.append(f"давление {pressure:.0f} hPa ↓")
        elif pressure > 1025:
            parts.append(f"давление {pressure:.0f} hPa ↑")

    # Ветер (если сильный)
    if wind is not None and wind > 30:
        parts.append(f"ветер {wind:.0f} км/ч")

    return ", ".join(parts)


def format_weather_training_hint(weather: dict, training_location: str = "home") -> str:
    """
    Генерирует тренировочную подсказку на основе погоды.
    Возвращает пустую строку если подсказка не нужна.

    Используется в pre-workout reminder и утреннем контексте AI.
    """
    if not weather:
        return ""

    hints = []
    temp = weather.get("temperature")
    pressure = weather.get("pressure")
    precip = weather.get("precipitation", 0)
    code = weather.get("weather_code", 0)

    # Низкое давление → предупреждение
    if pressure is not None and pressure < 1005:
        hints.append(
            "Давление ниже нормы — возможна вялость и головная боль. "
            "Снизь рабочие веса на 5-10% и добавь разминочный подход"
        )

    # Дождь/снег → для outdoor тренировок
    if training_location == "outdoor":
        if precip > 0 or code >= 51:
            hints.append("Осадки на улице — лучше тренироваться дома")
        if temp is not None and temp < 5:
            hints.append(f"На улице {temp:+.0f}°C — удлини разминку вдвое")
        if temp is not None and temp > 30:
            hints.append(f"На улице {temp:+.0f}°C — пей больше воды, сократи интенсивность")

    # Жара для всех
    if temp is not None and temp > 30 and training_location != "outdoor":
        hints.append("Жарко — не забудь проветрить комнату перед тренировкой")

    # Холод + home: позитивный вайб
    if temp is not None and temp < 0 and training_location == "home":
        hints.append(f"На улице {temp:+.0f}°C — отличный повод остаться дома и потренироваться 💪")

    return ". ".join(hints) if hints else ""


def format_weather_context_for_ai(weather: dict, city: str = None) -> str:
    """
    Форматирует погоду для включения в AI-контекст (context_builder).
    Компактный формат для экономии токенов (~30-50 tok).
    """
    if not weather:
        return ""

    city_name = city or DEFAULT_CITY
    temp = weather.get("temperature")
    apparent = weather.get("apparent_temp")
    pressure = weather.get("pressure")
    code = weather.get("weather_code", 0)
    desc = _WMO_CODES.get(code, "").split(" ")[0] if code in _WMO_CODES else ""

    parts = [f"Погода ({city_name})"]
    if temp is not None:
        parts.append(f"{temp:+.0f}°C")
    if apparent is not None and temp is not None and abs(apparent - temp) >= 3:
        parts.append(f"ощущ. {apparent:+.0f}°C")
    if desc:
        parts.append(desc)
    if pressure is not None and pressure < 1005:
        parts.append(f"давление↓ {pressure:.0f}")
    elif pressure is not None and pressure > 1025:
        parts.append(f"давление↑ {pressure:.0f}")

    return ", ".join(parts)


def get_user_location(user_id: int) -> tuple[float | None, float | None, str | None]:
    """
    Возвращает (lat, lon, city) из memory_athlete для данного пользователя.
    Если не задано — (None, None, None).
    """
    from db.queries.memory import get_athlete_card
    card = get_athlete_card(user_id)
    if not card:
        return None, None, None
    return (
        card.get("weather_lat"),
        card.get("weather_lon"),
        card.get("weather_city"),
    )
