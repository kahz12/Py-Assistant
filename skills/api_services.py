"""
skills/api_services.py -- Integracion con APIs externas de datos y servicios.

APIs soportadas:
  - Google Maps (geocoding, direcciones, places) — requiere GOOGLE_MAPS_KEY
  - OpenWeatherMap (clima detallado, pronostico) — requiere OPENWEATHER_KEY
  - NewsAPI (noticias por tema/pais) — requiere NEWS_API_KEY
  - ExchangeRate (ya en api_client, expuesto aqui tambien)

Seguridad:
  - API keys desde variables de entorno (nunca hardcoded).
  - Solo HTTPS para APIs con key.
  - Rate limiting implicito via timeouts.
  - No expone API keys en respuestas/logs.

Interfaz del skill:
    SKILL_NAME = "api_services"
    execute(action, params=None) -> str
"""
import os
import json
import urllib.request
import urllib.parse
from loguru import logger

SKILL_NAME = "api_services"
SKILL_DESCRIPTION = "APIs externas: Google Maps, clima, noticias, finanzas."

REQUEST_TIMEOUT = 15


def execute(
    action: str,
    params: dict = None,
) -> str:
    """
    Punto de entrada principal del skill.

    Acciones:
      - 'geocode'      : Geocodifica una direccion (Google Maps).
      - 'directions'    : Obtiene ruta entre dos puntos (Google Maps).
      - 'places'        : Busca lugares cercanos (Google Maps).
      - 'weather_detail': Clima detallado (OpenWeatherMap).
      - 'forecast'      : Pronostico 5 dias (OpenWeatherMap).
      - 'news'          : Noticias por tema o pais (NewsAPI).
      - 'news_headlines': Titulares principales (NewsAPI).

    Args:
        action: Accion a ejecutar.
        params: Diccionario con parametros especificos de la accion.
    """
    params = params or {}

    actions = {
        "geocode": lambda: _geocode(params.get("address", "")),
        "directions": lambda: _directions(
            params.get("origin", ""),
            params.get("destination", ""),
            params.get("mode", "driving"),
        ),
        "places": lambda: _places(
            params.get("query", ""),
            params.get("location", ""),
        ),
        "weather_detail": lambda: _weather_owm(params.get("city", "")),
        "forecast": lambda: _forecast_owm(params.get("city", "")),
        "news": lambda: _news(
            params.get("query", ""),
            params.get("language", "es"),
        ),
        "news_headlines": lambda: _news_headlines(
            params.get("country", "co"),
            params.get("category", ""),
        ),
    }

    if action not in actions:
        available = ", ".join(actions.keys())
        return f"Accion no reconocida: {action}. Opciones: {available}"

    return actions[action]()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _api_get(url: str, headers: dict = None) -> dict:
    """GET request seguro. Retorna dict parseado o error."""
    req_headers = {"User-Agent": "AsistenteIA/1.0"}
    if headers:
        req_headers.update(headers)
    try:
        req = urllib.request.Request(url, headers=req_headers)
        response = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
        return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.reason}"}
    except Exception as e:
        return {"error": str(e)}


def _get_key(env_var: str, service_name: str) -> tuple:
    """Obtiene API key de forma segura. Retorna (key, error_msg)."""
    key = os.environ.get(env_var, "")
    if not key:
        return None, (
            f"{service_name} requiere {env_var} en .env\n"
            f"Agrega: {env_var}=tu_api_key"
        )
    return key, None


# ---------------------------------------------------------------------------
# Google Maps
# ---------------------------------------------------------------------------

def _geocode(address: str) -> str:
    """Geocodifica una direccion a coordenadas."""
    if not address:
        return "Error: direccion requerida."
    key, err = _get_key("GOOGLE_MAPS_KEY", "Google Maps")
    if err:
        return err

    url = (
        f"https://maps.googleapis.com/maps/api/geocode/json"
        f"?address={urllib.parse.quote(address)}&key={key}"
    )
    data = _api_get(url)
    if "error" in data:
        return f"Error: {data['error']}"

    results = data.get("results", [])
    if not results:
        return f"No se encontro la direccion: {address}"

    r = results[0]
    location = r.get("geometry", {}).get("location", {})
    formatted = r.get("formatted_address", address)
    lat = location.get("lat", "?")
    lng = location.get("lng", "?")

    return (
        f"**{formatted}**\n\n"
        f"  Latitud:  {lat}\n"
        f"  Longitud: {lng}\n"
        f"  Tipo: {', '.join(r.get('types', []))}"
    )


