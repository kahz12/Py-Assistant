"""
skills/deep_learning.py -- Capacidades de aprendizaje profundo.

Proporciona acceso a tareas de deep learning:
  - Descripcion de imagenes (via LLM multimodal o API).
  - Clasificacion de imagenes.
  - Analisis de audio (voz -> emocion, genero).
  - OCR (reconocimiento optico de caracteres).

Para modelos pesados (PyTorch, TensorFlow), se delega a APIs externas
o al LLM multimodal cuando esta disponible.

Para OCR usa tesseract si esta instalado.

Seguridad:
  - Solo procesa archivos en /home y /tmp.
  - Tamano maximo: 20 MB.
  - No ejecuta modelos arbitrarios.

Interfaz del skill:
    SKILL_NAME = "deep_learning"
    execute(action, file_path=None, llm_engine=None, ...) -> str
"""
import os
import subprocess
import shutil
import base64
from pathlib import Path
from loguru import logger

SKILL_NAME = "deep_learning"
SKILL_DESCRIPTION = "Deep learning: descripcion de imagenes, OCR, clasificacion."

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff"}


def execute(
    action: str,
    file_path: str = None,
    text: str = None,
    llm_engine=None,
) -> str:
    """
    Punto de entrada principal del skill.

    Acciones:
      - 'describe_image' : Describe el contenido de una imagen.
      - 'classify_image' : Clasifica una imagen en categorias.
      - 'ocr'            : Extrae texto de una imagen (tesseract).
      - 'analyze_text'   : Analisis profundo de texto (NER, relaciones).

    Args:
        action: Accion a ejecutar.
        file_path: Ruta al archivo (imagen/audio).
        text: Texto para analisis.
        llm_engine: Motor LLM.
    """
    actions = {
        "describe_image": lambda: _describe_image(file_path, llm_engine),
        "classify_image": lambda: _classify_image(file_path, llm_engine),
        "ocr": lambda: _ocr(file_path),
        "analyze_text": lambda: _deep_text_analysis(text, llm_engine),
    }

    if action not in actions:
        available = ", ".join(actions.keys())
        return f"Accion no reconocida: {action}. Opciones: {available}"

    return actions[action]()


# ---------------------------------------------------------------------------
# Seguridad
# ---------------------------------------------------------------------------

def _validate_file(path: str, valid_exts: set = None) -> str:
    """Valida acceso al archivo."""
    if not path:
        return "Error: ruta de archivo requerida."

    p = Path(path)
    resolved = str(p.resolve())
    allowed = ["/home", "/tmp"]
    if not any(resolved.startswith(a) for a in allowed):
        return f"Acceso denegado: {path} fuera de rutas permitidas."

    if not p.exists():
        return f"Archivo no encontrado: {path}"

    if p.stat().st_size > MAX_FILE_SIZE:
        return f"Archivo demasiado grande (max: {MAX_FILE_SIZE // 1024 // 1024} MB)."

    if valid_exts and p.suffix.lower() not in valid_exts:
        return f"Formato no soportado: {p.suffix}. Soportados: {', '.join(valid_exts)}"

    return ""


# ---------------------------------------------------------------------------
# Acciones
# ---------------------------------------------------------------------------

def _describe_image(file_path: str, llm_engine) -> str:
    """Describe una imagen usando LLM multimodal o analisis basico."""
    err = _validate_file(file_path, IMAGE_EXTENSIONS)
    if err:
        return err

    if not llm_engine:
        return "Error: motor LLM no disponible."

    # Intentar con LLM multimodal via API
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        return _describe_via_openai(file_path, api_key)

    # Fallback: analisis basico con ImageMagick
    if shutil.which("identify"):
        info = subprocess.run(
            ["identify", "-verbose", file_path],
            capture_output=True, text=True, timeout=10,
        )
        if info.returncode == 0:
            return f"Analisis basico de imagen:\n```\n{info.stdout[:2000]}\n```"

    return "Descripcion de imagenes requiere OPENAI_API_KEY o ImageMagick."


