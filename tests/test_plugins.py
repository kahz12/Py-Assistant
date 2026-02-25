"""
tests/test_plugins.py -- Tests para el sistema de plugins (PluginManager).

Cubre:
  - Auto-descubrimiento de plugins
  - Generacion y lectura de manifests JSON
  - Hot-reload de plugins en runtime
  - Sandboxed execute() con timeout
  - install_from_github() con URL invalida y script malformado
  - Plugin de notas sin API key (completamente local)
  - Aislamiento de plugins defectuosos
"""
import importlib
import json
import sys
import time
from pathlib import Path

import pytest

from core.plugin_manager import PluginManager, PluginManifest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def plugin_dir(tmp_path):
    """Crea un directorio temporal de plugins con un plugin valido de prueba."""
    p = tmp_path / "plugins"
    p.mkdir()
    # Plugin valido minimo
    (p / "hello_plugin.py").write_text(
        """
SKILL_NAME = "hello"
SKILL_DESCRIPTION = "Plugin de prueba"
VERSION = "1.2.3"
AUTHOR = "test"
ACTIONS = ["greet", "farewell"]
REQUIRES_ENV = []

def execute(action="greet", name="mundo", **kwargs):
    if action == "greet":
        return f"Hola, {name}!"
    elif action == "farewell":
        return f"Adios, {name}!"
    return f"Accion desconocida: {action}"
""",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def pm(plugin_dir):
    """PluginManager con el directorio temporal."""
    return PluginManager(plugins_dir=plugin_dir)


# ---------------------------------------------------------------------------
# Auto-descubrimiento
# ---------------------------------------------------------------------------

class TestAutoDiscovery:

    def test_loads_valid_plugin(self, pm):
        """PluginManager carga automaticamente plugins validos."""
        assert pm.is_loaded("hello")

    def test_ignores_underscore_files(self, plugin_dir):
        """Archivos que comienzan con _ son ignorados."""
        (plugin_dir / "_private.py").write_text(
            "SKILL_NAME = 'private'\ndef execute(**kw): return 'x'",
            encoding="utf-8",
        )
        pm = PluginManager(plugins_dir=plugin_dir)
        assert not pm.is_loaded("private")

    def test_ignores_missing_skill_name(self, plugin_dir):
        """Plugin sin SKILL_NAME es ignorado."""
        (plugin_dir / "bad_no_name.py").write_text(
            "def execute(**kw): return 'x'",
            encoding="utf-8",
        )
        pm = PluginManager(plugins_dir=plugin_dir)
        assert "bad_no_name" not in pm.plugin_names()

    def test_ignores_missing_execute(self, plugin_dir):
        """Plugin sin execute() es ignorado."""
        (plugin_dir / "bad_no_exec.py").write_text(
            "SKILL_NAME = 'bad'\n",
            encoding="utf-8",
        )
        pm = PluginManager(plugins_dir=plugin_dir)
        assert not pm.is_loaded("bad")

    def test_broken_plugin_doesnt_crash_others(self, plugin_dir):
        """Un plugin con error de sintaxis no impide cargar los demas."""
        (plugin_dir / "crashing.py").write_text(
            "SKILL_NAME = 'crash'\nRAISE_BUG = 1 / 0\ndef execute(**kw): ...",
            encoding="utf-8",
        )
        pm = PluginManager(plugins_dir=plugin_dir)
        # El hello plugin debe seguir disponible
        assert pm.is_loaded("hello")
        assert not pm.is_loaded("crash")


# ---------------------------------------------------------------------------
# Manifests
# ---------------------------------------------------------------------------

class TestManifests:

    def test_manifest_created_on_load(self, pm, plugin_dir):
        """El manifest JSON se genera al cargar el plugin."""
        manifest_file = plugin_dir / "manifests" / "hello.json"
        assert manifest_file.exists()

    def test_manifest_contains_correct_values(self, pm, plugin_dir):
        """El manifest refleja correctamente los metadatos del modulo."""
        manifest_file = plugin_dir / "manifests" / "hello.json"
        data = json.loads(manifest_file.read_text())
        assert data["name"] == "hello"
        assert data["version"] == "1.2.3"
        assert data["author"] == "test"
        assert "greet" in data["actions"]
        assert "farewell" in data["actions"]

    def test_get_manifest_returns_dataclass(self, pm):
        """get_manifest() retorna una instancia de PluginManifest."""
        m = pm.get_manifest("hello")
        assert isinstance(m, PluginManifest)
        assert m.name == "hello"
        assert m.version == "1.2.3"

    def test_manifest_from_dict_roundtrip(self):
        """PluginManifest.to_dict() y from_dict() son inversos."""
        original = PluginManifest(
            name="test",
            version="2.0.0",
            actions=["a", "b"],
            requires_env=["MY_KEY"],
        )
        roundtripped = PluginManifest.from_dict(original.to_dict())
        assert roundtripped.name == original.name
        assert roundtripped.version == original.version
        assert roundtripped.actions == original.actions

    def test_list_plugins_returns_dicts(self, pm):
        """list_plugins() retorna lista de dicts con campo 'status'."""
        plugins = pm.list_plugins()
        assert isinstance(plugins, list)
        assert len(plugins) >= 1
        assert "name" in plugins[0]
        assert "status" in plugins[0]


# ---------------------------------------------------------------------------
# Ejecucion (run con sandboxing)
# ---------------------------------------------------------------------------

class TestRun:

    def test_run_valid_action(self, pm):
        """run() ejecuta la accion correctamente."""
        result = pm.run("hello", action="greet", name="Ale")
        assert result == "Hola, Ale!"

    def test_run_default_action(self, pm):
        """run() usa la accion default si no se especifica."""
        result = pm.run("hello")
        assert "Hola" in result

    def test_run_unknown_plugin(self, pm):
        """run() retorna mensaje claro para plugin desconocido."""
        result = pm.run("no_existe")
        assert "no disponible" in result.lower()

    def test_run_timeout(self, plugin_dir):
        """run() retorna mensaje de timeout si el plugin tarda demasiado."""
        (plugin_dir / "slow_plugin.py").write_text(
            "import time\nSKILL_NAME = 'slow'\n"
            "def execute(**kw):\n    time.sleep(60)\n    return 'done'",
            encoding="utf-8",
        )
        pm = PluginManager(plugins_dir=plugin_dir, execute_timeout=1)
        result = pm.run("slow")
        assert "timeout" in result.lower() or "tardo" in result.lower()

    def test_run_exception_in_plugin(self, plugin_dir):
        """run() captura excepciones del plugin y retorna mensaje de error."""
        (plugin_dir / "erroring_plugin.py").write_text(
            "SKILL_NAME = 'erroring'\n"
            "def execute(**kw):\n    raise ValueError('Error de prueba')",
            encoding="utf-8",
        )
        pm = PluginManager(plugins_dir=plugin_dir)
        result = pm.run("erroring")
        assert "Error" in result


# ---------------------------------------------------------------------------
# Hot-reload
# ---------------------------------------------------------------------------

class TestHotReload:

    def test_reload_updates_behavior(self, pm, plugin_dir):
        """reload() recarga el modulo con la version actualizada del archivo."""
        # Verificar estado inicial
        assert pm.run("hello", action="greet") == "Hola, mundo!"

        # Actualizar el archivo del plugin
        (plugin_dir / "hello_plugin.py").write_text(
            """
SKILL_NAME = "hello"
VERSION = "2.0.0"
ACTIONS = ["greet"]
REQUIRES_ENV = []

def execute(action="greet", name="mundo", **kwargs):
    return f"Buenos dias, {name}!"
""",
            encoding="utf-8",
        )
        result = pm.reload("hello")
        assert "recargado" in result.lower()
        assert pm.run("hello", action="greet") == "Buenos dias, mundo!"

    def test_reload_unknown_plugin_returns_error(self, pm):
        """reload() retorna mensaje de error para plugin desconocido."""
        result = pm.reload("plugin_inexistente")
        assert "no encontrado" in result.lower()

    def test_reload_all_returns_string(self, pm):
        """reload_all() retorna un string con el resultado de recargar todos."""
        result = pm.reload_all()
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# install_from_github
# ---------------------------------------------------------------------------

class TestInstallFromGithub:

    def test_rejects_non_py_url(self, pm):
        """install_from_github() rechaza URLs que no son .py."""
        result = pm.install_from_github("https://github.com/user/repo/blob/main/README.md")
        assert "py" in result.lower() or "valido" in result.lower()

    def test_rejects_invalid_content(self, pm, monkeypatch):
        """install_from_github() rechaza archivos sin SKILL_NAME o execute."""
        import urllib.request

        class FakeResponse:
            def __init__(self):
                self.data = b"# Este archivo no es un plugin valido"
            def read(self):
                return self.data
            def __enter__(self): return self
            def __exit__(self, *a): pass

        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: FakeResponse())
        result = pm.install_from_github("https://github.com/u/r/blob/main/fake_plugin.py")
        assert "valido" in result.lower() or "falta" in result.lower()

    def test_installs_valid_remote_plugin(self, pm, monkeypatch):
        """install_from_github() instala el plugin si el contenido es valido."""
        import urllib.request

        plugin_code = (
            'SKILL_NAME = "remote_test"\n'
            'def execute(**kw):\n    return "instalado desde GitHub"\n'
        )

        class FakeResp:
            def read(self): return plugin_code.encode()
            def __enter__(self): return self
            def __exit__(self, *a): pass

        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: FakeResp())
        result = pm.install_from_github(
            "https://github.com/u/r/blob/main/remote_test.py"
        )
        assert "instalado" in result.lower() or "cargado" in result.lower()
        assert pm.is_loaded("remote_test")


