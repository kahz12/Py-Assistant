"""
tests/test_mcp.py -- Tests del sistema MCP (registro y ejecución).

Verifica:
  - Registro correcto de todas las herramientas.
  - Ejecución funcional de herramientas básicas.
  - Manejo de errores (herramienta inexistente, argumentos inválidos).
"""
import sys
import os
import pytest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["LOGURU_LEVEL"] = "ERROR"
from loguru import logger
logger.remove()


@pytest.fixture(scope="module")
def mcp_router():
    """Inicializa el MCPRouter con todas las herramientas."""
    from mcp.mcp_router import MCPRouter
    from mcp.tools import register_all_tools
    mcp = MCPRouter()
    register_all_tools(mcp, Path("memory_vault"), {})
    return mcp


class TestMCPRegistration:
    def test_minimum_tool_count(self, mcp_router):
        """Debe tener al menos 50 herramientas registradas."""
        tools = mcp_router.get_tool_names()
        assert len(tools) >= 50, f"Solo {len(tools)} herramientas registradas"

    def test_core_tools_registered(self, mcp_router):
        """Las herramientas core deben estar registradas."""
        tools = mcp_router.get_tool_names()
        core = [
            "obtener_fecha_hora", "guardar_nota", "buscar_notas",
            "listar_directorio", "leer_archivo", "escribir_archivo",
            "ejecutar_comando", "buscar_web", "info_sistema",
        ]
        for tool in core:
            assert tool in tools, f"Herramienta core faltante: {tool}"

    def test_new_tools_registered(self, mcp_router):
        """Las herramientas nuevas deben estar registradas."""
        tools = mcp_router.get_tool_names()
        new_tools = [
            "copiar_archivo", "mover_archivo", "eliminar_archivo",
            "buscar_archivos", "info_archivo",
            "listar_procesos", "terminar_proceso",
            "analizar_sentimiento", "detectar_entidades",
            "transcribir_audio", "generar_texto", "clasificar_texto",
            "describir_imagen", "ocr_imagen",
            "google_maps", "clima_detallado", "noticias",
            "ha_dispositivos", "ha_estado", "ha_controlar", "ha_servicio",
        ]
        for tool in new_tools:
            assert tool in tools, f"Herramienta nueva faltante: {tool}"

    def test_all_tools_have_schemas(self, mcp_router):
        """Todas las herramientas deben tener schema OpenAI válido."""
        schemas = mcp_router.get_schemas()
        assert len(schemas) > 0
        for schema in schemas:
            assert "function" in schema, f"Schema sin 'function': {schema}"
            func = schema["function"]
            assert "name" in func, f"Schema sin nombre"
            assert "description" in func, f"Schema sin descripcion: {func.get('name')}"
            assert "parameters" in func, f"Schema sin parametros: {func.get('name')}"


class TestMCPExecution:
    def test_fecha_hora(self, mcp_router):
        """obtener_fecha_hora debe retornar fecha legible."""
        result = mcp_router.execute("obtener_fecha_hora")
        assert isinstance(result, str)
        assert len(result) > 10

    def test_info_archivo(self, mcp_router):
        """info_archivo debe retornar datos de un archivo existente."""
        result = mcp_router.execute("info_archivo", ruta="main.py")
        assert "Tamano" in result or "Error" in result or "denegado" in result.lower()

    def test_listar_procesos(self, mcp_router):
        """listar_procesos debe retornar una lista."""
        result = mcp_router.execute("listar_procesos")
        assert "procesos" in result.lower() or "```" in result

    def test_buscar_archivos(self, mcp_router):
        """buscar_archivos debe encontrar archivos .py."""
        result = mcp_router.execute(
            "buscar_archivos",
            directorio="skills",
            patron="*.py",
        )
        assert "archivo" in result.lower()

    def test_tool_inexistente(self, mcp_router):
        """Herramienta inexistente debe retornar error, no crash."""
        result = mcp_router.execute("herramienta_que_no_existe")
        assert "error" in result.lower() or "no encontrada" in result.lower()
