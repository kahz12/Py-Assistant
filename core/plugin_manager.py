"""
core/plugin_manager.py -- Gestor avanzado del sistema de plugins.

Mejora sustancialmente la logica de carga de plugins del SkillManager original:
  - Auto-descubrimiento de plugins en plugins/*.py
  - Manifests JSON autogenerados en plugins/manifests/
  - Hot-reload de plugins en runtime sin reiniciar el proceso
  - Install-from-GitHub: descarga e instala plugins externos
  - Sandboxed execute() con timeout configurable via threading
  - Registro automatico de MCP tools si el plugin define MCP_TOOLS
  - Validacion de variables de entorno requeridas (REQUIRES_ENV)

Interfaz del plugin (plugins/my_plugin.py):
    SKILL_NAME      = "my_plugin"           # obligatorio
    SKILL_DESCRIPTION = "..."               # opcional
    VERSION         = "1.0.0"              # opcional
    AUTHOR          = "autor"              # opcional
    REQUIRES_ENV    = ["MY_API_KEY"]       # opcional
    ACTIONS         = ["action1", "action2"]  # opcional

    def execute(action="default", **kwargs) -> str:
        ...

Uso:
    pm = PluginManager(plugins_dir=Path("plugins"), mcp_router=mcp)
    pm.list_plugins()            # [{"name": ..., "version": ..., ...}, ...]
    pm.run("my_plugin", action="hello")
    pm.reload("my_plugin")
    pm.install_from_github("https://github.com/user/repo/blob/main/my_plugin.py")
"""
import importlib
import importlib.util
import json
import os
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional
from loguru import logger


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

@dataclass
class PluginManifest:
    """
    Representa los metadatos de un plugin instalado.

    Atributos:
        name: Identificador unico (SKILL_NAME del modulo).
        display_name: Nombre legible (default = name).
        description: Descripcion breve del plugin.
        version: Version semantica (default "0.0.0").
        author: Autor del plugin.
        source: "local" o URL de origen.
        actions: Lista de acciones soportadas.
        requires_env: Variables de entorno requeridas.
        loaded_at: Timestamp ISO de la ultima carga exitosa.
        enabled: Si el plugin esta habilitado.
    """
    name: str
    display_name: str = ""
    description: str = ""
    version: str = "0.0.0"
    author: str = "local"
    source: str = "local"
    actions: list[str] = field(default_factory=list)
    requires_env: list[str] = field(default_factory=list)
    loaded_at: str = ""
    enabled: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PluginManifest":
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in valid_keys})

    @classmethod
    def from_module(cls, module, source: str = "local") -> "PluginManifest":
        """Construye un manifiesto a partir de las constantes del modulo."""
        name = getattr(module, "SKILL_NAME", module.__name__)
        return cls(
            name=name,
            display_name=getattr(module, "SKILL_DISPLAY_NAME", name.replace("_", " ").title()),
            description=getattr(module, "SKILL_DESCRIPTION", ""),
            version=getattr(module, "VERSION", "0.0.0"),
            author=getattr(module, "AUTHOR", "local"),
            source=source,
            actions=getattr(module, "ACTIONS", []),
            requires_env=getattr(module, "REQUIRES_ENV", []),
            loaded_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            enabled=True,
        )


# ---------------------------------------------------------------------------
# PluginManager
# ---------------------------------------------------------------------------

