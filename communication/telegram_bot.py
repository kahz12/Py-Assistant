"""
communication/telegram_bot.py -- Interfaz principal del asistente via Telegram.

Gestiona toda la comunicacion con el usuario, incluyendo:
  - Emparejamiento seguro via terminal del servidor.
  - Wizard de onboarding (6 pasos) para configurar el asistente.
  - Autenticacion con passphrase.
  - Procesamiento de mensajes de texto y archivos multimedia.
  - Rate limiting para prevenir floods.
  - Comandos: /start, /setup, /status, /logout, /reset.
"""
import time
import threading
import re
from collections import defaultdict
from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    filters,
    ContextTypes,
)
from pathlib import Path
from core.auth import AuthManager
from core.assistant import Assistant
from loguru import logger


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Estados del wizard de onboarding
ONBOARDING_NONE = "none"
ONBOARDING_NAME = "waiting_name"
ONBOARDING_GENDER = "waiting_gender"
ONBOARDING_PERSONALITY = "waiting_personality"
ONBOARDING_BEHAVIOR = "waiting_behavior"
ONBOARDING_ETHICS = "waiting_ethics"
ONBOARDING_USER_NAME = "waiting_user_name"

# Rate limiting: maximo de mensajes por ventana de tiempo
RATE_LIMIT_MESSAGES = 10
RATE_LIMIT_WINDOW = 60  # segundos


# ---------------------------------------------------------------------------
# Clase principal
# ---------------------------------------------------------------------------

