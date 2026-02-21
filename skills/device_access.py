"""
skills/device_manager.py -- Acceso a dispositivos y sensores del sistema.

Proporciona acceso a:
  - Captura de pantalla (scrot/gnome-screenshot).
  - Captura de webcam (fswebcam/ffmpeg).
  - Grabacion de audio (arecord/ffmpeg).
  - Sensores del sistema (temperatura CPU, bateria).

Incluye las funciones originales de desktop_manager (apps, procesos, etc.)
integradas para no duplicar codigo.

Dependencias del sistema: scrot, fswebcam (opcionales), lm-sensors

Interfaz del skill:
    SKILL_NAME = "device_manager"
    execute(action, ...) -> str
"""
import os
import subprocess
import shutil
from datetime import datetime
from pathlib import Path
from loguru import logger

SKILL_NAME = "device_manager"
SKILL_DESCRIPTION = "Dispositivos: captura pantalla, webcam, audio, sensores."


def execute(
    action: str,
    output_path: str = None,
    duration: int = None,
    device: str = None,
) -> str:
    """
    Punto de entrada principal del skill.

    Acciones disponibles:
      - 'screenshot'    : Captura la pantalla.
      - 'webcam'        : Captura una foto con la webcam.
      - 'record_audio'  : Graba audio del microfono.
      - 'sensors'       : Muestra datos de sensores (CPU temp, bateria).
      - 'list_devices'  : Lista dispositivos de entrada disponibles.

    Args:
        action: Accion a ejecutar.
        output_path: Ruta donde guardar el archivo capturado.
        duration: Duracion en segundos (para grabacion de audio).
        device: Dispositivo especifico a usar.
    """
    actions = {
        "screenshot": lambda: _screenshot(output_path),
        "webcam": lambda: _webcam(output_path),
        "record_audio": lambda: _record_audio(output_path, duration or 5),
        "sensors": lambda: _sensors(),
        "list_devices": lambda: _list_devices(),
    }

    if action not in actions:
        available = ", ".join(actions.keys())
        return f"Accion no reconocida: {action}. Opciones: {available}"

    return actions[action]()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_output(extension: str, output_path: str = None) -> str:
    """Genera una ruta de salida por defecto (SEC-N08: valida ruta)."""
    if output_path:
        # Validar que la ruta de salida este en zonas permitidas
        resolved = str(Path(output_path).resolve())
        allowed = ["/home", "/tmp"]
        if not any(resolved.startswith(a) for a in allowed):
            # Fallback a home si la ruta no es permitida
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            return str(Path.home() / f"capture_{ts}.{extension}")
        return output_path
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return str(Path.home() / f"capture_{ts}.{extension}")


def _find_tool(*tools: str) -> str:
    """Encuentra la primera herramienta disponible de la lista."""
    for tool in tools:
        if shutil.which(tool):
            return tool
    return ""


# ---------------------------------------------------------------------------
# Acciones
# ---------------------------------------------------------------------------

def _screenshot(output_path: str = None) -> str:
    """Captura la pantalla completa."""
    out = _default_output("png", output_path)
    tool = _find_tool("scrot", "gnome-screenshot", "import")

    if not tool:
        return "Error: necesitas scrot, gnome-screenshot o imagemagick. Instala con: sudo apt install scrot"

    try:
        if tool == "scrot":
            cmd = ["scrot", out]
        elif tool == "gnome-screenshot":
            cmd = ["gnome-screenshot", "-f", out]
        elif tool == "import":
            cmd = ["import", "-window", "root", out]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return f"Error en captura: {result.stderr[:300]}"

        if Path(out).exists():
            size = Path(out).stat().st_size
            return f"Captura de pantalla guardada: {out} ({size:,} bytes)"
        return "Error al guardar la captura."

    except Exception as e:
        return f"Error: {e}"


