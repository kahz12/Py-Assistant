"""
skills/text_analyzer.py -- Herramientas de analisis y procesamiento de texto.

Proporciona funciones de NLP delegando al LLM para tareas de:
  - Resumen de textos largos.
  - Traduccion entre idiomas.
  - Analisis de sentimiento.
  - Extraccion de palabras clave y entidades.
  - Correccion ortografica y gramatical.

El skill no usa bibliotecas de NLP externas; delega todo al LLM
configurado (Groq/OpenAI/Anthropic) para maxima calidad.

Interfaz del skill:
    SKILL_NAME = "text_analyzer"
    execute(action, text=None, language=None, llm_engine=None) -> str
"""
from loguru import logger

SKILL_NAME = "text_analyzer"
SKILL_DESCRIPTION = "Analisis de texto: resumir, traducir, sentimiento, corregir."


def execute(
    action: str,
    text: str = None,
    language: str = None,
    llm_engine=None,
) -> str:
    """
    Punto de entrada principal del skill.

    Acciones disponibles:
      - 'summarize'   : Resume un texto largo.
      - 'translate'   : Traduce texto a otro idioma.
      - 'sentiment'   : Analiza el sentimiento del texto.
      - 'keywords'    : Extrae palabras clave y entidades.
      - 'correct'     : Corrige ortografia y gramatica.
      - 'rewrite'     : Reescribe el texto en un estilo diferente.

    Args:
        action: Accion a ejecutar.
        text: Texto a analizar/procesar.
        language: Idioma destino (para traduccion).
        llm_engine: Instancia del motor LLM (BaseLLMEngine).
    """
    if not text:
        return "Error: texto requerido para analisis."

    if not llm_engine:
        return "Error: motor LLM no disponible."

    actions = {
        "summarize": lambda: _llm_task(
            llm_engine, text,
            "Resume el siguiente texto de forma concisa, manteniendo los puntos clave. "
            "Responde SOLO con el resumen, sin comentarios adicionales."
        ),
        "translate": lambda: _llm_task(
            llm_engine, text,
            f"Traduce el siguiente texto a {language or 'ingles'}. "
            "Responde SOLO con la traduccion, sin comentarios."
        ),
        "sentiment": lambda: _llm_task(
            llm_engine, text,
            "Analiza el sentimiento del siguiente texto. Indica: "
            "1) Sentimiento general (positivo/negativo/neutro/mixto). "
            "2) Emociones detectadas. "
            "3) Tono general. "
            "Se breve y directo."
        ),
        "keywords": lambda: _llm_task(
            llm_engine, text,
            "Extrae del siguiente texto: "
            "1) Palabras clave principales (maximo 10). "
            "2) Entidades nombradas (personas, lugares, organizaciones). "
            "3) Temas principales. "
            "Responde en formato de lista."
        ),
        "correct": lambda: _llm_task(
            llm_engine, text,
            "Corrige la ortografia y gramatica del siguiente texto. "
            "Responde SOLO con el texto corregido. Si no hay errores, "
            "retorna el texto original sin cambios."
        ),
        "rewrite": lambda: _llm_task(
            llm_engine, text,
            "Reescribe el siguiente texto de forma mas clara y profesional, "
            "manteniendo el significado original. Responde SOLO con el texto reescrito."
        ),
    }

    if action not in actions:
        available = ", ".join(actions.keys())
        return f"Accion no reconocida: {action}. Opciones: {available}"

    return actions[action]()


def _llm_task(llm_engine, text: str, instruction: str) -> str:
    """Ejecuta una tarea de NLP delegando al LLM."""
    # Truncar textos muy largos para no exceder context window
    if len(text) > 12000:
        text = text[:12000] + "\n\n[... texto truncado]"

    messages = [
        {"role": "system", "content": instruction},
        {"role": "user", "content": text},
    ]

    try:
        response = llm_engine.chat(messages)
        result = response.get("content", "")
        if not result:
            return "El LLM no genero respuesta."
        return result
    except Exception as e:
        logger.error(f"[text_analyzer] Error en LLM: {e}")
        return f"Error procesando texto: {e}"
