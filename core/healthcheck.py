"""
core/healthcheck.py -- Verificacion de dependencias al inicio.

Comprueba que las herramientas del sistema y modulos Python necesarios
estan disponibles antes de arrancar el asistente.

Categorias:
  - CRITICO: Sin esto el asistente no funciona (Python deps, API key).
  - OPCIONAL: Funcionalidad reducida sin esto (ffmpeg, tesseract, etc.).

Uso:
    from core.healthcheck import run_healthcheck
    issues = run_healthcheck(config)
    # issues = {"critical": [...], "warnings": [...]}
"""
import os
import shutil
import importlib
from pathlib import Path
from loguru import logger


def run_healthcheck(config: dict = None) -> dict:
    """
    Ejecuta todas las verificaciones de salud del sistema.

    Args:
        config: Diccionario de configuracion (de settings.yaml).

    Returns:
        Diccionario con listas 'critical' y 'warnings'.
        Si hay items en 'critical', el sistema no deberia arrancar.
    """
    config = config or {}
    issues = {"critical": [], "warnings": []}

    _check_python_deps(issues)
    _check_credentials(config, issues)
    _check_system_tools(issues)
    _check_directories(config, issues)

    # Log de resultados
    if issues["critical"]:
        for c in issues["critical"]:
            logger.error(f"[HEALTHCHECK] CRITICO: {c}")
    if issues["warnings"]:
        for w in issues["warnings"]:
            logger.warning(f"[HEALTHCHECK] Aviso: {w}")

    total = len(issues["critical"]) + len(issues["warnings"])
    if total == 0:
        logger.info("[HEALTHCHECK] ✅ Todas las verificaciones pasaron.")
    else:
        logger.info(
            f"[HEALTHCHECK] {len(issues['critical'])} critico(s), "
            f"{len(issues['warnings'])} aviso(s)"
        )

    return issues


def _check_python_deps(issues: dict):
    """Verifica módulos Python necesarios."""
    # Criticos: sin estos el asistente no arranca
    critical_deps = {
        "openai": "openai (pip install openai)",
        "yaml": "pyyaml (pip install pyyaml)",
        "dotenv": "python-dotenv (pip install python-dotenv)",
        "loguru": "loguru (pip install loguru)",
        "telegram": "python-telegram-bot (pip install python-telegram-bot)",
        "cryptography": "cryptography (pip install cryptography)",
    }

    for module, install_msg in critical_deps.items():
        try:
            importlib.import_module(module)
        except ImportError:
            issues["critical"].append(f"Modulo Python faltante: {install_msg}")

    # Opcionales: funcionalidad reducida
    optional_deps = {
        "bcrypt": "bcrypt — autenticacion segura (pip install bcrypt)",
        "speech_recognition": "SpeechRecognition — reconocimiento de voz local (pip install SpeechRecognition)",
    }

    for module, desc in optional_deps.items():
        try:
            importlib.import_module(module)
        except ImportError:
            issues["warnings"].append(f"Modulo opcional no instalado: {desc}")


def _check_credentials(config: dict, issues: dict):
    """Verifica que las credenciales minimas esten configuradas."""
    llm_config = config.get("llm", {})
    provider = llm_config.get("provider", "groq").upper()

    # API key del LLM
    has_key = bool(llm_config.get("api_key")) or bool(os.getenv(f"{provider}_API_KEY"))
    if not has_key and provider != "OLLAMA":
        issues["critical"].append(
            f"API key del LLM no configurada. "
            f"Agrega {provider}_API_KEY en .env"
        )

    # Token de Telegram
    tg_config = config.get("telegram", {})
    has_token = bool(tg_config.get("bot_token")) or bool(os.getenv("TELEGRAM_BOT_TOKEN"))
    if not has_token:
        issues["critical"].append(
            "TELEGRAM_BOT_TOKEN no configurado en .env"
        )

    # APIs opcionales
    optional_keys = {
        "GOOGLE_MAPS_KEY": "Google Maps (geocode, rutas, places)",
        "OPENWEATHER_KEY": "OpenWeatherMap (clima detallado)",
        "NEWS_API_KEY": "NewsAPI (noticias)",
        "HASS_TOKEN": "Home Assistant (hogar inteligente)",
        "OPENAI_API_KEY": "OpenAI Whisper (transcripcion de voz) / GPT-4 Vision",
    }

    missing_optional = []
    for key, desc in optional_keys.items():
        if not os.getenv(key):
            missing_optional.append(f"  {key} — {desc}")

    if missing_optional:
        issues["warnings"].append(
            "APIs opcionales sin configurar:\n" + "\n".join(missing_optional)
        )


def _check_system_tools(issues: dict):
    """Verifica herramientas del sistema operativo."""
    # Herramientas y que skill las necesita
    tools = {
        # Criticas
        # (ninguna herramienta del SO es critica para arrancar)
    }

    optional_tools = {
        "ffmpeg": "media_tools — conversion de audio/video",
        "ffprobe": "media_tools — informacion de archivos multimedia",
        "convert": "media_tools — redimensionar imagenes (ImageMagick)",
        "identify": "deep_learning — analisis basico de imagenes (ImageMagick)",
        "tesseract": "deep_learning — OCR (sudo apt install tesseract-ocr)",
        "scrot": "device_access — capturas de pantalla",
        "fswebcam": "device_access — captura de webcam",
        "arecord": "device_access — grabacion de audio",
        "sensors": "device_access — sensores de hardware (lm-sensors)",
        "git": "git_manager — control de versiones",
    }

    missing = []
    for tool, desc in optional_tools.items():
        if not shutil.which(tool):
            missing.append(f"  {tool} — {desc}")

    if missing:
        issues["warnings"].append(
            "Herramientas del sistema no encontradas:\n" + "\n".join(missing)
        )


def _check_directories(config: dict, issues: dict):
    """Verifica que los directorios necesarios existan."""
    vault_path = config.get("vault", {}).get("path", "memory_vault")
    vault = Path(vault_path)

    if not vault.exists():
        issues["warnings"].append(
            f"Directorio vault no existe: {vault}. Se creara automaticamente."
        )

    logs_dir = Path("logs")
    if not logs_dir.exists():
        issues["warnings"].append(
            f"Directorio de logs no existe: {logs_dir}. Se creara automaticamente."
        )


def format_report(issues: dict) -> str:
    """Formatea el reporte de healthcheck para consola."""
    lines = []

    if issues["critical"]:
        lines.append("❌ ERRORES CRITICOS:")
        for c in issues["critical"]:
            lines.append(f"   • {c}")

    if issues["warnings"]:
        lines.append("⚠️  AVISOS:")
        for w in issues["warnings"]:
            # Indentación para multi-linea
            for i, line in enumerate(w.split("\n")):
                prefix = "   • " if i == 0 else "     "
                lines.append(f"{prefix}{line}")

    if not issues["critical"] and not issues["warnings"]:
        lines.append("✅ Todas las verificaciones pasaron.")

    return "\n".join(lines)
