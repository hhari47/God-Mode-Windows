"""
Unified AI Client for GodMode.

Wraps AI providers (Gemini, Grok) with automatic fallback, error normalization,
and seamless model switching. Maintains 100% backward compatibility with GeminiClient.
"""

from __future__ import annotations
import logging
import warnings
from typing import Optional, Any

# Suppress upstream SDK deprecation warning
warnings.filterwarnings("ignore", category=FutureWarning)
import google.generativeai as genai

from godmode.ai.providers import (
    BaseAIProvider,
    GeminiProvider,
    GrokProvider,
    AIProviderError,
    AuthenticationError,
    QuotaExceededError,
    ModelNotFoundError,
    ProviderRegistry,
)

logger = logging.getLogger(__name__)

FALLBACK_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.8-flash",
]


class UnifiedAIClient:
    """
    Unified AI client coordinating between different providers and models.
    Fully compatible drop-in replacement for GeminiClient.
    """

    def __init__(
        self,
        api_key: str = "",
        model_name: str = "gemini-3.5-flash-lite",
        provider_name: str = "gemini",
        registry: Optional[ProviderRegistry] = None,
    ):
        self.provider_name = (provider_name or "gemini").lower()
        self.api_key = api_key or ""
        self.model_name = model_name or ("grok-2-latest" if self.provider_name == "grok" else "gemini-3.5-flash-lite")
        self.active_model_name = self.model_name
        self._configured = False
        self.last_error: Optional[str] = None
        self._registry = registry
        self.provider: Optional[BaseAIProvider] = None
        self._model = None

        self._init_provider()

    def _init_provider(self) -> None:
        self.last_error = None
        if self.provider_name == "grok":
            self.provider = GrokProvider(api_key=self.api_key, model_name=self.model_name)
            self._configured = self.provider.is_configured()
            logger.info("Unified AI Client configured with Grok (model: %s)", self.model_name)
            return

        # Default: Gemini
        self.provider = GeminiProvider(api_key=self.api_key, model_name=self.model_name)
        if not self.api_key:
            self._configured = False
            logger.error("Gemini API key is empty")
            return

        try:
            genai.configure(api_key=self.api_key)
            self._model = genai.GenerativeModel(self.model_name)
            self._configured = True
            logger.info("Gemini client configured with model: %s", self.model_name)
        except Exception as e:
            self.last_error = str(e)
            self._configured = False
            logger.error("Failed to configure Gemini client: %s", e)

    def switch_provider(self, provider_name: str, api_key: str = "", model_name: str = "") -> None:
        """Switch active AI provider and model at runtime."""
        self.provider_name = (provider_name or "gemini").lower()
        if api_key:
            self.api_key = api_key
        if model_name:
            self.model_name = model_name
        else:
            self.model_name = "grok-2-latest" if self.provider_name == "grok" else "gemini-3.5-flash-lite"
        self.active_model_name = self.model_name
        self._init_provider()

    @property
    def is_ready(self) -> bool:
        """Check if client is properly configured."""
        return self._configured

    def generate(self, prompt: str, temperature: float = 0.1) -> Optional[str]:
        """
        Send a prompt to the active AI provider and return the normalized response text.
        Returns None on failure and stores the normalized message in self.last_error.
        """
        self.last_error = None
        if not self._configured:
            prov = "xAI Grok" if self.provider_name == "grok" else "Gemini"
            self.last_error = f"{prov} client not configured"
            logger.error("%s — cannot generate", self.last_error)
            return None

        # Grok provider execution
        if self.provider_name == "grok" and self.provider:
            try:
                resp = self.provider.generate(prompt=prompt, model=self.model_name, temperature=temperature)
                return resp
            except AuthenticationError as e:
                self.last_error = f"Authentication Error: {e.message}"
                return None
            except QuotaExceededError as e:
                self.last_error = f"Rate Limit / Quota Exceeded (429): {e.message}"
                return None
            except ModelNotFoundError as e:
                self.last_error = f"Model Unavailable: {e.message}"
                return None
            except AIProviderError as e:
                self.last_error = f"Provider Error: {e.message}"
                return None
            except Exception as e:
                self.last_error = f"Unexpected Error: {e}"
                return None

        # Gemini provider execution with automatic model fallback
        models_to_try = [self.active_model_name]
        for m in [self.model_name] + FALLBACK_MODELS:
            if m not in models_to_try:
                models_to_try.append(m)

        for candidate in models_to_try:
            try:
                logger.debug("Sending request to Gemini (%s, %d chars prompt)", candidate, len(prompt))

                model = genai.GenerativeModel(candidate)
                response = model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=temperature,
                        max_output_tokens=2048,
                    ),
                )

                if response and response.text:
                    if candidate != self.model_name:
                        logger.info(
                            "Gemini fallback succeeded with %s (requested: %s)",
                            candidate,
                            self.model_name,
                        )
                    self.active_model_name = candidate
                    self._model = model
                    logger.debug("Gemini response received (%d chars)", len(response.text))
                    return response.text.strip()

                # Check for blocked responses
                if response and response.prompt_feedback:
                    block_reason = getattr(response.prompt_feedback, "block_reason", None)
                    if block_reason:
                        self.last_error = f"Gemini blocked response: {block_reason}"
                        logger.warning("Gemini blocked response: %s", block_reason)
                        return None

                self.last_error = "Gemini returned empty response"
                logger.warning("Gemini returned empty response on model %s", candidate)
                continue

            except Exception as e:
                err_str = str(e)
                self.last_error = err_str
                is_retryable = (
                    "429" in err_str
                    or "ResourceExhausted" in err_str
                    or "quota" in err_str.lower()
                    or "404" in err_str
                    or "NotFound" in err_str
                )
                if is_retryable and candidate != models_to_try[-1]:
                    logger.warning(
                        "Gemini model '%s' quota exceeded or unavailable. Automatically falling back...",
                        candidate,
                    )
                    continue

                logger.error("Gemini API call failed (%s) on %s: %s", type(e).__name__, candidate, e)
                continue

        return None

    def generate_content(self, prompt: str, **kwargs) -> Any:
        """
        Generate content returning an object with a .text attribute.
        Compatible with Google Gemini GenerativeModel response structure.
        """
        text = self.generate(prompt)
        return type("AIContentResponse", (), {"text": text or ""})()


# Backward-compatible alias
GeminiClient = UnifiedAIClient
