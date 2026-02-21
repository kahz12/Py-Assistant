"""
mcp/mcp_router.py -- Enrutador de herramientas MCP (Model Context Protocol).

Registra funciones Python como herramientas invocables por el LLM
via function calling. Genera los schemas en formato OpenAI y
despacha las ejecuciones por nombre.

Uso tipico:
    router = MCPRouter()

    @router.register(name="mi_tool", description="...", parameters={...})
    def mi_tool(arg1: str):
        return "resultado"
"""
from typing import Callable
from loguru import logger


class MCPRouter:
    """
    Registro central de herramientas MCP.

    Cada herramienta se compone de:
      - Una funcion Python ejecutable.
      - Un schema JSON compatible con el formato de tool-calling de OpenAI/Groq.

    Metodos principales:
      - register()     : Decorador para registrar herramientas.
      - get_schemas()  : Retorna los schemas para enviar al LLM.
      - execute()      : Ejecuta una herramienta por nombre.

    Atributos:
        _tools: Diccionario interno {nombre: {function, schema}}.
    """

    def __init__(self):
        self._tools: dict[str, dict] = {}

    def register(self, name: str, description: str, parameters: dict):
        """
        Decorador para registrar una funcion como herramienta MCP.

        Args:
            name: Nombre unico de la herramienta.
            description: Descripcion que el LLM usara para decidir cuando invocarla.
            parameters: Schema JSON de los parametros (formato OpenAI).

        Returns:
            Decorador que registra la funcion y la retorna sin modificar.
        """
        def decorator(func: Callable):
            self._tools[name] = {
                "function": func,
                "schema": {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": description,
                        "parameters": parameters,
                    }
                }
            }
            logger.info(f"[MCP] Herramienta registrada: {name}")
            return func
        return decorator

    def get_schemas(self) -> list[dict]:
        """
        Retorna todos los schemas de herramientas en formato OpenAI.

        Returns:
            Lista de schemas listos para enviar al LLM como parametro 'tools'.
        """
        return [t["schema"] for t in self._tools.values()]

    def get_tool_names(self) -> list[str]:
        """Retorna la lista de nombres de herramientas registradas."""
        return list(self._tools.keys())

    def execute(self, tool_name: str, **kwargs) -> str:
        """
        Ejecuta una herramienta registrada por su nombre.

        Si la herramienta no existe o falla, retorna un mensaje de error
        en lugar de propagar la excepcion, para que el LLM pueda manejar
        el fallo de forma natural.

        Args:
            tool_name: Nombre de la herramienta a ejecutar.
            **kwargs: Argumentos a pasar a la funcion.

        Returns:
            Resultado de la ejecucion como string.
        """
        if tool_name not in self._tools:
            error_msg = f"Error: herramienta '{tool_name}' no encontrada."
            logger.error(error_msg)
            return error_msg
        try:
            result = self._tools[tool_name]["function"](**kwargs)
            logger.info(f"[MCP] Ejecutado: {tool_name}")
            return result
        except Exception as e:
            error_msg = f"Error ejecutando '{tool_name}': {str(e)}"
            logger.error(error_msg)
            return error_msg
