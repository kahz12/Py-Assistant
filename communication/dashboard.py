"""
communication/dashboard.py -- Panel de monitoreo local expandido (Feature 2 + 6).

Servidor HTTP liviano (stdlib, sin dependencias) en http://localhost:8765.
Auto-refresh cada 15s con sidebar de navegacion.

Secciones:
  / (Overview)  Uptime, scheduler, lanes, WAQ, usuarios
  /memory       Notas recientes del vault (ultimas 20)
  /logs         Ultimas 100 lineas de assistant.log en tiempo real
  /agents       Tabla de los 12 sub-agentes con roles y whitelists
  /status       JSON puro del estado para integraciones externas
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable, Optional
from loguru import logger

_START_TIME = time.time()
VERSION = "Py-Assistant v1.0"

SIDEBAR = """
<nav>
  <a href="/">📊 Overview</a>
  <a href="/memory">🧠 Memoria</a>
  <a href="/logs">📋 Logs</a>
  <a href="/agents">🤖 Agentes</a>
</nav>"""

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', monospace; background: #0d0d12; color: #d4d4d8; display: flex; min-height: 100vh; }
nav { width: 160px; background: #111118; padding: 1.5rem 0; display: flex; flex-direction: column; gap: 4px; border-right: 1px solid #1e1e2e; flex-shrink: 0; }
nav a { display: block; padding: 10px 18px; color: #888; text-decoration: none; font-size: 0.9em; border-left: 3px solid transparent; transition: all 0.15s; }
nav a:hover { color: #7ec8e3; background: #1a1a2e; border-left-color: #7ec8e3; }
main { flex: 1; padding: 1.5rem 2rem; overflow: auto; }
h1 { color: #7ec8e3; font-size: 1.4em; margin-bottom: 0.2rem; }
h2 { color: #a0d4b4; font-size: 1em; border-bottom: 1px solid #1e1e2e; padding-bottom: 4px; margin: 1.2rem 0 0.6rem; }
.meta { color: #555; font-size: 0.78em; margin-bottom: 1.2rem; }
table { border-collapse: collapse; width: 100%; margin-bottom: 1.2rem; font-size: 0.88em; }
th { background: #1a1a2e; color: #7ec8e3; padding: 6px 10px; text-align: left; }
td { padding: 5px 10px; border-bottom: 1px solid #1a1a2e; vertical-align: top; }
.ok { color: #4caf50; } .warn { color: #f0a500; } .err { color: #f44336; }
.badge-admin { color: #ffd700; } .badge-viewer { color: #7ec8e3; }
.log-box { background: #0a0a0f; padding: 1rem; border-radius: 6px; font-size: 0.78em; line-height: 1.5; max-height: 70vh; overflow-y: auto; white-space: pre-wrap; word-break: break-all; }
.note-item { background: #111118; border: 1px solid #1e1e2e; border-radius: 4px; padding: 8px 12px; margin-bottom: 8px; font-size: 0.85em; }
.note-item .note-meta { color: #555; font-size: 0.78em; margin-top: 4px; }
.wl { color: #777; font-size: 0.75em; }
"""


def _uptime_str():
    secs = int(time.time() - _START_TIME)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s"


def _page(title: str, content: str, refresh: int = 15) -> str:
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="{refresh}">
  <title>{title} — Py-Assistant</title>
  <style>{CSS}</style>
</head>
<body>
{SIDEBAR}
<main>
  <h1>Py-Assistant Dashboard</h1>
  <p class="meta">{VERSION} &nbsp;|&nbsp; Uptime: {_uptime_str()} &nbsp;|&nbsp; {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}</p>
  {content}
