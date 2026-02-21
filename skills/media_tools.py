"""
skills/media_tools.py -- Herramientas de creacion y conversion de contenido multimedia.

Proporciona operaciones sobre archivos de audio, video e imagen
usando herramientas de linea de comandos (ffmpeg, ImageMagick).

Operaciones soportadas:
  - Conversion de formato (mp4->mp3, png->jpg, wav->ogg, etc.)
  - Informacion de archivos multimedia.
  - Redimensionar imagenes.
  - Extraer audio de video.
  - Recortar audio/video.

Dependencias del sistema: ffmpeg, imagemagick (convert)

Interfaz del skill:
    SKILL_NAME = "media_tools"
    execute(action, input_path=None, output_path=None, ...) -> str
"""
import os
import subprocess
from pathlib import Path
from loguru import logger

SKILL_NAME = "media_tools"
SKILL_DESCRIPTION = "Multimedia: convertir, redimensionar, extraer audio, info de archivos."


def execute(
    action: str,
    input_path: str = None,
    output_path: str = None,
    width: int = None,
    height: int = None,
    start_time: str = None,
    duration: str = None,
    format: str = None,
) -> str:
    """
    Punto de entrada principal del skill.

    Acciones disponibles:
      - 'convert'       : Convierte entre formatos de media.
      - 'info'          : Muestra informacion del archivo (duracion, codec, resolucion).
      - 'resize'        : Redimensiona una imagen.
      - 'extract_audio' : Extrae el audio de un video.
      - 'trim'          : Recorta un segmento de audio/video.

    Args:
        action: Accion a ejecutar.
        input_path: Ruta al archivo de entrada.
        output_path: Ruta al archivo de salida.
        width, height: Dimensiones para redimensionar.
        start_time: Tiempo de inicio para recortar (HH:MM:SS).
        duration: Duracion del segmento (HH:MM:SS o segundos).
        format: Formato de salida (mp3, mp4, jpg, png, etc.)
    """
    actions = {
        "convert": lambda: _convert(input_path, output_path, format),
        "info": lambda: _info(input_path),
        "resize": lambda: _resize(input_path, output_path, width, height),
        "extract_audio": lambda: _extract_audio(input_path, output_path, format),
        "trim": lambda: _trim(input_path, output_path, start_time, duration),
    }

    if action not in actions:
        available = ", ".join(actions.keys())
        return f"Accion no reconocida: {action}. Opciones: {available}"

    return actions[action]()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_tool(tool: str) -> str:
    """Verifica que una herramienta este instalada."""
    try:
        subprocess.run(["which", tool], capture_output=True, timeout=5, check=True)
        return ""
    except Exception:
        return f"{tool} no esta instalado. Instala con: sudo apt install {tool}"


def _validate_input(path: str) -> str:
    """Valida que el archivo de entrada exista y sea accesible (SEC-N06)."""
    if not path:
        return "Error: ruta de archivo requerida."
    resolved = str(Path(path).resolve())
    # Solo permitir archivos en /home y /tmp
    allowed = ["/home", "/tmp"]
    if not any(resolved.startswith(a) for a in allowed):
        return f"Acceso denegado: {path} esta fuera de las rutas permitidas."
    if not Path(path).exists():
        return f"Archivo no encontrado: {path}"
    return ""


def _sanitize_format(fmt: str) -> str:
    """Sanitiza el formato de salida (SEC-N07: solo alfanumerico)."""
    import re
    if fmt:
        return re.sub(r'[^a-zA-Z0-9]', '', fmt)
    return fmt


