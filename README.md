# Py-Assistant

Asistente personal autonomo diseñado para operar como un proceso daemon interactuando principalmente a traves de Telegram. Implementa un sistema de arquitectura modular con identidad persistente, memoria encriptada, aislamiento de red y multiples herramientas integradas (MCP/Skills).

Disenado para hardware con recursos limitados (ej. Orange Pi Zero 2W, 4GB RAM) y con un alto enfoque en seguridad, privacidad y extensibilidad.

## Arquitectura del Sistema

El sistema esta dividido en capas modulares que separan la identidad de la memoria, las herramientas de ejecucion y los canales de comunicacion:

1. **Capa de Inferencia (LLM Engine):** Abstraccion multi-modelo compatible con Groq, OpenAI, Anthropic, Ollama local, entre otros, manejando la logica y el razonamiento.
2. **Capa de Seguridad:** Aislamiento estricto de red, proteccion de archivos sensibles, autenticacion mediante bcrypt y prevencion de inyecciones de comandos.
3. **Capa de Persistencia (Memoria y Soul):** Directorio seguro que almacena la identidad del asistente (`soul_state.md`), perfil de usuario, memoria a largo plazo consolidada, y registros de chat. En produccion, se monta sobre LUKS2 o usa encriptacion nivel aplicacion.
4. **Capa de Orquestacion:** Bucle central que recibe el contexto de identidad, la memoria reciente y enruta las interacciones hacia el modulo Model Context Protocol (MCP) o los Skills.
5. **Capa de Módulos (MCP y Skills):** Proveen capacidades tangibles al agente:
   - **MCP:** Ejecucion segura de operaciones directas (lectura de archivos, consultas web crudas, APIs).
   - **Skills:** Integraciones complejas (Home Assistant, Web Scraping avanzado mediante Playwright/Firecrawl, control local y desktop).
6. **Capa de Presentacion:** Interfaz principal de entrada salida, actualmente operando a traves de Telegram Bot con emparejamiento seguro y autenticacion.

## Estado de Desarrollo

El proyecto se encuentra funcional con gran cantidad de herramientas integradas, estructurado en fases de desarrollo progresivo. Funciones destacadas desarrolladas:

- **Motor Central:** Integracion fluida de multiples LLMs, orquestacion de herramientas con parseo defensivo contra alucinaciones del modelo (errores `tool_use_failed` mitigados).
- **Herramientas (62 MCPs Activos):** Capacidad de leer y escribir archivos, gestionar tareas de sistema operativo, consultas a bases de datos SQLite integradas, traducciones, consultas de fechas/climas, extraccion de texto de PDFs y gestion de calendarios.
- **Habilidades Complejas (19 Skills Activas):**
  - Manejo de portapapeles y ventanas graficas (Desktop Manager via xdotool).
  - Web scraping interactivo (Skill original via Playwright y reciente integracion con CLI de Firecrawl para webs complejas protegiendo la API Key).
  - Reconocimiento de voz local y por transcribcion cloud (Whisper).
  - Motores de Text-to-Speech multi-tecnologia integrados.
  - Interaccion bidireccional con nodos de domotica Home Assistant.

## 🔒 Auditorías de Seguridad Centralizadas

El esquema asume que el LLM puede ser manipulado. Se realizaron exhaustivas auditorías de código reduciendo la superficie de ataque a lo largo del desarrollo:

### Auditoría Estructural (Diseño Core)

El esquema asume que el LLM puede ser manipulado o generar comandos erraticos. Por tanto, se realizaron exhaustivas auditorias de codigo reduciendo la superficie de ataque:

- **Red:** Aislamiento de subredes locales bloqueando intentos de SSRF mediante validacion estricta en el proxy interno `api_client.py` que discrimina entre rangos de IP (localhost, IPv6 local link).
- **Proceso (Daemon):** Systemd de produccion configurado con 12 directivas de hardening restrictivo (`NoNewPrivileges`, directorio `ProtectHome=read-only`, `UMask=0077`, y namespace isolation).
- **Credenciales:** Migracion a hashing `bcrypt` con Salt automatico para passwords locales (evitando visibilidad en historial de Telegram mediante depuracion dinamica de mensajes).
- **Proteccion de Comandos y SQL:** El sistema prohíbe el uso de `shell=True` durante la ejecucion paralela, empleando validaciones lexicas (`shlex`) y bloqueando operadores condicionales (ej. `;`, `||`, `&&`). Validacion restrictiva para subconsultas SQL evadiendo accesos cross-database.\n\n### 🔒 Auditoría de Seguridad — Completada (2026-02-20)