def _directions(origin: str, dest: str, mode: str = "driving") -> str:
    """Obtiene ruta entre dos puntos."""
    if not origin or not dest:
        return "Error: origen y destino requeridos."
    key, err = _get_key("GOOGLE_MAPS_KEY", "Google Maps")
    if err:
        return err

    valid_modes = {"driving", "walking", "bicycling", "transit"}
    if mode not in valid_modes:
        mode = "driving"

    url = (
        f"https://maps.googleapis.com/maps/api/directions/json"
        f"?origin={urllib.parse.quote(origin)}"
        f"&destination={urllib.parse.quote(dest)}"
        f"&mode={mode}&language=es&key={key}"
    )
    data = _api_get(url)
    if "error" in data:
        return f"Error: {data['error']}"

    routes = data.get("routes", [])
    if not routes:
        return "No se encontro una ruta."

    leg = routes[0].get("legs", [{}])[0]
    distance = leg.get("distance", {}).get("text", "?")
    duration = leg.get("duration", {}).get("text", "?")
    start = leg.get("start_address", origin)
    end = leg.get("end_address", dest)

    steps = leg.get("steps", [])
    instructions = []
    for i, step in enumerate(steps[:10], 1):
        # Limpiar HTML de las instrucciones
        import re
        instr = re.sub(r'<[^>]+>', '', step.get("html_instructions", ""))
        dist = step.get("distance", {}).get("text", "")
        instructions.append(f"  {i}. {instr} ({dist})")

    return (
        f"**Ruta ({mode}):**\n\n"
        f"  Desde: {start}\n"
        f"  Hasta: {end}\n"
        f"  Distancia: {distance}\n"
        f"  Duracion: {duration}\n\n"
        f"**Pasos:**\n" + "\n".join(instructions)
    )


def _places(query: str, location: str = "") -> str:
    """Busca lugares cercanos."""
    if not query:
        return "Error: termino de busqueda requerido."
    key, err = _get_key("GOOGLE_MAPS_KEY", "Google Maps")
    if err:
        return err

    url = (
        f"https://maps.googleapis.com/maps/api/place/textsearch/json"
        f"?query={urllib.parse.quote(query)}"
        f"&language=es&key={key}"
    )
    if location:
        url += f"&location={urllib.parse.quote(location)}&radius=5000"

    data = _api_get(url)
    if "error" in data:
        return f"Error: {data['error']}"

    results = data.get("results", [])[:8]
    if not results:
        return f"Sin resultados para: {query}"

    lines = [f"**Resultados para '{query}':**\n"]
    for r in results:
        name = r.get("name", "?")
        addr = r.get("formatted_address", "")
        rating = r.get("rating", "")
        status = r.get("business_status", "").replace("_", " ").title()
        line = f"  - **{name}**"
        if rating:
            line += f" ({rating}★)"
        if addr:
            line += f"\n    {addr}"
        if status and status != "Operational":
            line += f" [{status}]"
        lines.append(line)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# OpenWeatherMap
# ---------------------------------------------------------------------------

def _weather_owm(city: str) -> str:
    """Clima detallado via OpenWeatherMap."""
    if not city:
        return "Error: ciudad requerida."
    key, err = _get_key("OPENWEATHER_KEY", "OpenWeatherMap")
    if err:
        return err

    url = (
        f"https://api.openweathermap.org/data/2.5/weather"
        f"?q={urllib.parse.quote(city)}&appid={key}"
        f"&units=metric&lang=es"
    )
    data = _api_get(url)
    if "error" in data:
        return f"Error: {data['error']}"
    if data.get("cod") != 200:
        return f"Error: {data.get('message', 'ciudad no encontrada')}"

    main = data.get("main", {})
    weather = data.get("weather", [{}])[0]
    wind = data.get("wind", {})
    clouds = data.get("clouds", {})
    sys = data.get("sys", {})

    return (
        f"**Clima en {data.get('name', city)}, {sys.get('country', '')}:**\n\n"
        f"  Temperatura: {main.get('temp', '?')}°C "
        f"(sensacion: {main.get('feels_like', '?')}°C)\n"
        f"  Min/Max: {main.get('temp_min', '?')}°C / {main.get('temp_max', '?')}°C\n"
        f"  Condicion: {weather.get('description', '?').capitalize()}\n"
        f"  Humedad: {main.get('humidity', '?')}%\n"
        f"  Presion: {main.get('pressure', '?')} hPa\n"
        f"  Viento: {wind.get('speed', '?')} m/s ({wind.get('deg', '?')}°)\n"
        f"  Nubes: {clouds.get('all', '?')}%\n"
        f"  Visibilidad: {data.get('visibility', '?')}m"
    )


