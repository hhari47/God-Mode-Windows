"""
Configuration manager for GodMode.

Loads settings from .env file and provides validated access to all configuration
values. Enforces privacy constraints (e.g., screen content logging is always disabled).
"""

import os
import logging
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


@dataclass
class GodModeConfig:
    """Immutable application configuration loaded from .env file."""

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"

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
    def is_tesseract_configured(self) -> bool:
        """Check if Tesseract binary exists at configured path."""
        return Path(self.tesseract_path).is_file()

    def validate(self) -> list[str]:
        """Return list of configuration warnings/errors."""
        issues = []
        if not self.is_gemini_configured:
            issues.append(
                "Gemini API key not configured. Set GEMINI_API_KEY in .env file. "
                "Get your key at: https://aistudio.google.com/apikey"
            )
        if not self.is_tesseract_configured:
            issues.append(
                f"Tesseract not found at: {self.tesseract_path}. "
                "Screenshot OCR will be unavailable. "
                "Download from: https://github.com/UB-Mannheim/tesseract/wiki"
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
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
        tesseract_path=os.getenv(
            "TESSERACT_PATH", r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        ),
        blink_duration_ms=int(os.getenv("BLINK_DURATION_MS", "250")),
        enable_led_signal=os.getenv("ENABLE_LED_SIGNAL", "true").lower() == "true",
        enable_sound_signal=os.getenv("ENABLE_SOUND_SIGNAL", "false").lower() == "true",
        allow_single_stage_signal=os.getenv("ALLOW_SINGLE_STAGE_SIGNAL", "true").lower() == "true",
    )

    # Privacy enforcement: never log screen content regardless of env setting
    # (the field default is False and init=False prevents override)

    # Log validation issues
    issues = config.validate()
    for issue in issues:
        logger.warning("Config: %s", issue)

    return config
