"""
skills/google_calendar.py -- Integracion con Google Calendar.

Permite consultar y crear eventos en Google Calendar via la API de Google.

Acciones soportadas:
  - list      : Lista los proximos eventos.
  - create    : Crea un nuevo evento.
  - search    : Busca eventos especificos.

Seguridad:
  - Requiere credenciales OAuth en configuration (`credentials.json`).
  - El token se guarda localmente tras la primera autenticacion.
"""
import os
import datetime
import json
from pathlib import Path
from loguru import logger

SKILL_NAME = "google_calendar"
SKILL_DESCRIPTION = "Google Calendar: consultar y crear eventos."

SCOPES = ['https://www.googleapis.com/auth/calendar']
CREDS_PATH = Path("config/google_calendar_credentials.json")
TOKEN_PATH = Path("config/google_calendar_token.json")


def execute(action: str, **kwargs) -> str:
    """
    Punto de entrada principal del skill.

    Args:
        action: 'list', 'create', 'search'.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        return (
            "Dependencias de Google faltantes. Instala con:\n"
            "pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
        )

    creds = _get_credentials(Credentials, InstalledAppFlow, Request)
    if not creds:
        return (
            "Credenciales de Google Calendar no configuradas.\n"
            f"Por favor, descarga tus credenciales de Google Cloud Console y guardalas en: {CREDS_PATH}"
        )

    try:
        service = build('calendar', 'v3', credentials=creds)
    except Exception as e:
        logger.error(f"[google_calendar] Error inicializando servicio: {e}")
        return f"Error conectando a Google Calendar: {e}"

    actions = {
        "list": lambda: _list_events(service, kwargs.get("max_results", 10)),
        "create": lambda: _create_event(service, kwargs),
        "search": lambda: _search_events(service, kwargs.get("query", "")),
    }

    if action not in actions:
        return f"Accion no soportada: {action}."

    return actions[action]()


def _get_credentials(Credentials, InstalledAppFlow, Request):
    """Obtiene y refresca credenciales OAuth2."""
    creds = None
    if TOKEN_PATH.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        except Exception as e:
            logger.warning(f"Error cargando token de Google Calendar: {e}")

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                logger.warning(f"Error refrescando token: {e}")
                creds = None

        if not creds:
            if not CREDS_PATH.exists():
                return None
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(CREDS_PATH), SCOPES
                )
                creds = flow.run_local_server(port=0)
            except Exception as e:
                logger.error(f"Error en flujo OAuth: {e}")
                return None

        # Guardar credenciales para la proxima vez
        try:
            with open(TOKEN_PATH, 'w') as token:
                token.write(creds.to_json())
        except Exception as e:
            logger.error(f"Error guardando token: {e}")

    return creds


def _list_events(service, max_results: int) -> str:
    """Lista los proximos eventos del calendario principal."""
    try:
        now = datetime.datetime.utcnow().isoformat() + 'Z'
        events_result = service.events().list(
            calendarId='primary', timeMin=now,
            maxResults=max_results, singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])

        if not events:
            return "No tienes eventos proximos."

        lines = [f"**Proximos {len(events)} eventos:**\n"]
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            summary = event.get('summary', 'Sin titulo')
            lines.append(f"  - {start}: **{summary}**")
        
        return "\n".join(lines)
    except Exception as e:
        return f"Error listando eventos: {e}"


def _search_events(service, query: str) -> str:
    """Busca eventos por texto libres."""
    if not query:
        return "Debes proveer un texto de busqueda."

    try:
        events_result = service.events().list(
            calendarId='primary', q=query,
            maxResults=10, singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])

        if not events:
            return f"No se encontraron eventos coincidiendo con: '{query}'."

        lines = [f"**Eventos encontrados para '{query}':**\n"]
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            summary = event.get('summary', 'Sin titulo')
            lines.append(f"  - {start}: **{summary}**")
        
        return "\n".join(lines)
    except Exception as e:
        return f"Error buscando eventos: {e}"


def _create_event(service, data: dict) -> str:
    """Crea un nuevo evento en el calendario principal."""
    summary = data.get("summary")
    start_time = data.get("start_time")
    end_time = data.get("end_time")

    if not summary or not start_time or not end_time:
        return "Error: summary, start_time y end_time son requeridos (formato ISO 8601)."

    event = {
        'summary': summary,
        'description': data.get("description", ""),
        'start': {
            'dateTime': start_time,
            'timeZone': data.get("timezone", "America/Bogota"),
        },
        'end': {
            'dateTime': end_time,
            'timeZone': data.get("timezone", "America/Bogota"),
        },
    }

    try:
        event = service.events().insert(calendarId='primary', body=event).execute()
        html_link = event.get('htmlLink', '')
        logger.info(f"[google_calendar] Evento creado: {summary}")
        return f"✅ Evento creado exitosamente: **{summary}**.\nLink: {html_link}"
    except Exception as e:
        logger.error(f"Error creando evento: {e}")
        return f"Error creando evento: {e}"