Se realizó una auditoría completa del código fuente, configuraciones, scripts y permisos.
13 hallazgos identificados y remediados:

### Críticas (3)

| ID | Hallazgo | Remediación |
|---|---|---|
| SEC-01 | SHA-256 sin salt | Migrado a **bcrypt** (12 rounds, salt automático) con compatibilidad hacia atrás |
| SEC-02 | `shell=True` + blacklist evasible | `shlex.split()` + bloqueo de operadores (`;`, `&&`, `\|`, backticks, `$()`) + lista ampliada |
| SEC-03 | Permisos 664 en `.env`/`.auth` | `umask 077` en `main.py` + permisos 600/700 en archivos sensibles |

### Altas (4)

| ID | Hallazgo | Remediación |
|---|---|---|
| SEC-04 | Sin protección brute-force | Lockout: 5 intentos → bloqueo 15 min |
| SEC-05 | Passphrase visible en historial Telegram | `message.delete()` + respuesta via `send_message()` |
| SEC-06 | Sin timeout de sesión | Expiración automática a 30 min de inactividad |
| SEC-07 | Path traversal via symlinks | 10 rutas bloqueadas + detección de symlinks fuera de zona |

### Media/Baja (6)

| ID | Hallazgo | Remediación |
|---|---|---|
| SEC-08 | Backup sin cifrar | GPG AES-256 (interactivo + batch via `BACKUP_PASSPHRASE`) |
| SEC-09 | Core dumps filtran credenciales | `RLIMIT_CORE = 0` |
| SEC-10 | `.gitignore` incompleto | Agregado `memory_vault/`, `*.img`, `backups/` |
| SEC-11 | systemd sin hardening completo | 12 directivas: `SystemCallFilter`, `RestrictNamespaces`, `UMask=0077`, etc. |
| SEC-12 | Errores filtran info interna | Mensajes genéricos al usuario, detalle solo en logs |
| SEC-13 | Clave Fernet sin validar | Validación de longitud (44 bytes) + manejo de `InvalidToken` |

### Dependencia agregada

- `bcrypt 5.0.0`
\n\n### � Auditoría de Seguridad — Skills Nuevos (2026-02-20)

11 vulnerabilidades encontradas y remediadas en los 6 skills nuevos:

### Alta (5)

| ID | Archivo | Remediación |
|---|---|---|
| SEC-N01 | database_manager | SQL injection en PRAGMA → regex valida nombre tabla |
| SEC-N02 | database_manager | SQL arbitrario → SELECT-only en queries, bloqueo ATTACH/LOAD |
| SEC-N04 | api_client | SSRF via DNS rebinding → `gethostbyname()` + `ipaddress.is_private` |
| SEC-N09 | system_config | Command injection en servicio → regex `[a-zA-Z0-9_.@-]+` |
| SEC-N10 | system_config | Command injection en timezone/hostname → validación de formato |

### Media (4)

| ID | Archivo | Remediación |
|---|---|---|
| SEC-N03 | database_manager | Path traversal en db_name → sanitización alfanumérica |
| SEC-N05 | api_client | Faltaban 169.254.x.x, IPv6 privado → añadidos |
| SEC-N06 | media_tools | Sin validación de ruta → restringido a /home y /tmp |
| SEC-N08 | device_access | Escritura a ruta arbitraria → validación output_path |

### Baja (1)

| ID | Archivo | Remediación |
|---|---|---|
| SEC-N07 | media_tools | Inyección via formato → solo alfanumérico |
\n\n

## Estructura de Directorios

```
Py-Assistant/
├── main.py
├── requirements.txt
├── .env
├── README.md
├── wizard.py
│
├── core/
│   ├── assistant.py
│   ├── auth.py
│   ├── healthcheck.py
│   ├── llm_engine.py
│   ├── memory_manager.py
│   └── soul.py
│
├── mcp/
│   ├── mcp_router.py
│   └── tools.py
│
├── skills/
│   ├── firecrawl/               # Módulo Scraping Avanzado
│   ├── skill_manager.py
│   ├── web_browser.py
│   ├── desktop_manager.py
│   ├── api_client.py
│   ├── device_access.py
│   ├── voice_recognition.py
│   ├── tts.py
│   ├── system_config.py
│   └── (otros 16 skills...)
│
├── security/
│   └── encryptor.py
│
├── communication/
│   ├── telegram_bot.py
│   └── message_router.py
│
├── config/
│   ├── settings.yaml
│   └── security_config.yaml
│
├── scripts/
│   ├── start.sh
│   ├── vault_mount.sh
│   ├── vault_backup.sh
│   └── asistente@.service
│
├── memory_vault/
│   ├── soul_state.md
│   ├── user_profile.md
│   ├── user_preferences.md
│   └── feedback_log.md
│
└── logs/
    ├── assistant.log
    ├── errors.log
    └── security.log
```