def _run(cmd: list, timeout: int = 60) -> tuple[str, str, int]:
    """Ejecuta un comando y retorna (stdout, stderr, returncode)."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "", f"Timeout: el proceso tardo mas de {timeout}s.", 1
    except Exception as e:
        return "", str(e), 1


# ---------------------------------------------------------------------------
# Acciones
# ---------------------------------------------------------------------------

def _convert(input_path: str, output_path: str, fmt: str = None) -> str:
    """Convierte un archivo multimedia a otro formato."""
    err = _validate_input(input_path)
    if err:
        return err

    if not output_path and not fmt:
        return "Error: especifica output_path o format."

    if not output_path:
        stem = Path(input_path).stem
        parent = Path(input_path).parent
        fmt = _sanitize_format(fmt)
        output_path = str(parent / f"{stem}.{fmt}")
    else:
        fmt = _sanitize_format(fmt)

    # Detectar si es imagen o audio/video
    ext_in = Path(input_path).suffix.lower()
    ext_out = Path(output_path).suffix.lower()
    image_exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".svg"}

    if ext_in in image_exts or ext_out in image_exts:
        check = _check_tool("convert")
        if check:
            return check
        cmd = ["convert", input_path, output_path]
    else:
        check = _check_tool("ffmpeg")
        if check:
            return check
        cmd = ["ffmpeg", "-i", input_path, "-y", output_path]

    stdout, stderr, rc = _run(cmd)
    if rc != 0:
        return f"Error en conversion: {stderr[:500]}"
    size = Path(output_path).stat().st_size if Path(output_path).exists() else 0
    return f"Convertido: {Path(input_path).name} -> {Path(output_path).name} ({size:,} bytes)"


def _info(input_path: str) -> str:
    """Muestra informacion detallada del archivo multimedia."""
    err = _validate_input(input_path)
    if err:
        return err

    check = _check_tool("ffprobe")
    if check:
        return check

    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", input_path
    ]
    stdout, stderr, rc = _run(cmd)
    if rc != 0:
        return f"Error obteniendo info: {stderr[:500]}"

    try:
        import json
        data = json.loads(stdout)
        fmt = data.get("format", {})
        streams = data.get("streams", [])

        lines = [f"**{Path(input_path).name}**"]
        lines.append(f"  Formato: {fmt.get('format_long_name', '?')}")
        duration = float(fmt.get("duration", 0))
        if duration:
            mins = int(duration // 60)
            secs = int(duration % 60)
            lines.append(f"  Duracion: {mins}:{secs:02d}")
        size = int(fmt.get("size", 0))
        lines.append(f"  Tamano: {size:,} bytes")

        for s in streams:
            codec_type = s.get("codec_type", "?")
            codec_name = s.get("codec_name", "?")
            if codec_type == "video":
                w = s.get("width", "?")
                h = s.get("height", "?")
                fps = s.get("r_frame_rate", "?")
                lines.append(f"  Video: {codec_name} {w}x{h} @ {fps} fps")
            elif codec_type == "audio":
                sr = s.get("sample_rate", "?")
                ch = s.get("channels", "?")
                lines.append(f"  Audio: {codec_name} {sr}Hz {ch}ch")

        return "\n".join(lines)
    except Exception as e:
        return f"Info (raw):\n{stdout[:2000]}"


def _resize(input_path: str, output_path: str, width: int = None, height: int = None) -> str:
    """Redimensiona una imagen."""
    err = _validate_input(input_path)
    if err:
        return err
    check = _check_tool("convert")
    if check:
        return check

    if not width and not height:
        return "Error: especifica width y/o height."

    if not output_path:
        p = Path(input_path)
        output_path = str(p.parent / f"{p.stem}_resized{p.suffix}")

    size_str = f"{width or ''}x{height or ''}"
    cmd = ["convert", input_path, "-resize", size_str, output_path]
    stdout, stderr, rc = _run(cmd)
    if rc != 0:
        return f"Error redimensionando: {stderr[:500]}"
    return f"Imagen redimensionada a {size_str}: {Path(output_path).name}"


def _extract_audio(input_path: str, output_path: str = None, fmt: str = None) -> str:
    """Extrae el audio de un archivo de video."""
    err = _validate_input(input_path)
    if err:
        return err
    check = _check_tool("ffmpeg")
    if check:
        return check

    if not output_path:
        stem = Path(input_path).stem
        parent = Path(input_path).parent
        ext = fmt or "mp3"
        output_path = str(parent / f"{stem}_audio.{ext}")

    cmd = ["ffmpeg", "-i", input_path, "-vn", "-y", output_path]
    stdout, stderr, rc = _run(cmd)
    if rc != 0:
        return f"Error extrayendo audio: {stderr[:500]}"
    return f"Audio extraido: {Path(output_path).name}"


def _trim(input_path: str, output_path: str = None, start: str = None, duration: str = None) -> str:
    """Recorta un segmento de audio o video."""
    err = _validate_input(input_path)
    if err:
        return err
    check = _check_tool("ffmpeg")
    if check:
        return check

    if not start:
        return "Error: start_time requerido (formato HH:MM:SS o segundos)."

    if not output_path:
        p = Path(input_path)
        output_path = str(p.parent / f"{p.stem}_trimmed{p.suffix}")

    cmd = ["ffmpeg", "-i", input_path, "-ss", start, "-y"]
    if duration:
        cmd.extend(["-t", duration])
    cmd.append(output_path)

    stdout, stderr, rc = _run(cmd)
    if rc != 0:
        return f"Error recortando: {stderr[:500]}"
    return f"Recortado: {Path(output_path).name} (desde {start}" + (f", duracion {duration})" if duration else ")")
