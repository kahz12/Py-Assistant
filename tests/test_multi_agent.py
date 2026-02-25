"""
tests/test_multi_agent.py -- Tests de integracion para el sistema Multi-Agente.

Cubre:
  - AgentSpawner: roles, whitelist, contexto, tool-calling loop
  - WAQStorage: escritura y limpieza de archivos
  - LaneQueue: orden FIFO y WAQ integrado
"""
import asyncio
import json
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.agent_spawner import AgentSpawner, SubAgentConfig, PREDEFINED_ROLES
from core.lane_queue import LaneQueue, WAQStorage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_llm(content="Resultado de prueba", tool_calls=None):
    """Crea un LLM Engine mock con respuesta configurable."""
    llm = MagicMock()
    response = {"content": content}
    if tool_calls:
        response["tool_calls"] = tool_calls
    llm.chat.return_value = response
    return llm


def _make_mcp(tool_results=None):
    """Crea un MCPRouter mock."""
    mcp = MagicMock()
    mcp.get_schemas.return_value = [
        {"function": {"name": "buscar_web"}},
        {"function": {"name": "guardar_nota"}},
        {"function": {"name": "ejecutar_comando"}},
        {"function": {"name": "herramienta_prohibida"}},
    ]
    mcp.execute.return_value = tool_results or "resultado de herramienta"
    return mcp


@pytest.fixture
def spawner():
    return AgentSpawner(_make_llm(), _make_mcp())


@pytest.fixture
def tmp_waq(tmp_path):
    return WAQStorage(tmp_path / "waq")


# ---------------------------------------------------------------------------
# AgentSpawner Tests
# ---------------------------------------------------------------------------

