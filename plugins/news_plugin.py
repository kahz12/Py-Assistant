"""
plugins/news_plugin.py -- Noticias en tiempo real via NewsAPI.

Obtiene los titulares mas recientes por categoria, pais o busqueda
usando la API gratuita de newsapi.org.

Requiere:
    NEWS_API_KEY en .env

Acciones:
    headlines : Titulares principales (por pais/categoria).
    search    : Busqueda por palabra clave.
    sources   : Lista fuentes disponibles.
    help      : Informacion de uso.
"""
import json
import os
import urllib.parse
import urllib.request
from loguru import logger

SKILL_NAME = "news"
SKILL_DISPLAY_NAME = "Noticias (NewsAPI)"
SKILL_DESCRIPTION = (
    "Obtiene noticias y titulares en tiempo real de fuentes mundiales "
    "via NewsAPI. Soporta busqueda por tema, pais y categoria."
)
VERSION = "1.0.0"
AUTHOR = "local"
REQUIRES_ENV = ["NEWS_API_KEY"]
ACTIONS = ["headlines", "search", "sources", "help"]

_BASE = "https://newsapi.org/v2"
_CATEGORIES = ["business", "entertainment", "general", "health", "science", "sports", "technology"]
_COUNTRIES = {
    "es": "España", "us": "EEUU", "mx": "Mexico", "ar": "Argentina",
    "co": "Colombia", "ve": "Venezuela", "gb": "Reino Unido", "de": "Alemania",
}


def _key() -> str:
    key = os.environ.get("NEWS_API_KEY", "")
    if not key:
        raise ValueError(
            "Falta NEWS_API_KEY en .env — registrate gratis en newsapi.org."
        )
    return key


def _fetch(endpoint: str, params: dict) -> dict:
    params["apiKey"] = _key()
    qs = urllib.parse.urlencode(params)
    url = f"{_BASE}/{endpoint}?{qs}"
    logger.debug(f"[news] GET {endpoint}")
    with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _format_articles(articles: list, title: str, limit: int = 5) -> str:
    if not articles:
        return "No se encontraron articulos."
    lines = [f"📰 **{title}** ({len(articles)} articulos)\n"]
    for i, a in enumerate(articles[:limit], 1):
        source = a.get("source", {}).get("name", "—")
        headline = a.get("title", "Sin titulo")
        desc = (a.get("description") or "")[:120]
        url = a.get("url", "")
        lines.append(f"**{i}. {headline}**")
        if desc:
            lines.append(f"   {desc}…")
        lines.append(f"   🔗 {source} | {url}\n")
    return "\n".join(lines)


def execute(
    action: str = "headlines",
    query: str = "",
    country: str = "us",
    category: str = "general",
    language: str = "es",
    limit: int = 5,
    **kwargs,
) -> str:
    """
    Obtiene noticias de NewsAPI.

    Args:
        action   : "headlines", "search", "sources" o "help".
        query    : Termino de busqueda (para action="search").
        country  : Codigo de pais ISO-2 (para headlines, default: "us").
        category : Categoria de noticias (default: "general").
        language : Idioma para busqueda (default: "es").
        limit    : Maximo de articulos a mostrar (1-10, default: 5).
    """
    action = action.lower().strip()
    limit = max(1, min(int(limit), 10))

    if action == "help":
        return (
            "**Plugin Noticias — Acciones:**\n"
            "  • `headlines` [country=us] [category=general] — Titulares del dia\n"
            "  • `search` query=<tema> [language=es] — Busqueda por tema\n"
            "  • `sources` — Lista fuentes disponibles\n\n"
            f"Categorias: {', '.join(_CATEGORIES)}\n"
            f"Paises: {', '.join(f'{k}={v}' for k,v in _COUNTRIES.items())}"
        )

    try:
        if action == "headlines":
            country_name = _COUNTRIES.get(country, country.upper())
            data = _fetch("top-headlines", {"country": country, "category": category, "pageSize": limit})
            title = f"Titulares — {country_name} / {category.capitalize()}"
            return _format_articles(data.get("articles", []), title, limit)

        elif action == "search":
            if not query:
                return "Especifica el tema. Ej: action='search', query='inteligencia artificial'"
            data = _fetch("everything", {
                "q": query, "language": language,
                "sortBy": "publishedAt", "pageSize": limit,
            })
            total = data.get("totalResults", 0)
            title = f"Noticias: '{query}' ({total} encontradas)"
            return _format_articles(data.get("articles", []), title, limit)

        elif action == "sources":
            data = _fetch("top-headlines/sources", {"language": language})
            sources = data.get("sources", [])[:20]
            if not sources:
                return "No se encontraron fuentes."
            lines = ["**Fuentes disponibles:**\n"]
            for s in sources:
                lines.append(f"  • **{s['name']}** ({s.get('country','?')}) — {s.get('description','')[:80]}")
            return "\n".join(lines)

        else:
            return f"Accion '{action}' no soportada. Usa: {', '.join(ACTIONS)}."

    except ValueError as e:
        return str(e)
    except Exception as e:
        logger.error(f"[news] Error: {e}")
        return f"Error al obtener noticias: {str(e)}"
