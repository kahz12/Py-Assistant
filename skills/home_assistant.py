"""
skills/home_assistant.py -- Integracion con Home Assistant.

Permite controlar dispositivos y obtener estados del hogar inteligente
via la API REST de Home Assistant.

Acciones soportadas:
  - Listar entidades (luces, sensores, switches, etc.)
  - Obtener estado de una entidad.
  - Encender/Apagar dispositivos.
  - Ejecutar servicios (scripts, escenas, automatizaciones).

Seguridad:
  - Token de autorizacion via variable de entorno (HASS_TOKEN).
  - URL del servidor via variable de entorno (HASS_URL).
  - Solo se permiten dominios conocidos de HA (light, switch, etc.).
  - Timeout de 10 segundos en cada request.
  - No expone el token en logs ni respuestas.

Requisitos:
  - Home Assistant accesible en la red (local o Nabu Casa).
  - Long-Lived Access Token generado en HA (Perfil > Tokens).

Configuracion en .env:
  HASS_URL=http://homeassistant.local:8123
  HASS_TOKEN=tu_long_lived_access_token

Interfaz del skill:
    SKILL_NAME = "home_assistant"
    execute(action, entity_id=None, service=None, data=None) -> str
"""
import os
import re
import json
import urllib.request
import urllib.parse
import urllib.error
from loguru import logger

SKILL_NAME = "home_assistant"
SKILL_DESCRIPTION = "Home Assistant: controlar luces, sensores, switches y automatizaciones."

REQUEST_TIMEOUT = 10

# Dominios seguros que se pueden controlar
SAFE_DOMAINS = {
    "light", "switch", "fan", "cover", "lock", "climate",
    "media_player", "vacuum", "scene", "script", "automation",
    "input_boolean", "input_number", "input_select", "input_text",
    "button", "number", "select", "humidifier", "water_heater",
    "sensor", "binary_sensor", "weather", "person", "zone",
    "device_tracker", "sun", "calendar",
}


def execute(
    action: str,
    entity_id: str = None,
    service: str = None,
    domain: str = None,
    data: dict = None,
) -> str:
    """
    Punto de entrada principal del skill.

    Acciones:
      - 'states'        : Lista todas las entidades o filtra por dominio.
      - 'state'         : Obtiene el estado de una entidad especifica.
      - 'turn_on'       : Enciende una entidad (luz, switch, etc.).
      - 'turn_off'      : Apaga una entidad.
      - 'toggle'        : Alterna el estado de una entidad.
      - 'call_service'  : Ejecuta un servicio arbitrario de HA.
      - 'history'       : Historial reciente de una entidad.

    Args:
        action: Accion a ejecutar.
        entity_id: Identificador de la entidad (ej: light.sala).
        service: Nombre del servicio (para call_service).
        domain: Dominio para filtrar (ej: light, sensor).
        data: Datos adicionales para el servicio.
    """
    actions = {
        "states": lambda: _list_states(domain),
        "state": lambda: _get_state(entity_id),
        "turn_on": lambda: _call_service_simple("turn_on", entity_id, data),
        "turn_off": lambda: _call_service_simple("turn_off", entity_id, data),
        "toggle": lambda: _call_service_simple("toggle", entity_id, data),
        "call_service": lambda: _call_service(domain, service, data),
        "history": lambda: _get_history(entity_id),
    }

    if action not in actions:
        available = ", ".join(actions.keys())
        return f"Accion no reconocida: {action}. Opciones: {available}"

    return actions[action]()


# ---------------------------------------------------------------------------
# Configuracion y seguridad
# ---------------------------------------------------------------------------

