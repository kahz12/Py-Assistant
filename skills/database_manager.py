"""
skills/database_manager.py -- Gestion de bases de datos SQLite.

Permite crear, consultar y manipular bases de datos SQLite locales.
Util para almacenar datos estructurados, listas, inventarios,
contactos, o cualquier informacion tabulada.

Las bases de datos se almacenan en el vault para persistencia.

Interfaz del skill:
    SKILL_NAME = "database_manager"
    execute(action, db_name=None, query=None, table=None, ...) -> str
"""
import os
import sqlite3
from pathlib import Path
from loguru import logger

SKILL_NAME = "database_manager"
SKILL_DESCRIPTION = "Bases de datos SQLite: crear, consultar, insertar, listar."

# Directorio por defecto para bases de datos
_DB_DIR = Path("memory_vault/databases")


def execute(
    action: str,
    db_name: str = None,
    query: str = None,
    table: str = None,
    vault_path: str = None,
) -> str:
    """
    Punto de entrada principal del skill.

    Acciones disponibles:
      - 'query'       : Ejecuta una consulta SQL SELECT y retorna resultados.
      - 'execute'     : Ejecuta INSERT/UPDATE/DELETE/CREATE.
      - 'tables'      : Lista las tablas de una base de datos.
      - 'schema'      : Muestra el esquema de una tabla.
      - 'list_dbs'    : Lista todas las bases de datos disponibles.

    Args:
        action: Accion a ejecutar.
        db_name: Nombre de la base de datos (sin extension .db).
        query: Consulta SQL a ejecutar.
        table: Nombre de la tabla (para schema).
        vault_path: Ruta alternativa al vault.
    """
    actions = {
        "query": lambda: _query(db_name, query, vault_path),
        "execute": lambda: _execute(db_name, query, vault_path),
        "tables": lambda: _list_tables(db_name, vault_path),
        "schema": lambda: _schema(db_name, table, vault_path),
        "list_dbs": lambda: _list_dbs(vault_path),
    }

    if action not in actions:
        available = ", ".join(actions.keys())
        return f"Accion no reconocida: {action}. Opciones: {available}"

    return actions[action]()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitize_name(name: str) -> str:
    """Sanitiza un nombre para uso seguro (solo alfanumerico y guion bajo)."""
    import re
    return re.sub(r'[^a-zA-Z0-9_]', '', name)


def _get_db_path(db_name: str, vault_path: str = None) -> Path:
    """Retorna la ruta completa a la base de datos (SEC-N03: sin path traversal)."""
    base = Path(vault_path) / "databases" if vault_path else _DB_DIR
    base.mkdir(parents=True, exist_ok=True)
    # Sanitizar nombre: solo alfanumerico y guion bajo
    safe_name = _sanitize_name(db_name.replace(".db", ""))
    if not safe_name:
        safe_name = "default"
    return base / f"{safe_name}.db"


def _connect(db_name: str, vault_path: str = None) -> tuple:
    """Abre una conexion a la base de datos. Retorna (conn, error_msg)."""
    if not db_name:
        return None, "Error: nombre de base de datos requerido."
    path = _get_db_path(db_name, vault_path)
    try:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        return conn, None
    except Exception as e:
        return None, f"Error conectando a {db_name}: {e}"


def _is_safe_query(query: str, mode: str = "any") -> tuple[bool, str]:
    """Verifica que la consulta no contenga operaciones peligrosas (SEC-N02)."""
    q_lower = query.lower().strip()

    # Bloquear operaciones destructivas y peligrosas
    dangerous = [
        "drop database", "drop table", "truncate",
        "alter table", "attach", "detach", "load_extension",
        "pragma",  # Solo permitir via _schema()
    ]
    for d in dangerous:
        if d in q_lower:
            return False, f"Operacion bloqueada por seguridad: {d}"

    # Modo query: solo permitir SELECT
    if mode == "read" and not q_lower.startswith("select"):
        return False, "Solo se permiten consultas SELECT en modo lectura."

    # Modo execute: bloquear SELECT (usar query para eso)
    if mode == "write" and q_lower.startswith("select"):
        return False, "Usa 'query' para consultas SELECT."

    return True, ""


# ---------------------------------------------------------------------------
# Acciones
# ---------------------------------------------------------------------------