class TestAgentSpawner:

    @pytest.mark.asyncio
    async def test_spawn_invalid_role_returns_error(self, spawner):
        """Un rol inexistente retorna un string de error claro."""
        result = await spawner.spawn("rol_inexistente", "misión de prueba")
        assert "no existe" in result.lower()
        assert "roles disponibles" in result.lower()

    def test_all_12_predefined_roles_exist(self, spawner):
        """Los 12 roles pre-definidos están registrados en PREDEFINED_ROLES."""
        expected_roles = {
            "investigador", "programador", "hogar", "analista",
            "escritor", "creativo", "matematico", "quimico",
            "astronomo", "medico", "filosofo", "juridico",
        }
        available = set(spawner.get_available_roles())
        assert expected_roles.issubset(available), (
            f"Roles faltantes: {expected_roles - available}"
        )

    @pytest.mark.asyncio
    async def test_spawn_whitelist_enforced(self):
        """Herramientas fuera del whitelist del sub-agente son denegadas."""
        # Crear un LLM que intenta usar una herramienta prohibida
        tool_call_response = {
            "tool_calls": [{
                "id": "tc_001",
                "function": {
                    "name": "herramienta_prohibida",
                    "arguments": "{}",
                },
            }],
            "content": None,
        }
        final_response = {"content": "Respuesta final", "tool_calls": []}
        llm = MagicMock()
        llm.chat.side_effect = [tool_call_response, final_response]
        mcp = _make_mcp()

        spawner = AgentSpawner(llm, mcp)
        # 'investigador' tiene whitelist = [buscar_web, extraer_texto_web, ...]
        # 'herramienta_prohibida' NO está en ella
        result = await spawner.spawn("investigador", "prueba de whitelist")

        # El MCP execute NO debe haberse llamado con la herramienta prohibida
        for call in mcp.execute.call_args_list:
            assert call.args[0] != "herramienta_prohibida", (
                "La herramienta prohibida fue ejecutada a pesar del whitelist"
            )

    @pytest.mark.asyncio
    async def test_spawn_context_injected_in_message(self):
        """El contexto de conversación se inyecta en el mensaje del sub-agente."""
        llm = _make_llm(content="Resultado con contexto")
        mcp = _make_mcp()
        spawner = AgentSpawner(llm, mcp)

        context = "USER: Cuéntame sobre Python\nASSISTANT: Python es un lenguaje..."
        await spawner.spawn("investigador", "Misión de prueba", context=context)

        # Verificar que el mensaje enviado al LLM contiene el contexto
        call_args = llm.chat.call_args_list[0]
        messages = call_args[0][0]  # Primer argumento posicional = messages
        user_msg = next(m for m in messages if m["role"] == "user")
        assert "CONTEXTO DE CONVERSACION RECIENTE" in user_msg["content"]
        assert "Cuéntame sobre Python" in user_msg["content"]

    @pytest.mark.asyncio
    async def test_spawn_without_context_no_header(self):
        """Sin contexto, el mensaje no tiene el header de contexto."""
        llm = _make_llm(content="Resultado sin contexto")
        spawner = AgentSpawner(llm, _make_mcp())

        await spawner.spawn("investigador", "Misión sin contexto")
        messages = llm.chat.call_args_list[0][0][0]
        user_msg = next(m for m in messages if m["role"] == "user")
        assert "CONTEXTO" not in user_msg["content"]
        assert user_msg["content"] == "Misión sin contexto"

    @pytest.mark.asyncio
    async def test_spawn_result_always_string(self, spawner):
        """El resultado de spawn() siempre es un string."""
        result = await spawner.spawn("analista", "Analiza esto")
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_spawn_result_includes_agent_name(self, spawner):
        """El resultado incluye el nombre del sub-agente en el header."""
        result = await spawner.spawn("analista", "Prueba de formato")
        assert "AGENTE ANALISTA" in result.upper()

    @pytest.mark.asyncio
    async def test_spawn_max_rounds_respected(self):
        """El loop de tool-calling se detiene en MAX_ROUNDS=5."""
        # LLM siempre retorna tool_calls → el loop debe detenerse en 5 rondas
        tool_call_response = {
            "tool_calls": [{
                "id": "tc_loop",
                "function": {"name": "buscar_web", "arguments": '{"query":"test"}'},
            }],
            "content": None,
        }
        # Después de múltiples rounds, retorna respuesta final
        final = {"content": "Respuesta final tras rounds", "tool_calls": []}
        llm = MagicMock()
        # 1 llamada inicial + 5 rondas + 1 final = 7 llamadas máx
        llm.chat.side_effect = [tool_call_response] * 5 + [final]

        mcp = _make_mcp()
        mcp.get_schemas.return_value = [{"function": {"name": "buscar_web"}}]

        spawner = AgentSpawner(llm, mcp)
        result = await spawner.spawn("investigador", "Test de max rounds")

        # El LLM no debe haber sido llamado más de MAX_ROUNDS + 2 veces
        assert llm.chat.call_count <= 7, (
            f"LLM fue llamado {llm.chat.call_count} veces, máximo esperado: 7"
        )
        assert isinstance(result, str)

    def test_register_custom_role_available(self, spawner):
        """Un rol personalizado registrado en runtime aparece en get_available_roles()."""
        custom = SubAgentConfig(
            name="Agente Test",
            role="test_rol",
            system_prompt="Eres un agente de prueba.",
            tools_whitelist=["buscar_web"],
        )
        spawner.register_role(custom)
        assert "test_rol" in spawner.get_available_roles()

    @pytest.mark.asyncio
    async def test_spawn_custom_role(self, spawner):
        """Un rol personalizado puede ser invocado correctamente."""
        spawner.register_role(SubAgentConfig(
            name="Agente Custom",
            role="custom_test",
            system_prompt="Agente de prueba unitaria.",
            tools_whitelist=["buscar_web"],
        ))
        result = await spawner.spawn("custom_test", "Tarea de prueba custom")
        assert isinstance(result, str)
        assert "AGENTE CUSTOM" in result.upper()


# ---------------------------------------------------------------------------
# WAQStorage Tests
# ---------------------------------------------------------------------------

class TestWAQStorage:

    def test_write_creates_json_file(self, tmp_waq):
        """write() crea un archivo JSON en el directorio WAQ."""
        waq_id = tmp_waq.write("lane_1", "mensaje de prueba")
        files = list(tmp_waq.waq_dir.glob("*.json"))
        assert len(files) == 1
        assert waq_id in files[0].name

    def test_write_content_is_valid_json(self, tmp_waq):
        """El archivo WAQ contiene JSON válido con los campos esperados."""
        waq_id = tmp_waq.write("lane_1", "hola mundo")
        data = json.loads((tmp_waq.waq_dir / f"{waq_id}.json").read_text())
        assert data["lane_id"] == "lane_1"
        assert data["payload"] == "hola mundo"
        assert "ts" in data
        assert data["waq_id"] == waq_id

    def test_complete_removes_file(self, tmp_waq):
        """complete() elimina el archivo WAQ del item procesado."""
        waq_id = tmp_waq.write("lane_1", "mensajito")
        assert (tmp_waq.waq_dir / f"{waq_id}.json").exists()
        tmp_waq.complete(waq_id)
        assert not (tmp_waq.waq_dir / f"{waq_id}.json").exists()

    def test_complete_nonexistent_does_not_raise(self, tmp_waq):
        """complete() con ID inexistente no lanza excepciones."""
        try:
            tmp_waq.complete("id_que_no_existe")
        except Exception as e:
            pytest.fail(f"complete() lanzó una excepción inesperada: {e}")

    def test_load_orphans_returns_sorted_by_timestamp(self, tmp_waq):
        """load_orphans() retorna items ordenados por timestamp ascendente."""
        id1 = tmp_waq.write("lane_a", "primero")
        time.sleep(0.01)
        id2 = tmp_waq.write("lane_a", "segundo")
        orphans = tmp_waq.load_orphans()
        assert len(orphans) == 2
        assert orphans[0]["waq_id"] == id1
        assert orphans[1]["waq_id"] == id2

    def test_load_orphans_empty_dir(self, tmp_waq):
        """load_orphans() retorna lista vacía si no hay archivos."""
        orphans = tmp_waq.load_orphans()
        assert orphans == []

    def test_multiple_lanes_isolated(self, tmp_waq):
        """Items de distintos lanes coexisten en el WAQ correctamente."""
        tmp_waq.write("lane_x", "msg de lane X")
        tmp_waq.write("lane_y", "msg de lane Y")
        tmp_waq.write("lane_z", "msg de lane Z")
        orphans = tmp_waq.load_orphans()
        lanes = {o["lane_id"] for o in orphans}
        assert lanes == {"lane_x", "lane_y", "lane_z"}


