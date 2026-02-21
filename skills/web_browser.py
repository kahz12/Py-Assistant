"""
skills/web_browser.py -- Navegacion web y extraccion de contenido.

Proporciona busqueda en DuckDuckGo y extraccion de texto/links de
paginas web usando urllib (sin dependencias externas adicionales).

Si Playwright estuviera instalado en el futuro, se podria extender
con scraping avanzado en modo headless.

Interfaz del skill:
    SKILL_NAME = "web_browser"
    execute(action, url=None, query=None) -> str
"""
import re
import urllib.request
import urllib.parse
from loguru import logger

SKILL_NAME = "web_browser"
SKILL_DESCRIPTION = "Navegacion web: buscar, extraer texto, extraer links."


def execute(action: str, url: str = None, query: str = None) -> str:
    """
    Punto de entrada principal del skill.

    Acciones disponibles:
      - 'search'    : Busca en DuckDuckGo.
      - 'get_text'  : Extrae el texto visible de una URL.
      - 'get_links' : Extrae los links de una URL.

    Args:
        action: Accion a ejecutar.
        url: URL objetivo (requerida para get_text y get_links).
        query: Texto de busqueda (requerido para search).

    Returns:
        Resultado de la accion como texto.
    """
    actions = {
        "search": lambda: _search(query or ""),
        "search_images": lambda: _search_images(query or ""),
        "get_text": lambda: _get_text(url or ""),
        "get_links": lambda: _get_links(url or ""),
    }

    if action not in actions:
        return f"Accion no reconocida: {action}. Opciones: search, search_images, get_text, get_links"

    return actions[action]()


# ---------------------------------------------------------------------------
# Implementaciones internas
# ---------------------------------------------------------------------------

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def _search(query: str) -> str:
    """
    Busca en DuckDuckGo y retorna los primeros resultados.

    Args:
        query: Texto de busqueda.

    Returns:
        Resultados formateados o mensaje de error.
    """
    if not query:
        return "Error: query vacia."

    from skills.api_client import _is_url_safe
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
    
    safe, msg = _is_url_safe(url)
    if not safe:
        return f"Bloqueo de Seguridad (SSRF): {msg}"

    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        response = urllib.request.urlopen(req, timeout=15)
        html = response.read().decode("utf-8", errors="ignore")

        titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html, re.DOTALL)
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
        urls = re.findall(r'class="result__url"[^>]*>(.*?)</a>', html, re.DOTALL)

        results = []
        for i, (title, snippet) in enumerate(zip(titles[:7], snippets[:7])):
            clean_title = re.sub(r'<[^>]+>', '', title).strip()
            clean_snippet = re.sub(r'<[^>]+>', '', snippet).strip()
            result_url = re.sub(r'<[^>]+>', '', urls[i]).strip() if i < len(urls) else ""
            results.append(f"{i+1}. {clean_title}\n   {result_url}\n   {clean_snippet}")

        if results:
            return f"Resultados para '{query}':\n\n" + "\n\n".join(results)
        return f"No se encontraron resultados para '{query}'."

    except Exception as e:
        logger.error(f"[web_browser] Error en busqueda: {e}")
        return f"Error en busqueda: {e}"


