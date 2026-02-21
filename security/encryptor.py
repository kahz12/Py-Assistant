"""
security/encryptor.py -- Cifrado de archivos con Fernet (AES-128-CBC).

Proporciona cifrado y descifrado a nivel de archivo individual.
Alternativa a LUKS2 para entornos donde no se dispone de acceso root.

La clave se genera automaticamente en la primera ejecucion y se
almacena con permisos restrictivos (0600) para el propietario.
"""
from cryptography.fernet import Fernet
from pathlib import Path
from loguru import logger
import os


class VaultEncryptor:
    """
    Cifra y descifra archivos individuales del vault usando Fernet.

    Fernet garantiza que los datos cifrados no pueden ser leidos ni
    manipulados sin la clave correcta (autenticacion + cifrado).

    Atributos:
        key_path: Ruta al archivo que contiene la clave de cifrado.
        fernet: Instancia de Fernet inicializada con la clave.
    """

    def __init__(self, key_path: Path):
        self.key_path = key_path
        self.fernet = self._load_or_create_key()

    def _load_or_create_key(self) -> Fernet:
        """
        Carga la clave de cifrado existente o genera una nueva.

        Si la clave no existe, se genera automaticamente y se almacena
        con permisos 0600 (solo lectura/escritura para el propietario).

        Validacion (SEC-13):
          - La clave debe ser exactamente 44 bytes (base64 de 32 bytes).
          - Si la clave esta corrupta, se genera un error explicito.

        Returns:
            Instancia de Fernet lista para cifrar/descifrar.

        Raises:
            ValueError: Si la clave almacenada esta corrupta.
        """
        if self.key_path.exists():
            key = self.key_path.read_bytes().strip()
            # Validar longitud de la clave (44 bytes base64 = 32 bytes raw)
            if len(key) != 44:
                raise ValueError(
                    f"Clave de cifrado corrupta en {self.key_path} "
                    f"(esperados 44 bytes, encontrados {len(key)}). "
                    "Elimina el archivo para regenerar la clave."
                )
            try:
                fernet = Fernet(key)
            except Exception as e:
                raise ValueError(
                    f"Clave de cifrado invalida en {self.key_path}: {e}"
                )
            logger.debug("Clave de cifrado cargada y validada.")
            return fernet
        else:
            key = Fernet.generate_key()
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            self.key_path.write_bytes(key)
            os.chmod(self.key_path, 0o600)
            logger.info("Nueva clave de cifrado generada y almacenada.")
            return Fernet(key)

    def encrypt_file(self, file_path: Path):
        """
        Cifra un archivo in-situ, reemplazando su contenido original.

        Args:
            file_path: Ruta al archivo que sera cifrado.
        """
        data = file_path.read_bytes()
        encrypted = self.fernet.encrypt(data)
        file_path.write_bytes(encrypted)
        logger.debug(f"Archivo cifrado: {file_path.name}")

    def decrypt_file(self, file_path: Path) -> bytes:
        """
        Descifra un archivo y retorna su contenido en memoria.

        No modifica el archivo en disco; la operacion es de solo lectura.

        Args:
            file_path: Ruta al archivo cifrado.

        Returns:
            Contenido descifrado como bytes.
        """
        encrypted = file_path.read_bytes()
        return self.fernet.decrypt(encrypted)

    def read_text(self, file_path: Path) -> str:
        """
        Descifra un archivo y retorna su contenido como texto UTF-8.

        Args:
            file_path: Ruta al archivo cifrado.

        Returns:
            Contenido descifrado como cadena de texto.
        """
        return self.decrypt_file(file_path).decode("utf-8")

    def write_text(self, file_path: Path, content: str):
        """
        Cifra una cadena de texto y la escribe en el archivo indicado.

        Args:
            file_path: Ruta destino del archivo cifrado.
            content: Texto a cifrar y almacenar.
        """
        encrypted = self.fernet.encrypt(content.encode("utf-8"))
        file_path.write_bytes(encrypted)
        logger.debug(f"Texto cifrado almacenado: {file_path.name}")
