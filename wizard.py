#!/usr/bin/env python3
"""
wizard.py -- Asistente de Configuracion Interactiva para Py-Assistant.

Fase 1: Pre-vuelo (Auto-VENV)
Detecta si esta corriendo en un entorno virtual. Si no, lo crea, instala
las dependencias de requirements.txt y se re-ejecuta a si mismo dentro del venv.

Fase 2: TUI con Rich
Utiliza la libreria 'rich' para guiar al usuario a traves de la configuracion
del entorno (.env), seleccion del motor LLM (Local vs Cloud), recoleccion
de TODAS las credenciales opcionales y creacion de la boveda segura.
"""
import os
import sys
import subprocess
from pathlib import Path

# =======================================================================
# FASE 1: PRE-VUELO (VENV AUTO-SETUP)
# =======================================================================
PROJECT_ROOT = Path(__file__).parent
VENV_PATH = PROJECT_ROOT / "venv"
PYTHON_BIN = VENV_PATH / "bin" / "python3"
PIP_BIN = VENV_PATH / "bin" / "pip"

def is_in_venv():
    return sys.prefix != sys.base_prefix

def run_preflight():
    print("=" * 50)
    print(" Py-Assistant -- Inicializando Pre-vuelo...")
    print("=" * 50)
    
    if not VENV_PATH.exists():
        print("\n[!] No se encontro un entorno virtual (venv).")
        resp = input("¿Deseas crear uno automaticamente e instalar las dependencias necesarias? [Y/n]: ").strip().lower()
        if resp not in ('', 'y', 'yes', 's', 'si'):
            print("Abortando. El asistente requiere un entorno virtual para operar limpiamente.")
            sys.exit(1)
            
        print("\n-> Creando entorno virtual en ./venv ...")
        subprocess.check_call([sys.executable, "-m", "venv", "venv"])
        
        print("-> Instalando requirements.txt (esto puede tomar un minuto)...")
        subprocess.check_call([str(PIP_BIN), "install", "-r", "requirements.txt"])
        
        print("\n✅ Entorno Virtual creado e hidratado con exito.")
        print("-> Re-lanzando el asistente dentro del nuevo entorno...\n")
        
        # Re-execute this script inside the venv
        os.execl(str(PYTHON_BIN), str(PYTHON_BIN), *sys.argv)
        
    else:
        # Venv exists but we are not inside it and not running it directly?
        # Handled by checking if we have rich. If not, maybe we should re-exec via venv.
        try:
            import rich
        except ImportError:
            print("\n[!] El entorno virtual existe pero no estamo usando su binario, o le falta 'rich'.")
            print("-> Instalando posibles dependencias faltantes...")
            subprocess.check_call([str(PIP_BIN), "install", "-r", "requirements.txt"])
            print("-> Re-lanzando el asistente dentro del entorno...\n")
            os.execl(str(PYTHON_BIN), str(PYTHON_BIN), *sys.argv)


# Ejecutamos el prevuelo antes de intentar importar cualquier libreria de terceros
if not is_in_venv() or not VENV_PATH.exists():
     run_preflight()

# =======================================================================
# FASE 2: ASISTENTE INTERACTIVO (RICH TUI)
# =======================================================================
try:
    import yaml
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm
    from rich.table import Table
    from rich.align import Align
    from rich.text import Text
except ImportError as e:
    # Si aun falla tras el pre-vuelo, abortamos
    print(f"Error fatal, dependencias no resueltas: {e}")
    sys.exit(1)

console = Console()
ENV_PATH = PROJECT_ROOT / ".env"
SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"

def print_banner():
    console.clear()
    banner = Text("Py-Assistant Setup", style="bold cyan", justify="center")
    banner.append("\nUnidad A.R.I.A - Asistente Personal y Daemon Modular", style="italic blue")
    
    panel = Panel(
        Align.center(banner),
        border_style="magenta",
        padding=(1, 2)
    )
    console.print(panel)
    console.print()

