"""
Configuration manager for GodMode.

Loads settings from .env file and provides validated access to all configuration
values. Enforces privacy constraints (e.g., screen content logging is always disabled).
Supports multi-provider AI configurations (Google Gemini, xAI Grok).
"""

from __future__ import annotations
import os
import logging
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


@dataclass
class GodModeConfig:
    """Immutable application configuration loaded from .env file."""

    # Active AI Provider ('gemini' or 'grok')
    ai_provider: str = "gemini"

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"

    # xAI Grok
    grok_api_key: str = ""
    grok_model: str = "grok-2-latest"

    # Tesseract
    tesseract_path: str = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

    # Signal
    blink_duration_ms: int = 250
    enable_led_signal: bool = True
    enable_sound_signal: bool = False
    allow_single_stage_signal: bool = True

    # Privacy (enforced — cannot be overridden)
    log_screen_content: bool = field(default=False, init=False)

    @property
    def is_gemini_configured(self) -> bool:
        """Check if Gemini API key is set and non-placeholder."""
        return bool(self.gemini_api_key) and self.gemini_api_key != "your_api_key_here"

    @property
    def is_grok_configured(self) -> bool:
        """Check if Grok API key is set and non-placeholder."""
        return bool(self.grok_api_key) and self.grok_api_key != "your_grok_key_here"

    @property
    def is_ai_configured(self) -> bool:
        """Check if the currently selected AI provider is configured."""
        if self.ai_provider.lower() == "grok":
            return self.is_grok_configured
        return self.is_gemini_configured

    @property
    def active_api_key(self) -> str:
        """Get API key for active provider."""
        return self.grok_api_key if self.ai_provider.lower() == "grok" else self.gemini_api_key

    @property
    def active_model(self) -> str:
        """Get model for active provider."""
        return self.grok_model if self.ai_provider.lower() == "grok" else self.gemini_model

    @property
    def is_tesseract_configured(self) -> bool:
        """Check if Tesseract binary exists at configured path."""
        return Path(self.tesseract_path).is_file()

    @property
    def is_ocr_available(self) -> bool:
        """Check if any OCR engine is available (Windows Native OCR or Tesseract)."""
        try:
            import winocr
            return True
        except ImportError:
            pass
        return self.is_tesseract_configured

    def validate(self) -> list[str]:
        """Return list of configuration warnings/errors."""
        issues = []
        if self.ai_provider.lower() == "grok":
            if not self.is_grok_configured:
                issues.append(
                    "xAI Grok API key not configured. Set GROK_API_KEY in .env file or Settings tab. "
                    "Get your key at: https://console.x.ai"
                )
        else:
            if not self.is_gemini_configured:
                issues.append(
                    "Gemini API key not configured. Set GEMINI_API_KEY in .env file or Settings tab. "
                    "Get your key at: https://aistudio.google.com/apikey"
                )

        if not self.is_ocr_available:
            issues.append(
                f"No OCR engine available. Install winocr ('pip install winocr') or "
                f"install Tesseract at {self.tesseract_path}."
            )
        return issues


def load_config(env_path: str | None = None) -> GodModeConfig:
    """
    Load configuration from .env file.

    Args:
        env_path: Optional explicit path to .env file. If None, searches
                  the project root directory.

    Returns:
        Validated GodModeConfig instance.
    """
    # Find .env file
    if env_path:
        load_dotenv(env_path)
    else:
        # Search from project root
        project_root = Path(__file__).parent.parent
        env_file = project_root / ".env"
        if env_file.exists():
            load_dotenv(env_file)
        else:
            logger.warning(
                "No .env file found at %s. Copy .env.example to .env and configure.",
                env_file,
            )

    config = GodModeConfig(
        ai_provider=os.getenv("AI_PROVIDER", "gemini"),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
        grok_api_key=os.getenv("GROK_API_KEY", ""),
        grok_model=os.getenv("GROK_MODEL", "grok-2-latest"),
        tesseract_path=os.getenv(
            "TESSERACT_PATH", r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        ),
        blink_duration_ms=int(os.getenv("BLINK_DURATION_MS", "250")),
        enable_led_signal=os.getenv("ENABLE_LED_SIGNAL", "true").lower() == "true",
        enable_sound_signal=os.getenv("ENABLE_SOUND_SIGNAL", "true").lower() == "true",
        allow_single_stage_signal=os.getenv("ALLOW_SINGLE_STAGE_SIGNAL", "true").lower() == "true",
    )

    # Privacy enforcement: never log screen content regardless of env setting
    # (the field default is False and init=False prevents override)

    # Log validation issues
    issues = config.validate()
    for issue in issues:
        logger.warning("Config: %s", issue)

    return config
