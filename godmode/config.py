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

    # Desktop & UI Settings
    theme_mode: str = "dark"                   # "dark", "light", "system"
    start_minimized: bool = False              # Start minimized in system tray
    minimize_to_tray: bool = True              # Minimize to tray instead of quitting on window close
    auto_copy_answer: bool = False             # Copy answer to clipboard when solved
    window_geometry: str = "1020x720"          # Saved window size/position

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


def resolve_config_path(explicit_path: str | Path | None = None) -> Path:
    """Resolve the active .env configuration file path."""
    if explicit_path:
        return Path(explicit_path)

    # 1. Project root .env (portable mode / dev mode)
    project_root = Path(__file__).parent.parent
    root_env = project_root / ".env"
    if root_env.exists():
        return root_env

    # 2. Check AppData for installed / packaged execution
    appdata = os.getenv("APPDATA")
    if appdata:
        appdata_env = Path(appdata) / "GodMode" / ".env"
        if appdata_env.exists():
            return appdata_env

    # If writable, default to project root; otherwise AppData
    try:
        root_env.touch(exist_ok=True)
        return root_env
    except (PermissionError, OSError):
        if appdata:
            dir_path = Path(appdata) / "GodMode"
            dir_path.mkdir(parents=True, exist_ok=True)
            return dir_path / ".env"

    return root_env


def load_config(env_path: str | Path | None = None) -> GodModeConfig:
    """
    Load configuration from .env file.

    Args:
        env_path: Optional explicit path to .env file.

    Returns:
        Validated GodModeConfig instance.
    """
    target_env = resolve_config_path(env_path)
    if target_env.exists():
        load_dotenv(target_env, override=True)
    else:
        logger.warning("No .env file found at %s. Defaults applied.", target_env)

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
        theme_mode=os.getenv("THEME_MODE", "dark"),
        start_minimized=os.getenv("START_MINIMIZED", "false").lower() == "true",
        minimize_to_tray=os.getenv("MINIMIZE_TO_TRAY", "true").lower() == "true",
        auto_copy_answer=os.getenv("AUTO_COPY_ANSWER", "false").lower() == "true",
        window_geometry=os.getenv("WINDOW_GEOMETRY", "1020x720"),
    )

    # Privacy enforcement: never log screen content regardless of env setting
    # (the field default is False and init=False prevents override)

    # Log validation issues
    issues = config.validate()
    for issue in issues:
        logger.warning("Config: %s", issue)

    return config


def save_config(config: GodModeConfig, target_path: str | Path | None = None) -> bool:
    """
    Save GodModeConfig to .env file cleanly, preserving comments if present.
    """
    env_file = resolve_config_path(target_path)
    try:
        env_file.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        if env_file.exists():
            with open(env_file, "r", encoding="utf-8") as f:
                lines = f.readlines()

        kv_map = {
            "AI_PROVIDER": config.ai_provider,
            "GEMINI_API_KEY": config.gemini_api_key,
            "GEMINI_MODEL": config.gemini_model,
            "GROK_API_KEY": config.grok_api_key,
            "GROK_MODEL": config.grok_model,
            "TESSERACT_PATH": config.tesseract_path,
            "BLINK_DURATION_MS": str(config.blink_duration_ms),
            "ENABLE_LED_SIGNAL": "true" if config.enable_led_signal else "false",
            "ENABLE_SOUND_SIGNAL": "true" if config.enable_sound_signal else "false",
            "ALLOW_SINGLE_STAGE_SIGNAL": "true" if config.allow_single_stage_signal else "false",
            "THEME_MODE": config.theme_mode,
            "START_MINIMIZED": "true" if config.start_minimized else "false",
            "MINIMIZE_TO_TRAY": "true" if config.minimize_to_tray else "false",
            "AUTO_COPY_ANSWER": "true" if config.auto_copy_answer else "false",
            "WINDOW_GEOMETRY": config.window_geometry,
        }

        updated_keys = set()
        new_lines: list[str] = []

        for line in lines:
            trimmed = line.strip()
            if trimmed.startswith("#") or not trimmed or "=" not in trimmed:
                new_lines.append(line)
                continue

            key = trimmed.split("=", 1)[0].strip()
            if key in kv_map:
                new_lines.append(f"{key}={kv_map[key]}\n")
                updated_keys.add(key)
            else:
                new_lines.append(line)

        # Append any missing keys
        for key, val in kv_map.items():
            if key not in updated_keys:
                new_lines.append(f"{key}={val}\n")

        with open(env_file, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        logger.info("Configuration saved successfully to %s", env_file)
        return True
    except Exception as e:
        logger.error("Failed to save configuration to %s: %s", env_file, e)
        return False
