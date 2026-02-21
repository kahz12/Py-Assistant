"""
skills/git_manager.py -- Gestion de repositorios Git desde el asistente.

Proporciona operaciones de lectura sobre repositorios Git:
  - Estado del repositorio (status, branch actual).
  - Historial de commits formateado.
  - Diffs legibles entre commits o del working tree.
  - Listado de branches.
  - Informacion de un commit especifico.

No realiza operaciones de escritura (commit, push, merge) por seguridad.
Para eso, usar el MCP tool 'ejecutar_comando' con supervision.

Dependencia: git (CLI) instalado en el sistema.

Interfaz del skill:
    SKILL_NAME = "git_manager"
    execute(action, repo_path=None, n=None, commit=None, file_path=None) -> str
"""
import subprocess
from pathlib import Path
from loguru import logger

SKILL_NAME = "git_manager"
SKILL_DESCRIPTION = "Git: status, log, diff, branches, info de commits."


def execute(
    action: str,
    repo_path: str = None,
    n: int = None,
    commit: str = None,
    file_path: str = None,
) -> str:
    """
    Punto de entrada principal del skill.

    Acciones disponibles:
      - 'status'   : Estado del repositorio (branch, cambios).
      - 'log'      : Ultimos N commits (default: 10).
      - 'diff'     : Cambios en el working tree o de un commit especifico.
      - 'branches' : Lista de branches locales y remotas.
      - 'show'     : Detalle de un commit especifico.
      - 'blame'    : Anotaciones de un archivo (quien modifico cada linea).

    Args:
        action: Accion a ejecutar.
        repo_path: Ruta al repositorio. Si es None, usa el directorio actual.
        n: Numero de commits a mostrar (para log).
        commit: Hash o referencia de commit (para show, diff).
        file_path: Ruta a un archivo (para blame, diff).

    Returns:
        Resultado de la accion como texto.
    """
    actions = {
        "status": lambda: _status(repo_path),
        "log": lambda: _log(repo_path, n or 10),
        "diff": lambda: _diff(repo_path, commit, file_path),
        "branches": lambda: _branches(repo_path),
        "show": lambda: _show(repo_path, commit),
        "blame": lambda: _blame(repo_path, file_path),
    }

    if action not in actions:
        available = ", ".join(actions.keys())
        return f"Accion no reconocida: {action}. Opciones: {available}"

    return actions[action]()


# ---------------------------------------------------------------------------
# Git runner
# ---------------------------------------------------------------------------

def _run_git(repo_path: str, *args) -> tuple[str, str]:
    """
    Ejecuta un comando git en el repositorio indicado.

    Args:
        repo_path: Ruta al repositorio.
        *args: Argumentos del comando git.

    Returns:
        Tupla (stdout, stderr). Si hay error grave, stdout esta vacio.
    """
    cwd = repo_path or "."
    path = Path(cwd)

    if not path.exists():
        return "", f"Ruta no encontrada: {cwd}"
    if not (path / ".git").exists() and not _is_inside_git(cwd):
        return "", f"No es un repositorio git: {cwd}"

    try:
        result = subprocess.run(
            ["git"] + list(args),
            capture_output=True,
            text=True,
            timeout=15,
            cwd=cwd,
        )
        return result.stdout, result.stderr
    except FileNotFoundError:
        return "", "git no esta instalado. Instala con: sudo apt install git"
    except subprocess.TimeoutExpired:
        return "", "Timeout: el comando git tardo mas de 15 segundos."
    except Exception as e:
        return "", f"Error ejecutando git: {e}"