class TelegramInterface:
    """
    Interfaz de comunicacion del asistente via Telegram.

    Responsabilidades:
      - Gestionar el ciclo de vida del bot (polling).
      - Validar la identidad del usuario (pairing + auth).
      - Ejecutar el wizard de onboarding en la primera configuracion.
      - Aplicar rate limiting por usuario.
      - Enrutar mensajes al orquestador (Assistant).

    Atributos:
        token: Token del bot de Telegram.
        assistant: Instancia del orquestador.
        auth: Gestor de autenticacion.
        vault_path: Ruta al vault para persistencia de pairing/onboarding.
        allowed_user_id: ID del usuario emparejado (None si no existe).
    """

    def __init__(self, token: str, assistant: Assistant, auth: AuthManager, vault_path: Path = None):
        self.token = token
        self.assistant = assistant
        self.auth = auth
        self.vault_path = vault_path
        self.pairing_file = vault_path / ".pairing" if vault_path else None
        self.allowed_user_id = self._load_pairing()
        self.pending_pairing: dict | None = None

        # Estado del wizard de onboarding
        self.onboarding_state = ONBOARDING_NONE
        self.onboarding_data = {}

        # Rate limiting: {user_id: [timestamps]}
        self._rate_limits: dict[int, list[float]] = defaultdict(list)

        # Inicializar la aplicacion de Telegram
        self.app = Application.builder().token(token).build()
        self._register_handlers()

        if self.allowed_user_id:
            logger.info(f"Telegram Bot configurado. Usuario emparejado: {self.allowed_user_id}")
        else:
            logger.info("Telegram Bot configurado. Esperando primer usuario.")

    def _register_handlers(self):
        """Registra todos los handlers de comandos y mensajes."""
        self.app.add_handler(CommandHandler("start", self.handle_start))
        self.app.add_handler(CommandHandler("logout", self.handle_logout))
        self.app.add_handler(CommandHandler("status", self.handle_status))
        self.app.add_handler(CommandHandler("setup", self.handle_setup))
        self.app.add_handler(CommandHandler("reset", self.handle_reset))
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )
        self.app.add_handler(
            MessageHandler(filters.PHOTO | filters.Document.ALL, self.handle_media)
        )
        self.app.add_error_handler(self._error_handler)

    async def _error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        """Captura y registra errores que de otro modo serian silenciosos."""
        logger.error(f"Error en el bot: {context.error}")
        if update and hasattr(update, 'message') and update.message:
            try:
                await update.message.reply_text(
                    "Error interno. Intenta de nuevo."
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # RATE LIMITING
    # ------------------------------------------------------------------

    def _is_rate_limited(self, user_id: int) -> bool:
        """
        Verifica si el usuario excedio el limite de mensajes.

        Implementa una ventana deslizante: se mantienen los timestamps
        de los ultimos N segundos y se cuenta cuantos hay.

        Args:
            user_id: ID del usuario de Telegram.

        Returns:
            True si el usuario debe ser limitado.
        """
        now = time.time()
        timestamps = self._rate_limits[user_id]
        # Limpiar timestamps fuera de la ventana
        self._rate_limits[user_id] = [t for t in timestamps if now - t < RATE_LIMIT_WINDOW]
        if len(self._rate_limits[user_id]) >= RATE_LIMIT_MESSAGES:
            logger.warning(f"Rate limit alcanzado para usuario {user_id}")
            return True
        self._rate_limits[user_id].append(now)
        return False

    # ------------------------------------------------------------------
    # EMPAREJAMIENTO SEGURO (TERMINAL)
    # ------------------------------------------------------------------

    def _start_terminal_pairing_thread(self):
        """Inicia un hilo daemon que escucha la terminal para confirmar el pairing."""
        thread = threading.Thread(target=self._terminal_pairing_loop, daemon=True)
        thread.start()

    def _terminal_pairing_loop(self):
        """
        Loop que espera solicitudes de pairing y las presenta en la terminal
        del servidor para que el administrador las apruebe o rechace.
        """
        while self.allowed_user_id is None:
            if self.pending_pairing is None:
                import time as _time
                _time.sleep(0.5)
                continue

            pending = self.pending_pairing
            print("\n" + "=" * 55)
            print("   SOLICITUD DE EMPAREJAMIENTO")
            print("=" * 55)
            print(f"  Nombre:  {pending['user_name']}")
            print(f"  User ID: {pending['user_id']}")
            print(f"  Chat ID: {pending['chat_id']}")
            print("=" * 55)
            print()

            try:
                response = input("Autorizar este usuario? (s/n): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                break

            if response in ("s", "si", "y", "yes"):
                user_id = pending['user_id']
                self.allowed_user_id = user_id
                self._save_pairing(user_id)
                self.pending_pairing = None

                print(f"\n[OK] Usuario {pending['user_name']} (ID: {user_id}) emparejado.\n")
                logger.info(f"Usuario emparejado via terminal: {user_id} ({pending['user_name']})")

                # Notificar al usuario por Telegram (HTTP directo, thread-safe)
                self._send_telegram_message(
                    pending['chat_id'],
                    "Emparejamiento autorizado. Envia /start para continuar."
                )
            else:
                print("\n[RECHAZADO] Solicitud de pairing rechazada.\n")
                logger.warning(f"Pairing rechazado para: {pending['user_id']}")
                self.pending_pairing = None

    def _send_telegram_message(self, chat_id: int, text: str):
        """
        Envia un mensaje de Telegram via HTTP directo.

        Se usa desde hilos secundarios donde asyncio no esta disponible.
        """
        import urllib.request
        import urllib.parse

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": text,
        }).encode("utf-8")

        try:
            req = urllib.request.Request(url, data=data)
            urllib.request.urlopen(req, timeout=10)
            logger.debug(f"Mensaje de pairing enviado a chat_id: {chat_id}")
        except Exception as e:
            logger.error(f"Error enviando mensaje de Telegram: {e}")

    # ------------------------------------------------------------------
    # WIZARD DE ONBOARDING (6 PASOS)
    # ------------------------------------------------------------------

    def _needs_onboarding(self) -> bool:
        """Retorna True si el asistente aun no ha sido configurado."""
        return not self.assistant.soul.is_onboarded

    async def _start_onboarding(self, update: Update):
        """Inicia el wizard de configuracion inicial del asistente."""
        self.onboarding_state = ONBOARDING_NAME
        self.onboarding_data = {}

        await update.message.reply_text(
            "**Configuracion Inicial del Asistente**\n\n"
            "Se realizaran unas preguntas para personalizar el asistente.\n\n"
            "Paso 1/6: **Nombre del asistente**\n\n"
            "Escribe el nombre:",
            parse_mode="Markdown",
        )
        logger.info("Onboarding wizard iniciado.")

    async def _handle_onboarding(self, update: Update, text: str):
        """
        Procesa las respuestas del wizard de onboarding paso a paso.

        Pasos:
          1. Nombre del asistente
          2. Genero (mujer/hombre/neutro)
          3. Personalidad (texto libre)
          4. Comportamiento (texto libre)
          5. Nivel de etica (1-10)
          6. Nombre del usuario
        """

        if self.onboarding_state == ONBOARDING_NAME:
            self.onboarding_data["name"] = text.strip()
            self.onboarding_state = ONBOARDING_GENDER
            await update.message.reply_text(
                f"Nombre: **{text.strip()}**\n\n"
                "Paso 2/6: **Genero del asistente**\n\n"
                "Define como se expresa (femenino, masculino, neutro).\n\n"
                "Escribe: `mujer`, `hombre` o `neutro`",
                parse_mode="Markdown",
            )

        elif self.onboarding_state == ONBOARDING_GENDER:
            gender = text.strip().lower()
            if gender not in ("mujer", "hombre", "neutro"):
                await update.message.reply_text(
                    "Valor no valido. Escribe `mujer`, `hombre` o `neutro`:",
                    parse_mode="Markdown",
                )
                return
            self.onboarding_data["gender"] = gender
            gender_labels = {"mujer": "Femenino", "hombre": "Masculino", "neutro": "Neutro"}
            self.onboarding_state = ONBOARDING_PERSONALITY
            await update.message.reply_text(
                f"Genero: **{gender_labels[gender]}**\n\n"
                "Paso 3/6: **Personalidad**\n\n"
                "Describe como quieres que sea. Ejemplos:\n"
                "- Directa y sin rodeos\n"
                "- Amable y paciente\n"
                "- Profesional y formal\n"
                "- Curiosa y entusiasta\n\n"
                "Texto libre:",
                parse_mode="Markdown",
            )

        elif self.onboarding_state == ONBOARDING_PERSONALITY:
            self.onboarding_data["personality"] = text.strip()
            self.onboarding_state = ONBOARDING_BEHAVIOR
            await update.message.reply_text(
                "Personalidad guardada.\n\n"
                "Paso 4/6: **Comportamiento**\n\n"
                "Describe las reglas de comportamiento. Ejemplos:\n"
                "- Que sea proactiva y sugiera mejoras\n"
                "- Que solo responda lo que le pregunto\n"
                "- Que explique sus razonamientos\n"
                "- Que sea concisa y vaya al grano\n\n"
                "Escribe las instrucciones:",
                parse_mode="Markdown",
            )

        elif self.onboarding_state == ONBOARDING_BEHAVIOR:
            self.onboarding_data["behavior"] = text.strip()
            self.onboarding_state = ONBOARDING_ETHICS
            await update.message.reply_text(
                "Comportamiento guardado.\n\n"
                "Paso 5/6: **Nivel de etica (1-10)**\n\n"
                "1 = Sin restricciones, ejecuta todo\n"
                "3 = Pocas restricciones, menciona riesgos\n"
                "5 = Balance equilibrado\n"
                "7 = Etica alta, cuestiona lo dudoso\n"
                "10 = Etica maxima, muy restrictivo\n\n"
                "Escribe un numero del 1 al 10:",
                parse_mode="Markdown",
            )

        elif self.onboarding_state == ONBOARDING_ETHICS:
            try:
                level = int(text.strip())
                if level < 1 or level > 10:
                    raise ValueError()
            except ValueError:
                await update.message.reply_text(
                    "Valor no valido. Escribe un numero del 1 al 10:"
                )
                return

            self.onboarding_data["ethics"] = level
            self.onboarding_state = ONBOARDING_USER_NAME
            await update.message.reply_text(
                f"Etica: **{level}/10**\n\n"
                "Paso 6/6: **Tu nombre**\n\n"
                "Como quieres que te llame el asistente?\n"
                "Tu nombre, apodo, alias... lo que prefieras:",
                parse_mode="Markdown",
            )

        elif self.onboarding_state == ONBOARDING_USER_NAME:
            user_call_name = text.strip()
            self.onboarding_data["user_call_name"] = user_call_name

            # Guardar configuracion en el Soul
            name = self.onboarding_data["name"]
            self.assistant.soul.configure_identity(
                name=name,
                gender=self.onboarding_data["gender"],
                personality=self.onboarding_data["personality"],
                behavior=self.onboarding_data["behavior"],
                ethics_level=self.onboarding_data["ethics"],
                user_call_name=user_call_name,
            )

            # Actualizar nombre del asistente
            self.assistant.name = name
            ethics_level = self.onboarding_data["ethics"]

            self.onboarding_state = ONBOARDING_NONE
            self.onboarding_data = {}

            await update.message.reply_text(
                f"**{name} configurado correctamente.**\n\n"
                f"Nombre: **{name}**\n"
                f"Etica: **{ethics_level}/10**\n"
                f"Te llamara: **{user_call_name}**\n\n"
                "Ahora configura tu frase secreta de autenticacion:\n"
                "`/setup tu_frase_secreta_aqui`",
                parse_mode="Markdown",
            )
            logger.info(f"Onboarding completado: {name} -> usuario: {user_call_name}")

    # ------------------------------------------------------------------
    # HANDLERS DE COMANDOS
    # ------------------------------------------------------------------

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Maneja el comando /start.

        Flujo:
          1. Si no hay pairing -> solicita autorizacion por terminal.
          2. Si necesita onboarding -> inicia el wizard.
          3. Si falta autenticacion -> pide /setup.
          4. Si esta todo listo -> saluda.
        """
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "Usuario"

        # Sin pairing: solicitar emparejamiento
        if self.allowed_user_id is None:
            self.pending_pairing = {
                "user_id": user_id,
                "user_name": user_name,
                "chat_id": update.effective_chat.id,
            }
            await update.message.reply_text(
                "Solicitud de emparejamiento enviada.\n\n"
                "El administrador debe autorizar tu acceso desde el servidor.\n"
                "Espera la confirmacion...",
            )
            logger.info(f"Solicitud de pairing recibida: {user_id} ({user_name})")
            return

        # Usuario no autorizado
        if user_id != self.allowed_user_id:
            await update.message.reply_text("Acceso denegado.")
            logger.warning(f"Acceso denegado a usuario: {user_id}")
            return

        # Onboarding pendiente
        if self._needs_onboarding():
            await self._start_onboarding(update)
            return

        # Autenticacion no configurada
        if not self.auth.is_configured:
            await update.message.reply_text(
                f"Hola {user_name}.\n\n"
                "Emparejamiento correcto.\n"
                "Configura tu autenticacion:\n"
                "`/setup tu_frase_secreta_aqui`",
                parse_mode="Markdown",
            )
        elif not self.auth.is_authenticated:
            await update.message.reply_text(
                "Identificate. Envia tu frase secreta."
            )
        else:
            await update.message.reply_text(
                f"Sesion activa, {user_name}. En que puedo ayudarte?"
            )

    async def handle_setup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Maneja el comando /setup para configurar la autenticacion.

        Requiere: pairing + onboarding completados.
        Uso: /setup <frase_secreta>
        """
        user_id = update.effective_user.id

        if self.allowed_user_id is None:
            await update.message.reply_text(
                "Primero necesitas emparejarte. Envia /start",
            )
            return

        if user_id != self.allowed_user_id:
            await update.message.reply_text("Acceso denegado.")
            return

        if self._needs_onboarding():
            await update.message.reply_text(
                "Primero necesitas configurar tu asistente. Envia /start",
            )
            return

        if self.auth.is_configured:
            await update.message.reply_text(
                "La autenticacion ya esta configurada. "
                "Contacta al administrador para resetearla."
            )
            return

        if not context.args:
            await update.message.reply_text(
                "Uso: `/setup tu_frase_secreta_aqui`",
                parse_mode="Markdown",
            )
            return

        secret = " ".join(context.args)

        # SEC-05: Borrar el mensaje que contiene la passphrase del historial
        try:
            await update.message.delete()
        except Exception:
            # Si no tiene permisos para borrar, continuar igual
            logger.warning("No se pudo borrar el mensaje /setup del historial.")

        self.auth.setup("passphrase", secret)
        self.auth.authenticate(secret)

        name = self.assistant.name
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=(
                f"Autenticacion configurada.\n\n"
                f"**{name}** esta listo para ayudarte.\n"
                "En que necesitas ayuda?"
            ),
            parse_mode="Markdown",
        )
        logger.info("Autenticacion configurada exitosamente.")

    # ------------------------------------------------------------------
    # HANDLERS DE MENSAJES
    # ------------------------------------------------------------------

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Maneja los mensajes de texto del usuario.

        Flujo:
          1. Verifica pairing y autorizacion.
          2. Aplica rate limiting.
          3. Procesa onboarding si esta activo.
          4. Verifica autenticacion.
          5. Envia al orquestador y retorna la respuesta.
        """
        user_id = update.effective_user.id

        # Verificar autorizacion
        if self.allowed_user_id is None or user_id != self.allowed_user_id:
            return

        # Rate limiting
        if self._is_rate_limited(user_id):
            await update.message.reply_text(
                "Demasiados mensajes. Espera unos segundos."
            )
            return

        text = update.message.text

        # Onboarding activo: procesar en el wizard
        if self.onboarding_state != ONBOARDING_NONE:
            await self._handle_onboarding(update, text)
            return

        # Onboarding pendiente
        if self._needs_onboarding():
            await self._start_onboarding(update)
            return

        # Flujo de autenticacion
        if not self.auth.is_authenticated:
            # Verificar timeout de sesion
            self.auth._check_session_timeout()

            if not self.auth.is_configured:
                await update.message.reply_text(
                    "Primero configura tu autenticacion con `/setup tu_frase_secreta`",
                    parse_mode="Markdown",
                )
                return

            # Verificar bloqueo por brute-force
            if self.auth.is_locked_out:
                remaining = int(self.auth._lockout_until - time.time())
                await update.message.reply_text(
                    f"Autenticacion bloqueada. Intenta en {remaining // 60} minutos."
                )
                return

            if self.auth.authenticate(text):
                await update.message.reply_text(
                    f"Autenticado. Soy **{self.assistant.name}**, listo para ayudarte.",
                    parse_mode="Markdown",
                )
            else:
                attempts_left = max(0, 5 - self.auth._failed_attempts)
                if attempts_left > 0:
                    await update.message.reply_text(
                        f"Frase incorrecta. Quedan {attempts_left} intentos."
                    )
                else:
                    await update.message.reply_text(
                        "Demasiados intentos fallidos. Autenticacion bloqueada por 15 minutos."
                    )
            return

        # Indicador de escritura mientras procesa
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action="typing",
        )

        # Procesar con el orquestador
        self.auth.refresh_activity()  # Actualizar timestamp de sesion
        try:
            response = await self.assistant.process(text)
            
            # --- Envio de media adjunto desde el LLM ---
            # Parsear [IMAGE: ruta] y [FILE: ruta]
            images_to_send = re.findall(r'\[IMAGE:\s*(.+?)\]', response)
            files_to_send = re.findall(r'\[FILE:\s*(.+?)\]', response)
            
            # Limpiar etiquetas del texto final
            response = re.sub(r'\[IMAGE:\s*.+?\]', '', response).strip()
            response = re.sub(r'\[FILE:\s*.+?\]', '', response).strip()
            
            # Enviar imagenes
            for img_path in images_to_send:
                p = Path(img_path.strip())
                if p.exists() and p.is_file():
                    try:
                        await context.bot.send_photo(chat_id=update.effective_chat.id, photo=open(p, 'rb'))
                    except Exception as e:
                        logger.error(f"Error enviando foto {p}: {e}")
                        response += f"\n*(Error enviando la imagen {p.name})*"
            
            # Enviar archivos
            for file_path in files_to_send:
                p = Path(file_path.strip())
                if p.exists() and p.is_file():
                    try:
                        await context.bot.send_document(chat_id=update.effective_chat.id, document=open(p, 'rb'))
                    except Exception as e:
                        logger.error(f"Error enviando documento {p}: {e}")
                        response += f"\n*(Error enviando el archivo {p.name})*"
                        
            if not response:
                return

            # Telegram tiene limite de 4096 caracteres por mensaje
            if len(response) > 4000:
                chunks = [response[i:i+4000] for i in range(0, len(response), 4000)]
                for chunk in chunks:
                    try:
                        await update.message.reply_text(chunk, parse_mode="Markdown")
                    except Exception:
                        await update.message.reply_text(chunk)
            else:
                try:
                    await update.message.reply_text(response, parse_mode="Markdown")
                except Exception:
                    # Fallback a texto plano si el Markdown falla
                    await update.message.reply_text(response)
        except Exception as e:
            # SEC-12: Mensaje generico al usuario, detalle solo en logs
            logger.error(f"Error procesando mensaje: {e}")
            await update.message.reply_text(
                "Error interno. Intenta de nuevo."
            )

    async def handle_media(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Maneja archivos multimedia (imagenes y documentos).

        Descarga el archivo, lo guarda en el vault y lo procesa
        con el orquestador.
        """
        if not self.auth.is_authenticated:
            await update.message.reply_text("Identificate primero.")
            return

        if update.message.photo:
            file = await update.message.photo[-1].get_file()
            file_bytes = await file.download_as_bytearray()
            caption = update.message.caption or "Imagen recibida"
            response = await self.assistant.process_with_media(
                caption, bytes(file_bytes)
            )
            await update.message.reply_text(response)
        elif update.message.document:
            file = await update.message.document.get_file()
            file_bytes = await file.download_as_bytearray()
            caption = update.message.caption or f"Documento: {update.message.document.file_name}"
            response = await self.assistant.process_with_media(
                caption, bytes(file_bytes)
            )
            await update.message.reply_text(response)

    async def handle_logout(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cierra la sesion activa del usuario."""
        if update.effective_user.id != self.allowed_user_id:
            return

        self.auth.logout()
        self.assistant.shutdown()
        await update.message.reply_text("Sesion cerrada.")
        logger.info("Usuario cerro sesion.")

    async def handle_reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Resetea el bot completamente.

        Requiere confirmacion explicita: /reset CONFIRMAR
        Borra los archivos de pairing, autenticacion y onboarding.
        """
        if self.allowed_user_id is not None and update.effective_user.id != self.allowed_user_id:
            return

        # Requiere confirmacion explicita
        if not context.args or context.args[0] != "CONFIRMAR":
            await update.message.reply_text(
                "**Resetear el bot completamente?**\n\n"
                "Esto borrara:\n"
                "- Emparejamiento\n"
                "- Autenticacion\n"
                "- Configuracion del asistente (onboarding)\n\n"
                "Para confirmar, escribe:\n"
                "`/reset CONFIRMAR`",
                parse_mode="Markdown",
            )
            return

        # Borrar archivos de estado
        files_to_delete = [".pairing", ".auth", ".onboarded"]
        for fname in files_to_delete:
            fpath = self.vault_path / fname if self.vault_path else None
            if fpath and fpath.exists():
                fpath.unlink()

        # Resetear estado interno
        self.allowed_user_id = None
        self.pending_pairing = None
        self.onboarding_state = ONBOARDING_NONE
        self.onboarding_data = {}
        self.auth.logout()

        await update.message.reply_text(
            "**Bot reseteado completamente.**\n\n"
            "Envia /start para comenzar de nuevo.",
            parse_mode="Markdown",
        )
        logger.warning("Bot reseteado por el usuario.")

        # Reiniciar hilo de pairing
        self._start_terminal_pairing_thread()

    async def handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Retorna el estado actual del asistente."""
        if update.effective_user.id != self.allowed_user_id:
            return

        if not self.auth.is_authenticated:
            await update.message.reply_text("No autenticado.")
            return

        status = await self.assistant.get_status()
        await update.message.reply_text(status, parse_mode="Markdown")

    # ------------------------------------------------------------------
    # PERSISTENCIA DE PAIRING
    # ------------------------------------------------------------------

    def _load_pairing(self) -> int | None:
        """
        Carga el user ID emparejado desde el vault.

        Returns:
            ID del usuario emparejado, o None si no existe.
        """
        if self.pairing_file and self.pairing_file.exists():
            try:
                uid = int(self.pairing_file.read_text(encoding="utf-8").strip())
                logger.info(f"Pairing cargado desde vault: {uid}")
                return uid
            except (ValueError, OSError) as e:
                logger.warning(f"Error cargando pairing: {e}")
        return None

    def _save_pairing(self, user_id: int):
        """
        Persiste el user ID emparejado en el vault.

        Args:
            user_id: ID del usuario de Telegram a guardar.
        """
        if self.pairing_file:
            try:
                self.pairing_file.parent.mkdir(parents=True, exist_ok=True)
                self.pairing_file.write_text(str(user_id), encoding="utf-8")
                logger.info(f"Pairing guardado en vault: {user_id}")
            except OSError as e:
                logger.error(f"Error guardando pairing: {e}")

    # ------------------------------------------------------------------
    # EJECUCION
    # ------------------------------------------------------------------

    def run(self):
        """
        Inicia el bot de Telegram en modo polling.

        Si no existe un usuario emparejado, inicia ademas un hilo
        de escucha en la terminal para autorizar el primer acceso.
        """
        if self.allowed_user_id is None:
            self._start_terminal_pairing_thread()

        logger.info("Telegram Bot iniciado. Esperando mensajes...")
        self.app.run_polling(
            drop_pending_updates=True,
            allowed_updates=["message", "callback_query"],
        )
