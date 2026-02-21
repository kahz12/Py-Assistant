"""
plugins/example_plugin.py -- Plugin de ejemplo para demostrar el sistema de extensibilidad.

Este archivo se carga automaticamente por el SkillManager porque se encuentra
en la carpeta plugins/. Expone la interfaz estandar de un skill.

Instrucciones para crear plugins:
  1. Define SKILL_NAME (string, identificador unico).
  2. Opcional: define SKILL_DESCRIPTION.
  3. Define una funcion execute(**kwargs) que retorne un string.
"""
from loguru import logger

SKILL_NAME = "example_plugin"
SKILL_DESCRIPTION = "Plugin de ejemplo para mostrar como funciona el sistema externo."


def execute(action: str = "ping", **kwargs) -> str:
    """
    Ejecuta el plugin de ejemplo.

    Args:
        action: Accion a realizar (ej: 'ping', 'echo').
        **kwargs: Argumentos dinamicos.
    """
    logger.info(f"[{SKILL_NAME}] Ejecutando accion: {action}, args: {kwargs}")

    if action == "ping":
        return "pong! El sistema de plugins esta funcionando correctamente."
    elif action == "echo":
        msg = kwargs.get("message", "No enviaste mensaje")
        return f"Echo desde el plugin externo: {msg}"
    else:
        return f"Accion '{action}' no soportada por el plugin de ejemplo."
