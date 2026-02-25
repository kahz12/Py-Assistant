"""
core/user_registry.py -- Registro multi-usuario con roles.

Soporta N usuarios de Telegram con roles `admin` o `viewer`.
Persiste en `memory_vault/users.json` (cifrado a nivel filesystem por LUKS2).

Roles:
  - admin  : Acceso total. Puede chatear, configurar y gestionar usuarios.
  - viewer : Solo puede chatear. No puede /reset, /logout ni /adduser.

Uso:
    registry = UserRegistry(vault_path)
    registry.add_user(user_id=123, username="ale", role="admin", auth_hash="bcrypt_hash")
    user = registry.get_user(123)
    if registry.is_allowed(123, min_role="viewer"):
        ...
"""
import json
import time
from pathlib import Path
from typing import Optional
from loguru import logger


ROLES = ("admin", "viewer")
ROLE_RANK = {"admin": 100, "viewer": 10}


class UserRegistry:
    """
    Registro persistente de usuarios autorizados.

    Atributos:
        _path: Ruta al archivo users.json.
        _users: Diccionario interno {user_id: user_record}.
    """

    def __init__(self, vault_path: Path):
        self._path = vault_path / "users.json"
        self._users: dict[int, dict] = {}
        self._load()
        logger.info(f"[UserRegistry] Cargado con {len(self._users)} usuario(s).")

    # ------------------------------------------------------------------
    # Persistencia
    # ------------------------------------------------------------------

    def _load(self):
        """Carga usuarios desde disco."""
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._users = {int(k): v for k, v in data.items()}
            except Exception as e:
                logger.error(f"[UserRegistry] Error al cargar users.json: {e}")

    def _save(self):
        """Persiste usuarios a disco atomicamente."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({str(k): v for k, v in self._users.items()}, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            tmp.replace(self._path)
            self._path.chmod(0o600)
        except Exception as e:
            logger.error(f"[UserRegistry] Error al guardar users.json: {e}")

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add_user(
        self,
        user_id: int,
        username: str,
        role: str,
        auth_hash: Optional[str] = None,
    ) -> bool:
        """
        Registra un nuevo usuario.

        Args:
            user_id: ID de Telegram.
            username: Nombre de usuario (sin @).
            role: 'admin' o 'viewer'.
            auth_hash: Hash bcrypt del passphrase (None = sin passphrase propia).

        Returns:
            True si se registro correctamente.
        """
        if role not in ROLES:
            logger.warning(f"[UserRegistry] Rol inválido: '{role}'")
            return False
        self._users[user_id] = {
            "user_id": user_id,
            "username": username,
            "role": role,
            "auth_hash": auth_hash,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self._save()
        logger.info(f"[UserRegistry] Usuario registrado: {username} ({user_id}) rol={role}")
        return True

    def remove_user(self, user_id: int) -> bool:
        """Elimina un usuario del registro."""
        if user_id in self._users:
            username = self._users[user_id].get("username", str(user_id))
            del self._users[user_id]
            self._save()
            logger.info(f"[UserRegistry] Usuario eliminado: {username} ({user_id})")
            return True
        return False

    def update_role(self, user_id: int, new_role: str) -> bool:
        """Cambia el rol de un usuario existente."""
        if user_id not in self._users or new_role not in ROLES:
            return False
        self._users[user_id]["role"] = new_role
        self._save()
        logger.info(f"[UserRegistry] Rol actualizado: {user_id} -> {new_role}")
        return True

    def get_user(self, user_id: int) -> Optional[dict]:
        """Retorna el registro de un usuario o None si no existe."""
        return self._users.get(user_id)

    def list_users(self) -> list[dict]:
        """Retorna todos los usuarios (sin auth_hash por seguridad)."""
        return [
            {k: v for k, v in u.items() if k != "auth_hash"}
            for u in self._users.values()
        ]

    def count(self) -> int:
        """Retorna el numero total de usuarios registrados."""
        return len(self._users)

    # ------------------------------------------------------------------
    # Autorización
    # ------------------------------------------------------------------

    def is_allowed(self, user_id: int, min_role: str = "viewer") -> bool:
        """
        Verifica si un usuario tiene al menos el rol minimo requerido.

        Args:
            user_id: ID de Telegram a verificar.
            min_role: Rol minimo requerido ('viewer' o 'admin').

        Returns:
            True si el usuario esta registrado y tiene el rol suficiente.
        """
        user = self._users.get(user_id)
        if not user:
            return False
        user_rank = ROLE_RANK.get(user["role"], 0)
        required_rank = ROLE_RANK.get(min_role, 0)
        return user_rank >= required_rank

    def is_admin(self, user_id: int) -> bool:
        """Atajo: True si el usuario es admin."""
        return self.is_allowed(user_id, min_role="admin")

    def get_role(self, user_id: int) -> Optional[str]:
        """Retorna el rol del usuario o None si no esta registrado."""
        user = self._users.get(user_id)
        return user["role"] if user else None

    def migrate_from_pairing(self, user_id: int, username: str = "admin") -> bool:
        """
        Migra el usuario emparejado legado (archivo .pairing) al UserRegistry
        como admin si aun no existe en el registro.

        Args:
            user_id: ID del usuario legacy emparejado.
            username: Nombre de usuario.

        Returns:
            True si se migro (no existia), False si ya estaba registrado.
        """
        if user_id in self._users:
            return False
        return self.add_user(user_id, username, role="admin")
