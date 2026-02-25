"""
plugins/reminder_plugin.py -- Recordatorios persistentes con APScheduler.

Permite crear, listar y cancelar recordatorios que el asistente enviara
al usuario por Telegram en el momento indicado.

Usa APScheduler (ya instalado) y persiste los recordatorios en
memory_vault/reminders.json para sobrevivir reinicios.

Acciones:
    add    : Crear un recordatorio (fecha/hora o en N minutos/horas).
    list   : Ver recordatorios pendientes.
    cancel : Cancelar un recordatorio por ID.
    clear  : Eliminar todos los recordatorios pendientes.
    help   : Instrucciones de uso.

Formato de fecha soportado:
    - "en 10 minutos" / "en 2 horas" / "en 1 dia"
    - "2026-03-01 08:00" (ISO parcial)
    - "mañana 09:00"
    - Timestamp Unix (int como string)
"""
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from loguru import logger

SKILL_NAME = "reminder"
SKILL_DISPLAY_NAME = "Recordatorios"
SKILL_DESCRIPTION = (
    "Crea, lista y cancela recordatorios que el asistente enviara "
    "por Telegram en el momento indicado. Persiste entre reinicios."
)
VERSION = "1.1.0"
AUTHOR = "local"
REQUIRES_ENV = []
ACTIONS = ["add", "list", "cancel", "clear", "help"]

_STORAGE_PATH: Path = Path("memory_vault/reminders.json")
_scheduler_ref: dict = {"scheduler": None, "send_fn": None}


# ---------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------

def _load() -> list[dict]:
    """Carga recordatorios desde disco."""
    try:
        if _STORAGE_PATH.exists():
            return json.loads(_STORAGE_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"[reminder] Error cargando reminders.json: {e}")
    return []


def _save(reminders: list[dict]):
    """Persiste recordatorios a disco atomicamente."""
    try:
        _STORAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STORAGE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(reminders, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_STORAGE_PATH)
    except Exception as e:
        logger.error(f"[reminder] Error guardando reminders.json: {e}")


def _next_id(reminders: list[dict]) -> str:
    ids = [int(r["id"]) for r in reminders if str(r["id"]).isdigit()]
    return str(max(ids, default=0) + 1)


# ---------------------------------------------------------------------------
# Parseo de fecha
# ---------------------------------------------------------------------------

_RE_IN = re.compile(
    r"en\s+(\d+)\s+(minuto|minutos|hora|horas|dia|dias|d[ií]a|d[ií]as)",
    re.IGNORECASE,
)
_RE_TOMORROW = re.compile(r"ma[ñn]ana\s+(\d{1,2}):(\d{2})", re.IGNORECASE)
_RE_ISO = re.compile(r"(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})")


def _parse_when(when_str: str) -> datetime | None:
    """
    Parsea una descripcion de tiempo en un objeto datetime.
    Retorna None si no puede parsear.
    """
    when_str = when_str.strip()
    now = datetime.now()

    # "en N minutos/horas/dias"
    m = _RE_IN.search(when_str)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        if "min" in unit:
            return now + timedelta(minutes=n)
        if "hora" in unit:
            return now + timedelta(hours=n)
        if "d" in unit:
            return now + timedelta(days=n)

    # "mañana HH:MM"
    m = _RE_TOMORROW.search(when_str)
    if m:
        tomorrow = (now + timedelta(days=1)).date()
        return datetime(tomorrow.year, tomorrow.month, tomorrow.day,
                        int(m.group(1)), int(m.group(2)))

    # "YYYY-MM-DD HH:MM"
    m = _RE_ISO.search(when_str)
    if m:
        try:
            return datetime.fromisoformat(f"{m.group(1)} {m.group(2)}:{m.group(3)}")
        except ValueError:
            pass

    # Timestamp Unix
    if when_str.isdigit():
        return datetime.fromtimestamp(int(when_str))

    return None


# ---------------------------------------------------------------------------
# APScheduler integration (inyectada opcionalmente desde main.py)
# ---------------------------------------------------------------------------

def set_scheduler(scheduler, send_fn=None):
    """
    Inyecta el scheduler de APScheduler y una funcion de envio.

    Args:
        scheduler: Instancia de AssistantScheduler o BackgroundScheduler.
        send_fn: Callable(message:str) que envia el recordatorio al usuario.
    """
    _scheduler_ref["scheduler"] = scheduler
    _scheduler_ref["send_fn"] = send_fn
    logger.info("[reminder] Scheduler inyectado correctamente.")
    # Recuperar recordatorios pendientes y re-schedularlos
    _reschedule_pending()


def _reschedule_pending():
    """Re-programa los recordatorios persistidos al arrancar."""
    scheduler = _scheduler_ref.get("scheduler")
    if not scheduler:
        return
    reminders = [r for r in _load() if not r.get("sent")]
    now_ts = time.time()
    for r in reminders:
        if r["timestamp"] > now_ts:
            _schedule_one(r)
        else:
            # Ya vencio mientras el sistema estuvo apagado
            r["sent"] = True
            r["missed"] = True
    _save(reminders)


