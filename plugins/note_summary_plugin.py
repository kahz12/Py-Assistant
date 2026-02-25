"""
plugins/note_summary_plugin.py -- Plugin de resumen inteligente de notas.

Lee las notas del vault y genera resumenes, indices o busquedas
textuales sobre el contenido guardado.

No requiere API key externa — usa busqueda por keywords sobre el
sistema de archivos del vault.

Acciones:
    list     : Lista todas las notas con metadata.
    read     : Lee el contenido de una nota especifica.
    search   : Busqueda por keywords en todas las notas.
    summary  : Resumen estadistico del vault de notas.
    recent   : Notas modificadas en las ultimas N horas.
"""
import os
import re
import time
from pathlib import Path
from loguru import logger

SKILL_NAME = "notes"
SKILL_DISPLAY_NAME = "Gestor de Notas"
SKILL_DESCRIPTION = (
    "Lee, busca y resume notas del vault local. "
    "No requiere conexion a internet ni API keys."
)
VERSION = "1.0.0"
AUTHOR = "local"
REQUIRES_ENV = []
ACTIONS = ["list", "read", "search", "summary", "recent"]


def _get_notes_dir() -> Path:
    """Detecta el directorio de notas del vault."""
    candidates = [
        Path("memory_vault/notes"),
        Path("../memory_vault/notes"),
        Path(os.environ.get("VAULT_PATH", "memory_vault")) / "notes",
    ]
    for p in candidates:
        if p.exists():
            return p
    # Si no existe, devolver el primero y dejar que falle gracefully
    return candidates[0]


def _read_note_safe(path: Path, max_chars: int = 2000) -> str:
    """Lee una nota de forma segura con limite de caracteres."""
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
        if len(content) > max_chars:
            content = content[:max_chars] + f"\n\n… [+{len(path.read_text())-max_chars} caracteres]"
        return content
    except Exception as e:
        return f"(Error leyendo nota: {e})"


def execute(
    action: str = "summary",
    name: str = "",
    query: str = "",
    hours: int = 24,
    limit: int = 10,
    **kwargs,
) -> str:
    """
    Ejecuta una operacion sobre las notas del vault.

    Args:
        action  : "list", "read", "search", "summary" o "recent".
        name    : Nombre de la nota para la accion "read".
        query   : Termino de busqueda para la accion "search".
        hours   : Ventana de tiempo en horas para "recent" (default: 24).
        limit   : Numero maximo de resultados (default: 10).
    """
    action = action.lower().strip()
    notes_dir = _get_notes_dir()

    if not notes_dir.exists():
        return (
            f"Directorio de notas no encontrado: '{notes_dir}'. "
            "El vault podria no estar inicializado."
        )

    files = sorted(notes_dir.glob("*.*"), key=lambda f: f.stat().st_mtime, reverse=True)
    text_files = [f for f in files if f.suffix in (".md", ".txt", ".json")]

    # -- list ---------------------------------------------------------------
    if action == "list":
        if not text_files:
            return "No hay notas en el vault."
        lines = [f"📚 **Notas en el vault** ({len(text_files)} total)\n"]
        for i, f in enumerate(text_files[:limit], 1):
            mtime = time.strftime("%d/%m/%Y %H:%M", time.localtime(f.stat().st_mtime))
            size_kb = f.stat().st_size / 1024
            lines.append(f"  {i}. `{f.name}` ({size_kb:.1f} KB) — {mtime}")
        if len(text_files) > limit:
            lines.append(f"\n  … y {len(text_files) - limit} notas mas.")
        return "\n".join(lines)

    # -- read ---------------------------------------------------------------
    elif action == "read":
        if not name:
            return "Especifica el nombre de la nota. Ej: action='read', name='mi_nota.md'"
        # Buscar coincidencia exacta o parcial
        matches = [f for f in text_files if name.lower() in f.name.lower()]
        if not matches:
            return f"Nota '{name}' no encontrada en el vault."
        path = matches[0]
        content = _read_note_safe(path)
        mtime = time.strftime("%d/%m/%Y %H:%M", time.localtime(path.stat().st_mtime))
        return f"📄 **{path.name}** (modificado: {mtime})\n\n{content}"

    # -- search -------------------------------------------------------------
    elif action == "search":
        if not query:
            return "Especifica el termino de busqueda. Ej: action='search', query='python'"
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        results = []
        for f in text_files:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                matches_list = pattern.findall(content)
                if matches_list:
                    # Extraer un snippet del contexto
                    match = pattern.search(content)
                    start = max(0, match.start() - 60)
                    snippet = "…" + content[start:start + 150].replace("\n", " ") + "…"
                    results.append((f.name, len(matches_list), snippet))
            except Exception:
                continue
        if not results:
            return f"No se encontro '{query}' en ninguna nota del vault."
        lines = [f"🔍 **Busqueda:** '{query}' — {len(results)} nota(s)\n"]
        for fname, count, snippet in results[:limit]:
            lines.append(f"  📄 **{fname}** ({count} ocurrencia(s))")
            lines.append(f"     {snippet}\n")
        return "\n".join(lines)

    # -- summary ------------------------------------------------------------
    elif action == "summary":
        if not text_files:
            return "El vault de notas esta vacio."
        total_size = sum(f.stat().st_size for f in text_files)
        newest = text_files[0] if text_files else None
        oldest = text_files[-1] if text_files else None

        lines = [
            "📊 **Resumen del Vault de Notas**\n",
            f"  Total de notas: {len(text_files)}",
            f"  Peso total: {total_size / 1024:.1f} KB",
        ]
        if newest:
            mtime = time.strftime("%d/%m/%Y %H:%M", time.localtime(newest.stat().st_mtime))
            lines.append(f"  Mas reciente: `{newest.name}` ({mtime})")
        if oldest:
            mtime = time.strftime("%d/%m/%Y %H:%M", time.localtime(oldest.stat().st_mtime))
            lines.append(f"  Mas antigua: `{oldest.name}` ({mtime})")

        # Por extension
        by_ext: dict[str, int] = {}
        for f in text_files:
            by_ext[f.suffix] = by_ext.get(f.suffix, 0) + 1
        ext_str = ", ".join(f"{ext}: {count}" for ext, count in sorted(by_ext.items()))
        lines.append(f"  Por tipo: {ext_str}")
        return "\n".join(lines)

    # -- recent -------------------------------------------------------------
    elif action == "recent":
        cutoff = time.time() - (hours * 3600)
        recent = [f for f in text_files if f.stat().st_mtime >= cutoff]
        if not recent:
            return f"No hay notas modificadas en las ultimas {hours} horas."
        lines = [f"🕐 **Notas recientes** (ultimas {hours}h) — {len(recent)} nota(s)\n"]
        for i, f in enumerate(recent[:limit], 1):
            mtime = time.strftime("%d/%m/%Y %H:%M", time.localtime(f.stat().st_mtime))
            lines.append(f"  {i}. `{f.name}` — {mtime}")
        return "\n".join(lines)

    else:
        return (
            f"Accion '{action}' no soportada. "
            f"Disponibles: {', '.join(ACTIONS)}."
        )