def _query(db_name: str, query: str, vault_path: str = None) -> str:
    """Ejecuta un SELECT y retorna los resultados formateados (SEC-N02: solo SELECT)."""
    if not query:
        return "Error: consulta SQL requerida."

    safe, msg = _is_safe_query(query, mode="read")
    if not safe:
        return msg

    conn, error = _connect(db_name, vault_path)
    if error:
        return error

    try:
        cursor = conn.execute(query)
        rows = cursor.fetchall()
        if not rows:
            conn.close()
            return "Consulta ejecutada. Sin resultados."

        # Formatear como tabla
        columns = [desc[0] for desc in cursor.description]
        header = " | ".join(columns)
        separator = "-|-".join(["-" * len(c) for c in columns])
        lines = [header, separator]
        for row in rows[:100]:
            line = " | ".join([str(row[c])[:50] for c in columns])
            lines.append(line)

        conn.close()
        total = f"\n\n({len(rows)} filas" + (", mostrando 100)" if len(rows) > 100 else ")")
        return f"```\n" + "\n".join(lines) + f"\n```{total}"

    except Exception as e:
        conn.close()
        return f"Error en consulta: {e}"


def _execute(db_name: str, query: str, vault_path: str = None) -> str:
    """Ejecuta INSERT, UPDATE, DELETE o CREATE (SEC-N02: bloquea ATTACH/LOAD)."""
    if not query:
        return "Error: consulta SQL requerida."

    safe, msg = _is_safe_query(query, mode="write")
    if not safe:
        return msg

    conn, error = _connect(db_name, vault_path)
    if error:
        return error

    try:
        cursor = conn.execute(query)
        conn.commit()
        affected = cursor.rowcount
        conn.close()
        logger.info(f"[database] SQL ejecutado en {db_name}: {affected} filas afectadas")
        return f"Ejecutado correctamente. {affected} fila(s) afectada(s)."
    except Exception as e:
        conn.close()
        return f"Error ejecutando SQL: {e}"


def _list_tables(db_name: str, vault_path: str = None) -> str:
    """Lista todas las tablas de una base de datos."""
    conn, error = _connect(db_name, vault_path)
    if error:
        return error

    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        if not tables:
            return f"Base de datos '{db_name}' sin tablas."
        return f"Tablas en '{db_name}':\n\n" + "\n".join(f"  - {t}" for t in tables)
    except Exception as e:
        conn.close()
        return f"Error: {e}"


def _schema(db_name: str, table: str, vault_path: str = None) -> str:
    """Muestra el esquema (columnas y tipos) de una tabla."""
    if not table:
        return "Error: nombre de tabla requerido."

    conn, error = _connect(db_name, vault_path)
    if error:
        return error

    try:
        # SEC-N01: Validar nombre de tabla (solo alfanumerico y guion bajo)
        import re
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', table):
            conn.close()
            return f"Nombre de tabla invalido: {table}"
        cursor = conn.execute(f"PRAGMA table_info({table})")
        columns = cursor.fetchall()
        conn.close()
        if not columns:
            return f"Tabla '{table}' no encontrada en '{db_name}'."

        lines = [f"Esquema de '{table}':"]
        for col in columns:
            pk = " [PK]" if col[5] else ""
            nullable = "" if col[3] else " NOT NULL"
            default = f" DEFAULT {col[4]}" if col[4] else ""
            lines.append(f"  - {col[1]} ({col[2]}{nullable}{default}{pk})")
        return "\n".join(lines)
    except Exception as e:
        conn.close()
        return f"Error: {e}"


def _list_dbs(vault_path: str = None) -> str:
    """Lista todas las bases de datos disponibles."""
    base = Path(vault_path) / "databases" if vault_path else _DB_DIR
    if not base.exists():
        return "No hay bases de datos."
    dbs = sorted(base.glob("*.db"))
    if not dbs:
        return "No hay bases de datos."
    items = []
    for db in dbs:
        size = db.stat().st_size
        size_str = f"{size:,} bytes" if size < 1_000_000 else f"{size / 1_000_000:.1f} MB"
        items.append(f"  - {db.stem} ({size_str})")
    return f"{len(dbs)} base(s) de datos:\n\n" + "\n".join(items)
