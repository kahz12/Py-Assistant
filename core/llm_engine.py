"""
core/llm_engine.py -- Abstraccion del motor de lenguaje.

Define la interfaz base (BaseLLMEngine) y dos implementaciones:
  - APIEngine  : Proveedores remotos (Groq, OpenAI, Anthropic).
  - LocalEngine: Motor local via Ollama (futuro).

Cada motor normaliza las respuestas a un formato dict uniforme:
  {"role": "assistant", "content": "...", "tool_calls": [...]}

La funcion create_engine() actua como factory segun la configuracion.
"""
from abc import ABC, abstractmethod
from loguru import logger


class BaseLLMEngine(ABC):
    """
    Interfaz abstracta para motores de lenguaje.

    Todas las implementaciones deben definir:
      - complete(prompt) : Generacion simple de texto.
      - chat(messages, tools) : Generacion en formato chat con soporte para herramientas.
    """

    @abstractmethod
    def complete(self, prompt: str) -> str:
        """Genera una respuesta simple a partir de un prompt de texto."""
        pass

    @abstractmethod
    def chat(self, messages: list[dict], tools: list = None) -> dict:
        """Genera una respuesta en formato chat, opcionalmente con herramientas."""
        pass


# ---------------------------------------------------------------------------
# Motor basado en API externa
# ---------------------------------------------------------------------------

class APIEngine(BaseLLMEngine):
    """
    Motor LLM basado en APIs externas.

    Proveedores soportados (OpenAI-compatibles):
      - openai, groq, grok, gemini, ollama, cerebras, qwen, deepseek, kimi
    Proveedor nativo:
      - anthropic

    Atributos:
        provider: Nombre del proveedor
        model: Identificador del modelo
        max_tokens: Limite de tokens en la respuesta
        client: Instancia del SDK del proveedor
    """

    OPENAI_COMPATIBLE = {
        "openai", "groq", "grok", "gemini", "ollama", 
        "cerebras", "qwen", "deepseek", "kimi"
    }

    def __init__(self, provider: str, api_key: str, model: str, max_tokens: int = 2048, base_url: str = None):
        self.provider = provider.lower()
        self.model = model
        self.max_tokens = max_tokens
        self.client = None

        if self.provider in self.OPENAI_COMPATIBLE:
            from openai import OpenAI
            kwargs = {"api_key": api_key}
            
            # URLs base por defecto si no las provee el usuario
            default_base_urls = {
                "groq": "https://api.groq.com/openai/v1",
                "grok": "https://api.x.ai/v1",
                "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
                "ollama": "http://localhost:11434/v1",
                "cerebras": "https://api.cerebras.ai/v1",
                "deepseek": "https://api.deepseek.com/v1",
            }
            resolved_url = base_url or default_base_urls.get(self.provider)
            
            if resolved_url:
                kwargs["base_url"] = resolved_url
                
            self.client = OpenAI(**kwargs)
        elif self.provider == "anthropic":
            import anthropic
            self.client = anthropic.Anthropic(api_key=api_key)
        else:
            raise ValueError(f"Proveedor LLM no soportado: {provider}")

        logger.info(f"LLM Engine inicializado: {provider} / {model}")

    def complete(self, prompt: str) -> str:
        """
        Genera una respuesta a un prompt simple.

        Internamente usa chat() con un solo mensaje de usuario.

        Args:
            prompt: Texto de entrada.

        Returns:
            Texto de la respuesta generada.
        """
        messages = [{"role": "user", "content": prompt}]
        response = self.chat(messages)
        if isinstance(response, dict):
            return response.get("content", str(response))
        if hasattr(response, "content"):
            content = response.content
            if isinstance(content, str):
                return content
            if isinstance(content, list) and len(content) > 0:
                return content[0].text if hasattr(content[0], "text") else str(content[0])
        return str(response)

    def chat(self, messages: list[dict], tools: list = None) -> dict:
        """
        Genera una respuesta en formato chat.

        Soporta tool-calling para proveedores OpenAI/Groq. Las respuestas
        se normalizan a un diccionario con 'role', 'content', y opcionalmente
        'tool_calls'.

        Si el LLM genera una llamada a funcion malformada (error 400 de Groq),
        se reintenta sin herramientas como fallback.

        Args:
            messages: Lista de mensajes con 'role' y 'content'.
            tools: Lista opcional de schemas de herramientas (formato OpenAI).

        Returns:
            Diccionario normalizado con la respuesta del modelo.
        """
        try:
            if self.provider in self.OPENAI_COMPATIBLE:
                kwargs = {
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": self.max_tokens,
                }
                if tools:
                    # Not all compatible endpoints support tool_choice, handle carefully if needed
                    # but standard is auto
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"

                try:
                    response = self.client.chat.completions.create(**kwargs)
                except Exception as tool_error:
                    error_msg = str(tool_error)
                    # Groq retorna 400 si el LLM genera un function call malformado.
                    # Reintentar sin herramientas como fallback seguro.
                    if "tool_use_failed" in error_msg or "failed_generation" in error_msg:
                        logger.warning(
                            f"LLM genero tool call malformado, reintentando sin herramientas: "
                            f"{error_msg[:200]}"
                        )
                        kwargs.pop("tools", None)
                        kwargs.pop("tool_choice", None)
                        # Limpiar tool_calls de mensajes previos para evitar
                        # errores de validacion de schema en el reintento
                        clean_msgs = []
                        for m in kwargs.get("messages", []):
                            cleaned = {k: v for k, v in m.items() if k != "tool_calls"}
                            if cleaned.get("role") != "tool":
                                clean_msgs.append(cleaned)
                        kwargs["messages"] = clean_msgs
                        response = self.client.chat.completions.create(**kwargs)
                    else:
                        raise

                message = response.choices[0].message

                result = {
                    "role": "assistant",
                    "content": message.content or "",
                }
                if message.tool_calls:
                    result["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            }
                        }
                        for tc in message.tool_calls
                    ]
                return result

            elif self.provider == "anthropic":
                kwargs = {
                    "model": self.model,
                    "max_tokens": self.max_tokens,
                    "messages": messages,
                }
                if tools:
                    kwargs["tools"] = tools
                response = self.client.messages.create(**kwargs)
                content = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        content += block.text
                return {
                    "role": "assistant",
                    "content": content,
                }

        except Exception as e:
            logger.error(f"Error en LLM Engine ({self.provider}): {e}")
            return {
                "role": "assistant",
                "content": f"Error al procesar tu mensaje: {str(e)}",
            }


