"""
core/agent_spawner.py -- Sistema de Sub-Agentes (Multi-Agent Execution).

Inspirado en OpenClaw, permite que ARIA (el agente principal) delegue tareas
a agentes especializados y efimeros. Cada sub-agente:
  - Tiene su propia identidad (nombre, system prompt, rol).
  - Solo accede a las herramientas necesarias para su mision.
  - Es efimero: se crea, ejecuta y devuelve un resultado string.
  - Comparte el mismo LLM Engine que el agente principal.

Roles pre-definidos disponibles:
  - "investigador" : Busqueda web, scraping, extraccion de informacion.
  - "programador"  : Lectura/escritura de archivos y ejecucion de comandos.
  - "hogar"        : Control de dispositivos via Home Assistant.
  - "analista"     : Analisis de datos, resumenes y traducciones.
  - "escritor"     : Creacion y edicion de textos, articulos y documentos.
  - "creativo"     : Brainstorming, ideacion y contenido original.
  - "matematico"   : Calculo, algebra, estadistica y demostraciones.
  - "quimico"      : Quimica, formulas, reacciones y compuestos.
  - "astronomo"    : Astronomia, astrofisica, cosmologia.
  - "medico"       : Informacion medica de referencia (NO diagnostica).
  - "filosofo"     : Analisis filosofico, etica y epistemologia.
  - "juridico"     : Informacion juridica de referencia (NO asesoría legal).

Uso desde ARIA (via herramienta MCP delegar_tarea):
    spawner = AgentSpawner(llm_engine, mcp_router)
    resultado = await spawner.spawn("investigador", "Investiga X")
"""
import asyncio
from dataclasses import dataclass, field
from typing import Optional
from loguru import logger


@dataclass
class SubAgentConfig:
    """
    Configuracion de identidad y permisos de un sub-agente.

    Atributos:
        name: Nombre del sub-agente.
        role: Rol corto (ej. "investigador").
        system_prompt: Instrucciones especificas del rol.
        tools_whitelist: Lista de herramientas MCP permitidas. None = todas.
        max_tokens: Limite de tokens para la respuesta.
    """
    name: str
    role: str
    system_prompt: str
    tools_whitelist: Optional[list[str]] = field(default=None)
    max_tokens: int = 4096


# ---------------------------------------------------------------------------
# Roles pre-definidos
# ---------------------------------------------------------------------------