def _search_images(query: str) -> str:
    """
    Busca imagenes en DuckDuckGo Lite y extrae las URLs de las imagenes.
    
    Args:
        query: Texto de busqueda.
        
    Returns:
        Lista de URLs de imagenes o mensaje de error.
    """
    if not query:
        return "Error: query vacia."

    from skills.api_client import _is_url_safe
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
    
    safe, msg = _is_url_safe(url)
    if not safe:
        return f"Bloqueo de Seguridad (SSRF): {msg}"

    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        response = urllib.request.urlopen(req, timeout=15)
        html = response.read().decode("utf-8", errors="ignore")

        # duckduckgo lite sometimes includes thumbnails in the HTML
        img_tags = re.findall(r'<img[^>]*src=["\']([^"\']+)["\'][^>]*>', html, re.IGNORECASE)
        
        # Filtramos iconos propios de duckduckgo
        img_urls = [img for img in img_tags if "duckduckgo.com" not in img and img.startswith("http")]
        
        # Como DDG Lite html no expone facilmente imagenes completas,
        # intentamos buscar via API oculta (DuckDuckGo vqd)
        vqd_match = re.search(r'vqd=([\d-]+)', html)
        if vqd_match:
            vqd = vqd_match.group(1)
            img_url = f"https://duckduckgo.com/i.js?q={urllib.parse.quote(query)}&o=json&vqd={vqd}"
            try:
                import json
                req_api = urllib.request.Request(img_url, headers=_HEADERS)
                res_api = urllib.request.urlopen(req_api, timeout=10)
                data = json.loads(res_api.read().decode("utf-8"))
                for item in data.get("results", []):
                    img_urls.append(item.get("image"))
            except Exception:
                pass

        valid_urls = []
        for u in img_urls:
            if u and u.startswith("http") and u not in valid_urls:
                valid_urls.append(u)

        if valid_urls:
            return f"URLs de imagenes encontradas para '{query}':\n\n" + "\n".join(valid_urls[:10])
        return f"No se encontraron imagenes web validas para '{query}'."
        
    except Exception as e:
        logger.error(f"[web_browser] Error en busqueda de imagenes: {e}")
        return f"Error en busqueda de imagenes: {e}"


def _get_text(url: str) -> str:
    """
    Extrae el texto visible de una pagina web.

    Elimina scripts, estilos, navegacion y footer del HTML.
    El resultado se trunca a 4000 caracteres para no saturar el contexto del LLM.

    Args:
        url: URL de la pagina.

    Returns:
        Texto extraido o mensaje de error.
    """
    from skills.api_client import _is_url_safe
    
    if not url:
        return "Error: URL vacia."
    if not url.startswith("http"):
        url = "https://" + url

    safe, msg = _is_url_safe(url)
    if not safe:
        return f"Bloqueo de Seguridad (SSRF): {msg}"

    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        response = urllib.request.urlopen(req, timeout=15)
        html = response.read().decode("utf-8", errors="ignore")

        # Eliminar contenido no textual
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
        html = re.sub(r'<nav[^>]*>.*?</nav>', '', html, flags=re.DOTALL)
        html = re.sub(r'<footer[^>]*>.*?</footer>', '', html, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text).strip()

        if len(text) > 4000:
            text = text[:4000] + "\n\n[... contenido truncado]"

        return f"Contenido de {url}:\n\n{text}"

    except Exception as e:
        logger.error(f"[web_browser] Error extrayendo texto: {e}")
        return f"Error extrayendo texto de {url}: {e}"


def _get_links(url: str) -> str:
    """
    Extrae los links de una pagina web.

    Filtra links vacios, anclas internas (#) y links de javascript.
    Resuelve URLs relativas a absolutas.

    Args:
        url: URL de la pagina.

    Returns:
        Lista formateada de links encontrados (maximo 30).
    """
    from skills.api_client import _is_url_safe

    if not url:
        return "Error: URL vacia."
    if not url.startswith("http"):
        url = "https://" + url

    safe, msg = _is_url_safe(url)
    if not safe:
        return f"Bloqueo de Seguridad (SSRF): {msg}"

    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        response = urllib.request.urlopen(req, timeout=15)
        html = response.read().decode("utf-8", errors="ignore")

        links = re.findall(r'<a[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.DOTALL)

        results = []
        seen = set()
        for href, text in links:
            clean_text = re.sub(r'<[^>]+>', '', text).strip()
            if not clean_text or href.startswith("#") or href.startswith("javascript"):
                continue
            if href in seen:
                continue
            seen.add(href)
            # Resolver URLs relativas
            if href.startswith("/"):
                from urllib.parse import urlparse
                parsed = urlparse(url)
                href = f"{parsed.scheme}://{parsed.netloc}{href}"
            results.append(f"  {clean_text[:60]} -> {href}")

        if results:
            return f"Links en {url} ({len(results)}):\n\n" + "\n".join(results[:30])
        return f"No se encontraron links en {url}."

    except Exception as e:
        logger.error(f"[web_browser] Error extrayendo links: {e}")
        return f"Error extrayendo links de {url}: {e}"
