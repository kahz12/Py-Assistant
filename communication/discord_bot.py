"""
communication/discord_bot.py -- Canal secundario Discord (Feature 10).

Bot de Discord paralelo al canal de Telegram. Comparte el mismo
Assistant, LaneQueue y UserRegistry que el bot de Telegram.

Requiere:
    pip install discord.py>=2.3
    DISCORD_BOT_TOKEN en .env
    DISCORD_ALLOWED_GUILD_ID en .env (opcional, para limitar a un servidor)

Uso en main.py:
    discord_iface = DiscordInterface(bot_token, assistant, lane_queue, user_registry)
    asyncio.create_task(discord_iface.start())   # En el event loop del bot
"""
from loguru import logger

try:
    import discord
    from discord.ext import commands
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False


class DiscordInterface:
    """
    Interfaz Discord del asistente.

    Comparte el mismo `Assistant` y `LaneQueue` que el bot de Telegram,
    garantizando procesamiento serial y consistencia de contexto.

    Atributos:
        _token: Token del bot de Discord.
        _assistant: Orquestador principal del asistente.
        _lane_queue: Cola serial compartida.
        _user_registry: Registro de usuarios autorizados.
        _allowed_guild_id: ID del servidor permitido (None = todos).
        _bot: Instancia de discord.ext.commands.Bot.
    """

    def __init__(self, token: str, assistant, lane_queue, user_registry=None, allowed_guild_id: int = None):
        if not DISCORD_AVAILABLE:
            logger.warning(
                "[Discord] discord.py no instalado. "
                "Instala con: pip install 'discord.py>=2.3'"
            )
            self._bot = None
            return

        self._token = token
        self._assistant = assistant
        self._lane_queue = lane_queue
        self._user_registry = user_registry
        self._allowed_guild_id = allowed_guild_id

        intents = discord.Intents.default()
        intents.message_content = True
        self._bot = commands.Bot(command_prefix="!", intents=intents)
        self._register_events()
        logger.info("[Discord] DiscordInterface inicializado.")

    def _register_events(self):
        """Registra eventos del bot de Discord."""
        bot = self._bot

        @bot.event
        async def on_ready():
            logger.info(f"[Discord] Bot conectado como: {bot.user} (ID: {bot.user.id})")
            if self._allowed_guild_id:
                logger.info(f"[Discord] Limitado al servidor: {self._allowed_guild_id}")

        @bot.event
        async def on_message(message: discord.Message):
            # Ignorar mensajes propios del bot
            if message.author == bot.user:
                return

            # Filtrar por servidor si esta configurado
            if self._allowed_guild_id and message.guild and message.guild.id != self._allowed_guild_id:
                return

            # Solo mensajes de texto con mencion al bot o en DM
            is_dm = isinstance(message.channel, discord.DMChannel)
            is_mention = bot.user in message.mentions
            if not (is_dm or is_mention):
                return

            user_id = message.author.id
            text = message.content.replace(f"<@{bot.user.id}>", "").strip()

            if not text:
                return

            # Verificar autorizacion si hay UserRegistry
            if self._user_registry:
                if not self._user_registry.is_allowed(user_id, min_role="viewer"):
                    await message.reply(
                        "No tienes acceso a este asistente. "
                        "Contacta al administrador para que te registre."
                    )
                    logger.warning(f"[Discord] Acceso denegado: {user_id} ({message.author.name})")
                    return

            logger.info(f"[Discord] Mensaje de {message.author.name} ({user_id}): {text[:60]}")

            # Indicador de escritura
            async with message.channel.typing():
                discord_msg = message  # Capturar para el closure

                async def _process_and_reply(msg_text: str):
                    """Callback para procesar y responder en Discord."""
                    try:
                        response = await self._assistant.process(msg_text)
                        if response:
                            # Discord tiene limite de 2000 caracteres por mensaje
                            if len(response) <= 2000:
                                await discord_msg.reply(response)
                            else:
                                # Dividir en chunks de 1900 chars
                                chunks = [response[i:i+1900] for i in range(0, len(response), 1900)]
                                for i, chunk in enumerate(chunks):
                                    if i == 0:
                                        await discord_msg.reply(chunk)
                                    else:
                                        await discord_msg.channel.send(chunk)
                    except Exception as e:
                        logger.error(f"[Discord] Error procesando mensaje: {e}")
                        await discord_msg.reply("Error procesando tu mensaje. Intenta de nuevo.")

                await self._lane_queue.enqueue(
                    lane_id=f"discord_{user_id}",
                    payload=text,
                    callback=_process_and_reply,
                )

        @bot.command(name="status")
        async def cmd_status(ctx: commands.Context):
            """Comando !status — muestra el estado del asistente."""
            user_id = ctx.author.id
            if self._user_registry and not self._user_registry.is_admin(user_id):
                await ctx.send("Solo los administradores pueden usar este comando.")
                return
            lanes = self._lane_queue.all_lanes_status() if self._lane_queue else {}
            lanes_text = "\n".join(
                f"  Lane {lid}: {info['pending']} pendientes, {'activo' if info['active'] else 'inactivo'}"
                for lid, info in lanes.items()
            ) or "  Sin lanes activos."
            await ctx.send(f"**Estado del asistente:**\n{lanes_text}")

        @bot.command(name="adduser")
        async def cmd_adduser(ctx: commands.Context, member: discord.Member, role: str = "viewer"):
            """Comando !adduser @usuario [admin|viewer] — registra un usuario (solo admins)."""
            if self._user_registry and not self._user_registry.is_admin(ctx.author.id):
                await ctx.send("Solo los administradores pueden registrar usuarios.")
                return
            if role not in ("admin", "viewer"):
                await ctx.send("Rol invalido. Usa `admin` o `viewer`.")
                return
            ok = self._user_registry.add_user(
                user_id=member.id, username=str(member.name), role=role
            ) if self._user_registry else False
            if ok:
                await ctx.send(f"Usuario **{member.name}** registrado como `{role}`.")
            else:
                await ctx.send("Error al registrar usuario.")

    async def start(self):
        """Arranca el bot de Discord (debe ejecutarse en un asyncio task)."""
        if not self._bot:
            return
        try:
            await self._bot.start(self._token)
        except Exception as e:
            logger.error(f"[Discord] Error al iniciar el bot: {e}")

    async def close(self):
        """Cierra el bot de Discord de forma limpia."""
        if self._bot:
            await self._bot.close()
            logger.info("[Discord] Bot cerrado.")
