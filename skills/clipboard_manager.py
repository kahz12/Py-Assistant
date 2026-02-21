"""
skills/clipboard_manager.py -- Gestion del portapapeles del sistema.

Proporciona historial de portapapeles, copia/pegado programatico
y gestion de templates de texto reutilizables. Usa xclip como
backend (disponible en la mayoria de distribuciones Linux con X11).

Interfaz del skill:
    SKILL_NAME = "clipboard_manager"
    execute(action, text=None, template_name=None, vault_path=None) -> str
"""
import subprocess
import json
from datetime import datetime
from pathlib import Path
from loguru import logger

SKILL_NAME = "clipboard_manager"
SKILL_DESCRIPTION = "Portapapeles: copiar, pegar, historial, templates."

# Historial en memoria (se pierde al reiniciar el proceso)
_clipboard_history: list[dict] = []
MAX_HISTORY = 50


def execute(
    action: str,
    text: str = None,
    template_name: str = None,
    vault_path: str = None,
) -> str:
    """
    Punto de entrada principal del skill.

    Acciones disponibles:
      - 'copy'           : Copia texto al portapapeles.
      - 'paste'          : Lee el contenido actual del portapapeles.
      - 'history'        : Muestra el historial de copias.
      - 'clear'          : Limpia el portapapeles.
      - 'save_template'  : Guarda un template reutilizable.
      - 'load_template'  : Carga un template por nombre.
      - 'list_templates' : Lista todos los templates guardados.

    Args:
        action: Accion a ejecutar.
        text: Texto a copiar o contenido del template.
        template_name: Nombre del template (para save/load).
        vault_path: Ruta al vault para persistir templates.

    Returns:
        Resultado de la accion como texto.
    """
    actions = {
        "copy": lambda: _copy(text or ""),
        "paste": lambda: _paste(),
        "history": lambda: _get_history(),
        "clear": lambda: _clear(),
        "save_template": lambda: _save_template(template_name or "", text or "", vault_path),
        "load_template": lambda: _load_template(template_name or "", vault_path),
        "list_templates": lambda: _list_templates(vault_path),
    }

    if action not in actions:
        available = ", ".join(actions.keys())
        return f"Accion no reconocida: {action}. Opciones: {available}"

    return actions[action]()


# ---------------------------------------------------------------------------
# Deteccion del backend de portapapeles
# ---------------------------------------------------------------------------

def _get_clipboard_backend() -> str:
    """Detecta el backend disponible: xclip, xsel, o wl-copy (Wayland)."""
    for cmd in ["xclip", "xsel", "wl-copy"]:
        try:
            subprocess.run(
                ["which", cmd],
                capture_output=True,
                timeout=5,
            )
            return cmd
        except Exception:
            continue
    return ""


def _copy(text: str) -> str:
    """Copia texto al portapapeles del sistema."""
    if not text:
        return "Error: texto vacio."

    backend = _get_clipboard_backend()

    try:
        if backend == "xclip":
            proc = subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=5,
            )
        elif backend == "xsel":
            proc = subprocess.run(
                ["xsel", "--clipboard", "--input"],
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=5,
            )
        elif backend == "wl-copy":
            proc = subprocess.run(
                ["wl-copy"],
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=5,
            )
        else:
            return "Error: no se encontro xclip, xsel ni wl-copy. Instala con: sudo apt install xclip"

        if proc.returncode != 0:
            return f"Error copiando al portapapeles: {proc.stderr.decode()}"

        # Agregar al historial
        _clipboard_history.insert(0, {
            "text": text[:200],
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "length": len(text),
        })
        if len(_clipboard_history) > MAX_HISTORY:
            _clipboard_history.pop()

        logger.debug(f"[clipboard] Copiado: {len(text)} caracteres")
        return f"Copiado al portapapeles ({len(text)} caracteres)."

    except Exception as e:
        return f"Error: {e}"


def _paste() -> str:
    """Lee el contenido actual del portapapeles."""
    backend = _get_clipboard_backend()

    try:
        if backend == "xclip":
            proc = subprocess.run(
                ["xclip", "-selection", "clipboard", "-o"],
                capture_output=True,
                timeout=5,
            )
        elif backend == "xsel":
            proc = subprocess.run(
                ["xsel", "--clipboard", "--output"],
                capture_output=True,
                timeout=5,
            )
        elif backend == "wl-copy":
            proc = subprocess.run(
                ["wl-paste"],
                capture_output=True,
                timeout=5,
            )
        else:
            return "Error: no se encontro xclip, xsel ni wl-copy."

        content = proc.stdout.decode("utf-8", errors="ignore")
        if not content:
            return "Portapapeles vacio."
        return f"Contenido del portapapeles ({len(content)} chars):\n\n{content[:3000]}"

    except Exception as e:
        return f"Error: {e}"


def _get_history() -> str:
    """Retorna el historial de copias de la sesion actual."""
    if not _clipboard_history:
        return "Historial vacio."
    items = []
    for i, entry in enumerate(_clipboard_history[:15]):
        preview = entry["text"][:80].replace("\n", " ")
        items.append(f"  {i+1}. [{entry['timestamp']}] ({entry['length']} chars) {preview}")
    return f"Historial ({len(_clipboard_history)} entradas):\n\n" + "\n".join(items)


def _clear() -> str:
    """Limpia el portapapeles."""
    _copy(" ")
    _clipboard_history.clear()
    return "Portapapeles limpiado."


# ---------------------------------------------------------------------------
# Templates persistentes
# ---------------------------------------------------------------------------

def _templates_dir(vault_path: str = None) -> Path:
    """Retorna el directorio de templates, creandolo si no existe."""
    if vault_path:
        d = Path(vault_path) / "templates"
    else:
        d = Path("memory_vault") / "templates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_template(name: str, text: str, vault_path: str = None) -> str:
    """Guarda un template de texto reutilizable."""
    if not name:
        return "Error: nombre del template requerido."
    if not text:
        return "Error: contenido del template requerido."

    slug = name.lower().replace(" ", "_")[:30]
    filepath = _templates_dir(vault_path) / f"{slug}.txt"
    filepath.write_text(text, encoding="utf-8")
    logger.info(f"[clipboard] Template guardado: {slug}")
    return f"Template '{name}' guardado ({len(text)} caracteres)."


def _load_template(name: str, vault_path: str = None) -> str:
    """Carga un template por nombre y lo copia al portapapeles."""
    if not name:
        return "Error: nombre del template requerido."

    slug = name.lower().replace(" ", "_")[:30]
    filepath = _templates_dir(vault_path) / f"{slug}.txt"
    if not filepath.exists():
        return f"Template '{name}' no encontrado."

    content = filepath.read_text(encoding="utf-8")
    _copy(content)
    return f"Template '{name}' cargado y copiado al portapapeles ({len(content)} chars)."


def _list_templates(vault_path: str = None) -> str:
    """Lista todos los templates guardados."""
    tdir = _templates_dir(vault_path)
    templates = sorted(tdir.glob("*.txt"))
    if not templates:
        return "No hay templates guardados."
    items = []
    for t in templates:
        size = t.stat().st_size
        items.append(f"  - {t.stem} ({size} bytes)")
    return f"{len(templates)} templates:\n\n" + "\n".join(items)