def _is_inside_git(path: str) -> bool:
    """Verifica si la ruta esta dentro de un repositorio git."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=path,
        )
        return result.stdout.strip() == "true"
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Acciones
# ---------------------------------------------------------------------------

def _status(repo_path: str) -> str:
    """Estado del repositorio: branch actual, cambios, archivos sin rastrear."""
    # Branch actual
    branch_out, err = _run_git(repo_path, "branch", "--show-current")
    if err and not branch_out:
        return err
    branch = branch_out.strip() or "HEAD desconectado"

    # Status
    status_out, _ = _run_git(repo_path, "status", "--short")

    # Contar cambios
    lines = [l for l in status_out.strip().splitlines() if l.strip()]
    staged = sum(1 for l in lines if l[0] != " " and l[0] != "?")
    modified = sum(1 for l in lines if len(l) > 1 and l[1] == "M")
    untracked = sum(1 for l in lines if l.startswith("??"))

    # Ultimo commit
    log_out, _ = _run_git(repo_path, "log", "-1", "--format=%h %s (%ar)")
    last_commit = log_out.strip() or "Sin commits"

    result = [
        f"**Repositorio: {Path(repo_path or '.').resolve().name}**",
        f"  Branch: {branch}",
        f"  Ultimo commit: {last_commit}",
        f"  Staged: {staged} | Modificados: {modified} | Sin rastrear: {untracked}",
    ]

    if lines:
        result.append(f"\nCambios:\n```\n{status_out.strip()}\n```")

    return "\n".join(result)


def _log(repo_path: str, n: int = 10) -> str:
    """Ultimos N commits con formato legible."""
    n = min(n, 50)  # Limite de seguridad
    fmt = "--format=%C(auto)%h %C(blue)%an %C(green)(%ar) %C(reset)%s"
    out, err = _run_git(repo_path, "log", f"-{n}", "--oneline", "--decorate")
    if err and not out:
        return err

    if not out.strip():
        return "Sin historial de commits."

    return f"Ultimos {n} commits:\n\n```\n{out.strip()}\n```"


def _diff(repo_path: str, commit: str = None, file_path: str = None) -> str:
    """Muestra diferencias en el working tree o de un commit."""
    args = ["diff", "--stat"]

    if commit:
        args = ["diff", commit + "~1", commit]
    elif file_path:
        args = ["diff", "--", file_path]

    out, err = _run_git(repo_path, *args)
    if err and not out:
        return err

    if not out.strip():
        if commit:
            return f"Sin cambios en el commit {commit}."
        return "Sin cambios en el working tree."

    # Truncar diffs muy largos
    if len(out) > 5000:
        out = out[:5000] + "\n\n[... diff truncado]"

    label = f"commit {commit}" if commit else "working tree"
    return f"Diff ({label}):\n\n```diff\n{out.strip()}\n```"


def _branches(repo_path: str) -> str:
    """Lista branches locales y remotas."""
    local_out, err = _run_git(repo_path, "branch", "-v")
    if err and not local_out:
        return err

    remote_out, _ = _run_git(repo_path, "branch", "-r")

    result = []
    if local_out.strip():
        result.append(f"Branches locales:\n```\n{local_out.strip()}\n```")
    if remote_out.strip():
        result.append(f"\nBranches remotas:\n```\n{remote_out.strip()}\n```")

    return "\n".join(result) if result else "Sin branches."


def _show(repo_path: str, commit: str = None) -> str:
    """Muestra informacion detallada de un commit."""
    if not commit:
        commit = "HEAD"

    out, err = _run_git(
        repo_path, "show", commit,
        "--format=Commit: %H%nAutor: %an <%ae>%nFecha: %ai%nMensaje: %s%n%b",
        "--stat",
    )
    if err and not out:
        return err

    if not out.strip():
        return f"Commit no encontrado: {commit}"

    # Truncar si es muy largo
    if len(out) > 4000:
        out = out[:4000] + "\n\n[... truncado]"

    return f"```\n{out.strip()}\n```"


def _blame(repo_path: str, file_path: str = None) -> str:
    """Anotaciones de un archivo: quien modifico cada linea."""
    if not file_path:
        return "Error: ruta del archivo requerida."

    out, err = _run_git(repo_path, "blame", "--date=short", file_path)
    if err and not out:
        return err

    if not out.strip():
        return f"Sin anotaciones para: {file_path}"

    # Truncar archivos largos
    lines = out.strip().splitlines()
    if len(lines) > 60:
        out = "\n".join(lines[:60]) + f"\n\n[... {len(lines)} lineas en total]"

    return f"Blame de {file_path}:\n\n```\n{out.strip()}\n```"
