"""
core/assistant.py -- Orquestador principal del asistente.

Recibe mensajes del usuario, construye el contexto (soul + memoria),
invoca al LLM con herramientas MCP disponibles, y gestiona el ciclo
de tool-calling cuando el modelo decide usar herramientas.

Integra todas las capas: Soul, Memory, LLM, MCP, Skills.
"""
import json
from pathlib import Path
from loguru import logger
from core.soul import Soul
from core.memory_manager import MemoryManager
from core.llm_engine import BaseLLMEngine
from core.auth import AuthManager
from mcp.mcp_router import MCPRouter
from skills.skill_manager import SkillManager


class Assistant:
    """
    Orquestador que conecta todos los subsistemas del asistente.

    Flujo de procesamiento:
      1. Obtiene memoria reciente del vault.
      2. Construye el system prompt inyectando soul + memoria.
      3. Envia al LLM con los schemas MCP disponibles.
      4. Si el LLM solicita herramientas, las ejecuta y realimenta la respuesta.
      5. Guarda la conversacion periodicamente.

    Atributos:
        name: Nombre del asistente (configurable via onboarding).
        llm: Motor de lenguaje (Groq, OpenAI, Anthropic u Ollama).
        soul: Identidad y personalidad persistente.
        memory: Gestor de memoria a largo plazo.
        auth: Gestor de autenticacion.
        mcp: Enrutador de herramientas MCP.
        skills: Gestor de habilidades del sistema.
    """

    def __init__(
        self,
        name: str,
        llm_engine: BaseLLMEngine,
        soul: Soul,
        memory: MemoryManager,
        auth: AuthManager,
        mcp_router: MCPRouter,
        skill_manager: SkillManager,
        max_context_conversations: int = 5,
    ):
        self.name = name
        self.llm = llm_engine
        self.soul = soul
        self.memory = memory
        self.auth = auth
        self.mcp = mcp_router
        self.skills = skill_manager
        self.max_context = max_context_conversations
        self.conversation_history: list[dict] = []
        self._conversation_count = 0

        logger.info(f"Asistente '{name}' inicializado.")

    # ------------------------------------------------------------------
    # Procesamiento de mensajes
    # ------------------------------------------------------------------

    async def process(self, user_message: str) -> str:
        """
        Procesa un mensaje del usuario y genera una respuesta.

        Este es el flujo principal del asistente:
          1. Construye el contexto con soul + memoria reciente.
          2. Agrega el mensaje al historial.
          3. Envia todo al LLM con los schemas de herramientas MCP.
          4. Si el LLM invoca herramientas, ejecuta el ciclo de tool-calling.
          5. Guarda el historial periodicamente.

        Args:
            user_message: Texto enviado por el usuario.

        Returns:
            Respuesta generada por el LLM (posiblemente enriquecida con resultados de herramientas).
        """
        # Obtener memoria reciente para contexto
        recent_memory = self.memory.get_recent_memory(self.max_context)

        # Construir el system prompt con identidad + memoria
        system_prompt = self.soul.get_system_prompt(recent_memory)

        # Agregar mensaje del usuario al historial
        self.conversation_history.append({
            "role": "user",
            "content": user_message,
        })

        # Preparar la secuencia de mensajes para el LLM
        messages = [
            {"role": "system", "content": system_prompt},
        ] + self.conversation_history

        # Obtener los schemas de herramientas MCP disponibles
        tools = self.mcp.get_schemas()

        # Limitar herramientas para no saturar el modelo (Groq falla con >20)
        MAX_TOOLS = 20
        if len(tools) > MAX_TOOLS:
            # Herramientas prioritarias (uso comun)
            priority = {
                "obtener_fecha_hora", "guardar_nota", "buscar_notas",
                "listar_directorio", "leer_archivo", "escribir_archivo",
                "ejecutar_comando", "buscar_web", "extraer_texto_web",
                "buscar_imagen_web", "descargar_archivo", "firecrawl",
                "info_sistema", "abrir_aplicacion",
                "leer_emails", "enviar_email",
                "clima", "generar_texto", "resumir_texto", "traducir_texto",
                "buscar_archivos", "info_archivo", "listar_procesos",
            }
            # Poner prioritarias primero, luego el resto hasta el limite
            core = [t for t in tools if t.get("function", {}).get("name") in priority]
            extra = [t for t in tools if t.get("function", {}).get("name") not in priority]
            tools = (core + extra)[:MAX_TOOLS]

        # Enviar al LLM
        logger.debug(f"Enviando al LLM: {len(messages)} mensajes, {len(tools)} herramientas.")
        response = self.llm.chat(messages, tools=tools if tools else None)

        # Ciclo de tool-calling: si el LLM solicita herramientas, ejecutarlas
        if "tool_calls" in response and response["tool_calls"]:
            response = await self._handle_tool_calls(response, messages)

        assistant_message = response.get("content", "No pude generar una respuesta.")

        # Guardar respuesta en el historial
        self.conversation_history.append({
            "role": "assistant",
            "content": assistant_message,
        })

        # Guardar conversacion cada N intercambios
        self._conversation_count += 1
        if self._conversation_count % 5 == 0:
            self._save_current_conversation()

        return assistant_message

    async def _handle_tool_calls(self, response: dict, messages: list[dict]) -> dict:
        """
        Ejecuta las herramientas solicitadas por el LLM y obtiene la respuesta final.

        Flujo:
          1. Extrae las llamadas a herramientas del response.
          2. Ejecuta cada herramienta via MCPRouter.
          3. Agrega los resultados como mensajes de tipo 'tool'.
          4. Envia todo de vuelta al LLM para generar la respuesta final.

        Args:
            response: Respuesta del LLM que contiene tool_calls.
            messages: Historial completo de mensajes.

        Returns:
            Respuesta final del LLM despues de procesar los resultados de las herramientas.
        """
        tool_calls = response.get("tool_calls", [])
        tool_results = []

        for tc in tool_calls:
            func_info = tc.get("function", {})
            tool_name = func_info.get("name", "")
            try:
                raw = func_info.get("arguments") or "{}"
                arguments = json.loads(raw) if isinstance(raw, str) else raw
                if not isinstance(arguments, dict):
                    arguments = {}
            except (json.JSONDecodeError, TypeError):
                arguments = {}

            logger.info(f"Ejecutando herramienta: {tool_name}")
            result = self.mcp.execute(tool_name, **arguments)

            tool_results.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": str(result),
            })

        # Agregar el response original del LLM y los resultados de las herramientas
        messages.append(response)
        messages.extend(tool_results)

        # Segunda llamada al LLM con los resultados incorporados
        final_response = self.llm.chat(messages)
        return final_response

    # ------------------------------------------------------------------
    # Procesamiento de media
    # ------------------------------------------------------------------

    async def process_with_media(self, caption: str, media_data: bytes) -> str:
        """
        Procesa un mensaje con un archivo adjunto (imagen, documento).

        El archivo se guarda en el vault y el caption se procesa normalmente.

        Args:
            caption: Texto acompanante del archivo.
            media_data: Contenido binario del archivo.

        Returns:
            Respuesta del asistente.
        """
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_media.bin"
        self.memory.save_media(filename, media_data)

        response = await self.process(f"[Media recibido: {filename}] {caption}")
        return response

    # ------------------------------------------------------------------
    # Estado y persistencia
    # ------------------------------------------------------------------

    async def get_status(self) -> str:
        """
        Retorna un resumen del estado actual del asistente.

        Incluye: cantidad de herramientas, skills, estado de autenticacion
        y mensajes en la sesion actual.
        """
        skills_list = self.skills.list_skills()
        tools_list = self.mcp.get_tool_names()

        status = (
            f"Estado de {self.name}\n\n"
            f"Soul: Cargado\n"
            f"Memoria: {self._conversation_count} mensajes en sesion\n"
            f"Herramientas MCP: {len(tools_list)} ({', '.join(tools_list) if tools_list else 'ninguna'})\n"
            f"Skills: {len(skills_list)} ({', '.join(skills_list) if skills_list else 'ninguna'})\n"
            f"Autenticacion: {'Activa' if self.auth.is_authenticated else 'Inactiva'}\n"
        )
        return status.strip()

    def _save_current_conversation(self):
        """Persiste la conversacion actual en el vault."""
        if self.conversation_history:
            self.memory.save_conversation(self.conversation_history)
            logger.info("Conversacion guardada en el vault.")

    def shutdown(self):
        """Guarda el estado pendiente y cierra el asistente de forma limpia."""
        self._save_current_conversation()
        logger.info(f"Asistente '{self.name}' apagado correctamente.")