# ---------------------------------------------------------------------------
# Plugin de notas (completamente local, sin API key)
# ---------------------------------------------------------------------------

class TestNotesPlugin:

    def _load_plugin(self):
        """Carga el plugin de notas directamente."""
        spec = importlib.util.spec_from_file_location(
            "plugins.notes",
            Path("plugins/note_summary_plugin.py"),
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_notes_plugin_meta(self):
        """El plugin de notas tiene los metadatos correctos."""
        m = self._load_plugin()
        assert m.SKILL_NAME == "notes"
        assert callable(m.execute)
        assert "list" in m.ACTIONS
        assert "search" in m.ACTIONS

    def test_notes_unknown_action(self):
        """Plugin de notas retorna mensaje claro para accion desconocida."""
        m = self._load_plugin()
        result = m.execute(action="accion_invalida")
        assert "no soportada" in result or "disponibles" in result

    def test_notes_search_no_query(self):
        """Plugin de notas solicita query si no se proporciona."""
        m = self._load_plugin()
        result = m.execute(action="search")
        assert "busqueda" in result.lower() or "query" in result.lower() or "termino" in result.lower()

    def test_notes_summary_handles_missing_dir(self, monkeypatch, tmp_path):
        """Plugin de notas maneja gracefully un vault sin notas."""
        m = self._load_plugin()
        # Monkeypatch _get_notes_dir para apuntar a un dir vacio
        monkeypatch.setattr(
            sys.modules.get("plugins.notes", m),
            "_get_notes_dir",
            lambda: tmp_path / "notas_vacias",
        )
        result = m.execute(action="summary")
        # No debe lanzar excepcion
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Plugin de sistema (sysinfo)
# ---------------------------------------------------------------------------

class TestSysinfoPlugin:

    def _load(self):
        spec = importlib.util.spec_from_file_location(
            "plugins.sysinfo", Path("plugins/sysinfo_plugin.py")
        )
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_sysinfo_metadata(self):
        """sysinfo_plugin tiene los campos de metadatos requeridos."""
        m = self._load()
        assert m.SKILL_NAME == "sysinfo"
        assert callable(m.execute)
        assert "full" in m.ACTIONS
        assert "cpu" in m.ACTIONS
        assert "temp" in m.ACTIONS

    def test_sysinfo_full_returns_string(self):
        """execute(action='full') retorna un string no vacio."""
        m = self._load()
        result = m.execute(action="full")
        assert isinstance(result, str) and len(result) > 10

    def test_sysinfo_cpu_returns_string(self):
        """execute(action='cpu') retorna informacion de CPU."""
        m = self._load()
        result = m.execute(action="cpu")
        assert isinstance(result, str)
        # Debe mencionar CPU o falta psutil
        assert "cpu" in result.lower() or "psutil" in result.lower()

    def test_sysinfo_uptime_returns_string(self):
        """execute(action='uptime') retorna el uptime del sistema."""
        m = self._load()
        result = m.execute(action="uptime")
        assert isinstance(result, str)
        assert len(result) > 5

    def test_sysinfo_disk_mentions_mountpoint(self):
        """execute(action='disk') menciona al menos una particion."""
        m = self._load()
        result = m.execute(action="disk")
        assert isinstance(result, str)
        # En Linux, root siempre existe; si falta psutil dice eso
        assert "/" in result or "psutil" in result.lower() or "Disco" in result

    def test_sysinfo_unknown_action(self):
        """execute() retorna mensaje claro para accion desconocida."""
        m = self._load()
        result = m.execute(action="accion_que_no_existe")
        assert "soportada" in result.lower() or "disponibles" in result.lower()


# ---------------------------------------------------------------------------
# Plugin de recordatorios (reminder) — sin APScheduler real
# ---------------------------------------------------------------------------

class TestReminderPlugin:

    def _load(self, tmp_path=None):
        spec = importlib.util.spec_from_file_location(
            "plugins.reminder_test", Path("plugins/reminder_plugin.py")
        )
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        if tmp_path:
            m._STORAGE_PATH = tmp_path / "reminders.json"
        return m

    def test_reminder_metadata(self, tmp_path):
        """reminder_plugin tiene los metadatos correctos."""
        m = self._load()
        assert m.SKILL_NAME == "reminder"
        assert callable(m.execute)
        assert "add" in m.ACTIONS

    def test_parse_when_in_minutes(self, tmp_path):
        """_parse_when interpreta 'en N minutos' correctamente."""
        m = self._load(tmp_path)
        dt = m._parse_when("en 30 minutos")
        from datetime import datetime, timedelta
        assert dt is not None
        delta = dt - datetime.now()
        assert 25 * 60 < delta.total_seconds() < 35 * 60

    def test_parse_when_in_hours(self, tmp_path):
        """_parse_when interpreta 'en N horas' correctamente."""
        m = self._load(tmp_path)
        dt = m._parse_when("en 2 horas")
        from datetime import datetime
        assert dt is not None
        delta = dt - datetime.now()
        assert 1.9 * 3600 < delta.total_seconds() < 2.1 * 3600

    def test_parse_when_iso_format(self, tmp_path):
        """_parse_when interpreta formato ISO parcial."""
        m = self._load(tmp_path)
        dt = m._parse_when("2099-12-31 23:59")
        from datetime import datetime
        assert dt is not None
        assert dt.year == 2099

    def test_parse_when_invalid_returns_none(self, tmp_path):
        """_parse_when retorna None para fechas no reconocidas."""
        m = self._load(tmp_path)
        assert m._parse_when("proxima semana no se cuando") is None

    def test_add_reminder_requires_message(self, tmp_path):
        """add sin message retorna mensaje de error claro."""
        m = self._load(tmp_path)
        result = m.execute(action="add", when="en 10 minutos")
        assert "mensaje" in result.lower() or "message" in result.lower()

    def test_add_reminder_requires_when(self, tmp_path):
        """add sin when retorna mensaje de error claro."""
        m = self._load(tmp_path)
        result = m.execute(action="add", message="Pagar facturas")
        assert "cuando" in result.lower() or "when" in result.lower()

    def test_add_rejects_past_date(self, tmp_path):
        """add rechaza fechas que ya pasaron."""
        m = self._load(tmp_path)
        result = m.execute(action="add", message="Pasado", when="2000-01-01 00:00")
        assert "paso" in result.lower() or "pasado" in result.lower() or "futuro" in result.lower()

    def test_add_and_list_cycle(self, tmp_path):
        """Agregar un recordatorio y luego listarlo funciona correctamente."""
        m = self._load(tmp_path)
        add_result = m.execute(action="add", message="Reunion con cliente", when="en 1 hora")
        assert "creado" in add_result.lower() or "#1" in add_result

        list_result = m.execute(action="list")
        assert "Reunion con cliente" in list_result

    def test_cancel_reminder(self, tmp_path):
        """Cancelar un recordatorio lo elimina de la lista."""
        m = self._load(tmp_path)
        m.execute(action="add", message="Borrar esto", when="en 2 horas")
        cancel_result = m.execute(action="cancel", reminder_id="1")
        assert "cancelado" in cancel_result.lower()

        list_result = m.execute(action="list")
        assert "Borrar esto" not in list_result

    def test_clear_all(self, tmp_path):
        """clear elimina todos los recordatorios pendientes."""
        m = self._load(tmp_path)
        m.execute(action="add", message="Uno", when="en 1 hora")
        m.execute(action="add", message="Dos", when="en 2 horas")
        result = m.execute(action="clear")
        assert "cancelados" in result.lower() or "2" in result

        list_result = m.execute(action="list")
        assert "pendientes" not in list_result or "No hay" in list_result

    def test_list_empty_returns_clear_message(self, tmp_path):
        """list sin recordatorios retorna mensaje claro."""
        m = self._load(tmp_path)
        result = m.execute(action="list")
        assert "no hay" in result.lower() or "pendientes" in result.lower()


# ---------------------------------------------------------------------------
# Plugin de noticias (news) — sin llamadas reales de red
# ---------------------------------------------------------------------------

class TestNewsPlugin:

    def _load(self):
        spec = importlib.util.spec_from_file_location(
            "plugins.news_test", Path("plugins/news_plugin.py")
        )
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_news_metadata(self):
        """news_plugin tiene los metadatos correctos."""
        m = self._load()
        assert m.SKILL_NAME == "news"
        assert callable(m.execute)
        assert "headlines" in m.ACTIONS
        assert "search" in m.ACTIONS

    def test_news_help_action(self):
        """execute(action='help') retorna instrucciones sin llamar la API."""
        m = self._load()
        result = m.execute(action="help")
        assert "headlines" in result.lower()
        assert "search" in result.lower()

    def test_news_missing_api_key_graceful(self, monkeypatch):
        """Sin NEWS_API_KEY retorna mensaje claro en lugar de crashear."""
        monkeypatch.delenv("NEWS_API_KEY", raising=False)
        m = self._load()
        result = m.execute(action="headlines")
        assert "api_key" in result.lower() or "news_api_key" in result.lower() or "falta" in result.lower()

    def test_news_search_requires_query(self, monkeypatch):
        """execute(action='search') sin query retorna mensaje de error."""
        monkeypatch.setenv("NEWS_API_KEY", "fake_key")
        m = self._load()
        result = m.execute(action="search", query="")
        assert "tema" in result.lower() or "query" in result.lower() or "especifica" in result.lower()

    def test_news_format_articles_empty(self):
        """_format_articles con lista vacia retorna mensaje claro."""
        m = self._load()
        result = m._format_articles([], "Test")
        assert "encontraron" in result.lower() or "no se" in result.lower()

    def test_news_format_articles_limit(self):
        """_format_articles respeta el parametro limit."""
        m = self._load()
        articles = [
            {"title": f"Noticia {i}", "source": {"name": "Test"}, "description": "desc", "url": "http://x.com"}
            for i in range(8)
        ]
        result = m._format_articles(articles, "Test", limit=3)
        # Solo debe aparecer 3 noticias (Noticia 0, 1, 2) no la 4+
        assert "Noticia 3" not in result

    def test_news_unknown_action(self, monkeypatch):
        """execute() retorna mensaje claro para accion desconocida."""
        monkeypatch.setenv("NEWS_API_KEY", "fake_key")
        m = self._load()
        result = m.execute(action="accion_invalida")
        assert "soportada" in result.lower() or "disponibles" in result.lower()

