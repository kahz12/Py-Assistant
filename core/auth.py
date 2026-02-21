"""
core/auth.py -- Gestor de autenticacion del usuario.

Implementa autenticacion basada en passphrases con bcrypt (Blowfish).
bcrypt incluye salt automatico y factor de trabajo configurable,
lo que lo hace resistente a ataques de fuerza bruta y rainbow tables.

Metodos soportados: pregunta secreta, PIN numerico, frase de contrasena.
"""
import os
import time
import secrets
from pathlib import Path
from loguru import logger

try:
    import bcrypt
    _HAS_BCRYPT = True
except ImportError:
    import hashlib
    _HAS_BCRYPT = False
    logger.warning("bcrypt no disponible. Usando SHA-256 como fallback (menos seguro).")


# Factor de trabajo para bcrypt (12 = ~250ms por hash en hardware moderno).
BCRYPT_ROUNDS = 12

# Proteccion contra fuerza bruta.
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_SECONDS = 900  # 15 minutos

# Timeout de sesion por inactividad.
SESSION_TIMEOUT_SECONDS = 1800  # 30 minutos


class AuthManager:
    """
    Gestiona la autenticacion del usuario mediante bcrypt.

    Seguridad implementada:
      - Hashing con bcrypt (salt automatico, factor de trabajo 12).
      - Comparacion en tiempo constante.
      - Bloqueo tras 5 intentos fallidos (15 min).
      - Timeout de sesion por inactividad (30 min).
      - Permisos restrictivos en el archivo de auth (0600).

    Atributos:
        auth_file: Ruta al archivo donde se almacena el hash.
        is_authenticated: Estado de la sesion actual.
        session_token: Token unico generado al autenticarse con exito.
    """

    def __init__(self, auth_file: Path):
        self.auth_file = auth_file
        self.is_authenticated = False
        self.session_token = None
        self._failed_attempts = 0
        self._lockout_until = 0.0
        self._last_activity = 0.0

    @property
    def is_configured(self) -> bool:
        """Retorna True si ya existe una configuracion de autenticacion."""
        return self.auth_file.exists() and self.auth_file.stat().st_size > 0

    @property
    def is_locked_out(self) -> bool:
        """Retorna True si la autenticacion esta bloqueada por intentos fallidos."""
        if self._lockout_until > 0 and time.time() < self._lockout_until:
            return True
        if self._lockout_until > 0 and time.time() >= self._lockout_until:
            # Lockout expirado, reiniciar
            self._lockout_until = 0.0
            self._failed_attempts = 0
        return False

    def _check_session_timeout(self):
        """Invalida la sesion si ha pasado el timeout de inactividad."""
        if self.is_authenticated and self._last_activity > 0:
            elapsed = time.time() - self._last_activity
            if elapsed > SESSION_TIMEOUT_SECONDS:
                logger.info("Sesion expirada por inactividad.")
                self.logout()

    def refresh_activity(self):
        """Actualiza el timestamp de ultima actividad (llamar en cada mensaje)."""
        if self.is_authenticated:
            self._last_activity = time.time()

    def setup(self, method: str, secret: str):
        """
        Configura la autenticacion por primera vez.

        Genera un hash bcrypt de la frase secreta y lo almacena
        junto con el metodo utilizado. El archivo se protege con
        permisos 0600.

        Args:
            method: Tipo de autenticacion (passphrase, pin, pregunta).
            secret: Valor secreto proporcionado por el usuario.
        """
        if _HAS_BCRYPT:
            hashed = bcrypt.hashpw(secret.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS))
            hash_str = hashed.decode("utf-8")
        else:
            # Fallback SHA-256 con salt manual
            import hashlib
            salt = secrets.token_hex(16)
            hashed = hashlib.sha256((salt + secret).encode()).hexdigest()
            hash_str = f"{salt}${hashed}"

        data = f"method:{method}\nhash:{hash_str}\n"
        self.auth_file.parent.mkdir(parents=True, exist_ok=True)
        self.auth_file.write_text(data, encoding="utf-8")

        # Permisos restrictivos: solo el propietario puede leer/escribir
        os.chmod(self.auth_file, 0o600)

        logger.info(f"Autenticacion configurada con metodo: {method}")

    def authenticate(self, input_secret: str) -> bool:
        """
        Verifica la identidad del usuario comparando hashes bcrypt.

        Incluye proteccion contra fuerza bruta:
          - Maximo 5 intentos fallidos antes de bloqueo.
          - Bloqueo temporal de 15 minutos.

        Args:
            input_secret: Valor secreto proporcionado por el usuario.

        Returns:
            True si la autenticacion fue exitosa, False en caso contrario.

        Raises:
            RuntimeError: Si la autenticacion no fue configurada previamente.
        """
        if not self.is_configured:
            raise RuntimeError("Autenticacion no configurada. Ejecuta setup primero.")

        # Verificar bloqueo por intentos fallidos
        if self.is_locked_out:
            remaining = int(self._lockout_until - time.time())
            logger.warning(f"Autenticacion bloqueada. Quedan {remaining}s.")
            return False

        # Leer el hash almacenado
        data = {}
        for line in self.auth_file.read_text(encoding="utf-8").strip().splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                data[key.strip()] = value.strip()

        stored_hash = data.get("hash", "")

        # Verificar con bcrypt o SHA-256 fallback
        match = False
        if _HAS_BCRYPT and stored_hash.startswith("$2"):
            # Hash bcrypt
            match = bcrypt.checkpw(
                input_secret.encode("utf-8"),
                stored_hash.encode("utf-8"),
            )
        elif "$" in stored_hash and not stored_hash.startswith("$2"):
            # Fallback SHA-256 con salt
            import hashlib
            salt, expected_hash = stored_hash.split("$", 1)
            computed = hashlib.sha256((salt + input_secret).encode()).hexdigest()
            match = secrets.compare_digest(expected_hash, computed)
        else:
            # Legacy SHA-256 sin salt (compatibilidad con configuraciones anteriores)
            import hashlib
            input_hash = hashlib.sha256(input_secret.encode()).hexdigest()
            match = secrets.compare_digest(stored_hash, input_hash)

        if match:
            self.is_authenticated = True
            self.session_token = secrets.token_hex(32)
            self._failed_attempts = 0
            self._lockout_until = 0.0
            self._last_activity = time.time()
            logger.info("Autenticacion exitosa.")
            return True

        # Intento fallido
        self._failed_attempts += 1
        logger.warning(
            f"Intento de autenticacion fallido ({self._failed_attempts}/{MAX_FAILED_ATTEMPTS})."
        )

        if self._failed_attempts >= MAX_FAILED_ATTEMPTS:
            self._lockout_until = time.time() + LOCKOUT_DURATION_SECONDS
            logger.warning(
                f"Autenticacion bloqueada por {LOCKOUT_DURATION_SECONDS}s "
                f"tras {MAX_FAILED_ATTEMPTS} intentos fallidos."
            )

        return False

    def logout(self):
        """Cierra la sesion activa e invalida el token."""
        self.is_authenticated = False
        self.session_token = None
        self._last_activity = 0.0
        logger.info("Sesion cerrada.")

    def require_auth(self, func):
        """
        Decorador que protege funciones tras autenticacion.

        Verifica el timeout de sesion antes de ejecutar la funcion.
        """
        def wrapper(*args, **kwargs):
            self._check_session_timeout()
            if not self.is_authenticated:
                return "Autenticacion requerida. Identificate primero."
            self.refresh_activity()
            return func(*args, **kwargs)
        return wrapper
