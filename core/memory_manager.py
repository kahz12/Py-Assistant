"""
core/memory_manager.py -- Gestion de memoria persistente.

Administra la escritura y lectura de conversaciones, notas y media
en el vault del asistente. Soporta consolidacion periodica de
conversaciones antiguas mediante el LLM.

Directorios gestionados:
  - conversations/ : Historial de conversaciones con timestamps.
  - notes/         : Notas generadas por el asistente o el usuario.
  - media/         : Archivos binarios recibidos (imagenes, documentos).
"""
from pathlib import Path
from datetime import datetime
from loguru import logger


class MemoryManager:
    """
    Gestor de memoria persistente del asistente.

    Lee y escribe en el vault, ya sea montado via LUKS2 o cifrado
    con Fernet a nivel de aplicacion.

    Atributos:
        vault_path: Ruta raiz del vault.
        conversations_dir: Directorio de conversaciones.
        media_dir: Directorio de archivos binarios.
        notes_dir: Directorio de notas.
        long_term_file: Archivo de memoria consolidada a largo plazo.
    """

    def __init__(self, vault_path: Path):
        self.vault_path = vault_path
        self.conversations_dir = vault_path / "conversations"
        self.media_dir = vault_path / "media"
        self.notes_dir = vault_path / "notes"
        self.long_term_file = vault_path / "long_term_memory.md"
        self._ensure_dirs()

    def _ensure_dirs(self):
        """Crea los directorios necesarios si no existen."""
        for d in [self.conversations_dir, self.media_dir, self.notes_dir]:
            d.mkdir(parents=True, exist_ok=True)
        logger.debug("Directorios del vault verificados.")

    # ------------------------------------------------------------------
    # Conversaciones
    # ------------------------------------------------------------------

    def save_conversation(self, conversation: list[dict]) -> Path:
        """
        Guarda una conversacion completa en formato Markdown.

        Cada mensaje se almacena con su rol (USER/ASSISTANT) y timestamp.

        Args:
            conversation: Lista de diccionarios con 'role' y 'content'.

        Returns:
            Ruta al archivo de conversacion creado.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = self.conversations_dir / f"{timestamp}.md"
        content = f"# Conversacion -- {timestamp}\n\n"
        for msg in conversation:
            role = msg.get("role", "unknown").upper()
            text = msg.get("content", "")
            content += f"**{role}:** {text}\n\n"
        file_path.write_text(content, encoding="utf-8")
        logger.info(f"Conversacion guardada: {file_path.name}")
        return file_path

    def get_recent_memory(self, n_conversations: int = 3) -> str:
        """
        Obtiene las ultimas N conversaciones como texto de contexto.

        Args:
            n_conversations: Cantidad de conversaciones a recuperar.

        Returns:
            Texto concatenado de las conversaciones mas recientes.
        """
        files = sorted(self.conversations_dir.glob("*.md"), reverse=True)
        recent = []
        for f in files[:n_conversations]:
            recent.append(f.read_text(encoding="utf-8"))
        return "\n---\n".join(recent)

    # ------------------------------------------------------------------
    # Notas
    # ------------------------------------------------------------------

    def save_note(self, title: str, content: str) -> Path:
        """
        Guarda una nota con titulo y contenido en el vault.

        Args:
            title: Titulo de la nota.
            content: Cuerpo de la nota.

        Returns:
            Ruta al archivo de nota creado.
        """
        slug = title.lower().replace(" ", "_")
        timestamp = datetime.now().strftime("%Y%m%d")
        file_path = self.notes_dir / f"{timestamp}_{slug}.md"
        file_path.write_text(f"# {title}\n\n{content}", encoding="utf-8")
        logger.info(f"Nota guardada: {file_path.name}")
        return file_path

    # ------------------------------------------------------------------
    # Media
    # ------------------------------------------------------------------

    def save_media(self, filename: str, data: bytes) -> Path:
        """
        Guarda un archivo binario (imagen, video, documento) en el vault.

        Args:
            filename: Nombre del archivo a guardar.
            data: Contenido binario del archivo.

        Returns:
            Ruta al archivo guardado.
        """
        media_path = self.media_dir / filename
        media_path.write_bytes(data)
        logger.info(f"Media guardado: {filename}")
        return media_path

    # ------------------------------------------------------------------
    # Consolidacion de memoria
    # ------------------------------------------------------------------

    def consolidate_memory(self, llm_engine) -> str:
        """
        Usa el LLM para resumir conversaciones antiguas y extraer
        informacion relevante a largo plazo.

        El resumen se agrega al archivo long_term_memory.md.
        Se recomienda ejecutar periodicamente (cada 20 conversaciones).

        Args:
            llm_engine: Instancia del motor LLM para generar el resumen.

        Returns:
            Texto del resumen generado.
        """
        recent = self.get_recent_memory(n_conversations=10)
        if not recent:
            return "No hay conversaciones para consolidar."

        prompt = """Analiza las siguientes conversaciones y extrae:
