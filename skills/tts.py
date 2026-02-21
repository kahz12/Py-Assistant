"""
skills/tts.py -- Text-to-Speech (Texto a Voz).

Convierte texto a audio hablado usando:
  - OpenAI TTS API (alta calidad, requiere OPENAI_API_KEY).
  - pyttsx3 (offline, gratuito, calidad basica).
  - gTTS (Google Text-to-Speech, gratis, requiere internet).

Acciones soportadas:
  - speak     : Genera y reproduce audio directamente.
  - save      : Genera y guarda audio a archivo.
  - voices    : Lista voces disponibles.

Seguridad:
  - Texto limitado a 5000 caracteres.
  - Output path restringido a /home y /tmp.
  - API key desde variable de entorno (nunca hardcoded).

Configuracion en .env:
  OPENAI_API_KEY=sk-...  (opcional, para TTS de alta calidad)

Interfaz del skill:
    SKILL_NAME = "tts"
    execute(action, text=None, voice=None, output_path=None, engine=None) -> str
"""
import os
import re
import subprocess
from pathlib import Path
from loguru import logger

SKILL_NAME = "tts"
SKILL_DESCRIPTION = "Text-to-Speech: convertir texto a audio hablado."

MAX_TEXT_LENGTH = 5000

# Voces disponibles en OpenAI TTS
OPENAI_VOICES = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}
OPENAI_MODELS = {"tts-1", "tts-1-hd"}


def execute(
    action: str = "speak",
    text: str = None,
    voice: str = "nova",
    output_path: str = None,
    engine: str = None,
    language: str = "es",
) -> str:
    """
    Punto de entrada principal del skill.

    Args:
        action: 'speak' (reproducir), 'save' (guardar), 'voices' (listar).
        text: Texto a convertir en voz.
        voice: Voz a usar (para OpenAI: alloy, echo, fable, onyx, nova, shimmer).
        output_path: Ruta del archivo de salida (para action='save').
        engine: Motor a usar: 'openai', 'gtts', 'local'. Auto-detecta si no se especifica.
        language: Idioma para gTTS/local (default: 'es').
    """
    actions = {
        "speak": lambda: _speak(text, voice, engine, language),
        "save": lambda: _save(text, voice, output_path, engine, language),
        "voices": lambda: _list_voices(),
    }

    if action not in actions:
        return f"Accion no reconocida: {action}. Opciones: {', '.join(actions.keys())}"

    return actions[action]()


# ---------------------------------------------------------------------------
# Validaciones
# ---------------------------------------------------------------------------

def _validate_text(text: str) -> str:
    """Valida el texto de entrada."""
    if not text or not text.strip():
        return "Error: texto vacio. Proporciona el texto a convertir en voz."
    if len(text) > MAX_TEXT_LENGTH:
        return f"Error: texto demasiado largo ({len(text)} chars). Maximo: {MAX_TEXT_LENGTH}."
    return ""


def _validate_output_path(output_path: str) -> str:
    """Valida y sanitiza la ruta de salida."""
    if not output_path:
        return ""
    path = Path(output_path).resolve()
    allowed = [Path("/home"), Path("/tmp")]
    if not any(str(path).startswith(str(a)) for a in allowed):
        return f"Ruta denegada: {output_path}. Solo se permite /home y /tmp."
    return ""


def _get_default_output(ext: str = "mp3") -> str:
    """Genera ruta de salida por defecto."""
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path.home() / "tts_output"
    output_dir.mkdir(exist_ok=True)
    return str(output_dir / f"tts_{timestamp}.{ext}")


def _detect_engine() -> str:
    """Auto-detecta el mejor motor TTS disponible."""
    # Prioridad: OpenAI > gTTS > pyttsx3
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"

    try:
        import gtts  # noqa: F401
        return "gtts"
    except ImportError:
        pass

    try:
        import pyttsx3  # noqa: F401
        return "local"
    except ImportError:
        pass

    # Verificar si espeak esta disponible (Linux)
    if _has_command("espeak") or _has_command("espeak-ng"):
        return "espeak"

    return "none"


def _has_command(cmd: str) -> bool:
    """Verifica si un comando del sistema esta disponible."""
    try:
        subprocess.run(
            ["which", cmd],
            capture_output=True,
            timeout=5,
        )
        return subprocess.run(
            ["which", cmd], capture_output=True, timeout=5
        ).returncode == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Motores TTS
# ---------------------------------------------------------------------------