def _forecast_owm(city: str) -> str:
    """Pronostico de 5 dias via OpenWeatherMap."""
    if not city:
        return "Error: ciudad requerida."
    key, err = _get_key("OPENWEATHER_KEY", "OpenWeatherMap")
    if err:
        return err

    url = (
        f"https://api.openweathermap.org/data/2.5/forecast"
        f"?q={urllib.parse.quote(city)}&appid={key}"
        f"&units=metric&lang=es&cnt=40"
    )
    data = _api_get(url)
    if "error" in data:
        return f"Error: {data['error']}"

    forecasts = data.get("list", [])
    if not forecasts:
        return "Sin datos de pronostico."

    city_info = data.get("city", {})
    lines = [f"**Pronostico 5 dias — {city_info.get('name', city)}:**\n"]

    # Agrupar por dia (tomar 1 entrada cada 8 horas)
    seen_dates = set()
    for f in forecasts:
        dt_txt = f.get("dt_txt", "")
        date = dt_txt.split(" ")[0]
        if date in seen_dates:
            continue
        seen_dates.add(date)

        main = f.get("main", {})
        weather = f.get("weather", [{}])[0]
        lines.append(
            f"  {date}: {main.get('temp', '?')}°C "
            f"({weather.get('description', '?')}) "
            f"H:{main.get('humidity', '?')}%"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Noticias (NewsAPI)
# ---------------------------------------------------------------------------

def _news(query: str, language: str = "es") -> str:
    """Busca noticias por tema."""
    if not query:
        return "Error: termino de busqueda requerido."
    key, err = _get_key("NEWS_API_KEY", "NewsAPI")
    if err:
        return err

    url = (
        f"https://newsapi.org/v2/everything"
        f"?q={urllib.parse.quote(query)}&language={language}"
        f"&sortBy=publishedAt&pageSize=8&apiKey={key}"
    )
    data = _api_get(url)
    if "error" in data:
        return f"Error: {data['error']}"

    articles = data.get("articles", [])
    if not articles:
        return f"Sin noticias para: {query}"

    lines = [f"**Noticias sobre '{query}':**\n"]
    for a in articles[:8]:
        title = a.get("title", "?")
        source = a.get("source", {}).get("name", "?")
        date = a.get("publishedAt", "")[:10]
        desc = a.get("description", "")[:150]
        url_art = a.get("url", "")
        lines.append(f"  - **{title}**")
        lines.append(f"    {source} | {date}")
        if desc:
            lines.append(f"    {desc}")
        if url_art:
            lines.append(f"    {url_art}")

    return "\n".join(lines)


def _news_headlines(country: str = "co", category: str = "") -> str:
    """Titulares principales por pais."""
    key, err = _get_key("NEWS_API_KEY", "NewsAPI")
    if err:
        return err

    import re
    # Validar codigo de pais (2 letras)
    if not re.match(r'^[a-z]{2}$', country.lower()):
        return f"Codigo de pais invalido: {country}"

    url = (
        f"https://newsapi.org/v2/top-headlines"
        f"?country={country.lower()}&pageSize=10&apiKey={key}"
    )
    if category:
        valid_cats = {"business", "entertainment", "general", "health", "science", "sports", "technology"}
        if category.lower() in valid_cats:
            url += f"&category={category.lower()}"

    data = _api_get(url)
    if "error" in data:
        return f"Error: {data['error']}"

    articles = data.get("articles", [])
    if not articles:
        return f"Sin titulares para {country.upper()}."

    lines = [f"**Titulares — {country.upper()}:**\n"]
    for a in articles[:10]:
        title = a.get("title", "?")
        source = a.get("source", {}).get("name", "?")
        lines.append(f"  - {title} ({source})")

    return "\n".join(lines)