def _schedule_one(reminder: dict):
    """Programa un job en APScheduler para el recordatorio dado."""
    scheduler = _scheduler_ref.get("scheduler")
    send_fn = _scheduler_ref.get("send_fn")
    if not scheduler or not send_fn:
        return

    rid = reminder["id"]
    run_time = datetime.fromtimestamp(reminder["timestamp"])
    msg = reminder["message"]

    def _fire():
        logger.info(f"[reminder] Disparando recordatorio #{rid}: {msg}")
        try:
            send_fn(f"⏰ **Recordatorio #{rid}:**\n{msg}")
        except Exception as e:
            logger.error(f"[reminder] Error enviando recordatorio: {e}")
        # Marcar como enviado en disco
        items = _load()
        for item in items:
            if item["id"] == rid:
                item["sent"] = True
        _save(items)

    try:
        # Compatibilidad con AssistantScheduler y BackgroundScheduler raw
        internal = getattr(scheduler, "_scheduler", scheduler)
        internal.add_job(
            _fire,
            trigger="date",
            run_date=run_time,
            id=f"reminder_{rid}",
            replace_existing=True,
            misfire_grace_time=3600,
        )
    except Exception as e:
        logger.warning(f"[reminder] No se pudo programar recordatorio #{rid}: {e}")


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------

def execute(
    action: str = "list",
    message: str = "",
    when: str = "",
    reminder_id: str = "",
    **kwargs,
) -> str:
    """
    Gestiona recordatorios persistentes.

    Args:
        action     : "add", "list", "cancel", "clear" o "help".
        message    : Texto del recordatorio (para action="add").
        when       : Cuando disparar. Ej: "en 30 minutos", "2026-03-01 09:00".
        reminder_id: ID del recordatorio a cancelar (para action="cancel").
    """
    action = action.lower().strip()

    if action == "help":
        return (
            "**Plugin Recordatorios — Uso:**\n\n"
            "  `add` message=<texto> when=<cuando>\n"
            "     Formatos de 'when':\n"
            "       • 'en 30 minutos' / 'en 2 horas' / 'en 1 dia'\n"
            "       • 'mañana 08:30'\n"
            "       • '2026-03-15 10:00'\n\n"
            "  `list`           Recordatorios pendientes\n"
            "  `cancel` reminder_id=<id>  Cancelar uno\n"
            "  `clear`          Eliminar todos los pendientes"
        )

    reminders = _load()

    if action == "add":
        if not message:
            return "Especifica el mensaje. Ej: action='add', message='Llamar al medico', when='en 1 hora'"
        if not when:
            return "Especifica cuando. Ej: when='en 30 minutos', when='mañana 09:00'"

        dt = _parse_when(when)
        if dt is None:
            return (
                f"No pude entender la fecha '{when}'. "
                "Usa: 'en 30 minutos', 'en 2 horas', 'mañana 08:00' o '2026-03-01 10:00'."
            )

        now = datetime.now()
        if dt <= now:
            return f"La fecha '{when}' ya paso. Por favor elige un momento en el futuro."

        rid = _next_id(reminders)
        reminder = {
            "id": rid,
            "message": message,
            "timestamp": dt.timestamp(),
            "when_str": dt.strftime("%d/%m/%Y %H:%M"),
            "created_at": now.strftime("%d/%m/%Y %H:%M"),
            "sent": False,
            "missed": False,
        }
        reminders.append(reminder)
        _save(reminders)
        _schedule_one(reminder)

        delta = dt - now
        h, rem = divmod(int(delta.total_seconds()), 3600)
        m = rem // 60
        delta_str = f"{h}h {m}m" if h else f"{m}m"

        return (
            f"✅ **Recordatorio #{rid} creado**\n"
            f"📅 Para: {reminder['when_str']} (en {delta_str})\n"
            f"💬 Mensaje: {message}"
        )

    elif action == "list":
        pending = [r for r in reminders if not r.get("sent")]
        if not pending:
            return "No hay recordatorios pendientes."
        lines = [f"⏰ **Recordatorios pendientes** ({len(pending)})\n"]
        now_ts = time.time()
        for r in sorted(pending, key=lambda x: x["timestamp"]):
            secs_left = int(r["timestamp"] - now_ts)
            h, rem = divmod(secs_left, 3600)
            m = rem // 60
            time_left = f"{h}h {m}m" if h >= 1 else f"{m}m"
            lines.append(
                f"  **#{r['id']}** | {r['when_str']} (en {time_left})\n"
                f"     💬 {r['message']}"
            )
        return "\n".join(lines)

    elif action == "cancel":
        if not reminder_id:
            pending = [r for r in reminders if not r.get("sent")]
            if not pending:
                return "No hay recordatorios pendientes que cancelar."
            ids = ", ".join(r["id"] for r in pending)
            return f"Especifica el ID a cancelar. IDs pendientes: {ids}"

        found = False
        for r in reminders:
            if r["id"] == str(reminder_id) and not r.get("sent"):
                r["sent"] = True
                r["cancelled"] = True
                found = True
                # Intentar quitar del APScheduler
                try:
                    sched = _scheduler_ref.get("scheduler")
                    if sched:
                        internal = getattr(sched, "_scheduler", sched)
                        internal.remove_job(f"reminder_{reminder_id}")
                except Exception:
                    pass
                break
        if not found:
            return f"Recordatorio #{reminder_id} no encontrado o ya enviado."
        _save(reminders)
        return f"🗑️ Recordatorio #{reminder_id} cancelado."

    elif action == "clear":
        pending = [r for r in reminders if not r.get("sent")]
        for r in reminders:
            if not r.get("sent"):
                r["sent"] = True
                r["cancelled"] = True
        _save(reminders)
        if not pending:
            return "No habia recordatorios pendientes."
        return f"🗑️ {len(pending)} recordatorio(s) cancelados."

    else:
        return f"Accion '{action}' no soportada. Usa: {', '.join(ACTIONS)}."