def _tts_openai(text: str, voice: str, output_path: str) -> str:
    """Genera audio con OpenAI TTS API."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return "Error: OPENAI_API_KEY no configurada para TTS."

    if voice not in OPENAI_VOICES:
        voice = "nova"

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        response = client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=text,
        )

        response.stream_to_file(output_path)
        logger.info(f"[TTS] OpenAI: audio generado en {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"[TTS] Error OpenAI: {e}")
        return f"Error generando audio con OpenAI: {str(e)[:200]}"


def _tts_gtts(text: str, output_path: str, language: str = "es") -> str:
    """Genera audio con Google Text-to-Speech (gratis)."""
    try:
        from gtts import gTTS
        tts = gTTS(text=text, lang=language, slow=False)
        tts.save(output_path)
        logger.info(f"[TTS] gTTS: audio generado en {output_path}")
        return output_path
    except ImportError:
        return "Error: gTTS no instalado. Instala con: pip install gTTS"
    except Exception as e:
        logger.error(f"[TTS] Error gTTS: {e}")
        return f"Error generando audio con gTTS: {str(e)[:200]}"


def _tts_local(text: str, output_path: str, language: str = "es") -> str:
    """Genera audio con pyttsx3 (offline)."""
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.save_to_file(text, output_path)
        engine.runAndWait()
        logger.info(f"[TTS] pyttsx3: audio generado en {output_path}")
        return output_path
    except ImportError:
        return "Error: pyttsx3 no instalado. Instala con: pip install pyttsx3"
    except Exception as e:
        logger.error(f"[TTS] Error pyttsx3: {e}")
        return f"Error generando audio localmente: {str(e)[:200]}"


def _tts_espeak(text: str, output_path: str, language: str = "es") -> str:
    """Genera audio con espeak/espeak-ng (Linux, sin dependencias Python)."""
    cmd_name = "espeak-ng" if _has_command("espeak-ng") else "espeak"
    try:
        # Sanitizar texto para command line
        safe_text = re.sub(r'[^\w\s.,!?;:áéíóúñüÁÉÍÓÚÑÜ¿¡-]', '', text)

        result = subprocess.run(
            [cmd_name, "-v", language, "-w", output_path, safe_text],
            capture_output=True,
            timeout=30,
            text=True,
        )
        if result.returncode == 0:
            logger.info(f"[TTS] espeak: audio generado en {output_path}")
            return output_path
        return f"Error espeak: {result.stderr[:200]}"
    except Exception as e:
        logger.error(f"[TTS] Error espeak: {e}")
        return f"Error generando audio con espeak: {str(e)[:200]}"


# ---------------------------------------------------------------------------
# Acciones
# ---------------------------------------------------------------------------

def _speak(text: str, voice: str, engine: str, language: str) -> str:
    """Genera audio y lo reproduce."""
    err = _validate_text(text)
    if err:
        return err

    eng = engine or _detect_engine()
    if eng == "none":
        return (
            "No hay motor TTS disponible. Instala uno de:\n"
            "  - OpenAI API key (alta calidad): OPENAI_API_KEY en .env\n"
            "  - gTTS (gratis): pip install gTTS\n"
            "  - pyttsx3 (offline): pip install pyttsx3\n"
            "  - espeak (Linux): sudo apt install espeak-ng"
        )

    output_path = _get_default_output("mp3" if eng in ("openai", "gtts") else "wav")
    result = _generate_audio(eng, text, voice, output_path, language)

    if result.startswith("Error"):
        return result

    # Reproducir con mpv, aplay, o paplay
    _play_audio(result)
    return f"✅ Audio reproducido. Archivo: `{result}`"


def _save(text: str, voice: str, output_path: str, engine: str, language: str) -> str:
    """Genera y guarda audio a archivo."""
    err = _validate_text(text)
    if err:
        return err

    if output_path:
        path_err = _validate_output_path(output_path)
        if path_err:
            return path_err
    else:
        eng = engine or _detect_engine()
        output_path = _get_default_output("mp3" if eng in ("openai", "gtts") else "wav")

    eng = engine or _detect_engine()
    if eng == "none":
        return "No hay motor TTS disponible. Instala gTTS, pyttsx3 o espeak-ng."

    result = _generate_audio(eng, text, voice, output_path, language)

    if result.startswith("Error"):
        return result

    return f"✅ Audio guardado en: `{result}`"


def _generate_audio(eng: str, text: str, voice: str, output_path: str, language: str) -> str:
    """Genera audio con el motor especificado."""
    generators = {
        "openai": lambda: _tts_openai(text, voice, output_path),
        "gtts": lambda: _tts_gtts(text, output_path, language),
        "local": lambda: _tts_local(text, output_path, language),
        "espeak": lambda: _tts_espeak(text, output_path, language),
    }

    gen = generators.get(eng)
    if not gen:
        return f"Error: motor TTS desconocido '{eng}'. Opciones: {', '.join(generators.keys())}"

    return gen()


def _play_audio(filepath: str):
    """Reproduce un archivo de audio con el reproductor disponible."""
    players = ["mpv", "paplay", "aplay", "ffplay"]
    for player in players:
        if _has_command(player):
            try:
                args = [player, filepath]
                if player == "ffplay":
                    args = [player, "-nodisp", "-autoexit", filepath]
                if player == "mpv":
                    args = [player, "--no-video", filepath]

                subprocess.Popen(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return
            except Exception:
                continue


def _list_voices() -> str:
    """Lista las voces disponibles por motor."""
    lines = ["**Voces disponibles:**\n"]

    # OpenAI
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    lines.append(f"### OpenAI TTS {'✅' if has_openai else '❌ (necesita OPENAI_API_KEY)'}")
    if has_openai:
        for v in sorted(OPENAI_VOICES):
            lines.append(f"  - `{v}`")

    # gTTS
    try:
        import gtts  # noqa: F401
        lines.append("\n### gTTS ✅")
        lines.append("  - Soporta 50+ idiomas (es, en, fr, de, pt, etc.)")
    except ImportError:
        lines.append("\n### gTTS ❌ (pip install gTTS)")

    # pyttsx3
    try:
        import pyttsx3  # noqa: F401
        lines.append("\n### pyttsx3 ✅ (offline)")
    except ImportError:
        lines.append("\n### pyttsx3 ❌ (pip install pyttsx3)")

    # espeak
    if _has_command("espeak-ng") or _has_command("espeak"):
        lines.append("\n### espeak-ng ✅ (Linux nativo)")
    else:
        lines.append("\n### espeak ❌ (sudo apt install espeak-ng)")

    engine = _detect_engine()
    lines.append(f"\n**Motor activo:** `{engine}`")

    return "\n".join(lines)
