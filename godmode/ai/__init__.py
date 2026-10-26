"""
AI Integration Layer for GodMode.

Supports multi-provider AI routing including Google Gemini and xAI Grok.
Provides unified generation, automatic model fallbacks, and error normalization.
"""

from godmode.ai.providers import (
    BaseAIProvider,
    GeminiProvider,
    GrokProvider,
    AIProviderError,
    AuthenticationError,
    QuotaExceededError,
    ModelNotFoundError,
    ProviderRegistry,
    get_provider_registry,
)
from godmode.ai.client import UnifiedAIClient, GeminiClient

__all__ = [
    "BaseAIProvider",
    "GeminiProvider",
    "GrokProvider",
    "AIProviderError",
    "AuthenticationError",
    "QuotaExceededError",
    "ModelNotFoundError",
    "ProviderRegistry",
    "get_provider_registry",
    "UnifiedAIClient",
    "GeminiClient",
]
