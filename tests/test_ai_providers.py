"""Unit tests for Multi-Model AI Provider Architecture and Unified AI Client."""

import json
from unittest.mock import patch, MagicMock
import urllib.error
import pytest

from godmode.ai.providers import (
    BaseAIProvider,
    GeminiProvider,
    GrokProvider,
    ProviderRegistry,
    AIProviderError,
    AuthenticationError,
    QuotaExceededError,
    ModelNotFoundError,
)
from godmode.ai.client import UnifiedAIClient
from godmode.config import GodModeConfig


class TestProviderRegistry:
    """Tests for ProviderRegistry discovery and instantiation."""

    def test_registered_providers(self):
        providers = ProviderRegistry.list_providers()
        assert "gemini" in providers
        assert "grok" in providers

    def test_create_gemini_provider(self):
        with patch("google.generativeai.configure"):
            prov = ProviderRegistry.create("gemini", api_key="dummy_key", model_name="gemini-2.5-flash")
            assert isinstance(prov, GeminiProvider)
            assert prov.provider_name == "gemini"
            assert prov.model_name == "gemini-2.5-flash"

    def test_create_grok_provider(self):
        prov = ProviderRegistry.create("grok", api_key="xai-test-key", model_name="grok-2-latest")
        assert isinstance(prov, GrokProvider)
        assert prov.provider_name == "grok"
        assert prov.model_name == "grok-2-latest"

    def test_create_unknown_provider(self):
        with pytest.raises(AIProviderError) as exc_info:
            ProviderRegistry.create("unknown_provider", api_key="key")
        assert "Unknown AI provider" in str(exc_info.value)


class TestGrokProvider:
    """Tests for xAI Grok provider HTTP client and error normalization."""

    def test_successful_generation(self):
        provider = GrokProvider(api_key="xai-valid-key", model_name="grok-2-latest")

        mock_response_data = {
            "id": "chatcmpl-123",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "ANSWER: B\nExplanation: 2 + 2 = 4.",
                    }
                }
            ],
            "usage": {"total_tokens": 42},
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_response_data).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            result = provider.generate("What is 2 + 2?\nA) 3\nB) 4")
            assert "ANSWER: B" in result
            assert "2 + 2 = 4" in result
            mock_urlopen.assert_called_once()

    def test_authentication_error_401(self):
        provider = GrokProvider(api_key="xai-invalid-key")

        error = urllib.error.HTTPError(
            url="https://api.x.ai/v1/chat/completions",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=MagicMock(read=lambda: b'{"error": "Invalid API key"}'),
        )

        with patch("urllib.request.urlopen", side_effect=error):
            with pytest.raises(AuthenticationError) as exc_info:
                provider.generate("Test prompt")
            assert "Authentication failed" in str(exc_info.value)
            assert exc_info.value.status_code == 401

    def test_rate_limit_error_429(self):
        provider = GrokProvider(api_key="xai-key")

        error = urllib.error.HTTPError(
            url="https://api.x.ai/v1/chat/completions",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=MagicMock(read=lambda: b'{"error": "Rate limit exceeded"}'),
        )

        with patch("urllib.request.urlopen", side_effect=error):
            with pytest.raises(QuotaExceededError) as exc_info:
                provider.generate("Test prompt")
            assert "Rate limit or quota exceeded" in str(exc_info.value)
            assert exc_info.value.status_code == 429

    def test_model_not_found_404(self):
        provider = GrokProvider(api_key="xai-key", model_name="nonexistent-model")

        error = urllib.error.HTTPError(
            url="https://api.x.ai/v1/chat/completions",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=MagicMock(read=lambda: b'{"error": "Model not found"}'),
        )

        with patch("urllib.request.urlopen", side_effect=error):
            with pytest.raises(ModelNotFoundError):
                provider.generate("Test prompt")

    def test_validate_credentials_success(self):
        provider = GrokProvider(api_key="xai-valid-key")

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            valid, msg = provider.validate_credentials()
            assert valid is True
            assert "Connected successfully" in msg

    def test_validate_credentials_failure(self):
        provider = GrokProvider(api_key="xai-bad-key")

        error = urllib.error.HTTPError(
            url="https://api.x.ai/v1/chat/completions",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=MagicMock(read=lambda: b'{"error": "Incorrect API key"}'),
        )

        with patch("urllib.request.urlopen", side_effect=error):
            valid, msg = provider.validate_credentials()
            assert valid is False
            assert "Authentication failed" in msg


class TestUnifiedAIClient:
    """Tests for UnifiedAIClient provider switching and fallback."""

    def test_unified_client_with_grok(self):
        client = UnifiedAIClient(
            provider_name="grok",
            api_key="xai-key",
            model_name="grok-2-latest",
        )
        assert client.provider_name == "grok"
        assert client.model_name == "grok-2-latest"

        with patch.object(client.provider, "generate", return_value="Grok response"):
            resp = client.generate_content("Hello")
            assert resp.text == "Grok response"

    def test_unified_client_switch_provider(self):
        with patch("google.generativeai.configure"):
            client = UnifiedAIClient(
                provider_name="gemini",
                api_key="gem-key",
                model_name="gemini-2.5-flash",
            )
            assert client.provider_name == "gemini"

            client.switch_provider("grok", api_key="xai-key", model_name="grok-2-latest")
            assert client.provider_name == "grok"
            assert client.model_name == "grok-2-latest"
            assert isinstance(client.provider, GrokProvider)


class TestConfigMultiProvider:
    """Tests for GodModeConfig multi-provider properties and validation."""

    def test_config_active_properties_gemini(self):
        cfg = GodModeConfig(
            ai_provider="gemini",
            gemini_api_key="gemini-123",
            gemini_model="gemini-2.5-flash",
            grok_api_key="xai-456",
            grok_model="grok-2-latest",
        )
        assert cfg.active_api_key == "gemini-123"
        assert cfg.active_model == "gemini-2.5-flash"
        assert cfg.is_ai_configured is True

    def test_config_active_properties_grok(self):
        cfg = GodModeConfig(
            ai_provider="grok",
            gemini_api_key="gemini-123",
            gemini_model="gemini-2.5-flash",
            grok_api_key="xai-456",
            grok_model="grok-2-latest",
        )
        assert cfg.active_api_key == "xai-456"
        assert cfg.active_model == "grok-2-latest"
        assert cfg.is_ai_configured is True

    def test_config_validation_grok_unconfigured(self):
        cfg = GodModeConfig(
            ai_provider="grok",
            grok_api_key="",
        )
        issues = cfg.validate()
        assert any("Grok API key" in issue for issue in issues)
