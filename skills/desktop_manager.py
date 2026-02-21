"""
skills/desktop_manager.py -- Control del sistema operativo.

Permite ejecutar aplicaciones, tomar screenshots, obtener informacion
del sistema, y ejecutar comandos en terminal.

Funciona en Linux con X11 o Wayland. Algunas acciones requieren
herramientas externas (xdotool, scrot) que deben estar instaladas.

Interfaz del skill:
    SKILL_NAME = "desktop_manager"
    execute(action, **kwargs) -> str
"""
import subprocess
import shutil
from pathlib import Path
from loguru import logger

SKILL_NAME = "desktop_manager"
SKILL_DESCRIPTION = "Control del escritorio: aplicaciones, screenshots, informacion del sistema."


def execute(action: str, **kwargs) -> str:
    """
    Punto de entrada principal del skill.

    Acciones disponibles:
      - 'open_app'       : Abre una aplicacion (app_name).
      - 'type_text'      : Escribe texto en la ventana activa (text).
      - 'screenshot'     : Captura la pantalla.
      - 'run_command'    : Ejecuta un comando en terminal (command).
      - 'list_processes' : Lista los procesos mas pesados.
      - 'system_info'    : Muestra informacion general del sistema.
      - 'disk_usage'     : Muestra el uso de disco.
      - 'network_info'   : Muestra informacion de red.

    Args:
        action: Accion a ejecutar.
        **kwargs: Argumentos especificos de cada accion.

    Returns:
        Resultado de la accion como texto.
    """
    actions = {
        "open_app": _open_app,
        "type_text": _type_text,
        "screenshot": _screenshot,
        "run_command": _run_command,
        "list_processes": _list_processes,
        "system_info": _system_info,
        "disk_usage": _disk_usage,
        "network_info": _network_info,
    }

    if action not in actions:
        available = ", ".join(actions.keys())
        return f"Accion no reconocida: {action}. Disponibles: {available}"

    try:
        return actions[action](**kwargs)
    except Exception as e:
        logger.error(f"[desktop_manager] Error en {action}: {e}")
        return f"Error en {action}: {e}"


# ---------------------------------------------------------------------------
# Aplicaciones y entrada
# ---------------------------------------------------------------------------

