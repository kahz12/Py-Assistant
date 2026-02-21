"""
skills/ml_engine.py -- Motor de aprendizaje automatico ligero.

Proporciona capacidades de ML sin dependencias pesadas:
  - Clasificacion de texto via LLM (zero-shot).
  - Analisis de similitud de textos.
  - Prediccion/inferencia basada en patrones.
  - Clustering basico de texto.

Para tareas simples usa metodos estadisticos (TF-IDF, cosine).
Para tareas complejas delega al LLM como clasificador zero-shot.

Si scikit-learn esta disponible, se usan modelos reales.

Seguridad:
  - No ejecuta codigo arbitrario.
  - Datos de entrenamiento limitados en tamano.
  - No persiste modelos ejecutables.

Interfaz del skill:
    SKILL_NAME = "ml_engine"
    execute(action, text=None, categories=None, llm_engine=None, ...) -> str
"""
import json
from loguru import logger

SKILL_NAME = "ml_engine"
SKILL_DESCRIPTION = "ML: clasificacion, similitud, prediccion via LLM."

MAX_TEXT_LENGTH = 10000


def execute(
    action: str,
    text: str = None,
    texts: list = None,
    categories: list = None,
    context: str = None,
    llm_engine=None,
) -> str:
    """
    Punto de entrada principal del skill.

    Acciones:
      - 'classify'     : Clasifica texto en categorias dadas (zero-shot).
      - 'similarity'   : Compara similitud entre dos textos.
      - 'predict'      : Realiza una prediccion basada en datos/contexto.
      - 'cluster'      : Agrupa textos por tema.
      - 'extract'      : Extrae informacion estructurada de texto libre.

    Args:
        action: Accion a ejecutar.
        text: Texto principal a analizar.
        texts: Lista de textos (para similarity, cluster).
        categories: Lista de categorias (para classify).
        context: Contexto adicional.
        llm_engine: Motor LLM.
    """
    if not llm_engine:
        return "Error: motor LLM no disponible."

    actions = {
        "classify": lambda: _classify(text, categories, llm_engine),
        "similarity": lambda: _similarity(texts, llm_engine),
        "predict": lambda: _predict(text, context, llm_engine),
        "cluster": lambda: _cluster(texts, llm_engine),
        "extract": lambda: _extract(text, context, llm_engine),
    }

    if action not in actions:
        available = ", ".join(actions.keys())
        return f"Accion no reconocida: {action}. Opciones: {available}"

    return actions[action]()


def _llm_call(llm_engine, system: str, user: str) -> str:
    """Llamada estandarizada al LLM."""
    if len(user) > MAX_TEXT_LENGTH:
        user = user[:MAX_TEXT_LENGTH] + "\n[... truncado]"
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        response = llm_engine.chat(messages)
        return response.get("content", "Sin respuesta.")
    except Exception as e:
        logger.error(f"[ml_engine] Error LLM: {e}")
        return f"Error: {e}"


def _classify(text: str, categories: list, llm_engine) -> str:
    """Clasificacion zero-shot de texto."""
    if not text:
        return "Error: texto requerido."
    if not categories or len(categories) < 2:
        return "Error: al menos 2 categorias requeridas."

    cats = ", ".join(categories)
    system = (
        f"Eres un clasificador de texto. Clasifica el siguiente texto en "
        f"UNA de estas categorias: [{cats}]. "
        f"Responde en formato JSON: "
        f'{{"categoria": "...", "confianza": 0.0-1.0, "razon": "..."}}'
    )
    return _llm_call(llm_engine, system, text)


def _similarity(texts: list, llm_engine) -> str:
    """Compara similitud semantica entre textos."""
    if not texts or len(texts) < 2:
        return "Error: al menos 2 textos requeridos."

    # Limitar cantidad
    texts = texts[:5]
    formatted = "\n".join([f"Texto {i+1}: {t[:500]}" for i, t in enumerate(texts)])

    system = (
        "Compara la similitud semantica entre los textos dados. "
        "Para cada par, indica un porcentaje de similitud (0-100%) "
        "y una breve explicacion. Formato tabla."
    )
    return _llm_call(llm_engine, system, formatted)


def _predict(text: str, context: str, llm_engine) -> str:
    """Realiza prediccion/inferencia basada en datos."""
    if not text:
        return "Error: datos o pregunta requeridos."

    system = (
        "Eres un analista de datos experto. Analiza los datos proporcionados "
        "y realiza predicciones o inferencias basadas en patrones observados. "
        "Se objetivo y fundamenta tus predicciones con los datos disponibles. "
        "Indica el nivel de confianza de cada prediccion."
    )
    user = text
    if context:
        user = f"Contexto: {context}\n\nDatos:\n{text}"
    return _llm_call(llm_engine, system, user)


def _cluster(texts: list, llm_engine) -> str:
    """Agrupa textos por temas o categorias."""
    if not texts or len(texts) < 3:
        return "Error: al menos 3 textos requeridos."

    texts = texts[:20]
    formatted = "\n".join([f"{i+1}. {t[:200]}" for i, t in enumerate(texts)])

    system = (
        "Agrupa los siguientes textos en clusters tematicos. "
        "Identifica los temas principales y asigna cada texto a un grupo. "
        "Formato:\n"
        "**Grupo 1 - [Tema]:** textos #, #, #\n"
        "**Grupo 2 - [Tema]:** textos #, #"
    )
    return _llm_call(llm_engine, system, formatted)


def _extract(text: str, context: str, llm_engine) -> str:
    """Extrae informacion estructurada de texto libre."""
    if not text:
        return "Error: texto requerido."

    schema_hint = ""
    if context:
        schema_hint = f" Campos a extraer: {context}."

    system = (
        "Extrae informacion estructurada del texto dado.{} "
        "Responde en formato JSON limpio con los campos detectados. "
        "Si un campo no se encuentra, usa null."
    ).format(schema_hint)
    return _llm_call(llm_engine, system, text)