</main>
</body>
</html>"""


class _DashboardHandler(BaseHTTPRequestHandler):
    collector: "Dashboard" = None  # inyectado por Dashboard.start()

    def _respond(self, body: str, content_type: str = "text/html; charset=utf-8", status: int = 200):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", len(b))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            self._respond(_page("Overview", self.collector._render_overview()))
        elif path == "/memory":
            self._respond(_page("Memoria", self.collector._render_memory()))
        elif path == "/logs":
            self._respond(_page("Logs", self.collector._render_logs(), refresh=10))
        elif path == "/agents":
            self._respond(_page("Agentes", self.collector._render_agents()))
        elif path == "/status":
            self._respond(json.dumps(self.collector._collect_data(), ensure_ascii=False), "application/json")
        else:
            self._respond("<h2>404 — No encontrado</h2>", status=404)

    def log_message(self, fmt, *args):
        logger.debug(f"[Dashboard] {fmt % args}")


class Dashboard:
    """Panel de monitoreo HTTP local expandido."""

    def __init__(
        self,
        lane_queue=None,
        scheduler=None,
        user_registry=None,
        health_fn: Optional[Callable] = None,
        waq_dir: Optional[Path] = None,
        vault_path: Optional[Path] = None,
        log_path: Optional[Path] = None,
    ):
        self._lane_queue = lane_queue
        self._scheduler = scheduler
        self._user_registry = user_registry
        self._health_fn = health_fn
        self._waq_dir = waq_dir
        self._vault_path = vault_path
        self._log_path = log_path
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Data collection
    # ------------------------------------------------------------------

    def _collect_data(self) -> dict:
        data = {
            "uptime": _uptime_str(),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "scheduler_jobs": [],
            "lanes": {},
            "users": [],
            "health": {},
            "waq_orphans": 0,
            "notes_count": 0,
        }
        if self._scheduler and hasattr(self._scheduler, "_scheduler") and self._scheduler._scheduler:
            for job in self._scheduler._scheduler.get_jobs():
                data["scheduler_jobs"].append({
                    "id": job.id,
                    "next_run": str(job.next_run_time) if job.next_run_time else "—",
                })
        if self._lane_queue:
            data["lanes"] = self._lane_queue.all_lanes_status()
        if self._user_registry:
            data["users"] = self._user_registry.list_users()
        if self._health_fn:
            try:
                raw = self._health_fn()
                data["health"] = {k: (f"{len(v)} issues" if isinstance(v, list) and v else "OK")
                                  for k, v in (raw.items() if isinstance(raw, dict) else {}.items())}
            except Exception:
                pass
        if self._waq_dir and self._waq_dir.exists():
            data["waq_orphans"] = len(list(self._waq_dir.glob("*.json")))
        if self._vault_path:
            notes_dir = self._vault_path / "notes"
            if notes_dir.exists():
                data["notes_count"] = len(list(notes_dir.glob("*.md")) + list(notes_dir.glob("*.txt")))
        return data

    # ------------------------------------------------------------------
    # Renderers
    # ------------------------------------------------------------------

    def _render_overview(self) -> str:
        d = self._collect_data()

        # Scheduler
        sched_rows = "".join(
            f"<tr><td><code>{j['id']}</code></td><td>{j['next_run']}</td></tr>"
            for j in d["scheduler_jobs"]
        ) or "<tr><td colspan='2' class='warn'>Sin jobs activos</td></tr>"

        # Lanes
        lane_rows = "".join(
            f"<tr><td><code>{lid}</code></td><td>{info['pending']}</td>"
            f"<td class='{'ok' if info['active'] else ''}'>{'🟢 Activo' if info['active'] else '⬜ Inactivo'}</td></tr>"
            for lid, info in d["lanes"].items()
        ) or "<tr><td colspan='3' class='meta'>Sin lanes activos</td></tr>"

        # Users
        user_rows = "".join(
            f"<tr><td>{u['user_id']}</td><td>{u.get('username','—')}</td>"
            f"<td class='badge-{'admin' if u['role']=='admin' else 'viewer'}'>{'🔑' if u['role']=='admin' else '👁'} {u['role']}</td>"
            f"<td class='meta'>{u.get('created_at','—')}</td></tr>"
            for u in d["users"]
        ) or "<tr><td colspan='4' class='meta'>Sin usuarios</td></tr>"

        # Health
        health_rows = "".join(
            f"<tr><td>{k}</td><td class='{'ok' if v=='OK' else 'warn'}'>{v}</td></tr>"
            for k, v in d["health"].items()
        ) or "<tr><td colspan='2' class='meta'>—</td></tr>"

        waq_cls = "warn" if d["waq_orphans"] > 0 else "ok"
        waq_txt = f"<span class='{waq_cls}'>{d['waq_orphans']} item(s) pendientes</span>"

        return f"""
<h2>Write-Ahead Queue</h2>
<p>WAQ orphans: {waq_txt} &nbsp;|&nbsp; Notas indexadas: {d['notes_count']}</p>