PREDEFINED_ROLES: dict[str, SubAgentConfig] = {

    "investigador": SubAgentConfig(
        name="Agente Investigador",
        role="investigador",
        system_prompt=(
            "Eres un agente de investigacion especializado. Tu unica mision es "
            "buscar, extraer y sintetizar informacion sobre el tema indicado. "
            "Usa todas las herramientas de busqueda disponibles para generar un "
            "informe completo, estructurado y con fuentes. No conveses, SOLO reporta."
        ),
        tools_whitelist=[
            "buscar_web", "extraer_texto_web", "buscar_imagen_web",
            "firecrawl", "descargar_archivo", "resumir_texto"
        ],
    ),

    "programador": SubAgentConfig(
        name="Agente Programador",
        role="programador",
        system_prompt=(
            "Eres un agente experto en programacion Python y scripting. "
            "Tu mision es escribir, editar o ejecutar codigo segun se te indique. "
            "Siempre verifica que el codigo funcione antes de reportar. "
            "Retorna el resultado o el contenido del archivo generado."
        ),
        tools_whitelist=[
            "leer_archivo", "escribir_archivo", "ejecutar_comando",
            "listar_directorio", "buscar_archivos", "info_archivo",
            "git_status", "git_log"
        ],
    ),

    "hogar": SubAgentConfig(
        name="Agente Control de Hogar",
        role="hogar",
        system_prompt=(
            "Eres un agente especializado en automatizacion del hogar via Home Assistant. "
            "Tu mision es controlar dispositivos, verificar estados y ejecutar servicios "
            "exactamente segun las instrucciones recibidas. "
            "Reporta el resultado de cada accion ejecutada."
        ),
        tools_whitelist=[
            "ha_dispositivos", "ha_estado", "ha_controlar", "ha_servicio"
        ],
    ),

    "analista": SubAgentConfig(
        name="Agente Analista de Datos",
        role="analista",
        system_prompt=(
            "Eres un agente especializado en analisis de datos y textos. "
            "Tu mision es resumir documentos, traducir textos, analizar informacion "
            "almacenada en la memoria y detectar patrones segun se te indique. "
            "Cuando necesites calcular estadisticas o procesar datos numericos, "
            "escribe y ejecuta el codigo Python necesario con ejecutar_comando. "
            "Presenta resultados en formato estructurado: tablas, listas o parrafos segun convenga."
        ),
        tools_whitelist=[
            "buscar_notas", "listar_notas", "leer_archivo",
            "resumir_texto", "traducir_texto",
            "ejecutar_comando", "guardar_nota",
        ],
    ),

    "escritor": SubAgentConfig(
        name="Agente Escritor",
        role="escritor",
        system_prompt=(
            "Eres un escritor profesional de alto nivel. Tu mision es crear, editar, "
            "corregir o mejorar textos en cualquier formato: ensayos, articulos, emails, "
            "resumenes, guiones, poesias o documentacion tecnica. "
            "Antes de escribir, consulta las notas del vault para incorporar contexto previo relevante. "
            "Devuelve siempre el texto terminado, pulido y listo para usar, con estructura clara "
            "(titulos, parrafos, conclusion segun corresponda). "
            "Si el texto debe guardarse, usa escribir_archivo con un nombre descriptivo."
        ),
        tools_whitelist=[
            "buscar_notas", "listar_notas", "guardar_nota",
            "leer_archivo", "escribir_archivo",
            "resumir_texto", "traducir_texto",
        ],
    ),

    "creativo": SubAgentConfig(
        name="Agente Creativo",
        role="creativo",
        system_prompt=(
            "Eres un agente de creatividad radical e ideacion sin limites. "
            "Tu mision es generar ideas originales, conceptos innovadores, nombres, "
            "slogans, narrativas, metaforas, mundos ficticios o soluciones disruptivas. "
            "Puedes buscar en la web si necesitas referencias, tendencias o inspiracion real. "
            "Estructura tu respuesta en al menos 3 opciones o variaciones diferentes. "
            "Sé especifico, evocador y usa lenguaje que genere impacto emocional. "
            "Al final, indica cual es tu opcion favorita y por que."
        ),
        tools_whitelist=[
            "buscar_web", "extraer_texto_web",
            "guardar_nota", "buscar_notas",
            "resumir_texto",
        ],
    ),

    "matematico": SubAgentConfig(
        name="Agente Matematico",
        role="matematico",
        system_prompt=(
            "Eres un matematico experto en algebra, calculo, estadistica, "
            "teoria de numeros, geometria y matematica discreta. "
            "Resuelve problemas SIEMPRE paso a paso, mostrando el razonamiento completo. "
            "Para calculos numericos, escribe un script Python y ejecutalo con ejecutar_comando. "
            "Formato de ejecucion: ejecutar_comando con comando='python3 -c \"import math; print(math.sqrt(2))\"'. "
            "Para calculos complejos, guarda el script en /tmp/calculo.py con escribir_archivo "
            "y luego ejecutalo con ejecutar_comando. "
            "Verifica siempre que el resultado sea razonable antes de reportarlo. "
            "Termina con un resumen claro del resultado final."
        ),
        tools_whitelist=[
            "ejecutar_comando", "escribir_archivo", "leer_archivo", "guardar_nota",
        ],
    ),

    "quimico": SubAgentConfig(
        name="Agente Quimico",
        role="quimico",
        system_prompt=(
            "Eres un quimico experto en quimica organica, inorganica, fisicoquimica "
            "y quimica computacional. Puedes analizar formulas moleculares, equilibrar "
            "ecuaciones quimicas, predecir reacciones, calcular masas molares y "
            "explicar propiedades de compuestos. "
            "Para calculos numericos (pH, concentraciones, estequiometria), escribe un "
            "script Python y ejecutalo con ejecutar_comando. "
            "Busca informacion cientifica actualizada cuando sea necesario y siempre cita fuentes. "
            "Estructura tu respuesta con: formula, propiedades, reacciones y aplicaciones."
        ),
        tools_whitelist=[
            "buscar_web", "extraer_texto_web", "firecrawl",
            "ejecutar_comando", "escribir_archivo",
            "guardar_nota", "resumir_texto",
        ],
    ),

    "astronomo": SubAgentConfig(
        name="Agente Astronomo",
        role="astronomo",
        system_prompt=(
            "Eres un astrofisico y astronomo con profundo conocimiento del cosmos: "
            "planetas, estrellas, galaxias, agujeros negros, ondas gravitacionales y cosmologia. "
            "Explica conceptos complejos de forma clara, estructurada y apasionada. "
            "Busca datos observacionales actualizados en NASA, ESA o bases de datos cientificas. "
            "Para calculos astronomicos (distancias en parsecs, luminosidad, velocidad de escape), "
            "escribe y ejecuta el script Python necesario con ejecutar_comando. "
            "Incluye siempre datos cuantitativos (distancias, temperaturas, masas) cuando sea relevante. "
            "Estructura tu respuesta con contexto, explicacion tecnica y dato curioso al final."
        ),
        tools_whitelist=[
            "buscar_web", "extraer_texto_web", "firecrawl",
            "ejecutar_comando", "escribir_archivo",
            "guardar_nota", "resumir_texto",
        ],
    ),

    "medico": SubAgentConfig(
        name="Agente Medico (Solo Referencia)",
        role="medico",
        system_prompt=(
            "Eres un asistente de informacion medica de referencia. "
            "IMPORTANTE: NO diagnosticas, NO prescribes y siempre recuerdas consultar "
            "a un profesional certificado. Puedes explicar condiciones medicas, "
            "medicamentos, anatomia y buenas practicas de salud con base cientifica. "
            "Siempre indica que tus respuestas son solo informativas."
        ),
        tools_whitelist=[
            "buscar_web", "extraer_texto_web", "firecrawl",
            "resumir_texto", "guardar_nota",
        ],
    ),

    "filosofo": SubAgentConfig(
        name="Agente Filosofo",
        role="filosofo",
        system_prompt=(
            "Eres un filosofo erudito con dominio de la historia de la filosofia occidental "
            "y oriental, logica formal, etica, epistemologia y metafisica. "
            "Cuando cites a un filosofo (ej. Kant, Nietzsche, Aristoteles), usa buscar_web "
            "para verificar la cita textual exacta y evitar imprecisiones. "
            "Analiza argumentos con rigor logico, identifica falacias por nombre, "
            "presenta al menos dos perspectivas filosoficas distintas y fomenta "
            "el pensamiento critico en el usuario. "
            "Estructura tu respuesta con: contexto historico, analisis del argumento, "
            "perspectivas y conclusion reflexiva."
        ),
        tools_whitelist=[
            "buscar_web", "extraer_texto_web",
            "buscar_notas", "guardar_nota",
            "resumir_texto",
        ],
    ),

    "juridico": SubAgentConfig(
        name="Agente Juridico (Solo Referencia)",
        role="juridico",
        system_prompt=(
            "Eres un asistente de informacion juridica de referencia. "
            "IMPORTANTE: No eres abogado y no provees asesoria legal vinculante. "
            "Puedes explicar leyes, contratos, terminos juridicos, derechos generales "
            "y procedimientos legales de forma informativa. "
            "Siempre recomienda consultar con un abogado certificado para casos reales."
        ),
        tools_whitelist=[
            "buscar_web", "extraer_texto_web", "firecrawl",
            "resumir_texto", "guardar_nota", "leer_archivo",
        ],
    ),
}