def _open_app(app_name: str = "", **_) -> str:
    """
    Abre una aplicacion del sistema por nombre de ejecutable.

    Verifica que el ejecutable exista en PATH antes de lanzarlo.
    """
    if not app_name:
        return "Error: especifica el nombre de la aplicacion."

    if not shutil.which(app_name):
        return f"Aplicacion '{app_name}' no encontrada en el sistema."

    try:
        subprocess.Popen(
            [app_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return f"Aplicacion abierta: {app_name}"
    except Exception as e:
        return f"Error abriendo {app_name}: {e}"


def _type_text(text: str = "", **_) -> str:
    """
    Escribe texto en la ventana activa usando xdotool.

    Requiere: sudo apt install xdotool
    """
    if not text:
        return "Error: texto vacio."

    if not shutil.which("xdotool"):
        return "xdotool no esta instalado. Instalar con: sudo apt install xdotool"

    import shlex
    try:
        subprocess.run(
            ["xdotool", "type", "--clearmodifiers", shlex.quote(str(text))],
            timeout=10,
        )
        return f"Texto escrito ({len(text)} caracteres)."
    except subprocess.TimeoutExpired:
        return "Timeout escribiendo texto."
    except Exception as e:
        return f"Error escribiendo texto: {e}"


# ---------------------------------------------------------------------------
# Screenshot
# ---------------------------------------------------------------------------

def _screenshot(**_) -> str:
    """
    Toma un screenshot de la pantalla completa.

    Intenta usar (en orden de prioridad): scrot, gnome-screenshot, import.
    El archivo se guarda en /tmp/screenshot.png.
    """
    screenshot_path = Path("/tmp/screenshot.png")

    tools = [
        (["scrot", "-z", str(screenshot_path)], "scrot"),
        (["gnome-screenshot", "-f", str(screenshot_path)], "gnome-screenshot"),
        (["import", "-window", "root", str(screenshot_path)], "imagemagick"),
    ]

    for cmd, name in tools:
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, timeout=10, capture_output=True)
                if screenshot_path.exists():
                    size = screenshot_path.stat().st_size
                    return f"Screenshot guardado en {screenshot_path} ({size:,} bytes)"
            except Exception:
                continue

    return "Herramienta de screenshot no encontrada. Instalar con: sudo apt install scrot"


# ---------------------------------------------------------------------------
# Ejecucion de comandos
# ---------------------------------------------------------------------------

def _run_command(command: str = "", **_) -> str:
    """
    Ejecuta un comando en el shell del sistema.

    Incluye una lista de comandos bloqueados por seguridad.
    Timeout de 30 segundos.
    """
    if not command:
        return "Error: comando vacio."

    dangerous = ["rm -rf /", "mkfs", "dd if=", ":(){", "shutdown", "reboot", "poweroff"]
    for d in dangerous:
        if d in command.lower():
            return f"Comando bloqueado por seguridad: {command}"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout[:3000] if result.stdout else ""
        errors = result.stderr[:1000] if result.stderr else ""
        response = f"$ {command}\n\n"
        if output:
            response += output
        if errors:
            response += f"\n[stderr]: {errors}"
        response += f"\n[exit: {result.returncode}]"
        return response
    except subprocess.TimeoutExpired:
        return f"Timeout: el comando tardo mas de 30 segundos."
    except Exception as e:
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Informacion del sistema
# ---------------------------------------------------------------------------

def _list_processes(**_) -> str:
    """Lista los 15 procesos con mayor consumo de memoria."""
    try:
        result = subprocess.run(
            ["ps", "aux", "--sort=-%mem"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        lines = result.stdout.strip().split("\n")
        output = "\n".join(lines[:16])
        return f"Procesos (top 15 por RAM):\n\n{output}"
    except Exception as e:
        return f"Error: {e}"


def _system_info(**_) -> str:
    """Retorna informacion general del sistema (hostname, OS, CPU, RAM, uptime)."""
    info = []
    commands = {
        "Hostname": "hostname",
        "OS": "cat /etc/os-release | head -2",
        "Kernel": "uname -r",
        "Arquitectura": "uname -m",
        "CPU": "lscpu | grep 'Model name' | head -1",
        "RAM total": "free -h | grep Mem | awk '{print $2}'",
        "RAM usada": "free -h | grep Mem | awk '{print $3}'",
        "Uptime": "uptime -p",
    }

    for label, cmd in commands.items():
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=5
            )
            value = result.stdout.strip()
            if value:
                info.append(f"  {label}: {value}")
        except Exception:
            continue

    return "Info del sistema:\n\n" + "\n".join(info) if info else "No se pudo obtener info del sistema."


def _disk_usage(**_) -> str:
    """Retorna el uso de disco de los sistemas de archivos principales."""
    try:
        result = subprocess.run(
            ["df", "-h", "--type=ext4", "--type=btrfs", "--type=xfs", "--type=vfat"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return f"Uso de disco:\n\n{result.stdout}"
    except Exception as e:
        return f"Error: {e}"


def _network_info(**_) -> str:
    """Retorna informacion de red (IP local, IP publica, gateway, DNS)."""
    info = []
    commands = {
        "IP local": "hostname -I",
        "IP publica": "curl -s --max-time 5 ifconfig.me",
        "Gateway": "ip route | grep default | awk '{print $3}'",
        "DNS": "cat /etc/resolv.conf | grep nameserver | head -2",
    }

    for label, cmd in commands.items():
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=8
            )
            value = result.stdout.strip()
            if value:
                info.append(f"  {label}: {value}")
        except Exception:
            continue

    return "Info de red:\n\n" + "\n".join(info) if info else "No se pudo obtener info de red."
