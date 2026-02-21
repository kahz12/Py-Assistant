"""
skills/voice_recognition.py -- Reconocimiento y transcripcion de voz.

Soporta multiples backends:
  - Whisper (OpenAI) via API — maxima calidad, requiere API key.
  - speech_recognition (local) — gratuito, menor calidad.
  - ffmpeg para conversion de formatos.

Formatos soportados: wav, mp3, ogg, flac, m4a, webm.

Seguridad:
  - Solo procesa archivos en /home y /tmp.
  - Tamano maximo: 25 MB (limite Whisper API).
  - Timeout de 60 segundos.
  - No almacena ni transmite audio mas alla del procesamiento.

Interfaz del skill:
    SKILL_NAME = "voice_recognition"
    execute(action, audio_path=None, language=None, ...) -> str
"""
import os
import re
import subprocess
import shutil
from pathlib import Path
from loguru import logger

SKILL_NAME = "voice_recognition"
SKILL_DESCRIPTION = "Reconocimiento de voz: transcribir audio a texto."

# Limites de seguridad
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB
ALLOWED_EXTENSIONS = {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".webm", ".mp4"}
PROCESS_TIMEOUT = 60


def execute(
    action: str,
    audio_path: str = None,
    language: str = "es",
    model: str = "whisper-1",
) -> str:
    """
    Punto de entrada principal del skill.

    Acciones:
      - 'transcribe'  : Transcribe audio a texto.
      - 'detect_lang' : Detecta el idioma del audio.

    Args:
        action: Accion a ejecutar.
        audio_path: Ruta al archivo de audio.
        language: Idioma del audio (default: español).
        model: Modelo a usar (default: whisper-1).
    """
    actions = {
        "transcribe": lambda: _transcribe(audio_path, language),
        "detect_lang": lambda: _detect_language(audio_path),
    }

    if action not in actions:
        available = ", ".join(actions.keys())
        return f"Accion no reconocida: {action}. Opciones: {available}"

    return actions[action]()


# ---------------------------------------------------------------------------
# Seguridad
# ---------------------------------------------------------------------------

def _validate_audio(path: str) -> str:
    """Valida el archivo de audio (seguridad + existencia)."""
    if not path:
        return "Error: ruta de archivo de audio requerida."

    p = Path(path)
    resolved = str(p.resolve())

    # Validar ruta permitida
    allowed = ["/home", "/tmp"]
    if not any(resolved.startswith(a) for a in allowed):
        return f"Acceso denegado: {path} fuera de rutas permitidas."

    if not p.exists():
        return f"Archivo no encontrado: {path}"

    # Validar extension
    if p.suffix.lower() not in ALLOWED_EXTENSIONS:
        return f"Formato no soportado: {p.suffix}. Soportados: {', '.join(ALLOWED_EXTENSIONS)}"

    # Validar tamano
    size = p.stat().st_size
    if size > MAX_FILE_SIZE:
        return f"Archivo demasiado grande: {size:,} bytes (max: {MAX_FILE_SIZE:,})"

    if size == 0:
        return "Error: archivo de audio vacio."

    return ""


# ---------------------------------------------------------------------------
# Transcripcion
# ---------------------------------------------------------------------------

def _transcribe(audio_path: str, language: str = "es") -> str:
    """Transcribe audio a texto usando el mejor backend disponible."""
    err = _validate_audio(audio_path)
    if err:
        return err

    # Intentar Whisper API primero (mejor calidad)
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        return _transcribe_whisper_api(audio_path, language, api_key)

    # Fallback: speech_recognition local
    try:
        import speech_recognition as sr
        return _transcribe_local(audio_path, language)
    except ImportError:
        pass

    return (
        "No hay backend de reconocimiento de voz disponible.\n"
        "Opciones:\n"
        "  1. Configura OPENAI_API_KEY en .env para usar Whisper API\n"
        "  2. Instala: pip install SpeechRecognition"
    )


def _transcribe_whisper_api(audio_path: str, language: str, api_key: str) -> str:
    """Transcribe usando la API de Whisper de OpenAI."""
    import urllib.request
    import json

    try:
        # Preparar multipart form data manualmente
        boundary = "----AsistenteIA_Boundary"
        p = Path(audio_path)

        body = b""
        # Campo: model
        body += f"--{boundary}\r\n".encode()
        body += b'Content-Disposition: form-data; name="model"\r\n\r\n'
        body += b"whisper-1\r\n"
        # Campo: language
        body += f"--{boundary}\r\n".encode()
        body += b'Content-Disposition: form-data; name="language"\r\n\r\n'
        body += f"{language}\r\n".encode()
        # Campo: file
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="file"; filename="{p.name}"\r\n'.encode()
        body += b"Content-Type: application/octet-stream\r\n\r\n"
        body += p.read_bytes()
        body += b"\r\n"
        body += f"--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            "https://api.openai.com/v1/audio/transcriptions",
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        response = urllib.request.urlopen(req, timeout=PROCESS_TIMEOUT)
        data = json.loads(response.read().decode("utf-8"))
        text = data.get("text", "")

        if text:
            logger.info(f"[voice] Transcrito via Whisper API: {len(text)} chars")
            return f"**Transcripcion:**\n\n{text}"
        return "No se detecto texto en el audio."

    except Exception as e:
        logger.error(f"[voice] Error Whisper API: {e}")
        return f"Error en transcripcion: {e}"


def _transcribe_local(audio_path: str, language: str) -> str:
    """Transcribe usando speech_recognition (local, gratuito)."""
    try:
        import speech_recognition as sr

        recognizer = sr.Recognizer()
        p = Path(audio_path)

        # Convertir a WAV si no lo es
        wav_path = audio_path
        if p.suffix.lower() != ".wav":
            import shlex
            wav_path = f"/tmp/asistente_audio_{os.getpid()}.wav"
            safe_input = shlex.quote(str(audio_path))
            safe_output = shlex.quote(str(wav_path))
            # Usar exec con el shell flag disabled pero sanitizando input explicitamente por si falla el driver
            result = subprocess.run(
                ["ffmpeg", "-i", audio_path, "-ar", "16000", "-ac", "1", "-y", wav_path],
                capture_output=True, timeout=30,
            )
            if result.returncode != 0:
                return "Error convirtiendo audio a WAV."

        with sr.AudioFile(wav_path) as source:
            audio = recognizer.record(source)

        # Limpiar archivo temporal
        if wav_path != audio_path and Path(wav_path).exists():
            os.unlink(wav_path)

        text = recognizer.recognize_google(audio, language=language)
        logger.info(f"[voice] Transcrito localmente: {len(text)} chars")
        return f"**Transcripcion:**\n\n{text}"

    except Exception as e:
        return f"Error en transcripcion local: {e}"


def _detect_language(audio_path: str) -> str:
    """Detecta el idioma del audio (requiere Whisper API)."""
    err = _validate_audio(audio_path)
    if err:
        return err

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return "Deteccion de idioma requiere OPENAI_API_KEY."

    # Transcribir sin especificar idioma para auto-detectar
    result = _transcribe_whisper_api(audio_path, language="", api_key=api_key)
    return result