1. Hechos nuevos sobre el usuario
2. Preferencias detectadas
3. Tareas pendientes importantes
4. Informacion que debes recordar a largo plazo

Conversaciones:
{}

Responde en formato Markdown organizado.""".format(recent)

        summary = llm_engine.complete(prompt)

        # Anexar al archivo de memoria a largo plazo
        existing = ""
        if self.long_term_file.exists():
            existing = self.long_term_file.read_text(encoding="utf-8")

        timestamp = datetime.now().strftime("%Y-%m-%d")
        updated = existing + f"\n\n## Consolidacion -- {timestamp}\n{summary}"
        self.long_term_file.write_text(updated, encoding="utf-8")
        logger.info("Memoria consolidada exitosamente.")
        return summary

    # ------------------------------------------------------------------
    # Aprendizaje continuo
    # ------------------------------------------------------------------

    def save_preference(self, category: str, preference: str) -> str:
        """
        Guarda una preferencia del usuario para adaptacion continua.

        Las preferencias se almacenan por categoria (idioma, estilo,
        horario, temas, etc.) y se consultan al construir el contexto.

        Args:
            category: Categoria de la preferencia.
            preference: Descripcion de la preferencia.

        Returns:
            Mensaje de confirmacion.
        """
        prefs_file = self.vault_path / "user_preferences.md"
        existing = ""
        if prefs_file.exists():
            existing = prefs_file.read_text(encoding="utf-8")
        else:
            existing = "# Preferencias del Usuario\n"

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"\n- **{category}**: {preference} _{timestamp}_"
        prefs_file.write_text(existing + entry, encoding="utf-8")
        logger.info(f"Preferencia guardada: [{category}] {preference}")
        return f"Preferencia registrada: {category} = {preference}"

    def get_preferences(self) -> str:
        """Retorna todas las preferencias aprendidas del usuario."""
        prefs_file = self.vault_path / "user_preferences.md"
        if prefs_file.exists():
            return prefs_file.read_text(encoding="utf-8")
        return ""

    def save_feedback(self, response_quality: str, context: str = "") -> str:
        """
        Registra feedback sobre la calidad de una respuesta para mejora continua.

        Args:
            response_quality: 'buena', 'mala', 'incompleta', etc.
            context: Contexto adicional sobre el feedback.

        Returns:
            Mensaje de confirmacion.
        """
        feedback_file = self.vault_path / "feedback_log.md"
        existing = ""
        if feedback_file.exists():
            existing = feedback_file.read_text(encoding="utf-8")
        else:
            existing = "# Log de Feedback\n"

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"\n- [{timestamp}] Calidad: **{response_quality}**"
        if context:
            entry += f" — {context}"
        feedback_file.write_text(existing + entry, encoding="utf-8")
        logger.info(f"Feedback registrado: {response_quality}")
        return f"Feedback registrado. Gracias por ayudarme a mejorar."