def _describe_via_openai(file_path: str, api_key: str) -> str:
    """Usa GPT-4 Vision para describir una imagen."""
    import urllib.request
    import json

    try:
        image_data = Path(file_path).read_bytes()
        b64 = base64.b64encode(image_data).decode("utf-8")
        ext = Path(file_path).suffix.lower().replace(".", "")
        mime = f"image/{ext}" if ext != "jpg" else "image/jpeg"

        payload = json.dumps({
            "model": "gpt-4o-mini",
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe esta imagen en detalle, en español."},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            }],
            "max_tokens": 500,
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        response = urllib.request.urlopen(req, timeout=30)
        data = json.loads(response.read().decode("utf-8"))
        desc = data["choices"][0]["message"]["content"]
        return f"**Descripcion de imagen:**\n\n{desc}"

    except Exception as e:
        logger.error(f"[deep_learning] Error OpenAI Vision: {e}")
        return f"Error describiendo imagen: {e}"


def _classify_image(file_path: str, llm_engine) -> str:
    """Clasifica una imagen en categorias generales."""
    err = _validate_file(file_path, IMAGE_EXTENSIONS)
    if err:
        return err

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return "Clasificacion de imagenes requiere OPENAI_API_KEY."

    import urllib.request
    import json

    try:
        image_data = Path(file_path).read_bytes()
        b64 = base64.b64encode(image_data).decode("utf-8")
        ext = Path(file_path).suffix.lower().replace(".", "")
        mime = f"image/{ext}" if ext != "jpg" else "image/jpeg"

        payload = json.dumps({
            "model": "gpt-4o-mini",
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Clasifica esta imagen. Responde en JSON: "
                            '{"categoria": "...", "subcategoria": "...", '
                            '"objetos": ["..."], "escena": "...", "confianza": 0.0-1.0}'
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            }],
            "max_tokens": 300,
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        response = urllib.request.urlopen(req, timeout=30)
        data = json.loads(response.read().decode("utf-8"))
        result = data["choices"][0]["message"]["content"]
        return f"**Clasificacion:**\n\n{result}"

    except Exception as e:
        return f"Error clasificando imagen: {e}"


def _ocr(file_path: str) -> str:
    """Extrae texto de una imagen usando Tesseract OCR."""
    err = _validate_file(file_path, IMAGE_EXTENSIONS)
    if err:
        return err

    if not shutil.which("tesseract"):
        return "OCR requiere Tesseract. Instala con: sudo apt install tesseract-ocr tesseract-ocr-spa"

    try:
        result = subprocess.run(
            ["tesseract", file_path, "-", "-l", "spa+eng"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return f"Error en OCR: {result.stderr[:300]}"

        text = result.stdout.strip()
        if not text:
            return "No se detecto texto en la imagen."

        logger.info(f"[deep_learning] OCR: {len(text)} chars extraidos")
        return f"**Texto extraido (OCR):**\n\n{text}"

    except Exception as e:
        return f"Error en OCR: {e}"


def _deep_text_analysis(text: str, llm_engine) -> str:
    """Analisis profundo de texto: NER, relaciones, intenciones."""
    if not text:
        return "Error: texto requerido."
    if not llm_engine:
        return "Error: motor LLM no disponible."

    if len(text) > 10000:
        text = text[:10000] + "\n[... truncado]"

    system = (
        "Realiza un analisis profundo del texto:\n"
        "1. **Entidades:** Personas, organizaciones, lugares, fechas, cantidades.\n"
        "2. **Relaciones:** Conexiones entre las entidades.\n"
        "3. **Intenciones:** Proposito del texto.\n"
        "4. **Temas:** Temas principales y secundarios.\n"
        "5. **Estructura:** Tipo de texto y organizacion.\n"
        "Responde de forma estructurada."
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": text},
    ]

    try:
        response = llm_engine.chat(messages)
        return response.get("content", "Sin respuesta.")
    except Exception as e:
        return f"Error en analisis: {e}"