def check_system_health():
    console.print("[bold yellow]1. Comprobando Salud del Sistema y Opt-Tools...[/]")
    sys.path.insert(0, str(PROJECT_ROOT))
    
    try:
        from core.healthcheck import run_healthcheck
        config_basico = {"llm": {"provider": "groq"}, "telegram": {}}
        issues = run_healthcheck(config_basico)
        
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Categoria", style="dim", width=12)
        table.add_column("Estado", justify="center", width=15)
        table.add_column("Mensaje")

        if issues["critical"]:
            for c in issues["critical"]:
                table.add_row("CRÍTICO", "[red]❌ Fallo[/red]", c)
        else:
             table.add_row("CRÍTICO", "[green]✅ O.K.[/green]", "Dependencias Py Base instaladas.")

        if issues["warnings"]:
           for w in issues["warnings"]:
               if "API key" in w or "TELEGRAM_BOT_TOKEN" in w or "APIs opcionales" in w:
                   continue
               table.add_row("HERRAMIENTA", "[yellow]⚠️ Faltante[/yellow]", w[:65] + "...")
        else:
           table.add_row("OPTIONALES", "[green]✅ O.K.[/green]", "Todas las opt-tools (ffmpeg, sensors) ok.")
           
        console.print(table)
        console.print("[dim italic]* Las herramientas faltantes (ej. ffmpeg) no previenen arrancar el bot, solo limitan habilidades.[/]\n")
                
    except Exception as e:
        console.print(f"[red]Error al ejecutar healthcheck: {e}[/]")
    console.print()

def setup_llm_engine():
    console.print("[bold yellow]2. Configuración del Núcleo (Motor LLM)[/]")
    console.print("Py-Assistant respalda motores en la Nube (APIs) y Locales (Ollama Offline).")
    
    opciones = ["Groq (Recomendado, muy rápido)", "OpenAI", "Anthropic", "Ollama (Modelos Locales, Offline)", "Gemini", "DeepSeek"]
    for i, opt in enumerate(opciones, 1):
        console.print(f"  [cyan]{i}.[/] {opt}")
        
    seleccion = Prompt.ask("Selecciona el proveedor principal", choices=[str(i) for i in range(1, len(opciones)+1)], default="1")
    
    provider_map = {
        "1": "groq", "2": "openai", "3": "anthropic", "4": "ollama", "5": "gemini", "6": "deepseek"
    }
    
    provider_selected = provider_map[seleccion]
    
    config = {}
    if SETTINGS_PATH.exists():
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
            
    if "llm" not in config:
        config["llm"] = {}
        
    config["llm"]["provider"] = provider_selected
    api_key_needed = None
    
    if provider_selected == "ollama":
        config["llm"]["mode"] = "local"
        modelo = Prompt.ask("¿Qué modelo local deseas usar?", default="phi3:mini")
        if "local" not in config["llm"]:
             config["llm"]["local"] = {}
        config["llm"]["local"]["model"] = modelo
        console.print(f"[green]✔ Modo Offline activado usando '{modelo}'.[/]\n")
    else:
        config["llm"]["mode"] = "api"
        ejemplos = {
            "groq": "llama-3.3-70b-versatile", "openai": "gpt-4o", 
            "anthropic": "claude-3-5-sonnet-20241022", "gemini": "gemini-1.5-pro",
            "deepseek": "deepseek-chat"
        }
        modelo = Prompt.ask(f"¿Qué modelo deseas instanciar de {provider_selected}?", default=ejemplos.get(provider_selected, ""))
        config["llm"]["model"] = modelo
        api_key_needed = f"{provider_selected.upper()}_API_KEY"
        console.print("")
    
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, default_flow_style=False)
        
    return api_key_needed