# ---------------------------------------------------------------------------
# Spawner principal
# ---------------------------------------------------------------------------

class AgentSpawner:
    """
    Factory para crear y ejecutar sub-agentes especializados.

    Cada sub-agente es una instancia ligera que reutiliza el LLM Engine
    del agente principal pero con su propio system prompt y set de herramientas.

    Atributos:
        _llm: Motor de lenguaje compartido.
        _mcp: Enrutador MCP del sistema principal.
        _custom_roles: Roles personalizados añadidos en tiempo de ejecucion.
    """

    def __init__(self, llm_engine, mcp_router):
        self._llm = llm_engine
        self._mcp = mcp_router
        self._custom_roles: dict[str, SubAgentConfig] = {}
        logger.info("AgentSpawner inicializado con roles pre-definidos.")

    def register_role(self, config: SubAgentConfig):
        """Registra un rol personalizado en tiempo de ejecucion."""
        self._custom_roles[config.role] = config
        logger.info(f"[AgentSpawner] Rol personalizado registrado: '{config.role}'")

    def get_available_roles(self) -> list[str]:
        """Retorna la lista de roles disponibles (pre-definidos + personalizados)."""
        all_roles = list(PREDEFINED_ROLES.keys()) + list(self._custom_roles.keys())
        return all_roles

    async def spawn(self, role: str, mission: str, context: str = "") -> str:
        """
        Crea un sub-agente efimero y ejecuta una mision.

        El sub-agente hereda el LLM Engine principal pero opera con
        su propio system prompt y solo las herramientas de su whitelist.

        Args:
            role: Nombre del rol (ej. "investigador", "programador").
            mission: Descripcion en lenguaje natural de la tarea a realizar.
            context: Fragmento resumido del historial de conversacion reciente
                     del agente principal (opcional). Mejora la coherencia en
                     delegaciones de seguimiento.

        Returns:
            Resultado de la mision como string.
        """
        # Buscar el config del rol
        config = PREDEFINED_ROLES.get(role) or self._custom_roles.get(role)
        if not config:
            available = self.get_available_roles()
            return (
                f"Error: rol de sub-agente '{role}' no existe. "
                f"Roles disponibles: {', '.join(available)}"
            )

        logger.info(f"[AgentSpawner] Spawning sub-agente '{config.name}' para mision: {mission[:80]}...")

        # Filtrar herramientas segun whitelist del rol
        all_tools = self._mcp.get_schemas()
        if config.tools_whitelist:
            tools = [
                t for t in all_tools
                if t.get("function", {}).get("name") in config.tools_whitelist
            ]
        else:
            tools = all_tools

        # Construir el contexto de mensajes para el sub-agente
        # Si hay historial reciente, se inyecta antes de la mision
        user_content = mission
        if context:
            user_content = (
                f"[CONTEXTO DE CONVERSACION RECIENTE]\n"
                f"{context}\n"
                f"[FIN DE CONTEXTO]\n\n"
                f"{mission}"
            )

        messages = [
            {"role": "system", "content": config.system_prompt},
            {"role": "user", "content": user_content},
        ]

        # Primera respuesta del sub-agente
        response = self._llm.chat(messages, tools=tools if tools else None)

        # Ciclo de tool-calling para el sub-agente (max 5 rondas)
        MAX_ROUNDS = 5
        rounds = 0
        import json
        while "tool_calls" in response and response["tool_calls"] and rounds < MAX_ROUNDS:
            rounds += 1
            tool_results = []
            for tc in response["tool_calls"]:
                func_info = tc.get("function", {})
                tool_name = func_info.get("name", "")

                # Seguridad: verificar que la herramienta esta en la whitelist
                if config.tools_whitelist and tool_name not in config.tools_whitelist:
                    result_str = f"[DENEGADO] La herramienta '{tool_name}' no esta permitida para este rol."
                    logger.warning(f"[AgentSpawner] Sub-agente '{role}' intento usar '{tool_name}' fuera de su whitelist.")
                else:
                    try:
                        raw = func_info.get("arguments") or "{}"
                        args = json.loads(raw) if isinstance(raw, str) else raw
                        if not isinstance(args, dict):
                            args = {}
                    except (json.JSONDecodeError, TypeError):
                        args = {}

                    result_str = self._mcp.execute(tool_name, **args)

                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": str(result_str),
                })

            messages.append(response)
            messages.extend(tool_results)
            response = self._llm.chat(messages)

        result = response.get("content", "El sub-agente no produjo una respuesta.")
        logger.info(f"[AgentSpawner] Sub-agente '{config.name}' completó su mision en {rounds} rondas de tools.")

        # Empaque del resultado con metadatos del sub-agente
        return (
            f"[{config.name.upper()}]\n"
            f"{'─' * 40}\n"
            f"{result}\n"
            f"{'─' * 40}"
        )
