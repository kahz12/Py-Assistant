"""
plugins/weather_plugin.py -- Plugin de clima con OpenWeatherMap.

Proporciona informacion meteorologica actual y pronostico via la API
de OpenWeatherMap (gratuita con registro).

Requiere:
    OPENWEATHER_KEY en .env

Acciones:
    current  : Clima actual en una ciudad.
    forecast : Pronostico de los proximos 3 dias.
    help     : Lista las acciones disponibles.
"""
import os
import urllib.request
import urllib.parse
import json
from loguru import logger

SKILL_NAME = "weather"
SKILL_DISPLAY_NAME = "Clima (OpenWeatherMap)"
SKILL_DESCRIPTION = (
    "Consulta el clima actual o pronostico de cualquier ciudad "
    "usando la API de OpenWeatherMap."
)
VERSION = "1.1.0"
AUTHOR = "local"
REQUIRES_ENV = ["OPENWEATHER_KEY"]
ACTIONS = ["current", "forecast", "help"]

_API_BASE = "https://api.openweathermap.org/data/2.5"
_ICONS = {
    "Clear": "☀️", "Clouds": "☁️", "Rain": "🌧️", "Drizzle": "🌦️",
    "Thunderstorm": "⛈️", "Snow": "❄️", "Mist": "🌫️",
    "Fog": "🌫️", "Haze": "🌫️", "Smoke": "🌫️",
}


def _get_key() -> str:
    key = os.environ.get("OPENWEATHER_KEY", "")
    if not key:
        raise ValueError(
            "Falta OPENWEATHER_KEY en .env. "
            "Registrate gratis en openweathermap.org para obtenerla."
        )
    return key


def _fetch(endpoint: str, params: dict) -> dict:
    """Realiza una peticion a la API de OpenWeatherMap."""
    params["appid"] = _get_key()
    params["units"] = "metric"
    params["lang"] = "es"
    qs = urllib.parse.urlencode(params)
    url = f"{_API_BASE}/{endpoint}?{qs}"
    logger.debug(f"[weather] GET {url.replace(params['appid'], '***')}")
    with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _format_current(data: dict) -> str:
    city = data["name"]
    country = data["sys"]["country"]
    main = data["main"]
    weather = data["weather"][0]
    wind = data.get("wind", {})
    icon = _ICONS.get(weather["main"], "🌡️")

    return (
        f"{icon} **{city}, {country}**\n"
        f"Condicion: {weather['description'].capitalize()}\n"
        f"Temperatura: {main['temp']:.1f}°C "
        f"(sensacion: {main['feels_like']:.1f}°C)\n"
        f"Humedad: {main['humidity']}%\n"
        f"Viento: {wind.get('speed', 0):.1f} m/s\n"
        f"Presion: {main['pressure']} hPa"
    )


def _format_forecast(data: dict) -> str:
    city = data["city"]["name"]
    country = data["city"]["country"]

    # Agrupar por dia (solo 1 registro por dia, el de mediodia)
    days: dict[str, dict] = {}
    for item in data["list"]:
        date = item["dt_txt"][:10]
        hour = int(item["dt_txt"][11:13])
        if date not in days or abs(hour - 12) < abs(int(days[date]["dt_txt"][11:13]) - 12):
            days[date] = item

    lines = [f"☁️ **Pronostico — {city}, {country}** (3 dias)\n"]
    for i, (date, item) in enumerate(list(days.items())[:3], 1):
        w = item["weather"][0]
        icon = _ICONS.get(w["main"], "🌡️")
        t = item["main"]
        lines.append(
            f"  **Dia {i} ({date}):** {icon} {w['description'].capitalize()} | "
            f"{t['temp_min']:.0f}°C — {t['temp_max']:.0f}°C"
        )
    return "\n".join(lines)


def execute(action: str = "current", city: str = "Caracas", **kwargs) -> str:
    """
    Ejecuta una consulta meteorologica.

    Args:
        action: "current" (default), "forecast" o "help".
        city: Ciudad a consultar (default: "Caracas").
        **kwargs: Argumentos extra ignorados.
    """
    action = action.lower().strip()

    if action == "help":
        return (
            "**Plugin Clima — Acciones disponibles:**\n"
            "  • current [city=<ciudad>] — Clima actual\n"
            "  • forecast [city=<ciudad>] — Pronostico 3 dias\n\n"
            "Ejemplo: action='current', city='Madrid'"
        )

    try:
        if action == "current":
            data = _fetch("weather", {"q": city})
            return _format_current(data)

        elif action == "forecast":
            data = _fetch("forecast", {"q": city, "cnt": 24})
            return _format_forecast(data)

        else:
            return (
                f"Accion '{action}' no soportada. "
                f"Usa: {', '.join(ACTIONS[:-1])}."
            )

    except ValueError as e:
        return str(e)
    except Exception as e:
        logger.error(f"[weather] Error consultando clima: {e}")
        return f"No se pudo obtener el clima para '{city}'. Error: {str(e)}"
