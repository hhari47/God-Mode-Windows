"""
Multi-Provider AI Architecture for GodMode.

Defines a modular provider interface and implementations for:
- Google Gemini (google-generativeai SDK)
- xAI Grok (xAI REST API, OpenAI-compatible)
"""

from __future__ import annotations
import abc
import json
import logging
import urllib.request
import urllib.error
from typing import Optional

logger = logging.getLogger(__name__)


class AIProviderError(Exception):
    """Base exception for AI provider errors."""
    def __init__(self, message: str, provider: str = "", status_code: Optional[int] = None, retryable: bool = False):
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.status_code = status_code
        self.retryable = retryable


class AuthenticationError(AIProviderError):
    """Invalid or missing API key."""
    pass


class QuotaExceededError(AIProviderError):
    """Rate limit or quota exhausted."""
    def __init__(self, message: str, provider: str = ""):
        super().__init__(message, provider=provider, status_code=429, retryable=True)


class ModelNotFoundError(AIProviderError):
    """Requested model not supported or unavailable."""
    pass


class BaseAIProvider(abc.ABC):
    """Abstract base class for AI providers."""

    @property
    @abc.abstractmethod
    def provider_id(self) -> str:
        """Machine identifier (e.g. 'gemini', 'grok')."""
        pass

    @property
    def provider_name(self) -> str:
        """Alias for provider_id for backward compatibility."""
        return self.provider_id

    @property
    @abc.abstractmethod
    def display_name(self) -> str:
        """Human-readable name."""
        pass

    @abc.abstractmethod
    def is_configured(self) -> bool:
        """Check if provider credentials are set."""
        pass

    @abc.abstractmethod
    def list_models(self) -> list[str]:
        """Return list of supported models."""
        pass

    @abc.abstractmethod
    def default_model(self) -> str:
        """Return default model identifier."""
        pass

    @abc.abstractmethod
    def validate_credentials(self) -> tuple[bool, str]:
        """
        Validate credentials by making a lightweight test call or checking key format.
        Returns (is_valid, message).
        """
        pass

    @abc.abstractmethod
    def generate(self, prompt: str, model: Optional[str] = None, temperature: float = 0.1) -> str:
        """
        Generate text response for prompt.
        Raises AIProviderError subclasses on failure.
        """
        pass


class GeminiProvider(BaseAIProvider):
    """Google Gemini AI Provider."""

    MODELS = [
        "gemini-3.5-flash-lite",
        "gemini-3.8-flash",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
    ]

    def __init__(self, api_key: str = "", model_name: str = "gemini-3.5-flash-lite"):
        self.api_key = api_key.strip() if api_key else ""
        self.model_name = model_name or "gemini-3.5-flash-lite"
        self._sdk_configured = False
        self._init_sdk()

    def _init_sdk(self) -> None:
        if self.api_key and self.api_key != "your_api_key_here":
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                self._sdk_configured = True
            except Exception as e:
                logger.debug("Gemini SDK configuration warning: %s", e)
                self._sdk_configured = False

    @property
    def provider_id(self) -> str:
        return "gemini"

    @property
    def display_name(self) -> str:
        return "Google Gemini"

    def is_configured(self) -> bool:
        return bool(self.api_key) and self.api_key != "your_api_key_here"

    def list_models(self) -> list[str]:
        return list(self.MODELS)

    def default_model(self) -> str:
        return "gemini-3.5-flash-lite"

    def validate_credentials(self) -> tuple[bool, str]:
        if not self.is_configured():
            return False, "Gemini API key is not configured"
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(self.model_name)
            # Lightweight test prompt
            resp = model.generate_content("Ping", generation_config={"max_output_tokens": 5})
            if resp and resp.text:
                return True, f"Successfully connected to Gemini ({self.model_name})"
            return False, "Gemini returned empty response during validation"
        except Exception as e:
            err = str(e)
            if "API_KEY_INVALID" in err or "400" in err:
                return False, "Invalid Gemini API key"
            if "429" in err or "ResourceExhausted" in err:
                return False, "Gemini rate limit or quota exceeded"
            return False, f"Gemini connection failed: {err}"

    def generate(self, prompt: str, model: Optional[str] = None, temperature: float = 0.1) -> str:
        if not self.is_configured():
            raise AuthenticationError("Gemini API key is not configured", provider="gemini")

        target_model = model or self.model_name
        import google.generativeai as genai
        genai.configure(api_key=self.api_key)

        models_to_try = [target_model]
        for m in self.MODELS:
            if m not in models_to_try:
                models_to_try.append(m)

        last_exc: Optional[Exception] = None
        for candidate in models_to_try:
            try:
                m = genai.GenerativeModel(candidate)
                resp = m.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=temperature,
                        max_output_tokens=2048,
                    ),
                )
                if resp and resp.text:
                    return resp.text.strip()
                if resp and resp.prompt_feedback and getattr(resp.prompt_feedback, "block_reason", None):
                    raise AIProviderError(f"Gemini blocked response: {resp.prompt_feedback.block_reason}", provider="gemini")
            except Exception as e:
                err_str = str(e)
                last_exc = e
                if "API_KEY_INVALID" in err_str:
                    raise AuthenticationError("Invalid Gemini API key", provider="gemini", status_code=401)
                is_quota = "429" in err_str or "ResourceExhausted" in err_str or "quota" in err_str.lower()
                is_404 = "404" in err_str or "NotFound" in err_str
                if (is_quota or is_404) and candidate != models_to_try[-1]:
                    logger.warning("Gemini model '%s' quota or availability error. Trying fallback '%s'...", candidate, models_to_try[models_to_try.index(candidate) + 1])
                    continue
                if is_quota:
                    raise QuotaExceededError(f"Gemini quota exceeded: {err_str}", provider="gemini")
                raise AIProviderError(f"Gemini error: {err_str}", provider="gemini")

        raise AIProviderError(f"Gemini all models failed: {last_exc}", provider="gemini")