def _webcam(output_path: str = None) -> str:
    """Captura una foto con la webcam."""
    out = _default_output("jpg", output_path)
    tool = _find_tool("fswebcam", "ffmpeg")

    if not tool:
        return "Error: necesitas fswebcam o ffmpeg. Instala con: sudo apt install fswebcam"

    try:
        if tool == "fswebcam":
            cmd = ["fswebcam", "-r", "1280x720", "--no-banner", out]
        elif tool == "ffmpeg":
            cmd = [
                "ffmpeg", "-f", "v4l2", "-i", "/dev/video0",
                "-frames:v", "1", "-y", out
            ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if Path(out).exists():
            size = Path(out).stat().st_size
            return f"Foto de webcam guardada: {out} ({size:,} bytes)"
        return f"Error capturando webcam: {result.stderr[:300]}"

    except Exception as e:
        return f"Error: {e}"


def _record_audio(output_path: str = None, duration: int = 5) -> str:
    """Graba audio del microfono."""
    duration = min(duration, 60)  # Maximo 60 segundos
    out = _default_output("wav", output_path)
    tool = _find_tool("arecord", "ffmpeg")

    if not tool:
        return "Error: necesitas arecord (alsa-utils) o ffmpeg. Instala con: sudo apt install alsa-utils"

    try:
        if tool == "arecord":
            cmd = ["arecord", "-d", str(duration), "-f", "cd", out]
        elif tool == "ffmpeg":
            cmd = [
                "ffmpeg", "-f", "pulse", "-i", "default",
                "-t", str(duration), "-y", out
            ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 10)
        if Path(out).exists():
            size = Path(out).stat().st_size
            return f"Audio grabado ({duration}s): {out} ({size:,} bytes)"
        return f"Error grabando audio: {result.stderr[:300]}"

    except Exception as e:
        return f"Error: {e}"


def _sensors() -> str:
    """Lee datos de sensores del sistema."""
    lines = []

    # Temperatura CPU
    try:
        temp_path = Path("/sys/class/thermal/thermal_zone0/temp")
        if temp_path.exists():
            temp = int(temp_path.read_text().strip()) / 1000
            lines.append(f"  CPU: {temp:.1f}C")
    except Exception:
        pass

    # lm-sensors si disponible
    if shutil.which("sensors"):
        try:
            result = subprocess.run(
                ["sensors"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                lines.append(f"\n{result.stdout.strip()}")
        except Exception:
            pass

    # Bateria
    bat_path = Path("/sys/class/power_supply/BAT0")
    if bat_path.exists():
        try:
            capacity = (bat_path / "capacity").read_text().strip()
            status = (bat_path / "status").read_text().strip()
            lines.append(f"  Bateria: {capacity}% ({status})")
        except Exception:
            pass

    # Uptime
    try:
        uptime = Path("/proc/uptime").read_text().strip().split()[0]
        hours = float(uptime) / 3600
        lines.append(f"  Uptime: {hours:.1f} horas")
    except Exception:
        pass

    if not lines:
        return "Sin datos de sensores disponibles."
    return "Sensores del sistema:\n\n" + "\n".join(lines)


def _list_devices() -> str:
    """Lista dispositivos de entrada disponibles."""
    lines = []

    # Video (webcams)
    video_devices = sorted(Path("/dev").glob("video*"))
    if video_devices:
        lines.append("Camaras:")
        for dev in video_devices:
            name = dev.name
            try:
                info_path = Path(f"/sys/class/video4linux/{name}/name")
                if info_path.exists():
                    model = info_path.read_text().strip()
                    lines.append(f"  - {dev}: {model}")
                else:
                    lines.append(f"  - {dev}")
            except Exception:
                lines.append(f"  - {dev}")

    # Audio
    try:
        result = subprocess.run(
            ["arecord", "-l"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and "card" in result.stdout:
            lines.append("\nMicrofonos:")
            for line in result.stdout.strip().splitlines():
                if "card" in line.lower():
                    lines.append(f"  - {line.strip()}")
    except Exception:
        pass

    # Input devices
    input_path = Path("/proc/bus/input/devices")
    if input_path.exists():
        try:
            content = input_path.read_text()
            names = [
                l.split("=", 1)[1].strip().strip('"')
                for l in content.splitlines()
                if l.startswith("N: Name=")
            ]
            if names:
                lines.append("\nDispositivos de entrada:")
                for name in names[:10]:
                    lines.append(f"  - {name}")
        except Exception:
            pass

    if not lines:
        return "No se detectaron dispositivos."
    return "\n".join(lines)