def setup_environment(api_key_var: str):
    console.print("[bold yellow]3. Credenciales y API Keys[/]")
    console.print("Nota: Si deseas omitir una API Key opcional, solo presiona Enter en blanco.\n")
    
    env_data = {}
    if ENV_PATH.exists():
        with open(ENV_PATH, "r") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    env_data[k] = v

    def ask_key(key_name, description, is_password=False, default_val=""):
        current = env_data.get(key_name, default_val)
        if current:
            if Confirm.ask(f"[dim]¿Mantener la clave actual para {key_name}?[/]", default=True):
                return current
        prompt_text = f"Introduce [bold cyan]{key_name}[/] ({description})"
        return Prompt.ask(prompt_text, password=is_password, default="")

    # Core Keys
    token = ask_key("TELEGRAM_BOT_TOKEN", "Crealo via @BotFather en Telegram", is_password=True)
    if token: env_data["TELEGRAM_BOT_TOKEN"] = token
    
    if api_key_var:
        val = ask_key(api_key_var, "Clave del Motor de Lenguaje Principal", is_password=True)
        if val: env_data[api_key_var] = val

    console.print("\n[dim]--- Integraciones Opcionales ---[/]")
    opt_keys = [
        ("FIRECRAWL_API_KEY", "Para habilitar el Web Scraping Avanzado"),
        ("OPENWEATHER_KEY", "Para reportes de clima detallados"),
        ("NEWS_API_KEY", "Para la skill de busqueda de noticias"),
        ("GOOGLE_MAPS_KEY", "Habilita geocoding y estimaciones de ruta"),
        ("HASS_TOKEN", "Long-Lived Access Token de Home Assistant"),
        ("HASS_URL", "URL Base de Home Assistant (ej. http://192.168.1.100:8123)"),
        ("OPENAI_API_KEY", "Usada para OCR/Vision/Transcribcion si tu LLM principal es otro")
    ]
    
    for key_name, desc in opt_keys:
        # Avoid asking for OPENAI_API_KEY twice
        if key_name == api_key_var:
            continue
        val = ask_key(key_name, desc, is_password=("URL" not in key_name))
        if val:
            env_data[key_name] = val
        elif not val:
            # Si el usuario oprimio ENTER sin proveer valor y no quiso mantener el viejo, lo removemos.
            env_data.pop(key_name, None)

    with open(ENV_PATH, "w") as f:
        for k, v in env_data.items():
            f.write(f"{k}={v}\n")
    if os.name != "nt":
        os.chmod(ENV_PATH, 0o600)

    console.print("\n[green]✔ Archivo .env asegurado y poblado con las llaves proporcionadas.[/]\n")

def setup_vault():
    console.print("[bold yellow]4. Bóveda de Memoria (Vault)[/]")
    console.print("Todo lo que Py-Assistant lea de ti o discuta será persistido en una memoria cifrada.")
    
    vault_path = PROJECT_ROOT / "memory_vault"
    vault_path.mkdir(exist_ok=True)
    auth_file = vault_path / ".auth"
    
    if auth_file.exists():
         console.print("[dim]✔ Contraseña maestra y boveda ya configuradas previamente.[/]\n")
         return
         
    console.print("Por favor, crea una contraseña maestra. Te será solicitada en Telegram la primera vez para enlazar tu dispositivo de forma segura.")
    passphrase = Prompt.ask("[bold cyan]Inventa una contraseña maestra para Py-Assistant[/]", password=True)
    
    try:
        from core.auth import AuthManager
        auth_mgr = AuthManager(auth_file)
        auth_mgr.setup("passphrase", passphrase)
        console.print("[green]✔ Identidad y Vault protegidos estáticamente por Bcrypt.[/]\n")
    except Exception as e:
        console.print(f"[red]Error al inicializar la protección Bcrypt: {e}[/]\n")


def finish_wizard():
    console.print("[bold green]=============================================[/]")
    console.print("[bold green]  🎉 CONFIGURACION COMPLETADA EXITOSAMENTE  🎉[/]")
    console.print("[bold green]=============================================[/]")
    console.print("Py-Assistant esta listo para entrar en fase operativa.")
    
    if Confirm.ask("\n¿Arrancar el engine orquestador ahora mismo? ([bold green]main.py[/bold green])"):
        console.print("\nIniciando secuencia de lanzamiento...")
        os.execl(str(PYTHON_BIN), str(PYTHON_BIN), str(PROJECT_ROOT / "main.py"))
    else:
        console.print("\nDe acuerdo. Para arrancar mas tarde, ejecuta:")
        console.print(f"[bold cyan]source venv/bin/activate && python3 main.py[/]")

if __name__ == "__main__":
    try:
        print_banner()
        check_system_health()
        api_key_env = setup_llm_engine()
        setup_environment(api_key_env)
        setup_vault()
        finish_wizard()
    except KeyboardInterrupt:
        console.print("\n[bold red]Wizard cancelado por el usuario.[/]")
        sys.exit(0)