## Primeros Pasos

Si desea iniciar la instancia local en ambiente de desarrollo:

1. Clonar el repositorio y configurar el entorno virtual:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
2. Configurar las variables de entorno en el archivo `.env` (proveer `TELEGRAM_BOT_TOKEN`, `GROQ_API_KEY`, herramientas terceras como `FIRECRAWL_API_KEY`, etc).
3. Iniciar el engine orquestador en front-plane:
   ```bash
   python3 main.py
   ```
4. Navegar a Telegram y entablar el asistente mediante `/start` para iniciar el flujo de onboarding (wizard).

---

## 🧠 Estado del Proyecto (Bitácora Detallada)

> Última actualización: 2026-02-20

---

### ✅ Fase 1 — Completada

### Infraestructura
- [x] Estructura de directorios, requirements, .env, .gitignore, start.sh
- [x] `config/settings.yaml` — Groq + `llama-3.3-70b-versatile`
- [x] `config/security_config.yaml` — reglas de red y filesystem

### Core
- [x] `core/soul.py` — Identidad con género + nombre usuario
- [x] `core/memory_manager.py` — Memoria persistente + consolidación LLM
- [x] `core/llm_engine.py` — Groq/OpenAI/Anthropic + Ollama
- [x] `core/auth.py` — SHA-256 passphrases
- [x] `core/assistant.py` — Orquestador con tool calling loop
- [x] `main.py` — Entry point

### Comunicación
- [x] `communication/telegram_bot.py` — Bot con pairing seguro, onboarding 6 pasos, /reset

### MCP — 62 herramientas
- [x] `obtener_fecha_hora` (español), `guardar_nota`, `guardar_hecho`
- [x] `buscar_notas`, `listar_notas`
- [x] `listar_directorio`, `leer_archivo`, `escribir_archivo`
- [x] `ejecutar_comando`, `buscar_web`, `extraer_texto_web`
- [x] `info_sistema`, `abrir_aplicacion`
- [x] `leer_emails`, `enviar_email`
- [x] `copiar_portapapeles`, `pegar_portapapeles`
- [x] `leer_pdf`, `buscar_en_pdf`
- [x] `git_status`, `git_log`
- [x] `consultar_db`, `ejecutar_sql`
- [x] `resumir_texto`, `traducir_texto`
- [x] `consultar_api`, `clima`, `divisa`
- [x] `convertir_media`, `info_media`
- [x] `captura_pantalla`, `sensores`
- [x] `info_sistema_completa`, `config_red`
- [x] `copiar_archivo`, `mover_archivo`, `eliminar_archivo`
- [x] `buscar_archivos`, `info_archivo`
- [x] `listar_procesos`, `terminar_proceso`
- [x] `listar_usuarios_sistema`
- [x] `analizar_sentimiento`, `detectar_entidades`
- [x] `transcribir_audio`, `generar_texto`, `clasificar_texto`
- [x] `describir_imagen`, `ocr_imagen`
- [x] `google_maps`, `clima_detallado`, `noticias`
- [x] `ha_dispositivos`, `ha_estado`, `ha_controlar`, `ha_servicio`
- [x] `texto_a_voz`, `listar_plugins`, `ejecutar_plugin`
- [x] `calendario_eventos`, `calendario_buscar`, `calendario_crear`