class PluginManager:
    """
    Gestor central del sistema de plugins.

    Carga, valida, refresca e instala plugins externos. Mantiene
    manifests JSON para cada plugin y puede registrar tools MCP
    automaticamente si el plugin los declara.

    Atributos:
        plugins_dir: Directorio raiz de los plugins.
        manifests_dir: Subdirectorio donde se guardan los manifests JSON.
        _plugins: {name: module} de plugins cargados.
        _manifests: {name: PluginManifest} de metadatos.
        _mcp: MCPRouter para registro de tools automatico (opcional).
        execute_timeout: Timeout en segundos para execute() (default 30).
    """

    def __init__(
        self,
        plugins_dir: Path,
        mcp_router=None,
        execute_timeout: int = 30,
    ):
        self.plugins_dir = plugins_dir
        self.manifests_dir = plugins_dir / "manifests"
        self._plugins: dict[str, Any] = {}
        self._manifests: dict[str, PluginManifest] = {}
        self._mcp = mcp_router
        self.execute_timeout = execute_timeout

        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        self.manifests_dir.mkdir(parents=True, exist_ok=True)

        # Asegurar que plugins/ sea un paquete Python importable
        init_file = self.plugins_dir / "__init__.py"
        if not init_file.exists():
            init_file.write_text("# Plugin package — auto-generated\n")

        # Añadir al sys.path para importacion directa
        plugins_parent = str(self.plugins_dir.parent)
        if plugins_parent not in sys.path:
            sys.path.insert(0, plugins_parent)

        self._auto_discover()
        logger.info(f"[PluginManager] {len(self._plugins)} plugin(s) cargado(s).")

    # ------------------------------------------------------------------
    # Carga y descubrimiento
    # ------------------------------------------------------------------

    def _auto_discover(self):
        """Escanea plugins_dir y carga todos los plugins validos."""
        for plugin_path in sorted(self.plugins_dir.glob("*.py")):
            if plugin_path.name.startswith("_"):
                continue
            self._load_file(plugin_path, source="local")

    def _load_file(self, plugin_path: Path, source: str = "local") -> bool:
        """
        Carga un archivo .py como plugin.

        Args:
            plugin_path: Ruta al archivo del plugin.
            source: "local" o URL de origen.

        Returns:
            True si el plugin fue cargado exitosamente.
        """
        module_name = f"plugins.{plugin_path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, plugin_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            if not hasattr(module, "SKILL_NAME") or not hasattr(module, "execute"):
                logger.warning(
                    f"[PluginManager] '{plugin_path.name}' ignorado "
                    f"(falta SKILL_NAME o execute())."
                )
                return False

            name = module.SKILL_NAME
            manifest = self._load_or_create_manifest(module, source)

            # Verificar env vars requeridas
            missing_env = [e for e in manifest.requires_env if not os.environ.get(e)]
            if missing_env:
                logger.warning(
                    f"[PluginManager] '{name}' cargado con vars faltantes: "
                    f"{', '.join(missing_env)} — algunas funciones pueden fallar."
                )

            self._plugins[name] = module
            self._manifests[name] = manifest

            # Registrar MCP tools adicionales si el plugin las declara
            self._register_mcp_tools(module, name)

            logger.info(f"[PluginManager] Cargado: {name} v{manifest.version}")
            return True

        except Exception as e:
            logger.error(f"[PluginManager] Error cargando '{plugin_path.name}': {e}")
            return False

    def _load_or_create_manifest(self, module, source: str) -> PluginManifest:
        """Lee el manifest existente o lo genera desde el modulo."""
        name = module.SKILL_NAME
        manifest_path = self.manifests_dir / f"{name}.json"

        if manifest_path.exists():
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest = PluginManifest.from_dict(data)
                # Actualizar timestamp y version en vivo desde el modulo
                manifest.version = getattr(module, "VERSION", manifest.version)
                manifest.loaded_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            except Exception:
                manifest = PluginManifest.from_module(module, source)
        else:
            manifest = PluginManifest.from_module(module, source)

        self._save_manifest(manifest)
        return manifest

    def _save_manifest(self, manifest: PluginManifest):
        """Persiste el manifest a disco atomicamente."""
        path = self.manifests_dir / f"{manifest.name}.json"
        try:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(path)
        except Exception as e:
            logger.warning(f"[PluginManager] No se pudo guardar manifest de '{manifest.name}': {e}")

    def _register_mcp_tools(self, module, plugin_name: str):
        """
        Si el plugin define MCP_TOOLS (lista de dicts), los registra en el MCPRouter.

        Formato MCP_TOOLS:
            [{"name": "...", "description": "...", "parameters": {...}, "fn": callable}]
        """
        if not self._mcp:
            return
        mcp_tools = getattr(module, "MCP_TOOLS", None)
        if not mcp_tools or not isinstance(mcp_tools, list):
            return
        for tool_spec in mcp_tools:
            try:
                fn = tool_spec.get("fn")
                name = tool_spec.get("name")
                if not fn or not name:
                    continue
                # Usar el decorador register del MCPRouter
                decorated = self._mcp.register(
                    name=f"plugin_{plugin_name}_{name}",
                    description=tool_spec.get("description", ""),
                    parameters=tool_spec.get("parameters", {"type": "object", "properties": {}}),
                )(fn)
                logger.info(f"[PluginManager] MCP tool registrada: plugin_{plugin_name}_{name}")
            except Exception as e:
                logger.warning(f"[PluginManager] Error registrando MCP tool de '{plugin_name}': {e}")

    # ------------------------------------------------------------------
    # Hot-reload
    # ------------------------------------------------------------------

    def reload(self, plugin_name: str) -> str:
        """
        Recarga un plugin en tiempo de ejecucion sin reiniciar el proceso.

        Args:
            plugin_name: Nombre del plugin a recargar.

        Returns:
            Mensaje de exito o error.
        """
        if plugin_name not in self._plugins:
            return f"Plugin '{plugin_name}' no encontrado."

        module = self._plugins[plugin_name]
        plugin_file = Path(module.__file__)

        # Eliminar del cache de modulos para forzar reimportacion
        module_key = f"plugins.{plugin_file.stem}"
        sys.modules.pop(module_key, None)
        sys.modules.pop(plugin_file.stem, None)

        ok = self._load_file(plugin_file, source=self._manifests[plugin_name].source)
        if ok:
            return f"Plugin '{plugin_name}' recargado exitosamente."
        return f"Error al recargar '{plugin_name}'. Revisa los logs."

    def reload_all(self) -> str:
        """Recarga todos los plugins cargados y re-descubre nuevos archivos."""
        reloaded = []
        for name in list(self._plugins.keys()):
            result = self.reload(name)
            reloaded.append(result)
        # Descubrir nuevos plugins que no estaban cargados
        self._auto_discover()
        return "\n".join(reloaded) if reloaded else "No hay plugins cargados."

    # ------------------------------------------------------------------
    # Install-from-GitHub
    # ------------------------------------------------------------------

    def install_from_github(self, url: str) -> str:
        """
        Descarga e instala un plugin desde una URL de GitHub (raw).

        Acepta:
          - URL de archivo raw: https://raw.githubusercontent.com/user/repo/main/plugin.py
          - URL de blob normal: https://github.com/user/repo/blob/main/plugin.py
              (se convierte a raw automaticamente)

        Args:
            url: URL del archivo .py del plugin en GitHub.

        Returns:
            Mensaje de exito o error.
        """
        # Convertir URL blob a raw si es necesario
        raw_url = url.replace(
            "github.com", "raw.githubusercontent.com"
        ).replace("/blob/", "/")

        if not raw_url.endswith(".py"):
            return "La URL debe apuntar a un archivo .py."

        filename = raw_url.split("/")[-1]
        dest_path = self.plugins_dir / filename

        # Seguridad: solo permitir nombres de archivo validos
        if not filename.replace("_", "").replace("-", "").replace(".", "").isalnum():
            return f"Nombre de archivo no valido: '{filename}'"

        if dest_path.exists():
            return (
                f"El plugin '{filename}' ya existe. "
                f"Usa reload('{filename[:-3]}') para recargarlo."
            )

        try:
            logger.info(f"[PluginManager] Descargando plugin desde: {raw_url}")
            with urllib.request.urlopen(raw_url, timeout=15) as resp:  # noqa: S310
                content = resp.read().decode("utf-8")

            # Validacion minima de contenido antes de guardar
            if "SKILL_NAME" not in content or "def execute" not in content:
                return (
                    "El archivo descargado no parece ser un plugin valido "
                    "(falta SKILL_NAME o def execute)."
                )

            dest_path.write_text(content, encoding="utf-8")
            ok = self._load_file(dest_path, source=raw_url)

            if ok:
                return f"Plugin '{filename[:-3]}' instalado y cargado exitosamente."
            return f"Plugin descargado pero no pudo cargarse. Revisa los logs."

        except Exception as e:
            logger.error(f"[PluginManager] Error instalando plugin desde '{url}': {e}")
            return f"Error al descargar el plugin: {str(e)}"

    # ------------------------------------------------------------------
    # Ejecucion con sandboxing
    # ------------------------------------------------------------------

    def run(self, plugin_name: str, **kwargs) -> str:
        """
        Ejecuta un plugin con timeout y captura de excepciones.

        Args:
            plugin_name: Nombre del plugin.
            **kwargs: Argumentos para execute() del plugin.

        Returns:
            Resultado del plugin o mensaje de error/timeout.
        """
        if plugin_name not in self._plugins:
            available = ", ".join(self._plugins.keys()) or "ninguno"
            return f"Plugin '{plugin_name}' no disponible. Plugins cargados: {available}"

        module = self._plugins[plugin_name]
        result_container: list = []
        error_container: list = []

        def _target():
            try:
                result_container.append(module.execute(**kwargs))
            except Exception as e:
                error_container.append(str(e))

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()
        thread.join(timeout=self.execute_timeout)

        if thread.is_alive():
            logger.error(f"[PluginManager] Timeout ejecutando '{plugin_name}'")
            return f"Timeout: el plugin '{plugin_name}' tardo mas de {self.execute_timeout}s."

        if error_container:
            logger.error(f"[PluginManager] Error en '{plugin_name}': {error_container[0]}")
            return f"Error en plugin '{plugin_name}': {error_container[0]}"

        return result_container[0] if result_container else ""

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------

    def list_plugins(self) -> list[dict]:
        """Retorna la lista de plugins con sus metadatos (sin datos sensibles)."""
        result = []
        for name, manifest in self._manifests.items():
            d = manifest.to_dict()
            # Indicar cuales env vars faltan sin exponer los valores
            missing = [e for e in manifest.requires_env if not os.environ.get(e)]
            d["missing_env"] = missing
            d["status"] = "⚠️ env incompleta" if missing else "✅ listo"
            result.append(d)
        return result

    def get_manifest(self, plugin_name: str) -> Optional[PluginManifest]:
        """Retorna el manifiesto de un plugin por nombre."""
        return self._manifests.get(plugin_name)

    def plugin_names(self) -> list[str]:
        """Retorna la lista de nombres de plugins cargados."""
        return list(self._plugins.keys())

    def is_loaded(self, plugin_name: str) -> bool:
        """True si el plugin esta cargado."""
        return plugin_name in self._plugins

    def disable(self, plugin_name: str) -> bool:
        """Deshabilita un plugin sin eliminarlo del disco."""
        if plugin_name in self._plugins:
            del self._plugins[plugin_name]
            if plugin_name in self._manifests:
                self._manifests[plugin_name].enabled = False
                self._save_manifest(self._manifests[plugin_name])
            logger.info(f"[PluginManager] Plugin deshabilitado: {plugin_name}")
            return True
        return False
