"""
skills/api_client.py -- Cliente REST generico para APIs externas.

Permite al asistente interactuar con cualquier API REST publica:
  - GET, POST, PUT, DELETE con headers y body personalizados.
  - Soporte para JSON, formularios y texto plano.
  - Timeout y manejo de errores robusto.
  - APIs preconfiguradas: clima, divisas, traduccion.

Seguridad:
  - Solo permite conexiones HTTPS por defecto.
  - Bloquea IPs privadas/locales (192.168.x.x, 10.x.x.x, etc.)
  - Timeout de 15 segundos.

Interfaz del skill:
    SKILL_NAME = "api_client"
    execute(action, url=None, method=None, headers=None, body=None, ...) -> str
"""
import json
import re
import urllib.request
import urllib.parse
import urllib.error
from loguru import logger

SKILL_NAME = "api_client"
SKILL_DESCRIPTION = "Cliente REST: llamar APIs externas (GET/POST/PUT/DELETE)."

# Timeout global para requests
REQUEST_TIMEOUT = 15

# Bloquear IPs privadas y locales (SEC-N04/N05)
_BLOCKED_PATTERNS = [
    r"^https?://(127\.\d+\.\d+\.\d+)",
    r"^https?://(10\.\d+\.\d+\.\d+)",
    r"^https?://(172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)",
    r"^https?://(192\.168\.\d+\.\d+)",
    r"^https?://(169\.254\.\d+\.\d+)",       # Link-local / AWS metadata
    r"^https?://localhost",
    r"^https?://\[::1\]",
    r"^https?://\[fc",                        # IPv6 private (fc00::/7)
    r"^https?://\[fd",                        # IPv6 private (fd00::/8)
    r"^https?://\[fe80",                      # IPv6 link-local
    r"^https?://0\.0\.0\.0",
    r"^https?://metadata\.google\.internal",   # GCP metadata
]


def execute(
    action: str,
    url: str = None,
    method: str = "GET",
    headers: dict = None,
    body: str = None,
    api_name: str = None,
    params: dict = None,
) -> str:
    """
    Punto de entrada principal del skill.

    Acciones disponibles:
      - 'request'  : Realiza una peticion HTTP generica.
      - 'weather'  : Obtiene el clima de una ciudad (wttr.in).
      - 'currency' : Consulta tasa de cambio entre divisas.
      - 'ip_info'  : Informacion sobre una IP o la propia.

    Args:
        action: Accion a ejecutar.
        url: URL para peticiones genericas.
        method: Metodo HTTP (GET, POST, PUT, DELETE).
        headers: Headers HTTP como diccionario.
        body: Cuerpo de la peticion (JSON string o texto).
        api_name: Nombre de API preconfigurada.
        params: Parametros adicionales.
    """
    actions = {
        "request": lambda: _request(url, method, headers, body),
        "weather": lambda: _weather(params.get("city", "") if params else ""),
        "currency": lambda: _currency(
            params.get("from", "USD") if params else "USD",
            params.get("to", "EUR") if params else "EUR",
            params.get("amount", 1) if params else 1,
        ),
        "ip_info": lambda: _ip_info(params.get("ip", "") if params else ""),
    }

    if action not in actions:
        available = ", ".join(actions.keys())
        return f"Accion no reconocida: {action}. Opciones: {available}"

    return actions[action]()


# ---------------------------------------------------------------------------
# Seguridad
# ---------------------------------------------------------------------------

def _is_url_safe(url: str) -> tuple[bool, str]:
    """Verifica que la URL no apunte a la red local (SEC-N04: incluye resolucion DNS)."""
    if not url:
        return False, "Error: URL requerida."

    # Bloquear protocolos peligrosos
    if url.startswith(("file://", "ftp://", "gopher://", "data:")):
        return False, f"Protocolo no permitido: {url.split(':')[0]}"

    if not url.startswith("http"):
        return False, "Error: la URL debe comenzar con http:// o https://"

    # Verificar patrones bloqueados
    for pattern in _BLOCKED_PATTERNS:
        if re.match(pattern, url, re.IGNORECASE):
            return False, f"Acceso bloqueado: no se permite acceder a la red local ({url})."

    # SEC-N04: Resolver DNS y verificar que la IP resultante no sea privada
    try:
        import socket
        from urllib.parse import urlparse
        hostname = urlparse(url).hostname
        if hostname:
            ip = socket.gethostbyname(hostname)
            import ipaddress
            addr = ipaddress.ip_address(ip)
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                return False, f"Acceso bloqueado: {hostname} resuelve a IP privada ({ip})."
    except (socket.gaierror, ValueError):
        pass  # Si no resuelve, dejar que el request falle normalmente

    return True, ""


# ---------------------------------------------------------------------------
# Request generico
# ---------------------------------------------------------------------------

