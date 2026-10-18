"""
Gemini AI Client — Component 4 foundation.

Wraps the google-generativeai SDK for use by both the MCQ pipeline
and general text pipeline. Handles API key configuration, error handling,
and response parsing.
"""

import logging
from typing import Optional

import google.generativeai as genai

logger = logging.getLogger(__name__)


FALLBACK_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.8-flash",
]


class GeminiClient:
    """
    Wrapper around the Gemini API for structured question answering.

    Handles configuration, API calls, error handling, and automatic model fallback.
    Does not log question content (privacy).
    """

    def __init__(self, api_key: str, model_name: str = "gemini-3.5-flash-lite"):
        """
        Initialize Gemini client.

        Args:
            api_key: Gemini API key.
            model_name: Model identifier (default: gemini-3.5-flash-lite).
        """
        self.api_key = api_key
        self.model_name = model_name
        self.active_model_name = model_name
        self._configured = False
        self.last_error: Optional[str] = None

        if not api_key:
            logger.error("Gemini API key is empty")
            return

        try:
            genai.configure(api_key=api_key)
            self._model = genai.GenerativeModel(model_name)
            self._configured = True
            logger.info("Gemini client configured with model: %s", model_name)
        except Exception as e:
            self.last_error = str(e)
            logger.error("Failed to configure Gemini client: %s", e)

    @property
    def is_ready(self) -> bool:
        """Check if client is properly configured."""
        return self._configured

    def generate(self, prompt: str, temperature: float = 0.1) -> Optional[str]:
        """
        Send a prompt to Gemini and return the text response.
        Automatically falls back to alternate models if quota (429) or model unavailability occurs.

        Args:
            prompt: The full prompt text.
            temperature: Sampling temperature (lower = more deterministic).

        Returns:
            Response text, or None on failure.

        Note:
            Prompt content is not logged (privacy). Only metadata is logged.
        """
        self.last_error = None
        if not self._configured:
            self.last_error = "Gemini client not configured"
            logger.error("Gemini client not configured — cannot generate")
            return None

        # Build candidate list: active model first, then configured model, then fallbacks
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