def _get_config() -> tuple:
    """Obtiene URL y token de HA. Retorna (url, token, error)."""
    url = os.environ.get("HASS_URL", "").rstrip("/")
    token = os.environ.get("HASS_TOKEN", "")

    if not url:
        return None, None, (
            "Home Assistant no configurado.\n"
            "Agrega en .env:\n"
            "  HASS_URL=http://homeassistant.local:8123\n"
            "  HASS_TOKEN=tu_long_lived_access_token"
        )
    if not token:
        return None, None, (
            "Token de Home Assistant no configurado.\n"
            "Genera un Long-Lived Access Token en:\n"
            "  HA > Perfil > Tokens de acceso de larga duracion\n"
            "Agrega en .env: HASS_TOKEN=tu_token"
        )
    return url, token, None


def _validate_entity_id(entity_id: str) -> str:
    """Valida formato y dominio de entity_id."""
    if not entity_id:
        return "Error: entity_id requerido (ej: light.sala, switch.cocina)."

    # Formato: domain.object_id
    if not re.match(r'^[a-z_]+\.[a-z0-9_]+$', entity_id):
        return f"entity_id invalido: {entity_id}. Formato: dominio.nombre (ej: light.sala)"

    domain = entity_id.split(".")[0]
    if domain not in SAFE_DOMAINS:
        return f"Dominio no permitido: {domain}. Permitidos: {', '.join(sorted(SAFE_DOMAINS))}"

    return ""


def _validate_service_name(name: str) -> str:
    """Valida nombre de servicio (alfanumerico + guion bajo)."""
    if not name:
        return "Error: nombre de servicio requerido."
    if not re.match(r'^[a-z_]+$', name):
        return f"Nombre de servicio invalido: {name}"
    return ""


# ---------------------------------------------------------------------------
# API REST de Home Assistant
# ---------------------------------------------------------------------------

def _ha_request(method: str, endpoint: str, payload: dict = None) -> dict:
    """Realiza una request autenticada a la API de HA."""
    url, token, err = _get_config()
    if err:
        return {"error": err}

    full_url = f"{url}/api/{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        data = json.dumps(payload).encode("utf-8") if payload else None
        req = urllib.request.Request(
            full_url,
            data=data,
            headers=headers,
            method=method,
        )
        response = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
        body = response.read().decode("utf-8")
        return json.loads(body) if body else {}

    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8")[:300]
        except Exception:
            pass
        logger.error(f"[home_assistant] HTTP {e.code}: {error_body}")
        if e.code == 401:
            return {"error": "Token de HA invalido o expirado. Revisa HASS_TOKEN."}
        return {"error": f"Error HTTP {e.code}: {error_body}"}
    except urllib.error.URLError as e:
        logger.error(f"[home_assistant] Conexion fallida: {e}")
        return {"error": f"No se pudo conectar a Home Assistant ({url}). Verifica que este activo."}
    except Exception as e:
        logger.error(f"[home_assistant] Error: {e}")
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Acciones
# ---------------------------------------------------------------------------

def _list_states(domain: str = None) -> str:
    """Lista entidades, opcionalmente filtradas por dominio."""
    result = _ha_request("GET", "states")
    if isinstance(result, dict) and "error" in result:
        return result["error"]

    if not isinstance(result, list):
        return "Respuesta inesperada de Home Assistant."

    entities = result
    if domain:
        if not re.match(r'^[a-z_]+$', domain):
            return f"Dominio invalido: {domain}"
        entities = [e for e in entities if e.get("entity_id", "").startswith(f"{domain}.")]

    if not entities:
        return f"No se encontraron entidades{f' del dominio {domain}' if domain else ''}."

    # Agrupar por dominio
    groups = {}
    for e in entities:
        eid = e.get("entity_id", "?")
        d = eid.split(".")[0]
        state = e.get("state", "?")
        name = e.get("attributes", {}).get("friendly_name", eid)
        if d not in groups:
            groups[d] = []
        groups[d].append(f"  - `{eid}` — {name}: **{state}**")

    lines = [f"**{len(entities)} entidades encontradas:**\n"]
    for d, items in sorted(groups.items()):
        lines.append(f"### {d} ({len(items)})")
        lines.extend(items[:15])
        if len(items) > 15:
            lines.append(f"  ... y {len(items)-15} mas")

    return "\n".join(lines)


