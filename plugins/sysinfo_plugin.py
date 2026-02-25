"""
plugins/sysinfo_plugin.py -- Informacion del sistema (CPU, RAM, disco, temp, red).

Proporciona metricas de hardware en tiempo real. Ideal para monitorear
el Orange Pi Zero 2W o cualquier maquina Linux/Mac.

No requiere API key. Usa psutil (ya instalado via APScheduler) y
lectura directa de /sys/class/thermal para temperaturas en ARM.

Acciones:
    full     : Reporte completo de todo el sistema.
    cpu      : Uso de CPU y frecuencia.
    memory   : Uso de RAM y swap.
    disk     : Espacio en disco por particion.
    temp     : Temperaturas del hardware (sensores termicos).
    network  : Estadisticas de red (bytes enviados/recibidos).
    uptime   : Tiempo en linea del sistema.
"""
import os
import subprocess
import time
from pathlib import Path
from loguru import logger

SKILL_NAME = "sysinfo"
SKILL_DISPLAY_NAME = "Info del Sistema"
SKILL_DESCRIPTION = (
    "Reporta metricas de hardware en tiempo real: CPU, RAM, disco, "
    "temperatura y red. Ideal para monitorear el Orange Pi Zero 2W."
)
VERSION = "1.0.0"
AUTHOR = "local"
REQUIRES_ENV = []
ACTIONS = ["full", "cpu", "memory", "disk", "temp", "network", "uptime"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _try_psutil():
    try:
        import psutil
        return psutil
    except ImportError:
        return None


def _cpu_info(ps) -> str:
    if ps is None:
        return "psutil no disponible — instala: pip install psutil"
    pct = ps.cpu_percent(interval=0.5)
    count = ps.cpu_count(logical=True)
    phys = ps.cpu_count(logical=False) or count
    freq = ps.cpu_freq()
    freq_str = f"{freq.current:.0f} MHz" if freq else "—"
    load = os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0)
    return (
        f"💻 **CPU**\n"
        f"  Uso: {pct:.1f}%\n"
        f"  Nucleos: {phys} fisicos / {count} logicos\n"
        f"  Frecuencia: {freq_str}\n"
        f"  Carga (1/5/15 min): {load[0]:.2f} / {load[1]:.2f} / {load[2]:.2f}"
    )


def _mem_info(ps) -> str:
    if ps is None:
        return "psutil no disponible"
    vm = ps.virtual_memory()
    sw = ps.swap_memory()

    def _fmt(b): return f"{b / (1024**2):.0f} MB"

    return (
        f"🧠 **Memoria**\n"
        f"  RAM total : {_fmt(vm.total)}\n"
        f"  RAM usada : {_fmt(vm.used)} ({vm.percent:.1f}%)\n"
        f"  RAM libre : {_fmt(vm.available)}\n"
        f"  Swap total: {_fmt(sw.total)}\n"
        f"  Swap usada: {_fmt(sw.used)} ({sw.percent:.1f}%)"
    )


def _disk_info(ps) -> str:
    if ps is None:
        return "psutil no disponible"
    lines = ["💾 **Disco**"]
    seen = set()
    for part in ps.disk_partitions(all=False):
        if part.device in seen:
            continue
        seen.add(part.device)
        try:
            usage = ps.disk_usage(part.mountpoint)
            total_gb = usage.total / (1024**3)
            used_gb = usage.used / (1024**3)
            free_gb = usage.free / (1024**3)
            lines.append(
                f"  {part.mountpoint}: {used_gb:.1f}/{total_gb:.1f} GB "
                f"({usage.percent:.0f}% usado, {free_gb:.1f} GB libre)"
            )
        except (PermissionError, OSError):
            continue
    return "\n".join(lines) if len(lines) > 1 else "Sin informacion de disco."


def _temp_info() -> str:
    """
    Lee temperaturas de hardware.
    Prioriza /sys/class/thermal (ARM, Linux) luego psutil.sensors_temperatures().
    """
    readings = []

    # Metodo 1: /sys/class/thermal (Orange Pi, Raspberry Pi, etc.)
    thermal_dir = Path("/sys/class/thermal")
    if thermal_dir.exists():
        for zone in sorted(thermal_dir.glob("thermal_zone*")):
            temp_file = zone / "temp"
            type_file = zone / "type"
            try:
                temp_c = int(temp_file.read_text().strip()) / 1000
                zone_type = type_file.read_text().strip() if type_file.exists() else zone.name
                readings.append(f"  {zone_type}: {temp_c:.1f}°C")
            except Exception:
                continue

    # Metodo 2: psutil (Linux x86, etc.)
    if not readings:
        try:
            import psutil
            if hasattr(psutil, "sensors_temperatures"):
                for name, entries in (psutil.sensors_temperatures() or {}).items():
                    for e in entries:
                        lbl = e.label or name
                        readings.append(f"  {lbl}: {e.current:.1f}°C")
        except Exception:
            pass

    if not readings:
        return "🌡️ **Temperatura**: No disponible en este sistema."

    return "🌡️ **Temperatura**\n" + "\n".join(readings)


def _net_info(ps) -> str:
    if ps is None:
        return "psutil no disponible"

    def _fmt(b): return f"{b / (1024**2):.1f} MB"

    counters = ps.net_io_counters(pernic=True)
    lines = ["🌐 **Red**"]
    for iface, c in counters.items():
        if iface == "lo":
            continue
        lines.append(
            f"  {iface}: ↑{_fmt(c.bytes_sent)} / ↓{_fmt(c.bytes_recv)} "
            f"| pkts ↑{c.packets_sent:,} ↓{c.packets_recv:,}"
        )
    return "\n".join(lines) if len(lines) > 1 else "Sin interfaces de red activas."


def _uptime_info() -> str:
    try:
        import psutil
        boot = psutil.boot_time()
        secs = int(time.time() - boot)
    except ImportError:
        # Leer /proc/uptime en Linux
        try:
            secs = int(float(Path("/proc/uptime").read_text().split()[0]))
        except Exception:
            return "⏱️ **Uptime**: No disponible."

    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    days, h = divmod(h, 24)
    parts = []
    if days:
        parts.append(f"{days}d")
    if h:
        parts.append(f"{h}h")
    parts.append(f"{m}m {s}s")
    return f"⏱️ **Uptime**: {' '.join(parts)}"


# ---------------------------------------------------------------------------
# Main execute
# ---------------------------------------------------------------------------

def execute(action: str = "full", **kwargs) -> str:
    """
    Reporta informacion del sistema.

    Args:
        action: "full", "cpu", "memory", "disk", "temp", "network" o "uptime".
    """
    ps = _try_psutil()
    action = action.lower().strip()

    sections = {
        "cpu": lambda: _cpu_info(ps),
        "memory": lambda: _mem_info(ps),
        "disk": lambda: _disk_info(ps),
        "temp": _temp_info,
        "network": lambda: _net_info(ps),
        "uptime": _uptime_info,
    }

    if action == "full":
        parts = [_uptime_info(), _cpu_info(ps), _mem_info(ps),
                 _disk_info(ps), _temp_info(), _net_info(ps)]
        return "\n\n".join(parts)

    if action in sections:
        return sections[action]()

    return (
        f"Accion '{action}' no soportada. "
        f"Disponibles: {', '.join(ACTIONS)}."
    )
