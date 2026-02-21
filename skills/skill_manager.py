"""
skills/skill_manager.py -- Cargador dinamico de habilidades.

Busca modulos Python en el directorio skills/ que expongan:
  - SKILL_NAME : str         -- Identificador unico del skill.
  - execute(**kwargs) : str  -- Funcion principal de ejecucion.

Los skills se cargan automaticamente al inicializar el SkillManager.
"""
import importlib
from pathlib import Path
from loguru import logger


class SkillManager:
    """
    Carga y ejecuta skills de forma dinamica.

    Cada skill es un modulo Python independiente ubicado en el directorio
    de skills. Para ser reconocido, debe definir las constantes
    SKILL_NAME y la funcion execute().

    Atributos:
        skills_dir: Ruta al directorio de skills.
        loaded_skills: Diccionario {nombre: modulo} de skills cargados.
    """

    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.loaded_skills: dict[str, object] = {}
        self._auto_load()

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

        # Cargar plugins externos
        plugins_dir = self.skills_dir.parent / "plugins"
        if plugins_dir.exists():
            for plugin_file in plugins_dir.glob("*.py"):
                if plugin_file.name.startswith("_"):
                    continue

                try:
                    import sys
                    if str(plugins_dir) not in sys.path:
                        sys.path.insert(0, str(plugins_dir))
                    
                    module_name = plugin_file.stem
                    module = importlib.import_module(module_name)
                    if hasattr(module, "SKILL_NAME") and hasattr(module, "execute"):
                        self.loaded_skills[module.SKILL_NAME] = module
                        logger.info(f"[PLUGIN] Cargado: {module.SKILL_NAME}")
                except Exception as e:
                    logger.error(f"Error cargando plugin {plugin_file.name}: {e}")

    def run(self, skill_name: str, **kwargs) -> str:
        """
        Ejecuta un skill por su nombre.

        Args:
            skill_name: Identificador del skill a ejecutar.
            **kwargs: Argumentos a pasar a la funcion execute() del skill.

        Returns:
            Resultado de la ejecucion como string, o mensaje de error.
        """
        if skill_name not in self.loaded_skills:
            return f"Skill '{skill_name}' no disponible."
        try:
            result = self.loaded_skills[skill_name].execute(**kwargs)
            logger.info(f"[SKILL] Ejecutado: {skill_name}")
            return result
        except Exception as e:
            error_msg = f"Error ejecutando skill '{skill_name}': {str(e)}"
            logger.error(error_msg)
            return error_msg

    def list_skills(self) -> list[str]:
        """Retorna la lista de nombres de skills cargados."""
        return list(self.loaded_skills.keys())
