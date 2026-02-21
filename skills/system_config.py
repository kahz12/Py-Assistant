"""
skills/system_config.py -- Configuracion del sistema operativo.

Permite consultar y modificar ajustes del sistema Linux:
  - Ver/cambiar hostname, timezone, idioma.
  - Gestionar servicios systemd.
  - Consultar informacion de red (interfaces, DNS).
  - Listar paquetes instalados.
  - Verificar espacio en disco.

SEGURIDAD: Todas las acciones de escritura requieren confirmacion
explicita. Las funciones de lectura son seguras.

Interfaz del skill:
    SKILL_NAME = "system_config"
    execute(action, value=None, service=None) -> str
"""
import subprocess
import shutil
from pathlib import Path
from loguru import logger

SKILL_NAME = "system_config"
SKILL_DESCRIPTION = "Configuracion del sistema: timezone, servicios, red, paquetes."


def execute(
    action: str,
    value: str = None,
    service: str = None,
    confirmed: bool = False,
) -> str:
    """
    Punto de entrada principal del skill.

    Acciones de LECTURA (seguras):
      - 'info'           : Informacion general del sistema.
      - 'timezone'       : Muestra la zona horaria actual.
      - 'hostname'       : Muestra el hostname actual.
      - 'network'        : Muestra configuracion de red.
      - 'services'       : Lista servicios activos.
      - 'service_status' : Estado de un servicio especifico.
      - 'disk'           : Espacio en disco.
      - 'packages'       : Lista paquetes instalados (filtrable).
      - 'users'          : Lista usuarios del sistema.
      - 'env'            : Variables de entorno (filtradas).

    Acciones de ESCRITURA (requieren confirmed=True):
      - 'set_timezone'   : Cambia la zona horaria.
      - 'set_hostname'   : Cambia el hostname.

    Args:
        action: Accion a ejecutar.
        value: Valor para operaciones de escritura.
        service: Nombre del servicio (para service_status).
        confirmed: Si es True, permite operaciones de escritura.
    """
    # Acciones de lectura
    read_actions = {
        "info": lambda: _system_info(),
        "timezone": lambda: _get_timezone(),
        "hostname": lambda: _get_hostname(),
        "network": lambda: _network_info(),
        "services": lambda: _list_services(),
        "service_status": lambda: _service_status(service),
        "disk": lambda: _disk_usage(),
        "packages": lambda: _list_packages(value),
        "users": lambda: _list_users(),
        "env": lambda: _env_vars(value),
    }

    # Acciones de escritura
    write_actions = {
        "set_timezone": lambda: _set_timezone(value, confirmed),
        "set_hostname": lambda: _set_hostname(value, confirmed),
    }

    all_actions = {**read_actions, **write_actions}

    if action not in all_actions:
        available = ", ".join(all_actions.keys())
        return f"Accion no reconocida: {action}. Opciones: {available}"

    return all_actions[action]()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(cmd: list, timeout: int = 10) -> str:
    """Ejecuta un comando y retorna la salida."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip()
    except Exception as e:
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Acciones de lectura
# ---------------------------------------------------------------------------

def _system_info() -> str:
    """Informacion general del sistema."""
    lines = ["**Informacion del sistema:**\n"]

    # OS
    if Path("/etc/os-release").exists():
        content = Path("/etc/os-release").read_text()
        for line in content.splitlines():
            if line.startswith("PRETTY_NAME="):
                os_name = line.split("=", 1)[1].strip('"')
                lines.append(f"  SO: {os_name}")
                break

    # Kernel
    kernel = _run(["uname", "-r"])
    lines.append(f"  Kernel: {kernel}")

    # Hostname
    hostname = _run(["hostname"])
    lines.append(f"  Hostname: {hostname}")

    # Uptime
    try:
        uptime = float(Path("/proc/uptime").read_text().split()[0])
        days = int(uptime // 86400)
        hours = int((uptime % 86400) // 3600)
        lines.append(f"  Uptime: {days}d {hours}h")
    except Exception:
        pass

    # CPU
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text()
        model = [l for l in cpuinfo.splitlines() if "model name" in l]
        if model:
            cpu = model[0].split(":", 1)[1].strip()
            lines.append(f"  CPU: {cpu}")
        cores = len([l for l in cpuinfo.splitlines() if l.startswith("processor")])
        lines.append(f"  Cores: {cores}")
    except Exception:
        pass

    # RAM
    try:
        meminfo = Path("/proc/meminfo").read_text()
        for line in meminfo.splitlines():
            if "MemTotal" in line:
                kb = int(line.split(":")[1].strip().split()[0])
                lines.append(f"  RAM: {kb // 1024} MB")
                break
    except Exception:
        pass

    return "\n".join(lines)


def _get_timezone() -> str:
    """Retorna la zona horaria actual."""
    tz = _run(["timedatectl", "show", "--property=Timezone", "--value"])
    if tz:
        return f"Zona horaria: {tz}"
    try:
        return f"Zona horaria: {Path('/etc/timezone').read_text().strip()}"
    except Exception:
        return "No se pudo determinar la zona horaria."


def _get_hostname() -> str:
    """Retorna el hostname actual."""
    return f"Hostname: {_run(['hostname', '-f'])}"


def _network_info() -> str:
    """Muestra configuracion de red."""
    lines = ["**Configuracion de red:**\n"]

    # Interfaces
    ip_out = _run(["ip", "-br", "addr"])
    if ip_out:
        lines.append("Interfaces:")
        for line in ip_out.splitlines():
            parts = line.split()
            if len(parts) >= 3:
                iface, status = parts[0], parts[1]
                addrs = " ".join(parts[2:])
                lines.append(f"  - {iface} ({status}): {addrs}")

    # DNS
    try:
        resolv = Path("/etc/resolv.conf").read_text()
        nameservers = [l.split()[1] for l in resolv.splitlines() if l.startswith("nameserver")]
        if nameservers:
            lines.append(f"\nDNS: {', '.join(nameservers)}")
    except Exception:
        pass

    # Gateway
    gw = _run(["ip", "route", "show", "default"])
    if gw:
        lines.append(f"Gateway: {gw.split()[2] if len(gw.split()) > 2 else gw}")

    return "\n".join(lines)


def _list_services() -> str:
    """Lista los servicios systemd activos."""
    out = _run(["systemctl", "list-units", "--type=service", "--state=active", "--no-pager", "--plain"])
    if not out:
        return "No se pudieron listar los servicios."
    lines = out.splitlines()
    if len(lines) > 30:
        lines = lines[:30] + [f"\n... y {len(lines) - 30} mas"]
    return "Servicios activos:\n\n```\n" + "\n".join(lines) + "\n```"


def _service_status(service: str) -> str:
    """Estado de un servicio systemd (SEC-N09: nombre sanitizado)."""
    if not service:
        return "Error: nombre de servicio requerido."
    # Validar nombre de servicio: solo alfanumerico, guion, punto, @
    import re
    if not re.match(r'^[a-zA-Z0-9_.@-]+$', service):
        return f"Nombre de servicio invalido: {service}"
    out = _run(["systemctl", "status", service, "--no-pager"])
    return f"```\n{out[:2000]}\n```" if out else f"Servicio '{service}' no encontrado."


def _disk_usage() -> str:
    """Espacio en disco."""
    out = _run(["df", "-h", "--type=ext4", "--type=btrfs", "--type=xfs"])
    if not out:
        out = _run(["df", "-h"])
    return f"Espacio en disco:\n\n```\n{out}\n```"


def _list_packages(filter_str: str = None) -> str:
    """Lista paquetes instalados, con filtro opcional."""
    if shutil.which("dpkg"):
        cmd = ["dpkg", "-l"]
    elif shutil.which("rpm"):
        cmd = ["rpm", "-qa"]
    else:
        return "Gestor de paquetes no soportado."

    out = _run(cmd, timeout=15)
    if filter_str:
        lines = [l for l in out.splitlines() if filter_str.lower() in l.lower()]
        return f"Paquetes con '{filter_str}' ({len(lines)}):\n\n" + "\n".join(lines[:30])
    lines = out.splitlines()
    return f"Paquetes instalados ({len(lines)}):\n\n" + "\n".join(lines[:30]) + "\n\n..."


def _list_users() -> str:
    """Lista usuarios del sistema con shell de login."""
    try:
        passwd = Path("/etc/passwd").read_text()
        users = []
        for line in passwd.splitlines():
            parts = line.split(":")
            if len(parts) >= 7:
                shell = parts[6]
                if shell in ("/bin/bash", "/bin/zsh", "/usr/bin/zsh", "/bin/fish"):
                    users.append(f"  - {parts[0]} (UID: {parts[2]}, Home: {parts[5]})")
        return f"Usuarios con shell:\n\n" + "\n".join(users) if users else "Sin usuarios con shell."
    except Exception as e:
        return f"Error: {e}"


def _env_vars(filter_str: str = None) -> str:
    """Muestra variables de entorno (filtra las sensibles)."""
    import os
    sensitive = {"password", "secret", "token", "key", "api_key", "credential"}
    env = dict(os.environ)

    # Filtrar variables sensibles
    safe_env = {}
    for k, v in env.items():
        if any(s in k.lower() for s in sensitive):
            safe_env[k] = "***REDACTED***"
        else:
            safe_env[k] = v[:100]

    if filter_str:
        safe_env = {k: v for k, v in safe_env.items() if filter_str.lower() in k.lower()}

    if not safe_env:
        return "Sin variables que coincidan."
    items = [f"  {k}={v}" for k, v in sorted(safe_env.items())]
    if len(items) > 30:
        items = items[:30] + [f"\n... y {len(items) - 30} mas"]
    return "Variables de entorno:\n\n" + "\n".join(items)


# ---------------------------------------------------------------------------
# Acciones de escritura (requieren confirmacion)
# ---------------------------------------------------------------------------

def _set_timezone(value: str, confirmed: bool) -> str:
    """Cambia la zona horaria del sistema (SEC-N10: valor validado)."""
    if not value:
        return "Error: zona horaria requerida (ej: America/Bogota)."
    # Validar formato timezone: solo letras, numeros, /, guion bajo, + -
    import re
    if not re.match(r'^[a-zA-Z0-9/_+-]+$', value) or '..' in value:
        return f"Zona horaria invalida: {value}"
    if not confirmed:
        return f"CONFIRMACION REQUERIDA: Cambiar timezone a '{value}'. Usa confirmed=True para aplicar."
    out = _run(["sudo", "timedatectl", "set-timezone", value])
    if "Error" in out:
        return out
    logger.info(f"[system_config] Timezone cambiado a: {value}")
    return f"Zona horaria cambiada a: {value}"


def _set_hostname(value: str, confirmed: bool) -> str:
    """Cambia el hostname del sistema (SEC-N10: valor validado)."""
    if not value:
        return "Error: hostname requerido."
    # Validar formato hostname: solo alfanumerico y guiones
    import re
    if not re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?$', value) or len(value) > 63:
        return f"Hostname invalido: {value} (solo alfanumerico y guiones, max 63 chars)"
    if not confirmed:
        return f"CONFIRMACION REQUERIDA: Cambiar hostname a '{value}'. Usa confirmed=True para aplicar."
    out = _run(["sudo", "hostnamectl", "set-hostname", value])
    if "Error" in out:
        return out
    logger.info(f"[system_config] Hostname cambiado a: {value}")
    return f"Hostname cambiado a: {value}"