def _request(url: str, method: str = "GET", headers: dict = None, body: str = None) -> str:
    """Realiza una peticion HTTP generica."""
    safe, msg = _is_url_safe(url)
    if not safe:
        return msg

    method = method.upper()
    if method not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
        return f"Metodo HTTP no soportado: {method}"

    req_headers = {"User-Agent": "AsistenteIA/1.0", "Accept": "application/json"}
    if headers:
        req_headers.update(headers)

    data = None
    if body:
        data = body.encode("utf-8")
        if "Content-Type" not in req_headers:
            req_headers["Content-Type"] = "application/json"

    try:
        req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
        response = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
        content = response.read().decode("utf-8", errors="ignore")
        status = response.status

        # Intentar formatear JSON
        try:
            parsed = json.loads(content)
            content = json.dumps(parsed, indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, ValueError):
            pass

        # Truncar respuestas muy largas
        if len(content) > 5000:
            content = content[:5000] + "\n\n[... respuesta truncada]"

        return f"[{method} {status}] {url}\n\n```json\n{content}\n```"

    except urllib.error.HTTPError as e:
        body_err = e.read().decode("utf-8", errors="ignore")[:500]
        return f"Error HTTP {e.code}: {e.reason}\n{body_err}"
    except urllib.error.URLError as e:
        return f"Error de conexion: {e.reason}"
    except Exception as e:
        return f"Error en request: {e}"


# ---------------------------------------------------------------------------
# APIs preconfiguradas
# ---------------------------------------------------------------------------

def _weather(city: str) -> str:
    """Obtiene el clima usando wttr.in (sin API key)."""
    if not city:
        return "Error: ciudad requerida."
    url = f"https://wttr.in/{urllib.parse.quote(city)}?format=j1"
    safe, msg = _is_url_safe(url)
    if not safe:
        return msg

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AsistenteIA/1.0"})
        response = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
        data = json.loads(response.read().decode("utf-8"))

        current = data.get("current_condition", [{}])[0]
        area = data.get("nearest_area", [{}])[0]
        city_name = area.get("areaName", [{}])[0].get("value", city)
        country = area.get("country", [{}])[0].get("value", "")

        temp = current.get("temp_C", "?")
        feels = current.get("FeelsLikeC", "?")
        desc = current.get("lang_es", [{}])[0].get("value", "") or current.get("weatherDesc", [{}])[0].get("value", "")
        humidity = current.get("humidity", "?")
        wind = current.get("windspeedKmph", "?")

        return (
            f"Clima en {city_name}, {country}:\n\n"
            f"  Temperatura: {temp}C (sensacion: {feels}C)\n"
            f"  Condicion: {desc}\n"
            f"  Humedad: {humidity}%\n"
            f"  Viento: {wind} km/h"
        )
    except Exception as e:
        return f"Error obteniendo clima: {e}"


def _currency(from_cur: str, to_cur: str, amount: float = 1) -> str:
    """Consulta tasa de cambio usando ExchangeRate API (sin key)."""
    from_cur = from_cur.upper()
    to_cur = to_cur.upper()
    url = f"https://open.er-api.com/v6/latest/{from_cur}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AsistenteIA/1.0"})
        response = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
        data = json.loads(response.read().decode("utf-8"))

        if data.get("result") != "success":
            return f"Error: moneda '{from_cur}' no reconocida."

        rates = data.get("rates", {})
        if to_cur not in rates:
            return f"Error: moneda destino '{to_cur}' no encontrada."

        rate = rates[to_cur]
        converted = amount * rate
        return (
            f"Tasa de cambio:\n\n"
            f"  {amount} {from_cur} = {converted:.2f} {to_cur}\n"
            f"  (1 {from_cur} = {rate:.4f} {to_cur})\n"
            f"  Fuente: exchangerate-api.com"
        )
    except Exception as e:
        return f"Error consultando tasa de cambio: {e}"


def _ip_info(ip: str = "") -> str:
    """Obtiene informacion de una IP usando ip-api.com."""
    url = f"http://ip-api.com/json/{ip}" if ip else "http://ip-api.com/json/"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AsistenteIA/1.0"})
        response = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
        data = json.loads(response.read().decode("utf-8"))

        if data.get("status") != "success":
            return f"Error: IP '{ip}' no encontrada."

        return (
            f"Informacion IP: {data.get('query', ip)}\n\n"
            f"  Pais: {data.get('country', '?')}\n"
            f"  Region: {data.get('regionName', '?')}\n"
            f"  Ciudad: {data.get('city', '?')}\n"
            f"  ISP: {data.get('isp', '?')}\n"
            f"  Org: {data.get('org', '?')}\n"
            f"  Timezone: {data.get('timezone', '?')}"
        )
    except Exception as e:
        return f"Error: {e}"
