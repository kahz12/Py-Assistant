"""
main.py -- Punto de entrada del Asistente Personal AI.

Responsabilidades:
  - Cargar variables de entorno y configuracion desde YAML.
  - Inicializar todos los componentes del sistema (LLM, Soul, Memoria, Auth, MCP, Skills).
  - Arrancar el bot de Telegram como interfaz principal de comunicacion.

Ejecucion:
  python main.py
"""
import os
import sys
import resource
from pathlib import Path
from dotenv import load_dotenv
import yaml
from loguru import logger

# ---------------------------------------------------------------------------
# Seguridad del proceso
# ---------------------------------------------------------------------------
# umask 077: todos los archivos creados por el proceso seran 600/700.
# RLIMIT_CORE = 0: deshabilita core dumps para evitar filtrar credenciales.
# ---------------------------------------------------------------------------
os.umask(0o077)
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

# ---------------------------------------------------------------------------
# Configuracion de logging (loguru)
# ---------------------------------------------------------------------------
# Se eliminan los handlers por defecto y se configuran tres destinos:
#   1. stderr  -- salida visible en terminal durante desarrollo.
#   2. assistant.log -- registro general (DEBUG), rotacion cada 10 MB, 30 dias de retencion.
#   3. errors.log -- solo errores (ERROR), con backtrace completo para depuracion.
#   4. security.log -- eventos relacionados con autenticacion, pairing y seguridad.
# ---------------------------------------------------------------------------

logger.remove()

logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> -- <level>{message}</level>",
    level="INFO",
)

logger.add(
    "logs/assistant.log",
    rotation="10 MB",
    retention="30 days",
    level="DEBUG",
)

logger.add(
    "logs/errors.log",
    rotation="5 MB",
    retention="7 days",
    level="ERROR",
    backtrace=True,
    diagnose=True,
)

logger.add(
    "logs/security.log",
    rotation="5 MB",
    retention="90 days",
    level="WARNING",
    filter=lambda record: any(
        kw in record["message"].lower()
        for kw in ["auth", "pairing", "pair", "denegado", "reset", "rate limit", "bloqueado"]
    ),
)


# ---------------------------------------------------------------------------
# Funciones de configuracion
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """Lee y retorna el contenido de config/settings.yaml como diccionario."""
    config_path = Path(__file__).parent / "config" / "settings.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config


def resolve_env_vars(config: dict) -> dict:
    """
    Recorre el diccionario de configuracion y sustituye valores
    con formato '${VAR_NAME}' por el valor real de la variable de entorno.

    Si la variable no existe, emite un warning pero no detiene la ejecucion.
    """
    for key, value in config.items():
        if isinstance(value, dict):
            config[key] = resolve_env_vars(value)
        elif isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            env_var = value[2:-1]
            env_value = os.getenv(env_var)
            if env_value:
                config[key] = env_value
            else:
                logger.warning(f"Variable de entorno no encontrada: {env_var}")
    return config


# ---------------------------------------------------------------------------
# Entrada principal
# ---------------------------------------------------------------------------

