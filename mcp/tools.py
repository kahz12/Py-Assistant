"""
mcp/tools.py -- Registro de herramientas MCP para el asistente.

Contiene todas las funciones invocables por el LLM via function calling.
Las herramientas estan organizadas en categorias:

  1. Fecha y hora         -- obtener_fecha_hora
  2. Memoria (vault)      -- guardar_nota, guardar_hecho, buscar_notas, listar_notas
  3. Sistema de archivos  -- listar_directorio, leer_archivo, escribir_archivo
  4. Ejecucion            -- ejecutar_comando
  5. Web                  -- buscar_web, extraer_texto_web
  6. Sistema              -- info_sistema, abrir_aplicacion
  7. Email                -- leer_emails, enviar_email

Las operaciones de filesystem respetan las politicas definidas en
security_config.yaml (allowed_read, allowed_write, blocked_paths).
"""
import os
import re
import shlex
import subprocess
from datetime import datetime
from pathlib import Path
from loguru import logger


def register_all_tools(mcp, vault_path: Path, security_config: dict = None, llm_engine=None):
    """
    Registra todas las herramientas MCP en el router.

    Carga las politicas de seguridad del filesystem desde security_config
    y las aplica a las herramientas de lectura/escritura de archivos.

    Args:
        mcp: Instancia de MCPRouter donde se registran las herramientas.
        vault_path: Ruta al directorio del vault para operaciones de memoria.
        security_config: Diccionario con politicas de seguridad (opcional).
        llm_engine: Instancia del motor LLM (para herramientas de analisis de texto).
    """
    # Referencia al LLM engine para skills que lo necesitan
    _llm_ref = {"engine": llm_engine}

    def _get_llm_ref():
        return _llm_ref.get("engine")

    # Cargar politicas de filesystem desde security_config
    fs_config = security_config.get("filesystem", {}) if security_config else {}
    allowed_read = fs_config.get("allowed_read_paths", ["/home", "/tmp"])
    allowed_write = fs_config.get("allowed_write_paths", ["/tmp"])

    # Lista extendida de rutas bloqueadas (SEC-07)
    default_blocked = [
        "/etc", "/root", "/sys", "/proc", "/dev",
        "/boot", "/var", "/run", "/snap", "/usr/sbin",
    ]
    blocked_paths = fs_config.get("blocked_paths", default_blocked)

    # ------------------------------------------------------------------
    # 1. FECHA Y HORA
    # ------------------------------------------------------------------

    @mcp.register(
        name="obtener_fecha_hora",
        description="Obtiene la fecha y hora actual del sistema en español.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def obtener_fecha_hora():
        """Retorna fecha y hora actual con nombres en español."""
        now = datetime.now()
        dias = {
            "Monday": "lunes", "Tuesday": "martes", "Wednesday": "miercoles",
            "Thursday": "jueves", "Friday": "viernes", "Saturday": "sabado", "Sunday": "domingo",
        }
        meses = {
            "January": "enero", "February": "febrero", "March": "marzo",
            "April": "abril", "May": "mayo", "June": "junio",
            "July": "julio", "August": "agosto", "September": "septiembre",
            "October": "octubre", "November": "noviembre", "December": "diciembre",
        }
        dia = dias.get(now.strftime('%A'), now.strftime('%A'))
        mes = meses.get(now.strftime('%B'), now.strftime('%B'))
        return (
            f"Fecha: {dia} {now.day} de {mes} de {now.year}\n"
            f"Hora: {now.strftime('%H:%M:%S')}\n"
            f"Timestamp: {now.isoformat()}"
        )

    # ------------------------------------------------------------------
    # 2. MEMORIA -- GUARDAR
    # ------------------------------------------------------------------

    @mcp.register(
        name="guardar_nota",
        description="Guarda una nota o informacion importante en la memoria persistente del vault.",
        parameters={
            "type": "object",
            "properties": {
                "titulo": {
                    "type": "string",
                    "description": "Titulo breve para la nota",
                },
                "contenido": {
                    "type": "string",
                    "description": "Contenido completo de la nota",
                },
            },
            "required": ["titulo", "contenido"],
        },
    )
    def guardar_nota(titulo: str, contenido: str):
        """Crea un archivo Markdown con la nota en el directorio notes/ del vault."""
        notes_dir = vault_path / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = titulo.lower().replace(" ", "_")[:30]
        filename = f"{timestamp}_{slug}.md"
        filepath = notes_dir / filename
        filepath.write_text(
            f"# {titulo}\n\n{contenido}\n\n---\n_Guardado: {datetime.now().strftime('%Y-%m-%d %H:%M')}_\n",
            encoding="utf-8",
        )
        logger.info(f"[MCP] Nota guardada: {filename}")
        return f"Nota '{titulo}' guardada en {filename}"

    @mcp.register(
        name="guardar_hecho",
        description="Guarda un hecho importante sobre el usuario en la memoria a largo plazo.",
        parameters={
            "type": "object",
            "properties": {
                "hecho": {
                    "type": "string",
                    "description": "El hecho a recordar sobre el usuario",
                },
            },
            "required": ["hecho"],
        },
    )
    def guardar_hecho(hecho: str):
        """Agrega un hecho al archivo facts.md del vault."""
        facts_file = vault_path / "facts.md"
        existing = facts_file.read_text(encoding="utf-8") if facts_file.exists() else "# Hechos Importantes\n"
        existing += f"\n- {hecho}"
        facts_file.write_text(existing, encoding="utf-8")
        logger.info(f"[MCP] Hecho guardado: {hecho[:50]}")
        return f"Hecho guardado: {hecho}"

    # ------------------------------------------------------------------
    # 3. MEMORIA -- BUSCAR
    # ------------------------------------------------------------------

    @mcp.register(
        name="buscar_notas",
        description="Busca en las notas guardadas del vault. Retorna las notas que contienen el texto buscado.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Texto a buscar en las notas",
                },
            },
            "required": ["query"],
        },
    )
    def buscar_notas(query: str):
        """Busca coincidencias de texto en todas las notas del vault."""
        notes_dir = vault_path / "notes"
        if not notes_dir.exists():
            return "No hay notas guardadas."
        results = []
        for note_file in sorted(notes_dir.glob("*.md"), reverse=True):
            content = note_file.read_text(encoding="utf-8")
            if query.lower() in content.lower():
                results.append(f"**{note_file.stem}**\n{content[:300]}")
        if not results:
            return f"No se encontraron notas con '{query}'."
        return f"Encontradas {len(results)} notas:\n\n" + "\n\n---\n\n".join(results[:5])

    @mcp.register(
        name="listar_notas",
        description="Lista todas las notas guardadas en el vault.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def listar_notas():
        """Lista todos los archivos .md del directorio notes/ del vault."""
        notes_dir = vault_path / "notes"
        if not notes_dir.exists():
            return "No hay notas guardadas."
        notes = sorted(notes_dir.glob("*.md"), reverse=True)
        if not notes:
            return "No hay notas guardadas."
        items = [f"  - {n.stem}" for n in notes[:20]]
        return f"{len(notes)} notas guardadas:\n\n" + "\n".join(items)

    # ------------------------------------------------------------------
    # 4. SISTEMA DE ARCHIVOS
    # ------------------------------------------------------------------

    def _is_path_allowed(filepath: str, mode: str = "read") -> bool:
        """
        Verifica si una ruta esta permitida segun las politicas de seguridad.

        Validaciones:
          1. Resuelve la ruta absoluta (maneja .., rutas relativas).
          2. Verifica contra la lista de rutas bloqueadas.
          3. Detecta symlinks que apuntan fuera de las rutas permitidas.
          4. Verifica que la ruta este dentro de las rutas permitidas.

        Args:
            filepath: Ruta a verificar.
            mode: 'read' o 'write'.

        Returns:
            True si la ruta esta permitida.
        """
        path = Path(filepath)
        resolved = str(path.resolve())

        # Verificar contra rutas bloqueadas
        for blocked in blocked_paths:
            if resolved.startswith(blocked):
                return False

        # Detectar symlinks que apuntan fuera de rutas permitidas (SEC-07)
        if path.is_symlink():
            target = str(path.resolve())
            allowed = allowed_read if mode == "read" else allowed_write
            if not any(target.startswith(a) for a in allowed):
                logger.warning(f"Symlink bloqueado: {filepath} -> {target}")
                return False

        allowed = allowed_read if mode == "read" else allowed_write
        return any(resolved.startswith(a) for a in allowed)

    @mcp.register(
        name="listar_directorio",
        description="Lista los archivos y carpetas de un directorio. Solo funciona en rutas permitidas.",
        parameters={
            "type": "object",
            "properties": {
                "ruta": {
                    "type": "string",
                    "description": "Ruta absoluta del directorio a listar",
                },
                "limite": {
                    "type": "integer",
                    "description": "Maximo numero de elementos a retornar (default: 50)"
                },
                "offset": {
                    "type": "integer",
                    "description": "Elementos a omitir del inicio para paginacion (default: 0)"
                }
            },
            "required": ["ruta"],
        },
    )
    def listar_directorio(ruta: str, limite: int = 50, offset: int = 0):
        """Lista el contenido de un directorio respetando las politicas de acceso."""
        if not _is_path_allowed(ruta, "read"):
            return f"Acceso denegado a: {ruta}"
        path = Path(ruta)
        if not path.exists():
            return f"No existe: {ruta}"
        if not path.is_dir():
            return f"No es un directorio: {ruta}"
            
        items = []
        for item in sorted(path.iterdir()):
            prefix = "[DIR]" if item.is_dir() else "[FILE]"
            size = ""
            if item.is_file():
                s = item.stat().st_size
                size = f" ({s:,} bytes)" if s < 1_000_000 else f" ({s/1_000_000:.1f} MB)"
            items.append(f"{prefix} {item.name}{size}")
            
        if not items:
            return f"{ruta} esta vacio."
            
        total = len(items)
        sliced_items = items[offset:offset + limite]
        response = f"{ruta} ({total} items encontrados):\nMostrando {len(sliced_items)} items desde offset {offset}:\n\n" + "\n".join(sliced_items)
        
        if total > offset + limite:
            response += f"\n\n[Hay mas archivos. Usa offset={offset+limite} y limite={limite} para ver la siguiente pagina]"
            
        return response

    @mcp.register(
        name="leer_archivo",
        description="Lee el contenido de un archivo de texto. Solo funciona en rutas permitidas y archivos menores a 50KB.",
        parameters={
            "type": "object",
            "properties": {
                "ruta": {
                    "type": "string",
                    "description": "Ruta absoluta del archivo a leer",
                },
            },
            "required": ["ruta"],
        },
    )
    def leer_archivo(ruta: str):
        """Lee un archivo de texto dentro de las rutas permitidas. Limite: 50KB."""
        if not _is_path_allowed(ruta, "read"):
            return f"Acceso denegado a: {ruta}"
        path = Path(ruta)
        if not path.exists():
            return f"No existe: {ruta}"
        if not path.is_file():
            return f"No es un archivo: {ruta}"
        if path.stat().st_size > 50_000:
            return f"Archivo demasiado grande ({path.stat().st_size:,} bytes). Maximo: 50KB."
        try:
            content = path.read_text(encoding="utf-8")
            return f"**{path.name}**:\n<datos_externos>\n{content}\n</datos_externos>"
        except UnicodeDecodeError:
            return f"No es un archivo de texto: {path.name}"

    @mcp.register(
        name="escribir_archivo",
        description="Escribe contenido en un archivo. Solo funciona en rutas permitidas para escritura.",
        parameters={
            "type": "object",
            "properties": {
                "ruta": {
                    "type": "string",
                    "description": "Ruta absoluta del archivo a escribir",
                },
                "contenido": {
                    "type": "string",
                    "description": "Contenido a escribir en el archivo",
                },
            },
            "required": ["ruta", "contenido"],
        },
    )
    def escribir_archivo(ruta: str, contenido: str):
        """Escribe en un archivo dentro de las rutas permitidas para escritura."""
        if not _is_path_allowed(ruta, "write"):
            return f"Sin permiso de escritura en: {ruta}"
        path = Path(ruta)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contenido, encoding="utf-8")
        logger.info(f"[MCP] Archivo escrito: {ruta}")
        return f"Archivo escrito: {ruta} ({len(contenido)} caracteres)"

    # ------------------------------------------------------------------
    # 5. EJECUCION DE COMANDOS
    # ------------------------------------------------------------------

    @mcp.register(
        name="ejecutar_comando",
        description="Ejecuta un comando en la terminal del sistema. Timeout de 30 segundos.",
        parameters={
            "type": "object",
            "properties": {
                "comando": {
                    "type": "string",
                    "description": "Comando a ejecutar (ej: 'ls -la', 'df -h', 'uname -a')",
                },
            },
            "required": ["comando"],
        },
    )
    def ejecutar_comando(comando: str):
        """
        Ejecuta un comando en el sistema con multiples capas de seguridad.

        Protecciones (SEC-02):
          - Bloqueo de operadores de shell (;, &&, ||, |, backticks, $()).
          - Lista de comandos peligrosos ampliada.
          - Ejecucion sin shell=True (via shlex.split).
          - Timeout de 30 segundos.
        """
        # 1. Bloquear operadores de shell que permiten encadenamiento
        shell_operators = [";", "&&", "||", "`", "$(", ">#", ">>", "<<"]
        for op in shell_operators:
            if op in comando:
                logger.warning(f"Operador de shell bloqueado en comando: {comando}")
                return f"Comando rechazado: contiene operador de shell no permitido ({op})."

        # 2. Bloqueo por pipe (se permite solo si no hay comandos peligrosos)
        if "|" in comando:
            logger.warning(f"Pipe bloqueado en comando: {comando}")
            return "Comando rechazado: pipes (|) no estan permitidos."

        # 3. Lista ampliada de comandos peligrosos
        dangerous = [
            "rm -rf", "rm -fr", "mkfs", "dd if=", ":(){",
            "shutdown", "reboot", "poweroff", "halt",
            "chmod 777", "chown root", "passwd",
            "curl.*|.*sh", "wget.*|.*sh",
            "python.*import os", "python.*import subprocess",
            "nc -l", "ncat", "netcat",
            "/etc/shadow", "/etc/passwd",
            "crontab", "visudo", "sudoers",
        ]
        cmd_lower = comando.lower()
        for d in dangerous:
            if d in cmd_lower:
                logger.warning(f"Comando peligroso bloqueado: {comando}")
                return f"Comando bloqueado por seguridad: {comando}"

        try:
            # 4. Parsear comando sin shell (previene inyeccion)
            args = shlex.split(comando)
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=os.path.expanduser("~"),
            )
            output = result.stdout
            errors = result.stderr
            response = f"$ {comando}\n\n"
            if output:
                response += f"```\n{output[:3000]}\n```\n"
            if errors:
                response += f"\n[stderr]:\n```\n{errors[:1000]}\n```\n"
            response += f"\n[exit: {result.returncode}]"
            return response
        except ValueError as e:
            return f"Comando con formato invalido: {e}"
        except subprocess.TimeoutExpired:
            return "Timeout: el comando tardo mas de 30 segundos."
        except FileNotFoundError:
            return f"Comando no encontrado: {args[0] if args else comando}"
        except Exception as e:
            logger.error(f"Error ejecutando comando: {e}")
            return "Error interno al ejecutar el comando."

    # ------------------------------------------------------------------
    # 6. BUSQUEDA WEB
    # ------------------------------------------------------------------

    @mcp.register(
        name="buscar_web",
        description="Busca informacion en internet usando DuckDuckGo.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Texto a buscar en internet",
                },
            },
            "required": ["query"],
        },
    )
    def buscar_web(query: str):
        """Realiza una busqueda en DuckDuckGo y retorna los primeros resultados."""
        import urllib.request
        import urllib.parse

        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
        try:
            req = urllib.request.Request(url, headers=headers)
            response = urllib.request.urlopen(req, timeout=10)
            html = response.read().decode("utf-8", errors="ignore")

            results = []
            snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
            titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html, re.DOTALL)
            urls = re.findall(r'class="result__url"[^>]*>(.*?)</a>', html, re.DOTALL)

            for i, (title, snippet) in enumerate(zip(titles[:5], snippets[:5])):
                clean_title = re.sub(r'<[^>]+>', '', title).strip()
                clean_snippet = re.sub(r'<[^>]+>', '', snippet).strip()
                url_text = re.sub(r'<[^>]+>', '', urls[i]).strip() if i < len(urls) else ""
                results.append(f"**{i+1}. {clean_title}**\n{url_text}\n{clean_snippet}")

            if results:
                salida = f"Resultados para '{query}':\n\n" + "\n\n".join(results)
                return f"<datos_externos>\n{salida}\n</datos_externos>"
            return f"<datos_externos>\nNo se encontraron resultados para '{query}'.\n</datos_externos>"

        except Exception as e:
            return f"Error en busqueda web: {e}"

    # ------------------------------------------------------------------
    # 7. SKILLS EXPUESTOS COMO HERRAMIENTAS
    # ------------------------------------------------------------------

    @mcp.register(
        name="extraer_texto_web",
        description="Extrae el texto de una pagina web. Util para leer articulos o documentacion.",
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL completa de la pagina (ej: https://ejemplo.com)",
                },
            },
            "required": ["url"],
        },
    )
    def extraer_texto_web(url: str):
        """Delega al skill web_browser para extraer texto de una URL."""
        from skills.web_browser import execute as web_execute
        resultado = web_execute(action="get_text", url=url)
        return f"<datos_externos>\n{resultado}\n</datos_externos>"

    @mcp.register(
        name="info_sistema",
        description="Obtiene informacion del sistema: CPU, RAM, disco, red, procesos.",
        parameters={
            "type": "object",
            "properties": {
                "tipo": {
                    "type": "string",
                    "description": "Tipo de info: 'general', 'disco', 'red', 'procesos'.",
                },
            },
            "required": [],
        },
    )
    def info_sistema(tipo: str = "general"):
        """Delega al skill desktop_manager para obtener informacion del sistema."""
        from skills.desktop_manager import execute as desktop_execute
        actions = {
            "general": "system_info",
            "disco": "disk_usage",
            "red": "network_info",
            "procesos": "list_processes",
        }
        action = actions.get(tipo, "system_info")
        return desktop_execute(action=action)

    @mcp.register(
        name="abrir_aplicacion",
        description="Abre una aplicacion del sistema operativo por nombre de ejecutable.",
        parameters={
            "type": "object",
            "properties": {
                "nombre": {
                    "type": "string",
                    "description": "Nombre del ejecutable de la aplicacion",
                },
            },
            "required": ["nombre"],
        },
    )
    def abrir_aplicacion(nombre: str):
        """Delega al skill desktop_manager para abrir una aplicacion."""
        from skills.desktop_manager import execute as desktop_execute
        return desktop_execute(action="open_app", app_name=nombre)

    # ------------------------------------------------------------------
    # 8. EMAIL (IMAP/SMTP)
    # ------------------------------------------------------------------

    @mcp.register(
        name="leer_emails",
        description="Lee los ultimos emails de la bandeja de entrada (IMAP). Requiere EMAIL_USER y EMAIL_PASSWORD en .env.",
        parameters={
            "type": "object",
            "properties": {
                "cantidad": {
                    "type": "integer",
                    "description": "Cantidad de emails a leer (default: 5)",
                },
                "carpeta": {
                    "type": "string",
                    "description": "Carpeta de email (default: INBOX)",
                },
            },
            "required": [],
        },
    )
    def leer_emails(cantidad: int = 5, carpeta: str = "INBOX"):
        """
        Conecta al servidor IMAP, descarga los ultimos N emails y
        retorna un resumen con asunto, remitente, fecha y extracto del cuerpo.
        """
        import imaplib
        import email
        from email.header import decode_header

        email_user = os.environ.get("EMAIL_USER", "")
        email_pass = os.environ.get("EMAIL_PASSWORD", "")
        imap_server = os.environ.get("IMAP_SERVER", "imap.gmail.com")

        if not email_user or not email_pass:
            return "Email no configurado. Agrega EMAIL_USER y EMAIL_PASSWORD en .env"

        try:
            mail = imaplib.IMAP4_SSL(imap_server)
            mail.login(email_user, email_pass)
            mail.select(carpeta)

            _, messages = mail.search(None, "ALL")
            msg_ids = messages[0].split()

            if not msg_ids:
                mail.logout()
                return "Bandeja vacia."

            latest = msg_ids[-cantidad:]
            results = []

            for msg_id in reversed(latest):
                _, msg_data = mail.fetch(msg_id, "(RFC822)")
                msg = email.message_from_bytes(msg_data[0][1])

                # Decodificar asunto
                subject_parts = decode_header(msg["Subject"] or "Sin asunto")
                subject = ""
                for part, encoding in subject_parts:
                    if isinstance(part, bytes):
                        subject += part.decode(encoding or "utf-8", errors="ignore")
                    else:
                        subject += part

                from_addr = msg.get("From", "Desconocido")
                date = msg.get("Date", "")

                # Extraer texto del cuerpo
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            payload = part.get_payload(decode=True)
                            if payload:
                                body = payload.decode("utf-8", errors="ignore")[:500]
                            break
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        body = payload.decode("utf-8", errors="ignore")[:500]

                results.append(
                    f"**{subject}**\n"
                    f"  De: {from_addr}\n"
                    f"  Fecha: {date}\n"
                    f"  {body[:200]}..."
                )

            mail.logout()
            return f"Ultimos {len(results)} emails:\n\n" + "\n\n---\n\n".join(results)

        except Exception as e:
            logger.error(f"[MCP] Error leyendo emails: {e}")
            return f"Error leyendo emails: {e}"

    @mcp.register(
        name="enviar_email",
        description="Envia un email via SMTP. Requiere EMAIL_USER y EMAIL_PASSWORD en .env.",
        parameters={
            "type": "object",
            "properties": {
                "destinatario": {
                    "type": "string",
                    "description": "Direccion de email del destinatario",
                },
                "asunto": {
                    "type": "string",
                    "description": "Asunto del email",
                },
                "cuerpo": {
                    "type": "string",
                    "description": "Contenido del email",
                },
            },
            "required": ["destinatario", "asunto", "cuerpo"],
        },
    )
    def enviar_email(destinatario: str, asunto: str, cuerpo: str):
        """Envia un email de texto plano via SMTP con TLS."""
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        email_user = os.environ.get("EMAIL_USER", "")
        email_pass = os.environ.get("EMAIL_PASSWORD", "")
        smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))

        if not email_user or not email_pass:
            return "Email no configurado. Agrega EMAIL_USER y EMAIL_PASSWORD en .env"

        try:
            msg = MIMEMultipart()
            msg["From"] = email_user
            msg["To"] = destinatario
            msg["Subject"] = asunto
            msg.attach(MIMEText(cuerpo, "plain", "utf-8"))

            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            server.login(email_user, email_pass)
            server.send_message(msg)
            server.quit()

            logger.info(f"[MCP] Email enviado a: {destinatario}")
            return f"Email enviado a {destinatario}. Asunto: {asunto}"

        except Exception as e:
            logger.error(f"[MCP] Error enviando email: {e}")
            return f"Error enviando email: {e}"

    # ------------------------------------------------------------------
    # 9. PORTAPAPELES
    # ------------------------------------------------------------------

    @mcp.register(
        name="copiar_portapapeles",
        description="Copia texto al portapapeles del sistema.",
        parameters={
            "type": "object",
            "properties": {
                "texto": {
                    "type": "string",
                    "description": "Texto a copiar al portapapeles",
                },
            },
            "required": ["texto"],
        },
    )
    def copiar_portapapeles(texto: str):
        """Delega al skill clipboard_manager para copiar texto."""
        from skills.clipboard_manager import execute as clip_execute
        return clip_execute(action="copy", text=texto)

    @mcp.register(
        name="pegar_portapapeles",
        description="Lee el contenido actual del portapapeles del sistema.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def pegar_portapapeles():
        """Delega al skill clipboard_manager para leer el portapapeles."""
        from skills.clipboard_manager import execute as clip_execute
        return clip_execute(action="paste")

    # ------------------------------------------------------------------
    # 10. PDF
    # ------------------------------------------------------------------

    @mcp.register(
        name="leer_pdf",
        description="Extrae el texto de un archivo PDF. Soporta lectura completa o por pagina.",
        parameters={
            "type": "object",
            "properties": {
                "ruta": {
                    "type": "string",
                    "description": "Ruta absoluta al archivo PDF",
                },
                "pagina": {
                    "type": "integer",
                    "description": "Numero de pagina a leer (opcional, 1-indexed)",
                },
            },
            "required": ["ruta"],
        },
    )
    def leer_pdf(ruta: str, pagina: int = None):
        """Delega al skill pdf_reader para extraer texto de PDFs."""
        from skills.pdf_reader import execute as pdf_execute
        if pagina:
            resultado = pdf_execute(action="read_page", file_path=ruta, page=pagina)
        else:
            resultado = pdf_execute(action="read", file_path=ruta)
        return f"<datos_externos>\n{resultado}\n</datos_externos>"

    @mcp.register(
        name="buscar_en_pdf",
        description="Busca texto dentro de un archivo PDF.",
        parameters={
            "type": "object",
            "properties": {
                "ruta": {
                    "type": "string",
                    "description": "Ruta absoluta al archivo PDF",
                },
                "query": {
                    "type": "string",
                    "description": "Texto a buscar dentro del PDF",
                },
            },
            "required": ["ruta", "query"],
        },
    )
    def buscar_en_pdf(ruta: str, query: str):
        """Delega al skill pdf_reader para buscar texto en PDFs."""
        from skills.pdf_reader import execute as pdf_execute
        return pdf_execute(action="search", file_path=ruta, query=query)

    # ------------------------------------------------------------------
    # 11. GIT
    # ------------------------------------------------------------------

    @mcp.register(
        name="git_status",
        description="Muestra el estado del repositorio Git: branch actual, cambios pendientes, ultimo commit.",
        parameters={
            "type": "object",
            "properties": {
                "ruta": {
                    "type": "string",
                    "description": "Ruta al repositorio (default: directorio actual)",
                },
            },
            "required": [],
        },
    )
    def git_status(ruta: str = "."):
        """Delega al skill git_manager para obtener el estado del repo."""
        from skills.git_manager import execute as git_execute
        return git_execute(action="status", repo_path=ruta)

    @mcp.register(
        name="git_log",
        description="Muestra los ultimos commits de un repositorio Git.",
        parameters={
            "type": "object",
            "properties": {
                "ruta": {
                    "type": "string",
                    "description": "Ruta al repositorio (default: directorio actual)",
                },
                "cantidad": {
                    "type": "integer",
                    "description": "Cantidad de commits a mostrar (default: 10)",
                },
            },
            "required": [],
        },
    )
    def git_log(ruta: str = ".", cantidad: int = 10):
        """Delega al skill git_manager para mostrar el log de commits."""
        from skills.git_manager import execute as git_execute
        return git_execute(action="log", repo_path=ruta, n=cantidad)

    # ------------------------------------------------------------------
    # 12. BASE DE DATOS
    # ------------------------------------------------------------------

    @mcp.register(
        name="consultar_db",
        description="Ejecuta una consulta SELECT en una base de datos SQLite y retorna los resultados.",
        parameters={
            "type": "object",
            "properties": {
                "db_name": {"type": "string", "description": "Nombre de la base de datos"},
                "query": {"type": "string", "description": "Consulta SQL SELECT"},
            },
            "required": ["db_name", "query"],
        },
    )
    def consultar_db(db_name: str, query: str):
        """Consulta SELECT en base de datos SQLite."""
        from skills.database_manager import execute as db_execute
        return db_execute(action="query", db_name=db_name, query=query, vault_path=str(vault_path))

    @mcp.register(
        name="ejecutar_sql",
        description="Ejecuta SQL (CREATE, INSERT, UPDATE, DELETE) en una base de datos SQLite.",
        parameters={
            "type": "object",
            "properties": {
                "db_name": {"type": "string", "description": "Nombre de la base de datos"},
                "query": {"type": "string", "description": "Consulta SQL a ejecutar"},
            },
            "required": ["db_name", "query"],
        },
    )
    def ejecutar_sql(db_name: str, query: str):
        """Ejecuta operaciones SQL de escritura."""
        from skills.database_manager import execute as db_execute
        return db_execute(action="execute", db_name=db_name, query=query, vault_path=str(vault_path))

    # ------------------------------------------------------------------
    # 13. ANALISIS DE TEXTO
    # ------------------------------------------------------------------

    @mcp.register(
        name="resumir_texto",
        description="Resume un texto largo, manteniendo los puntos clave.",
        parameters={
            "type": "object",
            "properties": {
                "texto": {"type": "string", "description": "Texto a resumir"},
            },
            "required": ["texto"],
        },
    )
    def resumir_texto(texto: str):
        """Delega al skill text_analyzer para resumir texto."""
        from skills.text_analyzer import execute as text_execute
        from core.llm_engine import create_engine
        # Usar el LLM engine global si esta disponible
        return text_execute(action="summarize", text=texto, llm_engine=_get_llm_ref())

    @mcp.register(
        name="traducir_texto",
        description="Traduce texto a otro idioma.",
        parameters={
            "type": "object",
            "properties": {
                "texto": {"type": "string", "description": "Texto a traducir"},
                "idioma": {"type": "string", "description": "Idioma destino (ej: ingles, frances)"},
            },
            "required": ["texto", "idioma"],
        },
    )
    def traducir_texto(texto: str, idioma: str = "ingles"):
        """Delega al skill text_analyzer para traducir texto."""
        from skills.text_analyzer import execute as text_execute
        return text_execute(action="translate", text=texto, language=idioma, llm_engine=_get_llm_ref())

    # ------------------------------------------------------------------
    # 14. CLIENTE API
    # ------------------------------------------------------------------

    @mcp.register(
        name="consultar_api",
        description="Realiza una peticion HTTP a una API externa (GET/POST). Solo permite URLs publicas (bloquea red local).",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL de la API"},
                "metodo": {"type": "string", "description": "GET, POST, PUT, DELETE (default: GET)"},
                "body": {"type": "string", "description": "Cuerpo JSON de la peticion (opcional)"},
            },
            "required": ["url"],
        },
    )
    def consultar_api(url: str, metodo: str = "GET", body: str = None):
        """Realiza peticiones HTTP a APIs externas."""
        from skills.api_client import execute as api_execute
        return api_execute(action="request", url=url, method=metodo, body=body)

    @mcp.register(
        name="clima",
        description="Obtiene el clima actual de una ciudad.",
        parameters={
            "type": "object",
            "properties": {
                "ciudad": {"type": "string", "description": "Nombre de la ciudad"},
            },
            "required": ["ciudad"],
        },
    )
    def clima(ciudad: str):
        """Consulta el clima de una ciudad via wttr.in."""
        from skills.api_client import execute as api_execute
        return api_execute(action="weather", params={"city": ciudad})

    @mcp.register(
        name="divisa",
        description="Consulta la tasa de cambio entre dos divisas.",
        parameters={
            "type": "object",
            "properties": {
                "de": {"type": "string", "description": "Moneda origen (ej: USD)"},
                "a": {"type": "string", "description": "Moneda destino (ej: COP)"},
                "cantidad": {"type": "number", "description": "Cantidad a convertir (default: 1)"},
            },
            "required": ["de", "a"],
        },
    )
    def divisa(de: str, a: str, cantidad: float = 1):
        """Consulta tasa de cambio entre divisas."""
        from skills.api_client import execute as api_execute
        return api_execute(action="currency", params={"from": de, "to": a, "amount": cantidad})

    # ------------------------------------------------------------------
    # 15. MULTIMEDIA
    # ------------------------------------------------------------------

    @mcp.register(
        name="convertir_media",
        description="Convierte archivos multimedia entre formatos (audio, video, imagen). Usa ffmpeg e ImageMagick.",
        parameters={
            "type": "object",
            "properties": {
                "entrada": {"type": "string", "description": "Ruta al archivo de entrada"},
                "salida": {"type": "string", "description": "Ruta al archivo de salida (o dejar vacio y usar formato)"},
                "formato": {"type": "string", "description": "Formato de salida (mp3, mp4, jpg, png, etc.)"},
            },
            "required": ["entrada"],
        },
    )
    def convertir_media(entrada: str, salida: str = None, formato: str = None):
        """Convierte archivos multimedia entre formatos."""
        from skills.media_tools import execute as media_execute
        return media_execute(action="convert", input_path=entrada, output_path=salida, format=formato)

    @mcp.register(
        name="info_media",
        description="Muestra informacion detallada de un archivo multimedia (duracion, codec, resolucion).",
        parameters={
            "type": "object",
            "properties": {
                "ruta": {"type": "string", "description": "Ruta al archivo multimedia"},
            },
            "required": ["ruta"],
        },
    )
    def info_media(ruta: str):
        """Informacion de archivos multimedia via ffprobe."""
        from skills.media_tools import execute as media_execute
        return media_execute(action="info", input_path=ruta)

    # ------------------------------------------------------------------
    # 16. DISPOSITIVOS
    # ------------------------------------------------------------------

    @mcp.register(
        name="captura_pantalla",
        description="Captura la pantalla completa y guarda como imagen PNG.",
        parameters={
            "type": "object",
            "properties": {
                "ruta": {"type": "string", "description": "Ruta donde guardar la imagen (opcional)"},
            },
            "required": [],
        },
    )
    def captura_pantalla(ruta: str = None):
        """Captura de pantalla via scrot/gnome-screenshot."""
        from skills.device_access import execute as dev_execute
        return dev_execute(action="screenshot", output_path=ruta)

    @mcp.register(
        name="sensores",
        description="Lee datos de sensores: temperatura CPU, bateria, uptime.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def sensores():
        """Datos de sensores del sistema."""
        from skills.device_access import execute as dev_execute
        return dev_execute(action="sensors")

    # ------------------------------------------------------------------
    # 17. CONFIGURACION DEL SISTEMA
    # ------------------------------------------------------------------

    @mcp.register(
        name="info_sistema_completa",
        description="Informacion completa del sistema: SO, kernel, CPU, RAM, hostname, uptime.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def info_sistema_completa():
        """Informacion detallada del sistema operativo."""
        from skills.system_config import execute as sys_execute
        return sys_execute(action="info")

    @mcp.register(
        name="config_red",
        description="Muestra configuracion de red: interfaces, IPs, DNS, gateway.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def config_red():
        """Configuracion de red del sistema."""
        from skills.system_config import execute as sys_execute
        return sys_execute(action="network")

    # ------------------------------------------------------------------
    # 18. GESTION DE ARCHIVOS (expandida)
    # ------------------------------------------------------------------

    @mcp.register(
        name="copiar_archivo",
        description="Copia un archivo o directorio de una ruta a otra.",
        parameters={
            "type": "object",
            "properties": {
                "origen": {"type": "string", "description": "Ruta del archivo origen"},
                "destino": {"type": "string", "description": "Ruta de destino"},
            },
            "required": ["origen", "destino"],
        },
    )
    def copiar_archivo(origen: str, destino: str):
        """Copia archivos con validacion de rutas."""
        import shutil
        for path in [origen, destino]:
            if not _is_path_allowed(path, "write"):
                return f"Acceso denegado: {path}"
        if Path(origen).is_symlink():
            return "Acceso denegado: no se permiten symlinks."
        try:
            if Path(origen).is_dir():
                shutil.copytree(origen, destino)
            else:
                shutil.copy2(origen, destino)
            return f"Copiado: {origen} -> {destino}"
        except Exception as e:
            return f"Error: {e}"

    @mcp.register(
        name="mover_archivo",
        description="Mueve o renombra un archivo o directorio.",
        parameters={
            "type": "object",
            "properties": {
                "origen": {"type": "string", "description": "Ruta actual"},
                "destino": {"type": "string", "description": "Nueva ruta"},
            },
            "required": ["origen", "destino"],
        },
    )
    def mover_archivo(origen: str, destino: str):
        """Mueve archivos con validacion de rutas."""
        import shutil
        for path in [origen, destino]:
            if not _is_path_allowed(path, "write"):
                return f"Acceso denegado: {path}"
        if Path(origen).is_symlink():
            return "Acceso denegado: no se permiten symlinks."
        try:
            shutil.move(origen, destino)
            return f"Movido: {origen} -> {destino}"
        except Exception as e:
            return f"Error: {e}"

    @mcp.register(
        name="eliminar_archivo",
        description="Elimina un archivo o directorio vacio. PRECAUCION: Irreversible.",
        parameters={
            "type": "object",
            "properties": {
                "ruta": {"type": "string", "description": "Ruta del archivo a eliminar"},
            },
            "required": ["ruta"],
        },
    )
    def eliminar_archivo(ruta: str):
        """Elimina archivo con multiples validaciones de seguridad."""
        if not _is_path_allowed(ruta, "write"):
            return f"Acceso denegado: {ruta}"
        p = Path(ruta)
        if p.is_symlink():
            return "Acceso denegado: no se permiten symlinks."
        if not p.exists():
            return f"No existe: {ruta}"
        # Proteger vault y config
        resolved = str(p.resolve())
        protected = ["memory_vault", ".env", ".auth", ".key", "main.py"]
        for prot in protected:
            if prot in resolved:
                return f"Archivo protegido, no se puede eliminar: {ruta}"
        try:
            if p.is_dir():
                if any(p.iterdir()):
                    return "Directorio no vacio. Usa eliminar recursivo solo manualmente."
                p.rmdir()
            else:
                p.unlink()
            return f"Eliminado: {ruta}"
        except Exception as e:
            return f"Error: {e}"

    @mcp.register(
        name="buscar_archivos",
        description="Busca archivos por nombre o patron en un directorio.",
        parameters={
            "type": "object",
            "properties": {
                "directorio": {"type": "string", "description": "Directorio donde buscar"},
                "patron": {"type": "string", "description": "Patron de busqueda (ej: *.py, informe*)"},
            },
            "required": ["directorio", "patron"],
        },
    )
    def buscar_archivos(directorio: str, patron: str):
        """Busca archivos con glob seguro."""
        if not _is_path_allowed(directorio, "read"):
            return f"Acceso denegado: {directorio}"
        import re
        # Sanitizar patron: bloquear path traversal
        if ".." in patron or "/" in patron:
            return "Patron invalido: no se permiten .. o / en el patron."
        try:
            results = sorted(Path(directorio).rglob(patron))[:50]
            if not results:
                return f"Sin resultados para '{patron}' en {directorio}"
            lines = [f"{len(results)} archivo(s) encontrado(s):"]
            for r in results:
                size = r.stat().st_size if r.is_file() else 0
                lines.append(f"  {'📁' if r.is_dir() else '📄'} {r} ({size:,} B)")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    @mcp.register(
        name="info_archivo",
        description="Muestra informacion detallada de un archivo (tamano, permisos, fechas).",
        parameters={
            "type": "object",
            "properties": {
                "ruta": {"type": "string", "description": "Ruta del archivo"},
            },
            "required": ["ruta"],
        },
    )
    def info_archivo(ruta: str):
        """Informacion detallada de un archivo."""
        if not _is_path_allowed(ruta, "read"):
            return f"Acceso denegado: {ruta}"
        p = Path(ruta)
        if not p.exists():
            return f"No existe: {ruta}"
        try:
            stat = p.stat()
            import time
            return (
                f"**{p.name}**\n\n"
                f"  Tipo: {'directorio' if p.is_dir() else 'archivo'}\n"
                f"  Tamano: {stat.st_size:,} bytes\n"
                f"  Permisos: {oct(stat.st_mode)[-3:]}\n"
                f"  Modificado: {time.ctime(stat.st_mtime)}\n"
                f"  Creado: {time.ctime(stat.st_ctime)}\n"
                f"  Ruta: {p.resolve()}"
            )
        except Exception as e:
            return f"Error: {e}"

    # ------------------------------------------------------------------
    # 19. GESTION DE PROCESOS
    # ------------------------------------------------------------------

    @mcp.register(
        name="listar_procesos",
        description="Lista los procesos en ejecucion del sistema (top 20 por CPU).",
        parameters={
            "type": "object",
            "properties": {
                "filtro": {"type": "string", "description": "Filtrar por nombre de proceso (opcional)"},
            },
            "required": [],
        },
    )
    def listar_procesos(filtro: str = ""):
        """Lista procesos del sistema sin shell=True."""
        try:
            cmd = ["ps", "aux", "--sort=-%cpu"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            lines = result.stdout.strip().splitlines()
            if filtro:
                import re
                safe_filter = re.sub(r'[^a-zA-Z0-9_.-]', '', filtro)
                lines = [lines[0]] + [l for l in lines[1:] if safe_filter.lower() in l.lower()]
            lines = lines[:21]  # header + 20
            return f"```\n" + "\n".join(lines) + f"\n```\n({len(lines)-1} procesos)"
        except Exception as e:
            return f"Error: {e}"

    @mcp.register(
        name="terminar_proceso",
        description="Termina un proceso por PID. Solo procesos del usuario actual.",
        parameters={
            "type": "object",
            "properties": {
                "pid": {"type": "integer", "description": "PID del proceso a terminar"},
            },
            "required": ["pid"],
        },
    )
    def terminar_proceso(pid: int):
        """Termina un proceso con validacion de ownership."""
        import signal
        try:
            # Verificar que el proceso pertenezca al usuario actual
            proc_path = Path(f"/proc/{pid}/status")
            if not proc_path.exists():
                return f"Proceso {pid} no encontrado."
            status = proc_path.read_text()
            uid_line = [l for l in status.splitlines() if l.startswith("Uid:")]
            if uid_line:
                proc_uid = int(uid_line[0].split()[1])
                if proc_uid != os.getuid():
                    return f"Acceso denegado: proceso {pid} no pertenece al usuario actual."
            # No permitir terminar procesos criticos
            comm_path = Path(f"/proc/{pid}/comm")
            if comm_path.exists():
                comm = comm_path.read_text().strip()
                critical = ["systemd", "init", "sshd", "login", "Xorg", "wayland"]
                if comm in critical:
                    return f"Proceso critico protegido: {comm} (PID {pid})"
            os.kill(pid, signal.SIGTERM)
            logger.info(f"[procesos] SIGTERM enviado a PID {pid}")
            return f"Señal SIGTERM enviada al proceso {pid}."
        except ProcessLookupError:
            return f"Proceso {pid} no encontrado."
        except PermissionError:
            return f"Sin permisos para terminar proceso {pid}."
        except Exception as e:
            return f"Error: {e}"

    # ------------------------------------------------------------------
    # 20. GESTION DE USUARIOS
    # ------------------------------------------------------------------

    @mcp.register(
        name="listar_usuarios_sistema",
        description="Lista los usuarios del sistema con shell de login.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def listar_usuarios_sistema():
        """Lista usuarios del sistema (lectura de /etc/passwd)."""
        from skills.system_config import execute as sys_execute
        return sys_execute(action="users")

    # ------------------------------------------------------------------
    # 21. ANALISIS DE SENTIMIENTO Y ENTIDADES (via text_analyzer existente)
    # ------------------------------------------------------------------

    @mcp.register(
        name="analizar_sentimiento",
        description="Analiza el sentimiento y emociones de un texto.",
        parameters={
            "type": "object",
            "properties": {
                "texto": {"type": "string", "description": "Texto a analizar"},
            },
            "required": ["texto"],
        },
    )
    def analizar_sentimiento(texto: str):
        """Analisis de sentimiento via text_analyzer."""
        from skills.text_analyzer import execute as text_execute
        return text_execute(action="sentiment", text=texto, llm_engine=_get_llm_ref())

    @mcp.register(
        name="detectar_entidades",
        description="Detecta entidades (personas, lugares, organizaciones, fechas) en un texto.",
        parameters={
            "type": "object",
            "properties": {
                "texto": {"type": "string", "description": "Texto a analizar"},
            },
            "required": ["texto"],
        },
    )
    def detectar_entidades(texto: str):
        """Deteccion de entidades via text_analyzer."""
        from skills.text_analyzer import execute as text_execute
        return text_execute(action="keywords", text=texto, llm_engine=_get_llm_ref())

    # ------------------------------------------------------------------
    # 22. RECONOCIMIENTO DE VOZ
    # ------------------------------------------------------------------

    @mcp.register(
        name="transcribir_audio",
        description="Transcribe audio a texto (soporta wav, mp3, ogg, flac).",
        parameters={
            "type": "object",
            "properties": {
                "ruta": {"type": "string", "description": "Ruta al archivo de audio"},
                "idioma": {"type": "string", "description": "Idioma del audio (default: es)"},
            },
            "required": ["ruta"],
        },
    )
    def transcribir_audio(ruta: str, idioma: str = "es"):
        """Transcripcion de audio via Whisper o speech_recognition."""
        from skills.voice_recognition import execute as voice_execute
        return voice_execute(action="transcribe", audio_path=ruta, language=idioma)

    # ------------------------------------------------------------------
    # 23. GENERACION DE TEXTO
    # ------------------------------------------------------------------

    @mcp.register(
        name="generar_texto",
        description="Genera texto especializado: creativo, codigo, formal, ideas, estructurado.",
        parameters={
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Tema o instruccion"},
                "modo": {"type": "string", "description": "Modo: creative, code, formal, brainstorm, structured, free"},
                "estilo": {"type": "string", "description": "Estilo adicional o lenguaje de programacion"},
            },
            "required": ["prompt", "modo"],
        },
    )
    def generar_texto(prompt: str, modo: str = "free", estilo: str = None):
        """Generacion de texto especializada."""
        from skills.text_generator import execute as gen_execute
        return gen_execute(action=modo, prompt=prompt, style=estilo, language=estilo, llm_engine=_get_llm_ref())

    # ------------------------------------------------------------------
    # 24. APRENDIZAJE AUTOMATICO
    # ------------------------------------------------------------------

    @mcp.register(
        name="clasificar_texto",
        description="Clasifica texto en categorias dadas (clasificacion zero-shot).",
        parameters={
            "type": "object",
            "properties": {
                "texto": {"type": "string", "description": "Texto a clasificar"},
                "categorias": {"type": "string", "description": "Categorias separadas por coma"},
            },
            "required": ["texto", "categorias"],
        },
    )
    def clasificar_texto(texto: str, categorias: str):
        """Clasificacion zero-shot via LLM."""
        from skills.ml_engine import execute as ml_execute
        cats = [c.strip() for c in categorias.split(",")]
        return ml_execute(action="classify", text=texto, categories=cats, llm_engine=_get_llm_ref())

    # ------------------------------------------------------------------
    # 25. DEEP LEARNING
    # ------------------------------------------------------------------

    @mcp.register(
        name="describir_imagen",
        description="Describe el contenido de una imagen en detalle.",
        parameters={
            "type": "object",
            "properties": {
                "ruta": {"type": "string", "description": "Ruta a la imagen"},
            },
            "required": ["ruta"],
        },
    )
    def describir_imagen(ruta: str):
        """Descripcion de imagen via GPT-4 Vision o analisis basico."""
        from skills.deep_learning import execute as dl_execute
        return dl_execute(action="describe_image", file_path=ruta, llm_engine=_get_llm_ref())

    @mcp.register(
        name="ocr_imagen",
        description="Extrae texto de una imagen (OCR con Tesseract).",
        parameters={
            "type": "object",
            "properties": {
                "ruta": {"type": "string", "description": "Ruta a la imagen"},
            },
            "required": ["ruta"],
        },
    )
    def ocr_imagen(ruta: str):
        """OCR via Tesseract."""
        from skills.deep_learning import execute as dl_execute
        return dl_execute(action="ocr", file_path=ruta)

    # ------------------------------------------------------------------
    # 26. APIs EXTERNAS
    # ------------------------------------------------------------------

    @mcp.register(
        name="google_maps",
        description="Busca direcciones, rutas o lugares usando Google Maps.",
        parameters={
            "type": "object",
            "properties": {
                "accion": {"type": "string", "description": "geocode, directions, o places"},
                "direccion": {"type": "string", "description": "Direccion o lugar a buscar"},
                "destino": {"type": "string", "description": "Destino (solo para directions)"},
            },
            "required": ["accion", "direccion"],
        },
    )
    def google_maps(accion: str, direccion: str, destino: str = ""):
        """Google Maps: geocode, directions, places."""
        from skills.api_services import execute as api_execute
        if accion == "directions":
            return api_execute(action="directions", params={"origin": direccion, "destination": destino})
        elif accion == "places":
            return api_execute(action="places", params={"query": direccion})
        else:
            return api_execute(action="geocode", params={"address": direccion})

    @mcp.register(
        name="clima_detallado",
        description="Clima detallado de una ciudad via OpenWeatherMap.",
        parameters={
            "type": "object",
            "properties": {
                "ciudad": {"type": "string", "description": "Nombre de la ciudad"},
                "pronostico": {"type": "boolean", "description": "True para pronostico 5 dias"},
            },
            "required": ["ciudad"],
        },
    )
    def clima_detallado(ciudad: str, pronostico: bool = False):
        """Clima detallado o pronostico via OpenWeatherMap."""
        from skills.api_services import execute as api_execute
        action = "forecast" if pronostico else "weather_detail"
        return api_execute(action=action, params={"city": ciudad})

    @mcp.register(
        name="noticias",
        description="Busca noticias recientes por tema o muestra titulares.",
        parameters={
            "type": "object",
            "properties": {
                "tema": {"type": "string", "description": "Tema a buscar (o vacio para titulares)"},
                "pais": {"type": "string", "description": "Codigo de pais para titulares (default: co)"},
            },
            "required": [],
        },
    )
    def noticias(tema: str = "", pais: str = "co"):
        """Noticias via NewsAPI."""
        from skills.api_services import execute as api_execute
        if tema:
            return api_execute(action="news", params={"query": tema})
        return api_execute(action="news_headlines", params={"country": pais})

    # ------------------------------------------------------------------
    # 27. HOME ASSISTANT
    # ------------------------------------------------------------------

    @mcp.register(
        name="ha_dispositivos",
        description="Lista los dispositivos de Home Assistant, opcionalmente filtrados por tipo (light, switch, sensor, etc.).",
        parameters={
            "type": "object",
            "properties": {
                "tipo": {"type": "string", "description": "Tipo de dispositivo: light, switch, sensor, climate, cover, media_player (opcional)"},
            },
            "required": [],
        },
    )
    def ha_dispositivos(tipo: str = ""):
        """Lista entidades de Home Assistant."""
        from skills.home_assistant import execute as ha_execute
        return ha_execute(action="states", domain=tipo if tipo else None)

    @mcp.register(
        name="ha_estado",
        description="Obtiene el estado detallado de un dispositivo de Home Assistant.",
        parameters={
            "type": "object",
            "properties": {
                "entidad": {"type": "string", "description": "ID de la entidad (ej: light.sala, sensor.temperatura)"},
            },
            "required": ["entidad"],
        },
    )
    def ha_estado(entidad: str):
        """Estado de una entidad de Home Assistant."""
        from skills.home_assistant import execute as ha_execute
        return ha_execute(action="state", entity_id=entidad)

    @mcp.register(
        name="ha_controlar",
        description="Controla un dispositivo de Home Assistant: encender, apagar o alternar.",
        parameters={
            "type": "object",
            "properties": {
                "entidad": {"type": "string", "description": "ID de la entidad (ej: light.sala)"},
                "accion": {"type": "string", "description": "turn_on, turn_off, o toggle"},
                "brillo": {"type": "integer", "description": "Brillo 0-255 (solo para luces, opcional)"},
            },
            "required": ["entidad", "accion"],
        },
    )
    def ha_controlar(entidad: str, accion: str = "toggle", brillo: int = None):
        """Controla un dispositivo de Home Assistant."""
        from skills.home_assistant import execute as ha_execute
        valid_actions = {"turn_on", "turn_off", "toggle"}
        if accion not in valid_actions:
            return f"Accion invalida: {accion}. Opciones: {', '.join(valid_actions)}"
        data = {}
        if brillo is not None:
            data["brightness"] = max(0, min(255, brillo))
        return ha_execute(action=accion, entity_id=entidad, data=data if data else None)

    @mcp.register(
        name="ha_servicio",
        description="Ejecuta un servicio de Home Assistant (escena, script, automatizacion).",
        parameters={
            "type": "object",
            "properties": {
                "dominio": {"type": "string", "description": "Dominio del servicio (scene, script, automation)"},
                "servicio": {"type": "string", "description": "Nombre del servicio (turn_on, activate, trigger)"},
                "datos": {"type": "string", "description": "Datos adicionales en JSON (opcional)"},
            },
            "required": ["dominio", "servicio"],
        },
    )
    def ha_servicio(dominio: str, servicio: str, datos: str = ""):
        """Ejecuta un servicio de Home Assistant."""
        from skills.home_assistant import execute as ha_execute
        data = None
        if datos:
            try:
                import json
                data = json.loads(datos)
            except Exception:
                return "Error: datos JSON invalidos."
        return ha_execute(action="call_service", domain=dominio, service=servicio, data=data)

    # ------------------------------------------------------------------
    # 28. TEXT-TO-SPEECH (TTS)
    # ------------------------------------------------------------------

    @mcp.register(
        name="texto_a_voz",
        description="Convierte texto a audio hablado usando TTS (Text-to-Speech) y lo reproduce o guarda en un archivo.",
        parameters={
            "type": "object",
            "properties": {
                "texto": {"type": "string", "description": "Texto a hablar (max 5000 chars)"},
                "accion": {"type": "string", "description": "Accion: 'speak' (reproducir) o 'save' (guardar archivo)"},
                "voz": {"type": "string", "description": "Voz para OpenAI (alloy, echo, fable, onyx, nova, shimmer)"},
                "idioma": {"type": "string", "description": "Idioma para motores locales (default: 'es')"},
            },
            "required": ["texto"],
        },
    )
    def texto_a_voz(texto: str, accion: str = "speak", voz: str = "nova", idioma: str = "es"):
        """Convierte texto a voz."""
        from skills.tts import execute as tts_execute
        return tts_execute(action=accion, text=texto, voice=voz, language=idioma)

    # ------------------------------------------------------------------
    # 29. SISTEMA DE PLUGINS EXTERNOS
    # ------------------------------------------------------------------

    @mcp.register(
        name="listar_plugins",
        description="Lista los plugins externos cargados actualmente en el sistema.",
        parameters={},
    )
    def listar_plugins():
        """Lista los plugins externos disponibles."""
        from skills.skill_manager import SkillManager
        from pathlib import Path
        sm = SkillManager(Path("skills"))
        plugins_dir = Path("plugins")
        
        plugins = []
        if plugins_dir.exists():
            for f in plugins_dir.glob("*.py"):
                if not f.name.startswith("_"):
                    plugins.append(f.stem)
                    
        if not plugins:
            return "No hay plugins externos cargados en el directorio plugins/."
        return f"Plugins externos cargados: {', '.join(plugins)}"

    # ------------------------------------------------------------------
    # 30. NAVEGACIÓN Y SCRAPING (FIRECRAWL)
    # ------------------------------------------------------------------

    @mcp.register(
        name="firecrawl",
        description="""Herramienta avanzada de scraping y navegacion web. Ejecuta subcomandos del CLI de Firecrawl.
Ejemplos de comandos ('comando' es el argumento que debes pasar):
- search "query" --scrape
- scrape "https://url.com" -o /tmp/raw.md
- map "https://url.com" --search "auth"
- browser "open https://url.com" y luego browser "scrape" -o /tmp/page.md
Devuelve la salida en terminal, y si usas '-o ruta', leelo despues.""",
        parameters={
            "type": "object",
            "properties": {
                "comando": {
                    "type": "string",
                    "description": "El comando de firecrawl a ejecutar (sin 'firecrawl' prefijo). Ej: search \"noticias\" --scrape"
                },
            },
            "required": ["comando"],
        },
    )
    def firecrawl_tool(comando: str):
        """Ejecuta un comando delegando a la capa de Skills (aislado funcionalmente)."""
        from skills.firecrawl import execute as firecrawl_execute
        return firecrawl_execute(comando=comando)

    # ------------------------------------------------------------------
    # 30. DESCARGAR ARCHIVOS Y MEDIA
    # ------------------------------------------------------------------

    @mcp.register(
        name="descargar_archivo",
        description="Descarga un archivo/imagen de internet. IMPORTANTE: Cuando uses esto, DEBES incluir exactamente el texto devuelto (ej: [IMAGE: ruta] o [FILE: ruta]) en tu respuesta para que Telegram envíe el archivo.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL del archivo o imagen a descargar"},
            },
            "required": ["url"],
        },
    )
    def descargar_archivo(url: str):
        """Descarga un archivo al sistema local y le dice al bot que lo envíe."""
        import urllib.request
        from pathlib import Path
        import time
        
        try:
            # Crear nombre seguro e inferir si es imagen
            url_lower = url.lower().split('?')[0]
            es_imagen = any(url_lower.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'])
            
            ext = url.split('.')[-1].split('?')[0]
            if not ext or len(ext) > 4:
                ext = "jpg" if es_imagen else "bin"
            
            filename = f"download_{int(time.time())}.{ext}"
            filepath = Path("/tmp") / filename
            
            headers = {"User-Agent": "Mozilla/5.0"}
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as response:
                filepath.write_bytes(response.read())
            
            tag = "IMAGE" if es_imagen else "FILE"
            return f"Archivo descargado exitosamente. Para que el usuario lo vea, DALE ESTE TEXTO EXACTO en tu respuesta principal sin alterarlo:\n\n[{tag}: {filepath}]"
        except Exception as e:
            return f"Error descargando {url}: {e}"


    @mcp.register(
        name="ejecutar_plugin",
        description="Ejecuta una accion de un plugin externo especifico.",
        parameters={
            "type": "object",
            "properties": {
                "plugin_name": {"type": "string", "description": "Nombre del plugin a ejecutar"},
                "accion": {"type": "string", "description": "Accion a solicitar al plugin"},
                "datos": {"type": "string", "description": "Datos adicionales en formato JSON (opcional)"},
            },
            "required": ["plugin_name", "accion"],
        },
    )
    def ejecutar_plugin(plugin_name: str, accion: str, datos: str = ""):
        """Ejecuta un plugin externo."""
        from skills.skill_manager import SkillManager
        from pathlib import Path
        import json
        sm = SkillManager(Path("skills"))
        
        kwargs = {"action": accion}
        if datos:
            try:
                kwargs.update(json.loads(datos))
            except Exception:
                return "Error: Los datos deben ser formato JSON valido."
        
        return sm.run(plugin_name, **kwargs)

    # ------------------------------------------------------------------
    # 30. GOOGLE CALENDAR
    # ------------------------------------------------------------------

    @mcp.register(
        name="calendario_eventos",
        description="Lista los proximos eventos en Google Calendar.",
        parameters={
            "type": "object",
            "properties": {
                "cantidad": {"type": "integer", "description": "Cantidad maxima de eventos a listar (defecto: 10)"},
            },
            "required": [],
        },
    )
    def calendario_eventos(cantidad: int = 10):
        """Lista los proximos eventos de Google Calendar."""
        from skills.google_calendar import execute as gcal_execute
        return gcal_execute(action="list", max_results=cantidad)

    @mcp.register(
        name="calendario_buscar",
        description="Busca eventos en Google Calendar por palabras clave.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Texto a buscar en los eventos"},
            },
            "required": ["query"],
        },
    )
    def calendario_buscar(query: str):
        """Busca eventos en Google Calendar."""
        from skills.google_calendar import execute as gcal_execute
        return gcal_execute(action="search", query=query)

    @mcp.register(
        name="calendario_crear",
        description="Crea un nuevo evento en Google Calendar.",
        parameters={
            "type": "object",
            "properties": {
                "titulo": {"type": "string", "description": "Titulo del evento"},
                "inicio": {"type": "string", "description": "Fecha y hora de inicio (formato ISO 8601, ej: 2026-02-21T10:00:00)"},
                "fin": {"type": "string", "description": "Fecha y hora de fin (formato ISO 8601, ej: 2026-02-21T11:00:00)"},
                "descripcion": {"type": "string", "description": "Descripcion del evento (opcional)"},
            },
            "required": ["titulo", "inicio", "fin"],
        },
    )
    def calendario_crear(titulo: str, inicio: str, fin: str, descripcion: str = ""):
        """Crea un evento en Google Calendar."""
        from skills.google_calendar import execute as gcal_execute
        return gcal_execute(action="create", summary=titulo, start_time=inicio, end_time=fin, description=descripcion)

    # ------------------------------------------------------------------
    # Resumen de registro
    # ------------------------------------------------------------------
    tool_names = mcp.get_tool_names()
    logger.info(f"[MCP] {len(tool_names)} herramientas registradas: {', '.join(tool_names)}")
