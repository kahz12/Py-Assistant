"""
tests/test_llm_engine.py -- Tests del motor LLM (factory, providers, auth).

Verifica:
  - Factory crea engines correctos.
  - Proveedores OPENAI_COMPATIBLE se inicializan con base_url.
  - Auth: bcrypt, lockout.
"""
import sys
import os
import pytest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["LOGURU_LEVEL"] = "ERROR"
from loguru import logger
logger.remove()


class TestLLMFactory:
    def test_create_groq_engine(self):
        """Factory debe crear APIEngine para groq."""
        from core.llm_engine import create_engine
        engine = create_engine({
            "provider": "groq",
            "api_key": "dummy",
            "model": "llama-3.3-70b",
        })
        assert engine.provider == "groq"
        assert engine.model == "llama-3.3-70b"

    def test_create_gemini_with_base_url(self):
        """Factory debe crear engine Gemini con base_url personalizada."""
        from core.llm_engine import create_engine
        engine = create_engine({
            "provider": "gemini",
            "api_key": "dummy",
            "model": "gemini-1.5-flash",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        })
        assert engine.provider == "gemini"
        assert "googleapis" in str(engine.client.base_url)

    def test_create_deepseek_with_base_url(self):
        """Factory debe crear engine DeepSeek con base_url."""
        from core.llm_engine import create_engine
        engine = create_engine({
            "provider": "deepseek",
            "api_key": "dummy",
            "model": "deepseek-chat",
            "base_url": "https://api.deepseek.com/v1",
        })
        assert engine.provider == "deepseek"
        assert "deepseek" in str(engine.client.base_url)

    def test_create_cerebras_with_base_url(self):
        """Factory debe crear engine Cerebras."""
        from core.llm_engine import create_engine
        engine = create_engine({
            "provider": "cerebras",
            "api_key": "dummy",
            "model": "llama3.1-70b",
            "base_url": "https://api.cerebras.ai/v1",
        })
        assert engine.provider == "cerebras"

    def test_invalid_provider_raises(self):
        """Factory debe fallar con proveedor desconocido."""
        from core.llm_engine import create_engine
        with pytest.raises(ValueError, match="no soportado"):
            create_engine({
                "provider": "proveedor_falso",
                "api_key": "dummy",
                "model": "test",
            })

    def test_openai_compatible_set(self):
        """Todos los proveedores esperados están en OPENAI_COMPATIBLE."""
        from core.llm_engine import APIEngine
        expected = {"openai", "groq", "grok", "gemini", "ollama", "cerebras", "qwen", "deepseek", "kimi"}
        assert expected.issubset(APIEngine.OPENAI_COMPATIBLE)

    def test_local_mode_config(self):
        """Modo local debe crear LocalEngine (si ollama disponible)."""
        from core.llm_engine import create_engine
        try:
            engine = create_engine({
                "mode": "local",
                "local": {"model": "phi3:mini"},
            })
            assert engine.model == "phi3:mini"
        except ImportError:
            pytest.skip("ollama no instalado")

    def test_local_mode_tool_calling(self):
        """El LocalEngine debe parsear tool_calls nativos de Ollama."""
        from core.llm_engine import LocalEngine
        from unittest.mock import MagicMock, patch

        try:
            with patch('ollama.Client') as mock_client:
                # Mock the structure of Ollama's response objects
                mock_message = MagicMock()
                mock_message.content = "Ejecutando la herramienta..."
                
                mock_tool_call = MagicMock()
                mock_tool_call.function.name = "mi_herramienta"
                mock_tool_call.function.arguments = {"param1": 123}
                
                mock_message.tool_calls = [mock_tool_call]
                
                mock_response = MagicMock()
                mock_response.message = mock_message
                
                # Configure the client to return our mock
                instance = mock_client.return_value
                instance.chat.return_value = mock_response
                
                engine = LocalEngine("llama3.1", "http://localhost:11434")
                
                # Run the chat
                result = engine.chat([{"role": "user", "content": "test"}], tools=[])
                
                # Validations
                assert result["role"] == "assistant"
                assert "tool_calls" in result
                assert len(result["tool_calls"]) == 1
                
                tc = result["tool_calls"][0]
                assert tc["type"] == "function"
                assert "id" in tc
                assert tc["id"].startswith("call_")
                assert tc["function"]["name"] == "mi_herramienta"
                # Output args should be stringified JSON
                assert tc["function"]["arguments"] == '{"param1": 123}'
        except ImportError:
            pytest.skip("ollama no instalado")


class TestAuth:
    def test_bcrypt_hash_and_verify(self):
        """Debe hashear y verificar con bcrypt."""
        from core.auth import AuthManager
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".auth", delete=False) as f:
            auth = AuthManager(Path(f.name))
            auth.setup("passphrase", "test_pass_123")
            assert auth.authenticate("test_pass_123")
            assert not auth.authenticate("wrong_pass")
            os.unlink(f.name)

    def test_lockout_after_failed_attempts(self):
        """Debe bloquear después de intentos fallidos."""
        from core.auth import AuthManager
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".auth", delete=False) as f:
            auth = AuthManager(Path(f.name))
            auth.setup("passphrase", "correct_pass")
            # 5 intentos fallidos
            for _ in range(5):
                auth.authenticate("wrong_pass")
            # El sexto debe estar bloqueado
            result = auth.authenticate("correct_pass")
            assert not result  # Bloqueado incluso con pass correcta
            os.unlink(f.name)
