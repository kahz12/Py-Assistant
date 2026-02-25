"""
skills/skill_manager.py -- Cargador dinamico de habilidades y plugins.

Busca modulos Python en el directorio skills/ que expongan:
  - SKILL_NAME : str         -- Identificador unico del skill.
  - execute(**kwargs) : str  -- Funcion principal de ejecucion.

Los skills incorporados se cargan desde skills/.
Los plugins externos se delegan a PluginManager (core/plugin_manager.py).
"""
import importlib
from pathlib import Path
from loguru import logger


class SkillManager:
    """
    Carga y ejecuta skills de forma dinamica.

    Gestiona:
      - Skills incorporados: modulos en skills/ con SKILL_NAME + execute()
      - Plugins externos: delegados a PluginManager (plugins/ dir)

    Atributos:
        skills_dir: Ruta al directorio de skills.
        loaded_skills: {nombre: modulo} de skills incorporados.
        plugin_manager: Instancia de PluginManager para plugins externos.
    """

    def __init__(self, skills_dir: Path, mcp_router=None):
        self.skills_dir = skills_dir
        self.loaded_skills: dict[str, object] = {}
        self._auto_load()

        # Delegar plugins al PluginManager
        from core.plugin_manager import PluginManager
        plugins_dir = skills_dir.parent / "plugins"
        self.plugin_manager = PluginManager(plugins_dir, mcp_router=mcp_router)

    def _auto_load(self):
        """
        Busca y carga todos los skills validos del directorio.

        Ignora archivos que comienzan con '_' y el propio skill_manager.py.
        Un skill es valido si define SKILL_NAME y execute().
        """
        if not self.skills_dir.exists():
            logger.warning(f"Directorio de skills no encontrado: {self.skills_dir}")
            return

        # Escanear tanto archivos .py como directorios (paquetes con __init__.py)
        for skill_path in self.skills_dir.iterdir():
            if skill_path.name.startswith("_"):
                continue
            if skill_path.stem == "skill_manager":
                continue

            # Si es archivo, asegurar que sea .py
            if skill_path.is_file() and skill_path.suffix != ".py":
                continue
            # Si es directorio, asegurar que tenga __init__.py
            if skill_path.is_dir() and not (skill_path / "__init__.py").exists():
                continue

            try:
                module_name = f"skills.{skill_path.stem}"
                module = importlib.import_module(module_name)
                if hasattr(module, "SKILL_NAME") and hasattr(module, "execute"):
                    self.loaded_skills[module.SKILL_NAME] = module
                    logger.info(f"[SKILL] Cargado: {module.SKILL_NAME}")
            except Exception as e:
                logger.error(f"Error cargando skill {skill_path.name}: {e}")

    def run(self, skill_name: str, **kwargs) -> str:
        """
        Ejecuta un skill o plugin por su nombre.

        Primero busca en skills incorporados, luego en plugins externos.

        Args:
            skill_name: Identificador del skill/plugin a ejecutar.
            **kwargs: Argumentos a pasar a execute().

        Returns:
            Resultado de la ejecucion como string, o mensaje de error.
        """
        # Skills incorporados
        if skill_name in self.loaded_skills:
            try:
                result = self.loaded_skills[skill_name].execute(**kwargs)
                logger.info(f"[SKILL] Ejecutado: {skill_name}")
                return result
            except Exception as e:
                error_msg = f"Error ejecutando skill '{skill_name}': {str(e)}"
                logger.error(error_msg)
                return error_msg

        # Plugins externos (via PluginManager)
        if self.plugin_manager.is_loaded(skill_name):
            return self.plugin_manager.run(skill_name, **kwargs)

        available = ", ".join(self.list_skills()) or "ninguno"
        return f"Skill o plugin '{skill_name}' no disponible. Disponibles: {available}"

    def list_skills(self) -> list[str]:
        """Retorna la lista de nombres de skills y plugins cargados."""
        skill_names = list(self.loaded_skills.keys())
        plugin_names = self.plugin_manager.plugin_names()
        return skill_names + plugin_names