<h2>Scheduler — Jobs Autonomos</h2>
<table><tr><th>Job ID</th><th>Proxima ejecucion</th></tr>{sched_rows}</table>

<h2>Lane Queue</h2>
<table><tr><th>Lane ID</th><th>Pendientes</th><th>Estado</th></tr>{lane_rows}</table>

<h2>Usuarios Registrados</h2>
<table><tr><th>User ID</th><th>Username</th><th>Rol</th><th>Creado</th></tr>{user_rows}</table>

<h2>Health del Sistema</h2>
<table><tr><th>Componente</th><th>Estado</th></tr>{health_rows}</table>"""

    def _render_memory(self) -> str:
        if not self._vault_path:
            return "<p class='warn'>vault_path no configurado.</p>"
        notes_dir = self._vault_path / "notes"
        if not notes_dir.exists():
            return "<p class='meta'>Sin notas en el vault.</p>"

        files = sorted(notes_dir.glob("*.*"), key=lambda f: f.stat().st_mtime, reverse=True)[:20]
        if not files:
            return "<p class='meta'>Sin notas guardadas.</p>"

        items = ""
        for f in files:
            mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime))
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")[:300]
            except Exception:
                content = "(no se pudo leer)"
            content_escaped = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            items += f"""<div class='note-item'>
<strong>{f.name}</strong>
<pre style='margin-top:4px;white-space:pre-wrap'>{content_escaped}{'…' if len(content)==300 else ''}</pre>
<p class='note-meta'>Modificado: {mtime} &nbsp;|&nbsp; {f.stat().st_size} bytes</p>
</div>"""

        # Tambien mostrar long_term_memory.md si existe
        lt = self._vault_path / "long_term_memory.md"
        lt_section = ""
        if lt.exists():
            lt_content = lt.read_text(encoding="utf-8", errors="ignore")[:1000]
            lt_escaped = lt_content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            lt_section = f"<h2>Memoria a Largo Plazo</h2><div class='log-box'>{lt_escaped}</div>"

        return f"<h2>Notas Recientes (últimas 20)</h2>{items}{lt_section}"

    def _render_logs(self) -> str:
        log_file = self._log_path or Path("logs/assistant.log")
        if not log_file.exists():
            return "<p class='warn'>Archivo de log no encontrado.</p>"
        try:
            lines = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()[-100:]
            content = "\n".join(lines)
            content_escaped = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        except Exception as e:
            return f"<p class='err'>Error leyendo log: {e}</p>"
        return f"""<h2>assistant.log — Últimas 100 líneas</h2>
<p class='meta'>Auto-refresh cada 10s &nbsp;|&nbsp; <a href='/logs' style='color:#7ec8e3'>Refrescar ahora</a></p>
<div class='log-box'>{content_escaped}</div>"""

    def _render_agents(self) -> str:
        try:
            from core.agent_spawner import PREDEFINED_ROLES
        except ImportError:
            return "<p class='err'>agent_spawner no disponible.</p>"

        rows = ""
        for role_key, cfg in PREDEFINED_ROLES.items():
            whitelist = cfg.tools_whitelist or ["(todas)"]
            wl_str = f"<span class='wl'>{', '.join(whitelist[:5])}</span>"
            if cfg.tools_whitelist and len(cfg.tools_whitelist) > 5:
                wl_str += f"<span class='wl'> +{len(cfg.tools_whitelist)-5} más</span>"
            rows += f"""<tr>
<td><code>{role_key}</code></td>
<td>{cfg.name}</td>
<td>{wl_str}</td>
<td class='meta' style='max-width:300px;font-size:0.75em'>{cfg.system_prompt[:120]}…</td>
</tr>"""

        return f"""<h2>Sub-Agentes — {len(PREDEFINED_ROLES)} roles pre-definidos</h2>
<table>
<tr><th>Rol</th><th>Nombre</th><th>Herramientas</th><th>Prompt (resumen)</th></tr>
{rows}
</table>"""

    # ------------------------------------------------------------------
    # Server lifecycle
    # ------------------------------------------------------------------

    def start(self, host: str = "127.0.0.1", port: int = 8765):
        _DashboardHandler.collector = self
        self._server = HTTPServer((host, port), _DashboardHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info(f"[Dashboard] Panel disponible en http://{host}:{port}")

    def shutdown(self):
        if self._server:
            self._server.shutdown()
            logger.info("[Dashboard] Detenido.")