class GrokProvider(BaseAIProvider):
    """
    xAI Grok Provider using the official xAI REST API (OpenAI-compatible).
    Endpoint: https://api.x.ai/v1/chat/completions
    """

    BASE_URL = "https://api.x.ai/v1/chat/completions"

    MODELS = [
        "grok-2-latest",
        "grok-2-1212",
        "grok-beta",
        "grok-vision-beta",
        "grok-2-vision-1212",
    ]

    def __init__(self, api_key: str = "", model_name: str = "grok-2-latest"):
        self.api_key = api_key.strip() if api_key else ""
        self.model_name = model_name or "grok-2-latest"

    @property
    def provider_id(self) -> str:
        return "grok"

    @property
    def display_name(self) -> str:
        return "xAI Grok"

    def is_configured(self) -> bool:
        return bool(self.api_key) and self.api_key != "your_grok_key_here"

    def list_models(self) -> list[str]:
        return list(self.MODELS)

    def default_model(self) -> str:
        return "grok-2-latest"

    def validate_credentials(self) -> tuple[bool, str]:
        if not self.is_configured():
            return False, "Authentication failed: Grok API key is not configured"
        try:
            # Send a minimal test message
            self.generate("Hello", model=self.model_name, temperature=0.1)
            return True, f"Connected successfully to xAI Grok ({self.model_name})"
        except AuthenticationError as e:
            return False, f"Authentication failed: {e.message}"
        except QuotaExceededError as e:
            return False, f"Rate limit or quota exceeded: {e.message}"
        except Exception as e:
            return False, f"xAI Grok connection failed: {e}"

    def generate(self, prompt: str, model: Optional[str] = None, temperature: float = 0.1) -> str:
        if not self.is_configured():
            raise AuthenticationError("xAI Grok API key is not configured", provider="grok")

        target_model = model or self.model_name

        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "model": target_model,
            "temperature": temperature,
            "max_tokens": 2048,
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.BASE_URL,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": "GodMode-Windows/1.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8")
                parsed = json.loads(body)
                choices = parsed.get("choices", [])
                if choices and len(choices) > 0:
                    msg = choices[0].get("message", {})
                    content = msg.get("content", "")
                    if content and content.strip():
                        return content.strip()
                raise AIProviderError("xAI Grok returned empty choices in response", provider="grok")

        except urllib.error.HTTPError as e:
            err_msg = ""
            try:
                err_body = e.read().decode("utf-8")
                err_json = json.loads(err_body)
                err_msg = err_json.get("error", {}).get("message", err_body)
            except Exception:
                err_msg = str(e)

            if e.code == 401:
                raise AuthenticationError(f"Authentication failed: {err_msg}", provider="grok", status_code=401)
            elif e.code == 429:
                raise QuotaExceededError(f"Rate limit or quota exceeded: {err_msg}", provider="grok")
            elif e.code == 404 or (e.code == 400 and "model" in err_msg.lower()):
                raise ModelNotFoundError(f"Model not found: {err_msg}", provider="grok", status_code=e.code)
            else:
                raise AIProviderError(f"xAI Grok HTTP {e.code}: {err_msg}", provider="grok", status_code=e.code)

        except urllib.error.URLError as e:
            raise AIProviderError(f"xAI Grok network error: {e.reason}", provider="grok")
        except TimeoutError:
            raise AIProviderError("xAI Grok request timed out after 30s", provider="grok")
        except json.JSONDecodeError as e:
            raise AIProviderError(f"xAI Grok returned malformed JSON: {e}", provider="grok")


class ProviderRegistry:
    """Registry managing available AI providers and model mappings."""

    _PROVIDERS = ["gemini", "grok"]

    def __init__(self):
        self._providers: dict[str, BaseAIProvider] = {}

    def register(self, provider: BaseAIProvider) -> None:
        self._providers[provider.provider_id.lower()] = provider

    def get(self, provider_id: str) -> Optional[BaseAIProvider]:
        return self._providers.get(provider_id.lower())

    @classmethod
    def list_providers(cls) -> list[str]:
        """Return list of supported provider IDs."""
        return list(cls._PROVIDERS)

    @classmethod
    def create(cls, provider_name: str, api_key: str = "", model_name: str = "") -> BaseAIProvider:
        """Factory method to instantiate a provider by name."""
        name = (provider_name or "").lower().strip()
        if name == "gemini":
            return GeminiProvider(api_key=api_key, model_name=model_name or "gemini-3.5-flash-lite")
        elif name == "grok":
            return GrokProvider(api_key=api_key, model_name=model_name or "grok-2-latest")
        else:
            raise AIProviderError(f"Unknown AI provider: '{provider_name}'", provider=provider_name)


_default_registry: Optional[ProviderRegistry] = None


def get_provider_registry(
    gemini_key: str = "",
    gemini_model: str = "gemini-3.5-flash-lite",
    grok_key: str = "",
    grok_model: str = "grok-2-latest",
) -> ProviderRegistry:
    """Get or create singleton provider registry with configured providers."""
    global _default_registry
    registry = ProviderRegistry()
    registry.register(GeminiProvider(api_key=gemini_key, model_name=gemini_model))
    registry.register(GrokProvider(api_key=grok_key, model_name=grok_model))
    _default_registry = registry
    return registry