# ---------------------------------------------------------------------------
# Motor local (Ollama)
# ---------------------------------------------------------------------------

class LocalEngine(BaseLLMEngine):
    """
    Motor LLM local via Ollama.

    Pensado para hardware dedicado (Mini PC con Ryzen 8 / Intel i7).
    Actualmente en estado experimental.

    Atributos:
        model: Nombre del modelo local (ej: 'phi3:mini').
        client: Instancia del cliente Ollama.
    """

    def __init__(self, model: str, ollama_url: str = "http://localhost:11434"):
        try:
            import ollama
            self.model = model
            self.client = ollama.Client(host=ollama_url)
            logger.info(f"LLM Engine local inicializado: {model}")
        except ImportError:
            raise ImportError("Instala ollama: pip install ollama")

    def complete(self, prompt: str) -> str:
        """Genera una respuesta simple desde el modelo local."""
        messages = [{"role": "user", "content": prompt}]
        response = self.chat(messages)
        return response.get("content", "")

    def chat(self, messages: list[dict], tools: list = None) -> dict:
        """
        Genera una respuesta en formato chat desde el modelo local.

        Args:
            messages: Lista de mensajes con 'role' y 'content'.
            tools: Schemas de herramientas (soporte limitado en Ollama).

        Returns:
            Diccionario normalizado con la respuesta del modelo.
        """
        try:
            import json
            import uuid
            
            kwargs = {
                "model": self.model,
                "messages": messages,
            }
            if tools:
                kwargs["tools"] = tools

            response = self.client.chat(**kwargs)
            
            result = {
                "role": "assistant",
                "content": response.message.content or "",
            }
            
            # Parsear tool_calls devuelto por Ollama
            if hasattr(response.message, "tool_calls") and response.message.tool_calls:
                parsed_tool_calls = []
                for tc in response.message.tool_calls:
                    # Diferencia tecnica: la api de ollama nativamente devuelve arguments 
                    # como dict Python, pero nuestro mcp_router (basado en el standard OpenAI)
                    # espera un STRING jsonfeado. Asi que hay que serializarlo.
                    args = tc.function.arguments
                    if isinstance(args, dict):
                        args_str = json.dumps(args)
                    else:
                        args_str = str(args)
                        
                    parsed_tool_calls.append({
                        # Ollama no provee un ID único por defecto en su spec actual,
                        # asi que generamos uno propio para el router MCP.
                        "id": f"call_{uuid.uuid4().hex[:8]}",
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": args_str,
                        }
                    })
                result["tool_calls"] = parsed_tool_calls

            return result
        except Exception as e:
            logger.error(f"Error en LLM Engine local: {e}")
            return {
                "role": "assistant",
                "content": f"Error al procesar tu mensaje de forma nativa: {str(e)}",
            }


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_engine(config: dict) -> BaseLLMEngine:
    """
    Crea e inicializa el motor LLM segun la configuracion.

    Modos soportados:
      - 'api'   : Crea un APIEngine (Groq/OpenAI/Anthropic).
      - 'local' : Crea un LocalEngine (Ollama).

    Args:
        config: Diccionario con la configuracion del LLM (de settings.yaml).

    Returns:
        Instancia de BaseLLMEngine lista para usar.

    Raises:
        ValueError: Si el modo especificado no es soportado.
    """
    mode = config.get("mode", "api")

    if mode == "api":
        return APIEngine(
            provider=config["provider"],
            api_key=config["api_key"],
            model=config["model"],
            max_tokens=config.get("max_tokens", 2048),
            base_url=config.get("base_url"),
        )
    elif mode == "local":
        local_config = config.get("local", {})
        return LocalEngine(
            model=local_config.get("model", "phi3:mini"),
            ollama_url=local_config.get("ollama_url", "http://localhost:11434"),
        )
    else:
        raise ValueError(f"Modo LLM desconocido: {mode}")
