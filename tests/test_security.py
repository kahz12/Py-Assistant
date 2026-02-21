"""
tests/test_security.py -- Tests de seguridad para todos los skills.

Verifica:
  - SQL injection prevention (database_manager)
  - Path traversal prevention (database_manager, media_tools, device_access)
  - SSRF defenses (api_client)
  - Command injection prevention (system_config)
  - Format sanitization (media_tools)
  - Entity ID validation (home_assistant)
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------
# database_manager: SQL injection + path traversal
# ---------------------------------------------------------------

class TestDatabaseSecurity:
    def test_sanitize_name_removes_traversal(self):
        from skills.database_manager import _sanitize_name
        assert ".." not in _sanitize_name("../../etc/passwd")
        assert "/" not in _sanitize_name("../../etc/passwd")

    def test_sanitize_name_removes_sql_chars(self):
        from skills.database_manager import _sanitize_name
        result = _sanitize_name("tabla; DROP TABLE--")
        assert ";" not in result
        assert "DROP" not in result.upper() or result.isalnum()

    def test_safe_query_blocks_attach(self):
        from skills.database_manager import _is_safe_query
        safe, _ = _is_safe_query("ATTACH DATABASE 'evil.db' AS evil", "write")
        assert not safe

    def test_safe_query_blocks_load_extension(self):
        from skills.database_manager import _is_safe_query
        safe, _ = _is_safe_query("SELECT load_extension('evil')", "read")
        assert not safe

    def test_safe_query_read_only_blocks_insert(self):
        from skills.database_manager import _is_safe_query
        safe, _ = _is_safe_query("INSERT INTO users VALUES(1)", "read")
        assert not safe

    def test_safe_query_allows_select_in_read(self):
        from skills.database_manager import _is_safe_query
        safe, _ = _is_safe_query("SELECT * FROM users WHERE id=1", "read")
        assert safe

    def test_db_path_no_traversal(self):
        from skills.database_manager import _get_db_path
        path = _get_db_path("../../etc/passwd", "memory_vault")
        assert "etc" not in str(path) or "databases" in str(path)


# ---------------------------------------------------------------
# api_client: SSRF prevention
# ---------------------------------------------------------------

class TestSSRFPrevention:
    def test_blocks_localhost(self):
        from skills.api_client import _is_url_safe
        safe, _ = _is_url_safe("http://127.0.0.1/admin")
        assert not safe

    def test_blocks_private_ip(self):
        from skills.api_client import _is_url_safe
        safe, _ = _is_url_safe("http://192.168.1.1/config")
        assert not safe

    def test_blocks_metadata_endpoint(self):
        from skills.api_client import _is_url_safe
        safe, _ = _is_url_safe("http://169.254.169.254/latest/meta-data/")
        assert not safe

    def test_blocks_file_protocol(self):
        from skills.api_client import _is_url_safe
        safe, _ = _is_url_safe("file:///etc/passwd")
        assert not safe

    def test_blocks_gopher_protocol(self):
        from skills.api_client import _is_url_safe
        safe, _ = _is_url_safe("gopher://evil.com")
        assert not safe

    def test_blocks_ipv6_private(self):
        from skills.api_client import _is_url_safe
        safe, _ = _is_url_safe("http://[fc00::1]/admin")
        assert not safe

    def test_allows_public_url(self):
        from skills.api_client import _is_url_safe
        safe, _ = _is_url_safe("https://api.example.com/data")
        assert safe


# ---------------------------------------------------------------
# media_tools: path validation + format sanitization
# ---------------------------------------------------------------

class TestMediaSecurity:
    def test_blocks_etc_path(self):
        from skills.media_tools import _validate_input
        err = _validate_input("/etc/shadow")
        assert "denegado" in err.lower()

    def test_allows_home_path(self):
        from skills.media_tools import _validate_input
        err = _validate_input("/home/user/video.mp4")
        assert "denegado" not in err.lower()

    def test_sanitize_format_removes_dangerous(self):
        from skills.media_tools import _sanitize_format
        assert _sanitize_format("mp3; rm -rf /") == "mp3rmrf"

    def test_sanitize_format_preserves_normal(self):
        from skills.media_tools import _sanitize_format
        assert _sanitize_format("mp4") == "mp4"


# ---------------------------------------------------------------
# device_access: output path validation
# ---------------------------------------------------------------

class TestDeviceSecurity:
    def test_blocks_etc_output(self):
        from skills.device_access import _default_output
        result = _default_output("png", "/etc/malicious.png")
        assert "/etc/" not in result

    def test_allows_home_output(self):
        from skills.device_access import _default_output
        result = _default_output("png", "/home/user/capture.png")
        assert "/home/" in result


# ---------------------------------------------------------------
# system_config: command injection
# ---------------------------------------------------------------

class TestSystemConfigSecurity:
    def test_blocks_service_injection(self):
        from skills.system_config import _service_status
        result = _service_status("; rm -rf /")
        assert "invalido" in result.lower()

    def test_allows_valid_service(self):
        from skills.system_config import _service_status
        result = _service_status("ssh.service")
        assert "invalido" not in result.lower()

    def test_blocks_timezone_injection(self):
        from skills.system_config import _set_timezone
        result = _set_timezone("; rm -rf /", False)
        assert "invalida" in result.lower()

    def test_blocks_hostname_injection(self):
        from skills.system_config import _set_hostname
        result = _set_hostname("; rm -rf /", False)
        assert "invalido" in result.lower()

    def test_allows_valid_hostname(self):
        from skills.system_config import _set_hostname
        result = _set_hostname("mi-servidor", False)
        assert "CONFIRMACION" in result


# ---------------------------------------------------------------
# home_assistant: entity_id validation
# ---------------------------------------------------------------

class TestHomeAssistantSecurity:
    def test_blocks_traversal_entity(self):
        from skills.home_assistant import _validate_entity_id
        err = _validate_entity_id("../../etc/passwd")
        assert err  # Non-empty means invalid

    def test_blocks_invalid_domain(self):
        from skills.home_assistant import _validate_entity_id
        err = _validate_entity_id("shell.exec")
        assert err

    def test_allows_valid_entity(self):
        from skills.home_assistant import _validate_entity_id
        err = _validate_entity_id("light.sala")
        assert err == ""

    def test_blocks_empty_entity(self):
        from skills.home_assistant import _validate_entity_id
        err = _validate_entity_id("")
        assert err