def _get_state(entity_id: str) -> str:
    """Obtiene el estado detallado de una entidad."""
    err = _validate_entity_id(entity_id)
    if err:
        return err

    result = _ha_request("GET", f"states/{entity_id}")
    if isinstance(result, dict) and "error" in result:
        return result["error"]

    state = result.get("state", "?")
    attrs = result.get("attributes", {})
    name = attrs.get("friendly_name", entity_id)
    last_changed = result.get("last_changed", "?")

    lines = [f"**{name}** (`{entity_id}`)\n"]
    lines.append(f"  Estado: **{state}**")
    lines.append(f"  Ultimo cambio: {last_changed}")

    # Atributos relevantes
    skip_attrs = {"friendly_name", "icon", "entity_picture"}
    for key, value in attrs.items():
        if key not in skip_attrs:
            lines.append(f"  {key}: {value}")

    return "\n".join(lines)


def _call_service_simple(service: str, entity_id: str, data: dict = None) -> str:
    """Ejecuta turn_on, turn_off, toggle sobre una entidad."""
    err = _validate_entity_id(entity_id)
    if err:
        return err

    domain = entity_id.split(".")[0]
    payload = {"entity_id": entity_id}
    if data and isinstance(data, dict):
        # Solo atributos seguros (brillo, color, temperatura)
        safe_keys = {
            "brightness", "brightness_pct", "color_temp", "rgb_color",
            "hs_color", "xy_color", "effect", "temperature", "hvac_mode",
            "fan_mode", "preset_mode", "volume_level", "media_content_id",
            "media_content_type", "position", "tilt_position", "speed",
            "humidity", "target_temp_high", "target_temp_low",
        }
        for k, v in data.items():
            if k in safe_keys:
                payload[k] = v

    result = _ha_request("POST", f"services/{domain}/{service}", payload)
    if isinstance(result, dict) and "error" in result:
        return result["error"]

    name = entity_id.split(".")[-1].replace("_", " ").title()
    action_name = {"turn_on": "encendido", "turn_off": "apagado", "toggle": "alternado"}.get(service, service)
    logger.info(f"[home_assistant] {entity_id} -> {service}")
    return f"✅ **{name}** {action_name} exitosamente."


def _call_service(domain: str, service: str, data: dict = None) -> str:
    """Ejecuta un servicio arbitrario de HA."""
    if not domain:
        return "Error: dominio requerido (ej: light, switch, script)."
    if not re.match(r'^[a-z_]+$', domain):
        return f"Dominio invalido: {domain}"
    if domain not in SAFE_DOMAINS:
        return f"Dominio no permitido: {domain}"

    err = _validate_service_name(service)
    if err:
        return err

    payload = data if isinstance(data, dict) else {}
    result = _ha_request("POST", f"services/{domain}/{service}", payload)
    if isinstance(result, dict) and "error" in result:
        return result["error"]

    logger.info(f"[home_assistant] Servicio: {domain}.{service}")
    return f"✅ Servicio `{domain}.{service}` ejecutado exitosamente."


def _get_history(entity_id: str) -> str:
    """Obtiene historial reciente de una entidad (ultimas 24h)."""
    err = _validate_entity_id(entity_id)
    if err:
        return err

    from datetime import datetime, timedelta
    timestamp = (datetime.utcnow() - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")
    endpoint = f"history/period/{timestamp}?filter_entity_id={entity_id}&minimal_response"

    result = _ha_request("GET", endpoint)
    if isinstance(result, dict) and "error" in result:
        return result["error"]

    if not isinstance(result, list) or not result or not result[0]:
        return f"Sin historial para {entity_id}."

    entries = result[0]
    lines = [f"**Historial de `{entity_id}` (ultimas 24h):**\n"]
    for entry in entries[-15:]:
        state = entry.get("state", "?")
        changed = entry.get("last_changed", "?")
        if changed and len(changed) > 16:
            changed = changed[:16].replace("T", " ")
        lines.append(f"  {changed} → **{state}**")

    return "\n".join(lines)