def main():
    """
    Inicializa todos los subsistemas y arranca el bot de Telegram.

    Orden de inicializacion:
      1. Variables de entorno (.env)
      2. Configuracion (settings.yaml + security_config.yaml)
      3. Validacion de credenciales obligatorias (API key, bot token)
      4. Componentes: LLM Engine, Soul, Memory, Auth, MCP, Skills
      5. Orquestador (Assistant)
      6. Interfaz de comunicacion (Telegram)
    """
    print("""
    =============================================
             Py-Assistant -- A R I A
    ---------------------------------------------
          Inicializando sistemas...
    =============================================
    """)

    # -- Paso 1: Variables de entorno --
    load_dotenv()
    logger.info("Variables de entorno cargadas.")

    # -- Paso 2: Configuracion YAML --
    config = load_config()
    config = resolve_env_vars(config)
    logger.info("Configuracion cargada desde settings.yaml.")

    # -- Paso 2.5: Healthcheck del sistema --
    from core.healthcheck import run_healthcheck, format_report
    health = run_healthcheck(config)
    report = format_report(health)
    if report:
        print(report)
    if health["critical"]:
        logger.error("Healthcheck fallido. Corrige los errores criticos antes de continuar.")
        sys.exit(1)


    # -- Paso 3: Validacion de credenciales --
    llm_config = config.get("llm", {})
    telegram_config = config.get("telegram", {})

    provider = llm_config.get("provider", "groq").upper()
    if not llm_config.get("api_key"):
        # Intento de auto-descubrimiento basado en proveedor
        auto_key = os.getenv(f"{provider}_API_KEY")
        if auto_key:
            llm_config["api_key"] = auto_key
        # En proveedores locales como ollama, la key no siempre es necesaria,
        # pero para APIs externas si.  
        elif provider not in ["OLLAMA"]:
            logger.error(f"{provider}_API_KEY no configurada. Revisa el archivo .env o settings.yaml")
            sys.exit(1)

    # Auto-descubrimiento para base_url si aplica
    if not llm_config.get("base_url"):
        auto_url = os.getenv(f"{provider}_BASE_URL")
        if auto_url:
            llm_config["base_url"] = auto_url

    bot_token = telegram_config.get("bot_token")
    if not bot_token:
        logger.error("TELEGRAM_BOT_TOKEN no configurado. Revisa el archivo .env")
        sys.exit(1)

    # -- Paso 4: Resolucion de rutas --
    project_dir = Path(__file__).parent
    vault_path = Path(config.get("vault", {}).get("path", "memory_vault"))
    if not vault_path.is_absolute():
        vault_path = project_dir / vault_path

    # -- Paso 5: Inicializacion de componentes --
    logger.info("Inicializando componentes del asistente...")

    # Motor de lenguaje (LLM)
    from core.llm_engine import create_engine
    llm_engine = create_engine(llm_config)

    # Identidad del asistente (Soul)
    from core.soul import Soul
    soul = Soul(vault_path)

    # Gestor de memoria persistente
    from core.memory_manager import MemoryManager
    memory = MemoryManager(vault_path)

    # Gestor de autenticacion
    from core.auth import AuthManager
    auth_file = vault_path / ".auth"
    auth = AuthManager(auth_file)

    # Enrutador MCP y herramientas
    from mcp.mcp_router import MCPRouter
    mcp_router = MCPRouter()

    # Cargar politicas de seguridad para permisos del filesystem
    security_config_path = Path(__file__).parent / "config" / "security_config.yaml"
    security_config = {}
    if security_config_path.exists():
        with open(security_config_path, "r", encoding="utf-8") as f:
            security_config = yaml.safe_load(f) or {}

    # Registrar herramientas MCP en el router
    from mcp.tools import register_all_tools
    register_all_tools(mcp_router, vault_path, security_config, llm_engine=llm_engine)

    # Gestor de habilidades (Skills)
    from skills.skill_manager import SkillManager
    skills_dir = project_dir / "skills"
    skill_manager = SkillManager(skills_dir)

    # Orquestador principal (Assistant)
    from core.assistant import Assistant
    assistant_config = config.get("assistant", {})
    assistant = Assistant(
        name=assistant_config.get("name", "ARIA"),
        llm_engine=llm_engine,
        soul=soul,
        memory=memory,
        auth=auth,
        mcp_router=mcp_router,
        skill_manager=skill_manager,
        max_context_conversations=assistant_config.get("max_context_conversations", 5),
    )

    # -- Paso 6: Interfaz de Telegram --
    from communication.telegram_bot import TelegramInterface
    bot = TelegramInterface(
        token=bot_token,
        assistant=assistant,
        auth=auth,
        vault_path=vault_path,
    )

    logger.info("=" * 50)
    logger.info(f"{assistant_config.get('name', 'ARIA')} -- OPERACIONAL")
    logger.info("=" * 50)

    # -- Paso 7: Arranque del bot --
    try:
        bot.run()
    except KeyboardInterrupt:
        logger.info("Apagando asistente...")
        assistant.shutdown()
        logger.info("Asistente apagado correctamente.")


if __name__ == "__main__":
    main()