### Skills — 19 activos
- [x] `skills/web_browser.py` — search, get_text, get_links
- [x] `skills/desktop_manager.py` — 8 acciones de control
- [x] `skills/clipboard_manager.py` — copiar, pegar, historial, templates
- [x] `skills/pdf_reader.py` — extraer texto, buscar, metadata de PDFs
- [x] `skills/git_manager.py` — status, log, diff, branches, blame
- [x] `skills/database_manager.py` — SQLite: crear, consultar, insertar, schema
- [x] `skills/text_analyzer.py` — resumir, traducir, sentimiento, corregir (via LLM)
- [x] `skills/api_client.py` — REST client + clima, divisas, IP info (red local bloqueada)
- [x] `skills/media_tools.py` — convertir, redimensionar, extraer audio (ffmpeg/ImageMagick)
- [x] `skills/device_access.py` — captura pantalla, webcam, audio, sensores
- [x] `skills/system_config.py` — info sistema, red, servicios, disco, paquetes
- [x] `skills/voice_recognition.py` — transcribir audio (Whisper API / local)
- [x] `skills/text_generator.py` — creativo, codigo, formal, brainstorm, estructurado
- [x] `skills/ml_engine.py` — clasificacion zero-shot, similitud, prediccion, clustering
- [x] `skills/deep_learning.py` — describir imagenes, OCR, clasificacion visual
- [x] `skills/api_services.py` — Google Maps, OpenWeatherMap, NewsAPI
- [x] `skills/home_assistant.py` — controlar luces, sensores, switches, escenas, automatizaciones
- [x] `skills/tts.py` — Text-to-Speech (4 motores)
- [x] `skills/google_calendar.py` — Integracion con API de Google Calendar
- [x] `plugins/` — Sistema de plugins externos (ej: `example_plugin.py`)

---

### ✅ Fase 2 — Completada

### Seguridad y Producción
- [x] Rate limiting anti-flood (10 msgs/60s)
- [x] Logs rotativos: `assistant.log`, `errors.log` (con backtrace), `security.log` (auditoría)
- [x] `scripts/vault_backup.sh` — Backup cifrado con GPG (AES-256) + rotación
- [x] `scripts/vault_setup.sh` — Setup LUKS2 (una vez)
- [x] `scripts/vault_mount.sh` — Mount/unmount/status
- [x] `scripts/asistente@.service` — systemd con 12 directivas de hardening
- [x] Email MCP: `leer_emails` (IMAP), `enviar_email` (SMTP)
- [x] `.env` actualizado con config de email

### Tests automatizados — 105 tests
- [x] `tests/test_security.py` — 30 tests: SQL injection, path traversal, SSRF, command injection, entity validation
- [x] `tests/test_mcp.py` — Registro de 56+ tools, schemas válidos, ejecución funcional
- [x] `tests/test_skills.py` — 17 skills: imports, SKILL_NAME, execute(), SkillManager, validaciones
- [x] `tests/test_llm_engine.py` — Factory multi-LLM, base_url, bcrypt auth, lockout

### Robustez de producción
- [x] `core/healthcheck.py` — Verificación al inicio: Python deps, credenciales, herramientas del SO, directorios
- [x] `requirements.txt` actualizado — bcrypt, SpeechRecognition (opcional), sin groq SDK redundante

---

### 🛠 Correcciones de Estabilidad (2026-02-20)

- [x] **Groq `tool_use_failed`** — Límite de 20 herramientas por request al LLM (de 52 registradas)
- [x] **`argument ** must be mapping`** — Manejo defensivo de `arguments: null` en tool calls
- [x] **`property 'type' missing`** — Añadido `"type": "function"` a tool_calls serializados
- [x] **Retry mejorado** — Limpia `tool_calls` y mensajes `role: tool` antes de reintentar sin herramientas
- [x] **Aprendizaje continuo** — `save_preference()`, `save_feedback()`, `get_preferences()` en memory_manager
- [x] **Soporte Multi-LLM Unificado** — Arquitectura basada en `base_url` para 9+ proveedores (Groq, OpenAI, Anthropic, Grok, Gemini, Ollama, Cerebras, Qwen, DeepSeek, Kimi).

---

### �🔲 Fase 3 — Pendiente (Avanzado)

- [ ] Motor LLM local con Ollama (requiere hardware)
- [ ] Despliegue en Orange Pi Zero 2W
- [x] MCP: Integración con Google Calendar (requiere API key)
- [ ] Interfaz web administrativa
- [x] Sistema de plugins para skills de terceros
- [x] Voice-to-text (Whisper API + speech_recognition)
- [x] Text-to-voice (TTS)
- [ ] Multi-usuario con roles
- [ ] Dashboard de monitoreo
- [ ] Configurar API keys: `GOOGLE_MAPS_KEY`, `OPENWEATHER_KEY`, `NEWS_API_KEY`

---