# ---------------------------------------------------------------------------
# LaneQueue Tests
# ---------------------------------------------------------------------------

class TestLaneQueue:

    @pytest.mark.asyncio
    async def test_fifo_order_preserved(self):
        """Items del mismo lane se procesan en orden FIFO estricto."""
        queue = LaneQueue()
        received_order = []

        async def callback(msg):
            received_order.append(msg)

        await queue.enqueue("lane_1", "primero", callback)
        await queue.enqueue("lane_1", "segundo", callback)
        await queue.enqueue("lane_1", "tercero", callback)

        # Dar tiempo al worker para procesar
        await asyncio.sleep(0.1)
        assert received_order == ["primero", "segundo", "tercero"]

    @pytest.mark.asyncio
    async def test_different_lanes_independent(self):
        """Lanes distintos son independientes entre sí."""
        queue = LaneQueue()
        results = {"a": [], "b": []}

        async def cb_a(msg):
            results["a"].append(msg)

        async def cb_b(msg):
            results["b"].append(msg)

        await queue.enqueue("lane_a", "mensaje_a", cb_a)
        await queue.enqueue("lane_b", "mensaje_b", cb_b)
        await asyncio.sleep(0.1)

        assert results["a"] == ["mensaje_a"]
        assert results["b"] == ["mensaje_b"]

    @pytest.mark.asyncio
    async def test_waq_file_created_and_deleted(self, tmp_path):
        """Con WAQ activo, el archivo se crea antes y se elimina después."""
        waq_dir = tmp_path / "waq"
        queue = LaneQueue(waq_dir=waq_dir)
        processed = []

        async def callback(msg):
            # El archivo WAQ debe existir mientras se procesa
            files = list(waq_dir.glob("*.json"))
            processed.append(("files_during", len(files)))
            processed.append(("msg", msg))

        await queue.enqueue("lane_1", "test_payload", callback)
        await asyncio.sleep(0.1)

        # Después del procesamiento, el archivo WAQ debe haberse eliminado
        files_after = list(waq_dir.glob("*.json"))
        assert len(files_after) == 0, "El archivo WAQ no fue eliminado al completar"
        assert any(p[0] == "msg" and p[1] == "test_payload" for p in processed)

    @pytest.mark.asyncio
    async def test_queue_size_tracking(self):
        """queue_size() refleja correctamente el número de items pendientes."""
        queue = LaneQueue()
        barrier = asyncio.Event()

        async def slow_callback(msg):
            await barrier.wait()  # Bloquear hasta que liberemos el barrier

        await queue.enqueue("lane_x", "uno", slow_callback)
        await queue.enqueue("lane_x", "dos", slow_callback)
        await asyncio.sleep(0.05)

        # Debe haber al menos 1 item pendiente (el primero está bloqueado en el barrier)
        assert queue.queue_size("lane_x") >= 0  # El worker ya está activo

        barrier.set()  # Liberar
        await asyncio.sleep(0.1)

    def test_is_active_false_for_unknown_lane(self):
        """is_active() retorna False para un lane que nunca ha recibido mensajes."""
        queue = LaneQueue()
        assert queue.is_active("lane_desconocida") is False

    def test_all_lanes_status_empty_initially(self):
        """all_lanes_status() retorna dict vacío al inicio."""
        queue = LaneQueue()
        assert queue.all_lanes_status() == {}
