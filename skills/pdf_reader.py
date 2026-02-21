"""
skills/pdf_reader.py -- Lectura y procesamiento de archivos PDF.

Extrae texto de archivos PDF usando PyMuPDF (fitz). Soporta:
  - Extraccion de texto completo o por paginas.
  - Busqueda de texto dentro del PDF.
  - Resumen de metadata (titulo, autor, paginas).

Dependencia: pip install PyMuPDF

Interfaz del skill:
    SKILL_NAME = "pdf_reader"
    execute(action, file_path=None, query=None, page=None) -> str
"""
from pathlib import Path
from loguru import logger

SKILL_NAME = "pdf_reader"
SKILL_DESCRIPTION = "Lectura de PDFs: extraer texto, buscar, metadata."

# Limite de texto por pagina para no saturar el contexto del LLM
MAX_TEXT_PER_PAGE = 3000
MAX_TOTAL_TEXT = 8000


def execute(
    action: str,
    file_path: str = None,
    query: str = None,
    page: int = None,
) -> str:
    """
    Punto de entrada principal del skill.

    Acciones disponibles:
      - 'read'     : Extrae el texto completo del PDF.
      - 'read_page': Extrae el texto de una pagina especifica.
      - 'search'   : Busca texto dentro del PDF.
      - 'info'     : Muestra metadata del PDF.

    Args:
        action: Accion a ejecutar.
        file_path: Ruta al archivo PDF.
        query: Texto a buscar (para action='search').
        page: Numero de pagina 1-indexed (para action='read_page').

    Returns:
        Resultado de la accion como texto.
    """
    actions = {
        "read": lambda: _read_pdf(file_path),
        "read_page": lambda: _read_page(file_path, page),
        "search": lambda: _search_pdf(file_path, query),
        "info": lambda: _get_info(file_path),
    }

    if action not in actions:
        available = ", ".join(actions.keys())
        return f"Accion no reconocida: {action}. Opciones: {available}"

    return actions[action]()


# ---------------------------------------------------------------------------
# Implementaciones internas
# ---------------------------------------------------------------------------

def _open_pdf(file_path: str):
    """Abre un PDF y retorna el documento. Retorna (doc, None) o (None, error)."""
    try:
        import fitz
    except ImportError:
        return None, "PyMuPDF no instalado. Instala con: pip install PyMuPDF"

    if not file_path:
        return None, "Error: ruta de archivo requerida."

    path = Path(file_path)
    if not path.exists():
        return None, f"Archivo no encontrado: {file_path}"
    if not path.suffix.lower() == ".pdf":
        return None, f"No es un archivo PDF: {path.name}"
    if path.stat().st_size > 50_000_000:
        return None, f"Archivo demasiado grande ({path.stat().st_size / 1_000_000:.1f} MB). Maximo: 50MB."

    try:
        doc = fitz.open(str(path))
        return doc, None
    except Exception as e:
        return None, f"Error abriendo PDF: {e}"


def _read_pdf(file_path: str) -> str:
    """Extrae el texto completo del PDF, truncado a MAX_TOTAL_TEXT caracteres."""
    doc, error = _open_pdf(file_path)
    if error:
        return error

    text_parts = []
    total_length = 0

    for i, page in enumerate(doc):
        page_text = page.get_text().strip()
        if not page_text:
            continue
        text_parts.append(f"--- Pagina {i+1} ---\n{page_text[:MAX_TEXT_PER_PAGE]}")
        total_length += len(page_text)
        if total_length > MAX_TOTAL_TEXT:
            text_parts.append(f"\n[... truncado. {doc.page_count} paginas en total]")
            break

    doc.close()

    if not text_parts:
        return f"PDF sin texto extraible: {Path(file_path).name}"

    name = Path(file_path).name
    return f"**{name}** ({doc.page_count} paginas):\n\n" + "\n\n".join(text_parts)


def _read_page(file_path: str, page: int = None) -> str:
    """Extrae el texto de una pagina especifica (1-indexed)."""
    doc, error = _open_pdf(file_path)
    if error:
        return error

    if page is None:
        doc.close()
        return "Error: numero de pagina requerido."

    page_idx = page - 1
    if page_idx < 0 or page_idx >= doc.page_count:
        total = doc.page_count
        doc.close()
        return f"Pagina {page} fuera de rango. El PDF tiene {total} paginas."

    text = doc[page_idx].get_text().strip()
    doc.close()

    if not text:
        return f"Pagina {page} sin texto extraible."

    name = Path(file_path).name
    return f"**{name}** - Pagina {page}:\n\n{text[:MAX_TEXT_PER_PAGE]}"


def _search_pdf(file_path: str, query: str = None) -> str:
    """Busca texto dentro de todas las paginas del PDF."""
    doc, error = _open_pdf(file_path)
    if error:
        return error

    if not query:
        doc.close()
        return "Error: texto de busqueda requerido."

    query_lower = query.lower()
    results = []

    for i, page in enumerate(doc):
        text = page.get_text()
        if query_lower in text.lower():
            # Encontrar contexto alrededor de la coincidencia
            pos = text.lower().find(query_lower)
            start = max(0, pos - 100)
            end = min(len(text), pos + len(query) + 100)
            context = text[start:end].strip()
            results.append(f"  Pagina {i+1}: ...{context}...")

    doc.close()

    if not results:
        return f"'{query}' no encontrado en {Path(file_path).name}."

    name = Path(file_path).name
    return (
        f"'{query}' encontrado en {len(results)} pagina(s) de **{name}**:\n\n"
        + "\n\n".join(results[:10])
    )


def _get_info(file_path: str) -> str:
    """Retorna metadata del PDF: titulo, autor, paginas, tamaño."""
    doc, error = _open_pdf(file_path)
    if error:
        return error

    meta = doc.metadata
    size = Path(file_path).stat().st_size
    size_str = f"{size:,} bytes" if size < 1_000_000 else f"{size / 1_000_000:.1f} MB"

    info = [
        f"**{Path(file_path).name}**",
        f"  Paginas: {doc.page_count}",
        f"  Tamano: {size_str}",
    ]
    if meta.get("title"):
        info.append(f"  Titulo: {meta['title']}")
    if meta.get("author"):
        info.append(f"  Autor: {meta['author']}")
    if meta.get("subject"):
        info.append(f"  Asunto: {meta['subject']}")
    if meta.get("creator"):
        info.append(f"  Creador: {meta['creator']}")
    if meta.get("creationDate"):
        info.append(f"  Fecha: {meta['creationDate']}")

    doc.close()
    return "\n".join(info)
