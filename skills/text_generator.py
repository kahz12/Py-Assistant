"""
skills/text_generator.py -- Generacion avanzada de texto via LLM.

Expande las capacidades del LLM base con modos especializados:
  - Escritura creativa (historias, poemas, guiones).
  - Generacion de codigo en cualquier lenguaje.
  - Redaccion formal (emails, cartas, reportes).
  - Brainstorming y generacion de ideas.
  - Generacion estructurada (JSON, CSV, tablas).

Usa el LLM configurado (Groq/OpenAI/Anthropic) con prompts optimizados
por modo de generacion.

Interfaz del skill:
    SKILL_NAME = "text_generator"
    execute(action, prompt=None, style=None, llm_engine=None, ...) -> str
"""
from loguru import logger

SKILL_NAME = "text_generator"
SKILL_DESCRIPTION = "Generacion avanzada de texto: creativo, codigo, formal, ideas."

# Limites para prompts
MAX_PROMPT_LENGTH = 8000


def execute(
    action: str,
    prompt: str = None,
    style: str = None,
    language: str = None,
    llm_engine=None,
) -> str:
    """
    Punto de entrada principal del skill.

    Acciones disponibles:
      - 'creative'    : Escritura creativa (historias, poemas).
      - 'code'        : Generacion de codigo.
      - 'formal'      : Redaccion formal (emails, cartas).
      - 'brainstorm'  : Generacion de ideas y brainstorming.
      - 'structured'  : Datos estructurados (JSON, CSV, tablas).
      - 'free'        : Generacion libre con prompt personalizado.

    Args:
        action: Modo de generacion.
        prompt: Tema, instruccion o contexto para generar.
        style: Estilo adicional (ej: 'humoristico', 'profesional').
        language: Lenguaje de programacion (para code).
        llm_engine: Instancia del motor LLM.
    """
    if not prompt:
        return "Error: prompt o tema requerido."

    if not llm_engine:
        return "Error: motor LLM no disponible."

    if len(prompt) > MAX_PROMPT_LENGTH:
        prompt = prompt[:MAX_PROMPT_LENGTH] + "\n[... truncado]"

    actions = {
        "creative": lambda: _generate(llm_engine, prompt, _creative_system(style)),
        "code": lambda: _generate(llm_engine, prompt, _code_system(language)),
        "formal": lambda: _generate(llm_engine, prompt, _formal_system(style)),
        "brainstorm": lambda: _generate(llm_engine, prompt, _brainstorm_system()),
        "structured": lambda: _generate(llm_engine, prompt, _structured_system(style)),
        "free": lambda: _generate(llm_engine, prompt, _free_system()),
    }

    if action not in actions:
        available = ", ".join(actions.keys())
        return f"Accion no reconocida: {action}. Opciones: {available}"

    return actions[action]()


# ---------------------------------------------------------------------------
# System prompts por modo
# ---------------------------------------------------------------------------

def _creative_system(style: str = None) -> str:
    base = (
        "Eres un escritor creativo experto. Genera texto original, "
        "evocador y bien estructurado. Usa descripciones ricas y "
        "lenguaje vívido."
    )
    if style:
        base += f" Estilo solicitado: {style}."
    return base


def _code_system(language: str = None) -> str:
    base = (
        "Eres un programador experto. Genera codigo limpio, bien "
        "documentado, con comentarios claros y siguiendo las "
        "mejores practicas. Incluye manejo de errores."
    )
    if language:
        base += f" Lenguaje: {language}."
    return base


def _formal_system(style: str = None) -> str:
    base = (
        "Eres un redactor profesional. Genera texto formal, claro "
        "y apropiado para entornos profesionales. Usa un tono "
        "respetuoso y estructura logica."
    )
    if style:
        base += f" Tipo de documento: {style}."
    return base


def _brainstorm_system() -> str:
    return (
        "Eres un facilitador de brainstorming creativo. Genera "
        "multiples ideas originales y variadas sobre el tema dado. "
        "Organiza las ideas por categoria y prioridad. "
        "Se innovador y piensa fuera de la caja."
    )


def _structured_system(format_type: str = None) -> str:
    base = (
        "Genera datos estructurados y bien formateados. "
        "Usa el formato mas adecuado para los datos."
    )
    if format_type:
        base += f" Formato solicitado: {format_type}."
    return base


def _free_system() -> str:
    return (
        "Genera texto de alta calidad siguiendo las instrucciones "
        "del usuario. Se preciso, completo y util."
    )


# ---------------------------------------------------------------------------
# Motor de generacion
# ---------------------------------------------------------------------------

def _generate(llm_engine, prompt: str, system_prompt: str) -> str:
    """Genera texto usando el LLM con el system prompt dado."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]

    try:
        response = llm_engine.chat(messages)
        result = response.get("content", "")
        if not result:
            return "El LLM no genero respuesta."
        logger.info(f"[text_gen] Generado: {len(result)} chars")
        return result
    except Exception as e:
        logger.error(f"[text_gen] Error: {e}")
        return f"Error generando texto: {e}"
