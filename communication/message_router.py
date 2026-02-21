"""
communication/message_router.py -- Enrutador de mensajes entrantes.

Clasifica mensajes segun su contenido y los deriva al handler apropiado.
Permite registrar handlers personalizados por tipo de mensaje.

Actualmente basado en palabras clave. En futuras versiones se
integrara clasificacion inteligente via LLM.
"""
from loguru import logger


class MessageRouter:
    """
    Clasifica mensajes entrantes y los enruta al handler correspondiente.

    El enrutamiento se basa en palabras clave al inicio del mensaje.
    Si no se encuentra un comando especial, el mensaje se clasifica
    como 'chat' para procesamiento normal por el asistente.

    Atributos:
        handlers: Diccionario de handlers registrados por tipo de mensaje.
    """

    # Palabras clave reconocidas y su tipo correspondiente.
    SPECIAL_COMMANDS = {
        "recordar": "memory",
        "nota": "note",
        "buscar": "search",
        "estado": "status",
        "ayuda": "help",
        "skills": "list_skills",
        "herramientas": "list_tools",
    }

    def __init__(self):
        self.handlers = {}

    def register_handler(self, message_type: str, handler):
        """
        Registra un handler para un tipo de mensaje.

        Args:
            message_type: Tipo de mensaje (ej: 'memory', 'note', 'search').
            handler: Funcion asincrona que procesara el mensaje.
        """
        self.handlers[message_type] = handler
        logger.debug(f"Handler registrado para tipo: {message_type}")

    def classify(self, message: str) -> dict:
        """
        Clasifica un mensaje y retorna metadata de enrutamiento.

        Busca coincidencias con palabras clave al inicio del mensaje.
        Si no encuentra una, lo clasifica como mensaje de chat normal.

        Args:
            message: Texto del mensaje a clasificar.

        Returns:
            Diccionario con:
              - type: Tipo de mensaje ('chat', 'memory', 'note', etc.).
              - original: Mensaje original sin modificar.
              - content: Mensaje sin la palabra clave (para comandos) o completo (para chat).
        """
        message_lower = message.strip().lower()

        for keyword, cmd_type in self.SPECIAL_COMMANDS.items():
            if message_lower.startswith(keyword):
                return {
                    "type": cmd_type,
                    "original": message,
                    "content": message[len(keyword):].strip(),
                }

        return {
            "type": "chat",
            "original": message,
            "content": message,
        }

    async def route(self, message: str) -> str:
        """
        Clasifica un mensaje y lo enruta al handler registrado.

        Si no existe un handler para el tipo clasificado, retorna None
        para que el mensaje sea procesado por el flujo normal del asistente.

        Args:
            message: Texto del mensaje a enrutar.

        Returns:
            Respuesta del handler, o None si no hay handler registrado.
        """
        classified = self.classify(message)
        msg_type = classified["type"]

        if msg_type in self.handlers:
            handler = self.handlers[msg_type]
            return await handler(classified)

        return None
