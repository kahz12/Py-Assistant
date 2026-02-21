"""
tests/test_skills.py -- Tests de importación y validación de skills.

Verifica:
  - Todos los skills se importan correctamente.
  - Cada skill tiene SKILL_NAME y execute().
  - El SkillManager detecta todos los skills.
"""
import sys
import os
import pytest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["LOGURU_LEVEL"] = "ERROR"
from loguru import logger
logger.remove()

SKILL_MODULES = [
    "web_browser", "desktop_manager", "clipboard_manager",
    "pdf_reader", "git_manager", "database_manager",
    "text_analyzer", "api_client", "media_tools",
    "device_access", "system_config", "voice_recognition",
    "text_generator", "ml_engine", "deep_learning",
    "api_services", "home_assistant", "tts", "google_calendar",
]


class TestSkillImports:
    @pytest.mark.parametrize("module_name", SKILL_MODULES)
    def test_skill_imports(self, module_name):
        """Cada skill debe importarse sin errores."""
        import importlib
        mod = importlib.import_module(f"skills.{module_name}")
        assert mod is not None

    @pytest.mark.parametrize("module_name", SKILL_MODULES)
    def test_skill_has_name(self, module_name):
        """Cada skill debe tener SKILL_NAME definido."""
        import importlib
        mod = importlib.import_module(f"skills.{module_name}")
        assert hasattr(mod, "SKILL_NAME"), f"{module_name} sin SKILL_NAME"
        assert isinstance(mod.SKILL_NAME, str)
        assert len(mod.SKILL_NAME) > 0

    @pytest.mark.parametrize("module_name", SKILL_MODULES)
    def test_skill_has_execute(self, module_name):
        """Cada skill debe tener funcion execute()."""
        import importlib
        mod = importlib.import_module(f"skills.{module_name}")
        assert hasattr(mod, "execute"), f"{module_name} sin execute()"
        assert callable(mod.execute)


class TestSkillManager:
    def test_skill_manager_loads_all(self):
        """SkillManager debe detectar al menos 19 skills (incluyendo tts y cal)."""
        from skills.skill_manager import SkillManager
        sm = SkillManager(Path("skills"))
        skills = sm.list_skills()
        assert len(skills) >= 19, f"Solo {len(skills)} skills detectados"

    def test_skill_manager_returns_names(self):
        """SkillManager.list_skills() debe retornar nombres de skills."""
        from skills.skill_manager import SkillManager
        sm = SkillManager(Path("skills"))
        skills = sm.list_skills()
        assert "home_assistant" in skills or any("home" in s for s in skills)
        assert "tts" in skills
        assert "google_calendar" in skills

    def test_plugin_loading(self):
        """SkillManager debe cargar plugins externos."""
        from skills.skill_manager import SkillManager
        sm = SkillManager(Path("skills"))
        assert "example_plugin" in sm.list_skills()
        result = sm.run("example_plugin", action="ping")
        assert "pong" in result.lower()



class TestSkillValidations:
    def test_voice_recognition_validates_path(self):
        """voice_recognition debe rechazar rutas fuera de /home y /tmp."""
        from skills.voice_recognition import _validate_audio
        err = _validate_audio("/etc/shadow")
        assert "denegado" in err.lower()

    def test_deep_learning_validates_path(self):
        """deep_learning debe rechazar rutas fuera de /home y /tmp."""
        from skills.deep_learning import _validate_file
        err = _validate_file("/etc/passwd")
        assert "denegado" in err.lower()

    def test_text_generator_requires_prompt(self):
        """text_generator debe rechazar prompt vacío."""
        from skills.text_generator import execute
        result = execute(action="free", prompt=None)
        assert "error" in result.lower()

    def test_ml_engine_requires_llm(self):
        """ml_engine debe reportar error sin LLM."""
        from skills.ml_engine import execute
        result = execute(action="classify", text="test", categories=["a", "b"])
        assert "error" in result.lower()

    def test_api_services_requires_key(self):
        """api_services debe pedir API key si no está configurada."""
        from skills.api_services import execute
        result = execute(action="weather_detail", params={"city": "Bogota"})
        assert "requiere" in result.lower() or "error" in result.lower()

    def test_home_assistant_requires_config(self):
        """home_assistant debe pedir configuración si no está."""
        from skills.home_assistant import execute
        result = execute(action="states")
        assert "configurado" in result.lower() or "agrega" in result.lower()
